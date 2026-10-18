"""Rulebook MCR 2-9 (Prodes e documentos de regularização) — módulo da final. Casos por tabela."""

from __future__ import annotations

from datetime import date

import pytest

from laudo.contracts import Checagem, Evidencia, Fiscalizacao, ItemFinanciado, Operacao
from laudo.tools import regras as R

REF = date(2027, 2, 10)

CASOS_DOCUMENTOS = [
    # norma, tipo, data de emissão, situação esperada
    ("2-9-18-a-I: UAS antes de 15/03/2026 é aceita", "UAS", date(2026, 3, 14), "aceito"),
    ("2-9-18-a-I: UAS em 15/03/2026 já não é aceita", "UAS", date(2026, 3, 15), "recusado"),
    ("2-9-18-a-I: ato equivalente antigo é aceito", "ato_equivalente", date(2024, 5, 2), "aceito"),
    ("2-9-18-a-II: ASV antes de 15/09/2025 é aceita", "ASV", date(2025, 9, 14), "aceito"),
    ("2-9-18-a: ASV a partir de 15/09/2025 exige validação humana (Conama 510)", "ASV", date(2025, 9, 15),
     "validacao_humana"),
    ("2-9-18-a: ASV sem data exige validação humana", "ASV", None, "validacao_humana"),
    ("2-9-18-b: PRAD/PRA aprovado", "PRAD", None, "aceito"),
    ("2-9-18-c: TAC com o Ministério Público", "TAC", None, "aceito"),
    ("2-9-18-d: laudo de sensoriamento remoto da IF", "laudo_sr", None, "aceito"),
    ("2-9-18-e: Termo de Compromisso Ambiental", "TCA", None, "aceito"),
    ("2-9-18: documento fora da lista", "CPR", None, "desconhecido"),
]


@pytest.mark.parametrize("norma,tipo,emissao,esperado", CASOS_DOCUMENTOS, ids=[c[0] for c in CASOS_DOCUMENTOS])
def test_documento_de_regularizacao(norma, tipo, emissao, esperado):
    situacao, motivo = R.documento_18_aceito(tipo, emissao)
    assert situacao == esperado, motivo


def _op(contratacao: date) -> Operacao:
    return Operacao(ref_bacen="TESTE-SINTETICO-0029", tomador_ref="anon-teste", finalidade="investimento",
                    data_contratacao=contratacao, area_financiada_ha=120.0, fonte="sintetico",
                    itens=[ItemFinanciado(id="bov1", tipo="bovinos", descricao="bovinos (sintético)", quantidade=10)])


def _chk(status: str) -> Checagem:
    return Checagem(ferramenta="consultar_prodes", entrada_hash="teste", status=status,
                    resultado={"motivo": "supressão de 3,2 ha em 2022" if status == "divergente" else ""})


def _doc(tipo: str, emissao: str | None) -> Evidencia:
    return Evidencia(tipo="documento", sha256="0" * 64, meta={"tipo_documento": tipo, "data_emissao": emissao})


def _avaliar(chks=(), docs=(), contratacao=date(2027, 2, 1), mf=20.0, fonte=None):
    fis = Fiscalizacao(operacao=_op(contratacao), metodo="documental", checagens=list(chks), evidencias=list(docs))
    ctx = R.ContextoRegras(modulos_fiscais=mf, fonte_recursos=fonte, rulebooks=["mcr-2-7", "mcr-2-9"])
    return R.avaliar(fis, ctx, REF)


CASOS_PRODES = [
    # norma, checagens, documentos, fonte de recursos, esperado
    ("OP-2-9-prodes-status: sem consulta → pendente", [], [], None, "pendente"),
    ("2-9-17: sem supressão pós-2019 → verificado", [_chk("ok")], [], None, "verificado"),
    ("2-9-18: supressão sem documento → pendente", [_chk("divergente")], [], "controlados", "pendente"),
    ("2-9-18-a-I: supressão + UAS antiga → verificado", [_chk("divergente")], [_doc("UAS", "2026-01-10")],
     "controlados", "verificado"),
    ("2-9-18-a-I: supressão + UAS posterior a 15/03/2026 → divergente", [_chk("divergente")],
     [_doc("UAS", "2026-04-01")], "direcionados", "divergente"),
    ("2-9-18-a: supressão + ASV recente → pendente (validação humana)", [_chk("divergente")],
     [_doc("ASV", "2025-12-01")], "controlados", "pendente"),
    ("2-9-18: recursos livres não condicionam a concessão", [_chk("divergente")], [], "livres", "verificado"),
    ("PAR-prodes-fonte-recursos-desconhecida-aplica: fonte desconhecida exige documento", [_chk("divergente")], [],
     None, "pendente"),
    ("PAR-tentativas: consulta inconclusiva 2× → abstenção", [_chk("indeterminado"), _chk("indeterminado")], [],
     None, "abstencao"),
]


@pytest.mark.parametrize("norma,chks,docs,fonte,esperado", CASOS_PRODES, ids=[c[0] for c in CASOS_PRODES])
def test_campo_prodes(norma, chks, docs, fonte, esperado):
    res = _avaliar(chks, docs, fonte=fonte)
    campo = res.campos["imovel:prodes"]
    assert campo.status == esperado, campo.motivo
    assert campo.regra_id == "OP-2-9-prodes-status"
    assert campo.valor["alinea"] == "a" and campo.valor["inicio_exigencia"] == "2027-01-04"


def test_prodes_nao_vigente_para_a_operacao():
    """2-9-17-a: imóvel > 15 MF, operação contratada em 03/01/2027 (véspera do início)."""
    res = _avaliar([_chk("divergente")], contratacao=date(2027, 1, 3))
    assert "imovel:prodes" not in res.campos
    assert any(n["campo"] == "imovel:prodes" for n in res.nao_aplicaveis)


def test_prodes_sem_modulos_fiscais_fica_pendente():
    res = _avaliar([_chk("ok")], mf=None)
    assert res.campos["imovel:prodes"].status == "pendente"
    assert "imovel:prodes" in {b.campo for b in res.bloqueios}


def test_mcr_2_9_so_entra_quando_pedido():
    fis = Fiscalizacao(operacao=_op(date(2027, 2, 1)), metodo="documental", checagens=[_chk("divergente")])
    res = R.avaliar(fis, R.ContextoRegras(modulos_fiscais=20.0), REF)
    assert "imovel:prodes" not in res.campos and "mcr-2-9" not in res.fonte_versao
