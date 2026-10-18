"""Custo por fiscalização medido no trace: tokens do Ollama por chamada no span e soma por fiscalização."""

from __future__ import annotations

import json

import httpx

from laudo.audit import custo, otel
from laudo.llm.provider import OllamaProvider, ReplayProvider, RespostaLLM


def _ollama_falso(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "qwen3.5:4b",
            "message": {"role": "assistant", "content": "ok"},
            "prompt_eval_count": 4000,
            "eval_count": 50,
            "load_duration": 2_000_000,
            "prompt_eval_duration": 300_000_000,
            "eval_duration": 700_000_000,
        },
    )


def test_span_do_ollama_grava_tokens_e_tempos_de_gpu(tmp_path):
    otel.configurar(tmp_path)
    prov = OllamaProvider(cliente=httpx.Client(transport=httpx.MockTransport(_ollama_falso)), retentativas=0)
    with otel.contexto_fiscalizacao("fis_custo"):
        r = prov.chat([{"role": "user", "content": "oi"}])
    assert (r.tokens_entrada, r.tokens_saida, r.prompt_ms, r.geracao_ms) == (4000, 50, 300, 700)
    span = json.loads((tmp_path / "fis_custo.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    a = span["attributes"]
    assert a["gen_ai.usage.input_tokens"] == 4000 and a["gen_ai.usage.output_tokens"] == 50
    assert a["llm.prompt_eval_ms"] == 300 and a["llm.eval_ms"] == 700 and a["llm.uso_origem"] == "medido"


def test_replay_repete_no_span_o_uso_da_gravacao(tmp_path):
    otel.configurar(tmp_path / "traces")
    grav = tmp_path / "g.jsonl"
    resp = RespostaLLM(
        conteudo="x", modelo="qwen3.5:4b", tokens_entrada=1000, tokens_saida=10, latencia_ms=900
    )
    grav.write_text(
        json.dumps({"chave": "k", "tipo": "chat", "resposta": resp.model_dump(mode="json")}) + "\n",
        encoding="utf-8",
    )
    prov = ReplayProvider(grav, modo="sequencial")
    with otel.contexto_fiscalizacao("fis_rep"):
        prov.chat([{"role": "user", "content": "qualquer"}])
    usos = custo.somar(custo.ler_spans([tmp_path / "traces" / "fis_rep.jsonl"]))
    u = usos["fis_rep"]
    assert (u.tokens_entrada, u.tokens_saida, u.llm_ms, u.origem_uso) == (1000, 10, 900, {"gravacao"})


def test_soma_por_fiscalizacao_e_estimativa_com_precos_citados():
    spans = [
        {"name": "agente.turno", "attributes": {"laudo.fiscalizacao_id": "fis_x"}},
        {
            "name": "gen_ai.chat qwen3.5:4b",
            "duration_ms": 1200,
            "attributes": {
                "laudo.fiscalizacao_id": "fis_x",
                "gen_ai.operation.name": "chat",
                "gen_ai.request.model": "qwen3.5:4b",
                "gen_ai.usage.input_tokens": 1_000_000,
                "gen_ai.usage.output_tokens": 100_000,
                "llm.latency_ms": 1000,
                "llm.prompt_eval_ms": 600,
                "llm.eval_ms": 300,
                "llm.uso_origem": "medido",
            },
        },
        {
            "name": "tool contar_bovinos_video",
            "duration_ms": 9000,
            "attributes": {"laudo.fiscalizacao_id": "fis_x", "tool.name": "contar_bovinos_video"},
        },
        {
            "name": "gen_ai.chat qwen3.5:4b",
            "attributes": {"laudo.fiscalizacao_id": "fis_y", "gen_ai.usage.input_tokens": 5},
        },
    ]
    usos = custo.somar(spans)
    x = usos["fis_x"]
    assert (x.turnos, x.chamadas_llm, x.tokens_entrada, x.tokens_saida, x.gpu_ms) == (
        1,
        1,
        1_000_000,
        100_000,
        900,
    )
    assert x.ferramentas == {"contar_bovinos_video": [1, 9000]} and usos["fis_y"].tokens_entrada == 5
    est = custo.estimar(x, cambio=5.0, potencia_gpu_w=3600, potencia_cpu_w=0, tarifa_kwh_rs=1.0)
    nano = next(n for n in est["nuvem_equivalente"] if n["modelo"] == "gpt-5-nano")
    assert nano["usd"] == round(1 * 0.05 + 0.1 * 0.40, 5) and nano["rs"] == round(nano["usd"] * 5.0, 4)
    assert all("consultado em" in n["fonte"] for n in est["nuvem_equivalente"])
    assert est["energia_local"]["kwh"] == round(0.9 * 3600 / 3600 / 1000, 6)  # 0,9 s de GPU a 3,6 kW
    md = custo.relatorio_md(est)
    assert "1.000.000 de entrada" in md and "gpt-4.1-mini" in md and "estimativas" in md


def test_script_custo_le_trace(tmp_path, capsys):
    import importlib.util
    from pathlib import Path

    tr = tmp_path / "fis_z.jsonl"
    tr.write_text(
        json.dumps(
            {
                "name": "gen_ai.chat m",
                "attributes": {
                    "laudo.fiscalizacao_id": "fis_z",
                    "gen_ai.usage.input_tokens": 10,
                    "gen_ai.usage.output_tokens": 2,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    spec = importlib.util.spec_from_file_location(
        "custo_fiscalizacao", Path(__file__).resolve().parents[2] / "scripts" / "custo_fiscalizacao.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main([str(tr), "--json"]) == 0
    saida = json.loads(capsys.readouterr().out)
    assert saida[0]["uso"]["tokens_entrada"] == 10
