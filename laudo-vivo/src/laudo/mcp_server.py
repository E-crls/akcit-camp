"""Servidor MCP mínimo do Laudo Vivo: as ferramentas do `REGISTRO` (Sicor/Fiscal-GO, regras do MCR 2-7,
NDVI, foto, geofence, contagem, NF-e, GTA, laudo) para qualquer cliente MCP.

Transporte stdio: uma mensagem JSON-RPC 2.0 por linha (UTF-8) na entrada padrão; respostas na saída padrão;
log na saída de erro. Métodos: `initialize`, `notifications/initialized`, `ping`, `tools/list` e `tools/call`.
Sem dependência externa (só biblioteca padrão + o próprio pacote).

- `tools/list` publica nome, descrição e `inputSchema` (o JSON Schema do modelo Pydantic de entrada) de cada
  ferramenta, com a anotação `readOnlyHint` (falso para as que gravam estado: rascunho do laudo, ocorrência,
  índice de fotos).
- `tools/call` valida os argumentos com o mesmo Pydantic e devolve o `Envelope` da ferramenta em
  `structuredContent` e como texto JSON em `content`; `isError` = `not envelope.ok`. Ferramenta
  inexistente vira erro JSON-RPC -32602; argumento inválido vira resultado com `isError` e a mensagem de
  validação.
- A política, o verificador e a assinatura humana do agente NÃO passam por aqui: o servidor expõe as
  ferramentas determinísticas; quem orquestra a fiscalização continua sendo o condutor.

Uso:
  scripts/py.sh -m laudo.mcp_server                            # todas as ferramentas
  scripts/py.sh -m laudo.mcp_server --somente-leitura          # sem as que gravam estado
  scripts/py.sh -m laudo.mcp_server --ferramentas carregar_operacao,triar_carteira,explicar_regra

Configuração num cliente MCP (ex.: arquivo `mcp.json`):
  {"mcpServers": {"laudo-vivo": {"command": "scripts/py.sh", "args": ["-m", "laudo.mcp_server"]}}}
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import sys
from collections.abc import Iterable
from typing import IO, Any

from pydantic import ValidationError

from laudo.contracts import Ferramenta

VERSAO_SERVIDOR = "0.1.0"
PROTOCOLOS = ("2025-06-18", "2025-03-26", "2024-11-05")  # o primeiro é o preferido
MUTAVEIS = {"emitir_rascunho", "registrar_ocorrencia", "integridade_foto"}  # gravam estado ou índice

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = (
    -32700,
    -32600,
    -32601,
    -32602,
    -32603,
)

log = logging.getLogger("laudo.mcp")


def _erro(id_: Any, codigo: int, msg: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": codigo, "message": msg}}


def _ok(id_: Any, resultado: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "result": resultado}


class ServidorMCP:
    def __init__(
        self,
        registro: dict[str, Ferramenta] | None = None,
        permitidas: Iterable[str] | None = None,
        somente_leitura: bool = False,
    ):
        if registro is None:
            from laudo.tools import carregar_todas

            registro = dict(carregar_todas())
        nomes = set(permitidas) if permitidas else set(registro)
        if somente_leitura:
            nomes -= MUTAVEIS
        self.ferramentas = {n: f for n, f in sorted(registro.items()) if n in nomes}
        self.iniciado = False

    # -- métodos ---------------------------------------------------------------------
    def _initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        pedido = params.get("protocolVersion")
        versao = pedido if pedido in PROTOCOLOS else PROTOCOLOS[0]
        self.iniciado = True
        return {
            "protocolVersion": versao,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {
                "name": "laudo-vivo",
                "title": "Laudo Vivo — ferramentas de fiscalização de crédito rural",
                "version": VERSAO_SERVIDOR,
            },
            "instructions": (
                "Ferramentas determinísticas do Laudo Vivo. Elas calculam e conferem; não decidem status "
                "final de "
                "laudo nem assinam. Prioridade de verificação não é indício de irregularidade."
            ),
        }

    def _tools_list(self) -> dict[str, Any]:
        return {
            "tools": [
                {
                    "name": f.nome,
                    "description": f.descricao,
                    "inputSchema": f.entrada.model_json_schema(),
                    "annotations": {
                        "readOnlyHint": f.nome not in MUTAVEIS,
                        "openWorldHint": f.nome == "serie_ndvi",
                    },
                }
                for f in self.ferramentas.values()
            ]
        }

    def _tools_call(self, id_: Any, params: dict[str, Any]) -> dict[str, Any]:
        nome = params.get("name")
        ferr = self.ferramentas.get(str(nome))
        if ferr is None:
            return _erro(id_, INVALID_PARAMS, f"ferramenta desconhecida: {nome}")
        try:
            args = ferr.entrada.model_validate(params.get("arguments") or {})
        except ValidationError as e:
            msg = "; ".join(f"{'.'.join(map(str, x['loc'])) or 'entrada'}: {x['msg']}" for x in e.errors())
            return _ok(
                id_, {"content": [{"type": "text", "text": f"argumentos inválidos: {msg}"}], "isError": True}
            )
        try:
            with contextlib.redirect_stdout(sys.stderr):  # nada de print de ferramenta no canal JSON-RPC
                env = ferr.funcao(args)
        except Exception as e:
            log.exception("ferramenta %s lançou exceção", nome)
            return _ok(
                id_,
                {"content": [{"type": "text", "text": f"ERRO_INTERNO: {type(e).__name__}"}], "isError": True},
            )
        dados = env.model_dump(mode="json")
        return _ok(
            id_,
            {
                "content": [{"type": "text", "text": json.dumps(dados, ensure_ascii=False, default=str)}],
                "structuredContent": dados,
                "isError": not env.ok,
            },
        )

    # -- despacho --------------------------------------------------------------------
    def processar(self, msg: Any) -> dict[str, Any] | list[dict[str, Any]] | None:
        """Uma mensagem JSON-RPC (já decodificada) → resposta, ou None para notificação."""
        if isinstance(msg, list):  # lote (JSON-RPC 2.0; protocolo MCP 2025-03-26)
            respostas = [r for m in msg if (r := self.processar(m)) is not None]
            return respostas or None  # type: ignore[return-value]
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
            return _erro(
                msg.get("id") if isinstance(msg, dict) else None, INVALID_REQUEST, "requisição inválida"
            )
        metodo, id_ = msg["method"], msg.get("id")
        params = msg.get("params") or {}
        notificacao = "id" not in msg
        if metodo.startswith("notifications/"):
            return None
        if notificacao:
            return None
        if not isinstance(params, dict):
            return _erro(id_, INVALID_PARAMS, "params deve ser um objeto")
        if metodo == "initialize":
            return _ok(id_, self._initialize(params))
        if metodo == "ping":
            return _ok(id_, {})
        if metodo == "tools/list":
            return _ok(id_, self._tools_list())
        if metodo == "tools/call":
            return self._tools_call(id_, params)
        return _erro(id_, METHOD_NOT_FOUND, f"método não suportado: {metodo}")

    def processar_linha(self, linha: str) -> str | None:
        linha = linha.strip()
        if not linha:
            return None
        try:
            msg = json.loads(linha)
        except json.JSONDecodeError as e:
            return json.dumps(_erro(None, PARSE_ERROR, f"JSON inválido: {e.msg}"), ensure_ascii=False)
        try:
            resp = self.processar(msg)
        except Exception as e:
            log.exception("erro ao processar mensagem")
            resp = _erro(msg.get("id") if isinstance(msg, dict) else None, INTERNAL_ERROR, type(e).__name__)
        return None if resp is None else json.dumps(resp, ensure_ascii=False, default=str)

    def rodar(self, entrada: IO[str] | None = None, saida: IO[str] | None = None) -> None:
        entrada = entrada or sys.stdin
        saida = saida or sys.stdout
        for linha in entrada:
            resp = self.processar_linha(linha)
            if resp is not None:
                saida.write(resp + "\n")
                saida.flush()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Servidor MCP (stdio) das ferramentas do Laudo Vivo.")
    ap.add_argument("--ferramentas", help="lista separada por vírgula (padrão: todas)")
    ap.add_argument("--somente-leitura", action="store_true", help="sem ferramentas que gravam estado")
    a = ap.parse_args(argv)
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    for fluxo in (sys.stdin, sys.stdout):
        with contextlib.suppress(AttributeError, ValueError):
            fluxo.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    permitidas = [x.strip() for x in a.ferramentas.split(",") if x.strip()] if a.ferramentas else None
    with contextlib.redirect_stdout(sys.stderr):  # importar ferramentas não pode sujar o canal
        servidor = ServidorMCP(permitidas=permitidas, somente_leitura=a.somente_leitura)
    servidor.rodar(saida=sys.__stdout__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
