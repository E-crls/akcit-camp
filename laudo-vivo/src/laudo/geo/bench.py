"""Acesso somente leitura ao bench Fiscal-GO 2026 (parquets em `bench/fiscal_go/`).

O diretório pode ser trocado por `LAUDO_BENCH_DIR` (testes usam fixtures pequenas).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[3]


def dir_bench() -> Path:
    d = os.environ.get("LAUDO_BENCH_DIR")
    return Path(d) if d else RAIZ / "bench" / "fiscal_go"


class BenchAusente(FileNotFoundError):
    pass


def _ler(nome: str) -> pd.DataFrame:
    p = dir_bench() / f"{nome}.parquet"
    if not p.exists():
        raise BenchAusente(f"{p} não existe; rode scripts/dados_sicor.py, scripts/dados_ibge.py e "
                           "bench/fiscal_go/build.py")
    return pd.read_parquet(p)


@lru_cache(maxsize=4)
def _cache(nome: str, chave: str) -> pd.DataFrame:
    return _ler(nome)


def tabela(nome: str) -> pd.DataFrame:
    """Lê (com cache por diretório) uma tabela do bench: fiscal_go_2026, itens_go_2026, glebas_go_2026,
    rebanho_municipal_go."""
    return _cache(nome, str(dir_bench()))


def operacoes() -> pd.DataFrame:
    return tabela("fiscal_go_2026")


def itens() -> pd.DataFrame:
    return tabela("itens_go_2026")


def glebas() -> pd.DataFrame:
    return tabela("glebas_go_2026")


def rebanho() -> pd.DataFrame:
    return tabela("rebanho_municipal_go")


def versao() -> str:
    try:
        op = operacoes()
        return str(op["fonte_versao"].iloc[0]) if len(op) else "fiscal-go@vazio"
    except BenchAusente:
        return "fiscal-go@ausente"


def limpar_cache() -> None:
    _cache.cache_clear()
