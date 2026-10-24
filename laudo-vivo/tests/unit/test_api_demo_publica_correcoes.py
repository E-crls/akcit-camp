"""Correções da demo pública (`LAUDO_DEMO_PUBLICA=1`) depois da verificação na nuvem de 24/10/2026: cópias e IP
(SEG-01), confirmação sem pendência (SEG-02/VA-01), passo do roteiro só da gravação depois de ação livre (P1/VA-02),
foto do visitante sem GPS (VA-05) e sem "erro interno" do VLM (VA-06), XML que não é NF-e (VA-07), voz com fila de
teto e frases simples (VA-03/VA-09), cota só depois da validação (SEG-03/VA-08), PIN fora da etapa (SEG-08),
saída pública sem caminho, sem eco e com CSP (SEG-04/05/07) e o 413 no painel (P3). Rápidos: LLM roteirizado e
ferramentas falsas; o lento (LAUDO_LENTO=1) roda o DEMO-0001 com ferramentas reais e a gravação."""

from __future__ import annotations

import io
import json
import os
import threading
import time
import wave
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from laudo.agent import estado as est
from laudo.api import casos as casos_mod
from laudo.api import publica
from laudo.api.main import CSP_PUBLICA, criar_app
from laudo.api.servico import PIN_DEMO, Config, ErroServico
from laudo.contracts import CodigoErro, Envelope, Ferramenta
from laudo.llm.provider import ProvedorRoteirizado, RespostaLLM
from laudo.speech import asr
from laudo.speech.asr import ErroASR, Transcricao
from laudo.tools import laudo as ferr_laudo
from laudo.vision.integridade import ler_exif

FIS = "fis_demo_0001"
SEM_DEMO = casos_mod.localizar_caso("DEMO-0001") is None
pytestmark = pytest.mark.skipif(SEM_DEMO, reason="DEMO-0001 ausente")
WAV = Path(__file__).parent / "dados_voz" / "fala_contagem_sapi.wav"


@pytest.fixture(autouse=True)
def _limpar():
    yield
    est.ids_deterministicos(None)
    ferr_laudo.configurar(None, None)


@pytest.fixture()
def publico(tmp_path, monkeypatch):
    """App da demo pública (LLM roteirizado, ferramentas falsas); devolve o app e uma fábrica de visitantes."""
    monkeypatch.setenv("LAUDO_DEMO_PUBLICA", "1")
    monkeypatch.setenv("LAUDO_DEMO_DIR", str(tmp_path / "copias"))

    def fazer(transcritor=None, **env):
        for k, v in env.items():
            monkeypatch.setenv(k, str(v))
        app = criar_app(Config(dados=tmp_path / "api", caso="DEMO-0001", asr="desligado"), transcritor=transcritor)
        return app, lambda: TestClient(app)

    return fazer


def _eventos(capsys) -> list[dict]:
    return [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]


def _rodar(c: TestClient) -> list[dict]:
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
            assert c.post(f"/api/fiscalizacoes/{FIS}/assinar", json={"pin": PIN_DEMO, "hash_confirmado": h}).status_code \
                == 200


def _ids(c: TestClient) -> list[str]:
    e = c.get(f"/api/fiscalizacoes/{FIS}").json()
    return [x["id"] for k in ("evidencias", "falas", "checagens") for x in e[k]]


def _uso(c: TestClient) -> dict:
    return c.get("/api/saude").json()["demo_publica"]["uso"]


class _AoVivo(ProvedorRoteirizado):
    """O LLM ao vivo de teste no lugar do Vertex (conta as chamadas)."""

    externo = True

    def __init__(self):
        super().__init__(lambda *_: RespostaLLM(conteudo="Resposta do modelo ao vivo."), modelo="ao-vivo-teste")


class _Transcritor:
    """No lugar do Whisper: devolve as falas na ordem, ou levanta o erro dado."""

    def __init__(self, *falas):
        self.falas = list(falas)

    def transcrever(self, caminho):
        f = self.falas.pop(0)
        if isinstance(f, Exception):
            raise f
        if isinstance(f, Transcricao):
            return f
        return Transcricao(texto=f, latencia_ms=7, duracao_audio_s=3.0, confianca=0.9, modelo="falso")

    def estado(self):
        return {"carregado": True, "modelo": "falso"}

    def carregar(self):
        return self.estado()


def _audio(c: TestClient, conteudo: bytes | None = None):
    corpo = WAV.read_bytes() if conteudo is None else conteudo
    return c.post(f"/api/fiscalizacoes/{FIS}/turno-audio", files={"audio": ("fala.wav", corpo, "audio/wav")})


# ---------------------------------------------------------------------------------------------- SEG-01: cópias e IP


def test_teto_cheio_expulsa_a_ociosa_e_so_recusa_com_todas_em_uso(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LAUDO_DEMO_PUBLICA", "1")
    agora = [1000.0]
    ger = publica.GerenciadorSessoes(Config(dados=tmp_path / "api", caso="DEMO-0001", asr="desligado"),
                                     publica.Limites(max_sessoes=2), raiz=tmp_path / "copias",
                                     relogio=lambda: agora[0])
    ta, tb, tc, td = (publica.novo_token() for _ in range(4))
    a, b = ger.fachada(ta), ger.fachada(tb)
    b.passo_roteiro(FIS)  # b usada; a intocada (só a criação)
    assert b.sessao.tocada and not a.sessao.tocada
    with pytest.raises(ErroServico) as e:  # a intocada é recente demais: todas em uso
        ger.fachada(tc)
    assert e.value.status == 429 and e.value.limite == "copias"
    agora[0] += 31
    pasta_a = a.sessao.dados
    c = ger.fachada(tc)  # a intocada parada há 31 s sai; a usada (b) fica
    assert not pasta_a.exists() and set(ger.sessoes) == {b.sessao.sid, c.sessao.sid}
    ev = _eventos(capsys)
    exp = [x for x in ev if x["laudo_evento"] == "copia_expulsa"]
    assert len(exp) == 1 and exp[0]["intocada"] is True and exp[0]["sessao"] == a.sessao.curta
    assert [x["limite"] for x in ev if x["laudo_evento"] == "recusa_limite"] == ["copias"]
    c.turno(FIS, "Uma pergunta livre.")  # c usada também
    with pytest.raises(ErroServico):  # as duas usadas há menos de 2 min: recusa
        ger.fachada(td)
    agora[0] += 121
    # b é a menos usada, mas tem pedido em andamento: sai c
    preso, solto = threading.Event(), threading.Event()

    def segurar():
        with b.servico.lock:
            preso.set()
            solto.wait(10)

    t = threading.Thread(target=segurar)
    t.start()
    preso.wait(5)
    try:
        d = ger.fachada(td)
    finally:
        solto.set()
        t.join()
    assert set(ger.sessoes) == {b.sessao.sid, d.sessao.sid}
    # o visitante da cópia expulsa volta no passo 1, com cópia nova (sai a intocada parada: d)
    agora[0] += 31
    volta = ger.fachada(ta)
    assert volta.estado(FIS)["roteiro"]["proximo"] == 1 and volta.sessao.sid == a.sessao.sid


def test_copias_novas_por_ip(publico, capsys):
    _, visitante = publico(LAUDO_DEMO_COPIAS_POR_IP=2)
    url = f"/api/fiscalizacoes/{FIS}"
    rede = {"X-Forwarded-For": "200.1.2.3, 10.0.0.1"}  # o primeiro IP é o do visitante
    a = visitante()
    assert a.get(url, headers=rede).status_code == 200
    assert visitante().get(url, headers=rede).status_code == 200
    r = visitante().get(url, headers=rede)
    assert r.status_code == 429 and "rede" in r.json()["erro"]
    assert a.get(url, headers=rede).status_code == 200  # quem já tem cópia segue
    assert visitante().get(url, headers={"X-Forwarded-For": "200.9.9.9"}).status_code == 200  # outra rede
    rec = [x for x in _eventos(capsys) if x["laudo_evento"] == "recusa_limite"]
    assert [x["limite"] for x in rec] == ["ip"]


def test_janela_de_criacoes_por_ip():
    j = publica._CriacoesPorIP(2, 600)
    for t in (0, 1):
        assert j.permitir("1.1.1.1", t)
        j.registrar("1.1.1.1", t)
    assert not j.permitir("1.1.1.1", 2) and j.permitir("2.2.2.2", 2)
    assert not j.permitir("1.1.1.1", 599) and j.permitir("1.1.1.1", 600.5)  # a 1ª saiu da janela
    assert publica._CriacoesPorIP(0, 600).permitir("1.1.1.1", 0)  # 0: sem limite


# ------------------------------------------------------------------------------- SEG-02/VA-01: confirmar


def test_confirmar_sem_pendencia_409_e_correcao_conta_como_mensagem(publico):
    t = _Transcritor("Contei quarenta e duas cabeças no curral.", "Contei quarenta e duas cabeças no curral.")
    _, visitante = publico(transcritor=t)
    c = visitante()
    n_conv = len(c.get(f"/api/fiscalizacoes/{FIS}").json()["conversa"])
    r = c.post(f"/api/fiscalizacoes/{FIS}/confirmar", json={"aceitar": True, "texto": "Qual é a área da gleba?"})
    assert r.status_code == 409 and r.json()["erro"] == "nada a confirmar"
    assert len(c.get(f"/api/fiscalizacoes/{FIS}").json()["conversa"]) == n_conv  # nenhum turno rodou
    assert _uso(c)["turnos"] == 0
    pend = _audio(c).json()
    assert pend["confirmacao"]["texto"] == "Contei 42 cabeças no curral."
    r = c.post(f"/api/fiscalizacoes/{FIS}/confirmar", json={"aceitar": True, "texto": "Contei 40 cabeças no curral."})
    assert r.status_code == 200 and r.json()["resposta"]
    assert _uso(c) == {"turnos": 1, "falas": 1, "uploads": 0}  # corrigida: mensagem livre
    _audio(c)
    r = c.post(f"/api/fiscalizacoes/{FIS}/confirmar", json={"aceitar": True})
    assert r.status_code == 200 and _uso(c) == {"turnos": 1, "falas": 2, "uploads": 0}  # o que ouviu: só a fala
    assert c.post(f"/api/fiscalizacoes/{FIS}/confirmar", json={"aceitar": True, "texto": "x"}).status_code == 409


# ------------------------------------------------------------------------- P1/VA-02: o roteiro na gravação


def test_passo_do_roteiro_usa_so_a_gravacao_e_a_acao_livre_a_cadeia(tmp_path, monkeypatch):
    monkeypatch.setenv("LAUDO_DEMO_PUBLICA", "1")
    vivo = _AoVivo()
    cfg = Config(llm="publico", ferramentas="falsas", caso="DEMO-0001", asr="desligado", provedor_livre=vivo)
    ger = publica.GerenciadorSessoes(cfg, publica.Limites(), raiz=tmp_path / "copias")
    f = ger.fachada(publica.novo_token())
    srv = f.servico
    cadeia, rep = srv.provedor, srv.replay_publico
    assert cadeia.provedores == [rep, vivo] and not rep.sequencial_se_ausente
    with f.sessao.modo(livre=False):
        assert cadeia.provedores == [rep] and rep.sequencial_se_ausente  # passo: nunca o LLM ao vivo
        with f.sessao.modo(livre=True):
            assert cadeia.provedores == [rep, vivo] and not rep.sequencial_se_ausente
        assert cadeia.provedores == [rep]
    assert cadeia.provedores == [rep, vivo] and not rep.sequencial_se_ausente
    s = f.saude()
    assert "arquivo" not in s["llm"] and s["llm"]["substituicoes"] == 0  # sem caminho interno do contêiner


def test_arquivo_e_pergunta_do_visitante_nao_mudam_o_roteiro(publico):
    _, visitante = publico()
    a, b = visitante(), visitante()
    xml = (Path(casos_mod.localizar_caso("DEMO-0001")) / "nfe_1.xml").read_bytes()
    r = a.post(f"/api/fiscalizacoes/{FIS}/evidencias", data={"tipo": "nfe_xml"},
               files={"arquivo": ("minha_nota.xml", xml)})
    assert r.status_code == 200, r.text
    assert "roteiro da demonstração segue" in r.json()["aviso"]
    meu = [e for e in r.json()["estado"]["evidencias"] if e["tipo"] == "nfe_xml"]
    assert meu  # o visitante vê o arquivo dele até o próximo passo
    assert a.post(f"/api/fiscalizacoes/{FIS}/turno", json={"texto": "Contei 29 cabeças no curral."}).status_code == 200
    p1 = a.post(f"/api/fiscalizacoes/{FIS}/roteiro/proximo").json()
    assert not [e for e in p1["estado"]["evidencias"] if e["id"] == meu[0]["id"]]  # o roteiro volta ao estado dele
    _rodar(a)
    _rodar(b)
    fa, fb = (v.get(f"/api/fiscalizacoes/{FIS}").json() for v in (a, b))
    assert fa["etapa"] == fb["etapa"] == "SELADO"
    assert _ids(a) == _ids(b)  # a cadeia igual à do roteiro limpo
    assert [x["status"] for x in fa["matriz"]] == [x["status"] for x in fb["matriz"]]
    assert sum(1 for x in fa["conversa"] if x.get("livre")) == 2  # a conversa guarda o que o visitante fez


# --------------------------------------------------------------------------------- VA-05: foto sem GPS


def _corpo_da_imagem(dados: bytes) -> bytes:
    return dados[dados.index(b"\xff\xda"):]  # do SOS ao fim: os dados da imagem


def test_foto_perde_o_gps_do_exif_sem_recodificar(tmp_path):
    jpg = tmp_path / "f.jpg"
    jpg.write_bytes(publica.foto_de_teste_com_gps())
    with Image.open(jpg) as img:
        assert ler_exif(img)[1] is not None
    antes = jpg.read_bytes()
    assert publica.foto_sem_gps(jpg, "jpeg") is True
    depois = jpg.read_bytes()
    with Image.open(jpg) as img:
        resumo, gps = ler_exif(img)
    assert gps is None and resumo["data_hora_original"] == "2026:10:20 09:15:00"  # a data fica (integridade)
    assert _corpo_da_imagem(depois) == _corpo_da_imagem(antes)  # a imagem não foi recodificada
    assert publica.foto_sem_gps(jpg, "jpeg") is False and jpg.read_bytes() == depois  # nada mais a tirar
    png = tmp_path / "f.png"
    ex = Image.Exif()
    ex[0x8825] = {1: "S", 2: (16.0, 35.0, 54.0), 3: "W", 4: (49.0, 16.0, 41.0)}
    Image.new("RGB", (8, 8), (1, 2, 3)).save(png, "PNG", exif=ex.tobytes())
    with Image.open(png) as img:
        assert ler_exif(img)[1] is not None
    assert publica.foto_sem_gps(png, "png") is True
    with Image.open(png) as img:
        assert ler_exif(img)[1] is None and img.getpixel((0, 0)) == (1, 2, 3)


def test_foto_do_visitante_entra_sem_gps(publico):
    _, visitante = publico()
    c = visitante()
    r = c.post(f"/api/fiscalizacoes/{FIS}/evidencias", data={"tipo": "foto", "item_id": "cerca1", "lat": "-16.7",
                                                             "lon": "-49.2"},
               files={"arquivo": ("galeria.jpg", publica.foto_de_teste_com_gps())})
    assert r.status_code == 200, r.text
    assert "localização gravada na foto foi apagada" in r.json()["aviso"]
    ev = [e for e in r.json()["estado"]["evidencias"] if e["tipo"] == "foto"][-1]
    arq = c.get(f"/api/fiscalizacoes/{FIS}/evidencias/{ev['id']}/arquivo")
    assert arq.status_code == 200
    with Image.open(io.BytesIO(arq.content)) as img:
        assert ler_exif(img)[1] is None
    assert "-16.59" not in r.text and "-49.27" not in r.text and not ev.get("gps")


# ------------------------------------------------------------------------ VA-06/VA-07: VLM e XML do visitante


def test_foto_fora_do_cache_do_vlm_vira_indeterminado(tmp_path, monkeypatch):
    from laudo.tools.foto import EntradaClassificarFoto

    foto = tmp_path / "f.jpg"
    foto.write_bytes(publica.foto_de_teste_com_gps())

    def falha(args):
        return Envelope.falha("classificar_foto", CodigoErro.ERRO_INTERNO,
                              "Ollama indisponível: classificação do VLM ausente do cache x")

    ferr = Ferramenta(nome="classificar_foto", descricao="d", entrada=EntradaClassificarFoto, funcao=falha)
    com = publica.classificacao_so_do_cache(ferr)
    assert com.descricao == ferr.descricao and com.entrada is ferr.entrada  # o pedido ao LLM não muda
    args = EntradaClassificarFoto(caminho_foto=str(foto), classe_esperada="cerca")
    monkeypatch.delenv("LAUDO_VLM_SO_CACHE", raising=False)
    assert not com.funcao(args).ok  # VLM de verdade (fora da demo): o erro continua erro
    monkeypatch.setenv("LAUDO_VLM_SO_CACHE", "1")
    env = com.funcao(args)
    assert env.ok and est.status_de_envelope(env) == "indeterminado"
    assert env.data["motivo"] == publica.MOTIVO_VLM_DESLIGADO and env.data["classe_esperada"] == "cerca"

    def ilegivel(args):
        return Envelope.falha("classificar_foto", CodigoErro.ENTRADA_INVALIDA, "foto ilegível")

    com2 = publica.classificacao_so_do_cache(ferr.model_copy(update={"funcao": ilegivel}))
    assert not com2.funcao(args).ok  # foto ilegível continua erro


def test_xml_que_nao_e_nfe_415_sem_gastar_vaga(publico):
    _, visitante = publico()
    c = visitante()
    n_conv = len(c.get(f"/api/fiscalizacoes/{FIS}").json()["conversa"])
    r = c.post(f"/api/fiscalizacoes/{FIS}/evidencias", data={"tipo": "nfe_xml"},
               files={"arquivo": ("pedido.xml", b"<?xml version='1.0'?><pedido><cliente>x</cliente></pedido>")})
    assert r.status_code == 415 and r.json()["erro"] == "Este XML não é uma NF-e."
    assert _uso(c)["uploads"] == 0 and len(c.get(f"/api/fiscalizacoes/{FIS}").json()["conversa"]) == n_conv
    assert publica.eh_nfe(Path(casos_mod.localizar_caso("DEMO-0001")) / "nfe_1.xml")


# ----------------------------------------------------------------------- VA-03/VA-09: voz


def _wav(segundos: float) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * segundos))
    return buf.getvalue()


def test_voz_ocupada_429_sem_gastar_fala_e_mensagens_simples(publico, capsys):
    vazio = Transcricao(texto="", vazio=True, motivo_vazio="nenhuma fala detectada (VAD)", duracao_audio_s=3.0)
    t = _Transcritor(ErroASR("OCUPADO", "transcritor ocupado"), vazio)
    _, visitante = publico(transcritor=t)
    c = visitante()
    r = _audio(c)
    assert r.status_code == 429 and r.json()["erro"] == publica.MSG_ASR_OCUPADO
    assert _uso(c)["falas"] == 0
    assert [x["limite"] for x in _eventos(capsys) if x["laudo_evento"] == "recusa_limite"] == ["asr_ocupado"]
    r = _audio(c, b"isto nao e audio")
    assert r.status_code == 400 and r.json()["erro"] == publica.MSG_AUDIO_ILEGIVEL  # sem o nome da exceção
    r = _audio(c, b"")
    assert r.status_code == 400 and _uso(c)["falas"] == 0
    r = _audio(c, _wav(3)).json()
    assert r["aviso"] == publica.MSG_SEM_FALA and "VAD" not in json.dumps(r.get("aviso"))
    assert _uso(c)["falas"] == 1


class _ModeloLento:
    def __init__(self, s: float):
        self.s = s

    def transcribe(self, x, **_):
        time.sleep(self.s)

        class Info:
            language, language_probability, duration_after_vad = "pt", 1.0, 1.0

        return [], Info()


def test_fila_do_transcritor_tem_teto(monkeypatch):
    monkeypatch.delenv("LAUDO_ASR_ESPERA_S", raising=False)
    monkeypatch.delenv("LAUDO_DEMO_PUBLICA", raising=False)
    assert asr.espera_configurada() is None  # uso normal: espera a vez
    monkeypatch.setenv("LAUDO_DEMO_PUBLICA", "1")
    assert asr.espera_configurada() == 20.0
    monkeypatch.setenv("LAUDO_ASR_ESPERA_S", "0")
    assert asr.espera_configurada() is None
    monkeypatch.setenv("LAUDO_ASR_ESPERA_S", "0,2")
    assert asr.espera_configurada() == 0.2
    monkeypatch.setenv("LAUDO_ASR_THREADS", "2")
    t = asr.TranscritorWhisper(vad=False)
    assert t.cpu_threads == 2 and t.espera_s == 0.2
    monkeypatch.delenv("LAUDO_ASR_THREADS")
    assert asr.TranscritorWhisper().cpu_threads == 4
    t._modelo = _ModeloLento(0.8)
    x = np.zeros(16000, dtype=np.float32)
    res: dict[str, object] = {}
    th = threading.Thread(target=lambda: res.setdefault("a", t.transcrever(x)))
    th.start()
    time.sleep(0.2)
    with pytest.raises(ErroASR) as e:  # a 2ª fala espera 0,2 s e desiste
        t.transcrever(x)
    th.join()
    assert e.value.codigo == "OCUPADO"
    t._modelo = _ModeloLento(0.0)
    tr = t.transcrever(x)
    assert tr.vazio and tr.espera_ms < 200


# ------------------------------------------------------------------------- SEG-03/VA-08: cota só se validado


def test_erros_de_validacao_nao_gastam_cota(publico):
    _, visitante = publico(LAUDO_DEMO_MAX_UPLOADS=1)
    c = visitante()
    r = c.post(f"/api/fiscalizacoes/{FIS}/evidencias/caso", json={"nome": "y" * 50000})
    assert r.status_code == 404 and len(r.content) < 300  # sem repetir o nome recebido
    url = f"/api/fiscalizacoes/{FIS}/evidencias"
    assert c.post(url, data={"tipo": "foto"}, files={"arquivo": ("x.exe", b"MZ\x90\x00")}).status_code == 415
    assert c.post(url, data={"tipo": "foto"}, files={"arquivo": ("v.jpg", b"")}).status_code == 415
    assert _uso(c) == {"turnos": 0, "falas": 0, "uploads": 0}
    xml = (Path(casos_mod.localizar_caso("DEMO-0001")) / "nfe_1.xml").read_bytes()
    assert c.post(url, data={"tipo": "nfe_xml"}, files={"arquivo": ("n.xml", xml)}).status_code == 200
    assert c.post(url, data={"tipo": "nfe_xml"}, files={"arquivo": ("n.xml", xml)}).status_code == 429
    assert _uso(c)["uploads"] == 1


# ------------------------------------------------------------------------------- SEG-08: PIN fora da etapa


def test_pin_errado_fora_da_etapa_nao_gasta_tentativa(tmp_path, monkeypatch):
    monkeypatch.delenv("LAUDO_DEMO_PUBLICA", raising=False)  # correção do núcleo: vale também fora da demo pública
    c = TestClient(criar_app(Config(dados=tmp_path / "api", asr="desligado")))
    fis = c.post("/api/fiscalizacoes", json={"caso": "roteiro"}).json()["id"]
    for _ in range(6):
        r = c.post(f"/api/fiscalizacoes/{fis}/assinar", json={"pin": "0000", "hash_confirmado": "0" * 64})
        assert r.status_code == 200 and r.json()["tentativas_restantes"] == 5
        assert "não aceita assinatura" in r.json()["resposta"]["fala"]
    while True:
        p = c.post(f"/api/fiscalizacoes/{fis}/roteiro/proximo").json()
        if p.get("acao_humana") == "assinar":
            break
    h = c.get(f"/api/fiscalizacoes/{fis}").json()["laudo"]["hash_raiz"]
    r = c.post(f"/api/fiscalizacoes/{fis}/assinar", json={"pin": "0000", "hash_confirmado": h}).json()
    assert r["tentativas_restantes"] == 4  # na etapa de assinar, o PIN errado conta
    ok = c.post(f"/api/fiscalizacoes/{fis}/assinar", json={"pin": PIN_DEMO, "hash_confirmado": h}).json()
    assert ok["estado"]["etapa"] == "SELADO"


# ------------------------------------------------------------------- SEG-04/05/07 e P3: saída pública


def test_sem_caminhos():
    d = {"uri": "../../../../app/eval/golden/demo/DEMO-0001/nfe_1.xml", "fonte": "/app/manual/mcr/publico",
         "url": "/api/fiscalizacoes/fis_demo_0001/trace", "w": "C:\\tmp\\copia\\foto.jpg", "t": "6,0 cab/ha",
         "l": ["file:///tmp/a.mp4", "./x/y.json", 3]}
    assert publica.sem_caminhos(d) == {"uri": "nfe_1.xml", "fonte": "publico", "url": d["url"], "w": "foto.jpg",
                                       "t": "6,0 cab/ha", "l": ["a.mp4", "y.json", 3]}


def test_saida_publica_sem_eco_sem_caminho_e_com_csp(publico, tmp_path, capsys):
    _, visitante = publico()
    c = visitante()
    pagina = c.get("/")
    assert pagina.headers["content-security-policy"] == CSP_PUBLICA
    r = c.post(f"/api/fiscalizacoes/{FIS}/turno", json={"texto": "z" * 50000})
    assert r.status_code == 422 and len(r.content) < 300 and "zzzz" not in r.text
    assert r.json() == {"erro": "requisição inválida", "campo": ["texto"]}
    xml = (Path(casos_mod.localizar_caso("DEMO-0001")) / "nfe_1.xml").read_bytes()
    up = c.post(f"/api/fiscalizacoes/{FIS}/evidencias", data={"tipo": "nfe_xml"}, files={"arquivo": ("n.xml", xml)})
    ev = [e for e in up.json()["estado"]["evidencias"] if e["tipo"] == "nfe_xml"][-1]
    arq = c.get(f"/api/fiscalizacoes/{FIS}/evidencias/{ev['id']}/arquivo")
    assert arq.headers["content-disposition"].startswith("attachment")  # o XML não abre na mesma origem
    capsys.readouterr()
    r = c.post(f"/api/fiscalizacoes/{FIS}/turno", content=b"{" + b" " * (2 * 1024 * 1024) + b"}",
               headers={"content-type": "application/json"})
    assert r.status_code == 413
    rec = [x for x in _eventos(capsys) if x["laudo_evento"] == "recusa_limite"]
    assert [(x["limite"], x["status"]) for x in rec] == [("corpo", 413)]  # o 413 pelo Content-Length vai ao painel
    _rodar(c)
    locais = {str(tmp_path), str(tmp_path).replace("\\", "/"), "../"}
    for rota in ("laudo", "trace"):
        corpo = c.get(f"/api/fiscalizacoes/{FIS}/{rota}").text
        assert not [x for x in locais if x in corpo or x.replace("/", "\\\\") in corpo], rota


def test_desligada_sem_csp_e_xml_inline(tmp_path, monkeypatch):
    monkeypatch.delenv("LAUDO_DEMO_PUBLICA", raising=False)
    c = TestClient(criar_app(Config(dados=tmp_path / "api", caso="DEMO-0001", asr="desligado")))
    assert "content-security-policy" not in c.get("/").headers
    c.post("/api/fiscalizacoes", json={"caso": "DEMO-0001"})
    r = c.post(f"/api/fiscalizacoes/{FIS}/turno", json={"texto": "z" * 3000})
    assert r.status_code == 422 and "detail" in r.json()  # o formato do FastAPI, como antes


# ----------------------------------------------------------------------------------------- lento


@pytest.mark.lento
def test_pergunta_e_foto_do_visitante_nao_tiram_os_passos_da_gravacao(tmp_path, monkeypatch):
    """DEMO-0001 com ferramentas reais e a gravação: uma cópia limpa; outra com uma mensagem livre e uma foto do
    visitante (GPS no EXIF, data antiga) antes do passo 1. Nenhum passo da segunda chama o LLM ao vivo, e ela
    chega ao SELADO com os mesmos vereditos e a mesma cadeia da limpa."""
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
    limpo = publica.rodar_roteiro(ger.fachada(publica.novo_token()), FIS)
    assert (limpo["passos"], limpo["etapa"], limpo["fora"], limpo["substituicoes"]) == (19, "SELADO", 0, 0)
    assert not vivo.chamadas
    f = ger.fachada(publica.novo_token())
    livre = f.turno(FIS, "Explique em uma frase o que a fiscalização confere aqui.")
    assert livre["resposta"]["fala"] and vivo.chamadas  # antes do passo 1: a triagem por template e o LLM ao vivo
    assert livre["estado"]["etapa"] != "BRIEFING"  # a ação livre mudou o estado (fez o trabalho do passo 1)
    foto = f.upload(FIS, "galeria.jpg", io.BytesIO(publica.foto_de_teste_com_gps()), "foto", item_id="cerca1")
    txt = json.dumps(foto, ensure_ascii=False)
    assert "-16.59" not in txt and "-49.27" not in txt  # o GPS do EXIF não voltou
    cls = [x for x in foto["estado"]["checagens"] if x["ferramenta"] == "classificar_foto"]
    assert cls and cls[-1]["status"] == "indeterminado"  # e não "erro interno da ferramenta"
    assert "erro interno" not in txt
    n_livre = len(vivo.chamadas)
    assert n_livre >= 1  # a pergunta e o arquivo do visitante foram ao LLM ao vivo
    sujo = publica.rodar_roteiro(f, FIS)
    assert len(vivo.chamadas) == n_livre  # nenhum passo do roteiro chamou o LLM ao vivo
    assert (sujo["passos"], sujo["etapa"], sujo["fora"], sujo["substituicoes"]) == (19, "SELADO", 0, 0)
    assert sujo["matriz"] == limpo["matriz"] and sujo["ids"] == limpo["ids"]
