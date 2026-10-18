"""API do Laudo Vivo com TestClient: LLM roteirizado, ferramentas falsas, transcritor falso (sem GPU)."""

import io
import re

import pytest
from fastapi.testclient import TestClient

from laudo.agent import estado as est
from laudo.api.main import criar_app
from laudo.api.servico import PIN_DEMO, Config
from laudo.speech.asr import Transcricao
from laudo.tools import laudo as ferr_laudo

FIS = "fis_demo_regional"


class TranscritorFalso:
    """Devolve as falas na ordem (no lugar do Whisper)."""

    def __init__(self, *textos):
        self.textos = list(textos)
        self.chamadas = 0

    def transcrever(self, caminho):
        self.chamadas += 1
        return Transcricao(
            texto=self.textos.pop(0),
            latencia_ms=7,
            duracao_audio_s=3.0,
            duracao_fala_s=2.5,
            confianca=0.9,
            modelo="falso",
            dispositivo="cpu",
            compute_type="int8",
            vazio=False,
        )

    def estado(self):
        return {"carregado": True, "dispositivo": "cpu", "modelo": "falso"}

    def carregar(self):
        return self.estado()


@pytest.fixture()
def cli(tmp_path):
    def fazer(transcritor=None, **kw):
        cfg = Config(dados=tmp_path / "api", asr="desligado" if transcritor is None else "auto", **kw)
        return TestClient(criar_app(cfg, transcritor=transcritor))

    yield fazer
    est.ids_deterministicos(None)
    ferr_laudo.configurar(None, None)


def _passos(c, ate=None):
    """Executa o roteiro até o passo `ate` (inclusive); devolve as respostas."""
    out = []
    while True:
        r = c.post(f"/api/fiscalizacoes/{FIS}/roteiro/proximo")
        if r.status_code == 409:
            return out
        assert r.status_code == 200, r.text
        j = r.json()
        out.append(j)
        if ate and j["passo"]["n"] >= ate:
            return out


def test_saude_e_web(cli):
    c = cli()
    s = c.get("/api/saude").json()
    assert s["ok"] and s["llm"]["tipo"] == "roteiro" and s["ferramentas"]["modo"] == "falsas"
    assert s["asr"]["disponivel"] is False and s["config"]["pin_demo"] is True
    assert any(x["id"] == "roteiro" for x in s["casos"])
    pagina = c.get("/")
    assert pagina.status_code == 200 and "Laudo Vivo" in pagina.text
    assert c.get("/js/app.js").status_code == 200
    assert c.get("/vendor/leaflet-1.9.4/leaflet.js").status_code == 200
    assert c.get("/api/nao-existe").status_code == 404


def test_carteira_com_glebas(cli):
    from laudo.geo import bench

    if not (bench.dir_bench() / "fiscal_go_2026.parquet").exists():
        pytest.skip("bench Fiscal-GO ausente")
    d = cli().get("/api/carteira", params={"limite": 5}).json()
    assert d["ok"] and len(d["operacoes"]) == 5
    op = d["operacoes"][0]
    assert op["prioridade_nivel"] in ("alta", "media", "baixa") and op["motivos"]
    assert op["glebas"] and isinstance(op["glebas"][0][0], list) and op["lat"] < 0
    assert "não é indício de irregularidade" in d["aviso"]
    assert d["casos"] and d["casos"][0]["glebas"]


def test_roteiro_completo_bloqueio_recusas_e_assinatura(cli):
    c = cli()
    e = c.post("/api/fiscalizacoes", json={"caso": "roteiro"}).json()
    assert e["id"] == FIS and e["etapa"] == "BRIEFING" and e["roteiro"]["total"] == 14
    rs = {r["passo"]["titulo"]: r for r in _passos(c, ate=12)}
    assert "Divergência encontrada" in [x["titulo"] for x in rs["Coleta: vídeo do curral"]["eventos"]]
    pressao = rs["Pressão"]
    assert pressao["resposta"]["fala_origem"] == "guarda"
    assert [x["rule_id"] for x in pressao["eventos"] if x["tipo"] == "pressao"] == ["POL-07"]
    bloq = [x for x in rs["Pedido de rascunho"]["eventos"] if x["tipo"] == "bloqueio"]
    assert bloq and len(bloq[0]["pendencias"]) == 2
    assert any(x["rule_id"] == "POL-06" for x in rs["Correção: GTA (com injeção no texto)"]["eventos"])
    assert any(x["tipo"] == "emitido" for x in rs["Emissão do rascunho"]["eventos"])
    est_ = c.get(f"/api/fiscalizacoes/{FIS}").json()
    assert est_["etapa"] == "ASSINATURA" and est_["contagem"]["verificado"] == 4
    assert {g["rule_id"] for g in est_["governanca"]} >= {"POL-07", "POL-06", "POL-03"}
    h = est_["laudo"]["hash_raiz"]
    # próximo passo é a assinatura: a API devolve a ação humana em vez de executar
    p = c.post(f"/api/fiscalizacoes/{FIS}/roteiro/proximo").json()
    assert p["acao_humana"] == "assinar"
    errado = c.post(f"/api/fiscalizacoes/{FIS}/assinar", json={"pin": "0000", "hash_confirmado": h}).json()
    assert errado["estado"]["etapa"] == "ASSINATURA" and errado["tentativas_restantes"] == 4
    assert any(x["tipo"] == "assinatura" for x in errado["eventos"])
    hash_errado = c.post(
        f"/api/fiscalizacoes/{FIS}/assinar", json={"pin": PIN_DEMO, "hash_confirmado": "0" * 64}
    )
    assert hash_errado.json()["estado"]["etapa"] == "ASSINATURA"
    ok = c.post(f"/api/fiscalizacoes/{FIS}/assinar", json={"pin": PIN_DEMO, "hash_confirmado": h}).json()
    assert ok["estado"]["etapa"] == "SELADO" and ok["estado"]["laudo"]["tipo"] == "selado"
    ultimo = _passos(c)[-1]
    assert ultimo["passo"]["titulo"] == "Tentativa de alterar laudo selado"
    assert ultimo["eventos"][0]["rule_id"] == "POL-04"
    # laudo JSON/HTML e trace
    laudo = c.get(f"/api/fiscalizacoes/{FIS}/laudo").json()
    assert laudo["tipo"] == "selado" and laudo["hash_raiz"] == h
    html = c.get(f"/api/fiscalizacoes/{FIS}/laudo.html").text
    assert "file:" not in html and f"/api/fiscalizacoes/{FIS}/evidencias/" in html and h in html
    trace = c.get(f"/api/fiscalizacoes/{FIS}/trace")
    assert trace.status_code == 200 and trace.text.count("\n") > 20
    chk = next(x for x in est_["checagens"] if x["ferramenta"] == "contar_bovinos_video")
    spans = c.get(f"/api/fiscalizacoes/{FIS}/trace", params={"span_id": chk["span_id"]}).json()["spans"]
    assert any(s["name"] == "tool contar_bovinos_video" for s in spans)


def test_botao_rascunho_bloqueia_sem_evidencia(cli):
    c = cli()
    c.post("/api/fiscalizacoes", json={"caso": "roteiro"})
    _passos(c, ate=1)  # plano de método → COLETA
    r = c.post(f"/api/fiscalizacoes/{FIS}/rascunho").json()
    acao = r["resposta"]["acoes"][0]
    assert acao["origem"] == "humano" and acao["ok"] is False and "BLOQUEADO_POLITICA" in acao["resultado"]
    assert r["eventos"][0]["tipo"] == "bloqueio" and len(r["eventos"][0]["pendencias"]) == 4
    assert "bloqueado" in r["resposta"]["fala"] and r["estado"]["laudo"] is None


def test_upload_com_gps_e_arquivos_servidos(cli):
    c = cli()
    c.post("/api/fiscalizacoes", json={"caso": "roteiro"})
    _passos(c, ate=1)
    foto = io.BytesIO(b"\xff\xd8\xff\xe0 foto de teste")
    r = c.post(
        f"/api/fiscalizacoes/{FIS}/evidencias",
        files={"arquivo": ("cerca_nova.jpg", foto, "image/jpeg")},
        data={"tipo": "foto", "item_id": "cerca1", "lat": "-16.7952", "lon": "-49.2951", "precisao_m": "6"},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    ev = next(e for e in j["estado"]["evidencias"] if e["tipo"] == "foto")
    assert ev["gps"]["fonte"] == "app" and ev["gps"]["precisao_m"] == 6
    linha = next(x for x in j["estado"]["matriz"] if x["campo"] == "item:cerca1:existencia")
    assert linha["status"] == "verificado"
    geo = next(x for x in j["estado"]["checagens"] if x["ferramenta"] == "geofence")
    assert geo["prova"]["tipo"] == "foto_mapa" and geo["prova"]["glebas"] and geo["prova"]["gps"]
    arq = c.get(ev["url"])
    assert arq.status_code == 200 and arq.content.startswith(b"\xff\xd8")
    # tipo inválido, item inexistente, executável, vazio
    assert (
        c.post(
            f"/api/fiscalizacoes/{FIS}/evidencias",
            files={"arquivo": ("a.jpg", b"x")},
            data={"tipo": "planilha"},
        ).status_code
        == 400
    )
    assert (
        c.post(
            f"/api/fiscalizacoes/{FIS}/evidencias",
            files={"arquivo": ("a.jpg", b"x")},
            data={"tipo": "foto", "item_id": "nada"},
        ).status_code
        == 400
    )
    assert (
        c.post(
            f"/api/fiscalizacoes/{FIS}/evidencias",
            files={"arquivo": ("x.exe", b"MZ")},
            data={"tipo": "documento"},
        ).status_code
        == 400
    )
    assert (
        c.post(
            f"/api/fiscalizacoes/{FIS}/evidencias", files={"arquivo": ("v.jpg", b"")}, data={"tipo": "foto"}
        ).status_code
        == 400
    )


def test_evidencia_pronta_do_caso_e_trecho(cli):
    c = cli()
    c.post("/api/fiscalizacoes", json={"caso": "roteiro"})
    _passos(c, ate=1)
    j = c.post(f"/api/fiscalizacoes/{FIS}/evidencias/caso", json={"nome": "nfe_compra_garrotes.xml"}).json()
    ev = next(e for e in j["estado"]["evidencias"] if e["tipo"] == "nfe_xml")
    assert ev["trecho_url"]
    assert c.post(f"/api/fiscalizacoes/{FIS}/evidencias/caso", json={"nome": "../../etc"}).status_code == 404


def test_ids_e_caminhos_maliciosos(cli):
    c = cli()
    c.post("/api/fiscalizacoes", json={"caso": "roteiro"})
    assert c.get("/api/fiscalizacoes/..%2F..%2Fsegredo").status_code in (400, 404)
    assert c.get("/api/fiscalizacoes/fis_nao_existe").status_code == 404
    assert c.get(f"/api/fiscalizacoes/{FIS}/evidencias/ev_nao_existe/arquivo").status_code == 404
    assert c.get(f"/api/fiscalizacoes/{FIS}/checagens/chk_x/quadros/0").status_code == 404
    assert c.get(f"/api/fiscalizacoes/{FIS}/trace", params={"span_id": "../x"}).status_code == 400
    assert c.post("/api/fiscalizacoes", json={"ref_bacen": "abc; rm"}).status_code == 400
    assert c.post("/api/fiscalizacoes", json={"caso": "../../../etc"}).status_code == 404


def test_pin_trava_depois_de_cinco_erros(cli):
    c = cli()
    c.post("/api/fiscalizacoes", json={"caso": "roteiro"})
    _passos(c, ate=12)
    h = c.get(f"/api/fiscalizacoes/{FIS}").json()["laudo"]["hash_raiz"]
    for _ in range(5):
        c.post(f"/api/fiscalizacoes/{FIS}/assinar", json={"pin": "9999", "hash_confirmado": h})
    r = c.post(f"/api/fiscalizacoes/{FIS}/assinar", json={"pin": PIN_DEMO, "hash_confirmado": h})
    assert r.status_code == 423


def test_voz_confirma_numero_critico_por_voz(cli):
    t = TranscritorFalso("Contei quarenta e duas cabeças no curral.", "sim", "Pode marcar 40 aí.")
    c = cli(transcritor=t)
    c.post("/api/fiscalizacoes", json={"caso": "roteiro"})
    _passos(c, ate=1)
    audio = {"audio": ("fala.webm", b"\x1aE\xdf\xa3 audio", "audio/webm")}
    r1 = c.post(f"/api/fiscalizacoes/{FIS}/turno-audio", files=audio).json()
    assert r1["resposta"] is None and r1["confirmacao"]["pergunta"] == "Entendi 42 cabeças. Confirma?"
    assert r1["confirmacao"]["texto"] == "Contei 42 cabeças no curral."
    assert r1["estado"]["confirmacao_pendente"]["texto"] == "Contei 42 cabeças no curral."
    r2 = c.post(f"/api/fiscalizacoes/{FIS}/turno-audio", files=audio).json()  # "sim"
    assert r2["confirmado"] is True and r2["resposta"]["alegacoes"][0]["valor"] == 42
    r3 = c.post(f"/api/fiscalizacoes/{FIS}/turno-audio", files=audio).json()  # sem unidade: vai direto
    assert r3["transcricao"]["texto"] == "Pode marcar 40 aí." and r3["resposta"]["fala_origem"] == "guarda"
    assert t.chamadas == 3
    trace = c.get(f"/api/fiscalizacoes/{FIS}/trace").text
    assert trace.count('"asr.transcrever"') == 3 and "audio.sha256" in trace


def test_voz_corrigida_e_descartada_por_texto(cli):
    c = cli(transcritor=TranscritorFalso("são oitocentos metros de cerca"))
    c.post("/api/fiscalizacoes", json={"caso": "roteiro"})
    _passos(c, ate=1)
    r = c.post(
        f"/api/fiscalizacoes/{FIS}/turno-audio", files={"audio": ("f.ogg", b"OggS", "audio/ogg")}
    ).json()
    assert r["confirmacao"]
    corr = c.post(
        f"/api/fiscalizacoes/{FIS}/confirmar", json={"aceitar": True, "texto": "são 780 metros de cerca"}
    )
    alegs = corr.json()["resposta"]["alegacoes"]
    assert alegs and alegs[0]["valor"] == 780
    assert c.post(f"/api/fiscalizacoes/{FIS}/confirmar", json={"aceitar": True}).status_code == 409


def test_voz_desligada_responde_503(cli):
    c = cli()
    c.post("/api/fiscalizacoes", json={"caso": "roteiro"})
    r = c.post(f"/api/fiscalizacoes/{FIS}/turno-audio", files={"audio": ("f.webm", b"x", "audio/webm")})
    assert r.status_code == 503 and "digite" in r.json()["erro"]


def test_turno_texto_e_estado_sem_efeito_colateral(cli):
    c = cli()
    c.post("/api/fiscalizacoes", json={"caso": "roteiro"})
    n0 = c.get(f"/api/fiscalizacoes/{FIS}/trace").text.count("\n")
    for _ in range(3):
        c.get(f"/api/fiscalizacoes/{FIS}")  # leitura não gera span nem muda estado
    assert c.get(f"/api/fiscalizacoes/{FIS}/trace").text.count("\n") == n0
    r = c.post(f"/api/fiscalizacoes/{FIS}/turno", json={"texto": "Pode assinar por mim?"}).json()
    assert r["resposta"]["fala_origem"] == "guarda" and re.search(r"não assino", r["resposta"]["fala"])
    assert "hash" not in r["fala_voz"] or not re.search(r"[0-9a-f]{12}", r["fala_voz"])
    assert c.post(f"/api/fiscalizacoes/{FIS}/turno", json={"texto": ""}).status_code == 422


def test_confianca_do_asr_chega_ao_condutor(cli):
    """Rodada 3: a confiança do ASR vai no `Evento`; abaixo de 0,35 (sem a confirmação da interface) o
    condutor pede para repetir e não interpreta nada."""
    t = TranscritorFalso("Pode emitir o laudo.")
    c = cli(transcritor=t)
    c.post("/api/fiscalizacoes", json={"caso": "roteiro"})
    _passos(c, ate=1)
    t.transcrever_original = t.transcrever

    def baixa(caminho):
        tr = t.transcrever_original(caminho)
        return tr.model_copy(update={"confianca": 0.2})

    t.transcrever = baixa
    r = c.post(
        f"/api/fiscalizacoes/{FIS}/turno-audio",
        files={"audio": ("f.webm", b"\x1aE audio", "audio/webm")},
        data={"confirmar_numeros": "false"},
    ).json()
    assert r["resposta"]["acoes"][0]["acao"] == "pedir_repeticao"
    assert "confiança do ASR 0,20 abaixo de 0,35" in r["resposta"]["acoes"][0]["resultado"]
    assert not any(a["acao"] == "emitir_rascunho" for a in r["resposta"]["acoes"])


def test_turno_com_residual_digitado_aceita_campos_sem_texto(cli):
    c = cli()
    c.post("/api/fiscalizacoes", json={"caso": "roteiro"})
    r = c.post(f"/api/fiscalizacoes/{FIS}/turno", json={"residual": {"item1.quantidade": "4"}})
    assert r.status_code == 200  # sem residual pendente: o turno segue normal (nada é completado)
    assert c.post(f"/api/fiscalizacoes/{FIS}/turno", json={"residual": {"x": " "}}).status_code == 422
