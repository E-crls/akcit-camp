"""Servidor MCP mínimo (stdio, JSON-RPC 2.0) sobre o REGISTRO de ferramentas."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

from laudo.contracts import CodigoErro, Envelope, Ferramenta
from laudo.mcp_server import INVALID_PARAMS, METHOD_NOT_FOUND, PARSE_ERROR, ServidorMCP


class EntradaSoma(BaseModel):
    a: int
    b: int


def _soma(args: EntradaSoma) -> Envelope:
    print("isto não pode ir para o canal JSON-RPC")
    if args.a < 0:
        return Envelope.falha("soma", CodigoErro.ENTRADA_INVALIDA, "a negativo")
    return Envelope.sucesso("soma", {"status": "ok", "total": args.a + args.b})


QUADRADO = "POLYGON ((-49.001 -15.001, -48.999 -15.001, -48.999 -14.999, -49.001 -14.999, -49.001 -15.001))"

REG = {
    "soma": Ferramenta(nome="soma", descricao="soma dois inteiros", entrada=EntradaSoma, funcao=_soma),
    "emitir_rascunho": Ferramenta(nome="emitir_rascunho", descricao="x", entrada=EntradaSoma, funcao=_soma),
}


def _req(metodo, params=None, id_=1):
    m = {"jsonrpc": "2.0", "id": id_, "method": metodo}
    if params is not None:
        m["params"] = params
    return m


def test_mcp_initialize_negocia_versao_e_anuncia_ferramentas():
    s = ServidorMCP(REG)
    r = s.processar(
        _req(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            },
        )
    )
    assert r["result"]["protocolVersion"] == "2025-03-26"
    assert r["result"]["capabilities"] == {"tools": {"listChanged": False}}
    assert r["result"]["serverInfo"]["name"] == "laudo-vivo"
    desconhecida = s.processar(_req("initialize", {"protocolVersion": "1999-01-01"}))
    assert desconhecida["result"]["protocolVersion"] == "2025-06-18"
    assert s.processar({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_mcp_tools_list_tem_schema_pydantic_e_anotacao():
    s = ServidorMCP(REG)
    tools = {t["name"]: t for t in s.processar(_req("tools/list"))["result"]["tools"]}
    assert tools["soma"]["inputSchema"]["required"] == ["a", "b"]
    assert tools["soma"]["annotations"]["readOnlyHint"] is True
    assert tools["emitir_rascunho"]["annotations"]["readOnlyHint"] is False
    assert "emitir_rascunho" not in {
        t["name"] for t in ServidorMCP(REG, somente_leitura=True)._tools_list()["tools"]
    }


def test_mcp_tools_call_devolve_envelope_e_erros(capsys):
    s = ServidorMCP(REG)
    r = s.processar(_req("tools/call", {"name": "soma", "arguments": {"a": 2, "b": 3}}))["result"]
    assert r["isError"] is False and r["structuredContent"]["data"]["total"] == 5
    assert json.loads(r["content"][0]["text"])["data"]["total"] == 5
    falha = s.processar(_req("tools/call", {"name": "soma", "arguments": {"a": -1, "b": 3}}))["result"]
    assert falha["isError"] is True and falha["structuredContent"]["error"]["code"] == "ENTRADA_INVALIDA"
    invalido = s.processar(_req("tools/call", {"name": "soma", "arguments": {"a": "x"}}))["result"]
    assert invalido["isError"] is True and "argumentos inválidos" in invalido["content"][0]["text"]
    assert s.processar(_req("tools/call", {"name": "nao_existe"}))["error"]["code"] == INVALID_PARAMS
    assert s.processar(_req("resources/list"))["error"]["code"] == METHOD_NOT_FOUND
    assert json.loads(s.processar_linha("{quebrado"))["error"]["code"] == PARSE_ERROR
    assert s.processar(_req("ping"))["result"] == {}


def test_mcp_stdio_nao_mistura_print_da_ferramenta_com_jsonrpc():
    s = ServidorMCP(REG)
    entrada = io.StringIO(
        "\n".join(
            json.dumps(m)
            for m in [
                _req("initialize", {"protocolVersion": "2025-06-18"}, 1),
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                _req("tools/call", {"name": "soma", "arguments": {"a": 1, "b": 1}}, 2),
            ]
        )
        + "\n"
    )
    saida = io.StringIO()
    s.rodar(entrada, saida)
    linhas = [json.loads(x) for x in saida.getvalue().splitlines()]
    assert [x["id"] for x in linhas] == [1, 2]
    assert linhas[1]["result"]["structuredContent"]["data"]["total"] == 2


def test_mcp_registro_real_expoe_ferramentas_do_laudo():
    s = ServidorMCP()
    nomes = {t["name"] for t in s._tools_list()["tools"]}
    assert {"carregar_operacao", "planejar_metodo", "avaliar_regras", "geofence", "emitir_rascunho"} <= nomes
    r = s.processar(
        _req(
            "tools/call",
            {
                "name": "geofence",
                "arguments": {
                    "lat": -15.0,
                    "lon": -49.0,
                    "precisao_m": 5,
                    "glebas_wkt": [QUADRADO],
                },
            },
        )
    )["result"]
    assert r["isError"] is False and r["structuredContent"]["data"]["posicao"] == "dentro"


@pytest.mark.skipif(sys.platform != "win32" and not os.environ.get("CI"), reason="smoke de processo")
def test_mcp_processo_stdio_responde_initialize():
    raiz = Path(__file__).resolve().parents[2]
    env = dict(os.environ, PYTHONPATH=str(raiz / "src"), PYTHONUTF8="1")
    entrada = (
        json.dumps(_req("initialize", {"protocolVersion": "2025-06-18"}))
        + "\n"
        + json.dumps(_req("tools/list", id_=2))
        + "\n"
    )
    p = subprocess.run(
        [sys.executable, "-m", "laudo.mcp_server", "--ferramentas", "explicar_regra,geofence"],
        input=entrada,
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        env=env,
        timeout=120,
    )
    linhas = [json.loads(x) for x in p.stdout.splitlines() if x.strip()]
    assert [x["id"] for x in linhas] == [1, 2], p.stderr[-2000:]
    assert {t["name"] for t in linhas[1]["result"]["tools"]} == {"explicar_regra", "geofence"}
