"""Demo pública (`LAUDO_DEMO_PUBLICA=1`): uma cópia da fiscalização por visitante, sem interferência entre elas, com
os limites de custo e de abuso, e nada mudando com a variável desligada. Rápidos: LLM roteirizado e ferramentas
falsas. Lento (LAUDO_LENTO=1): ferramentas reais e a gravação do DEMO-0001 em 3 cópias em paralelo."""

from __future__ import annotations

import concurrent.futures as cf
import json
import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from laudo import isolamento
from laudo.agent import estado as est
from laudo.api import casos as casos_mod
from laudo.api import eventos, publica
from laudo.api.main import criar_app
from laudo.api.servico import PIN_DEMO, Config, ErroServico
from laudo.audit import otel
from laudo.contracts import Envelope, Ferramenta, sha256_arquivo
from laudo.llm.provider import ProvedorRoteirizado, RespostaLLM
from laudo.tools import laudo as ferr_laudo

FIS = "fis_demo_0001"
SEM_DEMO = casos_mod.localizar_caso("DEMO-0001") is None
pytestmark = pytest.mark.skipif(SEM_DEMO, reason="DEMO-0001 ausente")


@pytest.fixture(autouse=True)
def _limpar():
    yield
    est.ids_deterministicos(None)
    ferr_laudo.configurar(None, None)


@pytest.fixture()
def publico(tmp_path, monkeypatch):
    """App da demo pública com LLM roteirizado e ferramentas falsas (sem GPU); devolve uma fábrica de visitantes."""
    monkeypatch.setenv("LAUDO_DEMO_PUBLICA", "1")
    monkeypatch.setenv("LAUDO_DEMO_DIR", str(tmp_path / "copias"))

    def fazer(**env):
        for k, v in env.items():
            monkeypatch.setenv(k, str(v))
        app = criar_app(Config(dados=tmp_path / "api", caso="DEMO-0001", asr="desligado"))
        return app, lambda: TestClient(app)

    return fazer


def _rodar(c: TestClient, ate: int | None = None) -> list[dict]:
    """Executa passos do roteiro (todos ou até o passo `ate`, inclusive), assinando com o PIN de demonstração."""
    out = []
    while True:
        r = c.post(f"/api/fiscalizacoes/{FIS}/roteiro/proximo")
        if r.status_code == 409:
            return out
        assert r.status_code == 200, r.text
        j = r.json()
        out.append(j)
        if j.get("acao_humana") == "assinar":
            h = j["estado"]["laudo"]["hash_raiz"]
            a = c.post(f"/api/fiscalizacoes/{FIS}/assinar", json={"pin": PIN_DEMO, "hash_confirmado": h})
            assert a.status_code == 200, a.text
        if ate and j["passo"]["n"] >= ate:
            return out


def _ids(c: TestClient) -> list[str]:
    e = c.get(f"/api/fiscalizacoes/{FIS}").json()
    return [x["id"] for k in ("evidencias", "falas", "checagens") for x in e[k]]


# ---------------------------------------------------------------------------------------------------- desligada


def test_desligada_nada_muda(tmp_path, monkeypatch):
    monkeypatch.delenv("LAUDO_DEMO_PUBLICA", raising=False)
    app = criar_app(Config(dados=tmp_path / "api", caso="DEMO-0001", asr="desligado"))
    c = TestClient(app)
    assert not hasattr(app.state, "gerenciador")
    assert c.get("/api/openapi.json").status_code == 200
    r = c.get("/api/saude")
    assert "demo_publica" not in r.json() and "demo_publica" not in r.json()["config"]
    assert publica.COOKIE not in r.cookies and "set-cookie" not in r.headers
    assert eventos.evento("turno", canal="texto") is None


def test_eventos_uma_linha_json_so_na_demo_publica(monkeypatch, capsys):
    monkeypatch.delenv("LAUDO_DEMO_PUBLICA", raising=False)
    assert eventos.evento("upload", tipo="foto") is None
    assert capsys.readouterr().out == ""
    monkeypatch.setenv("LAUDO_DEMO_PUBLICA", "1")
    with isolamento.ativo(isolamento.Contexto(traces=Path("."), sessao="abc123")):
        eventos.evento("upload", tipo="foto", mb=1.5)
    linha = json.loads(capsys.readouterr().out.strip())
    assert linha["severity"] == "INFO" and linha["laudo_evento"] == "upload" and linha["sessao"] == "abc123"
    assert linha["tipo"] == "foto" and linha["mb"] == 1.5
    assert linha["detalhe"] == "foto"  # rótulo das métricas de log do painel (infra/nuvem/observabilidade.tf)
    eventos.evento("recusa_limite", limite="falas", tipo="x")
    assert json.loads(capsys.readouterr().out)["detalhe"] == "falas"  # o limite vem antes do tipo


# ---------------------------------------------------------------------------------------------------- isolamento


def test_ids_traces_e_laudo_por_contexto_tambem_na_thread_da_ferramenta(tmp_path):
    a = isolamento.Contexto(traces=tmp_path / "a")
    b = isolamento.Contexto(traces=tmp_path / "b")
    est.ids_deterministicos("global")
    with isolamento.ativo(a):
        est.ids_deterministicos("semente")
        ia = [est.novo_id("ev"), est.novo_id("ev")]
        assert otel.diretorio_traces() == tmp_path / "a"
    with isolamento.ativo(b):
        est.ids_deterministicos("semente")
        ib = est.novo_id("ev")
        with cf.ThreadPoolExecutor(1) as ex:  # como o executor de ferramentas
            na_thread = ex.submit(isolamento.no_contexto(lambda: (est.novo_id("ev"), otel.diretorio_traces()))).result()
    assert ia[0] == ib and na_thread == (ia[1], tmp_path / "b")
    assert est._IDS == {"semente": "global", "n": 0}  # o contador do processo não andou dentro das cópias
    with isolamento.ativo(a):
        ferr_laudo.configurar("repo-a", "pol-a")  # type: ignore[arg-type]
        assert ferr_laudo._repo() == "repo-a"
    assert ferr_laudo._CTX["repo"] != "repo-a"
    assert isolamento.no_contexto(len) is len  # sem contexto, a própria função (uso normal intacto)


def test_cookie_abre_o_caso_direto_e_sem_documentacao_nem_aquecimento(publico):
    _, visitante = publico()
    c = visitante()
    pagina = c.get("/")
    assert pagina.status_code == 200
    ck = pagina.headers["set-cookie"]
    assert f"{publica.COOKIE}=" in ck and "HttpOnly" in ck and "samesite=lax" in ck.lower()
    s = c.get("/api/saude").json()
    assert s["config"]["demo_publica"] is True and s["llm"]["tipo"] == "roteiro"
    assert s["demo_publica"]["fis_id"] == FIS and [x["id"] for x in s["casos"]] == ["DEMO-0001"]
    e = c.get(f"/api/fiscalizacoes/{FIS}").json()  # cópia criada já com o caso aberto, no passo 1
    assert e["etapa"] == "BRIEFING" and e["roteiro"]["proximo"] == 1 and e["roteiro"]["arquivos"]
    assert e["demonstracao"]
    for rota in ("/api/openapi.json", "/api/docs"):
        assert c.get(rota).status_code == 404
    for rota in ("/api/llm/aquecer", "/api/voz/aquecer"):
        assert c.post(rota).status_code == 404
    assert c.post("/api/fiscalizacoes", json={"ref_bacen": "123456789"}).status_code == 403
    assert c.post("/api/fiscalizacoes", json={"caso": "roteiro"}).status_code == 403
    assert "access-control-allow-origin" not in c.get("/api/saude", headers={"Origin": "https://x.example"}).headers


def test_tres_visitantes_intercalados_nao_se_atrapalham(publico, tmp_path):
    app, visitante = publico()
    a, b, c = visitante(), visitante(), visitante()
    for v in (a, b, c):
        v.get("/")
    total = len(a.get(f"/api/fiscalizacoes/{FIS}").json()["roteiro"]["passos"])
    feitos = {id(v): 0 for v in (a, b, c)}
    # a anda 1 passo, b 2, c 3, em rodízio, até cada um terminar
    while any(feitos[id(v)] < total for v in (a, b, c)):
        for k, v in enumerate((a, b, c), 1):
            for _ in range(k):
                if feitos[id(v)] < total:
                    _rodar(v, ate=feitos[id(v)] + 1)
                    feitos[id(v)] += 1
        pa, pb = (a.get(f"/api/fiscalizacoes/{FIS}").json()["roteiro"]["proximo"],
                  b.get(f"/api/fiscalizacoes/{FIS}").json()["roteiro"]["proximo"])
        assert pa == min(feitos[id(a)], total) + 1 and pb == min(feitos[id(b)], total) + 1
    finais = [v.get(f"/api/fiscalizacoes/{FIS}").json() for v in (a, b, c)]
    assert all(f["etapa"] == "SELADO" for f in finais)
    assert _ids(a) == _ids(b) == _ids(c)  # cada cópia com os ids da gravação, apesar do rodízio
    ger = app.state.gerenciador
    pastas = {s.dados for s in ger.sessoes.values()}
    assert len(pastas) == 3 and all((p / "traces" / f"{FIS}.jsonl").is_file() for p in pastas)
    assert all((p / "laudos" / FIS / "laudo_selado.json").is_file() for p in pastas)
    assert not (tmp_path / "api" / "traces" / f"{FIS}.jsonl").exists()  # nada na pasta do processo


def test_mensagem_livre_nao_desalinha_os_ids_do_roteiro(publico):
    _, visitante = publico()
    a, b = visitante(), visitante()
    _rodar(a, ate=2)
    _rodar(b, ate=2)
    r = a.post(f"/api/fiscalizacoes/{FIS}/turno", json={"texto": "O que é o NDVI e por que ele importa aqui?"})
    assert r.status_code == 200 and r.json()["resposta"]["fala"]
    conv = a.get(f"/api/fiscalizacoes/{FIS}").json()["conversa"]
    assert conv[-1].get("livre") is True  # marcado na conversa, que a tela mostra inteira
    _rodar(a)
    _rodar(b)
    ia, ib = _ids(a), _ids(b)
    assert [i for i in ia if i in set(ib)] == ib and set(ia) - set(ib)  # os do roteiro iguais; o livre à parte
    assert a.get("/api/saude").json()["demo_publica"]["uso"]["turnos"] == 1


def test_texto_igual_ao_do_passo_vira_o_passo(publico):
    _, visitante = publico()
    c = visitante()
    p1 = c.get(f"/api/fiscalizacoes/{FIS}").json()["roteiro"]["passos"][0]
    r = c.post(f"/api/fiscalizacoes/{FIS}/turno", json={"texto": p1["fala"].upper()})
    assert r.status_code == 200 and r.json()["passo"]["n"] == 1
    s = c.get("/api/saude").json()
    assert s["demo_publica"]["uso"]["turnos"] == 0
    assert c.get(f"/api/fiscalizacoes/{FIS}").json()["roteiro"]["proximo"] == 2
    assert c.post(f"/api/fiscalizacoes/{FIS}/roteiro/proximo?n=5").status_code == 400  # o roteiro segue em ordem


# ---------------------------------------------------------------------------------------------------- limites


def test_limite_de_mensagens_livres_429_e_evento(publico, capsys):
    _, visitante = publico(LAUDO_DEMO_MAX_TURNOS=2)
    c = visitante()
    for i in range(2):
        assert c.post(f"/api/fiscalizacoes/{FIS}/turno", json={"texto": f"pergunta livre {i}"}).status_code == 200
    r = c.post(f"/api/fiscalizacoes/{FIS}/turno", json={"texto": "mais uma"})
    assert r.status_code == 429 and "Limite da demonstração" in r.json()["erro"]
    assert c.post(f"/api/fiscalizacoes/{FIS}/roteiro/proximo").status_code == 200  # o passo gravado não conta
    linhas = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]
    rec = [x for x in linhas if x["laudo_evento"] == "recusa_limite"]
    assert rec and rec[0]["limite"] == "turnos" and rec[0]["sessao"]
    assert {x["laudo_evento"] for x in linhas} >= {"sessao_nova", "turno", "recusa_limite"}
    assert {x.get("canal") for x in linhas if x["laudo_evento"] == "turno"} == {"texto", "passo"}


def test_limite_de_copias_vivas(publico):
    _, visitante = publico(LAUDO_DEMO_MAX_SESSOES=2)
    a, b, c = visitante(), visitante(), visitante()
    assert a.get(f"/api/fiscalizacoes/{FIS}").status_code == 200
    assert b.get(f"/api/fiscalizacoes/{FIS}").status_code == 200
    r = c.get(f"/api/fiscalizacoes/{FIS}")
    assert r.status_code == 429 and "Limite da demonstração" in r.json()["erro"]
    assert c.get("/api/saude").status_code == 200  # a saúde não cria cópia


def test_copia_parada_some_depois_do_prazo(tmp_path, monkeypatch):
    monkeypatch.setenv("LAUDO_DEMO_PUBLICA", "1")
    agora = [1000.0]
    ger = publica.GerenciadorSessoes(Config(dados=tmp_path / "api", caso="DEMO-0001", asr="desligado"),
                                     publica.Limites(ttl_s=60), raiz=tmp_path / "copias", relogio=lambda: agora[0])
    tok = publica.novo_token()
    f = ger.fachada(tok)
    f.passo_roteiro(FIS)
    pasta = f.sessao.dados
    assert pasta.is_dir() and ger.vivas() == 1
    agora[0] += 30
    assert ger.limpar() == 0
    agora[0] += 61
    assert ger.limpar() == 1 and not pasta.exists() and ger.vivas() == 0
    nova = ger.fachada(tok)  # o mesmo visitante volta: cópia nova, do passo 1
    assert nova.estado(FIS)["roteiro"]["proximo"] == 1


def test_upload_so_foto_video_curto_e_xml_com_teto(publico, tmp_path):
    _, visitante = publico(LAUDO_DEMO_FOTO_MB=0.01, LAUDO_DEMO_MAX_UPLOADS=3)
    c = visitante()
    url = f"/api/fiscalizacoes/{FIS}/evidencias"

    def enviar(tipo, nome, conteudo, **form):
        return c.post(url, data={"tipo": tipo, **form}, files={"arquivo": (nome, conteudo)})

    assert enviar("gta", "gta.json", b"{}").status_code == 415  # GTA e foto da nota só dos arquivos do caso
    assert enviar("documento", "danfe.jpg", b"\xff\xd8\xff" + b"0" * 100).status_code == 415
    assert enviar("foto", "foto.jpg", b"isto nao e imagem").status_code == 415  # pelo conteúdo, não pelo nome
    assert enviar("foto", "grande.jpg", b"\xff\xd8\xff" + b"0" * 20000).status_code == 413
    xml = (Path(casos_mod.localizar_caso("DEMO-0001")) / "nfe_1.xml").read_bytes()
    r = enviar("nfe_xml", "nota.xml", xml, lat="-16.7", lon="-49.2")
    assert r.status_code == 200, r.text
    ev = [e for e in r.json()["estado"]["evidencias"] if e["tipo"] == "nfe_xml"][-1]
    assert not ev.get("gps")  # a localização do aparelho não entra
    r = enviar("nfe_xml", "nota2.xml", xml)
    assert r.status_code == 429 and "arquivos" in r.json()["erro"]  # 3º envio contado (inclui os recusados)
    assert not any(p.name == "_entrada" and any(p.iterdir()) for p in (tmp_path / "copias").rglob("_entrada"))


def _video(caminho: Path, segundos: int) -> Path | None:
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    w = cv2.VideoWriter(str(caminho), cv2.VideoWriter_fourcc(*"mp4v"), 2, (64, 48))
    if not w.isOpened():
        return None
    for i in range(segundos * 2):
        w.write(np.full((48, 64, 3), (i * 7) % 255, dtype=np.uint8))
    w.release()
    return caminho if caminho.is_file() and caminho.stat().st_size else None


def test_video_do_aparelho_com_teto_de_duracao(publico, tmp_path):
    longo, curto = _video(tmp_path / "longo.mp4", 25), _video(tmp_path / "curto.mp4", 4)
    if longo is None or curto is None:
        pytest.skip("OpenCV sem codificador mp4v")
    assert 24 <= (publica.duracao_video(longo) or 0) <= 26 and 3 <= (publica.duracao_video(curto) or 0) <= 5
    assert publica.duracao_video(tmp_path / "nao_existe.mp4") is None
    _, visitante = publico()
    c = visitante()
    url = f"/api/fiscalizacoes/{FIS}/evidencias"
    r = c.post(url, data={"tipo": "video"}, files={"arquivo": ("longo.mp4", longo.read_bytes())})
    assert r.status_code == 413 and "20 s" in r.json()["erro"]
    r = c.post(url, data={"tipo": "video"}, files={"arquivo": ("curto.mp4", curto.read_bytes())})
    assert r.status_code == 200, r.text
    assert any(e["tipo"] == "video" for e in r.json()["estado"]["evidencias"])


def test_post_de_outro_site_e_recusado(publico):
    _, visitante = publico()
    c = visitante()
    c.get("/")
    r = c.post(f"/api/fiscalizacoes/{FIS}/turno", json={"texto": "oi"}, headers={"Origin": "https://outro.example"})
    assert r.status_code == 403
    r = c.post(f"/api/fiscalizacoes/{FIS}/turno", json={"texto": "oi"}, headers={"Origin": "http://testserver"})
    assert r.status_code == 200


def test_formato_pelo_conteudo():
    assert publica.formato_arquivo(b"\xff\xd8\xff\xe0") == "jpeg"
    assert publica.formato_arquivo(b"\x89PNG\r\n\x1a\n") == "png"
    assert publica.formato_arquivo(b"RIFF\x00\x00\x00\x00WEBPVP8") == "webp"
    assert publica.formato_arquivo(b"\x00\x00\x00\x18ftypisom") == "mp4"
    assert publica.formato_arquivo(b"\x00\x00\x00\x18ftypheic") == "heic"
    assert publica.formato_arquivo(b"\x1a\x45\xdf\xa3") == "webm"
    assert publica.formato_arquivo(b"\xef\xbb\xbf  <?xml") == "xml"
    assert publica.formato_arquivo(b"MZ\x90\x00") is None


def test_contagem_do_video_pronto_sai_do_cache(tmp_path):
    from laudo.tools.bovinos import EntradaContarBovinos

    video = tmp_path / "v.mp4"
    video.write_bytes(b"video de teste")
    outro = tmp_path / "outro.mp4"
    outro.write_bytes(b"outro video")
    chamadas = []

    def contar(args):
        chamadas.append(args.caminho_video)
        q = Path(args.dir_evidencias) / "linha_x_000007.jpg"
        q.parent.mkdir(parents=True, exist_ok=True)
        q.write_bytes(b"jpeg")
        return Envelope.sucesso("contar_bovinos_video", {"status": "ok", "contagem": 15, "video": {"caminho": "x"},
                                                         "quadros_chave": [{"caminho": q.as_posix(), "quadro": 7}]})

    ferr = Ferramenta(nome="contar_bovinos_video", descricao="d", entrada=EntradaContarBovinos, funcao=contar)
    com = publica.contagem_com_cache(ferr, lambda: {sha256_arquivo(str(video))}, pasta=tmp_path / "cache")
    assert com.descricao == ferr.descricao and com.entrada is ferr.entrada  # o pedido ao LLM não muda
    e1 = com.funcao(EntradaContarBovinos(caminho_video=str(video), dir_evidencias=str(tmp_path / "s1")))
    e2 = com.funcao(EntradaContarBovinos(caminho_video=str(video), dir_evidencias=str(tmp_path / "s2"), item_id="b"))
    assert len(chamadas) == 1 and e1.data["contagem"] == e2.data["contagem"] == 15
    q2 = Path(e2.data["quadros_chave"][0]["caminho"])
    assert q2.parent == tmp_path / "s2" and q2.is_file() and e2.data["item_id"] == "b"
    assert e2.data["video"]["caminho"] == video.as_posix()
    com.funcao(EntradaContarBovinos(caminho_video=str(outro), dir_evidencias=str(tmp_path / "s3")))
    com.funcao(EntradaContarBovinos(caminho_video=str(outro), dir_evidencias=str(tmp_path / "s4")))
    assert len(chamadas) == 3  # vídeo do visitante: conta sempre


def test_limites_do_ambiente():
    lim = publica.Limites.do_ambiente({"LAUDO_DEMO_MAX_SESSOES": "7", "LAUDO_DEMO_TTL_MIN": "30",
                                       "LAUDO_DEMO_VIDEO_MAX_S": "15", "LAUDO_DEMO_MAX_FALAS": "x"})
    assert lim.max_sessoes == 7 and lim.ttl_s == 1800 and lim.video_max_s == 15 and lim.max_falas == 25
    p = publica.Limites.do_ambiente({})
    assert (p.max_sessoes, p.max_turnos, p.max_falas, p.max_uploads) == (300, 40, 25, 12)


# ---------------------------------------------------------------------------------------------------- lento


class _AoVivo(ProvedorRoteirizado):
    """O LLM ao vivo de teste no lugar do Vertex: externo (o condutor mascara a PII antes de mandar)."""

    externo = True

    def __init__(self):
        super().__init__(lambda *_: RespostaLLM(conteudo="Resposta do modelo ao vivo."), modelo="ao-vivo-teste")


@pytest.mark.lento
def test_tres_copias_reais_em_paralelo_saem_da_gravacao(tmp_path, monkeypatch):
    """Ferramentas reais e a gravação do DEMO-0001, 3 cópias em threads ao mesmo tempo: cada uma termina SELADA sem
    nenhuma requisição fora da gravação; uma mensagem livre em cada cópia vai ao LLM ao vivo, e o resto do roteiro
    continua saindo da gravação."""
    from laudo.vision.modelos import MODELOS

    if not os.environ.get("LAUDO_LENTO"):
        pytest.skip("teste lento: rode com LAUDO_LENTO=1")
    pasta = casos_mod.localizar_caso("DEMO-0001")
    if not (pasta / "replay_qwen35_4b.jsonl").exists() or not MODELOS["yolox_m"].caminho.is_file():
        pytest.skip("gravação do caso ou yolox_m ausentes")
    monkeypatch.setenv("LAUDO_DEMO_PUBLICA", "1")
    monkeypatch.setenv("LAUDO_VLM_CACHE", str(Path(__file__).parent / "dados_agente" / "vlm_cache_demo"))
    monkeypatch.setenv("LAUDO_VLM_SO_CACHE", "1")
    monkeypatch.setattr(publica, "DIR_CACHE_CONTAGEM", tmp_path / "cache_contagem")
    vivo = _AoVivo()
    cfg = Config(llm="publico", ferramentas="reais", caso="DEMO-0001", asr="desligado", provedor_livre=vivo)
    ger = publica.GerenciadorSessoes(cfg, publica.Limites(), raiz=tmp_path / "copias")

    def visitante(k: int) -> tuple[str, int, int, int]:
        f = ger.fachada(publica.novo_token())
        n = fora_livre = 0
        while True:
            try:
                out = f.passo_roteiro(FIS)
            except ErroServico as e:
                if e.status == 409:
                    break
                raise
            n += 1
            if n == 2 + k:  # cada cópia manda uma mensagem livre num ponto diferente do roteiro
                antes = f._fora()
                livre = f.turno(FIS, "Explique em uma frase o que a fiscalização confere aqui.")
                assert livre["resposta"]["fala"] == "Resposta do modelo ao vivo."
                fora_livre = f._fora() - antes
            if out.get("acao_humana") == "assinar":
                f.assinar(FIS, PIN_DEMO, f.estado(FIS)["laudo"]["hash_raiz"])
        return f.estado(FIS)["etapa"], f._fora(), fora_livre, n

    try:
        with cf.ThreadPoolExecutor(3) as ex:
            res = list(ex.map(visitante, range(3)))
        assert all(r[0] == "SELADO" and r[3] == 19 for r in res), res
        # fora da gravação, só os pedidos da mensagem livre: os 19 passos de cada cópia saíram da gravação
        assert all(r[1] == r[2] >= 1 for r in res), res
        assert len(vivo.chamadas) == sum(r[2] for r in res)  # e só esses foram ao LLM ao vivo
        assert list((tmp_path / "cache_contagem").glob("*/envelope.json"))  # o vídeo do caso contado uma vez
    finally:
        shutil.rmtree(tmp_path / "copias", ignore_errors=True)
