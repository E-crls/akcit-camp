"""Regras de prioridade de verificação (sem rede, sem bench)."""

from __future__ import annotations

import math
from datetime import date

import pytest

from laudo.geo.triagem import ano_agricola, classe_lotacao, fmt, nivel, pontuar


def op_base(**kw):
    base = {"compra_gado_tipo": "investimento", "unidade_qtd_bovinos": "UA", "lotacao_implicita_cab_ha": 1.0,
            "confinamento": False, "densidade_bovina_mun_cab_ha": 0.9, "n_ops_sobrepostas": 0,
            "sobreposicao_max_frac": math.nan, "sobrepoe_outra_if": False, "area_glebas_ha": 50.0,
            "area_informada_ha": 50.0, "valor_cabeca_fora_faixa": False, "frac_rebanho_mun": 0.001,
            "exige_sensoriamento_remoto": False, "tem_poligono": True}
    return base | kw


@pytest.mark.parametrize("d,esperado", [(date(2026, 1, 5), "2025/26"), (date(2026, 6, 30), "2025/26"),
                                        (date(2026, 7, 1), "2026/27"), (date(2026, 9, 30), "2026/27"),
                                        (None, None)])
def test_ano_agricola(d, esperado):
    assert ano_agricola(d) == esperado


def test_nivel():
    assert [nivel(p) for p in (0, 1, 2, 3, 4, 7)] == ["sem_sinal", "baixa", "media", "media", "alta", "alta"]


@pytest.mark.parametrize("lot,compra,pontos", [(1.9, "investimento", 0), (2.1, "investimento", 1),
                                               (3.5, "investimento", 2), (8.0, "investimento", 3),
                                               (2.9, "custeio", 0), (3.5, "custeio", 1), (6.0, "custeio", 2),
                                               (None, "investimento", 0), (9.0, None, 0)])
def test_classe_lotacao(lot, compra, pontos):
    assert classe_lotacao(lot, compra)[0] == pontos


def test_operacao_sem_sinal():
    r = pontuar(op_base())
    assert r.pontos == 0 and r.motivos == [] and r.codigos == []


def test_lotacao_alta_com_densidade_municipal_no_motivo():
    r = pontuar(op_base(lotacao_implicita_cab_ha=6.0))
    assert r.pontos == 3
    assert r.codigos == ["LOTACAO_ALTA"]
    assert "6,0 UA/ha" in r.motivos[0] and "densidade bovina do município" in r.motivos[0]


def test_confinamento_nao_pontua_lotacao():
    r = pontuar(op_base(lotacao_implicita_cab_ha=50.0, confinamento=True))
    assert r.pontos == 0
    assert any("confinamento" in o for o in r.observacoes)


def test_sem_area_vira_observacao_e_nao_pontua():
    r = pontuar(op_base(lotacao_implicita_cab_ha=math.nan))
    assert r.pontos == 0
    assert any("indeterminada" in o for o in r.observacoes)


def test_sobreposicao_com_outra_if_soma_ponto():
    r1 = pontuar(op_base(n_ops_sobrepostas=1, sobreposicao_max_frac=0.8, sobreposicao_ha=40.0))
    r2 = pontuar(op_base(n_ops_sobrepostas=1, sobreposicao_max_frac=0.8, sobreposicao_ha=40.0, sobrepoe_outra_if=True))
    r3 = pontuar(op_base(n_ops_sobrepostas=1, sobreposicao_max_frac=0.2, sobreposicao_ha=10.0))
    assert (r1.pontos, r2.pontos, r3.pontos) == (2, 3, 1)
    assert "outra IF" in r2.motivos[0]


def test_area_divergente_e_valor_atipico():
    r = pontuar(op_base(area_glebas_ha=10.0, area_informada_ha=50.0, valor_cabeca_fora_faixa=True,
                        valor_por_cabeca_rs=90000.0, faixa_valor_cabeca="R$ 2.000–15.000 por UA"))
    assert set(r.codigos) == {"AREA_DIVERGENTE", "VALOR_CABECA_ATIPICO"}


def test_nao_compra_ignora_lotacao_e_nan_no_tipo():
    r = pontuar(op_base(compra_gado_tipo=math.nan, lotacao_implicita_cab_ha=20.0))
    assert r.pontos == 0


def test_observacoes_de_metodo():
    r = pontuar(op_base(exige_sensoriamento_remoto=True, tem_poligono=False))
    assert any("300 ha" in o and "item 5" in o for o in r.observacoes)
    assert any("sem polígono" in o for o in r.observacoes)


def test_linguagem_nunca_acusa():
    r = pontuar(op_base(lotacao_implicita_cab_ha=9.0, n_ops_sobrepostas=2, sobreposicao_max_frac=1.0,
                        sobrepoe_outra_if=True, valor_cabeca_fora_faixa=True, area_glebas_ha=1.0))
    texto = " ".join(r.motivos + r.observacoes).lower()
    for proibida in ("suspeit", "fraude", "irregular", "ilícit"):
        assert proibida not in texto


def test_fmt_pt_br():
    assert fmt(1234.5, 1) == "1.234,5"
    assert fmt(None) == "n/d"
