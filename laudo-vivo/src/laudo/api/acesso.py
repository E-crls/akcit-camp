"""Senha compartilhada da demo pública (`LAUDO_DEMO_SENHA`): quem não a tem vê só a tela de entrada.

Sem a variável, nada muda. Com ela, toda rota pede o cookie `lv_acesso`, que `POST /api/entrar` com a senha certa
devolve (12 h, HttpOnly). Ficam abertas a tela de entrada, a saúde (a verificação de disponibilidade), a página do
produto (`/site/`) e as fontes e o ícone que essas páginas usam. A barreira roda antes da sessão: sem a senha, nem a
cópia do visitante é criada. Tentativas erradas têm teto por IP.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import threading
import time
from collections import deque

COOKIE = "lv_acesso"
ENV = "LAUDO_DEMO_SENHA"
DURACAO_S = 12 * 3600
ABERTOS = ("/entrar.html", "/api/entrar", "/api/saude", "/icone.svg", "/favicon.ico")
PREFIXOS_ABERTOS = ("/site/", "/vendor/fonts/")
TENTATIVAS, JANELA_S = 20, 600


def senha() -> str | None:
    s = (os.environ.get(ENV) or "").strip()
    return s or None


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def token(s: str) -> str:
    """O valor do cookie: deriva da senha (trocar a senha derruba os acessos antigos; reiniciar a instância, não)."""
    chave = hashlib.sha256(f"laudo-vivo-acesso:{_norm(s)}".encode()).digest()
    return hmac.new(chave, b"acesso-demo-publica:v1", hashlib.sha256).hexdigest()[:40]


def confere(digitada: str, s: str) -> bool:
    return hmac.compare_digest(_norm(digitada).encode(), _norm(s).encode())


def aberto(caminho: str) -> bool:
    return caminho in ABERTOS or caminho == "/site" or caminho.startswith(PREFIXOS_ABERTOS)


class Tentativas:
    """Tentativas erradas por IP numa janela deslizante."""

    def __init__(self, maximo: int = TENTATIVAS, janela_s: float = JANELA_S):
        self.maximo, self.janela_s = maximo, janela_s
        self._por_ip: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def bloqueado(self, ip: str, agora: float | None = None) -> bool:
        agora = time.monotonic() if agora is None else agora
        with self._lock:
            q = self._por_ip.get(ip)
            while q and agora - q[0] >= self.janela_s:
                q.popleft()
            return bool(q) and len(q) >= self.maximo

    def errou(self, ip: str, agora: float | None = None) -> None:
        agora = time.monotonic() if agora is None else agora
        with self._lock:
            if len(self._por_ip) > 5000:
                self._por_ip.clear()
            self._por_ip.setdefault(ip, deque()).append(agora)
