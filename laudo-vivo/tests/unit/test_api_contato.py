"""Formulário de contato da página do produto (`POST /api/contato`, laudo.api.contato)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from laudo.api import contato
from laudo.api.main import criar_app
from laudo.api.servico import Config

OK = {"nome": "Maria Teste", "email": "maria@exemplo.com.br", "instituicao": "Cooperativa X", "cargo": "gerente",
      "mensagem": "Quero conversar.", "consentimento": True}


@pytest.fixture()
def cliente(tmp_path, monkeypatch):
    monkeypatch.delenv("LAUDO_CONTATO_BUCKET", raising=False)

    def fazer(publica: bool = False, senha: str | None = None):
        if publica:
            monkeypatch.setenv("LAUDO_DEMO_PUBLICA", "1")
            monkeypatch.setenv("LAUDO_DEMO_DIR", str(tmp_path / "copias"))
        if senha:
            monkeypatch.setenv("LAUDO_DEMO_SENHA", senha)
        app = criar_app(Config(dados=tmp_path / "api", caso="DEMO-0001", asr="desligado"))
        return TestClient(app), tmp_path / "api" / "contatos.jsonl"

    return fazer


def _enviar(c, corpo, origem="https://laudovivo.web.app"):
    return c.post("/api/contato", content=json.dumps(corpo), headers={"Content-Type": "text/plain;charset=UTF-8",
                                                                       "Origin": origem})


def test_contato_guarda_e_libera_a_origem_do_link_curto(cliente):
    c, arq = cliente(publica=True, senha="curral26")  # aberto mesmo com a senha da demo
    r = _enviar(c, OK)
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert r.headers["access-control-allow-origin"] == "https://laudovivo.web.app"
    linha = json.loads(arq.read_text(encoding="utf-8").strip())
    assert linha["email"] == "maria@exemplo.com.br" and linha["consentimento"] is True and "site" not in linha


def test_sem_consentimento_ou_email_invalido_nao_guarda(cliente):
    c, arq = cliente()
    assert _enviar(c, {**OK, "consentimento": False}).status_code == 422
    assert _enviar(c, {**OK, "email": "sem-arroba"}).status_code == 422
    assert not arq.exists()


def test_campo_isca_responde_ok_sem_guardar(cliente):
    c, arq = cliente()
    assert _enviar(c, {**OK, "site": "http://spam"}).status_code == 200
    assert not arq.exists()


def test_origem_estranha_e_recusada_na_demo_publica(cliente):
    c, arq = cliente(publica=True)
    assert _enviar(c, OK, origem="https://exemplo.invalido").status_code == 403
    assert not arq.exists()


def test_teto_por_ip(cliente):
    c, _ = cliente()
    for _ in range(contato.MAX_POR_IP):
        assert _enviar(c, OK).status_code == 200
    assert _enviar(c, OK).status_code == 429


def test_dados_do_contato_nao_vao_para_o_log(cliente, capsys, monkeypatch):
    c, _ = cliente(publica=True)
    _enviar(c, OK)
    saida = capsys.readouterr().out
    assert "maria@exemplo.com.br" not in saida and "Maria Teste" not in saida
    assert '"laudo_evento": "contato"' in saida
