"""Cache do VLM e servidor do Ollama (P0-4 e P3-16, 22/10/2026).

P0-4: uma rodada ao vivo com foto nova (caso novo) gravava as respostas do VLM dentro de
`tests/unit/dados_agente/vlm_cache_demo` (versionada). Agora o cache versionado só é lido; as respostas novas vão
para `LAUDO_VLM_CACHE_GRAVACAO` (padrão: `dados_locais/vlm_cache`), que também é lida no replay.

P3-16: a classificação de foto e a leitura de documento usam o mesmo `OLLAMA_HOST` do condutor.
"""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest
from test_visao_foto import _ollama_falso, natural, salvar

from laudo.llm import provider
from laudo.tools import leitura_documentos as LD
from laudo.tools.foto import EntradaClassificarFoto, classificar_foto
from laudo.vision import cache_vlm


@pytest.fixture()
def pastas(tmp_path, monkeypatch):
    """`tests/` e `dados_locais/vlm_cache` de mentira (o teste nunca toca as pastas do repositório)."""
    protegida = tmp_path / "repo" / "tests"
    padrao = tmp_path / "repo" / "dados_locais" / "vlm_cache"
    monkeypatch.setattr(cache_vlm, "PASTAS_PROTEGIDAS", (protegida,))
    monkeypatch.setattr(cache_vlm, "GRAVACAO_PADRAO", padrao)
    for v in (cache_vlm.ENV_LEITURA, cache_vlm.ENV_GRAVACAO, cache_vlm.ENV_SO_CACHE):
        monkeypatch.delenv(v, raising=False)
    demo = protegida / "unit" / "dados_agente" / "vlm_cache_demo"
    return demo, padrao


def test_pastas_do_cache(pastas, tmp_path):
    demo, padrao = pastas
    assert cache_vlm.pastas({}) is None
    pc = cache_vlm.pastas({"LAUDO_VLM_CACHE": str(demo)})
    assert pc.leitura == (demo, padrao) and pc.gravacao == padrao and not pc.so_cache  # tests/ só é lida
    livre = tmp_path / "eval_cache"
    pc = cache_vlm.pastas({"LAUDO_VLM_CACHE": str(livre)})
    assert pc.leitura == (livre,) and pc.gravacao == livre  # fora de tests/: como antes (lê e grava nela)
    outra = tmp_path / "sinteticos" / "vlm_cache_ufg"
    pc = cache_vlm.pastas({"LAUDO_VLM_CACHE": str(demo), "LAUDO_VLM_CACHE_GRAVACAO": str(outra)})
    assert pc.leitura == (demo, outra) and pc.gravacao == outra
    pc = cache_vlm.pastas({"LAUDO_VLM_CACHE": str(demo), "LAUDO_VLM_SO_CACHE": "1"})
    assert pc.so_cache and pc.gravacao is None and pc.leitura == (demo, padrao)
    pc = cache_vlm.pastas({"LAUDO_VLM_CACHE_GRAVACAO": str(outra)})
    assert pc.leitura == (outra,) and pc.gravacao == outra
    assert cache_vlm.protegida(demo) and not cache_vlm.protegida(outra)


def test_classificacao_nova_nao_grava_no_cache_versionado(pastas, tmp_path, monkeypatch):
    demo, padrao = pastas
    chamadas: list[dict] = []
    _ollama_falso(monkeypatch, ["cerca"] * 8, chamadas)
    velha = salvar(natural(31), tmp_path / "velha.jpg")
    nova = salvar(natural(32), tmp_path / "nova.jpg")
    hoje = date(2026, 10, 20)
    # a fixture da demo é gravada de propósito (LAUDO_VLM_CACHE_GRAVACAO apontando para ela)
    monkeypatch.setenv("LAUDO_VLM_CACHE_GRAVACAO", str(demo))
    assert classificar_foto(EntradaClassificarFoto(caminho_foto=str(velha), data_referencia=hoje)).ok
    versionados = sorted(p.name for p in demo.iterdir())
    assert len(chamadas) == 2 and len(versionados) == 2
    # rodada ao vivo de um caso novo: lê a demo, mas a foto nova vai para dados_locais/vlm_cache
    monkeypatch.delenv("LAUDO_VLM_CACHE_GRAVACAO")
    monkeypatch.setenv("LAUDO_VLM_CACHE", str(demo))
    assert classificar_foto(EntradaClassificarFoto(caminho_foto=str(velha), data_referencia=hoje)).ok
    assert len(chamadas) == 2  # a resposta versionada continua valendo
    assert classificar_foto(EntradaClassificarFoto(caminho_foto=str(nova), data_referencia=hoje)).ok
    assert len(chamadas) == 4
    assert sorted(p.name for p in demo.iterdir()) == versionados  # tests/ intacta
    assert len(list(padrao.glob("cls_*.json"))) == 2
    # replay (só cache): as duas fotos saem das duas pastas, sem Ollama
    monkeypatch.setenv("LAUDO_VLM_SO_CACHE", "1")
    for f in (velha, nova):
        assert classificar_foto(EntradaClassificarFoto(caminho_foto=str(f), data_referencia=hoje)).data["classe"] == "cerca"
    assert len(chamadas) == 4


def test_leitura_de_documento_nao_grava_no_cache_versionado(pastas):
    demo, padrao = pastas
    demo.mkdir(parents=True)
    chamadas = []

    def leitor(img, prompt, esquema, temperatura, semente):
        chamadas.append(semente)
        return {"chave_acesso": "1" * 44}

    ler = LD.com_cache(leitor, demo, "qwen3.5:4b")
    assert ler("img", "p", {}, 0.0, 1) == {"chave_acesso": "1" * 44}
    assert ler("img", "p", {}, 0.0, 1) == {"chave_acesso": "1" * 44} and chamadas == [1]
    assert list(demo.iterdir()) == [] and len(list(padrao.glob("*.json"))) == 1
    so_cache = LD.com_cache(leitor, demo, "qwen3.5:4b", so_cache=True)
    assert so_cache("img", "p", {}, 0.0, 1)["chave_acesso"] == "1" * 44  # relida da pasta de gravação
    with pytest.raises(httpx.HTTPError, match="ausente do cache"):
        so_cache("img", "p", {}, 0.0, 2)
    assert chamadas == [1]


def test_url_do_ollama_normalizada(monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    assert provider.url_ollama() == provider.URL_PADRAO
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:11435")
    assert provider.url_ollama() == "http://127.0.0.1:11435"
    monkeypatch.setenv("OLLAMA_HOST", "https://gpu.local:443/")
    assert provider.url_ollama() == "https://gpu.local:443"
    assert provider.url_ollama("http://outro:1/") == "http://outro:1"  # argumento explícito vence a variável
    assert provider.OllamaProvider().base_url == "https://gpu.local:443"


def test_vlm_e_leitura_de_documento_usam_o_ollama_host(tmp_path, monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:11435")
    for v in (cache_vlm.ENV_LEITURA, cache_vlm.ENV_GRAVACAO):
        monkeypatch.delenv(v, raising=False)
    urls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        urls.append(str(req.url))
        if req.url.path == "/api/ps":
            return httpx.Response(200, json={"models": []})
        return httpx.Response(200, json={"message": {"content": json.dumps({"classe": "cerca",
                                                                              "justificativa": "t"})}})

    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    foto = salvar(natural(33), tmp_path / "f.jpg")
    assert classificar_foto(EntradaClassificarFoto(caminho_foto=str(foto), data_referencia=date(2026, 10, 20))).ok
    assert urls and all(u.startswith("http://127.0.0.1:11435/api/") for u in urls)

    postados: list[str] = []

    def post(url, json=None, timeout=None):  # mesma assinatura de httpx.post
        postados.append(url)
        return httpx.Response(200, json={"message": {"content": "{}"}}, request=httpx.Request("POST", url))

    monkeypatch.setattr(LD.httpx, "post", post)
    assert LD._ollama("qwen3.5:4b", 5.0)("img", "p", {}, 0.0, 1) == {}
    assert postados == ["http://127.0.0.1:11435/api/chat"]
