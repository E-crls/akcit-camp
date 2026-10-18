"""Detector de bovinos: YOLOX (COCO, Apache-2.0) em ONNX Runtime CPU.

Pré-processamento (letterbox no canto superior esquerdo, preenchimento 114, BGR 0–255 sem
normalização) e pós-processamento (decodificação das grades nos strides 8/16/32, score =
objetividade × probabilidade da classe, NMS) seguem o demo oficial do YOLOX, reescritos em
numpy/opencv. Não usa Ultralytics (AGPL).
"""

from __future__ import annotations

import os
import threading
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

# Índices COCO (80 classes) usados aqui.
COCO_PESSOA = 0
COCO_CAVALO = 17
COCO_OVELHA = 18
COCO_VACA = 19
COCO_ELEFANTE = 20
# Bezerros, animais claros e ângulos incomuns às vezes saem como "ovelha" num modelo COCO (o COCO tem
# sobretudo gado taurino europeu). Por isso o detector agrupa vaca + ovelha. "Cavalo" fica de fora de
# propósito: vaqueiro a cavalo é comum no curral e a maioria das detecções "cavalo" nos
# vídeos de teste eram cavalos de verdade (zebuínos saíram como "vaca"). Ver docs/modelos.md.
CLASSES_BOVINO = (COCO_OVELHA, COCO_VACA)
NOMES_COCO = {COCO_PESSOA: "pessoa", COCO_CAVALO: "cavalo", COCO_OVELHA: "ovelha", COCO_VACA: "vaca",
              COCO_ELEFANTE: "elefante"}


def letterbox(img_bgr: np.ndarray, lado: int) -> tuple[np.ndarray, float]:
    """Redimensiona mantendo a proporção e cola no canto superior esquerdo de um quadrado `lado`.

    Devolve o tensor (1, 3, lado, lado) float32 e a razão de escala aplicada.
    """
    h, w = img_bgr.shape[:2]
    r = min(lado / h, lado / w)
    nh, nw = max(1, int(h * r)), max(1, int(w * r))
    tela = np.full((lado, lado, 3), 114, dtype=np.uint8)
    tela[:nh, :nw] = cv2.resize(img_bgr, (nw, nh), interpolation=cv2.INTER_LINEAR)
    tensor = np.ascontiguousarray(tela.transpose(2, 0, 1)[None], dtype=np.float32)
    return tensor, r


@lru_cache(maxsize=4)
def _grades(lado: int) -> tuple[np.ndarray, np.ndarray]:
    grades, strides = [], []
    for s in (8, 16, 32):
        n = lado // s
        xv, yv = np.meshgrid(np.arange(n), np.arange(n))
        grades.append(np.stack((xv, yv), 2).reshape(-1, 2))
        strides.append(np.full((n * n, 1), s))
    return np.concatenate(grades).astype(np.float32), np.concatenate(strides).astype(np.float32)


def decodificar_yolox(saida: np.ndarray, lado: int) -> np.ndarray:
    """Converte a saída bruta (N, 85) do YOLOX em (N, 85) com caixas cx, cy, w, h em pixels da entrada."""
    grades, strides = _grades(lado)
    if saida.shape[0] != grades.shape[0]:
        raise ValueError(f"saída com {saida.shape[0]} âncoras; esperado {grades.shape[0]} para lado {lado}")
    out = saida.astype(np.float32, copy=True)
    out[:, :2] = (out[:, :2] + grades) * strides
    out[:, 2:4] = np.exp(np.clip(out[:, 2:4], -10, 10)) * strides
    return out


def iou_matriz(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """IoU entre caixas xyxy: a (N, 4) × b (M, 4) → (N, M)."""
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)), dtype=np.float32)
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return (inter / np.maximum(area_a[:, None] + area_b[None, :] - inter, 1e-9)).astype(np.float32)


def fracao_coberta(a: np.ndarray) -> np.ndarray:
    """(N, N): fração da área da caixa i coberta pela caixa j (diagonal zerada). Mede oclusão parcial."""
    x1 = np.maximum(a[:, None, 0], a[None, :, 0])
    y1 = np.maximum(a[:, None, 1], a[None, :, 1])
    x2 = np.minimum(a[:, None, 2], a[None, :, 2])
    y2 = np.minimum(a[:, None, 3], a[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    m = inter / np.maximum(area[:, None], 1e-9)
    np.fill_diagonal(m, 0)
    return m.astype(np.float32)


def nms(caixas: np.ndarray, scores: np.ndarray, limiar_iou: float = 0.45) -> np.ndarray:
    """NMS guloso (numpy). Devolve os índices mantidos, em ordem decrescente de score."""
    ordem = np.argsort(-scores, kind="stable")
    manter: list[int] = []
    while ordem.size:
        i = int(ordem[0])
        manter.append(i)
        if ordem.size == 1:
            break
        ious = iou_matriz(caixas[i:i + 1], caixas[ordem[1:]])[0]
        ordem = ordem[1:][ious <= limiar_iou]
    return np.asarray(manter, dtype=np.int64)


def pos_processar(saida_decodificada: np.ndarray, razao: float, limiar: float, limiar_nms: float,
                  classes: tuple[int, ...], agrupar: bool) -> np.ndarray:
    """Filtra, converte para xyxy na imagem original e aplica NMS.

    Devolve (K, 7): x1, y1, x2, y2, score, classe_coco, score_vaca.
    Com `agrupar=True`, o score do bovino é o maior entre as `classes`; a classe vencedora fica
    registrada para medir confusão (ex.: Nelore rotulado como ovelha).
    """
    obj = saida_decodificada[:, 4]
    probs = saida_decodificada[:, 5:]
    if agrupar:
        sub = probs[:, list(classes)]
        k = np.argmax(sub, axis=1)
        cls = np.asarray(classes)[k]
        score = obj * sub[np.arange(len(sub)), k]
    else:
        cls = np.full(len(probs), COCO_VACA)
        score = obj * probs[:, COCO_VACA]
    score_vaca = obj * probs[:, COCO_VACA]
    sel = score >= limiar
    if not np.any(sel):
        return np.zeros((0, 7), dtype=np.float32)
    d = saida_decodificada[sel]
    cx, cy, w, h = d[:, 0], d[:, 1], d[:, 2], d[:, 3]
    caixas = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], 1) / razao
    s = score[sel]
    manter = nms(caixas, s, limiar_nms)
    return np.concatenate([caixas[manter], s[manter, None], cls[sel][manter, None].astype(np.float32),
                           score_vaca[sel][manter, None]], 1).astype(np.float32)


class DetectorYOLOX:
    """Detector ONNX (CPU). `detectar(img_bgr)` devolve (K, 7) como em `pos_processar`."""

    def __init__(self, caminho: str | Path, limiar: float = 0.25, limiar_nms: float = 0.45,
                 agrupar_classes: bool = True, n_threads: int | None = None):
        import onnxruntime as ort

        so = ort.SessionOptions()
        so.intra_op_num_threads = n_threads or min(8, os.cpu_count() or 4)
        so.inter_op_num_threads = 1
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.sessao = ort.InferenceSession(str(caminho), so, providers=["CPUExecutionProvider"])
        ent = self.sessao.get_inputs()[0]
        self.nome_entrada = ent.name
        self.lado = int(ent.shape[2])
        self.limiar = limiar
        self.limiar_nms = limiar_nms
        self.agrupar = agrupar_classes
        self._trava = threading.Lock()

    def detectar(self, img_bgr: np.ndarray, limiar: float | None = None) -> np.ndarray:
        tensor, r = letterbox(img_bgr, self.lado)
        with self._trava:
            saida = self.sessao.run(None, {self.nome_entrada: tensor})[0][0]
        dec = decodificar_yolox(saida, self.lado)
        return pos_processar(dec, r, self.limiar if limiar is None else limiar, self.limiar_nms,
                             CLASSES_BOVINO, self.agrupar)


@lru_cache(maxsize=2)
def carregar_detector(caminho: str, agrupar_classes: bool = True) -> DetectorYOLOX:
    """Carrega (uma vez por processo) o detector ONNX."""
    return DetectorYOLOX(caminho, agrupar_classes=agrupar_classes)
