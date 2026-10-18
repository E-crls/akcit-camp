"""Laudo (rodada 3): seção alegações × evidência (OP-alegacao-declaracao-x-evidencia), origem de cada valor e
números em pt-BR nos motivos ("27,55", não "27.55")."""

from __future__ import annotations

import pytest

from laudo.agent import estado as est
from laudo.agent.condutor import Condutor, Evento, NovaEvidencia
from laudo.agent.ferramentas_falsas import criar_ferramentas_falsas, operacao_exemplo
from laudo.audit import otel
from laudo.contracts import REGISTRO
from laudo.tools import carregar_todas
from laudo.tools import laudo as ferr_laudo

CENARIO = {"curral.mp4": {"contar_bovinos_video": {"status": "ok", "contagem": 32, "intervalo": [31, 33]}}}


@pytest.fixture()
def cond(tmp_path):
    otel.configurar(tmp_path / "traces")
    est.ids_deterministicos("laudo-alegacoes")
    (tmp_path / "curral.mp4").write_bytes(b"curral")
    carregar_todas()
    reg = criar_ferramentas_falsas(CENARIO) | {"avaliar_regras": REGISTRO["avaliar_regras"]}
    yield Condutor(None, repo=est.RepositorioFiscalizacoes(tmp_path), registro=reg), tmp_path
    est.ids_deterministicos(None)
    ferr_laudo.configurar(None, None)


def test_alegacao_ao_lado_da_evidencia_e_origem_do_valor(cond):
    c, tmp = cond
    fis = c.abrir(operacao_exemplo(), estado_fsm="COLETA", metodo="presencial")
    c.turno(fis.id, Evento(texto="Contei 40 cabeças no curral."))
    c.turno(fis.id, Evento(evidencia=NovaEvidencia(tipo="video", caminho=str(tmp / "curral.mp4"), item_id="bov1")))
    final = c.repo.carregar(fis.id)
    res = c.verificador.recalcular(final)
    final.campos = res.campos
    laudo = ferr_laudo.montar_laudo(final, res, politica=c.politica)
    [a] = laudo["alegacoes_x_evidencia"]
    assert a["status"] == "divergente" and a["regra_id"] == "OP-alegacao-declaracao-x-evidencia"
    assert "o vídeo contou 32" in a["motivo"]
    qtd = next(x for x in laudo["itens"] if x["campo"] == "item:bov1:quantidade")
    assert qtd["proveniencia"] == ["vídeo (contagem por visão computacional)"]
    assert "limite 38" in qtd["motivo"] and "." not in qtd["motivo"].split("limite")[1][:6]
    html = ferr_laudo.renderizar_html(laudo)
    assert "Alegações × evidência" in html and "Contei 40 cabeças" in html


def test_motivo_com_decimal_em_pt_br(cond):
    from laudo.agent.ferramentas_falsas import operacao_exemplo as op_ex

    c, tmp = cond
    op = op_ex()
    op.itens[0].quantidade = 29  # limite 27,55 com a tolerância de 5%
    fis = c.abrir(op, estado_fsm="COLETA", metodo="presencial")
    c.turno(fis.id, Evento(evidencia=NovaEvidencia(tipo="video", caminho=str(tmp / "curral.mp4"), item_id="bov1")))
    motivo = c.repo.carregar(fis.id).campos["item:bov1:quantidade"].motivo
    assert "27,55" in motivo and "27.55" not in motivo
