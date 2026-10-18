"""Persistência da fiscalização: atomicidade, append-only, selo e conversa."""

import json

import pytest

from laudo.agent import estado as est
from laudo.agent.ferramentas_falsas import operacao_exemplo
from laudo.contracts import CodigoErro, Envelope


@pytest.fixture()
def repo(tmp_path):
    return est.RepositorioFiscalizacoes(tmp_path)


def test_criar_carregar_e_listar(repo):
    fis = repo.criar(operacao_exemplo())
    assert repo.existe(fis.id) and fis.id in repo.listar()
    assert repo.carregar(fis.id) == fis
    with pytest.raises(ValueError):
        repo.caminho("../fora")


def test_evidencia_checagem_ocorrencia_alegacao(repo):
    fis = repo.criar(operacao_exemplo())
    ev = est.adicionar_evidencia(fis, "declaracao", conteudo=b"contei 40", meta={"texto": "contei 40"})
    chk = est.registrar_checagem(
        fis,
        "contar_bovinos_video",
        "h1",
        Envelope.sucesso("contar_bovinos_video", {"status": "ok", "contagem": 40}),
        item_id="bov1",
        evidencias=[ev.id],
        span_id="abcd",
    )
    oc = est.registrar_ocorrencia(fis, "pressao", "pedido para marcar valor")
    al = est.registrar_alegacao(fis, {"grandeza": "quantidade", "valor": 40})
    repo.salvar(fis)
    f2 = repo.carregar(fis.id)
    assert f2.checagens[0].id == chk.id and f2.checagens[0].trace_id == "abcd"
    assert f2.evidencias[-1].tipo == "ocorrencia" and f2.evidencias[-1].meta["ocorrencia_id"] == oc.id
    assert f2.alegacoes[0]["id"] == al["id"]
    assert est.checagem_existente(f2, "contar_bovinos_video", "h1").id == chk.id


def test_status_de_envelope():
    assert est.status_de_envelope(Envelope.sucesso("g", {"status": "dentro"})) == "ok"
    assert est.status_de_envelope(Envelope.sucesso("g", {"status": "fora"})) == "divergente"
    assert est.status_de_envelope(Envelope.sucesso("g", {"status": "algo_estranho"})) == "indeterminado"
    assert est.status_de_envelope(Envelope.falha("n", CodigoErro.NUVEM, "nuvem")) == "indeterminado"
    assert est.status_de_envelope(Envelope.falha("n", CodigoErro.TIMEOUT, "t")) == "erro"


def test_append_only_remocao_e_alteracao_sao_negadas(repo):
    fis = repo.criar(operacao_exemplo())
    est.adicionar_evidencia(fis, "foto", conteudo=b"a")
    est.adicionar_evidencia(fis, "foto", conteudo=b"b")
    repo.salvar(fis)
    removida = repo.carregar(fis.id)
    removida.evidencias.pop()
    with pytest.raises(est.ViolacaoAppendOnly):
        repo.salvar(removida)
    alterada = repo.carregar(fis.id)
    alterada.evidencias[0].meta["x"] = 1
    with pytest.raises(est.ViolacaoAppendOnly):  # cadeia quebra e prefixo muda
        repo.salvar(alterada)


def test_operacao_imutavel_fora_do_briefing(repo):
    fis = repo.criar(operacao_exemplo())
    fis.estado_fsm = "COLETA"
    repo.salvar(fis)
    fis.operacao.valor_rs = 1.0
    with pytest.raises(est.ViolacaoAppendOnly):
        repo.salvar(fis)


def test_fiscalizacao_selada_nao_muda(repo):
    fis = repo.criar(operacao_exemplo())
    fis.estado_fsm = "SELADO"
    repo.salvar(fis)
    with pytest.raises(est.FiscalizacaoSelada):
        est.adicionar_evidencia(fis, "foto", conteudo=b"nova")
    fis2 = repo.carregar(fis.id)
    fis2.metodo = "remoto"
    with pytest.raises(est.FiscalizacaoSelada):
        repo.salvar(fis2)


def test_conversa_append_only_e_mascarada(repo):
    fis = repo.criar(operacao_exemplo())
    repo.anexar_conversa(fis.id, {"turno": 1, "fiscal": "meu telefone é (62) 99999-0000"})
    repo.anexar_conversa(fis.id, {"turno": 2, "fiscal": "ok"})
    linhas = repo.ler_conversa(fis.id)
    assert [x["turno"] for x in linhas] == [1, 2] and "99999" not in json.dumps(linhas)
    assert repo.ler_conversa(fis.id, ultimos=1)[0]["turno"] == 2


def test_ids_deterministicos():
    est.ids_deterministicos("semente")
    try:
        a = [est.novo_id("ev") for _ in range(3)]
        est.ids_deterministicos("semente")
        assert [est.novo_id("ev") for _ in range(3)] == a
    finally:
        est.ids_deterministicos(None)
    assert est.novo_id("ev") != est.novo_id("ev")
