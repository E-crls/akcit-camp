"""Pré e pós-processamento do detector YOLOX (sem o modelo ONNX)."""

from __future__ import annotations

import numpy as np

from laudo.vision.detector import (
    COCO_OVELHA,
    COCO_VACA,
    decodificar_yolox,
    iou_matriz,
    letterbox,
    nms,
    pos_processar,
)


def test_letterbox_mantem_proporcao_e_preenche_114():
    img = np.full((100, 200, 3), 7, dtype=np.uint8)
    t, r = letterbox(img, 64)
    assert t.shape == (1, 3, 64, 64) and t.dtype == np.float32
    assert r == 64 / 200
    assert t[0, 0, 0, 0] == 7  # conteúdo colado no canto superior esquerdo
    assert t[0, 0, 63, 0] == 114  # preenchimento abaixo (altura útil = 32)


def test_iou_e_nms():
    a = np.array([[0, 0, 10, 10], [5, 5, 15, 15], [100, 100, 110, 110]], dtype=np.float32)
    iou = iou_matriz(a, a)
    assert np.allclose(np.diag(iou), 1)
    assert abs(iou[0, 1] - 25 / 175) < 1e-6
    assert iou[0, 2] == 0
    caixas = np.array([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]], dtype=np.float32)
    manter = nms(caixas, np.array([0.9, 0.8, 0.7]), 0.45)
    assert manter.tolist() == [0, 2]


def _saida_falsa(lado: int, ancora: int, cls: int, obj: float, prob: float) -> np.ndarray:
    n = sum((lado // s) ** 2 for s in (8, 16, 32))
    out = np.zeros((n, 85), dtype=np.float32)
    out[:, 2:4] = np.log(2.0)  # w = h = 2 * stride
    out[ancora, 4] = obj
    out[ancora, 5 + cls] = prob
    return out


def test_decodificacao_grade_stride8():
    lado = 64
    ancora = 8 * 3 + 5  # linha 3, coluna 5 da grade de stride 8 (8 × 8)
    dec = decodificar_yolox(_saida_falsa(lado, ancora, COCO_VACA, 0.9, 0.9), lado)
    assert dec[ancora, 0] == 5 * 8 and dec[ancora, 1] == 3 * 8
    assert abs(dec[ancora, 2] - 16) < 1e-4  # exp(log 2) * 8


def test_pos_processar_filtra_classe_e_reescala():
    lado = 64
    dec = decodificar_yolox(_saida_falsa(lado, 8 * 3 + 5, COCO_VACA, 0.9, 0.8), lado)
    out = pos_processar(dec, razao=0.5, limiar=0.3, limiar_nms=0.45, classes=(COCO_OVELHA, COCO_VACA),
                        agrupar=True)
    assert out.shape == (1, 7)
    x1, y1, x2, y2, score, cls, _s_vaca = out[0]
    assert abs(score - 0.72) < 1e-5 and int(cls) == COCO_VACA
    assert (x1, y1, x2, y2) == (64.0, 32.0, 96.0, 64.0)  # (40±8, 24±8) / 0.5


def test_agrupamento_de_quadrupedes():
    lado = 64
    dec = decodificar_yolox(_saida_falsa(lado, 10, COCO_OVELHA, 0.9, 0.8), lado)
    so_vaca = pos_processar(dec, 1.0, 0.3, 0.45, (COCO_OVELHA, COCO_VACA), agrupar=False)
    agrupado = pos_processar(dec, 1.0, 0.3, 0.45, (COCO_OVELHA, COCO_VACA), agrupar=True)
    assert len(so_vaca) == 0
    assert len(agrupado) == 1 and int(agrupado[0, 5]) == COCO_OVELHA


def test_fracao_coberta_mede_oclusao_parcial():
    from laudo.vision.detector import fracao_coberta

    # caixa pequena metade escondida atrás de uma grande: IoU baixo, mas 50% coberta
    a = np.array([[0, 0, 100, 100], [80, 0, 120, 40]], dtype=np.float32)
    m = fracao_coberta(a)
    assert abs(m[1, 0] - 0.5) < 1e-6 and abs(m[0, 1] - 0.08) < 1e-6
    assert iou_matriz(a, a)[0, 1] < 0.1
