"""Persistência da `Fiscalizacao` e operações append-only sobre o estado.

- Um JSON por fiscalização em `dados_locais/fiscalizacoes/<id>.json`, gravado de forma atômica
  (arquivo temporário + `os.replace`), para retomar após queda do processo.
- `salvar` confere contra a versão anterior em disco: evidências, checagens, alegações, ocorrências e
  aprovações são **append-only** (prefixo idêntico) e a cadeia de hash precisa estar íntegra (POL-04).
  Fiscalização SELADA não aceita nenhuma alteração.
- A conversa (fala do fiscal e fala do agente, mascaradas) vai para `<id>.conversa.jsonl`, também
  append-only; serve de memória episódica do turno e de trilha.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from laudo import isolamento
from laudo.agent.pii import mascarar_obj
from laudo.audit import hashchain
from laudo.contracts import (
    GPS,
    Checagem,
    CodigoErro,
    Envelope,
    Evidencia,
    Fiscalizacao,
    Ocorrencia,
    Operacao,
    StatusChecagem,
    TipoEvidencia,
    para_status_checagem,
    sha256_arquivo,
    sha256_bytes,
)
from laudo.privacidade import proteger_resultado

_REPO = Path(__file__).resolve().parents[3]
_LISTAS_APPEND_ONLY = ("evidencias", "checagens", "alegacoes", "ocorrencias", "aprovacoes")
_IDS: dict[str, Any] = {"semente": None, "n": 0}


def _ids() -> dict[str, Any]:
    """Contador de ids em uso: o da cópia do visitante na demo pública (`laudo.isolamento`), senão o do
    processo."""
    ctx = isolamento.atual()
    return ctx.ids if ctx is not None else _IDS


def ids_deterministicos(semente: str | None) -> None:
    """Liga (semente) ou desliga (None) ids reprodutíveis para evidências, checagens, ocorrências e alegações.
    Usado no replay da demo e em testes; em produção os ids são aleatórios."""
    ids = _ids()
    ids["semente"], ids["n"] = semente, 0


def novo_id(prefixo: str) -> str:
    ids = _ids()
    if ids["semente"] is None:
        return f"{prefixo}_{uuid.uuid4().hex[:10]}"
    ids["n"] += 1
    return f"{prefixo}_{sha256_bytes(f'{ids["semente"]}:{ids["n"]}'.encode())[:10]}"


def diretorio_dados() -> Path:
    base = os.environ.get("LAUDO_DADOS_DIR")
    return Path(base) if base else _REPO / "dados_locais"


class ViolacaoAppendOnly(Exception):
    """Tentativa de alterar ou apagar registro já gravado (POL-04)."""


class FiscalizacaoSelada(ViolacaoAppendOnly):
    """Tentativa de alterar fiscalização selada (POL-04)."""


def violacoes_append_only(anterior: Fiscalizacao, nova: Fiscalizacao) -> list[str]:
    """Lista de violações de append-only entre duas versões do mesmo estado."""
    erros: list[str] = []
    if anterior.id != nova.id:
        return [f"id diferente: {anterior.id} != {nova.id}"]
    for nome in _LISTAS_APPEND_ONLY:
        a = [_dump(x) for x in getattr(anterior, nome)]
        n = [_dump(x) for x in getattr(nova, nome)]
        if len(n) < len(a):
            erros.append(f"{nome}: {len(a) - len(n)} registro(s) removido(s)")
            continue
        for i, (xa, xn) in enumerate(zip(a, n)):
            if xa != xn:
                erros.append(f"{nome}[{i}] alterado")
                break
    if anterior.estado_fsm != "BRIEFING" and _dump(anterior.operacao) != _dump(nova.operacao):
        erros.append("operacao alterada fora do BRIEFING")
    if anterior.estado_fsm == "SELADO" and _dump(anterior) != _dump(nova):
        erros.append("fiscalização selada não pode ser alterada")
    return erros


def _dump(x: Any) -> Any:
    return x.model_dump(mode="json") if hasattr(x, "model_dump") else x


class RepositorioFiscalizacoes:
    def __init__(self, diretorio: str | Path | None = None):
        base = Path(diretorio) if diretorio else diretorio_dados()
        self.dir = base / "fiscalizacoes"
        self.dir.mkdir(parents=True, exist_ok=True)

    def caminho(self, fis_id: str) -> Path:
        seguro = "".join(c for c in fis_id if c.isalnum() or c in "_-")
        if not seguro or seguro != fis_id:
            raise ValueError(f"id de fiscalização inválido: {fis_id!r}")
        return self.dir / f"{seguro}.json"

    def existe(self, fis_id: str) -> bool:
        return self.caminho(fis_id).exists()

    def criar(self, operacao: Operacao, **campos: Any) -> Fiscalizacao:
        fis = Fiscalizacao(operacao=operacao, **campos)
        self.salvar(fis)
        return fis

    def carregar(self, fis_id: str) -> Fiscalizacao:
        with open(self.caminho(fis_id), encoding="utf-8") as f:
            return Fiscalizacao.model_validate_json(f.read())

    def listar(self) -> list[str]:
        return sorted(p.stem for p in self.dir.glob("fis_*.json"))

    def salvar(self, fis: Fiscalizacao) -> None:
        cadeia = hashchain.verificar_cadeia(fis.evidencias)
        if not cadeia.integra:
            raise ViolacaoAppendOnly(f"cadeia de hash quebrada: {cadeia.motivo}")
        destino = self.caminho(fis.id)
        if destino.exists():
            anterior = self.carregar(fis.id)
            erros = violacoes_append_only(anterior, fis)
            if erros:
                cls = FiscalizacaoSelada if anterior.estado_fsm == "SELADO" else ViolacaoAppendOnly
                raise cls("; ".join(erros))
        fd, tmp = tempfile.mkstemp(prefix=f".{fis.id}.", suffix=".tmp", dir=self.dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(fis.model_dump_json(indent=1))
            os.replace(tmp, destino)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    # -- conversa ------------------------------------------------------------
    def anexar_conversa(self, fis_id: str, registro: dict[str, Any]) -> None:
        caminho = self.caminho(fis_id).with_suffix(".conversa.jsonl")
        linha = mascarar_obj({"em": datetime.now().astimezone().isoformat(timespec="seconds"), **registro})
        with open(caminho, "a", encoding="utf-8") as f:
            f.write(json.dumps(linha, ensure_ascii=False, default=str) + "\n")

    def ler_conversa(self, fis_id: str, ultimos: int | None = None) -> list[dict[str, Any]]:
        caminho = self.caminho(fis_id).with_suffix(".conversa.jsonl")
        if not caminho.exists():
            return []
        with open(caminho, encoding="utf-8") as f:
            linhas = [json.loads(x) for x in f if x.strip()]
        return linhas[-ultimos:] if ultimos else linhas


# ---------------------------------------------------------------------------
# Operações sobre o estado (puras: mutam o objeto em memória; quem persiste é o repositório)
# ---------------------------------------------------------------------------


def adicionar_evidencia(
    fis: Fiscalizacao,
    tipo: TipoEvidencia,
    *,
    conteudo: bytes | None = None,
    caminho: str | None = None,
    sha256: str | None = None,
    meta: dict[str, Any] | None = None,
    gps: GPS | None = None,
    capturada_em: datetime | None = None,
    recebida_em: datetime | None = None,
    derivada_de: str | None = None,
) -> Evidencia:
    """Registra evidência nova no fim da cadeia. O sha256 vem do conteúdo, do arquivo ou é informado
    (quando o hash foi calculado na captura, no celular)."""
    if fis.estado_fsm == "SELADO":
        raise FiscalizacaoSelada("fiscalização selada: correção vira nova fiscalização (POL-04)")
    if sha256 is None:
        if conteudo is not None:
            sha256 = sha256_bytes(conteudo)
        elif caminho is not None and Path(caminho).exists():
            sha256 = sha256_arquivo(caminho)
        else:
            raise ValueError("evidência sem conteúdo, sem arquivo e sem sha256")
    ev = Evidencia(
        id=novo_id("ev"),
        tipo=tipo,
        caminho=caminho,
        sha256=sha256,
        meta=dict(meta or {}),
        gps=gps,
        capturada_em=capturada_em,
        derivada_de=derivada_de,
        **({"recebida_em": recebida_em} if recebida_em is not None else {}),
    )
    return hashchain.anexar(fis.evidencias, ev)


# Sinônimos aceitos além do mapa comum (`contracts._MAPA_STATUS`); proposta de inclusão no contrato.
_SINONIMOS_EXTRAS: dict[str, StatusChecagem] = {
    "válido": "ok",
    "integra": "ok",
    "íntegra": "ok",
    "nao_conforme": "divergente",
    "incoerente": "divergente",
    "inválido": "divergente",
    "suspeita": "divergente",
    "abstenção": "indeterminado",
    "inconclusivo": "indeterminado",
}


def status_de_envelope(env: Envelope) -> StatusChecagem:
    """Traduz o envelope de uma ferramenta em status de checagem (`contracts.para_status_checagem`).

    Falha nunca vira "ok"; envelope ok **sem** `data.status` também não (seria um falso "verificado"
    silencioso): vira "indeterminado".
    """
    if not env.ok:
        if env.error and env.error.code in (CodigoErro.NUVEM, CodigoErro.SEM_DADOS):
            return "indeterminado"
        return "erro"
    bruto = (env.data or {}).get("status")
    chave = str(bruto).strip().lower() if bruto is not None else ""
    if chave in _SINONIMOS_EXTRAS:
        return _SINONIMOS_EXTRAS[chave]
    return para_status_checagem(chave or None)  # type: ignore[return-value]


def registrar_checagem(
    fis: Fiscalizacao,
    ferramenta: str,
    entrada_hash: str,
    env: Envelope,
    item_id: str | None = None,
    evidencias: list[str] | None = None,
    span_id: str | None = None,
    cofre: Any | None = None,
) -> Checagem:
    """Registra a checagem. O resultado vai para o estado sem chave de acesso da NF-e em claro (máscara + hash com
    o sal da instalação; a chave inteira, cifrada no `cofre` da fiscalização: `laudo.privacidade`)."""
    data = dict(env.data or {})
    if not env.ok and env.error:
        data.setdefault(
            "erro", {"code": str(env.error.code), "msg": env.error.msg, "retryable": env.error.retryable}
        )
    chk = Checagem(
        id=novo_id("chk"),
        ferramenta=ferramenta,
        entrada_hash=entrada_hash,
        status=status_de_envelope(env),
        resultado=proteger_resultado(data, fis.id, cofre),
        evidencias=list(evidencias or []),
        item_id=item_id or data.get("item_id"),
        regra_id=data.get("regra_id"),
        trace_id=span_id,
        fonte_versao=env.fonte_versao,
    )
    fis.checagens.append(chk)
    return chk


def checagem_existente(fis: Fiscalizacao, ferramenta: str, entrada_hash: str) -> Checagem | None:
    """Idempotência: mesma ferramenta com a mesma entrada já checada (e sem erro) não roda de novo."""
    for chk in reversed(fis.checagens):
        if chk.ferramenta == ferramenta and chk.entrada_hash == entrada_hash and chk.status != "erro":
            return chk
    return None


def registrar_ocorrencia(
    fis: Fiscalizacao, tipo: str, descricao: str, evidencia_ref: str | None = None
) -> Ocorrencia:
    """Ocorrência (pressão, injeção, falha) entra no estado e também na cadeia de hash, como evidência
    do tipo "ocorrencia", para não poder ser apagada sem deixar rastro."""
    oc = Ocorrencia(
        id=novo_id("oc"),
        tipo=tipo,
        descricao=descricao,  # type: ignore[arg-type]
        evidencia_ref=evidencia_ref,
    )
    corpo = json.dumps(oc.model_dump(mode="json"), sort_keys=True, ensure_ascii=False).encode("utf-8")
    adicionar_evidencia(
        fis,
        "ocorrencia",
        conteudo=corpo,
        meta={"ocorrencia_id": oc.id, "tipo": tipo, "descricao": descricao[:500]},
    )
    fis.ocorrencias.append(oc)
    return oc


def registrar_alegacao(fis: Fiscalizacao, alegacao: dict[str, Any]) -> dict[str, Any]:
    a = {"id": novo_id("alg"), **alegacao}
    fis.alegacoes.append(a)
    return a


def evidencia_por_id(fis: Fiscalizacao, ev_id: str | None) -> Evidencia | None:
    if not ev_id:
        return None
    return next((e for e in fis.evidencias if e.id == ev_id), None)
