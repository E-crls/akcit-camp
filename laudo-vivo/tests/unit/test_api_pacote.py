"""API: abertura "por que caiu na amostra" na carteira e na fiscalização, e rotas do pacote de exibição antes
de SELADO (o caminho completo, até o ZIP, está em `test_pacote_exibicao.py`)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from laudo.agent import estado as est
from laudo.api.main import criar_app
from laudo.api.servico import Config
from laudo.tools import laudo as ferr_laudo


@pytest.fixture()
def cli(tmp_path):
    c = TestClient(criar_app(Config(dados=tmp_path / "api", asr="desligado")))
    yield c
    est.ids_deterministicos(None)
    ferr_laudo.configurar(None, None)


def _bench_disponivel() -> bool:
    try:
        from laudo.geo import bench

        bench.operacoes()
        return True
    except Exception:  # noqa: BLE001 - sem bench local: o teste da carteira real é pulado
        return False


def test_carteira_traz_a_abertura_dos_casos(cli):
    dados = cli.get("/api/carteira", params={"limite": 5}).json()
    casos = {c["id"]: c for c in dados["casos"]}
    assert "roteiro" in casos
    a = casos["roteiro"]["amostra"]
    assert a["tem_triagem"] and a["motivos"] and "não é indício de irregularidade" in a["aviso"]
    if "DEMO-0001" in casos:
        m = casos["DEMO-0001"]["amostra"]["motivos"][0]
        assert m["codigo"] == "LOTACAO_ALTA" and m["pontos"] == 3 and "cab/ha" in m["criterio"]


@pytest.mark.skipif(not _bench_disponivel(), reason="bench Fiscal-GO ausente nesta máquina")
def test_carteira_real_abre_cada_motivo_com_codigo(cli):
    ops = cli.get("/api/carteira", params={"limite": 20, "prioridade_minima": 4}).json()["operacoes"]
    assert ops
    for o in ops:
        a = o["amostra"]
        assert a["tem_triagem"] and a["fundamento"] == []  # compacto na lista
        assert [m["codigo"] for m in a["motivos"]] == o["motivos_codigos"]
        assert sum(m["pontos"] or 0 for m in a["motivos"]) == o["prioridade_verificacao"]
        assert all(m["criterio"] and "(+" not in m["texto"] for m in a["motivos"])


def test_fiscalizacao_aberta_mostra_amostra_e_pacote_bloqueado(cli):
    e = cli.post("/api/fiscalizacoes", json={"caso": "roteiro"}).json()
    assert e["amostra"]["tem_triagem"] and e["amostra"]["aviso"]
    assert e["pacote"] == {
        "liberado": False,
        "regra_id": "POL-03",
        "motivo": "liberado só depois de SELADO (assinatura humana)",
        "gerado": False,
    }
    r = cli.post(f"/api/fiscalizacoes/{e['id']}/pacote")
    assert r.status_code == 409 and "SELADO" in r.json()["erro"]
    assert cli.get(f"/api/fiscalizacoes/{e['id']}/pacote.zip").status_code == 404
    assert (
        cli.post(f"/api/fiscalizacoes/{e['id']}/pacote", params={"prazo_contestacao_dias": 2}).status_code
        == 400
    )
    gov = cli.get(f"/api/fiscalizacoes/{e['id']}").json()["governanca"]
    assert any(g["acao"] == "gerar_pacote_exibicao" and g["resultado"] == "negar" for g in gov)
