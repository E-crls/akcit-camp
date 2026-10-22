"""Pastas do cache de respostas do VLM (classificação de foto e leitura de DANFE/GTA por foto).

O cache serve ao replay sem GPU: cada resposta do Ollama fica num JSON cuja chave é o hash do pedido. Há duas
pastas, para o cache versionado da demo nunca ser escrito por uma rodada ao vivo com foto nova:

- `LAUDO_VLM_CACHE`: pasta de **leitura** (a da demo, versionada: `tests/unit/dados_agente/vlm_cache_demo`);
- `LAUDO_VLM_CACHE_GRAVACAO`: pasta onde as respostas **novas** são gravadas (e também lidas, depois da
  primeira). Sem ela, as respostas novas vão para a própria `LAUDO_VLM_CACHE`, salvo se ela estiver dentro de
  `tests/` do repositório: aí vão para `dados_locais/vlm_cache` (fora do git). Para regravar de propósito uma
  fixture de `tests/`, aponte `LAUDO_VLM_CACHE_GRAVACAO` para ela;
- `LAUDO_VLM_SO_CACHE=1`: nada é gravado e resposta ausente vira erro (replay da contingência).

Sem nenhuma das duas pastas, não há cache (toda chamada vai ao Ollama).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
# Pastas versionadas que uma rodada ao vivo nunca escreve sem pedido explícito (LAUDO_VLM_CACHE_GRAVACAO)
PASTAS_PROTEGIDAS: tuple[Path, ...] = (REPO / "tests",)
GRAVACAO_PADRAO = REPO / "dados_locais" / "vlm_cache"
ENV_LEITURA = "LAUDO_VLM_CACHE"
ENV_GRAVACAO = "LAUDO_VLM_CACHE_GRAVACAO"
ENV_SO_CACHE = "LAUDO_VLM_SO_CACHE"


def protegida(pasta: str | Path) -> bool:
    """A pasta fica dentro de uma das `PASTAS_PROTEGIDAS` (ex.: `tests/` do repositório)?"""
    alvo = Path(pasta).resolve()
    for base in PASTAS_PROTEGIDAS:
        b = Path(base).resolve()
        if alvo == b or alvo.is_relative_to(b):
            return True
    return False


@dataclass(frozen=True)
class PastasCache:
    leitura: tuple[Path, ...]  # na ordem de consulta (a versionada primeiro)
    gravacao: Path | None  # None: não grava (só cache)
    so_cache: bool = False

    @property
    def principal(self) -> Path:
        """Pasta citada nas mensagens (a de leitura, ou a de gravação se só ela existe)."""
        return self.leitura[0]

    def ler(self, nome: str) -> str | None:
        for d in self.leitura:
            arq = d / nome
            if arq.is_file():
                return arq.read_text(encoding="utf-8")
        return None

    def gravar(self, nome: str, texto: str) -> Path | None:
        if self.gravacao is None:
            return None
        self.gravacao.mkdir(parents=True, exist_ok=True)
        arq = self.gravacao / nome
        arq.write_text(texto, encoding="utf-8")
        return arq


def montar(leitura: str | Path | None, gravacao: str | Path | None = None, so_cache: bool = False) -> PastasCache:
    """Pastas a partir da pasta de leitura e da de gravação (opcional), com a proteção de `tests/`."""
    lidas = [Path(leitura)] if leitura else []
    if gravacao:
        destino = Path(gravacao)
    elif lidas and not protegida(lidas[0]):
        destino = lidas[0]
    else:
        destino = GRAVACAO_PADRAO
    if all(destino.resolve() != d.resolve() for d in lidas):
        lidas.append(destino)
    return PastasCache(leitura=tuple(lidas), gravacao=None if so_cache else destino, so_cache=so_cache)


def pastas(env: Mapping[str, str] | None = None) -> PastasCache | None:
    """Pastas do cache pelas variáveis de ambiente (None: sem cache)."""
    env = os.environ if env is None else env
    leitura, gravacao = env.get(ENV_LEITURA) or None, env.get(ENV_GRAVACAO) or None
    if not leitura and not gravacao:
        return None
    return montar(leitura, gravacao, so_cache=env.get(ENV_SO_CACHE) == "1")
