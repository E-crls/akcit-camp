"""Ferramenta `integridade_foto`: EXIF, horário, GPS, sha256, phash/duplicata, nitidez e "foto de tela".

Status: "ok", "indeterminado" (ex.: sem EXIF, desfocada; pede nova captura no app) ou "divergente"
(ex.: duplicata de outra fiscalização, horário incoerente, provável foto de tela), sempre com motivos.
"""

from __future__ import annotations

import time
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from laudo.contracts import GPS, CodigoErro, Envelope, registrar, sha256_arquivo
from laudo.vision.integridade import (
    VERSAO_INTEGRIDADE,
    IndiceFotos,
    ParametrosIntegridade,
    avaliar_integridade,
)
from laudo.vision.modelos import RAIZ_REPO

NOME = "integridade_foto"
INDICE_PADRAO = RAIZ_REPO / "dados_locais" / "indices" / "fotos.jsonl"


class EntradaIntegridadeFoto(BaseModel):
    caminho_foto: str = Field(description="caminho local da foto (JPEG/PNG/HEIC convertido)")
    recebida_em: datetime | None = Field(None, description="momento do recebimento; padrão = agora (UTC-3)")
    gps_app: GPS | None = Field(None, description="coordenada informada pelo app no momento da captura")
    contexto: str | None = Field(None, description="id da fiscalização (duplicata em outro contexto = divergente)")
    indice: str | None = Field(None, description="índice local de fotos (JSONL); padrão em dados_locais/indices")
    registrar_no_indice: bool = True
    max_atraso_h: float = Field(72.0, gt=0, description="parâmetro operacional do rulebook")
    limiar_nitidez: float = Field(60.0, ge=0)
    exigir_gps: bool = True


@registrar(NOME, "Confere a integridade de uma foto de evidência: EXIF (data, GPS, câmera, software), "
                 "atraso entre captura e recebimento, sha256, phash e duplicatas no índice local, nitidez e "
                 "sinais de foto de tela. Devolve status ok/indeterminado/divergente com motivos.",
           EntradaIntegridadeFoto, deterministica=True, timeout_s=5.0)
def integridade_foto(args: EntradaIntegridadeFoto) -> Envelope:
    t0 = time.perf_counter()
    foto = Path(args.caminho_foto)
    if not foto.is_file():
        return Envelope.falha(NOME, CodigoErro.ENTRADA_INVALIDA, f"foto não encontrada: {foto}", t0=t0)
    try:
        sha = sha256_arquivo(str(foto))
        p = ParametrosIntegridade(max_atraso_h=args.max_atraso_h, limiar_nitidez=args.limiar_nitidez,
                                  exigir_gps=args.exigir_gps)
        gps_app = (args.gps_app.lat, args.gps_app.lon) if args.gps_app else None
        # precisão e "localização simulada" do GPS do app: foto sem GPS no EXIF com GPS do app bom (≤ 30 m) não
        # fica pendente por isso (SEM_GPS vira informação; ver avaliar_integridade)
        dados = avaliar_integridade(foto, sha, recebida_em=args.recebida_em, gps_app=gps_app,
                                    contexto=args.contexto, indice=IndiceFotos(args.indice or INDICE_PADRAO),
                                    registrar=args.registrar_no_indice, p=p,
                                    precisao_app_m=args.gps_app.precisao_m if args.gps_app else None,
                                    gps_app_simulado=bool(args.gps_app and args.gps_app.mock))
    except Exception as e:  # noqa: BLE001 — erro vira Envelope
        from PIL import UnidentifiedImageError

        if isinstance(e, (UnidentifiedImageError, OSError, ValueError)):
            return Envelope.falha(NOME, CodigoErro.ENTRADA_INVALIDA, f"imagem ilegível: {e}", t0=t0)
        return Envelope.falha(NOME, CodigoErro.ERRO_INTERNO, f"{type(e).__name__}: {e}", t0=t0)
    dados["caminho"] = foto.as_posix()
    return Envelope.sucesso(NOME, dados, fonte_versao=VERSAO_INTEGRIDADE, t0=t0)


# ---------------------------------------------------------------------------
# classificar_foto (VLM local; não determinística)
# ---------------------------------------------------------------------------

ClasseFoto = Literal["bovinos", "cerca", "curral", "galpao", "maquina", "documento", "outro"]


class EntradaClassificarFoto(BaseModel):
    caminho_foto: str
    classes: list[ClasseFoto] = Field(
        default_factory=lambda: ["bovinos", "cerca", "curral", "galpao", "maquina", "documento", "outro"])
    k: int = Field(3, ge=1, le=5, description="amostras para autoconsistência")
    modelo: str = "qwen3.5:4b"
    descarregar_ao_final: bool = Field(False, description="tira o modelo da VRAM ao final (só se o condutor usa "
                                                          "outro modelo)")
    classe_esperada: ClasseFoto | None = Field(
        None, description="classe do item financiado (cerca, curral, galpão): status ok só se a foto mostra essa "
                          "estrutura (MCR-2-7-item16-benfeitorias-conclusao); sem ela, ok = classificação confiante")
    data_referencia: date | None = Field(None, description="data de hoje da fiscalização (vai no prompt)")


@registrar("classificar_foto", "Classifica o assunto principal da foto (bovinos, cerca, curral, galpão, máquina, "
                               "documento, outro) com VLM local e autoconsistência (até k=3); abstém-se se a "
                               "concordância for menor que 2/3. Com classe_esperada, diz se a foto mostra a "
                               "estrutura do item.",
           EntradaClassificarFoto, deterministica=False, timeout_s=90.0)
def classificar_foto(args: EntradaClassificarFoto) -> Envelope:
    t0 = time.perf_counter()
    foto = Path(args.caminho_foto)
    if not foto.is_file():
        return Envelope.falha("classificar_foto", CodigoErro.ENTRADA_INVALIDA, f"foto não encontrada: {foto}",
                              t0=t0)
    classes = tuple(dict.fromkeys([*args.classes, "outro"]))
    try:
        import httpx

        from laudo.vision.vlm import classificar

        dados = classificar(str(foto), classes, k=args.k, modelo=args.modelo,
                            descarregar=args.descarregar_ao_final, hoje=args.data_referencia)
    except ValueError as e:
        return Envelope.falha("classificar_foto", CodigoErro.ENTRADA_INVALIDA, str(e), t0=t0)
    except httpx.TimeoutException as e:
        return Envelope.falha("classificar_foto", CodigoErro.TIMEOUT, f"Ollama não respondeu: {e}",
                              retryable=True, t0=t0)
    except httpx.HTTPError as e:
        return Envelope.falha("classificar_foto", CodigoErro.ERRO_INTERNO, f"Ollama indisponível: {e}",
                              retryable=True, t0=t0)
    if args.classe_esperada:
        # a foto prova a estrutura do item só se o VLM viu essa estrutura (nunca divergência: o VLM não sabe se a
        # obra está inacabada; outra classe ou abstenção é inconclusiva e pede a foto da estrutura inteira)
        dados["classe_esperada"] = args.classe_esperada
        if dados.get("classe") == args.classe_esperada and not dados.get("abstencao"):
            dados["status"], dados["motivo"] = "ok", f"a foto mostra {args.classe_esperada}"
        else:
            vista = dados.get("classe") or dados.get("classe_majoritaria") or "indeterminado"
            dados["status"] = "indeterminado"
            dados["motivo"] = (f"a foto não mostra a estrutura do item ({args.classe_esperada}): o VLM viu {vista}"
                               + (" sem concordância" if dados.get("abstencao") else "")
                               + "; fotografe a estrutura inteira")
    dados["caminho"] = foto.as_posix()
    dados["sha256"] = sha256_arquivo(str(foto))
    return Envelope.sucesso("classificar_foto", dados, fonte_versao=f"{args.modelo}+vlm@0.2.0", t0=t0)
