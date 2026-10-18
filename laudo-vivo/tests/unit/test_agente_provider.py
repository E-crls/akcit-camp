"""Provedor de LLM: Ollama (transporte falso), data no prompt, retentativas, gravação e replay; sem GPU."""

import json
from datetime import date

import httpx
import pytest
from pydantic import BaseModel

from laudo.audit import otel
from laudo.llm.provider import (
    MARCADOR_DATA,
    PERFIS,
    ErroLLM,
    Gravador,
    OllamaProvider,
    ProvedorLLM,
    ProvedorRoteirizado,
    ReplayProvider,
    RespostaLLM,
    chamadas_do_texto,
    chave_requisicao,
    criar_provedor,
    injetar_data,
    modelo_do_perfil,
    pedir_json,
)


@pytest.fixture(autouse=True)
def _traces(tmp_path):
    otel.configurar(tmp_path / "traces")


def _resposta_ollama(conteudo="", tool_calls=None, modelo="qwen3.5:4b"):
    return {
        "model": modelo,
        "message": {"role": "assistant", "content": conteudo, "tool_calls": tool_calls or []},
        "done": True,
        "prompt_eval_count": 120,
        "eval_count": 15,
        "load_duration": 2_000_000,
    }


def _prov(handler, **kw) -> OllamaProvider:
    cliente = httpx.Client(transport=httpx.MockTransport(handler))
    return OllamaProvider(cliente=cliente, dormir=lambda s: None, hoje=date(2026, 10, 8), **kw)


MSGS = [
    {"role": "system", "content": "Você é o condutor."},
    {"role": "user", "content": "Contei 40 cabeças."},
]
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "contar_bovinos_video",
            "description": "conta",
            "parameters": {"type": "object", "properties": {}},
        },
    }
]


def test_perfis_e_sobreposicao_por_ambiente(monkeypatch):
    assert modelo_do_perfil("campo") == PERFIS["campo"] == "qwen3.5:4b"
    assert modelo_do_perfil("lote") == "qwen3:14b"
    monkeypatch.setenv("LAUDO_MODELO_ESCRITORIO", "qwen3:14b")
    assert modelo_do_perfil("escritorio") == "qwen3:14b"
    with pytest.raises(ValueError):
        modelo_do_perfil("nuvem")


def test_injecao_da_data_no_sistema():
    m = injetar_data(MSGS, date(2026, 10, 8))
    assert m[0]["content"].startswith(MARCADOR_DATA) and "8 de outubro de 2026" in m[0]["content"]
    assert (
        "quinta-feira" in m[0]["content"] and MSGS[0]["content"] == "Você é o condutor."
    )  # sem efeito colateral
    assert injetar_data(m, date(2026, 10, 8))[0]["content"].count(MARCADOR_DATA) == 1
    sem_sistema = injetar_data([{"role": "user", "content": "oi"}], date(2026, 1, 1))
    assert sem_sistema[0]["role"] == "system" and "2026-01-01" in sem_sistema[0]["content"]


def test_requisicao_tools_format_keep_alive_e_parse():
    vistos = []

    def handler(req: httpx.Request) -> httpx.Response:
        corpo = json.loads(req.content)
        vistos.append(corpo)
        return httpx.Response(
            200,
            json=_resposta_ollama(
                tool_calls=[
                    {"function": {"name": "contar_bovinos_video", "arguments": {"evidencia_id": "ev_1"}}}
                ]
            ),
        )

    p = _prov(handler, perfil="campo", keep_alive=-1)
    r = p.chat(MSGS, ferramentas=TOOLS, formato={"type": "object"})
    corpo = vistos[0]
    assert corpo["model"] == "qwen3.5:4b" and corpo["keep_alive"] == -1 and corpo["think"] is False
    assert corpo["stream"] is False and corpo["tools"] == TOOLS and corpo["format"] == {"type": "object"}
    assert corpo["options"]["temperature"] == 0 and "8 de outubro de 2026" in corpo["messages"][0]["content"]
    assert r.chamadas[0].nome == "contar_bovinos_video" and r.chamadas[0].argumentos == {
        "evidencia_id": "ev_1"
    }
    assert r.tokens_entrada == 120 and r.tokens_saida == 15 and r.carga_ms == 2 and r.span_id
    assert isinstance(p, ProvedorLLM)


def test_retentativa_com_backoff_em_5xx_e_timeout():
    chamadas = {"n": 0}

    def handler(req):
        chamadas["n"] += 1
        if chamadas["n"] < 3:
            return httpx.Response(503, text="carregando")
        return httpx.Response(200, json=_resposta_ollama("ok"))

    esperas = []
    p = _prov(handler)
    p._dormir = esperas.append
    r = p.chat(MSGS)
    assert r.conteudo == "ok" and r.tentativas == 3 and esperas == [1.0, 2.0]

    posts = {"n": 0}

    def lento(req):
        posts["n"] += 1
        raise httpx.ReadTimeout("lento", request=req)

    with pytest.raises(ErroLLM) as e:
        _prov(lento).chat(MSGS)
    # L39: TIMEOUT não é repetido (temperatura 0: quem não respondeu em 120 s não responde na 2ª vez)
    assert e.value.codigo == "TIMEOUT" and not e.value.retryable and posts["n"] == 1


class _OllamaTravado:
    """Ollama que aceita a conexão e não responde: cada POST consome, no relógio virtual, o timeout de leitura
    que o cliente pediu e termina em ReadTimeout (como `dados_locais/auditoria/sim_l39_ollama_travado.py`)."""

    def __init__(self):
        self.t = 0.0
        self.posts = 0
        self.timeouts: list[float] = []
        self.responde = False

    def relogio(self) -> float:
        return self.t

    def dormir(self, s: float) -> None:
        self.t += s

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if not req.url.path.endswith("/api/chat"):
            return httpx.Response(200, json={"version": "x"})
        self.posts += 1
        lido = req.extensions["timeout"]["read"]
        self.timeouts.append(lido)
        if self.responde:
            self.t += 0.5
            return httpx.Response(200, json=_resposta_ollama("ok"))
        self.t += lido
        raise httpx.ReadTimeout("sem resposta", request=req)


def _prov_travado(travado: _OllamaTravado, **kw) -> OllamaProvider:
    return OllamaProvider(cliente=httpx.Client(transport=httpx.MockTransport(travado)), dormir=travado.dormir,
                          relogio=travado.relogio, hoje=date(2026, 10, 16), **kw)


def test_orcamento_do_turno_limita_o_timeout_no_perfil_de_palco(monkeypatch):
    monkeypatch.delenv("LAUDO_ORCAMENTO_TURNO_S", raising=False)
    trav = _OllamaTravado()
    p = _prov_travado(trav, perfil="campo")
    assert p.orcamento_turno_s == 25.0 and p.espera_disjuntor_s == 60.0
    with p.orcamento_do_turno():
        with pytest.raises(ErroLLM) as e:
            p.chat(MSGS)
        assert e.value.codigo == "TIMEOUT" and trav.timeouts == [25.0] and trav.t == 25.0
        with pytest.raises(ErroLLM) as e:  # orçamento esgotado: nem vai ao servidor
            p.chat(MSGS)
        assert "orçamento" in str(e.value) and trav.posts == 1 and trav.t == 25.0
    # fora do turno (ou no escritório) vale o timeout configurado, sem orçamento
    with pytest.raises(ErroLLM):
        p.chat(MSGS)
    assert trav.timeouts[-1] == 120.0
    esc = _prov_travado(_OllamaTravado(), perfil="escritorio")
    assert esc.orcamento_turno_s is None and esc.espera_disjuntor_s is None
    monkeypatch.setenv("LAUDO_ORCAMENTO_TURNO_S", "0")
    assert _prov_travado(_OllamaTravado(), perfil="campo").orcamento_turno_s is None
    monkeypatch.setenv("LAUDO_ORCAMENTO_TURNO_S", "20")
    assert _prov_travado(_OllamaTravado(), perfil="escritorio").orcamento_turno_s == 20.0


def test_orcamento_corta_a_retentativa_de_5xx():
    rel = {"t": 0.0}

    def handler(req):
        rel["t"] += 9.0  # cada 503 demora 9 s
        return httpx.Response(503, text="carregando")

    p = OllamaProvider(cliente=httpx.Client(transport=httpx.MockTransport(handler)), relogio=lambda: rel["t"],
                       dormir=lambda s: rel.__setitem__("t", rel["t"] + s), orcamento_turno_s=20.0,
                       hoje=date(2026, 10, 16))
    with p.orcamento_do_turno(), pytest.raises(ErroLLM) as e:
        p.chat(MSGS)
    # 9 s + 1 s de espera + 9 s = 19 s; a 3ª tentativa (2 s de espera + 9 s) não cabe nos 20 s
    assert e.value.codigo == "HTTP" and rel["t"] == 19.0


def test_erro_4xx_nao_tenta_de_novo():
    chamadas = {"n": 0}

    def handler(req):
        chamadas["n"] += 1
        return httpx.Response(404, json={"error": "model not found"})

    with pytest.raises(ErroLLM) as e:
        _prov(handler).chat(MSGS)
    assert e.value.codigo == "HTTP" and chamadas["n"] == 1


def test_gravacao_e_replay_sem_gpu_em_outro_dia(tmp_path):
    arq = tmp_path / "grav.jsonl"
    p = _prov(lambda req: httpx.Response(200, json=_resposta_ollama("anotado")), gravador=Gravador(arq))
    p.chat(MSGS, ferramentas=TOOLS)
    p.chat([*MSGS[:1], {"role": "user", "content": "meu cpf é 111.222.333-44"}])
    texto = arq.read_text(encoding="utf-8")
    assert "111.222" not in texto and texto.count("\n") == 2
    rep = ReplayProvider(arq)
    r = rep.chat(injetar_data(MSGS, date(2027, 1, 1)), ferramentas=TOOLS)  # outro dia: mesma chave
    assert r.conteudo == "anotado" and r.replay
    assert (
        rep.chat([*MSGS[:1], {"role": "user", "content": "meu cpf é 111.222.333-44"}]).conteudo == "anotado"
    )
    with pytest.raises(ErroLLM) as e:
        rep.chat([{"role": "user", "content": "nunca gravado"}])
    assert e.value.codigo == "REPLAY_AUSENTE"
    seq = ReplayProvider(arq, modo="sequencial")
    assert seq.chat([{"role": "user", "content": "qualquer"}]).conteudo == "anotado"


def test_chave_ignora_data_e_considera_ferramentas():
    a = chave_requisicao(injetar_data(MSGS, date(2026, 10, 8)), TOOLS, None)
    b = chave_requisicao(MSGS, TOOLS, None)
    assert a == b and chave_requisicao(MSGS, None, None) != b


class _Saida(BaseModel):
    valor: int


def test_pedir_json_com_reparo_e_sem_valor_inventado():
    prov = ProvedorRoteirizado(["isto não é json", '```json\n{"valor": 40}\n```'])
    r = pedir_json(prov, MSGS, _Saida, reparos=1)
    assert r.valido and not r.valido_primeira and r.tentativas == 2 and r.objeto.valor == 40
    assert "JSON Schema" in prov.chamadas[1]["mensagens"][-1]["content"]
    ruim = pedir_json(ProvedorRoteirizado(["{}", '{"valor": "quarenta"}']), MSGS, _Saida, reparos=1)
    assert not ruim.valido and ruim.objeto is None
    caiu = pedir_json(ProvedorRoteirizado([ErroLLM("INDISPONIVEL", "fora")]), MSGS, _Saida)
    assert not caiu.valido and "INDISPONIVEL" in caiu.erro


def test_reparo_local_de_tool_call_no_texto():
    t = (
        'Vou contar.<tool_call>{"name": "contar_bovinos_video", "arguments": {"evidencia_id": "ev_9"}}'
        "</tool_call>"
    )
    c = chamadas_do_texto(t)
    assert c[0].nome == "contar_bovinos_video" and c[0].argumentos["evidencia_id"] == "ev_9"
    assert chamadas_do_texto('{"name": "geofence", "arguments": "{\\"x\\": 1}"}')[0].argumentos == {"x": 1}
    assert chamadas_do_texto("só texto") == []


def test_fabrica_e_bedrock_como_ponto_de_extensao(tmp_path):
    assert isinstance(criar_provedor("ollama", perfil="lote"), OllamaProvider)
    with pytest.raises(NotImplementedError):
        criar_provedor("bedrock")
    r = ProvedorRoteirizado([RespostaLLM(conteudo="x")]).chat(MSGS)
    assert r.provedor == "roteiro"


def test_mesma_janela_de_contexto_no_condutor_no_vlm_e_no_aquecimento(monkeypatch):
    """Um num_ctx diferente entre condutor, leitores de foto e aquecimento faz o Ollama recarregar o modelo
    (15-20 s) no meio do turno; no palco, isso estoura o orçamento e o turno cai no plano mínimo (16/10)."""
    import inspect

    from laudo.api import servico
    from laudo.llm import provider
    from laudo.tools import leitura_documentos
    from laudo.vision import vlm

    assert provider.OPCOES_PADRAO["num_ctx"] == provider.NUM_CTX >= 16384
    for mod in (vlm, leitura_documentos):
        fonte = inspect.getsource(mod)
        assert '"num_ctx": NUM_CTX' in fonte and '"num_ctx": 8192' not in fonte, mod.__name__
    assert '"options": dict(getattr(self.provedor, "opcoes", {}))' in inspect.getsource(servico.Servico.aquecer_llm)


def test_prompt_cortado_pelo_ollama_vira_aviso_e_atributo_do_trace(capsys):
    """O Ollama não falha quando o prompt passa de num_ctx: corta para (num_ctx - 4) // 2 + 4 tokens e responde."""
    from laudo.llm.provider import NUM_CTX, assinatura_corte

    assert assinatura_corte(8192) == 4098 and assinatura_corte(16384) == 8194  # 4098 medido no Ollama 0.32.4

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={**_resposta_ollama("ok"), "prompt_eval_count": assinatura_corte(NUM_CTX)})

    _prov(handler).chat(MSGS)
    assert "cortou o prompt" in capsys.readouterr().err

    def handler_ok(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_resposta_ollama("ok"))

    _prov(handler_ok).chat(MSGS)
    assert "cortou o prompt" not in capsys.readouterr().err
