"""VertexProvider (Gemini pela API compatível com a da OpenAI) e ProvedorEmCadeia, sem rede."""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from laudo.llm import provider as prov
from laudo.llm.provider import (
    ErroLLM,
    ProvedorEmCadeia,
    ProvedorRoteirizado,
    RespostaLLM,
    VertexProvider,
    criar_provedor,
)


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setenv("LAUDO_VERTEX_TOKEN", "tok-teste")
    monkeypatch.setattr(prov, "_COTA", prov._CotaDiaria())
    monkeypatch.setattr(prov.time, "sleep", lambda s: None)


def _resposta(conteudo="", chamadas=(), entrada=100, saida=10, assinatura="sig-1"):
    msg: dict = {"role": "assistant", "content": conteudo or None}
    if chamadas:
        msg["tool_calls"] = [
            {
                "id": f"call_{i}",
                "type": "function",
                "function": {"name": n, "arguments": json.dumps(a)},
                "extra_content": {"google": {"thought_signature": assinatura}},
            }
            for i, (n, a) in enumerate(chamadas)
        ]
    return {"choices": [{"message": msg}], "usage": {"prompt_tokens": entrada, "completion_tokens": saida}}


def _provedor(respostas, pedidos, **kw):
    def tratar(req: httpx.Request) -> httpx.Response:
        pedidos.append(json.loads(req.content))
        r = respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        if isinstance(r, int):
            return httpx.Response(r, text="erro")
        return httpx.Response(200, json=r)

    cliente = httpx.Client(transport=httpx.MockTransport(tratar))
    return VertexProvider(
        modelo="gemini-3.1-flash-lite", projeto="p", hoje=date(2026, 10, 24), cliente=cliente, **kw
    )


HIST = [
    {"role": "system", "content": "Sistema."},
    {"role": "user", "content": "Contei 42."},
    {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "contar", "arguments": {"n": 42}}}]},
    {"role": "tool", "tool_name": "contar", "content": "ok"},
]


def test_url_global_e_regional():
    assert VertexProvider(projeto="p").base_url.startswith("https://aiplatform.googleapis.com/v1/projects/p/locations/global/")
    assert VertexProvider(projeto="p", local="us-central1").base_url.startswith("https://us-central1-aiplatform")


def test_converte_historico_do_ollama():
    corpo = VertexProvider(projeto="p", hoje=date(2026, 10, 24)).montar_requisicao(
        HIST, ferramentas=[{"type": "function", "function": {"name": "contar"}}], formato={"type": "object"}
    )
    msgs = corpo["messages"]
    assert prov.MARCADOR_DATA in msgs[0]["content"]  # data injetada no sistema, como no Ollama
    tc = msgs[2]["tool_calls"][0]
    assert tc["id"] == "c2_0" and json.loads(tc["function"]["arguments"]) == {"n": 42}
    assert tc["extra_content"]["google"]["thought_signature"] == prov._ASSINATURA_NEUTRA
    assert msgs[2]["content"] is None
    assert msgs[3] == {"role": "tool", "tool_call_id": "c2_0", "content": "ok"}
    assert corpo["model"] == "google/gemini-3.1-flash-lite" and corpo["temperature"] == 0
    assert corpo["response_format"]["json_schema"]["schema"] == {"type": "object"}


def test_resultado_sem_chamada_vira_texto():
    corpo = VertexProvider(projeto="p").montar_requisicao([{"role": "tool", "tool_name": "x", "content": "r"}])
    assert corpo["messages"][-1] == {"role": "user", "content": "[resultado de x] r"}


def test_chat_le_chamadas_guarda_assinatura_e_reusa(capsys, monkeypatch):
    monkeypatch.setenv("LAUDO_DEMO_PUBLICA", "1")
    pedidos: list = []
    p = _provedor([_resposta(chamadas=[("contar", {"n": 42})], entrada=1000, saida=100), _resposta("feito")], pedidos)
    r = p.chat(HIST[:2])
    assert r.provedor == "vertex" and r.chamadas[0].nome == "contar" and r.chamadas[0].argumentos == {"n": 42}
    assert (r.tokens_entrada, r.tokens_saida) == (1000, 100)
    assert pedidos[0]["messages"][-1]["content"] == "Contei 42."
    p.chat(HIST)
    assert pedidos[1]["messages"][2]["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == "sig-1"
    evento = json.loads(capsys.readouterr().out.splitlines()[0])
    assert evento["laudo_evento"] == "llm" and evento["detalhe"] == "vertex" and evento["tokens"] == 1100
    assert evento["custo_usd"] == pytest.approx((1000 * 0.25 + 100 * 1.50) / 1e6)


def test_evento_so_na_demo_publica(capsys, monkeypatch):
    monkeypatch.delenv("LAUDO_DEMO_PUBLICA", raising=False)
    _provedor([_resposta("oi")], []).chat(HIST[:2])
    assert capsys.readouterr().out == ""


def test_teto_diario_de_tokens():
    p = _provedor([_resposta("oi", entrada=80, saida=30)], [], tokens_dia=100)
    p.chat(HIST[:2])
    with pytest.raises(ErroLLM) as e:
        p.chat(HIST[:2])
    assert e.value.codigo == "LIMITE"


def test_repete_uma_vez_em_5xx_e_desiste():
    pedidos: list = []
    with pytest.raises(ErroLLM) as e:
        _provedor([503, 503], pedidos).chat(HIST[:2])
    assert e.value.codigo == "HTTP" and len(pedidos) == 2
    assert _provedor([429, _resposta("oi")], []).chat(HIST[:2]).conteudo == "oi"


def test_4xx_nao_repete():
    pedidos: list = []
    with pytest.raises(ErroLLM) as e:
        _provedor([400], pedidos).chat(HIST[:2])
    assert e.value.codigo == "HTTP" and len(pedidos) == 1


def test_timeout_deixa_o_vertex_de_fora_por_um_tempo():
    agora = [0.0]
    pedidos: list = []
    p = _provedor([httpx.ReadTimeout("lento"), _resposta("oi")], pedidos, relogio=lambda: agora[0])
    with pytest.raises(ErroLLM) as e:
        p.chat(HIST[:2])
    assert e.value.codigo == "TIMEOUT"
    with pytest.raises(ErroLLM) as e:
        p.chat(HIST[:2])
    assert e.value.codigo == "INDISPONIVEL" and len(pedidos) == 1  # nem foi à rede
    agora[0] = 61.0
    assert p.chat(HIST[:2]).conteudo == "oi"


def test_sem_token_e_fora_da_nuvem_fica_indisponivel(monkeypatch):
    monkeypatch.delenv("LAUDO_VERTEX_TOKEN")

    def tratar(req):
        raise httpx.ConnectError("sem metadata server")

    p = VertexProvider(projeto="p", cliente=httpx.Client(transport=httpx.MockTransport(tratar)))
    with pytest.raises(ErroLLM) as e:
        p.chat(HIST[:2])
    assert e.value.codigo == "INDISPONIVEL"


def test_cadeia_passa_ao_proximo_e_relanca_o_ultimo():
    falha = ProvedorRoteirizado([ErroLLM("REPLAY_AUSENTE", "sem gravação")])
    ok = ProvedorRoteirizado(["resposta"])
    assert ProvedorEmCadeia([falha, ok]).chat(HIST[:2]).conteudo == "resposta"
    a = ProvedorRoteirizado([ErroLLM("REPLAY_AUSENTE", "x")])
    b = ProvedorRoteirizado([ErroLLM("LIMITE", "teto")])
    with pytest.raises(ErroLLM) as e:
        ProvedorEmCadeia([a, b]).chat(HIST[:2])
    assert e.value.codigo == "LIMITE"


def test_cadeia_nao_engole_erro_de_formato():
    a = ProvedorRoteirizado([ErroLLM("FORMATO", "tool call ilegível")])
    b = ProvedorRoteirizado(["nunca"])
    with pytest.raises(ErroLLM) as e:
        ProvedorEmCadeia([a, b]).chat(HIST[:2])
    assert e.value.codigo == "FORMATO" and b.chamadas == []


def test_cadeia_externa_se_algum_for_externo():
    cad = ProvedorEmCadeia([ProvedorRoteirizado([]), VertexProvider(projeto="p")])
    assert cad.externo is True and cad.espera_disjuntor_s is None
    assert ProvedorEmCadeia([ProvedorRoteirizado([])]).externo is False
    with pytest.raises(ValueError):
        ProvedorEmCadeia([])


def test_cadeia_conta_replay_sem_custo(capsys, monkeypatch):
    monkeypatch.setenv("LAUDO_DEMO_PUBLICA", "1")
    gravada = ProvedorRoteirizado([RespostaLLM(conteudo="x", replay=True)])
    ProvedorEmCadeia([gravada]).chat(HIST[:2])
    ev = json.loads(capsys.readouterr().out)
    assert ev["detalhe"] == "replay" and ev["custo_usd"] == 0.0


def test_fabrica():
    assert isinstance(criar_provedor("vertex", projeto="p"), VertexProvider)
