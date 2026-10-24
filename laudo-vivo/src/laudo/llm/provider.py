"""Provedores de LLM do Laudo Vivo.

- `OllamaProvider`: cliente HTTP do Ollama (`/api/chat`) com tools nativas, saída estruturada (`format` com
  JSON Schema), timeouts, 2 retentativas com backoff (5xx e conexão; **TIMEOUT não é repetido**: com
  temperatura 0, um modelo que não respondeu em 120 s não responde na segunda vez, e o fiscal fica
  esperando), `keep_alive`, seleção de modelo por perfil e **injeção da data de hoje** no prompt de sistema
  (o modelo inventa datas).
- Orçamento de LLM por turno: no perfil `campo` (palco da demo e app no campo) o condutor abre
  `orcamento_do_turno()` e o tempo somado das chamadas do turno não passa de `ORCAMENTO_TURNO_S` (o timeout
  de leitura de cada chamada é o que sobra); estourou, a chamada falha como TIMEOUT sem ir ao servidor e o
  condutor segue com o plano mínimo e a fala por template. `espera_disjuntor_s` diz ao condutor por quanto
  tempo deixar o LLM de fora depois de um TIMEOUT ou de o servidor sumir (disjuntor). Escritório e lote
  (avaliação): sem orçamento nem disjuntor.
- `Gravador` + `ReplayProvider`: grava pares requisição→resposta em JSONL e os reproduz sem GPU (CI e demo
  de contingência). A chave de replay é o hash canônico da requisição *antes* da injeção da data e depois do
  mascaramento de PII, então o replay funciona em outro dia e a gravação não guarda CPF/telefone.
- `ProvedorRoteirizado`: respostas fixas ou geradas por função (testes e demo sem modelo).
- `VertexProvider` + `ProvedorEmCadeia`: só na demo pública na nuvem (infra/nuvem). Os passos gravados saem do
  replay, sem custo; o texto livre vai ao Gemini do Vertex AI (`externo=True`, com teto diário de tokens); se
  nenhum responder, o condutor segue com o plano mínimo e a fala por template.

Interface: qualquer objeto com `nome`, `modelo`, `externo` e `chat(...) -> RespostaLLM` serve
(`ProvedorLLM`). Um provedor externo (`externo=True`, como o `VertexProvider`) faz o condutor mascarar PII
antes de enviar. O produto em campo usa só modelo local.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import httpx
from pydantic import BaseModel, Field, ValidationError

from laudo.agent.pii import mascarar, mascarar_obj
from laudo.audit import otel
from laudo.contracts import hash_entrada

# ---------------------------------------------------------------------------
# Perfis de execução. Escolha do modelo (bake-off) em docs/adr/001-modelo-local.md.
# ---------------------------------------------------------------------------

PERFIS: dict[str, str] = {
    "campo": "qwen3.5:4b",
    "escritorio": "qwen3.5:4b",  # alternativa: qwen3:14b (sem ASR na GPU); ver ADR 001
    "lote": "qwen3:14b",
}
URL_PADRAO = "http://127.0.0.1:11434"


def url_ollama(base_url: str | None = None) -> str:
    """URL do Ollama: `base_url`, senão `OLLAMA_HOST` (como o próprio `ollama serve` lê), senão a porta padrão.
    Sem esquema, vira `http://` ("127.0.0.1:11435" → "http://127.0.0.1:11435"); a barra final sai. Lida a cada
    chamada: o condutor, o VLM (classificação de foto) e a leitura de documento usam o mesmo servidor."""
    url = (base_url or os.environ.get("OLLAMA_HOST") or URL_PADRAO).strip().rstrip("/")
    return url if url.startswith("http") else "http://" + url


# Janela de contexto única do Ollama, usada pelo condutor, pelos leitores de foto (VLM), pelo aquecimento e
# pela avaliação. Com outro valor, o Ollama recarrega o modelo, o que leva de 15 a 20 s.
# 16384 porque, no modo real, o 1º pedido do condutor tem cerca de 9.300 tokens e os outros chegam a 8.047:
# com 8192, o Ollama cortaria o 1º para 4.098 (`truncating input prompt`), perdendo o começo do prompt de
# sistema, e os outros ficariam sem folga para a resposta.
NUM_CTX = 16384
OPCOES_PADRAO: dict[str, Any] = {"temperature": 0, "seed": 42, "num_ctx": NUM_CTX}


def assinatura_corte(num_ctx: int, manter: int = 4) -> int:
    """Tamanho do prompt (em tokens) que o Ollama 0.32 devolve quando corta um prompt maior que `num_ctx`.
    O valor é `(num_ctx - keep) // 2 + keep`, com `--keep 4`: dá 4098 para 8192 e 8194 para 16384.
    Um `prompt_eval_count` igual a ele quer dizer que o modelo não viu o prompt inteiro."""
    return (num_ctx - manter) // 2 + manter
# Orçamento de LLM por turno (s), por perfil. Só o perfil de palco tem: nas gravações da demo (76 chamadas)
# a mediana foi 0,9 s e a maior 4,4 s, com carga do modelo frio de até 3,7 s; 25 s cobrem um turno de até
# 5 passos e cortam um Ollama travado, que sem orçamento seguraria o turno por 6 a 12 min
# (120 s de timeout x 3 tentativas x até 2 chamadas).
# `LAUDO_ORCAMENTO_TURNO_S` sobrepõe (0 desliga).
ORCAMENTO_TURNO_S: dict[str, float] = {"campo": 25.0}
# Disjuntor: depois de TIMEOUT ou servidor fora, o condutor deixa o LLM de fora por este tempo (s) e tenta de
# novo no primeiro turno depois dele. Só vale com orçamento (perfil de palco).
ESPERA_DISJUNTOR_S = 60.0
_DO_PERFIL = "perfil"

_DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
_MESES = [
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
]
MARCADOR_DATA = "[data de referência]"


def modelo_do_perfil(perfil: str = "escritorio") -> str:
    """Modelo do perfil, com sobreposição por variável de ambiente
    (`LAUDO_MODELO` ou `LAUDO_MODELO_<PERFIL>`)."""
    if perfil not in PERFIS:
        raise ValueError(f"perfil desconhecido: {perfil} (use {sorted(PERFIS)})")
    return (
        os.environ.get(f"LAUDO_MODELO_{perfil.upper()}") or os.environ.get("LAUDO_MODELO") or PERFIS[perfil]
    )


def orcamento_do_perfil(perfil: str = "escritorio") -> float | None:
    """Orçamento de LLM por turno (s) do perfil; `LAUDO_ORCAMENTO_TURNO_S` sobrepõe (0 desliga)."""
    bruto = os.environ.get("LAUDO_ORCAMENTO_TURNO_S")
    if bruto is not None and bruto.strip():
        try:
            v = float(bruto.replace(",", "."))
        except ValueError as e:
            raise ValueError(f"LAUDO_ORCAMENTO_TURNO_S inválido: {bruto!r}") from e
        return v if v > 0 else None
    return ORCAMENTO_TURNO_S.get(perfil)


def linha_data(hoje: date) -> str:
    return (
        f"{MARCADOR_DATA} Hoje é {_DIAS[hoje.weekday()]}, {hoje.day} de {_MESES[hoje.month - 1]} de "
        f"{hoje.year} ({hoje.isoformat()}). Use esta data como referência; não invente datas."
    )


def injetar_data(mensagens: list[dict[str, Any]], hoje: date) -> list[dict[str, Any]]:
    """Cópia das mensagens com a data de hoje no prompt de sistema (cria um se não houver)."""
    msgs = [dict(m) for m in mensagens]
    linha = linha_data(hoje)
    if msgs and msgs[0].get("role") == "system":
        conteudo = msgs[0].get("content") or ""
        if MARCADOR_DATA not in conteudo:
            msgs[0]["content"] = f"{linha}\n\n{conteudo}"
    else:
        msgs.insert(0, {"role": "system", "content": linha})
    return msgs


# ---------------------------------------------------------------------------
# Tipos
# ---------------------------------------------------------------------------


class ChamadaFerramenta(BaseModel):
    nome: str
    argumentos: dict[str, Any] = Field(default_factory=dict)


class RespostaLLM(BaseModel):
    conteudo: str = ""
    chamadas: list[ChamadaFerramenta] = Field(default_factory=list)
    pensamento: str = ""
    modelo: str = ""
    provedor: str = ""
    tokens_entrada: int = 0
    tokens_saida: int = 0
    latencia_ms: int = 0
    carga_ms: int = 0
    prompt_ms: int = 0  # Ollama prompt_eval_duration: processamento do prompt na GPU
    geracao_ms: int = 0  # Ollama eval_duration: geração dos tokens de saída
    tentativas: int = 1
    replay: bool = False
    span_id: str = ""


class ErroLLM(Exception):
    """Falha do provedor. `codigo` ∈ {TIMEOUT, INDISPONIVEL, HTTP, FORMATO, REPLAY_AUSENTE}."""

    def __init__(self, codigo: str, msg: str, retryable: bool = False):
        super().__init__(f"{codigo}: {msg}")
        self.codigo = codigo
        self.retryable = retryable


@runtime_checkable
class ProvedorLLM(Protocol):
    nome: str
    modelo: str
    externo: bool

    def chat(
        self,
        mensagens: list[dict[str, Any]],
        ferramentas: list[dict[str, Any]] | None = None,
        formato: dict[str, Any] | None = None,
        metadados: dict[str, Any] | None = None,
    ) -> RespostaLLM: ...


# ---------------------------------------------------------------------------
# Gravação e replay
# ---------------------------------------------------------------------------


def _msg_canonica(m: dict[str, Any]) -> dict[str, Any]:
    d: dict[str, Any] = {"role": m.get("role"), "content": m.get("content") or ""}
    if m.get("tool_calls"):
        d["tool_calls"] = m["tool_calls"]
    if m.get("tool_name"):
        d["tool_name"] = m["tool_name"]
    return d


def chave_requisicao(
    mensagens: list[dict[str, Any]], ferramentas: list[dict[str, Any]] | None, formato: dict[str, Any] | None
) -> str:
    """Hash canônico da requisição (sem a linha de data, com PII mascarada, independente do modelo)."""
    msgs = []
    for m in mensagens:
        c = _msg_canonica(m)
        if c["role"] == "system":
            c["content"] = "\n".join(
                linha for linha in c["content"].splitlines() if not linha.startswith(MARCADOR_DATA)
            ).strip()
        msgs.append(c)
    tools = sorted((t.get("function", {}).get("name", ""), hash_entrada(t)) for t in (ferramentas or []))
    return hash_entrada(mascarar_obj({"m": msgs, "t": tools, "f": formato}))


def tipo_requisicao(ferramentas: Any, formato: Any) -> str:
    return "formato" if formato else "tools" if ferramentas else "chat"


class Gravador:
    """Acrescenta pares requisição→resposta (mascarados) a um JSONL."""

    def __init__(self, caminho: str | Path):
        self.caminho = Path(caminho)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)

    def registrar(self, chave: str, requisicao: dict[str, Any], resposta: RespostaLLM) -> None:
        linha = {
            "chave": chave,
            "tipo": tipo_requisicao(requisicao.get("tools"), requisicao.get("format")),
            "requisicao": mascarar_obj(requisicao),
            "resposta": mascarar_obj(resposta.model_dump(mode="json")),
            "gravado_em": time.time(),
        }
        with open(self.caminho, "a", encoding="utf-8") as f:
            f.write(json.dumps(linha, ensure_ascii=False, default=str) + "\n")


class ReplayProvider:
    """Reproduz respostas gravadas, sem GPU.

    `modo="chave"`: casa pelo hash da requisição (cada gravação é usada uma vez, na ordem; se a mesma
    requisição se repetir além do gravado, repete a última). Com `sequencial_se_ausente=True`, uma requisição
    sem gravação recebe a próxima gravação ainda não usada **do mesmo tipo** (tools, formato ou chat); o
    número dessas substituições fica em `self.substituicoes`. `modo="sequencial"` ignora a chave."""

    externo = False

    def __init__(
        self,
        caminho: str | Path,
        modo: str = "chave",
        modelo: str | None = None,
        sequencial_se_ausente: bool = False,
    ):
        self.nome = "replay"
        self.caminho = Path(caminho)
        self.modo = modo
        self.sequencial_se_ausente = sequencial_se_ausente
        self._registros: list[dict[str, Any]] = []
        with open(self.caminho, encoding="utf-8") as f:
            for linha in f:
                if not linha.strip():
                    continue
                d = json.loads(linha)
                r = RespostaLLM.model_validate(d["resposta"])
                if modelo and r.modelo and r.modelo != modelo:
                    continue
                req = d.get("requisicao") or {}
                tipo = d.get("tipo") or tipo_requisicao(req.get("tools"), req.get("format"))
                self._registros.append({"chave": d["chave"], "tipo": tipo, "resposta": r, "usado": False})
        self.modelo = modelo or (self._registros[0]["resposta"].modelo if self._registros else "replay")
        self._cursor = 0
        self.substituicoes = 0

    def _proximo(self, cond) -> dict[str, Any] | None:
        for i in list(range(self._cursor, len(self._registros))) + list(range(self._cursor)):
            reg = self._registros[i]
            if not reg["usado"] and cond(reg):
                reg["usado"] = True
                self._cursor = i + 1
                return reg
        return None

    def chat(self, mensagens, ferramentas=None, formato=None, metadados=None) -> RespostaLLM:
        chave = chave_requisicao(mensagens, ferramentas, formato)
        tipo = tipo_requisicao(ferramentas, formato)
        reg = None
        if self.modo == "chave":
            reg = self._proximo(lambda x: x["chave"] == chave)
            if reg is None:
                usados = [x for x in self._registros if x["chave"] == chave]
                reg = usados[-1] if usados else None
        if reg is None and (self.modo == "sequencial" or self.sequencial_se_ausente):
            reg = self._proximo(lambda x: x["tipo"] == tipo)
            if reg is not None and self.modo == "chave":
                self.substituicoes += 1
        if reg is None:
            raise ErroLLM("REPLAY_AUSENTE", f"sem gravação para a requisição {chave}")
        r: RespostaLLM = reg["resposta"]
        with otel.span_llm(
            "replay", r.modelo or self.modelo, **{"llm.replay": True, "llm.chave": chave, **(metadados or {})}
        ) as s:
            # uso da gravação original (tokens e tempo de GPU medidos pelo Ollama quando foi gravada): o custo
            # por fiscalização (`scripts/custo_fiscalizacao.py`) sai igual ao da execução gravada
            otel.definir(
                s,
                **{
                    "gen_ai.usage.input_tokens": r.tokens_entrada,
                    "gen_ai.usage.output_tokens": r.tokens_saida,
                    "llm.latency_ms": r.latencia_ms,
                    "llm.load_ms": r.carga_ms,
                    "llm.prompt_eval_ms": r.prompt_ms,
                    "llm.eval_ms": r.geracao_ms,
                    "llm.uso_origem": "gravacao",
                },
            )
            return r.model_copy(update={"replay": True, "span_id": otel.id_span(s)})


class ProvedorRoteirizado:
    """Provedor falso: devolve respostas de uma lista (em ordem) ou de uma função
    `f(mensagens, ferramentas, formato) -> RespostaLLM | dict | str`. Guarda as chamadas para asserção."""

    externo = False

    def __init__(
        self,
        respostas: list[RespostaLLM | dict | str] | Callable[..., Any] | None = None,
        modelo: str = "roteiro",
    ):
        self.nome = "roteiro"
        self.modelo = modelo
        self._respostas = respostas if respostas is not None else []
        self.chamadas: list[dict[str, Any]] = []

    def chat(self, mensagens, ferramentas=None, formato=None, metadados=None) -> RespostaLLM:
        self.chamadas.append({"mensagens": mensagens, "ferramentas": ferramentas, "formato": formato})
        if callable(self._respostas):
            bruto = self._respostas(mensagens, ferramentas, formato)
        elif self._respostas:
            bruto = self._respostas.pop(0)
        else:
            raise ErroLLM("INDISPONIVEL", "roteiro esgotado")
        if isinstance(bruto, ErroLLM):
            raise bruto
        if isinstance(bruto, str):
            r = RespostaLLM(conteudo=bruto)
        elif isinstance(bruto, dict):
            r = RespostaLLM.model_validate(bruto)
        else:
            r = bruto
        with otel.span_llm("roteiro", self.modelo, **(metadados or {})) as s:
            return r.model_copy(
                update={"modelo": self.modelo, "provedor": "roteiro", "span_id": otel.id_span(s)}
            )


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------


class OllamaProvider:
    """Cliente do Ollama `/api/chat` (sem streaming)."""

    externo = False

    def __init__(
        self,
        modelo: str | None = None,
        perfil: str = "escritorio",
        base_url: str | None = None,
        timeout_s: float = 120.0,
        retentativas: int = 2,
        backoff_s: float = 1.0,
        keep_alive: str | int = "30m",
        think: bool = False,
        opcoes: dict[str, Any] | None = None,
        gravador: Gravador | None = None,
        hoje: date | None = None,
        cliente: httpx.Client | None = None,
        dormir: Callable[[float], None] = time.sleep,
        orcamento_turno_s: float | None | str = _DO_PERFIL,
        espera_disjuntor_s: float | None | str = _DO_PERFIL,
        relogio: Callable[[], float] = time.monotonic,
    ):
        self.nome = "ollama"
        self.perfil = perfil
        self.modelo = modelo or modelo_do_perfil(perfil)
        self.base_url = url_ollama(base_url)
        self.timeout_s = timeout_s
        self.timeout = httpx.Timeout(connect=5.0, read=timeout_s, write=30.0, pool=5.0)
        self.retentativas = retentativas
        self.backoff_s = backoff_s
        self.keep_alive = keep_alive
        self.think = think
        self.opcoes = {**OPCOES_PADRAO, **(opcoes or {})}
        self.gravador = gravador
        self.hoje = hoje
        self._cliente = cliente or httpx.Client(timeout=self.timeout)
        self._dormir = dormir
        self._relogio = relogio  # orçamento do turno (relógio virtual nos testes)
        self.orcamento_turno_s: float | None = (
            orcamento_do_perfil(perfil) if orcamento_turno_s == _DO_PERFIL
            else orcamento_turno_s  # type: ignore[assignment]
        )
        self.espera_disjuntor_s: float | None = (
            (ESPERA_DISJUNTOR_S if self.orcamento_turno_s else None)
            if espera_disjuntor_s == _DO_PERFIL
            else espera_disjuntor_s  # type: ignore[assignment]
        )
        self._restante_turno: float | None = None  # só dentro de `orcamento_do_turno()`

    # -- orçamento do turno --------------------------------------------------
    @contextmanager
    def orcamento_do_turno(self) -> Iterator[None]:
        """Abre o orçamento de LLM de um turno do condutor: o tempo somado das chamadas feitas dentro do bloco
        não passa de `orcamento_turno_s` (sem orçamento no perfil, nada muda). Fora do bloco não há limite."""
        anterior = self._restante_turno
        self._restante_turno = self.orcamento_turno_s
        try:
            yield
        finally:
            self._restante_turno = anterior

    def _restante(self, t0: float) -> float | None:
        """Segundos de orçamento que sobram nesta chamada (iniciada em `t0` no relógio do provedor)."""
        if self._restante_turno is None:
            return None
        return self._restante_turno - (self._relogio() - t0)

    def _erro_orcamento(self) -> ErroLLM:
        return ErroLLM(
            "TIMEOUT",
            f"orçamento de LLM do turno esgotado ({self.orcamento_turno_s:.0f} s): plano mínimo e template",
            retryable=False,
        )

    # -- utilidades ---------------------------------------------------------
    def disponivel(self) -> bool:
        try:
            return self._cliente.get(f"{self.base_url}/api/version", timeout=3.0).status_code == 200
        except httpx.HTTPError:
            return False

    def descarregar(self) -> bool:
        """Equivale a `ollama stop <modelo>`: pede keep_alive=0 para liberar a VRAM."""
        try:
            r = self._cliente.post(
                f"{self.base_url}/api/generate", json={"model": self.modelo, "keep_alive": 0}, timeout=30.0
            )
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def montar_requisicao(self, mensagens, ferramentas=None, formato=None) -> dict[str, Any]:
        corpo: dict[str, Any] = {
            "model": self.modelo,
            "messages": injetar_data(mensagens, self.hoje or datetime.now().astimezone().date()),
            "stream": False,
            "keep_alive": self.keep_alive,
            "think": self.think,
            "options": self.opcoes,
        }
        if ferramentas:
            corpo["tools"] = ferramentas
        if formato:
            corpo["format"] = formato
        return corpo

    # -- chamada ------------------------------------------------------------
    def chat(self, mensagens, ferramentas=None, formato=None, metadados=None) -> RespostaLLM:
        corpo = self.montar_requisicao(mensagens, ferramentas, formato)
        chave = chave_requisicao(mensagens, ferramentas, formato)
        attrs = {
            "gen_ai.request.temperature": self.opcoes.get("temperature"),
            "gen_ai.request.seed": self.opcoes.get("seed"),
            "llm.perfil": self.perfil,
            "llm.n_tools": len(ferramentas or []),
            "llm.formato": bool(formato),
            "llm.chave": chave,
            "llm.orcamento_restante_s": (
                round(self._restante_turno, 1) if self._restante_turno is not None else None
            ),
            **(metadados or {}),
        }
        with otel.span_llm("ollama", self.modelo, **attrs) as s:
            t0 = time.perf_counter()
            r0 = self._relogio()
            try:
                dados, tentativas = self._post_com_retentativa(corpo, s, r0)
            finally:
                if self._restante_turno is not None:
                    self._restante_turno -= self._relogio() - r0
            resp = self._parse(dados)
            resp.latencia_ms = int((time.perf_counter() - t0) * 1000)
            resp.tentativas = tentativas
            resp.span_id = otel.id_span(s)
            ctx = int(self.opcoes.get("num_ctx") or 0)
            if ctx and resp.tokens_entrada == assinatura_corte(ctx):
                # o Ollama não falha quando o prompt passa de num_ctx: corta e responde. Fica no trace e no stderr.
                otel.definir(s, **{"llm.prompt_cortado": True})
                print(f"AVISO: o Ollama cortou o prompt para {resp.tokens_entrada} tokens (num_ctx={ctx}); "
                      "aumente NUM_CTX em src/laudo/llm/provider.py", file=sys.stderr, flush=True)
            otel.definir(
                s,
                **{
                    "gen_ai.response.model": resp.modelo,
                    "gen_ai.usage.input_tokens": resp.tokens_entrada,
                    "gen_ai.usage.output_tokens": resp.tokens_saida,
                    "llm.latency_ms": resp.latencia_ms,
                    "llm.load_ms": resp.carga_ms,
                    "llm.prompt_eval_ms": resp.prompt_ms,
                    "llm.eval_ms": resp.geracao_ms,
                    "llm.uso_origem": "medido",
                    "llm.tentativas": tentativas,
                    "llm.n_tool_calls": len(resp.chamadas),
                },
            )
        if self.gravador:
            self.gravador.registrar(chave, corpo, resp)
        return resp

    def _timeout_da_tentativa(self, t0: float) -> httpx.Timeout:
        """Timeout da tentativa: o configurado, limitado pelo que sobra do orçamento do turno."""
        restante = self._restante(t0)
        if restante is None:
            return self.timeout
        if restante <= 0:
            raise self._erro_orcamento()
        return httpx.Timeout(
            connect=min(5.0, restante), read=min(self.timeout_s, restante), write=min(30.0, restante),
            pool=min(5.0, restante),
        )

    def _post_com_retentativa(
        self, corpo: dict[str, Any], s, t0: float | None = None
    ) -> tuple[dict[str, Any], int]:
        t0 = self._relogio() if t0 is None else t0
        ultimo: ErroLLM | None = None
        for tentativa in range(self.retentativas + 1):
            if tentativa:
                espera = self.backoff_s * (2 ** (tentativa - 1))
                restante = self._restante(t0)
                if restante is not None and espera >= restante:
                    break  # o orçamento do turno não cobre a espera e outra tentativa: fica o último erro
                self._dormir(espera)
            try:
                timeout = self._timeout_da_tentativa(t0)
            except ErroLLM as erro:
                otel.marcar_erro(s, str(erro))
                raise
            try:
                r = self._cliente.post(f"{self.base_url}/api/chat", json=corpo, timeout=timeout)
            except httpx.TimeoutException as e:
                # TIMEOUT não é repetido (temperatura 0: o modelo que não respondeu não responde na 2ª
                # vez; repetir só prende o fiscal). O condutor segue com o plano mínimo e o template.
                erro = ErroLLM("TIMEOUT", str(e) or "timeout", retryable=False)
                otel.marcar_erro(s, str(erro))
                raise erro from e
            except httpx.TransportError as e:
                ultimo = ErroLLM("INDISPONIVEL", str(e) or "falha de conexão", retryable=True)
                continue
            if r.status_code >= 500:
                corpo_erro = r.text[:200]
                if re.search(r"syntax error|parse|unmarshal|invalid character", corpo_erro, re.IGNORECASE):
                    # o servidor não conseguiu ler a tool call que o modelo gerou: com temperatura 0 a repetição
                    # dá o mesmo erro; quem decide a contingência (saída estruturada) é o condutor
                    erro = ErroLLM("FORMATO", f"{r.status_code}: {corpo_erro}", retryable=False)
                    otel.marcar_erro(s, str(erro))
                    raise erro
                ultimo = ErroLLM("HTTP", f"{r.status_code}: {corpo_erro}", retryable=True)
                continue
            if r.status_code >= 400:
                erro = ErroLLM("HTTP", f"{r.status_code}: {r.text[:200]}", retryable=False)
                otel.marcar_erro(s, str(erro))
                raise erro
            try:
                return r.json(), tentativa + 1
            except json.JSONDecodeError as e:
                ultimo = ErroLLM("FORMATO", f"resposta não é JSON: {e}", retryable=True)
        assert ultimo is not None
        otel.marcar_erro(s, str(ultimo))
        raise ultimo

    def _parse(self, dados: dict[str, Any]) -> RespostaLLM:
        msg = dados.get("message") or {}
        chamadas = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"_bruto": args}
            chamadas.append(ChamadaFerramenta(nome=fn.get("name", ""), argumentos=args or {}))
        return RespostaLLM(
            conteudo=msg.get("content") or "",
            chamadas=chamadas,
            pensamento=msg.get("thinking") or "",
            modelo=dados.get("model", self.modelo),
            provedor="ollama",
            tokens_entrada=int(dados.get("prompt_eval_count") or 0),
            tokens_saida=int(dados.get("eval_count") or 0),
            carga_ms=int((dados.get("load_duration") or 0) / 1e6),
            prompt_ms=int((dados.get("prompt_eval_duration") or 0) / 1e6),
            geracao_ms=int((dados.get("eval_duration") or 0) / 1e6),
        )


# ---------------------------------------------------------------------------
# Vertex AI (Gemini) — demo pública na nuvem
# ---------------------------------------------------------------------------

# US$ por milhão de tokens (entrada, saída), do catálogo do Cloud Billing (serviço Vertex AI C7E2-9256-1C43,
# SKUs "Global Text Input/Output - Predictions", consultado em 24/10/2026). Só para o custo estimado do painel.
PRECOS_GEMINI_USD_MTOK: dict[str, tuple[float, float]] = {
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-3.5-flash-lite": (0.30, 2.50),
}
# O Gemini 3 exige a assinatura do raciocínio em toda chamada de ferramenta do histórico. As que vieram do
# replay (ou de outro modelo) não têm: vai o valor neutro que a documentação do Gemini prevê para isso.
_ASSINATURA_NEUTRA = "skip_thought_signature_validator"
_CODIGOS_PROXIMO = frozenset({"REPLAY_AUSENTE", "INDISPONIVEL", "TIMEOUT", "HTTP", "LIMITE"})


def evento_llm(**campos: Any) -> None:
    """Uma linha JSON no stdout por chamada de LLM, só na demo pública (o Cloud Logging guarda e as métricas
    de log em infra/nuvem somam tokens e custo). Sem texto de prompt nem resposta."""
    if os.environ.get("LAUDO_DEMO_PUBLICA") != "1":
        return
    print(json.dumps({"severity": "INFO", "laudo_evento": "llm", **campos}, ensure_ascii=False), flush=True)


class _CotaDiaria:
    """Teto de tokens por dia (UTC) no processo, somado entre todos os provedores Vertex da instância."""

    def __init__(self) -> None:
        self.dia = ""
        self.usados = 0

    def restante(self, teto: int) -> int:
        hoje = datetime.now(UTC).strftime("%Y-%m-%d")
        if hoje != self.dia:
            self.dia, self.usados = hoje, 0
        return teto - self.usados


_COTA = _CotaDiaria()


class VertexProvider:
    """Gemini no Vertex AI pela API compatível com a da OpenAI (`/endpoints/openapi/chat/completions`).

    Recebe as mensagens no formato do Ollama (o do condutor) e converte: chamadas de ferramenta ganham id e a
    assinatura do raciocínio (guardada da resposta ou neutra), e o resultado da ferramenta (`tool_name`) casa
    com a chamada pendente de mesmo nome. Token: o do metadata server do Cloud Run, ou `LAUDO_VERTEX_TOKEN`
    (teste local, com `gcloud auth print-access-token`). `externo=True`: o condutor mascara PII antes do envio.
    Teto diário de tokens (`LAUDO_LLM_TOKENS_DIA`): estourou, falha como LIMITE e a cadeia segue sem LLM."""

    externo = True
    espera_disjuntor_s = None

    def __init__(
        self,
        modelo: str | None = None,
        projeto: str | None = None,
        local: str | None = None,
        timeout_s: float = 30.0,
        tokens_dia: int | None = None,
        hoje: date | None = None,
        cliente: httpx.Client | None = None,
        espera_falha_s: float = 60.0,
        relogio: Callable[[], float] = time.monotonic,
    ):
        self.nome = "vertex"
        self.modelo = modelo or os.environ.get("LAUDO_VERTEX_MODELO") or "gemini-3.1-flash-lite"
        self.projeto = projeto or os.environ.get("LAUDO_VERTEX_PROJETO") or ""
        self.local = local or os.environ.get("LAUDO_VERTEX_LOCAL") or "global"
        host = "aiplatform.googleapis.com" if self.local == "global" else f"{self.local}-aiplatform.googleapis.com"
        self.base_url = (
            f"https://{host}/v1/projects/{self.projeto}/locations/{self.local}/endpoints/openapi/chat/completions"
        )
        self.tokens_dia = int(tokens_dia or os.environ.get("LAUDO_LLM_TOKENS_DIA") or 3_000_000)
        self.hoje = hoje
        self.timeout = httpx.Timeout(connect=5.0, read=timeout_s, write=10.0, pool=5.0)
        self._cliente = cliente or httpx.Client(timeout=self.timeout)
        self._relogio = relogio
        self._espera_falha_s = espera_falha_s
        self._fora_ate = 0.0  # depois de falha de transporte, não tenta de novo por `espera_falha_s`
        self._token = ("", 0.0)
        self._assinaturas: dict[str, str] = {}

    # -- credencial ---------------------------------------------------------
    def _credencial(self) -> str:
        if tok := os.environ.get("LAUDO_VERTEX_TOKEN"):
            return tok
        valor, expira = self._token
        if valor and self._relogio() < expira:
            return valor
        try:
            r = self._cliente.get(
                "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
                headers={"Metadata-Flavor": "Google"},
                timeout=3.0,
            )
            r.raise_for_status()
            d = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise ErroLLM("INDISPONIVEL", f"sem credencial do Vertex AI: {e}", retryable=False) from e
        self._token = (d["access_token"], self._relogio() + int(d.get("expires_in", 300)) - 60)
        return self._token[0]

    # -- conversão ----------------------------------------------------------
    @staticmethod
    def _chave_chamada(nome: str, argumentos: Any) -> str:
        return nome + json.dumps(argumentos, sort_keys=True, ensure_ascii=False, default=str)

    def montar_requisicao(self, mensagens, ferramentas=None, formato=None) -> dict[str, Any]:
        msgs: list[dict[str, Any]] = []
        pendentes: list[tuple[str, str]] = []  # (id, nome) das chamadas sem resultado ainda
        for i, m in enumerate(injetar_data(mensagens, self.hoje or datetime.now().astimezone().date())):
            papel = m.get("role")
            if papel == "assistant" and m.get("tool_calls"):
                chamadas = []
                for j, tc in enumerate(m["tool_calls"]):
                    fn = tc.get("function") or {}
                    args = fn.get("arguments") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    cid = f"c{i}_{j}"
                    assinatura = self._assinaturas.get(self._chave_chamada(fn.get("name", ""), args))
                    chamadas.append({
                        "id": cid,
                        "type": "function",
                        "function": {"name": fn.get("name", ""), "arguments": json.dumps(args, ensure_ascii=False)},
                        "extra_content": {"google": {"thought_signature": assinatura or _ASSINATURA_NEUTRA}},
                    })
                    pendentes.append((cid, fn.get("name", "")))
                msgs.append({"role": "assistant", "content": m.get("content") or None, "tool_calls": chamadas})
            elif papel == "tool":
                nome = m.get("tool_name", "")
                k = next((k for k, (_, n) in enumerate(pendentes) if n == nome), 0 if pendentes else -1)
                if k < 0:  # resultado sem chamada (não acontece no condutor): vira texto para não quebrar
                    msgs.append({"role": "user", "content": f"[resultado de {nome}] {m.get('content') or ''}"})
                    continue
                cid, _ = pendentes.pop(k)
                msgs.append({"role": "tool", "tool_call_id": cid, "content": m.get("content") or ""})
            else:
                msgs.append({"role": papel, "content": m.get("content") or ""})
        corpo: dict[str, Any] = {
            "model": f"google/{self.modelo}",
            "messages": msgs,
            "temperature": 0,
            "max_tokens": 1024,
            "reasoning_effort": "low",
        }
        if ferramentas:
            corpo["tools"] = ferramentas
        if formato:
            corpo["response_format"] = {"type": "json_schema", "json_schema": {"name": "saida", "schema": formato}}
        return corpo

    # -- chamada ------------------------------------------------------------
    def chat(self, mensagens, ferramentas=None, formato=None, metadados=None) -> RespostaLLM:
        if self._relogio() < self._fora_ate:
            raise ErroLLM("INDISPONIVEL", "Vertex AI falhou há pouco; tentando de novo em instantes")
        if _COTA.restante(self.tokens_dia) <= 0:
            evento_llm(detalhe="limite", modelo=self.modelo, tokens=0, custo_usd=0.0)
            raise ErroLLM("LIMITE", f"teto diário de {self.tokens_dia} tokens do LLM atingido")
        corpo = self.montar_requisicao(mensagens, ferramentas, formato)
        with otel.span_llm("vertex", self.modelo, **{"llm.n_tools": len(ferramentas or []), **(metadados or {})}) as s:
            t0 = time.perf_counter()
            dados = self._post(corpo, s)
            resp = self._parse(dados)
            resp.latencia_ms = int((time.perf_counter() - t0) * 1000)
            resp.span_id = otel.id_span(s)
            ent, sai = PRECOS_GEMINI_USD_MTOK.get(self.modelo, (0.0, 0.0))
            custo = (resp.tokens_entrada * ent + resp.tokens_saida * sai) / 1e6
            _COTA.usados += resp.tokens_entrada + resp.tokens_saida
            otel.definir(
                s,
                **{
                    "gen_ai.usage.input_tokens": resp.tokens_entrada,
                    "gen_ai.usage.output_tokens": resp.tokens_saida,
                    "llm.latency_ms": resp.latencia_ms,
                    "llm.uso_origem": "medido",
                    "llm.custo_usd": round(custo, 6),
                    "llm.n_tool_calls": len(resp.chamadas),
                },
            )
        evento_llm(
            detalhe="vertex", modelo=self.modelo, tokens=resp.tokens_entrada + resp.tokens_saida,
            tokens_entrada=resp.tokens_entrada, tokens_saida=resp.tokens_saida, custo_usd=round(custo, 6),
            latencia_ms=resp.latencia_ms,
        )
        return resp

    def _post(self, corpo: dict[str, Any], s) -> dict[str, Any]:
        for tentativa in range(2):  # uma repetição só, para 429 e 5xx
            try:
                r = self._cliente.post(
                    self.base_url,
                    json=corpo,
                    headers={"Authorization": f"Bearer {self._credencial()}"},
                    timeout=self.timeout,
                )
            except httpx.TimeoutException as e:
                self._fora_ate = self._relogio() + self._espera_falha_s
                erro = ErroLLM("TIMEOUT", str(e) or "timeout")
                otel.marcar_erro(s, str(erro))
                raise erro from e
            except httpx.TransportError as e:
                self._fora_ate = self._relogio() + self._espera_falha_s
                erro = ErroLLM("INDISPONIVEL", str(e) or "falha de conexão")
                otel.marcar_erro(s, str(erro))
                raise erro from e
            if (r.status_code == 429 or r.status_code >= 500) and tentativa == 0:
                time.sleep(1.0)
                continue
            if r.status_code >= 400:
                erro = ErroLLM("HTTP", f"{r.status_code}: {r.text[:300]}")
                otel.marcar_erro(s, str(erro))
                raise erro
            try:
                dados = r.json()
            except json.JSONDecodeError as e:
                raise ErroLLM("FORMATO", f"resposta não é JSON: {e}") from e
            return dados[0] if isinstance(dados, list) and dados else dados
        raise ErroLLM("HTTP", "Vertex AI sem resposta válida")

    def _parse(self, dados: dict[str, Any]) -> RespostaLLM:
        escolha = (dados.get("choices") or [{}])[0]
        msg = escolha.get("message") or {}
        chamadas = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"_bruto": args}
            args = args or {}
            assinatura = ((tc.get("extra_content") or {}).get("google") or {}).get("thought_signature")
            if assinatura:
                if len(self._assinaturas) > 2000:
                    self._assinaturas.clear()
                self._assinaturas[self._chave_chamada(fn.get("name", ""), args)] = assinatura
            chamadas.append(ChamadaFerramenta(nome=fn.get("name", ""), argumentos=args))
        uso = dados.get("usage") or {}
        return RespostaLLM(
            conteudo=msg.get("content") or "",
            chamadas=chamadas,
            modelo=self.modelo,
            provedor="vertex",
            tokens_entrada=int(uso.get("prompt_tokens") or 0),
            tokens_saida=int(uso.get("completion_tokens") or 0),
        )


class ProvedorEmCadeia:
    """Tenta os provedores em ordem: o primeiro que responder vale. REPLAY_AUSENTE, INDISPONIVEL, TIMEOUT, HTTP
    e LIMITE passam ao próximo; FORMATO não (o modelo respondeu, a contingência é do condutor). Se todos
    falham, relança o último erro, e o condutor segue com o plano mínimo e a fala por template.
    Na demo pública: replay (passos gravados, sem custo) → Vertex AI (texto livre)."""

    espera_disjuntor_s = None

    def __init__(self, provedores: list[Any]):
        if not provedores:
            raise ValueError("cadeia sem provedores")
        self.provedores = provedores
        self.nome = "cadeia"
        self.modelo = "+".join(getattr(p, "modelo", "?") for p in provedores)
        self.externo = any(getattr(p, "externo", False) for p in provedores)

    def chat(self, mensagens, ferramentas=None, formato=None, metadados=None) -> RespostaLLM:
        ultimo: ErroLLM | None = None
        for p in self.provedores:
            try:
                r = p.chat(mensagens, ferramentas=ferramentas, formato=formato, metadados=metadados)
            except ErroLLM as e:
                if e.codigo not in _CODIGOS_PROXIMO:
                    raise
                ultimo = e
                continue
            if r.replay:
                evento_llm(detalhe="replay", modelo=r.modelo, tokens=0, custo_usd=0.0, latencia_ms=0)
            return r
        assert ultimo is not None
        raise ultimo


def criar_provedor(tipo: str = "ollama", perfil: str = "escritorio", **kw: Any) -> ProvedorLLM:
    """Fábrica. `tipo` ∈ {ollama, replay, vertex}. Bedrock: ponto de extensão (classe com `externo=True`)."""
    if tipo == "ollama":
        return OllamaProvider(perfil=perfil, **kw)
    if tipo == "replay":
        return ReplayProvider(**kw)
    if tipo == "vertex":
        return VertexProvider(**kw)
    if tipo == "bedrock":
        raise NotImplementedError(
            "Bedrock fica para a final (DECISAO.md); implemente uma classe ProvedorLLM "
            "com externo=True para que o condutor mascare PII antes do envio."
        )
    raise ValueError(f"tipo de provedor desconhecido: {tipo}")


# ---------------------------------------------------------------------------
# Saída estruturada e reparo
# ---------------------------------------------------------------------------

_BLOCO_JSON = re.compile(r"\{.*\}", re.DOTALL)
_TOOL_CALL_TXT = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


def extrair_json(texto: str) -> Any:
    """Extrai o primeiro objeto JSON de um texto (tolera cercas ```json e texto em volta)."""
    t = (texto or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = _BLOCO_JSON.search(t)
        if not m:
            raise
        return json.loads(m.group(0))


def chamadas_do_texto(texto: str) -> list[ChamadaFerramenta]:
    """Reparo local: tool call que o modelo escreveu no texto (`<tool_call>{...}</tool_call>` ou JSON cru
    com `name`/`arguments`) em vez de usar o campo nativo."""
    saida: list[ChamadaFerramenta] = []
    blocos = _TOOL_CALL_TXT.findall(texto or "")
    if not blocos:
        try:
            obj = extrair_json(texto)
        except (json.JSONDecodeError, ValueError):
            return []
        blocos = [json.dumps(o) for o in (obj if isinstance(obj, list) else [obj])]
    for b in blocos:
        try:
            o = json.loads(b) if isinstance(b, str) else b
        except json.JSONDecodeError:
            continue
        if isinstance(o, dict) and isinstance(o.get("name"), str):
            args = o.get("arguments") or o.get("parameters") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            saida.append(ChamadaFerramenta(nome=o["name"], argumentos=args if isinstance(args, dict) else {}))
    return saida


class ResultadoEstruturado(BaseModel):
    objeto: Any = None
    valido_primeira: bool = False
    valido: bool = False
    tentativas: int = 0
    erro: str = ""
    codigo_erro: str = ""  # código do ErroLLM do provedor (TIMEOUT, INDISPONIVEL...) quando a chamada falhou
    latencia_ms: int = 0
    respostas: list[RespostaLLM] = Field(default_factory=list)


def pedir_json(
    provedor: ProvedorLLM,
    mensagens: list[dict[str, Any]],
    modelo: type[BaseModel],
    reparos: int = 1,
    metadados: dict[str, Any] | None = None,
    esquema: dict[str, Any] | None = None,
) -> ResultadoEstruturado:
    """Pede saída estruturada (`format` = JSON Schema do modelo Pydantic), valida e, se inválida, faz até
    `reparos` novas tentativas mostrando o erro ao modelo. Nunca levanta por saída inválida: devolve
    `valido=False` para o chamador degradar para "pendente"/template."""
    esquema = esquema or modelo.model_json_schema()
    msgs = list(mensagens)
    res = ResultadoEstruturado()
    t0 = time.perf_counter()
    for i in range(reparos + 1):
        res.tentativas = i + 1
        try:
            r = provedor.chat(msgs, formato=esquema, metadados=metadados)
        except ErroLLM as e:
            res.erro, res.codigo_erro = str(e), e.codigo
            break
        res.respostas.append(r)
        try:
            obj = modelo.model_validate(extrair_json(r.conteudo))
            res.objeto, res.valido = obj, True
            res.valido_primeira = i == 0
            break
        except (json.JSONDecodeError, ValueError, ValidationError) as e:
            res.erro = mascarar(str(e))[:400]
            msgs = msgs + [
                {"role": "assistant", "content": r.conteudo[:2000]},
                {
                    "role": "user",
                    "content": "A resposta anterior não seguiu o JSON Schema exigido "
                    f"({res.erro[:300]}). Responda de novo apenas com o JSON válido.",
                },
            ]
    res.latencia_ms = int((time.perf_counter() - t0) * 1000)
    return res
