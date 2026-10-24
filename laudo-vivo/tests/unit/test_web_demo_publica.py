"""Interface na demonstração pública (`LAUDO_DEMO_PUBLICA=1`): as regras puras da tela (apps/web/js/regras.js
e api.js) testadas no Node, também com os estados reais da demo pública ao longo do roteiro (LLM roteirizado e
ferramentas falsas, como em test_api_demo_publica.py). O que o teste confere:

- P3: no passo do roteiro que não pede arquivo, a câmera não é a ação principal do cartão AGORA ("Executar
  passo" é);
- VA-04: vídeo acima de 30 MB ou de 20 s e foto acima de 10 MB barrados antes de enviar, com mensagem em
  português; 413/429 sem o JSON do app (o front-end do Cloud Run) viram frase em português; a mensagem do 429
  com JSON aparece; fora da demonstração pública, as mensagens continuam as de antes;
- P5: depois do selo ainda há o passo 19 (a tela do selo no celular oferece "Continuar a demonstração");
- e, no CSS (sem navegador), que os ajustes de tela (P4, P6) ficam presos à classe `demo-publica` do corpo.

A rolagem até o PIN e a barra em duas linhas dependem do leiaute: foram conferidas no Edge, em 1440x900 e
390x844. Sem o Node no PATH, os testes do Node pulam (o CI do Python não depende dele)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from laudo.agent import estado as est
from laudo.api import casos as casos_mod
from laudo.api.main import criar_app
from laudo.api.servico import PIN_DEMO, Config
from laudo.tools import laudo as ferr_laudo

RAIZ = Path(__file__).resolve().parents[2]
WEB = RAIZ / "apps" / "web"
SCRIPT = Path(__file__).parent / "dados_web" / "demo_publica.mjs"
FIS = "fis_demo_0001"
NODE = shutil.which("node")
SEM_NODE = pytest.mark.skipif(NODE is None, reason="Node ausente")


@pytest.fixture(autouse=True)
def _limpar():
    yield
    est.ids_deterministicos(None)
    ferr_laudo.configurar(None, None)


def _node(*args: str) -> str:
    cmd = [NODE, str(SCRIPT), *args]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=120, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    assert re.search(r"^ok \d+", r.stdout, re.MULTILINE), r.stdout
    return r.stdout


@SEM_NODE
def test_regras_puras_da_demo_publica():
    _node()


@SEM_NODE
@pytest.mark.skipif(casos_mod.localizar_caso("DEMO-0001") is None, reason="DEMO-0001 ausente")
def test_regras_com_os_estados_reais_da_demo_publica(tmp_path, monkeypatch):
    monkeypatch.setenv("LAUDO_DEMO_PUBLICA", "1")
    monkeypatch.setenv("LAUDO_DEMO_DIR", str(tmp_path / "copias"))
    c = TestClient(criar_app(Config(dados=tmp_path / "api", caso="DEMO-0001", asr="desligado")))
    # o sinal que a interface lê (publica() em fiscalizacao.js e laudo.js; a classe do corpo em app.js)
    assert c.get("/api/saude").json()["config"]["demo_publica"] is True
    estados, selado = [], None
    while True:
        e = c.get(f"/api/fiscalizacoes/{FIS}").json()
        if e["etapa"] == "SELADO" and selado is None:
            selado = e
        if e["roteiro"]["proximo"] > e["roteiro"]["total"]:
            break
        estados.append(e)
        r = c.post(f"/api/fiscalizacoes/{FIS}/roteiro/proximo")
        assert r.status_code == 200, r.text
        j = r.json()
        if j.get("acao_humana") == "assinar":
            corpo = {"pin": PIN_DEMO, "hash_confirmado": j["estado"]["laudo"]["hash_raiz"]}
            assert c.post(f"/api/fiscalizacoes/{FIS}/assinar", json=corpo).status_code == 200
    assert selado is not None and selado["roteiro"]["proximo"] == selado["roteiro"]["total"]
    arq = tmp_path / "estados.json"
    dados = {"estados": estados, "selado": selado, "depois": e}
    arq.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    _node(str(arq))


def test_ajustes_de_tela_so_na_demo_publica():
    """P4 e P6 são CSS: cada regra nova fica presa a `body.demo-publica` (a classe que app.js liga pela saúde)."""
    css = (WEB / "css" / "app.css").read_text(encoding="utf-8")
    seletores = [s.strip() for s in re.findall(r"(?:^|[}\n])\s*([^{}@/]+?)\s*\{", css)]
    alvo = re.compile(r"titulo-txt|\.demo-faixa$|roteiro-marca$|pin-dica( \.ic)?$")
    novos = [s for s in seletores if alvo.search(s)]
    # a faixa fina duplicada sai; a barra em até 2 linhas; a marca repetida da barra sai; a dica do PIN numa linha
    assert "body.demo-publica .demo-faixa" in novos and "body.demo-publica .roteiro-marca" in novos
    assert any("titulo-txt" in s for s in novos) and "body.demo-publica .pin-dica" in novos
    for s in novos:
        if "demo-publica" not in s:
            assert s in {".demo-faixa", ".roteiro-marca", ".pin-dica", ".pin-dica .ic"}, s  # as de antes
    regra = re.search(r"body\.demo-publica \.roteiro \.titulo-txt,[^{]*\{([^}]*)\}", css)
    assert regra and "-webkit-line-clamp: 2" in regra.group(1)
    app = (WEB / "js" / "app.js").read_text(encoding="utf-8")
    assert 'classList.toggle("demo-publica", publica())' in app
    # as frases do 413/429 sem JSON só na demonstração pública
    assert "definirDemoPublica(publica() ?" in app
