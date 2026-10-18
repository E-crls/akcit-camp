"""Cadeia de hash das evidências (append-only).

Cada evidência guarda em `hash_anterior` o *hash do elo* da evidência anterior. O hash do elo cobre
o conteúdo canônico da evidência (id, tipo, sha256 do arquivo, hash_anterior, datas, GPS e metadados),
de modo que alterar qualquer campo de qualquer evidência já registrada quebra a cadeia a partir dali.

A raiz da cadeia (hash do elo da última evidência) entra no `hash_raiz` do laudo, que é o que o humano
assina. O caminho do arquivo fica fora do hash (mover o arquivo não altera a prova; o sha256 do conteúdo,
sim).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel

from laudo.contracts import Evidencia

GENESIS = "0" * 64
_CAMPOS_DO_ELO = ("id", "tipo", "sha256", "hash_anterior", "capturada_em", "recebida_em", "gps", "meta")


def canonico(obj: Any) -> bytes:
    """Serialização canônica (chaves ordenadas, sem espaços, UTF-8)."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode(
        "utf-8"
    )


def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def conteudo_do_elo(ev: Evidencia) -> dict[str, Any]:
    d = ev.model_dump(mode="json")
    return {k: d.get(k) for k in _CAMPOS_DO_ELO}


def hash_elo(ev: Evidencia) -> str:
    return sha256_hex(canonico(conteudo_do_elo(ev)))


def raiz(evidencias: list[Evidencia]) -> str:
    """Hash do elo da última evidência (ou GENESIS se não há evidência)."""
    return hash_elo(evidencias[-1]) if evidencias else GENESIS


def anexar(evidencias: list[Evidencia], ev: Evidencia) -> Evidencia:
    """Encadeia `ev` ao fim da lista (define `hash_anterior`) e a anexa. Nunca altera elos anteriores."""
    if any(e.id == ev.id for e in evidencias):
        raise ValueError(f"evidência duplicada: {ev.id}")
    ev.hash_anterior = raiz(evidencias)
    evidencias.append(ev)
    return ev


class ResultadoCadeia(BaseModel):
    integra: bool
    raiz: str
    n: int
    quebra_em: int | None = None  # índice da primeira evidência cujo hash_anterior não confere
    evidencia_id: str | None = None
    motivo: str = ""


def verificar_cadeia(evidencias: Iterable[Evidencia]) -> ResultadoCadeia:
    lista = list(evidencias)
    anterior = GENESIS
    for i, ev in enumerate(lista):
        if ev.hash_anterior != anterior:
            return ResultadoCadeia(
                integra=False,
                raiz=raiz(lista),
                n=len(lista),
                quebra_em=i,
                evidencia_id=ev.id,
                motivo=f"hash_anterior de {ev.id} não confere com o elo {i - 1}",
            )
        anterior = hash_elo(ev)
    return ResultadoCadeia(integra=True, raiz=anterior, n=len(lista))


def hash_raiz_laudo(raiz_cadeia: str, conteudo_laudo: dict[str, Any]) -> str:
    """Hash que o humano assina: raiz da cadeia de evidências + conteúdo canônico do laudo."""
    return sha256_hex(raiz_cadeia.encode("ascii") + b"|" + canonico(conteudo_laudo))
