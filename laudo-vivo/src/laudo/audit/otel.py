"""Tracing com OpenTelemetry SDK exportando spans para JSONL local (trilha de auditoria = trace).

- Um arquivo por fiscalização em `dados_locais/traces/<fiscalizacao_id>.jsonl` (spans sem fiscalização vão
  para `geral.jsonl`). O id da fiscalização vem de um `ContextVar` que o condutor define por turno e que um
  `SpanProcessor` copia para o atributo `laudo.fiscalizacao_id` de cada span.
- Três famílias de span: LLM (`gen_ai.*`, convenções semânticas GenAI), ferramenta (`tool.*`, com hash dos
  argumentos, nunca os argumentos crus) e decisão de política (`policy.rule_id`, `policy.resultado`).
- POL-08: todo atributo e evento passa por `mascarar_obj` antes de ir para o disco, menos o que o código gera
  e precisa aparecer como é na trilha: atributos de versão (`*.versao`, `*fonte_versao`, `*.version`:
  `mcr_2_7@0.3.0`, `condutor.v3@1a2b3c4d`), quando o valor tem forma de versão (um token só, com letra), e
  identificadores técnicos (`span_id`, `trace_id`, `tool.args_hash`, `llm.chave`, `laudo.fiscalizacao_id`),
  quando o valor é hex com pelo menos uma letra. Sem essa exceção, `x@0.3.0` viraria "[EMAIL]" e ~0,1% dos
  span_id e ~0,5% dos sha256 (11 ou 14 dígitos seguidos) virariam "[TELEFONE]"/"[CNPJ]"
  (`"tool.envelope_trace_id": "[TELEFONE]c48ba"`), quebrando o link do laudo para o span. Valor só de
  dígitos (CPF, CNPJ, chave de acesso) continua mascarado em qualquer chave.

Não usa o TracerProvider global do OpenTelemetry (que só pode ser definido uma vez): mantém um provedor
próprio, reconfigurável em testes com `configurar(diretorio)`.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import Span, Status, StatusCode

from laudo.agent.pii import mascarar_obj
from laudo.contracts import hash_entrada

_REPO = Path(__file__).resolve().parents[3]
# Atributos de versão (gerados pelo código, nunca dado de pessoa): ficam fora da máscara do POL-08 quando o
# valor tem forma de versão (um token, com letra: `mcr_2_7@0.3.0+contador@0.2.0`); texto com espaço é
# mascarado.
_ATRIBUTO_VERSAO = re.compile(r"(?:^|[._])(?:fonte_)?(?:versao|version)$")
_VALOR_VERSAO = re.compile(r"(?=[^\s]*[A-Za-z])[\w.+@:/-]{1,200}")
# Identificadores técnicos (span, trace, hash dos argumentos, chave de replay, ids fis_/chk_/ev_): hex gerado
# pelo código. Só valor hex com pelo menos uma letra (prefixo curto opcional) fica fora da máscara.
_CHAVE_TECNICA = re.compile(
    r"(?:^|[._])(?:trace_id|span_id|fiscalizacao_id|checagem_id|evidencia_id|args_hash|entrada_hash|chave)$"
)
_VALOR_TECNICO = re.compile(r"(?:[a-z]{2,4}_)?(?=[0-9a-f]*[a-f])[0-9a-f]{8,64}")
_fiscalizacao_atual: ContextVar[str | None] = ContextVar("laudo_fiscalizacao_atual", default=None)
_lock = threading.Lock()
_estado: dict[str, Any] = {"provider": None, "tracer": None, "diretorio": None}


def diretorio_padrao() -> Path:
    base = os.environ.get("LAUDO_DADOS_DIR")
    return (Path(base) if base else _REPO / "dados_locais") / "traces"


def _ns_iso(ns: int | None) -> str | None:
    if ns is None:
        return None
    return datetime.fromtimestamp(ns / 1e9, tz=UTC).isoformat()


def span_para_dict(s: ReadableSpan) -> dict[str, Any]:
    ctx = s.get_span_context()
    dur = (s.end_time - s.start_time) / 1e6 if s.end_time and s.start_time else None
    return {
        "name": s.name,
        "trace_id": format(ctx.trace_id, "032x"),
        "span_id": format(ctx.span_id, "016x"),
        "parent_span_id": format(s.parent.span_id, "016x") if s.parent else None,
        "start": _ns_iso(s.start_time),
        "end": _ns_iso(s.end_time),
        "duration_ms": round(dur, 3) if dur is not None else None,
        "status": s.status.status_code.name,
        "status_msg": s.status.description,
        "attributes": dict(s.attributes or {}),
        "events": [
            {"name": e.name, "time": _ns_iso(e.timestamp), "attributes": dict(e.attributes or {})}
            for e in s.events
        ],
    }


def eh_atributo_de_versao(chave: str) -> bool:
    return bool(_ATRIBUTO_VERSAO.search(chave))


def eh_id_tecnico(chave: str, valor: Any) -> bool:
    """Identificador técnico gerado pelo código (chave de id/hash e valor hex com letra): não é dado
    pessoal."""
    return (isinstance(valor, str) and bool(_CHAVE_TECNICA.search(chave))
            and bool(_VALOR_TECNICO.fullmatch(valor)))


def _fora_da_mascara(chave: str, valor: Any) -> bool:
    if eh_atributo_de_versao(chave):
        return isinstance(valor, str) and bool(_VALOR_VERSAO.fullmatch(valor))
    return eh_id_tecnico(chave, valor)


def mascarar_span(d: dict[str, Any]) -> dict[str, Any]:
    """POL-08 sobre o span exportado: tudo mascarado, menos versões e identificadores técnicos."""
    attrs = d.get("attributes") or {}
    saida = {k: (v if _fora_da_mascara(k, v) else mascarar_obj(v)) for k, v in d.items() if k != "attributes"}
    saida["attributes"] = {k: (v if _fora_da_mascara(k, v) else mascarar_obj(v)) for k, v in attrs.items()}
    return saida


class ExportadorJSONL(SpanExporter):
    """Grava cada span como uma linha JSON (mascarada) no arquivo da fiscalização."""

    def __init__(self, diretorio: Path):
        self.diretorio = Path(diretorio)
        self.diretorio.mkdir(parents=True, exist_ok=True)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        try:
            with _lock:
                for s in spans:
                    d = mascarar_span(span_para_dict(s))
                    fis = d["attributes"].get("laudo.fiscalizacao_id") or "geral"
                    nome = "".join(c for c in str(fis) if c.isalnum() or c in "_-") or "geral"
                    with open(self.diretorio / f"{nome}.jsonl", "a", encoding="utf-8") as f:
                        f.write(json.dumps(d, ensure_ascii=False, default=str) + "\n")
            return SpanExportResult.SUCCESS
        except OSError:
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:  # nada a liberar
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


class ProcessadorContexto(SpanProcessor):
    """Copia o id da fiscalização corrente (ContextVar) para os atributos de cada span."""

    def on_start(self, span: Span, parent_context=None) -> None:
        fis = _fiscalizacao_atual.get()
        if fis:
            span.set_attribute("laudo.fiscalizacao_id", fis)

    def on_end(self, span: ReadableSpan) -> None:
        return None

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


def configurar(diretorio: str | Path | None = None) -> Path:
    """(Re)configura o provedor de traces. Devolve o diretório onde os JSONL serão gravados."""
    d = Path(diretorio) if diretorio else diretorio_padrao()
    provider = TracerProvider(
        resource=Resource.create({"service.name": "laudo-vivo", "service.version": "0.1.0"})
    )
    provider.add_span_processor(ProcessadorContexto())
    provider.add_span_processor(SimpleSpanProcessor(ExportadorJSONL(d)))
    _estado.update(provider=provider, tracer=provider.get_tracer("laudo.agent"), diretorio=d)
    return d


def tracer():
    if _estado["tracer"] is None:
        configurar()
    return _estado["tracer"]


def diretorio_traces() -> Path:
    if _estado["diretorio"] is None:
        configurar()
    return _estado["diretorio"]


def arquivo_trace(fiscalizacao_id: str) -> Path:
    return diretorio_traces() / f"{fiscalizacao_id}.jsonl"


@contextmanager
def contexto_fiscalizacao(fiscalizacao_id: str | None) -> Iterator[None]:
    token = _fiscalizacao_atual.set(fiscalizacao_id)
    try:
        yield
    finally:
        _fiscalizacao_atual.reset(token)


def _limpar(atributos: dict[str, Any]) -> dict[str, Any]:
    """OTel só aceita str/bool/int/float (ou listas homogêneas); o resto vira JSON."""
    saida: dict[str, Any] = {}
    for k, v in atributos.items():
        if v is None:
            continue
        if isinstance(v, (str, bool, int, float)):
            saida[k] = v
        elif isinstance(v, (list, tuple)) and all(isinstance(x, str) for x in v):
            saida[k] = list(v)
        else:
            saida[k] = json.dumps(v, ensure_ascii=False, default=str)
    return saida


@contextmanager
def span(nome: str, **atributos: Any) -> Iterator[Span]:
    with tracer().start_as_current_span(nome) as s:
        if atributos:
            s.set_attributes(_limpar(atributos))
        yield s


def definir(s: Span, **atributos: Any) -> None:
    s.set_attributes(_limpar(atributos))


def id_span(s: Span) -> str:
    return format(s.get_span_context().span_id, "016x")


def id_trace(s: Span) -> str:
    return format(s.get_span_context().trace_id, "032x")


def marcar_erro(s: Span, msg: str) -> None:
    s.set_status(Status(StatusCode.ERROR, msg[:200]))


@contextmanager
def span_llm(provedor: str, modelo: str, operacao: str = "chat", **atributos: Any) -> Iterator[Span]:
    with span(
        f"gen_ai.{operacao} {modelo}",
        **{
            "gen_ai.system": provedor,
            "gen_ai.operation.name": operacao,
            "gen_ai.request.model": modelo,
            **atributos,
        },
    ) as s:
        yield s


@contextmanager
def span_ferramenta(nome: str, argumentos: dict[str, Any]) -> Iterator[Span]:
    with span(
        f"tool {nome}",
        **{
            "tool.name": nome,
            "tool.args_hash": hash_entrada(argumentos),
            "tool.args_keys": sorted(argumentos.keys()),
        },
    ) as s:
        yield s


def registrar_decisao(rule_id: str, resultado: str, acao: str, motivo: str = "", **extra: Any) -> str:
    """Span curto de decisão de política. `resultado` ∈ {permitir, negar, registrar, transformar}."""
    with span(
        "policy.decision",
        **{
            "policy.rule_id": rule_id,
            "policy.resultado": resultado,
            "policy.acao": acao,
            "policy.motivo": motivo[:500],
            **extra,
        },
    ) as s:
        return id_span(s)
