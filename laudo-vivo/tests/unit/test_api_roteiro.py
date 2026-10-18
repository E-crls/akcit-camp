"""Interface da demo (onda 3): ponteiro do roteiro que avança pela fala e pelos botões e "Pular passo" (L20),
caso padrão primeiro (L56), GTA em papel vira documento (L38), limites de tamanho (L104) e o split de teste
congelado que não abre pela web nem pela CLI (uso fora do registro). LLM roteirizado e ferramentas falsas, sem
GPU."""

from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from laudo.agent import estado as est
from laudo.api import casos as casos_mod
from laudo.api.main import criar_app, limite_corpo
from laudo.api.servico import LIMITE_UPLOAD_MB, Config, Servico, fala_corresponde
from laudo.tools import laudo as ferr_laudo

FIS = "fis_demo_regional"


@pytest.fixture()
def cli(tmp_path):
    def fazer(**kw):
        return TestClient(criar_app(Config(dados=tmp_path / "api", asr="desligado", **kw)))

    yield fazer
    est.ids_deterministicos(None)
    ferr_laudo.configurar(None, None)


def _proximo(c: TestClient, fis: str = FIS) -> dict:
    r = c.post(f"/api/fiscalizacoes/{fis}/roteiro/proximo")
    assert r.status_code == 200, r.text
    return r.json()


def _passo_atual(c: TestClient, fis: str = FIS) -> dict:
    rot = c.get(f"/api/fiscalizacoes/{fis}").json()["roteiro"]
    return {"n": rot["proximo"], **rot["passos"][rot["proximo"] - 1]}


def _ate_titulo(c: TestClient, titulo: str, fis: str = FIS) -> dict:
    for _ in range(30):
        p = _passo_atual(c, fis)
        if p["titulo"] == titulo:
            return p
        _proximo(c, fis)
    raise AssertionError(f"passo {titulo!r} não encontrado")


def test_fala_corresponde_tolera_a_transcricao():
    fala = "Pode marcar 29, o resto está no pasto de cima."
    assert fala_corresponde(fala, "pode marcar 29 o resto tá no pasto de cima")
    assert fala_corresponde(fala, "Pode marcar 29, o resto esta no pasto de cima")
    assert not fala_corresponde(fala, "Muda a contagem para 29.")
    assert not fala_corresponde(fala, "") and not fala_corresponde("", fala)


def test_fala_do_passo_pelo_microfone_avanca_o_ponteiro_e_o_passo_nao_se_repete(cli):
    """O operador diz no microfone (ou digita) a fala do passo atual em vez de apertar →: o ponteiro avança e
    o → seguinte vai para o próximo passo (antes repetia a pressão e o replay saía da gravação)."""
    c = cli()
    c.post("/api/fiscalizacoes", json={"caso": "roteiro"})
    p = _ate_titulo(c, "Pressão")
    r = c.post(f"/api/fiscalizacoes/{FIS}/turno", json={"texto": p["fala"].lower().rstrip(".")})
    assert r.status_code == 200 and any(x["tipo"] == "pressao" for x in r.json()["eventos"])
    assert r.json()["estado"]["roteiro"]["proximo"] == p["n"] + 1
    seguinte = _proximo(c)
    assert seguinte["passo"]["n"] == p["n"] + 1 and seguinte["passo"]["titulo"] != "Pressão"
    # fala que não é a do passo não mexe no ponteiro
    antes = _passo_atual(c)["n"]
    c.post(f"/api/fiscalizacoes/{FIS}/turno", json={"texto": "Qual é a regra da contagem?"})
    assert _passo_atual(c)["n"] == antes


def test_botao_emitir_rascunho_no_passo_do_pedido_avanca_o_ponteiro(cli):
    c = cli()
    c.post("/api/fiscalizacoes", json={"caso": "roteiro"})
    p = _ate_titulo(c, "Pedido de rascunho")
    r = c.post(f"/api/fiscalizacoes/{FIS}/rascunho")
    assert r.status_code == 200 and r.json()["eventos"][0]["tipo"] == "bloqueio"
    assert _passo_atual(c)["n"] == p["n"] + 1
    # fora do passo do pedido, o botão não mexe no ponteiro
    n = _passo_atual(c)["n"]
    c.post(f"/api/fiscalizacoes/{FIS}/rascunho")
    assert _passo_atual(c)["n"] == n


def test_evidencia_pronta_do_passo_avanca_o_ponteiro(cli):
    c = cli()
    c.post("/api/fiscalizacoes", json={"caso": "roteiro"})
    p = _passo_atual(c)
    while not p.get("evidencia"):
        _proximo(c)
        p = _passo_atual(c)
    r = c.post(f"/api/fiscalizacoes/{FIS}/evidencias/caso", json={"nome": p["evidencia"]})
    assert r.status_code == 200 and r.json()["estado"]["roteiro"]["proximo"] == p["n"] + 1


def test_pular_passo(cli):
    c = cli()
    c.post("/api/fiscalizacoes", json={"caso": "roteiro"})
    n0 = _passo_atual(c)["n"]
    r = c.post(f"/api/fiscalizacoes/{FIS}/roteiro/pular")
    assert r.status_code == 200 and r.json()["estado"]["roteiro"]["proximo"] == n0 + 1
    assert "pulado" in r.json()["aviso"] and r.json()["resposta"] is None
    assert c.get(f"/api/fiscalizacoes/{FIS}").json()["etapa"] == "BRIEFING"  # nada foi ao agente
    total = r.json()["estado"]["roteiro"]["total"]
    for _ in range(total):
        c.post(f"/api/fiscalizacoes/{FIS}/roteiro/pular")
    assert c.post(f"/api/fiscalizacoes/{FIS}/roteiro/pular").status_code == 409


def test_caso_padrao_vem_primeiro(tmp_path):
    srv = Servico(Config(dados=tmp_path / "api", asr="desligado", caso="DEMO-0001"))
    ids = [c["id"] for c in srv.listar_casos()]
    if casos_mod.localizar_caso("DEMO-0001") is None:
        pytest.skip("DEMO-0001 ausente")
    assert ids[0] == "DEMO-0001" and srv.listar_casos()[0]["padrao"] is True
    assert [c["id"] for c in srv.listar_casos() if c.get("padrao")] == ["DEMO-0001"]
    est.ids_deterministicos(None)
    ferr_laudo.configurar(None, None)


@pytest.mark.parametrize(
    "conteudo, formato",
    [(b"%PDF-1.7\n...", "PDF"), (b"\xff\xd8\xff\xe0 jpeg", "JPEG"), (b"\x89PNG\r\n\x1a\n png", "PNG")],
)
def test_gta_em_pdf_ou_imagem_vira_documento(cli, conteudo, formato):
    """Botão errado: o arquivo enviado como GTA é o papel (PDF/foto), não a e-GTA (JSON). Vira `documento` com
    `tipo_documento: gta` e não chega à conciliação da GTA como se fosse o JSON (L38)."""
    c = cli()
    c.post("/api/fiscalizacoes", json={"caso": "roteiro"})
    _proximo(c)
    r = c.post(
        f"/api/fiscalizacoes/{FIS}/evidencias",
        files={"arquivo": ("gta.bin", io.BytesIO(conteudo))},
        data={"tipo": "gta", "item_id": "bov1"},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert f"é {formato}" in j["aviso"] and "e-GTA é o JSON" in j["aviso"]
    fis = est.RepositorioFiscalizacoes(c.app.state.servico.dados).carregar(FIS)
    ev = next(e for e in reversed(fis.evidencias) if e.meta.get("enviado_como") == "gta")
    assert (
        ev.tipo == "documento"
        and ev.meta["tipo_documento"] == "gta"
        and ev.meta["formato_arquivo"] == formato
    )
    assert not any(e.tipo == "gta" and e.meta.get("nome_original") == "gta.bin" for e in fis.evidencias)


def test_gta_json_continua_gta(cli):
    c = cli()
    c.post("/api/fiscalizacoes", json={"caso": "roteiro"})
    _proximo(c)
    r = c.post(
        f"/api/fiscalizacoes/{FIS}/evidencias",
        files={"arquivo": ("gta.json", io.BytesIO(b'{"numero": "1"}'))},
        data={"tipo": "gta", "item_id": "bov1"},
    )
    assert r.status_code == 200 and "aviso" not in r.json()
    fis = est.RepositorioFiscalizacoes(c.app.state.servico.dados).carregar(FIS)
    assert any(e.tipo == "gta" and e.meta.get("nome_original") == "gta.json" for e in fis.evidencias)


def test_limites_de_tamanho_da_api(cli):
    """L104: corpo acima do limite da rota volta 413 antes de ser lido inteiro (pelo Content-Length declarado
    e pelos bytes que chegam, sem Content-Length)."""
    assert limite_corpo("/api/fiscalizacoes/x/evidencias") > max(LIMITE_UPLOAD_MB.values()) * 1024 * 1024
    assert limite_corpo("/api/fiscalizacoes/x/turno") == 1024 * 1024
    c = cli()
    c.post("/api/fiscalizacoes", json={"caso": "roteiro"})
    grande = b'{"texto": "' + b"a" * (2 * 1024 * 1024) + b'"}'
    r = c.post(
        f"/api/fiscalizacoes/{FIS}/turno", content=grande, headers={"content-type": "application/json"}
    )
    assert r.status_code == 413 and "limite" in r.json()["erro"]

    def em_pedacos():
        yield b'{"texto": "'
        for _ in range(3):
            yield b"a" * (1024 * 1024)
        yield b'"}'

    r = c.post(
        f"/api/fiscalizacoes/{FIS}/turno", content=em_pedacos(), headers={"content-type": "application/json"}
    )
    assert r.status_code == 413
    assert c.post(f"/api/fiscalizacoes/{FIS}/turno", json={"texto": "Bom dia."}).status_code == 200


def test_caso_do_split_de_teste_congelado_nao_abre_pela_web_nem_pela_cli(tmp_path, monkeypatch):
    teste = sorted(casos_mod.casos_do_teste_congelado())
    if not teste:
        pytest.skip("split de teste não congelado nesta cópia")
    gid = teste[0]
    c = TestClient(criar_app(Config(dados=tmp_path / "api", asr="desligado")))
    r = c.post("/api/fiscalizacoes", json={"caso": gid})
    assert (
        r.status_code == 403
        and "split de teste congelado" in r.json()["erro"]
        and "registro" in r.json()["erro"]
    )
    with pytest.raises(casos_mod.CasoDoTesteCongelado):  # CLI: `python -m laudo.api --caso GLD-...`
        casos_mod.carregar_caso(gid, tmp_path / "t")
    # CLI da demo: recusa antes de qualquer limpeza (a pasta de dados e a gravação ficam como estavam)
    spec = importlib.util.spec_from_file_location(
        "demo_cli_j1", Path(__file__).parents[2] / "scripts" / "demo_cli.py"
    )
    demo_cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo_cli)
    dados = tmp_path / "cli"
    (dados / "fiscalizacoes").mkdir(parents=True)
    (dados / "fiscalizacoes" / "marca.json").write_text("{}", encoding="utf-8")
    gravacao = tmp_path / "grav.jsonl"
    gravacao.write_text("{}\n", encoding="utf-8")
    argv = ["demo_cli.py", "--ferramentas", "reais", "--caso", str(casos_mod.localizar_caso(gid)),
            "--dados", str(dados), "--gravar", str(gravacao), "--sem-cor"]
    monkeypatch.setattr(sys, "argv", argv)
    assert demo_cli.main() == 2
    assert (dados / "fiscalizacoes" / "marca.json").is_file() and gravacao.is_file()
    dev = sorted(set(casos_mod.listar_casos_disponiveis()) | {"GLD-0001"} - set(teste))
    assert casos_mod.checar_uso_do_teste(casos_mod.localizar_caso(dev[-1]) or tmp_path, dev[-1]) is None
    monkeypatch.setenv(casos_mod.ENV_USO_TESTE, "1")  # só para depurar: abre, com aviso
    caso = casos_mod.carregar_caso(gid, tmp_path / "t")
    assert "AVISO" in caso.aviso_uso and caso.resumo()["aviso_uso"]
    est.ids_deterministicos(None)
    ferr_laudo.configurar(None, None)
