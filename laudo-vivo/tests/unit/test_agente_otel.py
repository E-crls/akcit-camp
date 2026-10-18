"""Tracing OTel em JSONL: um arquivo por fiscalização, hash dos argumentos, decisão de política."""

import json

from laudo.audit import otel
from laudo.contracts import hash_entrada


def _linhas(p):
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]


def test_spans_por_fiscalizacao_com_hierarquia(tmp_path):
    d = otel.configurar(tmp_path)
    with otel.contexto_fiscalizacao("fis_a"), otel.span("agente.turno") as pai:
        args = {"caminho": "/x/video.mp4", "item_id": "bov1"}
        with otel.span_ferramenta("contar_bovinos_video", args) as s:
            otel.definir(s, **{"tool.ok": True, "tool.lista": [1, 2]})
        sid = otel.registrar_decisao("POL-07", "negar+registrar_ocorrencia", "fala", "pressão")
        with otel.span_llm("ollama", "qwen3.5:4b", **{"gen_ai.usage.input_tokens": 10}):
            pass
    with otel.span("sem_fiscalizacao"):
        pass
    spans = _linhas(d / "fis_a.jsonl")
    nomes = [s["name"] for s in spans]
    assert nomes == ["tool contar_bovinos_video", "policy.decision", "gen_ai.chat qwen3.5:4b", "agente.turno"]
    tool = spans[0]
    assert tool["attributes"]["tool.args_hash"] == hash_entrada(args) and "/x/video.mp4" not in json.dumps(
        tool
    )
    assert tool["parent_span_id"] == otel.id_span(pai) and tool["attributes"]["tool.lista"] == "[1, 2]"
    pol = spans[1]
    assert pol["span_id"] == sid and pol["attributes"]["policy.rule_id"] == "POL-07"
    assert spans[2]["attributes"]["gen_ai.request.model"] == "qwen3.5:4b"
    assert all(s["attributes"]["laudo.fiscalizacao_id"] == "fis_a" for s in spans)
    assert _linhas(d / "geral.jsonl")[0]["name"] == "sem_fiscalizacao"
    assert otel.arquivo_trace("fis_a") == d / "fis_a.jsonl"


def test_atributos_de_versao_nao_sao_mascarados_e_o_resto_e(tmp_path):
    """L28: `tool.fonte_versao` = `mcr_2_7@0.3.0` aparecia como "[EMAIL]" no trace (92 vezes na demo)."""
    d = otel.configurar(tmp_path)
    with otel.contexto_fiscalizacao("fis_v"), otel.span("tool x") as s:
        otel.definir(
            s,
            **{
                "tool.fonte_versao": "mcr_2_7@0.3.0+contador@0.2.0",
                "laudo.prompt.versao": "condutor.v3@1a2b3c4d",
                "rulebook_versao": "mcr_2_7@0.3.0",
                "tool.resumo": "contato beltrano.teste@exemplo.invalid, tel (62) 99999-0000",
            },
        )
    a = _linhas(d / "fis_v.jsonl")[0]["attributes"]
    assert a["tool.fonte_versao"] == "mcr_2_7@0.3.0+contador@0.2.0"
    assert a["laudo.prompt.versao"] == "condutor.v3@1a2b3c4d" and a["rulebook_versao"] == "mcr_2_7@0.3.0"
    assert a["tool.resumo"] == "contato [EMAIL], tel [TELEFONE]"
    assert otel.eh_atributo_de_versao("service.version") and not otel.eh_atributo_de_versao("tool.resumo")


def test_identificadores_tecnicos_nao_viram_telefone_nem_cnpj():
    """L28: hex gerado pelo código com 11 ou 14 dígitos seguidos virava "[TELEFONE]"/"[CNPJ]" no trace
    (`"tool.envelope_trace_id": "[TELEFONE]c48ba"` numa demo; ~0,1% dos span_id, ~0,5% dos sha256), e o link
    do laudo para o span quebrava. Valor só de dígitos (CPF, CNPJ, chave de acesso) segue mascarado."""
    from laudo.agent.pii import CPF, mascarar
    from laudo.docs_fiscais.sintetico import cpf_sintetico

    span_id, sha = "000f38948446529b", "bb487e7a2ca6a35aa818ef3d1e1dffcc54dc4b89944610679d38712820710af5"
    assert mascarar(span_id) != span_id and mascarar(sha) != sha  # o problema: a máscara pega hex
    d = {
        "name": "tool x", "trace_id": "cffefda85925169218b92f97b5c9a6ea", "span_id": span_id,
        "parent_span_id": "ec65167524344207", "status_msg": "falhou para o tel (62) 99999-0000",
        "attributes": {
            "tool.envelope_trace_id": "17848277589d4c48ba", "tool.args_hash": sha, "llm.chave": sha,
            "laudo.fiscalizacao_id": "fis_0b2d10e1d1",
            # só dígitos (forma de CPF, CNPJ ou chave de acesso) numa chave técnica: mascara mesmo assim
            "x.chave": cpf_sintetico(191),
            "tool.resumo": f"hash {sha} de beltrano.teste@exemplo.invalid",
            # atributo de versão com texto que não é versão: mascarado
            "tool.fonte_versao": "contato fulano.teste@exemplo.invalid",
        },
    }
    m = otel.mascarar_span(d)
    assert m["trace_id"] == d["trace_id"] and m["span_id"] == span_id
    assert m["parent_span_id"] == "ec65167524344207"
    a = m["attributes"]
    assert a["tool.envelope_trace_id"] == "17848277589d4c48ba"
    assert a["tool.args_hash"] == sha == a["llm.chave"]
    assert a["laudo.fiscalizacao_id"] == "fis_0b2d10e1d1"
    assert a["x.chave"] == CPF
    assert "[EMAIL]" in a["tool.resumo"] and "[EMAIL]" in a["tool.fonte_versao"]
    assert m["status_msg"] == "falhou para o tel [TELEFONE]"
    assert otel.eh_id_tecnico("span_id", span_id) and not otel.eh_id_tecnico("tool.resumo", span_id)
    assert not otel.eh_id_tecnico("llm.chave", cpf_sintetico(191))  # só dígitos: não é id técnico
