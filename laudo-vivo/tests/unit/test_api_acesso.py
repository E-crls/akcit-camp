"""Senha compartilhada da demo pública (`LAUDO_DEMO_SENHA`, laudo.api.acesso)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from laudo.api import acesso
from laudo.api.main import criar_app
from laudo.api.servico import Config

FIS = "fis_demo_0001"


@pytest.fixture()
def app_publico(tmp_path, monkeypatch):
    monkeypatch.setenv("LAUDO_DEMO_PUBLICA", "1")
    monkeypatch.setenv("LAUDO_DEMO_DIR", str(tmp_path / "copias"))

    def fazer(senha: str | None = "curral26"):
        if senha:
            monkeypatch.setenv(acesso.ENV, senha)
        else:
            monkeypatch.delenv(acesso.ENV, raising=False)
        return criar_app(Config(dados=tmp_path / "api", caso="DEMO-0001", asr="desligado"))

    return fazer


def test_sem_senha_tudo_fecha_menos_o_que_e_aberto(app_publico):
    c = TestClient(app_publico(), follow_redirects=False)
    r = c.get("/")
    assert r.status_code == 302 and r.headers["location"] == "/entrar.html"
    r = c.get(f"/api/fiscalizacoes/{FIS}")
    assert r.status_code == 401 and r.json()["entrar"] == "/entrar.html"
    assert "lv_sessao" not in r.cookies  # sem a senha, nem a cópia do visitante é criada
    assert c.get("/api/saude").status_code == 200  # a verificação de disponibilidade não pede senha
    assert c.get("/entrar.html").status_code == 200
    assert c.get("/vendor/fonts/Barlow-500.woff2").status_code == 200


def test_senha_certa_libera_e_errada_nao(app_publico):
    c = TestClient(app_publico())
    r = c.post("/api/entrar", json={"senha": "errada"})
    assert r.status_code == 401 and "slide" in r.json()["erro"]
    r = c.post("/api/entrar", json={"senha": "  Curral26 "})  # sem diferença de maiúscula e espaço
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert c.cookies.get(acesso.COOKIE) == acesso.token("curral26")
    assert c.get(f"/api/fiscalizacoes/{FIS}").status_code == 200
    assert c.post(f"/api/fiscalizacoes/{FIS}/roteiro/proximo").status_code == 200


def test_cookie_forjado_nao_entra(app_publico):
    c = TestClient(app_publico(), follow_redirects=False)
    c.cookies.set(acesso.COOKIE, "0" * 40)
    assert c.get(f"/api/fiscalizacoes/{FIS}").status_code == 401


def test_tentativas_erradas_tem_teto(app_publico):
    c = TestClient(app_publico())
    for _ in range(acesso.TENTATIVAS):
        assert c.post("/api/entrar", json={"senha": "x"}).status_code == 401
    r = c.post("/api/entrar", json={"senha": "curral26"})
    assert r.status_code == 429  # bloqueado por um tempo, mesmo com a senha certa


def test_sem_a_variavel_nada_muda(app_publico):
    c = TestClient(app_publico(senha=None), follow_redirects=False)
    assert c.get(f"/api/fiscalizacoes/{FIS}").status_code == 200
    assert c.post("/api/entrar", json={"senha": "x"}).status_code in (404, 405)


def test_janela_das_tentativas():
    t = acesso.Tentativas(maximo=2, janela_s=10)
    t.errou("1.1.1.1", 0)
    t.errou("1.1.1.1", 1)
    assert t.bloqueado("1.1.1.1", 2) and not t.bloqueado("2.2.2.2", 2)
    assert not t.bloqueado("1.1.1.1", 11.5)
