"""Formulário de contato da página do produto (`POST /api/contato`).

O pedido vem da página do produto (no domínio curto ou no próprio serviço): as origens aceitas ficam em
`LAUDO_CONTATO_ORIGENS`. Cada contato vira um objeto JSON num bucket privado (`LAUDO_CONTATO_BUCKET`, com expiração no
Terraform); sem bucket, uma linha num JSONL da pasta de dados (uso local e testes). Nada do que a pessoa escreveu vai
para os logs: o evento só diz que houve um contato. Consentimento obrigatório; campo-isca e teto por IP contra spam.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field, field_validator

ORIGENS_PADRAO = ("https://laudovivo.web.app", "https://laudovivo.firebaseapp.com")
MAX_POR_IP, JANELA_S = 5, 600
_RX_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,24}$")


class Contato(BaseModel):
    nome: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=254)
    instituicao: str = Field("", max_length=160)
    cargo: str = Field("", max_length=120)
    mensagem: str = Field("", max_length=2000)
    consentimento: bool = False
    site: str = Field("", max_length=200)  # campo-isca: gente não vê nem preenche

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip()
        if not _RX_EMAIL.match(v):
            raise ValueError("e-mail inválido")
        return v


def origens() -> set[str]:
    extra = [o.strip().rstrip("/") for o in (os.environ.get("LAUDO_CONTATO_ORIGENS") or "").split(",") if o.strip()]
    return {*ORIGENS_PADRAO, *extra}


class Teto:
    """Contatos por IP numa janela deslizante."""

    def __init__(self, maximo: int = MAX_POR_IP, janela_s: float = JANELA_S):
        self.maximo, self.janela_s = maximo, janela_s
        self._por_ip: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def permitir(self, ip: str, agora: float | None = None) -> bool:
        agora = time.monotonic() if agora is None else agora
        with self._lock:
            if len(self._por_ip) > 5000:
                self._por_ip.clear()
            q = self._por_ip.setdefault(ip, deque())
            while q and agora - q[0] >= self.janela_s:
                q.popleft()
            if len(q) >= self.maximo:
                return False
            q.append(agora)
            return True


def _token_metadata() -> str:
    r = httpx.get("http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
                  headers={"Metadata-Flavor": "Google"}, timeout=3.0)
    r.raise_for_status()
    return r.json()["access_token"]


def guardar(c: Contato, dados_dir: Path, cliente: httpx.Client | None = None) -> str:
    """Grava o contato e devolve o id. Bucket (`LAUDO_CONTATO_BUCKET`) na nuvem; JSONL local sem ele."""
    agora = datetime.now(UTC)
    cid = f"{agora:%Y%m%dT%H%M%S}-{secrets.token_hex(4)}"
    registro: dict[str, Any] = {"id": cid, "recebido_em": agora.isoformat(timespec="seconds"),
                                **c.model_dump(exclude={"site"})}
    bucket = (os.environ.get("LAUDO_CONTATO_BUCKET") or "").strip()
    if not bucket:
        arq = Path(dados_dir) / "contatos.jsonl"
        arq.parent.mkdir(parents=True, exist_ok=True)
        with open(arq, "a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")
        return cid
    token = os.environ.get("LAUDO_GCS_TOKEN") or _token_metadata()
    url = f"https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o"
    r = (cliente or httpx).post(url, params={"uploadType": "media", "name": f"contatos/{cid}.json"},
                                content=json.dumps(registro, ensure_ascii=False).encode("utf-8"),
                                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                                timeout=15.0)
    r.raise_for_status()
    return cid
