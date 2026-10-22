"""API do Laudo Vivo (FastAPI) e servidor da interface web (`apps/web/`).

Rotas (todas sob `/api`):

| Método | Rota | Faz |
|---|---|---|
| GET | `/saude` | modo do LLM, ferramentas (falsas/mistas/reais), ASR, casos de demo |
| GET | `/carteira` | `triar_carteira` (Fiscal-GO 2026) com glebas simplificadas para o mapa |
| GET | `/mapa/contorno-go` | contorno de Goiás (IBGE) para o mapa sem internet |
| GET/POST | `/fiscalizacoes` | lista / cria (`{"ref_bacen"}` ou `{"caso", "reiniciar"}`) |
| GET | `/fiscalizacoes/{id}` | estado para a tela: matriz de itens, evidências, provas, governança, laudo |
| POST | `/fiscalizacoes/{id}/turno` | fala digitada (`{"texto"}`) |
| POST | `/fiscalizacoes/{id}/turno-audio` | áudio → ASR → números → turno (ou pedido de confirmação) |
| POST | `/fiscalizacoes/{id}/confirmar` | confirma/corrige/descarta a fala com número crítico |
| POST | `/fiscalizacoes/{id}/evidencias` | upload (vídeo, foto, NF-e XML, GTA) com GPS do navegador |
| POST | `/fiscalizacoes/{id}/evidencias/caso` | usa uma evidência pronta do caso de demo |
| POST | `/fiscalizacoes/{id}/roteiro/proximo` | próximo passo do roteiro (apresentação/contingência) |
| POST | `/fiscalizacoes/{id}/roteiro/pular` | avança o roteiro sem executar o passo ("Pular passo") |
| POST | `/fiscalizacoes/{id}/rascunho` | pedido humano de rascunho (pode voltar BLOQUEADO_POLITICA) |
| POST | `/fiscalizacoes/{id}/assinar` | assinatura humana: PIN + hash raiz conferido |
| GET | `/fiscalizacoes/{id}/laudo`, `/laudo.html` | laudo JSON / HTML (links item → evidência → trace) |
| POST | `/fiscalizacoes/{id}/pacote` | pacote de exibição BCB/Justiça (só SELADO; ação humana, sem LLM) |
| GET | `/fiscalizacoes/{id}/pacote.zip` | ZIP do pacote (manifest sha256, GeoJSON, cenas, checklist…) |
| GET | `/fiscalizacoes/{id}/trace` | trace OpenTelemetry (JSONL; `?span_id=` devolve o span e vizinhos) |
| GET | `/fiscalizacoes/{id}/evidencias/{ev}/arquivo` · `/trecho` | arquivo / trecho da NF-e ou GTA |
| GET | `/fiscalizacoes/{id}/checagens/{chk}/quadros/{i}` | quadro-chave anotado da contagem |
| POST | `/voz/aquecer` · `/llm/aquecer` | carrega o Whisper / o modelo do Ollama antes da demo |

Limites de tamanho: o corpo de cada requisição é conferido enquanto chega (Content-Length declarado e
bytes recebidos): upload de evidência até o maior limite por tipo (`servico.LIMITE_UPLOAD_MB`, o vídeo) mais a
folga do multipart, áudio até `servico.LIMITE_AUDIO_MB`, demais rotas até 1 MiB; acima disso, 413 antes de ler
o resto.

Uso: `scripts/py.sh -m laudo.api --llm ollama --ferramentas mistas` (ver `scripts/rodar_demo.sh`).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from laudo.api.servico import LIMITE_AUDIO_MB, LIMITE_UPLOAD_MB, Config, ErroServico, Servico, checar_id

log = logging.getLogger("laudo.api")

_MIME = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".xml": "application/xml",
    ".json": "application/json",
    ".pdf": "application/pdf",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
    ".html": "text/plain",
    ".zip": "application/zip",
}


MIB = 1024 * 1024
FOLGA_MULTIPART = MIB  # cabeçalhos do multipart e campos de formulário (GPS, item, comentário)
LIMITE_PADRAO = MIB  # JSON das demais rotas (fala de até 2.000 caracteres, campos do residual)


def limite_corpo(caminho: str) -> int:
    """Maior corpo aceito pela rota (bytes)."""
    if caminho.endswith("/evidencias"):
        return max(LIMITE_UPLOAD_MB.values()) * MIB + FOLGA_MULTIPART
    if caminho.endswith("/turno-audio"):
        return LIMITE_AUDIO_MB * MIB + FOLGA_MULTIPART
    return LIMITE_PADRAO


class CorpoGrande(StarletteHTTPException):
    """Corpo acima do limite, percebido enquanto chega: o FastAPI repassa HTTPException da leitura do corpo
    (outra exceção ali vira 400 "erro ao ler o corpo")."""

    def __init__(self, limite: int):
        super().__init__(status_code=413, detail=f"requisição acima do limite de {limite // MIB} MB")


class LimiteCorpo:
    """Middleware ASGI que recusa (413) corpo acima do limite da rota: pelo Content-Length declarado, antes de
    ler, e pelos bytes que chegam (corpo sem Content-Length ou maior que o declarado)."""

    def __init__(self, app, limite=limite_corpo):
        self.app, self.limite = app, limite

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") not in ("POST", "PUT", "PATCH"):
            await self.app(scope, receive, send)
            return
        limite = self.limite(scope.get("path") or "")
        declarado = dict(scope.get("headers") or []).get(b"content-length")
        if declarado is not None and declarado.isdigit() and int(declarado) > limite:
            await _responder_413(send, limite)
            return
        recebido, iniciou = 0, False

        async def receber():
            nonlocal recebido
            msg = await receive()
            if msg.get("type") == "http.request":
                recebido += len(msg.get("body") or b"")
                if recebido > limite:
                    raise CorpoGrande(limite)
            return msg

        async def enviar(msg):
            nonlocal iniciou
            iniciou = iniciou or msg.get("type") == "http.response.start"
            await send(msg)

        try:
            await self.app(scope, receber, enviar)
        except CorpoGrande:
            if not iniciou:
                await _responder_413(send, limite)


async def _responder_413(send, limite: int) -> None:
    corpo = JSONResponse({"erro": f"requisição acima do limite de {limite // MIB} MB"}, status_code=413).body
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(corpo)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": corpo})


class CriarFiscalizacao(BaseModel):
    ref_bacen: str | None = None
    caso: str | None = None
    reiniciar: bool = True
    nova: bool = False


class Turno(BaseModel):
    texto: str = Field("", max_length=2000)
    # campos que a foto do DANFE/GTA não validou, digitados no formulário do pedido (campo → valor)
    residual: dict[str, str] | None = Field(None, max_length=40)

    @model_validator(mode="after")
    def _nao_vazio(self):
        if not self.texto.strip() and not any(str(v).strip() for v in (self.residual or {}).values()):
            raise ValueError("turno vazio: envie texto ou os campos pedidos")
        return self


class Confirmacao(BaseModel):
    aceitar: bool = True
    texto: str | None = Field(default=None, max_length=2000)


class EvidenciaCaso(BaseModel):
    nome: str
    texto: str = ""


class Assinatura(BaseModel):
    pin: str = Field(min_length=1, max_length=12)
    hash_confirmado: str = Field(min_length=16, max_length=128)
    papel: str = "fiscal"
    nome_ref: str = "fiscal-demo"


def criar_app(cfg: Config | None = None, transcritor: Any | None = None) -> FastAPI:
    cfg = cfg or Config()
    srv = Servico(cfg, transcritor=transcritor)
    app = FastAPI(title="Laudo Vivo", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.servico = srv
    app.add_middleware(LimiteCorpo)

    @app.exception_handler(CorpoGrande)
    async def _corpo_grande(_: Request, e: CorpoGrande):
        return JSONResponse({"erro": e.detail}, status_code=413)

    @app.exception_handler(ErroServico)
    async def _erro(_: Request, e: ErroServico):
        return JSONResponse({"erro": e.msg}, status_code=e.status)

    @app.middleware("http")
    async def _cabecalhos(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.url.path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")
        else:
            resp.headers.setdefault("Cache-Control", "no-cache")
        # microfone, câmera e GPS só para a própria origem
        resp.headers.setdefault("Permissions-Policy", "microphone=(self), camera=(self), geolocation=(self)")
        return resp

    # -- saúde, carteira, mapa ------------------------------------------------------------
    @app.get("/api/saude")
    def saude():
        return srv.saude()

    @app.get("/api/carteira")
    def carteira(
        limite: int = 60,
        tipo: str = "compra_gado",
        municipio: str | None = None,
        prioridade_minima: int = 1,
        so_com_poligono: bool = True,
        instituicao: str | None = None,
    ):
        from laudo.api import mapa
        from laudo.tools.pacote import por_que_na_amostra

        limite = max(1, min(limite, 200))
        try:
            dados = mapa.triar(
                limite=limite,
                tipo=tipo,
                municipio=municipio,
                prioridade_minima=prioridade_minima,
                so_com_poligono=so_com_poligono,
                instituicao=instituicao,
            )
        except ValueError as e:  # filtro inválido (pydantic)
            raise ErroServico(400, str(e)[:300]) from e
        casos = []
        for c in srv.listar_casos():
            if c.get("erro"):
                continue
            caso = srv.caso(c["id"])
            from laudo.api.visao import glebas_coords

            gl = glebas_coords(caso.operacao.glebas_wkt)
            lat = sum(p[0] for p in gl[0]) / len(gl[0]) if gl else None
            lon = sum(p[1] for p in gl[0]) / len(gl[0]) if gl else None
            casos.append(
                c
                | {
                    "glebas": gl,
                    "lat": lat,
                    "lon": lon,
                    "triagem": caso.triagem,
                    "amostra": por_que_na_amostra(caso.triagem),
                    "valor_rs": caso.operacao.valor_rs,
                    "itens": [i.model_dump(mode="json") for i in caso.operacao.itens],
                }
            )
        dados["casos"] = casos
        return dados

    @app.get("/api/mapa/contorno-go")
    def contorno_go():
        from laudo.api import mapa

        c = mapa.contorno_go(srv.dados)
        if c is None:
            raise ErroServico(404, "malha do IBGE não encontrada (dados_locais/ibge)")
        return c

    # -- fiscalizações ---------------------------------------------------------------------
    @app.get("/api/fiscalizacoes")
    def listar():
        return {"fiscalizacoes": srv.listar(), "casos": srv.listar_casos()}

    @app.post("/api/fiscalizacoes")
    def criar(c: CriarFiscalizacao):
        if c.caso:
            try:
                return srv.abrir_caso(c.caso, reiniciar=c.reiniciar)
            except FileNotFoundError as e:
                raise ErroServico(404, str(e)) from e
        if c.ref_bacen:
            return srv.abrir_ref(c.ref_bacen.strip(), nova=c.nova)
        raise ErroServico(400, "informe ref_bacen ou caso")

    @app.get("/api/fiscalizacoes/{fis_id}")
    def estado(fis_id: str):
        return srv.estado(fis_id)

    @app.post("/api/fiscalizacoes/{fis_id}/turno")
    def turno(fis_id: str, t: Turno):
        return srv.turno(fis_id, t.texto, origem="texto", residual=t.residual)

    @app.post("/api/fiscalizacoes/{fis_id}/turno-audio")
    async def turno_audio(
        fis_id: str, audio: Annotated[UploadFile, File()],
        confirmar_numeros: Annotated[str | None, Form()] = None,
    ):
        # O campo é opcional e o padrão é confirmar. Lido como texto porque versões diferentes do FastAPI tratam
        # de formas diferentes um booleano de formulário ausente num envio multipart.
        confirmar = (confirmar_numeros or "").strip().lower() not in ("false", "0", "nao", "não", "off", "no")
        conteudo = await audio.read(LIMITE_AUDIO_MB * MIB + 1)
        return await run_in_threadpool(
            srv.turno_audio, fis_id, audio.filename or "fala.webm", conteudo, confirmar
        )

    @app.post("/api/fiscalizacoes/{fis_id}/confirmar")
    def confirmar(fis_id: str, c: Confirmacao):
        return srv.confirmar(fis_id, c.aceitar, c.texto)

    @app.post("/api/fiscalizacoes/{fis_id}/evidencias")
    def upload(
        fis_id: str,
        arquivo: Annotated[UploadFile, File()],
        tipo: Annotated[str, Form()],
        item_id: Annotated[str, Form()] = "",
        lote: Annotated[str, Form()] = "",
        texto: Annotated[str, Form()] = "",
        lat: Annotated[float | None, Form()] = None,
        lon: Annotated[float | None, Form()] = None,
        precisao_m: Annotated[float | None, Form()] = None,
        gps_capturado_em: Annotated[str, Form()] = "",
        capturada_em: Annotated[str, Form()] = "",
        mock: Annotated[bool | None, Form()] = None,
    ):
        gps = (
            {
                "lat": lat,
                "lon": lon,
                "precisao_m": precisao_m,
                "capturada_em": gps_capturado_em or None,
                "mock": mock,
            }
            if lat is not None and lon is not None
            else None
        )
        return srv.upload(
            fis_id,
            arquivo.filename or "arquivo",
            arquivo.file,
            tipo,
            item_id=item_id or None,
            lote=lote or None,
            texto=texto,
            gps=gps,
            capturada_em=capturada_em or None,
            mime=arquivo.content_type or "",
        )

    @app.post("/api/fiscalizacoes/{fis_id}/evidencias/caso")
    def evidencia_caso(fis_id: str, e: EvidenciaCaso):
        return srv.evidencia_do_caso(fis_id, e.nome, e.texto)

    @app.post("/api/fiscalizacoes/{fis_id}/roteiro/proximo")
    def roteiro_proximo(fis_id: str, n: int | None = None):
        return srv.passo_roteiro(fis_id, n)

    @app.post("/api/fiscalizacoes/{fis_id}/roteiro/pular")
    def roteiro_pular(fis_id: str):
        return srv.pular_passo(fis_id)

    @app.post("/api/fiscalizacoes/{fis_id}/rascunho")
    def rascunho(fis_id: str):
        return srv.pedir_rascunho(fis_id)

    @app.post("/api/fiscalizacoes/{fis_id}/assinar")
    def assinar(fis_id: str, a: Assinatura):
        return srv.assinar(fis_id, a.pin, a.hash_confirmado, a.papel, a.nome_ref)

    @app.post("/api/fiscalizacoes/{fis_id}/pacote")
    def pacote(fis_id: str, prazo_contestacao_dias: int = 15):
        if not 5 <= prazo_contestacao_dias <= 60:
            raise ErroServico(400, "prazo de contestação deve ficar entre 5 e 60 dias")
        return srv.gerar_pacote(fis_id, prazo_contestacao_dias)

    @app.get("/api/fiscalizacoes/{fis_id}/pacote.zip")
    def pacote_zip(fis_id: str):
        p = srv.pacote_arquivo(fis_id)
        return FileResponse(p, media_type=_MIME[".zip"], filename=p.name)

    # -- laudo, trace, arquivos ---------------------------------------------------------------
    @app.get("/api/fiscalizacoes/{fis_id}/laudo")
    def laudo(fis_id: str):
        return srv.laudo_json(fis_id)

    @app.get("/api/fiscalizacoes/{fis_id}/laudo.html", response_class=HTMLResponse)
    def laudo_html(fis_id: str):
        return HTMLResponse(srv.laudo_html(fis_id))

    @app.get("/api/fiscalizacoes/{fis_id}/trace")
    def trace(fis_id: str, span_id: str | None = None):
        if span_id:
            return {"spans": srv.trace(fis_id, checar_id(span_id))}
        p = srv.trace_arquivo(fis_id)
        if not p.exists():
            raise ErroServico(404, "trace ainda vazio")
        return FileResponse(
            p,
            media_type="application/x-ndjson",
            filename=f"{fis_id}.trace.jsonl",
            content_disposition_type="inline",
        )

    @app.get("/api/fiscalizacoes/{fis_id}/evidencias/{ev_id}/arquivo")
    def arquivo(fis_id: str, ev_id: str):
        p = srv.arquivo_evidencia(fis_id, ev_id)
        return FileResponse(
            p,
            media_type=_MIME.get(p.suffix.lower(), "application/octet-stream"),
            content_disposition_type="inline",
            filename=p.name,
        )

    @app.get("/api/fiscalizacoes/{fis_id}/evidencias/{ev_id}/trecho")
    def trecho(fis_id: str, ev_id: str):
        return srv.trecho(fis_id, ev_id)

    @app.get("/api/fiscalizacoes/{fis_id}/checagens/{chk_id}/quadros/{i}")
    def quadro(fis_id: str, chk_id: str, i: int):
        p = srv.quadro_chave(fis_id, chk_id, i)
        return FileResponse(p, media_type=_MIME.get(p.suffix.lower(), "image/jpeg"))

    # -- aquecimento ------------------------------------------------------------------------
    @app.post("/api/voz/aquecer")
    def aquecer_voz():
        return srv.aquecer_asr()

    @app.post("/api/llm/aquecer")
    def aquecer_llm():
        return srv.aquecer_llm()

    @app.get("/api/{resto:path}")
    def api_inexistente(resto: str):
        return PlainTextResponse("rota inexistente", status_code=404)

    web = Path(cfg.web)
    if web.is_dir():
        app.mount("/", StaticFiles(directory=str(web), html=True), name="web")
    return app
