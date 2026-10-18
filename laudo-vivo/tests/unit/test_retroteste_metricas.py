"""Retro-teste (eval/retroteste): métricas contra força bruta, protocolo e pontuação sem retoque."""

from __future__ import annotations

import hashlib
import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

RAIZ = Path(__file__).resolve().parents[2]
DIR = RAIZ / "eval" / "retroteste"
sys.path.insert(0, str(DIR))
sys.path.insert(0, str(RAIZ / "bench" / "desclassificacao"))

import metricas as M
import observatorio as O
import rodar as R

from laudo.geo.triagem import pontuar


def _forca_bruta(estrato, s, y, fracao=0.1, reps=20000, semente=1):
    """Top `fracao` por estrato com desempate aleatório (média de muitos sorteios) e AUC por pares."""
    rng = np.random.default_rng(semente)
    top = 0.0
    for e in np.unique(estrato):
        idx = np.where(estrato == e)[0]
        k = fracao * len(idx)
        acc = 0.0
        for _ in range(reps // 50):
            u = rng.random(len(idx))
            ordem = idx[np.lexsort((u, -s[idx]))]
            inteiro = int(np.floor(k))
            acc += y[ordem[:inteiro]].sum() + (k - inteiro) * (y[ordem[inteiro]] if inteiro < len(idx) else 0)
        top += acc / (reps // 50)
    num = den = 0.0
    for e in np.unique(estrato):
        idx = np.where(estrato == e)[0]
        pos, neg = idx[y[idx] == 1], idx[y[idx] == 0]
        for i, j in product(pos, neg):
            num += 1.0 if s[i] > s[j] else (0.5 if s[i] == s[j] else 0.0)
            den += 1
    return top, num / den


def test_top_e_auc_batem_com_forca_bruta():
    rng = np.random.default_rng(7)
    n = 120
    estrato = rng.integers(0, 3, n)
    s = rng.integers(0, 4, n).astype(float)  # muitos empates, como a pontuação da triagem
    y = (rng.random(n) < 0.2 + 0.1 * s).astype(float)
    o = M.ordenar(estrato, s)
    pe = M.por_estrato(o, np.ones(n), y)
    top_bf, auc_bf = _forca_bruta(estrato, s, y)
    assert pe.top_P.sum() == pytest.approx(top_bf, abs=0.15)
    ag = M.agregar(pe)
    assert ag["auc"][0] == pytest.approx(auc_bf)
    assert ag["lift"][0] == pytest.approx(pe.top_P.sum() / y.sum() / 0.1)


def test_pesos_inteiros_equivalem_a_repetir_linhas():
    rng = np.random.default_rng(3)
    n = 60
    estrato, s = rng.integers(0, 2, n), rng.integers(0, 3, n).astype(float)
    y = (rng.random(n) < 0.3).astype(float)
    w = rng.integers(0, 3, n).astype(float)
    a = M.agregar(M.por_estrato(M.ordenar(estrato, s), w, y))
    rep = np.repeat(np.arange(n), w.astype(int))
    b = M.agregar(M.por_estrato(M.ordenar(estrato[rep], s[rep]), np.ones(len(rep)), y[rep]))
    for m in ("captura", "auc", "taxa"):
        assert a[m][0] == pytest.approx(b[m][0])


def test_pontuacao_constante_da_lift_um_e_auc_meio():
    y = np.array([1, 0, 0, 0, 1, 0, 0, 0, 0, 0] * 10, dtype=float)
    ag = M.agregar(M.por_estrato(M.ordenar(np.zeros(100, int), np.zeros(100)), np.ones(100), y))
    assert ag["lift"][0] == pytest.approx(1.0) and ag["auc"][0] == pytest.approx(0.5)


def test_pontuacao_perfeita():
    y = np.zeros(100)
    y[:5] = 1
    ag = M.agregar(M.por_estrato(M.ordenar(np.zeros(100, int), y.copy()), np.ones(100), y))
    assert ag["captura"][0] == pytest.approx(1.0) and ag["lift"][0] == pytest.approx(10.0)
    assert ag["auc"][0] == pytest.approx(1.0)


def test_agregar_por_classe_e_aleatorio():
    estrato = np.array([0] * 50 + [1] * 50)
    y = np.r_[np.ones(10), np.zeros(40), np.ones(5), np.zeros(45)]
    pe = M.por_estrato(M.ordenar(estrato, y.copy()), np.ones(100), y)
    por = M.agregar(pe, np.array([0, 1]), 2)
    assert list(por["captura"]) == pytest.approx([0.5, 1.0])
    sel = np.zeros(100)
    sel[::10] = 1
    al = M.aleatorio(np.ones(100), y, sel)
    assert al["lift"][0] == pytest.approx((y[::10].mean()) / y.mean())
    assert M.intervalo(np.arange(101.0)) == [2.5, 97.5]


def test_protocolo_registrado_e_inalterado():
    reg = (DIR / "PROTOCOLO.sha256").read_text(encoding="utf-8").split()[0]
    atual = hashlib.sha256((DIR / "PROTOCOLO.md").read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    assert atual == reg, "PROTOCOLO.md mudou depois do registro: crie uma versão nova"
    assert R.conferir_protocolo()["sha256"] == reg
    texto = (DIR / "PROTOCOLO.md").read_text(encoding="utf-8")
    assert "maior que 1,5" in texto and "VL_PRODUTIV_OBTIDA" in texto
    for c in O.CAMPOS_ORIGINACAO:
        assert c in texto


@pytest.fixture(scope="module")
def bench_go():
    p = RAIZ / "bench" / "fiscal_go" / "fiscal_go_2026.parquet"
    if not p.exists():
        pytest.skip("bench Fiscal-GO ausente")
    return pd.read_parquet(p)


def test_pontuacao_so_le_os_campos_listados(bench_go):
    """Reduzir o registro aos campos de CAMPOS_CADASTRO + CAMPOS_GEO (+ município) não muda nada."""
    extra = ("densidade_bovina_mun_cab_ha", "frac_rebanho_mun", "exige_sensoriamento_remoto")
    campos = list(R.CAMPOS_CADASTRO + R.CAMPOS_GEO + extra)
    for r in bench_go.to_dict("records"):
        cheio, reduzido = pontuar(r), pontuar({k: r[k] for k in campos})
        assert (cheio.pontos, cheio.codigos) == (reduzido.pontos, reduzido.codigos)
        assert cheio.pontos == r["prioridade_verificacao"]


def test_insumos_de_cadastro_sao_as_regras_sem_os_campos_ausentes(bench_go):
    """'cadastro' = a mesma pontuação, só com LOTACAO_ALTA e VALOR_CABECA_ATIPICO (os outros sem insumo)."""
    cad_regras = {"LOTACAO_ALTA", "VALOR_CABECA_ATIPICO"}
    for r in bench_go[bench_go["eh_compra_gado"]].to_dict("records"):
        cheio = pontuar(r)
        cad = pontuar({k: r[k] for k in R.CAMPOS_CADASTRO})
        esperado = sum(
            int(m.rsplit("(+", 1)[1].rstrip(")"))
            for c, m in zip(cheio.codigos, cheio.motivos, strict=True)
            if c in cad_regras
        )
        assert cad.pontos == esperado
        assert set(cad.codigos) <= cad_regras


def test_analisar_sintetico():
    """A análise inteira roda numa população sintética e acha o sinal plantado."""
    rng = np.random.default_rng(11)
    n = 3000
    pontos = rng.integers(0, 4, n)
    y = (rng.random(n) < 0.01 + 0.05 * (pontos >= 2)).astype(float)
    df = pd.DataFrame({
        "REF_BACEN": [str(i) for i in range(n)], "if_cnpj_base": rng.choice(["A", "B", "C"], n),
        "segmento_if": "S", "compra_gado_tipo": rng.choice(["investimento", "custeio"], n),
        "valor_rs": rng.random(n), "pontos_cadastro": pontos, "codigos_cadastro": "LOTACAO_ALTA",
        "coorte": rng.choice([2022, 2023, 2024], n), "rotulo_A": y, "rotulo_B": y,
    })
    res = R.analisar(df, "BR", ["cadastro"], 20, np.random.default_rng(1), {"A": "S"})
    prim = res["analises"]["regras_cadastro|coorte_if|A"]["total"]
    lo, hi = prim["lift"]["ic95"]
    assert prim["lift"]["valor"] > 1.5 and lo < prim["lift"]["valor"] < hi
    assert prim["n"] == n and prim["positivos"] == int(y.sum())
    valor = res["analises"]["so_valor|coorte_if|A"]["total"]["lift"]["valor"]
    assert abs(valor - 1) < 0.6
    assert res["analises"]["aleatorio|-|A"]["total"]["lift"]["valor"] == 1.0
    assert set(res["analises"]["regras_cadastro|coorte_if|A"]["por_coorte"]) == {"2022", "2023", "2024"}
