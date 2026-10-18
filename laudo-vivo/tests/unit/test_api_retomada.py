"""Retomada (REQ-37): o servidor cai no meio da fiscalização e sobe de novo sobre a mesma pasta de dados.

O que tem de continuar íntegro depois do reinício: a cadeia de hash do estado, a confirmação de números
falados que estava pendente, as tentativas erradas de PIN (a trava não pode ser zerada por reinício) e o
roteiro da demo (próximo passo). Também: uma queda no meio da gravação do estado não deixa estado pela metade.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from laudo.agent import estado as est
from laudo.api.main import criar_app
from laudo.api.servico import MAX_TENTATIVAS_PIN, PIN_DEMO, Config
from laudo.audit import hashchain
from laudo.speech.asr import Transcricao
from laudo.tools import laudo as ferr_laudo

FIS = "fis_demo_regional"


class TranscritorFalso:
    def __init__(self, *textos: str):
        self.textos = list(textos)

    def transcrever(self, caminho):
        return Transcricao(
            texto=self.textos.pop(0),
            latencia_ms=5,
            duracao_audio_s=2.0,
            duracao_fala_s=1.5,
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


@pytest.fixture(autouse=True)
def _limpar():
    yield
    est.ids_deterministicos(None)
    ferr_laudo.configurar(None, None)


def _servidor(dados, *falas: str) -> TestClient:
    """Um "processo" do servidor sobre a pasta `dados` (cada chamada é um reinício)."""
    t = TranscritorFalso(*falas) if falas else None
    cfg = Config(dados=dados, asr="auto" if t else "desligado")
    return TestClient(criar_app(cfg, transcritor=t))


def _ate_assinatura(c: TestClient) -> None:
    while True:
        r = c.post(f"/api/fiscalizacoes/{FIS}/roteiro/proximo")
        assert r.status_code == 200, r.text
        if r.json().get("acao_humana") == "assinar":
            return


def _cadeia_integra(dados) -> est.Fiscalizacao:
    fis = est.RepositorioFiscalizacoes(dados).carregar(FIS)
    assert hashchain.verificar_cadeia(fis.evidencias).integra
    return fis


def test_servidor_reinicia_no_meio_e_a_fiscalizacao_continua(tmp_path):
    dados = tmp_path / "api"
    audio = {"audio": ("fala.webm", b"\x1aE\xdf\xa3 audio", "audio/webm")}
    a = _servidor(dados, "Contei quarenta e duas cabeças no curral.")
    a.post("/api/fiscalizacoes", json={"caso": "roteiro"})
    _ate_assinatura(a)
    h = a.get(f"/api/fiscalizacoes/{FIS}").json()["laudo"]["hash_raiz"]
    for _ in range(2):  # dois PINs errados antes da queda
        r = a.post(f"/api/fiscalizacoes/{FIS}/assinar", json={"pin": "9999", "hash_confirmado": h}).json()
    assert r["tentativas_restantes"] == MAX_TENTATIVAS_PIN - 2
    pend = a.post(f"/api/fiscalizacoes/{FIS}/turno-audio", files=audio).json()
    assert pend["confirmacao"]["texto"] == "Contei 42 cabeças no curral."
    antes = _cadeia_integra(dados)
    n_conversa = len(est.RepositorioFiscalizacoes(dados).ler_conversa(FIS))
    del a  # queda: nada é encerrado de forma limpa; o próximo processo começa sem memória nenhuma
    est.ids_deterministicos(None)
    ferr_laudo.configurar(None, None)

    b = _servidor(dados, "sim")
    e = b.get(f"/api/fiscalizacoes/{FIS}").json()
    depois = _cadeia_integra(dados)
    assert [x.sha256 for x in depois.evidencias] == [x.sha256 for x in antes.evidencias]
    assert e["etapa"] == antes.estado_fsm and e["laudo"]["hash_raiz"] == h
    # a confirmação pendente voltou e o "sim" do novo processo a conclui
    assert e["confirmacao_pendente"]["texto"] == "Contei 42 cabeças no curral."
    sim = b.post(f"/api/fiscalizacoes/{FIS}/turno-audio", files=audio).json()
    assert sim["confirmado"] is True and sim["resposta"]["alegacoes"][0]["valor"] == 42
    assert b.get(f"/api/fiscalizacoes/{FIS}").json()["confirmacao_pendente"] is None
    # a numeração dos turnos continua (vem da conversa em disco, não de um contador em memória)
    assert sim["resposta"]["turno"] == n_conversa + 1
    # a trava do PIN não zerou com o reinício: 2 erros antes + 1 agora
    r = b.post(f"/api/fiscalizacoes/{FIS}/assinar", json={"pin": "0000", "hash_confirmado": h}).json()
    assert r["tentativas_restantes"] == MAX_TENTATIVAS_PIN - 3
    # o roteiro continua no passo da assinatura e o PIN certo sela
    assert b.get(f"/api/fiscalizacoes/{FIS}").json()["roteiro"]["proximo"] == e["roteiro"]["proximo"]
    ok = b.post(f"/api/fiscalizacoes/{FIS}/assinar", json={"pin": PIN_DEMO, "hash_confirmado": h}).json()
    assert ok["estado"]["etapa"] == "SELADO"
    _cadeia_integra(dados)


def test_trava_do_pin_sobrevive_ao_reinicio(tmp_path):
    dados = tmp_path / "api"
    a = _servidor(dados)
    a.post("/api/fiscalizacoes", json={"caso": "roteiro"})
    _ate_assinatura(a)
    h = a.get(f"/api/fiscalizacoes/{FIS}").json()["laudo"]["hash_raiz"]
    for _ in range(MAX_TENTATIVAS_PIN):
        a.post(f"/api/fiscalizacoes/{FIS}/assinar", json={"pin": "9999", "hash_confirmado": h})
    del a
    ferr_laudo.configurar(None, None)
    b = _servidor(dados)
    r = b.post(f"/api/fiscalizacoes/{FIS}/assinar", json={"pin": PIN_DEMO, "hash_confirmado": h})
    assert r.status_code == 423 and "reinício" in r.json()["erro"]


def test_queda_durante_a_gravacao_nao_corrompe_o_estado(tmp_path, monkeypatch):
    """O processo morre entre escrever o arquivo temporário e trocá-lo pelo estado: o estado em disco fica na
    versão anterior (íntegra) e o turno seguinte, já no processo novo, segue normalmente."""
    dados = tmp_path / "api"
    a = _servidor(dados)
    a.post("/api/fiscalizacoes", json={"caso": "roteiro"})
    a.post(f"/api/fiscalizacoes/{FIS}/roteiro/proximo")
    antes = _cadeia_integra(dados)
    real = os.replace

    def queda(origem, destino):
        if Path(destino).parent.name == "fiscalizacoes" and Path(destino).name == f"{FIS}.json":
            raise OSError("queda simulada do processo durante a gravação")
        return real(origem, destino)

    monkeypatch.setattr(est.os, "replace", queda)
    r = a.post(f"/api/fiscalizacoes/{FIS}/turno", json={"texto": "Esse é o vídeo do lote."})
    assert r.status_code == 200 and "nada foi alterado" in r.json()["resposta"]["fala"]
    monkeypatch.setattr(est.os, "replace", real)
    assert len(_cadeia_integra(dados).evidencias) == len(antes.evidencias)
    assert not list((dados / "fiscalizacoes").glob(".*.tmp"))  # o temporário não ficou para trás
    del a
    ferr_laudo.configurar(None, None)
    b = _servidor(dados)
    r = b.post(f"/api/fiscalizacoes/{FIS}/roteiro/proximo")
    assert r.status_code == 200
    assert len(_cadeia_integra(dados).evidencias) > len(antes.evidencias)
