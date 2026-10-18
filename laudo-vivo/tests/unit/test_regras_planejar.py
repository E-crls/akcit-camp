"""planejar_metodo: obrigatoriedades, prazos com datas, método por item e requisitos (casos por tabela).

Cada caso cita o item da norma (ou o parâmetro operacional) que o justifica. Dados 100% sintéticos.
"""

from __future__ import annotations

from datetime import date

import pytest

from laudo.contracts import REGISTRO, ItemFinanciado, Operacao
from laudo.tools import regras as R

REF = date(2026, 10, 8)


def _op(finalidade="investimento", contratacao=date(2026, 7, 1), area_fin=120.0, itens=None) -> Operacao:
    return Operacao(ref_bacen="TESTE-SINTETICO-0001", tomador_ref="anon-teste", finalidade=finalidade,
                    data_contratacao=contratacao, area_financiada_ha=area_fin, fonte="sintetico",
                    itens=itens if itens is not None else [_item("bov1", "bovinos", 40)])


def _item(iid: str, tipo: str, qtd: float = 1) -> ItemFinanciado:
    return ItemFinanciado(id=iid, tipo=tipo, descricao=f"{tipo} (sintético)", quantidade=qtd)


def _plan(op: Operacao, ref: date = REF, **ctx) -> dict:
    return R.planejar(op, R.ContextoRegras(**ctx), ref)


# --------------------------------------------------------------------------- MCR 2-7-5
CASOS_REMOTO = [
    # norma, finalidade, contratação, área total, área financiada, esperado
    ("2-7-5-b: 300 ha exatos não é 'superior a trezentos'", "investimento", date(2026, 3, 1), 300.0, None, False),
    ("2-7-5-b: 300,01 ha é superior", "investimento", date(2026, 3, 1), 300.01, None, True),
    ("2-7-5-a: contratada em 28/02/2026 fica fora", "custeio", date(2026, 2, 28), 5000.0, None, False),
    ("2-7-5-a: contratada em 01/03/2026 entra", "custeio", date(2026, 3, 1), 301.0, None, True),
    ("2-7-5 caput: só custeio e investimento", "comercializacao", date(2026, 6, 1), 1000.0, None, False),
    ("2-7-5: área desconhecida → indeterminado", "investimento", date(2026, 6, 1), None, None, None),
    ("2-7-5: data de contratação desconhecida → indeterminado", "investimento", None, 500.0, None, None),
    ("2-7-5-b: financiada > 300 basta (total ≥ financiada)", "investimento", date(2026, 6, 1), None, 450.0, True),
    ("PAR-area-total-usa-financiada: financiada ≤ 300 aproxima", "investimento", date(2026, 6, 1), None, 120.0,
     False),
]


@pytest.mark.parametrize("norma,fin,contr,area_total,area_fin,esperado", CASOS_REMOTO, ids=[c[0] for c in CASOS_REMOTO])
def test_obrigatoriedade_sensoriamento_remoto(norma, fin, contr, area_total, area_fin, esperado):
    op = _op(finalidade=fin, contratacao=contr, area_fin=area_fin)
    d = _plan(op, area_total_ha=area_total)
    obrig = d["obrigatoriedades"][0]
    assert obrig["regra_id"] == "MCR-2-7-item5-remoto-obrigatorio-300ha"
    assert obrig["aplica"] is esperado, obrig["motivo"]
    assert "trezentos hectares" in obrig["citacao"]
    assert d["metodos_complementares"] == (["remoto"] if esperado else [])


def test_aproximacao_pela_area_financiada_gera_aviso():
    d = _plan(_op(area_fin=120.0))
    assert any("PAR-area-total-usa-financiada" in a for a in d["avisos"])


def test_pecuaria_obrigatoria_exige_pastagem_e_instalacoes_no_sensoriamento():
    """MCR 2-7-9: aplicável à pecuária; contagem de animais por satélite é facultada."""
    d = _plan(_op(itens=[_item("bov1", "bovinos", 40), _item("cur1", "curral")]), area_total_ha=800.0)
    ids = [o["regra_id"] for o in d["obrigatoriedades"]]
    assert "MCR-2-7-item9-pecuaria-pastagem-instalacoes" in ids
    req = {r["id"] for r in d["requisitos"]}
    assert {"laudo:sensoriamento_remoto", "laudo:metadados_sensoriamento"} <= req
    # o satélite não substitui a contagem: bovinos continuam com método de campo
    assert d["metodos_por_item"][0]["metodo"] == "presencial"


# --------------------------------------------------------------------------- prazos
CASOS_PRAZO_MAQUINA = [
    # norma, liberação, data de referência, data limite, situação, dias restantes
    ("2-7-16-b-II: limite = liberação + 60", date(2026, 8, 1), date(2026, 9, 1), date(2026, 9, 30), "no_prazo", 29),
    ("2-7-16-b-II: dia 60 ainda está no prazo", date(2026, 8, 1), date(2026, 9, 30), date(2026, 9, 30), "no_prazo",
     0),
    ("2-7-16-b-II: dia 61 vencido", date(2026, 8, 1), date(2026, 10, 1), date(2026, 9, 30), "vencido", -1),
    ("2-7-16-b-II: sem liberação → indeterminado", None, REF, None, "indeterminado", None),
]


@pytest.mark.parametrize("norma,lib,ref,limite,situacao,restantes", CASOS_PRAZO_MAQUINA,
                         ids=[c[0] for c in CASOS_PRAZO_MAQUINA])
def test_prazo_maquina_60_dias(norma, lib, ref, limite, situacao, restantes):
    d = _plan(_op(itens=[_item("maq1", "maquina")]), ref=ref, data_liberacao=lib)
    p = next(x for x in d["prazos"] if x["regra_id"] == "MCR-2-7-item16-maquinas-60d")
    assert p["data_limite"] == (limite.isoformat() if limite else None)
    assert p["situacao"] == situacao and p["dias_restantes"] == restantes
    assert p["responsavel"] == "instituicao_financeira"


def test_prazo_comprovantes_do_mutuario_30_dias():
    """MCR 2-5-10-b: comprovantes de aquisição de animais e máquinas em 30 dias da liberação."""
    d = _plan(_op(itens=[_item("bov1", "bovinos", 40)]), data_liberacao=date(2026, 8, 1))
    p = next(x for x in d["prazos"] if x["regra_id"] == "MCR-2-5-item10-comprovantes-30d")
    assert p["data_limite"] == "2026-08-31" and p["responsavel"] == "mutuario"


@pytest.mark.parametrize(
    "cronograma,limite,situacao",
    [({"cur1": date(2026, 12, 31)}, "2026-12-31", "no_prazo"), ({}, None, "indeterminado")],
    ids=["2-7-16-a: até o término do cronograma", "2-7-16-a: cronograma desconhecido"],
)
def test_prazo_benfeitoria_cronograma(cronograma, limite, situacao):
    d = _plan(_op(itens=[_item("cur1", "curral")]), cronograma_fim=cronograma)
    p = next(x for x in d["prazos"] if x["regra_id"] == "MCR-2-7-item16-benfeitorias-cronograma")
    assert p["data_limite"] == limite and p["situacao"] == situacao


# --------------------------------------------------------------------------- método
CASOS_METODO = [
    # justificativa, tipo, prioridade, método esperado
    ("OP-metodo-escolha: bovinos prioridade alta", "bovinos", "alta", "presencial"),
    ("OP-metodo-escolha: bovinos prioridade desconhecida (conservador)", "bovinos", "desconhecida", "presencial"),
    ("OP-metodo-escolha: bovinos prioridade média", "bovinos", "media", "autofiscalizacao_assistida"),
    ("OP-metodo-escolha: curral prioridade baixa", "curral", "baixa", "autofiscalizacao_assistida"),
    ("OP-metodo-escolha: cerca prioridade alta", "cerca", "alta", "presencial"),
    ("OP-metodo-escolha: máquina prioridade média", "maquina", "media", "autofiscalizacao_assistida"),
]


@pytest.mark.parametrize("norma,tipo,prioridade,esperado", CASOS_METODO, ids=[c[0] for c in CASOS_METODO])
def test_metodo_por_item(norma, tipo, prioridade, esperado):
    d = _plan(_op(itens=[_item("x1", tipo, 10)]), prioridade_verificacao=prioridade)
    m = d["metodos_por_item"][0]
    assert m["metodo"] == esperado and m["regra_id"] == "OP-metodo-escolha-por-item"


def test_metodo_principal_e_o_mais_rigoroso_e_autofiscalizacao_e_documental():
    """OP-metodo-autofiscalizacao-enquadramento: autofiscalização assistida = método documental (2-7-3-b)."""
    d = _plan(_op(itens=[_item("bov1", "bovinos", 40), _item("cur1", "curral")]), prioridade_verificacao="media")
    assert d["metodo_recomendado"] == "autofiscalizacao_assistida"
    assert d["enquadramento_normativo"] == "documental"
    d = _plan(_op(itens=[_item("bov1", "bovinos", 40), _item("maq1", "maquina")]))
    assert d["metodo_recomendado"] == "presencial"


def test_item_sem_fluxo_fica_fora_do_escopo():
    d = _plan(_op(itens=[_item("lav1", "lavoura", 50)]))
    assert d["fora_do_escopo"][0]["regra_id"] == "OP-escopo-itens-regional"


# --------------------------------------------------------------------------- requisitos
def test_requisitos_por_item_com_regra_citavel():
    d = _plan(_op(itens=[_item("bov1", "bovinos", 40), _item("cur1", "curral"), _item("maq1", "maquina")]))
    req = {r["id"]: r for r in d["requisitos"]}
    assert req["item:bov1:quantidade"]["regra_id"] == "OP-bovinos-contagem-tolerancia"
    assert req["item:bov1:comprovante_nfe"]["regra_id"] == "MCR-2-5-item10-comprovante-aquisicao"
    assert req["item:bov1:gta"]["origem"] == "parametro_operacional"
    assert req["item:cur1:localizacao"]["evidencias"] == ["foto"]
    assert req["item:maq1:nfe"]["regra_id"] == "MCR-2-7-item16-maquinas-nfe"
    assert req["item:maq1:numero_serie"]["item_norma"] == "MCR 2-7-16-b-I"
    assert req["laudo:independencia_fiscal"]["regra_id"] == "MCR-2-7-item15-independencia-fiscal"
    # MCR 3-3-10-b: marcação dos animais é recomendação, não bloqueia
    assert req["item:bov1:MCR-3-3-item10-marcacao-animais"]["bloqueante"] is False


def test_saida_compativel_com_o_condutor_e_o_verificador():
    """agent/condutor.py lê `metodo`; agent/verificador.py lê `campo`, `ferramenta`, `tipos_evidencia`."""
    d = _plan(_op(itens=[_item("bov1", "bovinos", 40)]))
    assert d["metodo"] == d["metodo_recomendado"] == "presencial"
    r = next(x for x in d["requisitos"] if x["id"] == "item:bov1:quantidade")
    assert r["campo"] == "item:bov1:quantidade" and r["ferramenta"] == "contar_bovinos_video"
    assert r["tipos_evidencia"] == ["video"] and r["obrigatorio"] is True


def test_numero_de_serie_quando_couber():
    """MCR 2-7-16-b-I: 'quando couber' — máquina sem numeração de fábrica não exige a foto da plaqueta."""
    d = _plan(_op(itens=[_item("maq1", "maquina")]), itens_sem_numero_serie=["maq1"])
    assert "item:maq1:numero_serie" not in {r["id"] for r in d["requisitos"]}


# --------------------------------------------------------------------------- MCR 2-9-17
CASOS_PRODES = [
    # norma, módulos fiscais, uso coletivo, início esperado, alínea
    ("2-9-17-a: acima de 15 MF", 15.01, False, date(2027, 1, 4), "a"),
    ("2-9-17-b: 15 MF exatos ('até quinze')", 15.0, False, date(2027, 7, 1), "b"),
    ("2-9-17-b: acima de 4 MF", 4.01, False, date(2027, 7, 1), "b"),
    ("2-9-17-c: 4 MF exatos ('até quatro')", 4.0, False, date(2028, 1, 3), "c"),
    ("2-9-17-c: pequeno imóvel", 0.5, False, date(2028, 1, 3), "c"),
    ("2-9-17-A: CAR coletivo usa a alínea c", 100.0, True, date(2028, 1, 3), "17-A"),
    ("2-9-17: módulos desconhecidos → indeterminado", None, False, None, ""),
]


@pytest.mark.parametrize("norma,mf,coletivo,inicio,alinea", CASOS_PRODES, ids=[c[0] for c in CASOS_PRODES])
def test_inicio_da_exigencia_prodes(norma, mf, coletivo, inicio, alinea):
    got, al, _ = R.prodes_inicio(mf, coletivo)
    assert got == inicio and al == alinea


@pytest.mark.parametrize(
    "contratacao,aplica",
    [(date(2027, 1, 3), False), (date(2027, 1, 4), True)],
    ids=["2-9-17-a: contratada na véspera do início", "2-9-17-a: contratada no dia do início"],
)
def test_planejar_com_mcr_2_9(contratacao, aplica):
    d = _plan(_op(contratacao=contratacao), modulos_fiscais=20, rulebooks=["mcr-2-7", "mcr-2-9"])
    o = next(x for x in d["obrigatoriedades"] if x["regra_id"] == "MCR-2-9-item17-prodes-inicio")
    assert o["aplica"] is aplica
    assert any(f.startswith("rulebook-mcr-2-9@") for f in d["rulebooks"])


# --------------------------------------------------------------------------- envelope
def test_ferramenta_planejar_metodo_envelope():
    env = REGISTRO["planejar_metodo"].funcao(
        R.PlanejarMetodoEntrada(operacao=_op(), data_referencia=REF))
    assert env.ok and env.ferramenta == "planejar_metodo"
    assert env.fonte_versao.startswith("rulebook-mcr-2-7@")
    assert env.data["data_referencia"] == "2026-10-08"


def test_ferramenta_planejar_metodo_entrada_invalida():
    env = REGISTRO["planejar_metodo"].funcao({"operacao": {"ref_bacen": "x", "finalidade": "nao-existe"}})
    assert not env.ok and env.error.code.value == "ENTRADA_INVALIDA"


def test_sem_data_de_referencia_avisa():
    env = REGISTRO["planejar_metodo"].funcao(R.PlanejarMetodoEntrada(operacao=_op()))
    assert env.ok and any("data_referencia" in a for a in env.data["avisos"])
