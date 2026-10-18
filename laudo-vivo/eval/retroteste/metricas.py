"""Métricas do retro-teste (PROTOCOLO.md, seção 7): top 10% por estrato, captura, lift e AUC, com pesos.

Tudo é vetorizado sobre "grupos": operações do mesmo estrato com a mesma pontuação. O top 10% de cada estrato
pega os grupos de maior pontuação; no grupo da fronteira entra só a fração necessária, com a taxa de positivos
do grupo (valor esperado do desempate aleatório). Os pesos `w` permitem o bootstrap de Poisson sem reamostrar
linhas: `w = 1` dá a estimativa pontual.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

FRACAO = 0.10


@dataclass(frozen=True)
class Ordenacao:
    """Estrutura de grupos (estrato, pontuação) em ordem de estrato crescente e pontuação decrescente."""

    gid: np.ndarray  # (N,) grupo de cada operação
    g_estrato: np.ndarray  # (G,) estrato de cada grupo (não decrescente)
    n_estratos: int


def ordenar(estrato: np.ndarray, pontuacao: np.ndarray) -> Ordenacao:
    estrato = np.asarray(estrato, dtype=np.int64)
    s = np.nan_to_num(np.asarray(pontuacao, dtype=np.float64), nan=-np.inf)
    n = len(s)
    if n == 0:
        return Ordenacao(np.zeros(0, np.int64), np.zeros(0, np.int64), 0)
    ordem = np.lexsort((-s, estrato))
    e_o, s_o = estrato[ordem], s[ordem]
    novo = np.empty(n, dtype=bool)
    novo[0] = True
    novo[1:] = (e_o[1:] != e_o[:-1]) | (s_o[1:] != s_o[:-1])
    gid = np.empty(n, dtype=np.int64)
    gid[ordem] = np.cumsum(novo) - 1
    return Ordenacao(gid=gid, g_estrato=e_o[novo], n_estratos=int(estrato.max()) + 1)


@dataclass
class PorEstrato:
    W: np.ndarray  # peso total (operações)
    P: np.ndarray  # peso dos positivos
    top_P: np.ndarray  # positivos esperados no top `fracao`
    auc_num: np.ndarray  # soma de pares (positivo acima do negativo; empate vale 0,5)
    auc_den: np.ndarray  # pares positivo-negativo do estrato


def por_estrato(
    o: Ordenacao, w: np.ndarray, y: np.ndarray, fracao: float = FRACAO, Wg: np.ndarray | None = None
) -> PorEstrato:
    G, S, ge = len(o.g_estrato), o.n_estratos, o.g_estrato
    if Wg is None:
        Wg = np.bincount(o.gid, weights=w, minlength=G)
    Pg = np.bincount(o.gid, weights=w * y, minlength=G)
    Ng = Wg - Pg
    Ws = np.bincount(ge, weights=Wg, minlength=S)
    Ps = np.bincount(ge, weights=Pg, minlength=S)
    Ns = Ws - Ps
    off_W = np.cumsum(Ws) - Ws
    off_N = np.cumsum(Ns) - Ns
    antes = np.cumsum(Wg) - Wg - off_W[ge]
    pega = np.clip(fracao * Ws[ge] - antes, 0.0, Wg)
    with np.errstate(invalid="ignore", divide="ignore"):
        top_g = np.where(Wg > 0, Pg * pega / np.where(Wg > 0, Wg, 1.0), 0.0)
    abaixo = Ns[ge] - (np.cumsum(Ng) - off_N[ge])  # negativos com pontuação menor, no mesmo estrato
    num_g = Pg * (abaixo + 0.5 * Ng)
    return PorEstrato(
        W=Ws,
        P=Ps,
        top_P=np.bincount(ge, weights=top_g, minlength=S),
        auc_num=np.bincount(ge, weights=num_g, minlength=S),
        auc_den=Ps * Ns,
    )


def pesos_grupo(o: Ordenacao, w: np.ndarray) -> np.ndarray:
    return np.bincount(o.gid, weights=w, minlength=len(o.g_estrato))


def agregar(
    pe: PorEstrato, mapa: np.ndarray | None = None, n_classes: int | None = None, fracao: float = FRACAO
) -> dict[str, np.ndarray]:
    """Soma estratos (todos, ou por classe de `mapa`: coorte, IF) e devolve taxa, captura, lift e AUC."""
    if mapa is None:
        soma = {k: np.array([getattr(pe, k).sum()]) for k in ("W", "P", "top_P", "auc_num", "auc_den")}
    else:
        soma = {
            k: np.bincount(mapa, weights=getattr(pe, k), minlength=n_classes)
            for k in ("W", "P", "top_P", "auc_num", "auc_den")
        }
    with np.errstate(invalid="ignore", divide="ignore"):
        cap = soma["top_P"] / soma["P"]
        return {
            "n": soma["W"],
            "positivos": soma["P"],
            "taxa": soma["P"] / soma["W"],
            "captura": cap,
            "lift": cap / fracao,
            "auc": soma["auc_num"] / soma["auc_den"],
        }


def aleatorio(
    w: np.ndarray,
    y: np.ndarray,
    selecao: np.ndarray,
    mapa: np.ndarray | None = None,
    n_classes: int | None = None,
) -> dict[str, np.ndarray]:
    """Lift de uma amostra aleatória (máscara `selecao`), no total ou por classe."""
    if mapa is None:
        mapa, n_classes = np.zeros(len(w), dtype=np.int64), 1
    W = np.bincount(mapa, weights=w, minlength=n_classes)
    P = np.bincount(mapa, weights=w * y, minlength=n_classes)
    Wsel = np.bincount(mapa, weights=w * selecao, minlength=n_classes)
    Psel = np.bincount(mapa, weights=w * y * selecao, minlength=n_classes)
    with np.errstate(invalid="ignore", divide="ignore"):
        lift = (Psel / Wsel) / (P / W)
        return {"lift": lift, "captura": Psel / P}


def wilson(k: float, n: float, z: float = 1.959964) -> tuple[float | None, float | None]:
    if n <= 0:
        return None, None
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    m = z * math.sqrt(max(p * (1 - p) / n + z * z / (4 * n * n), 0.0)) / den
    return max(0.0, c - m), min(1.0, c + m)


def intervalo(amostras: np.ndarray) -> list[float | None]:
    a = np.asarray(amostras, dtype=float)
    a = a[np.isfinite(a)]
    if a.size == 0:
        return [None, None]
    lo, hi = np.percentile(a, [2.5, 97.5])
    return [float(lo), float(hi)]
