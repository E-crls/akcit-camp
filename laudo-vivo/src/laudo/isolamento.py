"""Isolamento por visitante (demo pública): o estado que o processo guarda em variáveis de módulo, por cópia.

Num processo normal há uma fiscalização por vez e três coisas ficam em variáveis de módulo: o contador de ids
reprodutíveis (`agent.estado`), a pasta dos traces (`audit.otel`) e o repositório e a política da ferramenta de
laudo (`tools.laudo`). Na demo pública (`LAUDO_DEMO_PUBLICA=1`) cada visitante tem a sua cópia da fiscalização,
com o mesmo id (`fis_demo_0001`, para o replay casar), numa pasta própria. Este módulo guarda, num
`ContextVar`, o `Contexto` da cópia que está atendendo a requisição; os três módulos consultam `atual()` antes
da variável de módulo. Sem contexto ativo (uso normal), nada muda.

A ferramenta roda numa thread do executor (`agent.executor`): `no_contexto(f)` leva o contexto junto. Sem
contexto, devolve a própria função (o uso normal continua exatamente igual).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Contexto:
    """Estado de uma cópia: ids reprodutíveis, pasta dos traces e contexto da ferramenta de laudo."""

    traces: Path
    sessao: str = ""  # hash curto do visitante (eventos de observabilidade; nunca o cookie)
    ids: dict[str, Any] = field(default_factory=lambda: {"semente": None, "n": 0})
    laudo: dict[str, Any] = field(default_factory=lambda: {"repo": None, "politica": None})


_ATUAL: ContextVar[Contexto | None] = ContextVar("laudo_isolamento", default=None)


def atual() -> Contexto | None:
    return _ATUAL.get()


@contextmanager
def ativo(ctx: Contexto) -> Iterator[Contexto]:
    token = _ATUAL.set(ctx)
    try:
        yield ctx
    finally:
        _ATUAL.reset(token)


def no_contexto(f: Callable[..., Any]) -> Callable[..., Any]:
    """`f` para rodar noutra thread com o contexto atual (sem contexto, a própria `f`)."""
    ctx = _ATUAL.get()
    if ctx is None:
        return f

    def g(*a: Any, **k: Any) -> Any:
        with ativo(ctx):
            return f(*a, **k)

    return g
