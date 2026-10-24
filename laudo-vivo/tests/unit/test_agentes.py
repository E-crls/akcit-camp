"""Arquitetura de agentes v2: registro (`laudo.agentes`), cartão A2A, `GET /api/agentes` e o Agente Auditor
(`laudo.agent.auditor`, `POST /api/fiscalizacoes/{id}/auditoria`), que nunca muda o estado da fiscalização."""

import json

import pytest
from fastapi.testclient import TestClient

from laudo import agentes
from laudo.agent import auditor
from laudo.agent import estado as est
from laudo.api.main import criar_app
from laudo.api.servico import Config
from laudo.llm.provider import ErroLLM, ProvedorRoteirizado
from laudo.tools import carregar_todas
from laudo.tools import laudo as ferr_laudo

FIS = "fis_demo_regional"


# ---------------------------------------------------------------------------- registro
def test_toda_ferramenta_tem_um_agente():
    nomes = set(carregar_todas())
    assert nomes, "registro de ferramentas vazio"
    sem_dono = {n for n in nomes if agentes.agente_da_ferramenta(n) is None}
    assert not sem_dono, f"ferramentas sem agente: {sorted(sem_dono)}"
    # avaliar_regras é do verificador (guarda-corpo, sem IA); as demais, de um agente
    assert agentes.agente_da_ferramenta("avaliar_regras") == "verificador"
    ids_agentes = {a.id for a in agentes.AGENTES}
    for n in nomes - {"avaliar_regras"}:
        assert agentes.agente_da_ferramenta(n) in ids_agentes, n
    # as ferramentas declaradas existem de verdade
    declaradas = {f for a in agentes.AGENTES for f in a.ferramentas} | {f for g in agentes.GUARDA_CORPOS for f in g.ferramentas}
    assert declaradas <= nomes


def test_seis_agentes_e_quatro_guarda_corpos():
    assert [a.id for a in agentes.AGENTES] == ["triagem", "condutor", "visao", "documentos", "territorio", "auditor"]
    assert [g.id for g in agentes.GUARDA_CORPOS] == ["politica", "verificador", "selo", "assinatura"]
    assert all(not g.ia for g in agentes.GUARDA_CORPOS)
    aud = agentes.agente("auditor")
    assert aud is not None and aud.novo and not aud.ferramentas and "não muda" in aud.guarda_corpo.lower()
    for a in agentes.AGENTES:
        assert a.nome and a.papel and a.quando_age and a.modelo and a.guarda_corpo and a.saida
    assert agentes.agente_da_ferramenta("contar_bovinos_video") == "visao"
    assert agentes.agente_da_ferramenta("conciliar_gta") == "documentos"
    assert agentes.agente_da_ferramenta("geofence") == "territorio"
    assert agentes.agente_da_ferramenta("triar_carteira") == "triagem"
    assert agentes.agente_da_ferramenta("emitir_rascunho") == "condutor"
    assert agentes.agente_da_ferramenta("nao_existe") is None


# ---------------------------------------------------------------------------- API
@pytest.fixture()
def cli(tmp_path):
    def fazer(**kw):
        return TestClient(criar_app(Config(dados=tmp_path / "api", asr="desligado", **kw)))

    yield fazer
    est.ids_deterministicos(None)
    ferr_laudo.configurar(None, None)


def _passos(c, ate):
    while True:
        r = c.post(f"/api/fiscalizacoes/{FIS}/roteiro/proximo")
        assert r.status_code == 200, r.text
        if r.json()["passo"]["n"] >= ate:
            return


def test_api_agentes_e_cartao_a2a(cli):
    c = cli()
    j = c.get("/api/agentes").json()
    assert len(j["agentes"]) == 6 and len(j["guarda_corpos"]) == 4
    assert j["ferramenta_agente"]["contar_bovinos_video"] == "visao"
    assert j["interop"]["a2a"] == "/.well-known/agent.json"
    assert "contar_bovinos_video" in j["interop"]["mcp"]["ferramentas"]
    assert set(j["interop"]["mcp"]["gravam_estado"]) <= set(j["interop"]["mcp"]["ferramentas"])
    card = c.get("/.well-known/agent.json", headers={"x-forwarded-proto": "https", "x-forwarded-host": "lv.exemplo"}).json()
    assert card["name"] == "Laudo Vivo" and card["url"] == "https://lv.exemplo/"
    assert card["capabilities"] == {"streaming": False, "pushNotifications": False}
    assert card["version"] and card["provider"]["organization"] and card["description"]
    assert card["defaultInputModes"] and card["defaultOutputModes"]
    assert [s["id"] for s in card["skills"]] == ["fiscalizar_operacao", "revisar_laudo"]
    for s in card["skills"]:
        assert s["name"] and s["description"] and s["tags"] and s["examples"]
    assert "a construir" in card["description"]  # honestidade: o recebimento de tarefas ainda não existe


def test_cartao_a2a_aberto_com_senha_da_demo_publica(monkeypatch):
    from laudo.api import acesso

    assert acesso.aberto("/.well-known/agent.json")
    assert not acesso.aberto("/api/agentes")


def _estado_completo(c):
    j = c.get(f"/api/fiscalizacoes/{FIS}").json()
    return json.dumps(j, sort_keys=True, ensure_ascii=False)


def test_auditor_pelas_regras_no_roteiro_e_estado_inalterado(cli):
    c = cli()
    c.post("/api/fiscalizacoes", json={"caso": "roteiro"})
    _passos(c, ate=12)  # rascunho emitido
    srv = c.app.state.servico
    antes_fis = srv.carregar(FIS).model_dump(mode="json")
    antes = _estado_completo(c)
    r = c.post(f"/api/fiscalizacoes/{FIS}/auditoria")
    assert r.status_code == 200, r.text
    out = r.json()
    # roteiro fixo dos testes: chamar o LLM gastaria a próxima resposta do roteiro, então o parecer vem das regras
    assert out["origem"] == "regras" and out["parecer"]["recomendacao"] in ("pode_assinar", "revisar_antes")
    assert "não muda nenhum status" in out["nota"]
    assert _estado_completo(c) == antes
    assert srv.carregar(FIS).model_dump(mode="json") == antes_fis
    # o roteiro continua: o próximo passo é a assinatura
    assert c.post(f"/api/fiscalizacoes/{FIS}/roteiro/proximo").json()["acao_humana"] == "assinar"


def test_auditor_com_llm_valida_ids_e_nao_muda_estado(cli):
    c = cli()
    c.post("/api/fiscalizacoes", json={"caso": "roteiro"})
    _passos(c, ate=12)
    srv = c.app.state.servico
    linhas = c.get(f"/api/fiscalizacoes/{FIS}").json()["matriz"]
    campo = next(ln for ln in linhas if ln.get("evidencias") or ln.get("checagens"))
    ev_ok = (campo.get("evidencias") or campo.get("checagens"))[0]
    parecer = {
        "resumo": "Contagem confere com a GTA; a nota cita o mesmo lote.",
        "itens": [
            {"item_id": campo["campo"], "risco": "baixo", "motivo": "ok", "evidencias": [ev_ok, "ev_inventada"],
             "pergunta_para_a_fiscal": "Confere?"},
            {"item_id": "item:inexistente:x", "risco": "alto", "motivo": "x", "evidencias": [],
             "pergunta_para_a_fiscal": "?"},
        ],
        "recomendacao": "pode_assinar",
    }
    srv.provedor = ProvedorRoteirizado([json.dumps(parecer, ensure_ascii=False)], modelo="auditor-teste")
    antes = _estado_completo(c)
    antes_fis = srv.carregar(FIS).model_dump(mode="json")
    out = c.post(f"/api/fiscalizacoes/{FIS}/auditoria").json()
    assert out["origem"] == "llm" and out["modelo"] == "auditor-teste"
    ids = [i["item_id"] for i in out["parecer"]["itens"]]
    assert ids == [campo["campo"]]  # o item inexistente saiu
    assert out["parecer"]["itens"][0]["evidencias"] == [ev_ok]  # a evidência inventada saiu
    assert any("inexistente" in a for a in out["avisos"])
    assert _estado_completo(c) == antes
    assert srv.carregar(FIS).model_dump(mode="json") == antes_fis
    # o LLM recebeu o schema do parecer (saída estruturada)
    assert "recomendacao" in json.dumps(srv.provedor.chamadas[0]["formato"])


# ---------------------------------------------------------------------------- Auditor (unidade)
def _estado(status="verificado", justificativa=None):
    return {
        "etapa": "ASSINATURA",
        "matriz": [
            {"campo": "item:bov:quantidade", "item_id": "bov", "item_descricao": "Bovinos", "aspecto": "Quantidade",
             "status": status, "regra_id": "MCR-2-7-x", "motivo": "contagem 38 de 40", "justificativa": justificativa,
             "evidencias": ["ev_1"], "checagens": ["chk_1"], "valor_fmt": "38"},
            {"campo": "item:bov:gta", "item_id": "bov", "item_descricao": "Bovinos", "aspecto": "GTA",
             "status": "verificado", "motivo": "", "evidencias": ["ev_2"], "checagens": []},
        ],
        "evidencias": [{"id": "ev_1"}, {"id": "ev_2"}],
        "falas": [],
        "checagens": [{"id": "chk_1", "ferramenta": "contar_bovinos_video", "status": "ok", "item_id": "bov"}],
    }


def _resp(rec="pode_assinar", itens=None):
    return json.dumps({"resumo": "r", "itens": itens or [], "recomendacao": rec})


def test_auditor_forca_revisar_com_divergencia_sem_justificativa():
    p = ProvedorRoteirizado([_resp("pode_assinar")])
    out = auditor.auditar(_estado("divergente"), p)
    assert out["origem"] == "llm" and out["parecer"]["recomendacao"] == "revisar_antes"
    assert any("ajustada" in a for a in out["avisos"])
    # justificada pela fiscal: a recomendação do LLM fica
    out2 = auditor.auditar(_estado("divergente", justificativa="2 animais no pasto ao lado"), ProvedorRoteirizado([_resp()]))
    assert out2["parecer"]["recomendacao"] == "pode_assinar"


def test_auditor_cai_nas_regras_com_erro_ou_saida_invalida():
    p = ProvedorRoteirizado([ErroLLM("TIMEOUT", "lento")])
    out = auditor.auditar(_estado("divergente"), p)
    assert out["origem"] == "regras" and out["parecer"]["recomendacao"] == "revisar_antes"
    it = out["parecer"]["itens"][0]
    assert it["item_id"] == "item:bov:quantidade" and it["risco"] == "alto" and it["evidencias"] == ["ev_1", "chk_1"]
    assert any("TIMEOUT" in a for a in out["avisos"])
    invalido = auditor.auditar(_estado(), ProvedorRoteirizado(["não sei", "ainda não"]))
    assert invalido["origem"] == "regras" and invalido["parecer"]["recomendacao"] == "pode_assinar"
    sem = auditor.auditar(_estado("pendente"), None)
    assert sem["origem"] == "regras" and sem["parecer"]["recomendacao"] == "revisar_antes"


def test_auditor_mascara_pii_para_provedor_externo():
    class Externo(ProvedorRoteirizado):
        externo = True

    e = _estado()
    e["matriz"][0]["motivo"] = "produtor CPF 529.982.247-25 declarou 40"
    p = Externo([_resp()])
    auditor.auditar(e, p)
    enviado = p.chamadas[0]["mensagens"][-1]["content"]
    assert "529.982.247-25" not in enviado
    local = ProvedorRoteirizado([_resp()])
    auditor.auditar(e, local)
    assert "529.982.247-25" in local.chamadas[0]["mensagens"][-1]["content"]


# ---------------------------------------------------------------------------- demo pública
def test_auditor_na_demo_publica_e_livre_conta_na_cota_e_nao_desalinha_o_roteiro(tmp_path, monkeypatch, capsys):
    from laudo.api import casos as casos_mod
    from laudo.api.servico import PIN_DEMO

    if casos_mod.localizar_caso("DEMO-0001") is None:
        pytest.skip("DEMO-0001 ausente")
    monkeypatch.setenv("LAUDO_DEMO_PUBLICA", "1")
    monkeypatch.setenv("LAUDO_DEMO_DIR", str(tmp_path / "copias"))
    monkeypatch.setenv("LAUDO_LLM_LIVRE", "roteiro")
    app = criar_app(Config(dados=tmp_path / "api", caso="DEMO-0001", asr="desligado"))
    fis = "fis_demo_0001"

    def rodar(c, ate=None):
        while True:
            r = c.post(f"/api/fiscalizacoes/{fis}/roteiro/proximo")
            if r.status_code == 409:
                return
            j = r.json()
            if j.get("acao_humana") == "assinar":
                c.post(f"/api/fiscalizacoes/{fis}/assinar",
                       json={"pin": PIN_DEMO, "hash_confirmado": j["estado"]["laudo"]["hash_raiz"]})
            if ate and j["passo"]["n"] >= ate:
                return

    def ids(c):
        e = c.get(f"/api/fiscalizacoes/{fis}").json()
        return [x["id"] for k in ("evidencias", "falas", "checagens") for x in e[k]], e["etapa"]

    a, b = TestClient(app), TestClient(app)
    rodar(a, ate=3)
    rodar(b, ate=3)
    antes = _sem_volateis(a.get(f"/api/fiscalizacoes/{fis}").json())
    r = a.post(f"/api/fiscalizacoes/{fis}/auditoria")
    assert r.status_code == 200, r.text
    assert r.json()["origem"] == "regras"  # o LLM livre de teste não devolve JSON: cai nas regras
    assert _sem_volateis(a.get(f"/api/fiscalizacoes/{fis}").json()) == antes
    assert a.get("/api/saude").json()["demo_publica"]["uso"]["turnos"] == 1
    rodar(a)
    rodar(b)
    assert ids(a) == ids(b) and ids(a)[1] == "SELADO"
    linhas = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]
    aud = [x for x in linhas if x.get("laudo_evento") == "auditoria"]
    assert aud and aud[0]["origem"] == "regras" and aud[0]["sessao"]


def _sem_volateis(e):
    # o uso da cota e o relógio da sessão mudam; a fiscalização não
    return json.dumps({k: v for k, v in e.items() if k not in ("roteiro",)}, sort_keys=True, ensure_ascii=False)
