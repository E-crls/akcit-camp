"""Eventos de observabilidade da demo pública: uma linha JSON por evento no stdout.

O Cloud Run manda o stdout para o Cloud Logging; uma linha JSON com `severity` vira um registro estruturado, e o
painel do Cloud Monitoring conta os eventos por métricas de log (custos e acessos). Formato:

    {"severity": "INFO", "laudo_evento": "turno", "sessao": "3f9a1c0b2d", "canal": "texto", ...}

- `sessao` é um hash curto do visitante (o da cópia da fiscalização, `laudo.isolamento`), nunca o cookie;
- os campos são números, booleanos e códigos curtos: nada de fala, nome de arquivo nem dado pessoal;
- só com `LAUDO_DEMO_PUBLICA=1`; fora dela, `evento` não imprime nada.

Eventos emitidos pelo servidor (`api.publica` e `api.main`): `sessao_nova`, `turno` (canal texto | voz | passo),
`asr` (audio_s, latencia_ms), `upload` (tipo, mb), `assinatura`, `selo`, `recusa_limite` (limite) e `erro`
(codigo). O provedor do LLM emite `llm` (tokens e custo) no mesmo formato.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from typing import Any

from laudo import isolamento

ENV_DEMO_PUBLICA = "LAUDO_DEMO_PUBLICA"
_lock = threading.Lock()
_SIMPLES = (str, int, float, bool, type(None))


def ligado() -> bool:
    return (os.environ.get(ENV_DEMO_PUBLICA) or "").strip().lower() in ("1", "true", "sim", "yes")


def _valor(v: Any) -> Any:
    if isinstance(v, _SIMPLES):
        return v[:120] if isinstance(v, str) else v
    if isinstance(v, (list, tuple)):
        return [_valor(x) for x in v[:20]]
    if isinstance(v, dict):
        return {str(k)[:40]: _valor(x) for k, x in list(v.items())[:20]}
    return str(v)[:120]


def evento(nome: str, **campos: Any) -> dict[str, Any] | None:
    """Imprime o evento (uma linha JSON) e o devolve; sem a demo pública, não faz nada e devolve None.
    `sessao=` explícito vale sobre o do contexto da cópia em uso."""
    if not ligado():
        return None
    sessao = campos.pop("sessao", None)
    if sessao is None and (ctx := isolamento.atual()) is not None:
        sessao = ctx.sessao or None
    severidade = str(campos.pop("severity", "INFO"))
    linha = {"severity": severidade, "laudo_evento": nome, "sessao": sessao, "t": round(time.time(), 3)}
    linha |= {str(k): _valor(v) for k, v in campos.items()}
    if "detalhe" not in linha:  # rótulo `detalhe` das métricas de log (infra/nuvem): o campo que qualifica o evento
        for k in ("canal", "limite", "codigo", "tipo"):
            if linha.get(k) is not None:
                linha["detalhe"] = str(linha[k])
                break
    texto = json.dumps(linha, ensure_ascii=False, default=str)
    with _lock:
        sys.stdout.write(texto + "\n")
        sys.stdout.flush()
    return linha
