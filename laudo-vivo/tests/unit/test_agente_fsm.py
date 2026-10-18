"""Máquina de estados da fiscalização."""

import pytest

from laudo.agent import fsm
from laudo.agent.ferramentas_falsas import criar_ferramentas_falsas, operacao_exemplo
from laudo.contracts import Fiscalizacao

E = fsm.Etapa


def _fis(etapa: str = "BRIEFING") -> Fiscalizacao:
    return Fiscalizacao(operacao=operacao_exemplo(), estado_fsm=etapa)


def test_caminho_feliz_completo():
    fis = _fis()
    for e in (E.COLETA, E.CHECAGEM, E.COLETA, E.CHECAGEM, E.CONCILIACAO, E.REVISAO, E.RASCUNHO, E.ASSINATURA):
        fsm.transitar(fis, e)
    fsm.transitar(fis, E.SELADO, humano=True)
    assert fis.estado_fsm == "SELADO" and fsm.TRANSICOES[E.SELADO] == frozenset()


def test_transicao_invalida_e_selo_so_humano():
    with pytest.raises(fsm.TransicaoInvalida):
        fsm.transitar(_fis("BRIEFING"), E.REVISAO)
    with pytest.raises(fsm.TransicaoInvalida):
        fsm.transitar(_fis("ASSINATURA"), E.SELADO)  # o agente não sela
    assert not fsm.pode_transitar("ASSINATURA", "SELADO") and fsm.pode_transitar(
        "ASSINATURA", "SELADO", humano=True
    )


def test_lacuna_volta_para_coleta_e_caminho_minimo():
    assert fsm.caminho("RASCUNHO", "CHECAGEM") == [E.REVISAO, E.COLETA, E.CHECAGEM]
    assert fsm.caminho("COLETA", "RASCUNHO") == [E.CHECAGEM, E.CONCILIACAO, E.REVISAO, E.RASCUNHO]
    assert fsm.caminho("ASSINATURA", "SELADO") is None
    fis = _fis("ASSINATURA")
    assert fsm.ir_para(fis, "CHECAGEM") == [E.REVISAO, E.COLETA, E.CHECAGEM]
    with pytest.raises(fsm.TransicaoInvalida):
        fsm.ir_para(_fis("SELADO"), "COLETA")


def test_acoes_por_estado():
    assert "planejar_metodo" in fsm.acoes_permitidas("BRIEFING")
    assert "contar_bovinos_video" not in fsm.acoes_permitidas("BRIEFING")
    assert "contar_bovinos_video" in fsm.acoes_permitidas("CHECAGEM")
    assert "emitir_rascunho" in fsm.acoes_permitidas("REVISAO")
    assert "emitir_rascunho" not in fsm.acoes_permitidas("CHECAGEM")
    assert "solicitar_assinatura" in fsm.acoes_permitidas("RASCUNHO")
    assert fsm.acoes_permitidas("SELADO") == frozenset()
    assert not (fsm.ACOES_HUMANAS & set().union(*[fsm.acoes_permitidas(e) for e in E]))  # nunca para o LLM


def test_ferramentas_permitidas_respeitam_o_registro():
    reg = criar_ferramentas_falsas()
    nomes = [f.nome for f in fsm.ferramentas_permitidas("CHECAGEM", reg)]
    assert "contar_bovinos_video" in nomes and "checar_lotacao" not in nomes  # ausente do registro
    assert fsm.nomes_permitidos("BRIEFING", reg) == [
        "avancar_etapa",
        "pedir_evidencia",
        "planejar_metodo",
        "serie_ndvi",
    ]
