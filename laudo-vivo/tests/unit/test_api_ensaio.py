"""Higiene de ensaio e aquecimento do modelo (P1-9 e P0-3, 22/10/2026).

- P1-9: "Recomeçar" tira do índice de fotos as linhas da fiscalização recomeçada. Antes, a mesma foto enviada de
  novo depois de recomeçar dava DUPLICATA_MESMA_FISCALIZACAO (e, numa fiscalização nova, DUPLICATA_EXATA).
- P0-3: o aquecimento faz uma chamada de chat curta com o mesmo começo do 1º turno (prompt de sistema e
  ferramentas), para o Ollama não processar os ~9 mil tokens do prompt na 1ª resposta real.
"""

from __future__ import annotations

import json
import shutil

import httpx
import pytest
from test_visao_foto import RECEBIDA, natural, salvar

from laudo.agent import estado as est
from laudo.api.servico import Config, Servico
from laudo.contracts import sha256_arquivo
from laudo.llm.provider import NUM_CTX
from laudo.tools import laudo as ferr_laudo
from laudo.vision.integridade import IndiceFotos, avaliar_integridade


@pytest.fixture()
def limpar():
    yield
    est.ids_deterministicos(None)
    ferr_laudo.configurar(None, None)


def _codigos(d: dict) -> set[str]:
    return {m["codigo"] for m in d["motivos"]}


def test_recomecar_tira_as_fotos_da_fiscalizacao_do_indice(tmp_path, limpar):
    srv = Servico(Config(dados=tmp_path / "api", asr="desligado"))
    fis_id = srv.abrir_caso("roteiro")["id"]
    idx = IndiceFotos(srv.dados / "indices" / "fotos.jsonl")
    foto = salvar(natural(51), tmp_path / "upload_1.jpg")
    outra = salvar(natural(52), tmp_path / "outra.jpg")

    def integridade(caminho, contexto):
        return avaliar_integridade(caminho, sha256_arquivo(str(caminho)), recebida_em=RECEBIDA, contexto=contexto,
                                   indice=idx)

    assert integridade(foto, fis_id)["status"] == "ok"  # 1º ensaio: a foto enviada entra no índice
    assert integridade(outra, "fis_outra_fiscalizacao")["status"] == "ok"
    reenvio = shutil.copy(foto, tmp_path / "upload_2.jpg")  # o upload ganha outro caminho
    assert "DUPLICATA_MESMA_FISCALIZACAO" in _codigos(integridade(reenvio, fis_id))  # o problema da sonda
    srv.abrir_caso("roteiro", reiniciar=True)  # botão "Recomeçar"
    contextos = [e["contexto"] for e in idx.entradas()]
    assert fis_id not in contextos and contextos == ["fis_outra_fiscalizacao"]  # a outra fiscalização fica
    d = integridade(reenvio, fis_id)
    assert d["status"] == "ok" and not d["duplicata_de"]
    # a outra fiscalização continua protegida contra reuso da foto dela
    assert "DUPLICATA_EXATA" in _codigos(integridade(shutil.copy(outra, tmp_path / "x.jpg"), fis_id))


class _ClienteOllama:
    """Cliente httpx falso do provedor: guarda o corpo de cada /api/chat e responde sem ferramentas."""

    def __init__(self):
        self.corpos: list[dict] = []

    def post(self, url, json=None, timeout=None):  # mesma assinatura de httpx.Client.post
        self.corpos.append(json)
        return httpx.Response(200, json={"message": {"content": "Bom dia."}, "model": json["model"],
                                         "prompt_eval_count": 10}, request=httpx.Request("POST", url))

    def get(self, url, timeout=None):
        return httpx.Response(200, json={"version": "teste"}, request=httpx.Request("GET", url))


def test_aquecimento_faz_chat_curto_com_o_mesmo_prefixo_do_1o_turno(tmp_path, monkeypatch, limpar):
    srv = Servico(Config(dados=tmp_path / "api", asr="desligado", llm="ollama"))
    postados: list[tuple[str, dict]] = []

    def post(url, json=None, timeout=None):  # httpx.post do aquecimento (fora do provedor)
        postados.append((url, json))
        return httpx.Response(200, json={"model": json["model"], "prompt_eval_count": 9300},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    falso = _ClienteOllama()
    srv.provedor._cliente = falso
    r = srv.aquecer_llm()
    assert falso.corpos == []  # fora do provedor: não grava na contingência nem abre span de LLM
    assert r["ok"] and r["chat"]["ok"] and r["chat"]["tokens_prompt"] == 9300 and r["chat"]["n_ferramentas"] > 0
    (url_g, gen), (url_c, chat) = postados
    assert url_g.endswith("/api/generate") and url_c.endswith("/api/chat")
    assert chat["model"] == srv.provedor.modelo and chat["keep_alive"] == srv.provedor.keep_alive
    assert chat["options"]["num_ctx"] == NUM_CTX == gen["options"]["num_ctx"]  # sem recarregar o modelo
    assert chat["options"]["num_predict"] == 1 and chat["think"] is False

    # o 1º pedido real do condutor começa igual: mesmo prompt de sistema (com a data) e mesmas ferramentas
    fis_id = srv.abrir_caso("roteiro")["id"]
    srv.turno(fis_id, "Bom dia. Vamos começar a fiscalização.")
    real = next(c for c in falso.corpos if c.get("tools"))
    assert real["messages"][0] == chat["messages"][0]
    assert json.dumps(real["tools"], sort_keys=True) == json.dumps(chat["tools"], sort_keys=True)
    assert real["options"] == {k: v for k, v in chat["options"].items() if k != "num_predict"}


def test_aquecimento_tolera_falha_do_chat(tmp_path, monkeypatch, limpar):
    srv = Servico(Config(dados=tmp_path / "api", asr="desligado", llm="ollama"))

    def post(url, json=None, timeout=None):
        if url.endswith("/api/chat"):
            raise httpx.ReadTimeout("lento", request=httpx.Request("POST", url))
        return httpx.Response(200, json={}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    r = srv.aquecer_llm()
    assert r["ok"] and r["chat"] == {"ok": False, "erro": "ReadTimeout", "ms": r["chat"]["ms"]}
    assert Servico(Config(dados=tmp_path / "api2", asr="desligado")).aquecer_llm()["aviso"].startswith("LLM roteiro")
