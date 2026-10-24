"""Demonstração guiada (`apps/web/guiado/index.html`): servida em /guiado/ e só com rotas que existem."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.routing import Route

from laudo.api import acesso
from laudo.api.main import criar_app
from laudo.api.servico import Config

WEB = Path(__file__).resolve().parents[2] / "apps" / "web"
PAGINA = WEB / "guiado" / "index.html"
FIS = "fis_demo_0001"


@pytest.fixture()
def app_publico(tmp_path, monkeypatch):
    monkeypatch.setenv("LAUDO_DEMO_PUBLICA", "1")
    monkeypatch.setenv("LAUDO_DEMO_DIR", str(tmp_path / "copias"))
    monkeypatch.delenv(acesso.ENV, raising=False)
    return criar_app(Config(dados=tmp_path / "api", caso="DEMO-0001", asr="desligado"))


def _rotas(app) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for r in app.routes:
        if isinstance(r, Route) and r.path.startswith("/api/") and "{resto:path}" not in r.path:
            out.setdefault(r.path, set()).update(r.methods or ())
    return out


def _chamadas(html: str) -> list[tuple[str, str]]:
    """(método, rota) de cada `pedir(...)` e de cada link para a API, com `${...}` trocado por `{fis_id}`."""
    api = re.search(r'const API = "([^"]+)"', html).group(1)
    out = []
    for metodo, alvo in re.findall(r'pedir\("(GET|POST)",\s*(API\b|`[^`]*`)', html):
        caminho = api if alvo == "API" else alvo.strip("`").replace("${API}", api)
        out.append((metodo, re.sub(r"\$\{[^}]+\}", "{fis_id}", caminho)))
    for alvo in re.findall(r"`\$\{API\}([^`]*)`", html):
        caminho = re.sub(r"\$\{[^}]+\}", "{fis_id}", api + alvo)
        if not any(c == caminho for _, c in out):
            out.append(("GET", caminho))
    return out


def test_guiado_e_servido_e_so_chama_rotas_que_existem(app_publico):
    c = TestClient(app_publico)
    r = c.get("/guiado/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    html = r.text
    assert html == PAGINA.read_text(encoding="utf-8")
    chamadas = _chamadas(html)
    usadas = {c for _, c in chamadas}
    # as quatro rotas do fluxo: estado, próximo passo, assinatura, recomeçar; e o laudo para ler
    assert {"/api/fiscalizacoes/{fis_id}", "/api/fiscalizacoes/{fis_id}/roteiro/proximo", "/api/fiscalizacoes/{fis_id}/assinar",
            "/api/fiscalizacoes", "/api/fiscalizacoes/{fis_id}/laudo.html"} <= usadas
    rotas = _rotas(app_publico)
    for metodo, caminho in chamadas:
        assert caminho in rotas, f"rota inexistente na página guiada: {caminho}"
        assert metodo in rotas[caminho], f"{metodo} não existe em {caminho}"


def test_guiado_so_usa_arquivos_locais(app_publico):
    c = TestClient(app_publico)
    html = PAGINA.read_text(encoding="utf-8")
    assert not re.search(r'(?:src|href)="https?://', html), "a página guiada não carrega nada de fora"
    assert "#FFC414" not in html.upper(), "paleta Cerrado: nada de amarelo"
    estaticos = set(re.findall(r'url\("(/[^"]+)"\)', html)) | set(re.findall(r'href="(/[^"#?]*)"', html))
    estaticos |= {m for m in re.findall(r'link\("[^"]+",\s*"(/[^"]*)"', html)}
    assert "/vendor/fonts/Barlow-500.woff2" in estaticos and "/" in estaticos
    for caminho in sorted(estaticos):
        assert c.get(caminho).status_code == 200, caminho


def test_estado_da_demo_tem_o_que_a_pagina_le(app_publico):
    c = TestClient(app_publico)
    e = c.get(f"/api/fiscalizacoes/{FIS}").json()
    r = e["roteiro"]
    assert r["proximo"] == 1 and r["total"] == len(r["passos"]) and any(p["acao"] == "assinar" for p in r["passos"])
    assert all({"n", "titulo", "acao"} <= set(p) for p in r["passos"])
    novo = c.post("/api/fiscalizacoes", json={"caso": r["caso_id"], "reiniciar": True}).json()
    assert novo["id"] == FIS and novo["roteiro"]["proximo"] == 1


def test_depois_de_entrar_vai_para_a_guiada():
    assert 'location.replace("/guiado/")' in (WEB / "entrar.html").read_text(encoding="utf-8")
