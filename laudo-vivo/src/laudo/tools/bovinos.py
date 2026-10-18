"""Ferramenta `contar_bovinos_video`: contagem de bovinos em vídeo com intervalo e abstenção.

A ferramenta calcula; quem compara com a quantidade financiada e atribui status ao item do laudo é o
verificador. Aqui o status é só "ok" (contagem utilizável) ou "indeterminado" (abstenção, com motivos
e pedido de nova captura).
"""

from __future__ import annotations

import time
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from laudo.contracts import CodigoErro, Envelope, hash_entrada, registrar, sha256_arquivo
from laudo.vision.contagem import ParametrosContagem
from laudo.vision.modelos import MODELO_PADRAO, MODELOS, RAIZ_REPO
from laudo.vision.pipeline import VERSAO_CONTADOR, ConfigPipeline, processar_video

NOME = "contar_bovinos_video"
DIR_EVIDENCIAS_PADRAO = RAIZ_REPO / "dados_locais" / "evidencias" / "visao"

# Pedido de nova captura por motivo de abstenção (o condutor repassa ao fiscal).
PEDIDOS = {
    "SEM_CRUZAMENTO": "Filme o lote passando pelo corredor ou brete, com a câmera parada e de lado.",
    "SEM_BOVINOS": "Chegue mais perto (5–15 m) e filme com luz do dia, sem contraluz.",
    "VIDEO_RUIM": "Refaça o vídeo com mais luz e o celular apoiado (sem tremer).",
    "VIDEO_CURTO": "Grave pelo menos o tempo de todo o lote passar.",
    "TRUNCADO": "Divida em vídeos menores (até 3 min) e conte cada parte.",
    "CONF_BAIXA": "Filme mais perto e de lado; evite animais muito pequenos no quadro.",
    "COBERTURA_BAIXA": "Filme o corredor de cima ou de lado, onde os animais passem em fila.",
    "INTERVALO_LARGO": "Faça os animais passarem em fila pelo corredor, com a câmera parada.",
    "OCLUSAO_ALTA": "Filme de um ponto mais alto, com os animais passando em fila.",
    "CAMERA_EM_MOVIMENTO": "Apoie o celular e deixe a câmera parada; não acompanhe os animais com ela.",
}


class EntradaContarBovinos(BaseModel):
    caminho_video: str = Field(description="caminho local do vídeo (mp4, webm, mov)")
    modo: Literal["linha", "ids_unicos"] = Field(
        "linha", description="linha = animais passando por corredor/brete (recomendado); "
                             "ids_unicos = lote parado ou câmera passando devagar")
    linha: list[float] | None = Field(
        None, min_length=4, max_length=4,
        description="x1, y1, x2, y2 normalizados (0–1); omitido = linha automática perpendicular ao movimento")
    sentido: Literal["auto", "a_para_b", "b_para_a"] = "auto"
    fps_amostragem: float = Field(8.0, gt=0, le=30)
    limiar_deteccao: float = Field(0.25, ge=0.05, le=0.9)
    modelo: Literal["yolox_s", "yolox_m", "yolox_tiny"] = MODELO_PADRAO
    max_duracao_s: float = Field(180.0, gt=0, le=600)
    n_quadros_chave: int = Field(4, ge=3, le=6)
    dir_evidencias: str | None = Field(None, description="onde salvar os quadros-chave anotados")
    item_id: str | None = Field(None, description="item financiado (rastreabilidade)")


@lru_cache(maxsize=4)
def _hash_modelo(caminho: str) -> str:
    return sha256_arquivo(caminho)


@registrar(NOME, "Conta bovinos num vídeo (detector YOLOX + rastreador + linha de contagem ou IDs únicos) "
                 "e devolve contagem, intervalo, motivos de abstenção e quadros-chave anotados.",
           EntradaContarBovinos, deterministica=True, timeout_s=180.0)
def contar_bovinos_video(args: EntradaContarBovinos) -> Envelope:
    t0 = time.perf_counter()
    video = Path(args.caminho_video)
    if not video.is_file():
        return Envelope.falha(NOME, CodigoErro.ENTRADA_INVALIDA, f"vídeo não encontrado: {video}", t0=t0)
    info = MODELOS[args.modelo]
    if not info.caminho.is_file():
        return Envelope.falha(NOME, CodigoErro.SEM_DADOS,
                              f"modelo {args.modelo} ausente; rode scripts/py.sh scripts/baixar_modelos.py",
                              t0=t0)
    h_modelo = _hash_modelo(str(info.caminho))
    if h_modelo != info.sha256:
        return Envelope.falha(NOME, CodigoErro.ERRO_INTERNO,
                              f"sha256 do modelo {args.modelo} não confere com o registro", t0=t0)
    try:
        from laudo.vision.detector import carregar_detector

        h_video = sha256_arquivo(str(video))
        detector = carregar_detector(str(info.caminho))
        params = ParametrosContagem(modo=args.modo, linha=tuple(args.linha) if args.linha else None,
                                    sentido=args.sentido)
        cfg = ConfigPipeline(fps_amostragem=args.fps_amostragem, limiar_deteccao=args.limiar_deteccao,
                             max_duracao_s=args.max_duracao_s, n_quadros_chave=args.n_quadros_chave)
        dir_ev = Path(args.dir_evidencias) if args.dir_evidencias else DIR_EVIDENCIAS_PADRAO / h_video[:12]
        dados = processar_video(str(video), detector, params, cfg, dir_evidencias=dir_ev,
                                prefixo=f"{args.modo}_{hash_entrada(args.model_dump())[:6]}")
    except Exception as e:  # noqa: BLE001 — erro vira Envelope, nunca exceção solta
        import av

        if isinstance(e, (av.error.InvalidDataError, av.error.FFmpegError, IndexError)):
            return Envelope.falha(NOME, CodigoErro.ENTRADA_INVALIDA, f"vídeo ilegível: {e}", t0=t0)
        return Envelope.falha(NOME, CodigoErro.ERRO_INTERNO, f"{type(e).__name__}: {e}", t0=t0)

    dados["video"] = {"caminho": video.as_posix(), "sha256": h_video}
    dados["modelo"] = {"nome": info.nome, "sha256": h_modelo, "licenca": info.licenca, "url": info.url}
    dados["item_id"] = args.item_id
    dados["pedidos_recaptura"] = sorted({PEDIDOS[m["codigo"]] for m in dados["motivos"]
                                         if m["abstem"] and m["codigo"] in PEDIDOS})
    return Envelope.sucesso(NOME, dados, fonte_versao=f"{info.versao}+{VERSAO_CONTADOR}", t0=t0)
