"""Demo pública (`LAUDO_DEMO_PUBLICA=1`): cada visitante ganha a sua cópia da fiscalização de demonstração.

Ligada pela variável de ambiente (desligada por padrão; sem ela nada deste módulo entra em uso). O QR code do
slide leva ao app, que abre direto no caso `DEMO-0001`; quem lê o QR usa sozinho.

**Isolamento.** O visitante é um cookie aleatório (`lv_sessao`, HttpOnly, SameSite=Lax). A cópia dele é um
`ServicoPublico` com pasta própria no disco temporário da instância (`LAUDO_DEMO_DIR`, padrão
`<tmp>/laudo-demo-publica/<hash do cookie>`): estado, conversa, traces, laudos, evidências e índices. O id da
fiscalização continua o do caso (`fis_demo_0001`) em todas as cópias: ele entra no estado e o replay casa pela
chave da requisição, que depende do histórico e dos ids. O contador de ids reprodutíveis, a pasta dos traces e o
contexto da ferramenta de laudo, que no uso normal são do processo, ficam por cópia (`laudo.isolamento`). Assim 20
pessoas clicando ao mesmo tempo não se atrapalham, e cada uma roda em paralelo com as outras.

**Gravação e texto livre.** O LLM é `publico` (`servico.Config.llm`). O passo do roteiro **nunca** chama o LLM ao
vivo: sai da gravação (pela chave da requisição e, se ela não casar, pela próxima gravação do mesmo tipo) e, sem
nenhuma, do plano mínimo e da fala por template. O LLM ao vivo da cadeia (o Gemini) fica só para o que é do
visitante: mensagem livre, fala e arquivo dele. Para o passo seguinte continuar casando com a gravação depois de
uma ação livre (`Sessao.modo`):
- a ação livre usa outro espaço de ids (`ids_livres`), e os ids do roteiro seguem a sequência gravada;
- o turno livre fica marcado na conversa (`livre: true`) e sai do histórico que o passo do roteiro manda ao LLM;
- antes da primeira ação livre depois de um passo, o estado do roteiro (fiscalização e índices) é guardado; o
  passo seguinte volta a ele. O visitante vê o efeito da pergunta ou do arquivo dele até tocar em "Executar
  passo"; o roteiro segue com os arquivos do caso e o laudo sai igual ao do roteiro limpo.
O texto (ou a fala transcrita) igual à fala do próximo passo, e o arquivo pronto do próximo passo, viram o passo.
As perguntas frequentes do visitante (o que o projeto financiou, o que falta para emitir o laudo, o que é pressão,
divergência ou residual) têm resposta pronta, dos dados do caso, sem LLM (`pergunta_frequente`).

**Arquivo do visitante.** A foto perde o GPS do EXIF (e o XMP) antes de entrar na fiscalização: nada da
localização do visitante vai ao estado, ao laudo ou ao trace; o GPS do aparelho também não entra. A foto fora do
cache do VLM volta "indeterminado" com o motivo (a leitura por IA fica desligada na demonstração), e XML que não é
NF-e é recusado (415) sem ir ao LLM.

**Limites (custo e abuso, por variável de ambiente; `Limites.do_ambiente`).** Cópias vivas (400; cheio, sai a
cópia ociosa menos usada, primeiro as intocadas: `GerenciadorSessoes`), criação de cópias por IP (150 a cada 10
min), validade da cópia parada (2 h), turnos livres (40), falas (25) e arquivos (12) por visitante, tamanho e
tipo do arquivo (só foto JPEG/PNG/WebP, vídeo MP4/MOV/WebM de até 20 s e XML da NF-e), duração da fala e total
enviado. A cota só é gasta pelo que passou da validação. Estourou: 429 (ou 413/415 para tamanho e tipo) com
mensagem para a tela e o evento `recusa_limite` (`api.eventos`).

**Pronto no build.** `python -m laudo.api.publica --preparar` roda o roteiro inteiro numa cópia, confere SELADO e 0
requisição fora da gravação e guarda o resultado da contagem do vídeo do caso (`LAUDO_DEMO_CACHE_CONTAGEM`): na
demo, o YOLOX não roda de novo para o vídeo pronto do caso (só para vídeo enviado pelo visitante).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from laudo import isolamento
from laudo.agent import estado as est
from laudo.api import eventos
from laudo.api.servico import REPO, Config, ErroServico, Servico, fala_corresponde
from laudo.contracts import CodigoErro, Envelope, Ferramenta, hash_entrada, sha256_arquivo

log = logging.getLogger(__name__)

ENV = eventos.ENV_DEMO_PUBLICA
COOKIE = "lv_sessao"
_TOKEN_OK = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
MIB = 1024 * 1024
DIR_CACHE_CONTAGEM = Path(os.environ.get("LAUDO_DEMO_CACHE_CONTAGEM") or REPO / "dados_locais" / "cache_contagem")


def ligada() -> bool:
    return eventos.ligado()


def novo_token() -> str:
    return secrets.token_urlsafe(24)


def token_valido(token: str | None) -> bool:
    return bool(token) and bool(_TOKEN_OK.match(token or ""))


# caminho local: absoluto (/app/..., C:\...), relativo (../, ./) ou file:; as rotas da API (/api/...) ficam
_CAMINHO = re.compile(r"^(?:file:|[A-Za-z]:[\\/]|\.{1,2}[\\/]|/(?!api/))")


def sem_caminhos(obj: Any) -> Any:
    """O JSON público com cada caminho local reduzido ao nome do arquivo (como o laudo.html já sai): o caminho
    interno do contêiner (`/app/eval/...`, a pasta da cópia) não vai ao visitante."""
    if isinstance(obj, dict):
        return {k: sem_caminhos(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sem_caminhos(v) for v in obj]
    if isinstance(obj, str) and len(obj) < 1000 and "\n" not in obj and _CAMINHO.match(obj):
        return obj.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    return obj


# ---------------------------------------------------------------------------
# Limites
# ---------------------------------------------------------------------------


def _num(env: dict[str, str] | os._Environ, nome: str, padrao: float) -> float:
    bruto = (env.get(nome) or "").strip().replace(",", ".")
    try:
        return float(bruto) if bruto else padrao
    except ValueError:
        log.warning("%s inválido (%r): uso %s", nome, bruto, padrao)
        return padrao


@dataclass
class Limites:
    # cópias vivas por instância: a recém-criada ocupa ~80 KiB de memória e 3,4 KiB de disco; depois do roteiro
    # inteiro e do pacote, ~1,3 MB de disco (o /tmp do Cloud Run é RAM): 400 cópias cabem com folga nos 8 GiB
    max_sessoes: int = 400
    ttl_s: float = 2 * 3600  # cópia parada há mais que isso é apagada
    copias_por_ip: int = 150  # cópias novas por IP na janela (a plateia inteira pode vir do mesmo Wi-Fi)
    janela_ip_s: float = 600
    ociosa_s: float = 120  # teto cheio: cópia usada (passo, turno, arquivo) parada há mais que isso pode sair
    ociosa_intocada_s: float = 30  # ... e a intocada (só a criação), que volta igual no próximo pedido
    max_turnos: int = 40  # mensagens livres (texto e arquivo do caso fora do roteiro); "Executar passo" não conta
    max_falas: int = 25  # falas pelo microfone (ASR)
    max_uploads: int = 12  # arquivos do aparelho
    upload_mb: dict[str, float] = field(default_factory=lambda: {"foto": 10.0, "video": 30.0, "nfe_xml": 2.0})
    upload_total_mb: float = 60.0  # soma dos arquivos de um visitante
    video_max_s: float = 20.0  # vídeo do visitante: o YOLOX roda na CPU (até ~1 min)
    audio_mb: float = 3.0
    audio_max_s: float = 30.0

    @classmethod
    def do_ambiente(cls, env: dict[str, str] | os._Environ | None = None) -> Limites:
        e = os.environ if env is None else env
        p = cls()
        return cls(
            max_sessoes=int(_num(e, "LAUDO_DEMO_MAX_SESSOES", p.max_sessoes)),
            ttl_s=_num(e, "LAUDO_DEMO_TTL_MIN", p.ttl_s / 60) * 60,
            copias_por_ip=int(_num(e, "LAUDO_DEMO_COPIAS_POR_IP", p.copias_por_ip)),
            janela_ip_s=_num(e, "LAUDO_DEMO_JANELA_IP_MIN", p.janela_ip_s / 60) * 60,
            ociosa_s=_num(e, "LAUDO_DEMO_OCIOSA_S", p.ociosa_s),
            ociosa_intocada_s=_num(e, "LAUDO_DEMO_OCIOSA_INTOCADA_S", p.ociosa_intocada_s),
            max_turnos=int(_num(e, "LAUDO_DEMO_MAX_TURNOS", p.max_turnos)),
            max_falas=int(_num(e, "LAUDO_DEMO_MAX_FALAS", p.max_falas)),
            max_uploads=int(_num(e, "LAUDO_DEMO_MAX_UPLOADS", p.max_uploads)),
            upload_mb={
                "foto": _num(e, "LAUDO_DEMO_FOTO_MB", p.upload_mb["foto"]),
                "video": _num(e, "LAUDO_DEMO_VIDEO_MB", p.upload_mb["video"]),
                "nfe_xml": _num(e, "LAUDO_DEMO_XML_MB", p.upload_mb["nfe_xml"]),
            },
            upload_total_mb=_num(e, "LAUDO_DEMO_UPLOAD_TOTAL_MB", p.upload_total_mb),
            video_max_s=_num(e, "LAUDO_DEMO_VIDEO_MAX_S", p.video_max_s),
            audio_mb=_num(e, "LAUDO_DEMO_AUDIO_MB", p.audio_mb),
            audio_max_s=_num(e, "LAUDO_DEMO_AUDIO_MAX_S", p.audio_max_s),
        )

    def publico(self) -> dict[str, Any]:
        return {
            "turnos": self.max_turnos,
            "falas": self.max_falas,
            "uploads": self.max_uploads,
            "upload_mb": dict(self.upload_mb),
            "video_max_s": self.video_max_s,
            "audio_max_s": self.audio_max_s,
        }


class ErroLimite(ErroServico):
    """Limite da demonstração estourado: a tela mostra a mensagem; vira o evento `recusa_limite`."""

    def __init__(self, limite: str, msg: str, status: int = 429, sessao: str | None = None, **campos: Any):
        super().__init__(status, msg)
        self.limite = limite
        eventos.evento("recusa_limite", limite=limite, status=status, **({"sessao": sessao} if sessao else {}),
                       **campos)


# ---------------------------------------------------------------------------
# Cópia por visitante
# ---------------------------------------------------------------------------


class RepositorioPublico(est.RepositorioFiscalizacoes):
    """Marca o turno livre na conversa (`livre: true`) e, no passo do roteiro, tira os turnos livres do histórico
    que vai ao LLM (`ler_conversa(..., ultimos=)`, o único uso com `ultimos`, em `Condutor._mensagens`). A tela
    lê a conversa inteira."""

    def __init__(self, diretorio: Path):
        super().__init__(diretorio)
        self.marcar_livre = False
        self.ocultar_livres = False

    def anexar_conversa(self, fis_id: str, registro: dict[str, Any]) -> None:
        if self.marcar_livre:
            registro = {**registro, "livre": True}
        super().anexar_conversa(fis_id, registro)

    def ler_conversa(self, fis_id: str, ultimos: int | None = None) -> list[dict[str, Any]]:
        linhas = super().ler_conversa(fis_id)
        if ultimos and self.ocultar_livres:
            linhas = [x for x in linhas if not x.get("livre")]
        return linhas[-ultimos:] if ultimos else linhas


@dataclass
class Sessao:
    sid: str  # hash do cookie (nome da pasta); nunca o cookie
    dados: Path
    contexto: isolamento.Contexto
    gerenciador: GerenciadorSessoes | None = None
    criada: float = field(default_factory=time.time)
    usada: float = field(default_factory=time.time)
    turnos: int = 0
    falas: int = 0
    uploads: int = 0
    upload_bytes: int = 0
    tocada: bool = False  # já teve passo, turno, fala ou arquivo (a intocada só teve a criação e leituras)
    servico: ServicoPublico | None = None
    ids_livres: dict[str, Any] = field(default_factory=lambda: {"semente": None, "n": 0})

    @property
    def ids_roteiro(self) -> dict[str, Any]:
        return self._ids_roteiro

    def __post_init__(self) -> None:
        self._ids_roteiro = self.contexto.ids  # o dicionário que `ids_deterministicos` reinicia no lugar
        self._modos: list[bool] = []  # pilha de `modo` (True = livre)
        self._foto: dict[str, Any] | None = None  # estado do roteiro guardado antes da 1ª ação livre

    @property
    def curta(self) -> str:
        return self.contexto.sessao

    @contextmanager
    def modo(self, livre: bool) -> Iterator[None]:
        """Ação livre do visitante ou passo do roteiro. Aninhável: volta ao modo anterior.

        - livre: ids próprios (`ids_livres`), turno marcado na conversa, a cadeia inteira de LLM (gravação e o LLM
          ao vivo) e, antes da 1ª ação livre depois de um passo, o estado do roteiro guardado (`_guardar_roteiro`);
        - passo: ids da gravação, histórico sem os turnos livres, só a gravação (sem LLM ao vivo; ver
          `ServicoPublico.elos`) e o estado do roteiro de volta (`_restaurar_roteiro`), se uma ação livre o mudou.
        """
        srv = self.servico
        repo = srv.repo if srv is not None else None
        antes_ids = self.contexto.ids
        antes = (repo.marcar_livre, repo.ocultar_livres) if isinstance(repo, RepositorioPublico) else None
        self.contexto.ids = self.ids_livres if livre else self._ids_roteiro
        if antes is not None:
            repo.marcar_livre, repo.ocultar_livres = livre, not livre  # type: ignore[union-attr]
        self._modos.append(livre)
        desfazer: Callable[[], None] | None = None
        try:
            if srv is not None:
                if livre:
                    self._guardar_roteiro()
                else:
                    self._restaurar_roteiro()
                desfazer = srv.elos(livre)
            yield
        finally:
            if desfazer is not None:
                desfazer()
            self._modos.pop()
            self.contexto.ids = antes_ids
            if antes is not None:
                repo.marcar_livre, repo.ocultar_livres = antes  # type: ignore[union-attr]
            if srv is not None and self._modos and self._modos[-1]:
                self._guardar_roteiro()  # passo aninhado numa ação livre: o estado novo do roteiro é o de agora

    # -- estado do roteiro (ver `modo`) ---------------------------------------------------------------
    def _fis_id(self) -> str | None:
        srv = self.servico
        try:
            return srv.caso(srv.caso_padrao).fis_id if srv is not None else None
        except (FileNotFoundError, ErroServico):
            return None

    def _guardar_roteiro(self) -> None:
        """Guarda o estado do roteiro (a fiscalização, os índices de fotos e documentos e a lista das pastas de
        evidência) antes da ação livre, se ainda não está guardado."""
        srv, fis_id = self.servico, self._fis_id()
        if self._foto is not None or srv is None or not fis_id:
            return
        arq = srv.repo.caminho(fis_id)
        self._foto = {
            "fis": arq.read_bytes() if arq.is_file() else None,
            "indices": {p.name: p.read_bytes() for p in (srv.dados / "indices").glob("*.jsonl") if p.is_file()},
            "evidencias": _pastas_de_evidencia(srv.dados / "evidencias"),
        }

    def _restaurar_roteiro(self) -> bool:
        """Volta ao estado do roteiro guardado (ação livre desde o último passo): a fiscalização e os índices como
        estavam e, fora, as pastas de evidência que a ação livre criou (o arquivo do visitante). A conversa e o
        trace continuam inteiros. Devolve se havia o que restaurar."""
        foto, self._foto = self._foto, None
        srv, fis_id = self.servico, self._fis_id()
        if foto is None or srv is None or not fis_id:
            return False
        arq = srv.repo.caminho(fis_id)
        if foto["fis"] is None:
            arq.unlink(missing_ok=True)
        elif not arq.is_file() or arq.read_bytes() != foto["fis"]:
            _gravar_atomico(arq, foto["fis"])
        pasta = srv.dados / "indices"
        for p in pasta.glob("*.jsonl"):
            if p.name not in foto["indices"]:
                p.unlink(missing_ok=True)
        for nome, dados in foto["indices"].items():
            p = pasta / nome
            if not p.is_file() or p.read_bytes() != dados:
                _gravar_atomico(p, dados)
        for p in _pastas_de_evidencia(srv.dados / "evidencias") - foto["evidencias"]:
            shutil.rmtree(p, ignore_errors=True)
        return True

    def descartar_roteiro_guardado(self) -> None:
        """O que a ação livre fez fica (ex.: a assinatura que selou o laudo)."""
        self._foto = None

    def uso(self) -> dict[str, int]:
        return {"turnos": self.turnos, "falas": self.falas, "uploads": self.uploads}


def _pastas_de_evidencia(base: Path) -> set[Path]:
    """`evidencias/<fiscalização ou visao>/<pasta do envio>`: cada envio ou contagem cria uma pasta nesse nível."""
    if not base.is_dir():
        return set()
    return {q for p in base.iterdir() if p.is_dir() for q in p.iterdir()}


def _gravar_atomico(destino: Path, dados: bytes) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_name(f".{destino.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_bytes(dados)
    os.replace(tmp, destino)


# -- perguntas frequentes do visitante (texto normalizado: sem acento, minúsculo, só palavras) ---------------------
_TERMOS = {"pressao": re.compile(r"\bpress(?:ao|oes)\b"), "divergencia": re.compile(r"\bdivergen\w*"),
           "residual": re.compile(r"\bresidua(?:l|is)\b")}
_GLOSSARIO = {
    "pressao": "Pressão é o pedido para mudar um resultado sem prova nova, como “pode marcar 29” quando o vídeo "
               "contou menos. O agente não muda o valor: registra a tentativa como ocorrência (regra POL-07) e o "
               "número continua o da evidência.",
    "divergencia": "Divergência é quando a prova não bate com o contrato ou com outra prova, como o vídeo contar "
                   "menos animais que a nota fiscal. O item fica divergente, e o rascunho do laudo só sai com a "
                   "justificativa da fiscal para cada divergência (regra POL-02).",
    "residual": "Residual é o que a leitura da foto de um documento, como a nota impressa (DANFE), não conseguiu "
                "validar: o agente pede só esses campos, a fiscal lê no papel ou digita, e as regras conferem o que "
                "foi informado (dígito verificador e somas).",
}
_RX_DEFINICAO = re.compile(r"\b(?:o que (?:e|sao|significa|quer dizer)|que e|explique|explica|defina|definicao|"
                           r"significa|significado|como funciona)\b")
_RX_FALTA = re.compile(r"\b(?:falta|faltam|faltando|pendencia|pendencias|pendente|pendentes)\b")
_RX_LAUDO = re.compile(r"\b(?:laudo|emitir|emissao|rascunho|concluir|terminar|fechar|assinar)\b")
_RX_PERGUNTA = re.compile(r"\b(?:quant[oa]s?|qual|quais|o que|que)\b")
_RX_FINANCIADO = re.compile(r"\b(?:financi\w*|projeto|valor|credito|contrat\w*|orcamento)\b")
_RX_CONTAGEM = re.compile(r"\b(?:cont(?:ou|ei|agem|ar|ados?|aram)|video|curral|nota|gta|foto|vi|viu)\b")
_RX_CAMPO = re.compile(r"\s*\(?\b(?:item|documento|laudo|operacao):[\w:]+\)?")


def _normal(texto: str) -> str:
    from laudo.api.servico import _normalizar_fala

    return _normalizar_fala(texto)


def _termos(texto: str) -> list[str]:
    t = _normal(texto)
    return [k for k, rx in _TERMOS.items() if rx.search(t)]


def pergunta_frequente(texto: str) -> str | None:
    """"glossario", "falta", "financiado" ou None. Conservador: na dúvida, None (a pergunta vai ao LLM)."""
    t = _normal(texto)
    if not t or len(t) > 200:
        return None
    if _termos(texto) and _RX_DEFINICAO.search(t):
        return "glossario"
    if _RX_FALTA.search(t) and _RX_LAUDO.search(t):
        return "falta"
    if _RX_PERGUNTA.search(t) and _RX_FINANCIADO.search(t) and not _RX_CONTAGEM.search(t) and not _RX_FALTA.search(t):
        return "financiado"
    return None


def _fala_financiado(fis: Any) -> str:
    """O que o projeto financiou, item a item, com quantidade e valor (do contrato do caso)."""
    from laudo.formatacao import fmt_milhar

    partes = []
    for i in fis.operacao.itens:
        d = re.split(r"\s+[—(]", i.descricao or "", maxsplit=1)[0].strip() or i.tipo
        if i.quantidade is not None and fmt_milhar(i.quantidade) not in d and str(int(i.quantidade)) not in d:
            d = f"{fmt_milhar(i.quantidade)} {i.unidade or ''} de {d}".replace("  ", " ")
        d = d[:1].lower() + d[1:]
        if d.split(" ", 1)[0].endswith(("ção", "são", "gem")):
            d = "a " + d
        if i.valor_rs:
            d += f" (R$ {fmt_milhar(i.valor_rs)})"
        partes.append(d)
    if not partes:
        return ""
    lista = partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " e " + partes[-1]
    v = fis.operacao.valor_rs
    total = f"; total de R$ {fmt_milhar(v)}" if v and len(partes) > 1 else ""
    return f"O projeto financiou {lista}{total}. A fiscalização confere se cada item existe como foi financiado."


def _passo_da_fala(p: Any, texto: str) -> bool:
    return bool(p) and p.acao == "turno" and not p.evidencia and bool(p.fala) and fala_corresponde(p.fala, texto)


def _passo_de_emissao(p: Any) -> bool:
    if not p or p.evidencia:
        return False
    if p.acao == "rascunho":
        return True
    from laudo.agent.intencao import comando_humano

    cmd = comando_humano(p.fala) if p.acao == "turno" and p.fala else None
    return bool(cmd) and cmd[0] == "emitir_rascunho"


class ServicoPublico(Servico):
    """O `Servico` de uma cópia: pasta, repositório, provedor e condutor próprios (ver o docstring do módulo)."""

    def __init__(self, cfg: Config, sessao: Sessao, transcritor: Any | None = None):
        self.sessao = sessao
        super().__init__(cfg, transcritor=transcritor)

    # -- montagem --------------------------------------------------------------------
    def _configurar_traces(self) -> None:
        # os traces vão para a pasta da cópia pelo contexto (`laudo.isolamento`), sem trocar o do processo
        (self.dados / "traces").mkdir(parents=True, exist_ok=True)

    def _novo_repositorio(self) -> est.RepositorioFiscalizacoes:
        return RepositorioPublico(self.dados)

    def _montar_registro(self, cenario: dict[str, dict[str, Any]]) -> tuple[dict, list[str]]:
        reg, falsas = super()._montar_registro(cenario)
        if "contar_bovinos_video" in reg and "contar_bovinos_video" not in falsas and self.cfg.ferramentas == "reais":
            reg = dict(reg)
            reg["contar_bovinos_video"] = contagem_com_cache(reg["contar_bovinos_video"], self._videos_do_caso)
        if "classificar_foto" in reg and "classificar_foto" not in falsas:
            reg = dict(reg)
            reg["classificar_foto"] = classificacao_so_do_cache(reg["classificar_foto"])
        return reg, falsas

    def elos(self, livre: bool) -> Callable[[], None] | None:
        """Os elos da cadeia de LLM no modo (`Sessao.modo`): no passo do roteiro, só a gravação, com a substituição
        pela próxima gravação do mesmo tipo quando a chave não casa (sem nenhuma, o condutor segue pelo plano
        mínimo e pela fala por template); na ação livre, a gravação pela chave e depois o LLM ao vivo. Devolve
        como desfazer (None: o LLM não é a cadeia `publico`)."""
        from laudo.llm.provider import ProvedorEmCadeia

        cadeia, rep = self.provedor, self.replay_publico
        if not isinstance(cadeia, ProvedorEmCadeia) or rep is None:
            return None
        antes = (cadeia.provedores, rep.sequencial_se_ausente)
        if livre:
            cadeia.provedores = [rep] + ([self.provedor_ao_vivo] if self.provedor_ao_vivo is not None else [])
        else:
            cadeia.provedores = [rep]
        rep.sequencial_se_ausente = not livre

        def desfazer() -> None:
            cadeia.provedores, rep.sequencial_se_ausente = antes

        return desfazer

    def _videos_do_caso(self) -> set[str]:
        """sha256 dos vídeos prontos do caso de demonstração (a contagem deles sai do cache)."""
        ger = self.sessao.gerenciador
        cache = ger.videos_preset if ger is not None else None
        if cache is not None:
            return cache
        out = set()
        try:
            for a in self.caso(self.caso_padrao).arquivos:
                if a.tipo == "video" and a.disponivel and a.nova.caminho and Path(a.nova.caminho).is_file():
                    out.add(sha256_arquivo(a.nova.caminho))
        except (FileNotFoundError, ErroServico):
            pass
        if ger is not None:
            ger.videos_preset = out
        return out

    def caso(self, cid: str):
        """Os casos são lidos uma vez por processo (pela cópia de base) e divididos entre as cópias."""
        ger = self.sessao.gerenciador
        if ger is not None and cid in ger.casos:
            c = ger.casos[cid]
            self._casos.setdefault(cid, c)
            return c
        c = super().caso(cid)
        if ger is not None:
            ger.casos.setdefault(cid, c)
            ger.casos.setdefault(c.id, c)
        return c

    def listar_casos(self) -> list[dict[str, Any]]:
        return [self.caso(self.caso_padrao).resumo() | {"padrao": True}]

    def saude(self) -> dict[str, Any]:
        d = super().saude()
        d["config"]["demo_publica"] = True
        d["llm"].pop("arquivo", None)  # caminho interno do contêiner não vai ao público
        if d["config"].get("replay"):
            d["config"]["replay"] = Path(str(d["config"]["replay"])).name
        caso = self.caso(self.caso_padrao)
        lim = self.sessao.gerenciador.limites if self.sessao.gerenciador else Limites()
        d["demo_publica"] = {"fis_id": caso.fis_id, "caso": caso.id, "limites": lim.publico(),
                             "uso": self.sessao.uso()}
        return d

    def laudo_json(self, fis_id: str) -> dict[str, Any]:
        return sem_caminhos(super().laudo_json(fis_id))

    def trace(self, fis_id: str, span_id: str | None = None) -> list[dict[str, Any]]:
        return sem_caminhos(super().trace(fis_id, span_id))

    def trace_publico(self, fis_id: str) -> str:
        """O trace inteiro (JSONL) com os caminhos reduzidos ao nome do arquivo."""
        p = self.trace_arquivo(fis_id)
        if not p.is_file():
            raise ErroServico(404, "trace ainda vazio")
        linhas = []
        for linha in p.read_text(encoding="utf-8").splitlines():
            if not linha.strip():
                continue
            try:
                linhas.append(json.dumps(sem_caminhos(json.loads(linha)), ensure_ascii=False))
            except json.JSONDecodeError:
                continue
        return "".join(x + "\n" for x in linhas)

    # -- ações -----------------------------------------------------------------------
    def abrir_caso(self, cid: str, reiniciar: bool = True) -> dict[str, Any]:
        if cid not in {self.caso_padrao, self.caso(self.caso_padrao).id}:
            raise ErroServico(403, "Na demonstração pública só o caso de demonstração abre.")
        with self.sessao.modo(livre=False):
            out = super().abrir_caso(cid, reiniciar=reiniciar)
        if reiniciar:
            sem = self.sessao.ids_roteiro.get("semente")
            self.sessao.ids_livres.clear()
            self.sessao.ids_livres.update({"semente": f"{sem}:livre" if sem else None, "n": 0})
        return out

    def abrir_ref(self, ref_bacen: str, nova: bool = False) -> dict[str, Any]:
        raise ErroServico(403, "Na demonstração pública só o caso de demonstração abre (dados sintéticos).")

    def passo_do_texto(self, fis_id: str, texto: str) -> bool:
        atual = self._passo_atual(fis_id)
        return atual is not None and _passo_da_fala(atual[2], texto)

    def turno(self, fis_id: str, texto: str = "", origem: str = "texto", evidencia=None, passos_llm=None,
              extra=None, confianca_asr=None, residual=None, do_roteiro: bool = False,
              nome_caso: str | None = None) -> dict[str, Any]:
        # a fala transcrita (ou confirmada) igual à do próximo passo vira o passo: a resposta sai da gravação
        if origem == "asr" and evidencia is None and not residual and not do_roteiro:
            with self.lock:
                if self.passo_do_texto(fis_id, texto):
                    with self.sessao.modo(livre=False):
                        out = self.passo_roteiro(fis_id)
                    return out | (extra or {}) | {"pelo_roteiro": True}
        # pergunta frequente do visitante (digitada ou falada): resposta pronta dos dados do caso, sem LLM
        if origem in ("texto", "asr") and evidencia is None and not residual and not do_roteiro and not nome_caso:
            pronta = self.resposta_pronta(fis_id, texto)
            if pronta is not None:
                return pronta | (extra or {})
        return super().turno(fis_id, texto, origem=origem, evidencia=evidencia, passos_llm=passos_llm,
                             extra=extra, confianca_asr=confianca_asr, residual=residual,
                             do_roteiro=do_roteiro, nome_caso=nome_caso)

    # -- perguntas frequentes (P2): resposta pronta, dos dados do caso, antes do LLM -------------------------
    def resposta_pronta(self, fis_id: str, texto: str) -> dict[str, Any] | None:
        """Resposta por template para as perguntas que o visitante mais faz (`pergunta_frequente`): o que o projeto
        financiou (quantidade e valor), o que falta para emitir o laudo e o que é pressão, divergência ou residual.
        Vai à conversa como turno livre e não muda o estado. None: não é uma delas (segue para o LLM)."""
        tipo = pergunta_frequente(texto)
        if tipo is None:
            return None
        with self.lock:
            fis = self.carregar(fis_id)
            t0 = time.perf_counter()
            if tipo == "financiado":
                fala = _fala_financiado(fis)
            elif tipo == "falta":
                fala = self._fala_falta(fis)
            else:
                fala = " ".join(_GLOSSARIO[t] for t in _termos(texto))
            if not fala:
                return None
            n = len(self.repo.ler_conversa(fis_id)) + 1
            from laudo.agent.condutor import RespostaTurno

            resp = RespostaTurno(fiscalizacao_id=fis.id, turno=n, etapa=fis.estado_fsm, fala=fala,
                                 fala_origem="template")
            self.repo.anexar_conversa(fis_id, {"turno": n, "fiscal": texto[:2000], "agente": fala,
                                               "etapa": fis.estado_fsm, "acoes": [], "pronta": tipo})
            out = self._resultado(fis_id, resp.model_dump(mode="json"), self._status(fis),
                                  int((time.perf_counter() - t0) * 1000))
        return out | {"pronta": tipo}

    def _fala_falta(self, fis: Any) -> str:
        from laudo.tools import laudo as ferr_laudo

        if fis.estado_fsm == "SELADO":
            return "Nada: o laudo desta fiscalização já está assinado e selado."
        if fis.estado_fsm in ("RASCUNHO", "ASSINATURA") and ferr_laudo.ultimo_rascunho(fis):
            return ("O rascunho do laudo já foi emitido: falta a assinatura da fiscal, com o PIN e a conferência do "
                    "hash. O agente nunca assina.")
        faltas: list[str] = []
        for p in self.cond.politica.pendencias_emissao(fis):
            f = _RX_CAMPO.sub("", str(p.get("falta") or "")).strip(" .;")
            f = re.sub(r"^evidência ausente:\s*", "", f)
            if f and f not in faltas:
                faltas.append(f)
        if not faltas:
            return "Nada bloqueia: o rascunho do laudo já pode ser emitido; a assinatura continua sendo da fiscal."
        n = len(faltas)
        lista = "; ".join(faltas[:4]) + (f"; e mais {n - 4}" if n > 4 else "")
        return (f"Para emitir o laudo ainda falta{'m' if n > 1 else ''} {n} ponto{'s' if n > 1 else ''}: {lista}. "
                "O roteiro em “Executar passo” traz cada prova.")


# ---------------------------------------------------------------------------
# Fachada por requisição (o que as rotas chamam)
# ---------------------------------------------------------------------------

_FORMATOS = {"foto": ("jpeg", "png", "webp"), "video": ("mp4", "webm"), "nfe_xml": ("xml",)}
_ROTULO_TIPO = {"foto": "foto (JPEG, PNG ou WebP)", "video": "vídeo (MP4, MOV ou WebM)", "nfe_xml": "XML da NF-e"}
# frases da tela e da voz (o detalhe técnico vai só ao log)
MSG_AUDIO_ILEGIVEL = "Não consegui ouvir esse áudio. Grave de novo segurando o botão."
MSG_SEM_FALA = "Não ouvi fala nenhuma. Pode repetir?"
MSG_ASR_OCUPADO = "Muita gente falando ao mesmo tempo; tente de novo em alguns segundos."
MSG_VOZ_FORA = "A voz está indisponível agora: digite a mensagem."
AVISO_ARQUIVO_VISITANTE = ("Seu arquivo foi conferido. O roteiro da demonstração segue com os arquivos prontos do caso "
                           "quando você tocar em “Executar passo”.")
AVISO_SEM_GPS = "A localização gravada na foto foi apagada antes da conferência: a demonstração não guarda onde você está."


def formato_arquivo(cab: bytes) -> str | None:
    """Formato pelo começo do arquivo (assinatura), nunca pela extensão nem pelo tipo que o navegador diz."""
    if cab.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if cab.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if cab[:4] == b"RIFF" and cab[8:12] == b"WEBP":
        return "webp"
    if cab[4:8] == b"ftyp":
        marca = cab[8:12]
        if marca in (b"heic", b"heix", b"hevc", b"heim", b"heis", b"mif1", b"msf1", b"avif"):
            return "heic"
        return "mp4"
    if cab.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm"
    t = cab[3:] if cab.startswith(b"\xef\xbb\xbf") else cab
    if t.lstrip().startswith(b"<"):
        return "xml"
    return None


def duracao_video(caminho: Path) -> float | None:
    """Duração do vídeo pelo contêiner; sem ela (gravação do navegador), pelo último pacote. None: ilegível."""
    import av

    try:
        with av.open(str(caminho)) as c:
            if not c.streams.video:
                return None
            s = c.streams.video[0]
            if s.duration is not None and s.time_base is not None:
                return float(s.duration * s.time_base)
            if c.duration:
                return c.duration / 1_000_000
            fim = 0.0
            for pac in c.demux(s):
                if pac.pts is not None and pac.time_base is not None:
                    fim = max(fim, float(pac.pts * pac.time_base))
            return fim or None
    except Exception:  # noqa: BLE001 - qualquer falha de leitura: vídeo ilegível
        return None


class FachadaSessao:
    """O que as rotas chamam na demo pública: cada chamada roda no contexto da cópia do visitante, com a trava
    dela; as ações separam o passo do roteiro (gravação) do turno livre e conferem os limites."""

    def __init__(self, ger: GerenciadorSessoes, sessao: Sessao):
        self._ger = ger
        self._s = sessao

    @property
    def sessao(self) -> Sessao:
        return self._s

    @property
    def servico(self) -> ServicoPublico:
        assert self._s.servico is not None
        return self._s.servico

    @contextmanager
    def _ativo(self) -> Iterator[ServicoPublico]:
        srv = self.servico
        self._s.usada = self._ger.relogio()
        with isolamento.ativo(self._s.contexto), srv.lock:
            yield srv

    def __getattr__(self, nome: str) -> Any:
        alvo = getattr(self.servico, nome)
        if not callable(alvo):
            return alvo

        def chamada(*a: Any, **k: Any) -> Any:
            with self._ativo():
                return alvo(*a, **k)

        return chamada

    # -- limites -----------------------------------------------------------------------
    def _limite(self, contador: str, maximo: int, msg: str) -> None:
        if getattr(self._s, contador) >= maximo:
            raise ErroLimite(contador, msg, sessao=self._s.curta, maximo=maximo)
        setattr(self._s, contador, getattr(self._s, contador) + 1)

    @contextmanager
    def _cota(self, contador: str, maximo: int, msg: str) -> Iterator[None]:
        """Gasta uma unidade da cota do visitante; recusa da ação (erro 4xx: validação, arquivo, ASR ocupado)
        devolve a unidade. Só conta o que passou da validação."""
        self._limite(contador, maximo, msg)
        try:
            yield
        except ErroServico as e:
            if e.status < 500:
                setattr(self._s, contador, max(0, getattr(self._s, contador) - 1))
            raise

    def _msg_turnos(self) -> str:
        n = self._ger.limites.max_turnos
        return f"Limite da demonstração: até {n} mensagens livres por visitante. O roteiro continua em “Executar passo”."

    def _tocar(self) -> None:
        self._s.tocada = True

    def _fora(self) -> int:
        r = self.servico.replay_publico
        return int(getattr(r, "fora", 0) or 0)

    def _substituicoes(self) -> int:
        r = self.servico.replay_publico
        return int(getattr(r, "substituicoes", 0) or 0)

    def _ev(self, nome: str, **campos: Any) -> None:
        eventos.evento(nome, sessao=self._s.curta, **campos)

    def _evento_turno(self, canal: str, out: dict[str, Any], t0: float, fora0: int, livre: bool, **extra: Any):
        est_ = out.get("estado") or {}
        if out.get("pronta"):
            extra["pronta"] = out["pronta"]  # pergunta frequente: resposta pronta, sem LLM
        self._ev("turno", canal=canal, livre=livre, etapa=est_.get("etapa"), passo=(out.get("passo") or {}).get("n"),
                 latencia_ms=int((time.perf_counter() - t0) * 1000), fora_da_gravacao=self._fora() - fora0, **extra)

    # -- passo do roteiro ------------------------------------------------------------------
    def _passo(self, fis_id: str, canal: str = "passo") -> dict[str, Any]:
        t0, fora0, sub0 = time.perf_counter(), self._fora(), self._substituicoes()
        with self._ativo() as srv, self._s.modo(livre=False):
            self._tocar()
            out = srv.passo_roteiro(fis_id)
        self._evento_turno(canal, out, t0, fora0, livre=False, substituicoes=self._substituicoes() - sub0)
        return out

    def passo_roteiro(self, fis_id: str, n: int | None = None) -> dict[str, Any]:
        with self._ativo() as srv:
            atual = srv._passo_atual(fis_id)
        if n is not None and (atual is None or atual[1] != n):
            raise ErroServico(400, "Na demonstração pública o roteiro segue em ordem: use “Executar passo”.")
        return self._passo(fis_id)

    def pular_passo(self, fis_id: str) -> dict[str, Any]:
        with self._ativo() as srv, self._s.modo(livre=False):
            self._tocar()
            return srv.pular_passo(fis_id)

    def abrir_caso(self, cid: str, reiniciar: bool = True) -> dict[str, Any]:
        with self._ativo() as srv:
            return srv.abrir_caso(cid, reiniciar=reiniciar)

    # -- turnos ----------------------------------------------------------------------------
    def turno(self, fis_id: str, texto: str = "", origem: str = "texto",
              residual: dict[str, str] | None = None) -> dict[str, Any]:
        with self._ativo() as srv:
            if not residual and srv.passo_do_texto(fis_id, texto):
                return self._passo(fis_id, canal="texto")
            self._tocar()
            with self._cota("turnos", self._ger.limites.max_turnos, self._msg_turnos()):
                t0, fora0 = time.perf_counter(), self._fora()
                with self._s.modo(livre=True):
                    out = srv.turno(fis_id, texto, origem=origem, residual=residual)
        self._evento_turno("texto", out, t0, fora0, livre=True)
        return out

    def turno_audio(self, fis_id: str, nome: str, conteudo: bytes, confirmar_numeros: bool = True) -> dict[str, Any]:
        from laudo.speech.asr import TAXA, ErroASR, decodificar

        lim = self._ger.limites
        if len(conteudo) > lim.audio_mb * MIB:
            raise ErroLimite("audio_mb", f"Fala acima de {lim.audio_mb:g} MB: fale em trechos curtos.", status=413,
                             sessao=self._s.curta)
        if not conteudo:
            raise ErroServico(400, MSG_AUDIO_ILEGIVEL)
        with self._ativo() as srv:
            if srv.transcritor is None:
                raise ErroServico(503, "voz desligada neste modo: digite a fala")
            srv.carregar(fis_id)
            self._tocar()
            try:
                dur = decodificar(conteudo).size / TAXA
            except ErroASR as e:
                log.info("fala ilegível: %s", e.msg)  # o detalhe técnico fica no log; a tela recebe a frase simples
                raise ErroServico(400, MSG_AUDIO_ILEGIVEL) from e
            if dur > lim.audio_max_s:
                raise ErroLimite("audio_s", f"Fala de {dur:.0f} s: o limite da demonstração é "
                                 f"{lim.audio_max_s:g} s por fala.", status=413, sessao=self._s.curta)
            with self._cota("falas", lim.max_falas, f"Limite da demonstração: até {lim.max_falas} falas por "
                            "visitante. Digite a mensagem ou use “Executar passo”."):
                t0, fora0 = time.perf_counter(), self._fora()
                try:
                    with self._s.modo(livre=True):
                        out = srv.turno_audio(fis_id, nome, conteudo, confirmar_numeros)
                except ErroServico as e:
                    if isinstance(e, ErroLimite):
                        raise
                    if e.status == 429:  # transcritor ocupado (fila cheia): a fala não conta
                        raise ErroLimite("asr_ocupado", MSG_ASR_OCUPADO, status=429, sessao=self._s.curta) from e
                    if e.status in (400, 503):
                        log.info("ASR: %s", e.msg)
                        raise ErroServico(e.status, MSG_AUDIO_ILEGIVEL if e.status == 400 else MSG_VOZ_FORA) from e
                    raise
        tr = out.get("transcricao") or {}
        if tr.get("vazio") and out.get("resposta") is None and not out.get("confirmacao"):
            out["aviso"] = MSG_SEM_FALA  # sem o motivo técnico (VAD, Whisper)
            out["fala_voz"] = MSG_SEM_FALA
        self._ev("asr", audio_s=tr.get("duracao_audio_s"), latencia_ms=tr.get("latencia_ms"), modelo=tr.get("modelo"),
                 dispositivo=tr.get("dispositivo"), vazio=tr.get("vazio"), espera_ms=tr.get("espera_ms"))
        if out.get("resposta") is not None:
            self._evento_turno("voz", out, t0, fora0, livre=not out.get("pelo_roteiro"))
        return out

    def confirmar(self, fis_id: str, aceitar: bool, texto: str | None = None) -> dict[str, Any]:
        """Confirma (ou descarta) os números da fala pendente. Sem fala pendente, nada a confirmar (409, sem LLM);
        o texto corrigido, diferente do que ficou pendente, é mensagem livre e conta no limite."""
        t0, fora0 = time.perf_counter(), self._fora()
        with self._ativo() as srv:
            self._tocar()
            pend = srv._pendente.get(fis_id)
            if aceitar and not pend:
                raise ErroServico(409, "nada a confirmar")
            editado = aceitar and bool((texto or "").strip()) and \
                (texto or "").strip() != str((pend or {}).get("texto") or "").strip()
            cota = self._cota("turnos", self._ger.limites.max_turnos, self._msg_turnos()) if editado else nullcontext()
            with cota, self._s.modo(livre=True):
                out = srv.confirmar(fis_id, aceitar, texto)
        if out.get("resposta") is not None:
            self._evento_turno("voz", out, t0, fora0, livre=not out.get("pelo_roteiro"))
        return out

    def evidencia_do_caso(self, fis_id: str, nome: str, texto: str = "") -> dict[str, Any]:
        with self._ativo() as srv:
            atual = srv._passo_atual(fis_id)
            p = atual[2] if atual else None
            if p is not None and p.acao == "turno" and p.evidencia == nome:
                return self._passo(fis_id)
            m = srv.meta(fis_id)
            if not m.get("caso_id") or srv.caso(m["caso_id"]).arquivo(nome) is None:
                raise ErroServico(404, "Esta evidência não existe no caso.")  # sem repetir o nome recebido
            self._tocar()
            with self._cota("turnos", self._ger.limites.max_turnos, self._msg_turnos()):
                t0, fora0 = time.perf_counter(), self._fora()
                with self._s.modo(livre=True):
                    out = srv.evidencia_do_caso(fis_id, nome, texto)
        self._evento_turno("texto", out, t0, fora0, livre=True, arquivo_do_caso=True)
        return out

    def pedir_rascunho(self, fis_id: str) -> dict[str, Any]:
        with self._ativo() as srv:
            atual = srv._passo_atual(fis_id)
            if atual is not None and _passo_de_emissao(atual[2]):
                return self._passo(fis_id)
            self._tocar()
            with self._s.modo(livre=True):
                return srv.pedir_rascunho(fis_id)

    def assinar(self, fis_id: str, pin: str, hash_confirmado: str, papel: str = "fiscal",
                nome_ref: str = "fiscal-demo") -> dict[str, Any]:
        with self._ativo() as srv:
            self._tocar()
            atual = srv._passo_atual(fis_id)
            no_roteiro = atual is not None and atual[2].acao == "assinar"
            with self._s.modo(livre=not no_roteiro):
                out = srv.assinar(fis_id, pin, hash_confirmado, papel, nome_ref)
                if (out.get("estado") or {}).get("etapa") == "SELADO":
                    self._s.descartar_roteiro_guardado()  # selado é final: o passo seguinte não volta atrás
        etapa = (out.get("estado") or {}).get("etapa")
        self._ev("assinatura", ok=etapa == "SELADO", tentativas_restantes=out.get("tentativas_restantes"),
                 no_roteiro=no_roteiro)
        if etapa == "SELADO":
            self._ev("selo", passos_pulados=len(srv.meta(fis_id).get("passos_pulados") or []),
                     turnos_livres=self._s.turnos, falas=self._s.falas, uploads=self._s.uploads,
                     minutos=round((self._ger.relogio() - self._s.criada) / 60, 1))
        return out

    def upload(self, fis_id: str, nome: str, fluxo, tipo: str, item_id: str | None = None, lote: str | None = None,
               texto: str = "", gps: dict[str, Any] | None = None, capturada_em: str | None = None,
               mime: str = "") -> dict[str, Any]:
        lim, s = self._ger.limites, self._s
        if tipo not in lim.upload_mb:
            raise ErroLimite("tipo", "Na demonstração pública o aparelho envia só foto, vídeo curto ou o XML da NF-e; "
                             "a foto da nota ou da GTA vem dos arquivos prontos do caso.", status=415, sessao=s.curta,
                             tipo=tipo)
        msg_cota = f"Limite da demonstração: até {lim.max_uploads} arquivos por visitante. Use os arquivos prontos do caso."
        if s.uploads >= lim.max_uploads:  # antes de receber o arquivo; a vaga só é gasta depois da validação
            raise ErroLimite("uploads", msg_cota, sessao=s.curta, maximo=lim.max_uploads)
        teto = int(lim.upload_mb[tipo] * MIB)
        sem_gps = False
        with self._ativo() as srv:
            srv.carregar(fis_id)
            self._tocar()
            entrada = s.dados / "_entrada" / uuid.uuid4().hex[:10]
            entrada.mkdir(parents=True, exist_ok=True)
            tmp = entrada / "arquivo"
            try:
                n = 0
                with open(tmp, "wb") as f:
                    while bloco := fluxo.read(1 << 20):
                        n += len(bloco)
                        if n > teto:
                            raise ErroLimite("tamanho", f"Arquivo acima de {lim.upload_mb[tipo]:g} MB "
                                             f"({_ROTULO_TIPO[tipo]}).", status=413, sessao=s.curta, tipo=tipo)
                        f.write(bloco)
                if s.upload_bytes + n > lim.upload_total_mb * MIB:
                    raise ErroLimite("upload_total", f"Limite da demonstração: até {lim.upload_total_mb:g} MB de "
                                     "arquivos por visitante.", sessao=s.curta)
                with open(tmp, "rb") as f:
                    fmt = formato_arquivo(f.read(64))
                if fmt not in _FORMATOS[tipo]:
                    raise ErroLimite("tipo", f"Este arquivo não é {_ROTULO_TIPO[tipo]}.", status=415, sessao=s.curta,
                                     tipo=tipo, formato=fmt or "desconhecido")
                if tipo == "nfe_xml" and not eh_nfe(tmp):  # sem ir ao LLM nem à conciliação
                    raise ErroLimite("tipo", "Este XML não é uma NF-e.", status=415, sessao=s.curta, tipo=tipo,
                                     formato="xml_nao_nfe")
                if tipo == "video":
                    dur = duracao_video(tmp)
                    if dur is None:
                        raise ErroServico(400, "Não consegui ler este vídeo.")
                    if dur > lim.video_max_s + 0.5:
                        raise ErroLimite("video_s", f"Vídeo de {dur:.0f} s: na demonstração pública, até "
                                         f"{lim.video_max_s:g} s (a contagem roda na CPU).", status=413,
                                         sessao=s.curta)
                if tipo == "foto":
                    # a localização gravada pelo aparelho sai do arquivo antes de entrar na fiscalização; o GPS do
                    # navegador também não entra (gps=None): nada da localização do visitante vai ao estado,
                    # ao laudo ou ao trace
                    sem_gps = foto_sem_gps(tmp, fmt or "")
                with self._cota("uploads", lim.max_uploads, msg_cota):
                    t0, fora0 = time.perf_counter(), self._fora()
                    with open(tmp, "rb") as f, s.modo(livre=True):
                        out = srv.upload(fis_id, nome, f, tipo, item_id=item_id, lote=lote, texto=texto, gps=None,
                                         capturada_em=capturada_em, mime=mime)
                s.upload_bytes += n
            finally:
                shutil.rmtree(entrada, ignore_errors=True)
        avisos = [x for x in (out.get("aviso"), AVISO_ARQUIVO_VISITANTE,
                              AVISO_SEM_GPS if sem_gps else None) if x]
        out["aviso"] = " ".join(avisos)
        self._ev("upload", tipo=tipo, mb=round(n / MIB, 2), sem_gps=sem_gps)
        self._evento_turno("arquivo", out, t0, fora0, livre=True, tipo=tipo)
        return out


# ---------------------------------------------------------------------------
# Gerenciador das cópias
# ---------------------------------------------------------------------------


class _CriacoesPorIP:
    """Cópias novas por IP numa janela deslizante (chamar com a trava do gerenciador). `maximo` <= 0: sem limite."""

    def __init__(self, maximo: int, janela_s: float):
        self.maximo, self.janela_s = maximo, janela_s
        self._por_ip: dict[str, deque[float]] = {}
        self._poda = 0.0

    def permitir(self, ip: str, agora: float) -> bool:
        if self.maximo <= 0:
            return True
        if agora - self._poda >= 60:  # IPs sem criação na janela saem do mapa
            self._poda = agora
            for k in [k for k, q in self._por_ip.items() if not q or agora - q[-1] >= self.janela_s]:
                del self._por_ip[k]
        q = self._por_ip.get(ip)
        while q and agora - q[0] >= self.janela_s:
            q.popleft()
        return q is None or len(q) < self.maximo

    def registrar(self, ip: str, agora: float) -> None:
        self._por_ip.setdefault(ip, deque()).append(agora)


class GerenciadorSessoes:
    """Cópias vivas por cookie: cria (com o caso aberto), entrega e apaga as paradas há mais de `ttl_s`; com o teto
    cheio, tira a ociosa (`_escolher_expulsa`); limita as cópias novas por IP (`_CriacoesPorIP`)."""

    BASE = "_base"

    def __init__(self, cfg: Config, limites: Limites | None = None, raiz: Path | None = None,
                 transcritor: Any | None = None, relogio: Callable[[], float] = time.time):
        self.cfg_base = cfg
        self.limites = limites or Limites.do_ambiente()
        self.raiz = Path(raiz or os.environ.get("LAUDO_DEMO_DIR") or Path(tempfile.gettempdir()) / "laudo-demo-publica")
        self.transcritor = transcritor
        self.relogio = relogio
        self.lock = threading.Lock()
        self.sessoes: dict[str, Sessao] = {}
        self._criando: dict[str, threading.Event] = {}
        self.casos: dict[str, Any] = {}
        self.videos_preset: set[str] | None = None
        self._por_ip = _CriacoesPorIP(self.limites.copias_por_ip, self.limites.janela_ip_s)
        # as cópias não sobrevivem ao processo: a pasta recomeça vazia
        shutil.rmtree(self.raiz, ignore_errors=True)
        self.raiz.mkdir(parents=True, exist_ok=True)
        # cópia de base: lê os casos uma vez e responde a saúde de quem ainda não tem cópia (sem criar uma)
        self.base = self._criar(self.BASE, abrir=False)

    @staticmethod
    def sid_de(token: str) -> str:
        return hashlib.sha256(f"laudo-demo-publica:{token}".encode()).hexdigest()[:20]

    def _criar(self, sid: str, abrir: bool = True) -> Sessao:
        dados = self.raiz / sid
        ctx = isolamento.Contexto(traces=dados / "traces", sessao=sid[:10])
        s = Sessao(sid=sid, dados=dados, contexto=ctx, gerenciador=self, criada=self.relogio(), usada=self.relogio())
        cfg = dataclasses.replace(self.cfg_base, dados=dados)
        with isolamento.ativo(ctx):
            s.servico = ServicoPublico(cfg, s, transcritor=self.transcritor)
            if abrir:  # dados pré-selecionados: o caso de demonstração já aberto, no passo 1
                s.servico.abrir_caso(s.servico.caso_padrao)
        return s

    def obter(self, token: str | None, criar: bool = True, ip: str | None = None) -> Sessao | None:
        """A cópia do cookie; sem ela (e `criar`), cria uma. Antes de criar: o limite de cópias novas por IP
        (`ip`, o do visitante; vazio, sem limite) e, com o teto de cópias vivas cheio, a saída de uma cópia ociosa
        (`_escolher_expulsa`); só recusa (429) quando todas estão em uso."""
        if not token_valido(token):
            if not criar:
                return None
            raise ErroServico(400, "sessão inválida: recarregue a página")
        sid = self.sid_de(token or "")
        while True:
            velhas: list[Sessao] = []
            expulsa: Sessao | None = None
            recusa: str | None = None
            dono = False
            vivas = 0
            with self.lock:
                s = self.sessoes.get(sid)
                if s is not None:
                    s.usada = self.relogio()
                    return s
                if not criar:
                    return None
                espera = self._criando.get(sid)
                if espera is None:
                    agora = self.relogio()
                    velhas = self._expiradas()
                    vivas = len(self.sessoes) + len(self._criando)
                    if ip and not self._por_ip.permitir(ip, agora):
                        recusa = "ip"
                    elif vivas >= self.limites.max_sessoes:
                        expulsa = self._escolher_expulsa(agora)
                        if expulsa is None:
                            recusa = "copias"
                        else:
                            self.sessoes.pop(expulsa.sid, None)
                            velhas.append(expulsa)
                    if recusa is None:
                        if ip:
                            self._por_ip.registrar(ip, agora)
                        espera = self._criando[sid] = threading.Event()
                        dono = True
            if expulsa is not None:
                eventos.evento("copia_expulsa", sessao=expulsa.curta, intocada=not expulsa.tocada,
                               ociosa_s=int(self.relogio() - expulsa.usada), vivas=vivas)
            self._apagar(velhas)  # fora da trava do mapa: espera o turno em andamento da cópia vencida
            if recusa == "ip":
                raise ErroLimite("ip", "Limite da demonstração: muitas cópias novas desta rede agora. Tente de novo "
                                 "em alguns minutos.", sessao=sid[:10])
            if recusa == "copias":
                raise ErroLimite("copias", "Limite da demonstração: muita gente usando agora. Tente de novo em "
                                 "alguns minutos.", sessao=sid[:10], vivas=vivas)
            if not dono:
                assert espera is not None
                espera.wait(60)
                continue
            nova: Sessao | None = None
            try:
                nova = self._criar(sid)
            finally:
                with self.lock:
                    if nova is not None:
                        self.sessoes[sid] = nova
                    self._criando.pop(sid).set()
                    vivas = len(self.sessoes)
            eventos.evento("sessao_nova", sessao=nova.curta, vivas=vivas)
            return nova

    def _escolher_expulsa(self, agora: float) -> Sessao | None:
        """Teto cheio (chamar com `self.lock`): a cópia que sai para a nova entrar. Primeiro a intocada (só a
        criação e leituras: o visitante dela volta no passo 1, igual, no próximo pedido) parada há
        `ociosa_intocada_s`; depois a usada parada há `ociosa_s`; em cada grupo, a usada há mais tempo e sem
        pedido em andamento. None: todas em uso (recusa)."""
        lim = self.limites
        intocadas = [s for s in self.sessoes.values() if not s.tocada and agora - s.usada >= lim.ociosa_intocada_s]
        usadas = [s for s in self.sessoes.values() if s.tocada and agora - s.usada >= lim.ociosa_s]
        for grupo in (intocadas, usadas):
            for s in sorted(grupo, key=lambda x: x.usada):
                srv = s.servico
                if srv is None or srv.lock.acquire(blocking=False):  # sem pedido em andamento
                    if srv is not None:
                        srv.lock.release()
                    return s
        return None

    def fachada(self, token: str | None, criar: bool = True, ip: str | None = None) -> FachadaSessao | None:
        s = self.obter(token, criar=criar, ip=ip)
        return FachadaSessao(self, s) if s is not None else None

    def fachada_base(self) -> FachadaSessao:
        return FachadaSessao(self, self.base)

    def _expiradas(self) -> list[Sessao]:
        """Tira do mapa as cópias paradas há mais de `ttl_s` (chamar com `self.lock`)."""
        agora = self.relogio()
        velhas = [s for s in self.sessoes.values() if agora - s.usada > self.limites.ttl_s]
        for s in velhas:
            self.sessoes.pop(s.sid, None)
        return velhas

    def _apagar(self, velhas: list[Sessao]) -> None:
        for s in velhas:
            srv = s.servico
            # espera um turno em andamento terminar antes de apagar a pasta
            if srv is not None and srv.lock.acquire(timeout=30):
                srv.lock.release()
            shutil.rmtree(s.dados, ignore_errors=True)

    def limpar(self) -> int:
        """Apaga as cópias vencidas; devolve quantas."""
        with self.lock:
            velhas = self._expiradas()
        self._apagar(velhas)
        return len(velhas)

    def vivas(self) -> int:
        with self.lock:
            return len(self.sessoes)


# ---------------------------------------------------------------------------
# Foto do visitante: sem GPS no arquivo e classificação só do cache do VLM
# ---------------------------------------------------------------------------

MOTIVO_VLM_DESLIGADO = "leitura da foto por IA desligada nesta demonstração; use as fotos prontas do caso"
_TAG_GPS, _TAG_EXIF, _TAG_MAKERNOTE = 0x8825, 0x8769, 0x927C
_XMP = (b"http://ns.adobe.com/xap/1.0/\x00", b"http://ns.adobe.com/xmp/extension/\x00")


def classificacao_so_do_cache(ferr: Ferramenta) -> Ferramenta:
    """A mesma `classificar_foto` (nome, descrição e esquema iguais: o pedido ao LLM não muda). Com o VLM só do
    cache (`LAUDO_VLM_SO_CACHE=1`, a demo pública), a foto fora do cache (a do visitante) volta "indeterminado"
    com o motivo, e não "erro interno da ferramenta" (que levaria o agente a falar de falha nas ferramentas)."""
    original = ferr.funcao

    def funcao(args: Any) -> Envelope:
        env = original(args)
        so_cache = (os.environ.get("LAUDO_VLM_SO_CACHE") or "") == "1"
        if env.ok or not so_cache or env.error is None or env.error.code not in (CodigoErro.ERRO_INTERNO,
                                                                                 CodigoErro.TIMEOUT):
            return env
        foto = Path(args.caminho_foto)
        dados: dict[str, Any] = {"status": "indeterminado", "abstencao": True, "motivo": MOTIVO_VLM_DESLIGADO,
                                 "vlm": "desligado", "caminho": foto.as_posix()}
        if args.classe_esperada:
            dados["classe_esperada"] = args.classe_esperada
        if foto.is_file():
            dados["sha256"] = sha256_arquivo(str(foto))
        return Envelope.sucesso(ferr.nome, dados, fonte_versao="vlm-desligado-demo-publica")

    return ferr.model_copy(update={"funcao": funcao})


def _exif_sem_gps(corpo: bytes) -> bytes | None:
    """O segmento EXIF (b"Exif\\0\\0" + TIFF) sem o IFD de GPS e sem a MakerNote (que pode trazer posição);
    None: não há o que tirar. Levanta exceção se o EXIF não for legível (quem chama descarta o segmento)."""
    from PIL import Image

    ex = Image.Exif()
    ex.load(corpo)
    sub = ex.get_ifd(_TAG_EXIF)
    if _TAG_GPS not in ex and _TAG_MAKERNOTE not in sub:
        return None
    ex.pop(_TAG_GPS, None)
    sub.pop(_TAG_MAKERNOTE, None)
    novo = ex.tobytes()
    if len(novo) > 65533:
        raise ValueError("EXIF grande demais")
    return novo


def _jpeg_sem_gps(dados: bytes) -> bytes | None:
    """JPEG sem o GPS do EXIF e sem XMP, trocando só os segmentos de metadados (a imagem não é recodificada).
    None: nada a tirar, ou estrutura inesperada (quem chama recodifica)."""
    if not dados.startswith(b"\xff\xd8"):
        return None
    out, i, mudou = bytearray(b"\xff\xd8"), 2, False
    while i + 4 <= len(dados):
        if dados[i] != 0xFF:
            return None
        marca = dados[i + 1]
        if marca == 0xFF:  # preenchimento entre segmentos
            i += 1
            continue
        if marca in (0xDA, 0xD9):  # começo da imagem (SOS) ou fim: o resto vai igual
            out += dados[i:]
            return bytes(out) if mudou else None
        n = int.from_bytes(dados[i + 2:i + 4], "big")
        if n < 2 or i + 2 + n > len(dados):
            return None
        seg, corpo = dados[i:i + 2 + n], dados[i + 4:i + 2 + n]
        i += 2 + n
        if marca == 0xE1 and corpo.startswith(b"Exif\x00\x00"):
            try:
                novo = _exif_sem_gps(corpo)
            except Exception:  # noqa: BLE001 - EXIF ilegível: sai inteiro
                mudou = True
                continue
            if novo is None:
                out += seg
            else:
                mudou = True
                out += b"\xff\xe1" + (len(novo) + 2).to_bytes(2, "big") + novo
        elif marca == 0xE1 and corpo.startswith(_XMP):
            mudou = True  # o XMP pode repetir a posição (exif:GPSLatitude)
        else:
            out += seg
    return None


def _tem_gps(caminho: Path) -> bool:
    from PIL import Image

    with Image.open(caminho) as img:
        return bool(img.getexif().get_ifd(_TAG_GPS)) or any(k in img.info for k in ("xmp", "XML:com.adobe.xmp"))


def foto_sem_gps(caminho: Path, fmt: str) -> bool:
    """Tira do arquivo a localização gravada pelo aparelho (GPS do EXIF e XMP), no lugar. JPEG: só os segmentos
    de metadados mudam (a data da captura fica, para a integridade); PNG/WebP com GPS, ou JPEG fora do padrão:
    recodificado sem metadados. Devolve se mudou o arquivo."""
    from PIL import Image

    if fmt == "jpeg":
        novo = _jpeg_sem_gps(caminho.read_bytes())
        if novo is not None:
            caminho.write_bytes(novo)
            if not _tem_gps(caminho):
                return True
    try:
        if not _tem_gps(caminho):
            return False
        with Image.open(caminho) as img:
            img.load()
            limpa = img.copy()
        limpa.info = {}
        if fmt == "jpeg":
            limpa.convert("RGB").save(caminho, "JPEG", quality=95)
        elif fmt == "png":
            limpa.save(caminho, "PNG")
        else:
            limpa.save(caminho, "WEBP", quality=95)
    except Exception as e:  # noqa: BLE001 - imagem ilegível: a integridade da foto acusa
        log.info("foto do visitante: GPS não conferido (%s)", type(e).__name__)
        return False
    return True


def eh_nfe(caminho: Path) -> bool:
    """XML com a raiz NFe ou nfeProc (namespace do portal fiscal) e o infNFe, lido sem entidade externa nem
    rede (`docs_fiscais.nfe`)."""
    from lxml import etree

    ns = "{http://www.portalfiscal.inf.br/nfe}"
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, load_dtd=False)
    try:
        raiz = etree.parse(str(caminho), parser).getroot()
    except (etree.XMLSyntaxError, OSError, ValueError):
        return False
    nfe = raiz if raiz.tag == f"{ns}NFe" else raiz.find(f"{ns}NFe") if raiz.tag == f"{ns}nfeProc" else None
    return nfe is not None and nfe.find(f"{ns}infNFe") is not None


# ---------------------------------------------------------------------------
# Contagem do vídeo pronto do caso: do cache (preparado no build)
# ---------------------------------------------------------------------------

_trava_cache = threading.Lock()


def _chave_contagem(args: Any, sha_video: str) -> str:
    base = args.model_dump(mode="json", exclude={"caminho_video", "dir_evidencias", "item_id"})
    return hash_entrada({"video": sha_video, "args": base})


def _prefixo(args: Any) -> str:
    # o mesmo prefixo dos quadros-chave que a ferramenta usaria (tools/bovinos.py)
    return f"{args.modo}_{hash_entrada(args.model_dump())[:6]}"


def contagem_com_cache(ferr: Ferramenta, presets: Callable[[], set[str]],
                       pasta: Path | None = None) -> Ferramenta:
    """A mesma ferramenta (nome, descrição e esquema iguais: o pedido ao LLM não muda); para o vídeo pronto do
    caso (`presets`, por sha256), o resultado vem do cache e os quadros-chave são copiados para a pasta da cópia.
    Vídeo enviado pelo visitante roda o YOLOX normalmente."""
    pasta = pasta or DIR_CACHE_CONTAGEM
    original = ferr.funcao

    def funcao(args: Any) -> Envelope:
        video = Path(args.caminho_video)
        if not video.is_file():
            return original(args)
        sha = sha256_arquivo(str(video))
        if sha not in presets():
            return original(args)
        destino = pasta / _chave_contagem(args, sha)
        arq = destino / "envelope.json"
        with _trava_cache:  # o primeiro calcula; os outros esperam e leem
            if not arq.is_file():
                env = original(args)
                if env.ok and env.data:
                    _gravar_contagem(destino, env)
                return env
        return _restaurar_contagem(arq, args, video)

    return ferr.model_copy(update={"funcao": funcao})


def _gravar_contagem(destino: Path, env: Envelope) -> None:
    try:
        tmp = destino.with_name(destino.name + f".{os.getpid()}.tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True, exist_ok=True)
        d = json.loads(env.model_dump_json())
        for q in d["data"].get("quadros_chave") or []:
            origem = Path(q["caminho"])
            if origem.is_file():
                shutil.copyfile(origem, tmp / origem.name)
            q["caminho"] = origem.name
        if isinstance(d["data"].get("video"), dict):  # o caminho local não vai para o cache (a restauração repõe)
            d["data"]["video"]["caminho"] = Path(d["data"]["video"].get("caminho") or "").name
        (tmp / "envelope.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        shutil.rmtree(destino, ignore_errors=True)
        tmp.replace(destino)
    except OSError as e:  # sem cache, a próxima cópia conta de novo
        log.warning("cache da contagem não gravado: %s", e)


def _restaurar_contagem(arq: Path, args: Any, video: Path) -> Envelope:
    d = json.loads(arq.read_text(encoding="utf-8"))
    dados = d["data"]
    dir_ev = Path(args.dir_evidencias) if args.dir_evidencias else arq.parent
    dir_ev.mkdir(parents=True, exist_ok=True)
    pre = _prefixo(args)
    for q in dados.get("quadros_chave") or []:
        nome = f"{pre}_{int(q['quadro']):06d}.jpg"
        shutil.copyfile(arq.parent / q["caminho"], dir_ev / nome)
        q["caminho"] = (dir_ev / nome).as_posix()
    dados["video"] = {**(dados.get("video") or {}), "caminho": video.as_posix()}
    dados["item_id"] = args.item_id
    return Envelope.model_validate(d)


# ---------------------------------------------------------------------------
# Build: roda o roteiro numa cópia, confere e deixa o cache pronto
# ---------------------------------------------------------------------------


def rodar_roteiro(fach: FachadaSessao, fis: str, imprimir: bool = False) -> dict[str, Any]:
    """Executa os passos que faltam do roteiro (como um visitante tocando em "Executar passo"), com a assinatura
    pelo PIN de demonstração. Devolve passos, etapa, requisições fora da gravação e substituições nos passos, os
    vereditos da matriz e os ids da cadeia."""
    from laudo.api.servico import PIN_DEMO

    fora0, sub0, n = fach._fora(), fach._substituicoes(), 0
    while True:
        try:
            out = fach.passo_roteiro(fis)
        except ErroServico as e:
            if e.status == 409:
                break
            raise
        n += 1
        if imprimir:
            print(f"[{n:02d}] {out['passo']['titulo']}", flush=True)
        if out.get("acao_humana") == "assinar":
            fach.assinar(fis, PIN_DEMO, fach.estado(fis)["laudo"]["hash_raiz"])
    e = fach.estado(fis)
    return {"passos": n, "etapa": e["etapa"], "fora": fach._fora() - fora0,
            "substituicoes": fach._substituicoes() - sub0, "matriz": _vereditos(e),
            # os ids da cadeia (evidências, falas e checagens) saem da sequência gravada: iguais em toda cópia; o
            # hash raiz não (spans e horários de cada execução)
            "ids": [x["id"] for k in ("evidencias", "falas", "checagens") for x in e.get(k) or []]}


def _vereditos(estado: dict[str, Any]) -> list[tuple[Any, ...]]:
    """O veredito de cada linha da matriz do laudo (para comparar o roteiro limpo com o que teve ação livre)."""
    out = []
    for linha in estado.get("matriz") or []:
        if isinstance(linha, dict):
            out.append(tuple(str(linha.get(k)) for k in sorted(linha) if k in ("campo", "item_id", "status", "valor")))
    return out


def foto_de_teste_com_gps() -> bytes:
    """JPEG pequeno com GPS no EXIF e data de captura antiga (a foto da galeria de um visitante)."""
    import io

    from PIL import Image

    ex = Image.Exif()
    ex[0x0110] = "Celular de teste"
    ex[_TAG_EXIF] = {0x9003: "2026:10:20 09:15:00"}
    ex[_TAG_GPS] = {1: "S", 2: (16.0, 35.0, 54.0), 3: "W", 4: (49.0, 16.0, 41.0)}
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (120, 140, 90)).save(buf, "JPEG", exif=ex.tobytes())
    return buf.getvalue()


def preparar(caso: str = "DEMO-0001", replay: str | None = None) -> int:
    """Roteiro inteiro numa cópia da demo pública, com a assinatura pelo PIN de demonstração, e de novo noutra
    cópia depois de uma mensagem livre e de uma foto do visitante (com GPS no EXIF). 0 = as duas SELADAS, nenhuma
    requisição dos passos fora da gravação (nem substituída) e o mesmo laudo; grava o cache da contagem."""
    import io

    os.environ.setdefault(ENV, "1")
    os.environ.setdefault("LAUDO_VLM_CACHE", str(REPO / "tests" / "unit" / "dados_agente" / "vlm_cache_demo"))
    os.environ.setdefault("LAUDO_VLM_SO_CACHE", "1")
    raiz = Path(tempfile.mkdtemp(prefix="laudo-demo-preparar-"))
    try:
        cfg = Config(llm="publico", ferramentas="reais", caso=caso, asr="desligado", replay=replay,
                     provedor_livre=_SemLLM())
        ger = GerenciadorSessoes(cfg, Limites(), raiz=raiz / "sessoes")
        fach = ger.fachada(novo_token())
        assert fach is not None
        fis = fach.estado(fach.servico.caso(caso).fis_id)["id"]
        t0 = time.perf_counter()
        limpo = rodar_roteiro(fach, fis, imprimir=True)
        print(f"demo pública: {limpo['passos']} passos em {time.perf_counter() - t0:.1f} s, etapa {limpo['etapa']}, "
              f"{limpo['fora']} fora da gravação, {limpo['substituicoes']} substituições; cache da contagem em "
              f"{DIR_CACHE_CONTAGEM}", flush=True)
        ok = limpo["etapa"] == "SELADO" and limpo["fora"] == 0 and limpo["substituicoes"] == 0
        # o visitante pergunta e manda a foto dele antes do passo 1: os passos continuam saindo da gravação
        outra = ger.fachada(novo_token())
        assert outra is not None
        outra.turno(fis, "Explique em uma frase o que a fiscalização confere aqui.")
        foto = outra.upload(fis, "foto_visitante.jpg", io.BytesIO(foto_de_teste_com_gps()), "foto", item_id="cerca1")
        vazou = "-16.59" in json.dumps(foto, ensure_ascii=False)  # a posição do EXIF não pode voltar
        livre = rodar_roteiro(outra, fis)
        igual = livre["matriz"] == limpo["matriz"] and livre["ids"] == limpo["ids"]
        print(f"com mensagem livre e foto do visitante: {livre['passos']} passos, etapa {livre['etapa']}, "
              f"{livre['fora']} fora da gravação nos passos, {livre['substituicoes']} substituições, laudo "
              f"{'igual' if igual else 'DIFERENTE'} ao do roteiro limpo, GPS da foto {'VAZOU' if vazou else 'apagado'}",
              flush=True)
        ok = ok and livre["etapa"] == "SELADO" and livre["fora"] == 0 and livre["substituicoes"] == 0 and igual             and not vazou
        return 0 if ok else 1
    finally:
        est.ids_deterministicos(None)
        shutil.rmtree(raiz, ignore_errors=True)


class _SemLLM:
    """Segundo elo da cadeia no build: nenhum LLM ao vivo (o roteiro inteiro tem de sair da gravação)."""

    nome = "nenhum"
    modelo = ""
    externo = False

    def chat(self, *_a: Any, **_k: Any):
        from laudo.llm.provider import ErroLLM

        raise ErroLLM("INDISPONIVEL", "sem LLM ao vivo no preparo da imagem")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preparar", action="store_true", help="roteiro inteiro numa cópia; grava o cache da contagem")
    ap.add_argument("--caso", default="DEMO-0001")
    ap.add_argument("--replay", default=None)
    a = ap.parse_args()
    if not a.preparar:
        ap.print_help()
        sys.exit(2)
    logging.basicConfig(level=logging.WARNING)
    sys.exit(preparar(a.caso, a.replay))
