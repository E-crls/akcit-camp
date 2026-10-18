"""Desenho dos quadros-chave anotados (evidência visual da contagem)."""

from __future__ import annotations

import cv2
import numpy as np

VERDE = (60, 200, 60)
CINZA = (170, 170, 170)
AMARELO = (0, 215, 255)
VERMELHO = (40, 40, 230)


def anotar(img: np.ndarray, caixas: list[tuple[int, tuple[float, float, float, float], float, bool]],
           linha: tuple[float, float, float, float] | None, titulo: str, rodape: str = "") -> np.ndarray:
    """Desenha caixas (id, xyxy, score, contada?), a linha de contagem e uma faixa de texto."""
    out = img.copy()
    h, w = out.shape[:2]
    esp = max(1, round(min(w, h) / 360))
    fonte = 0.4 + min(w, h) / 1400
    if linha is not None:
        x1, y1, x2, y2 = (round(v) for v in linha)
        cv2.line(out, (x1, y1), (x2, y2), AMARELO, esp + 1, cv2.LINE_AA)
    for tid, (bx1, by1, bx2, by2), score, contada in caixas:
        cor = VERDE if contada else CINZA
        p1, p2 = (int(bx1), int(by1)), (int(bx2), int(by2))
        cv2.rectangle(out, p1, p2, cor, esp, cv2.LINE_AA)
        rot = f"#{tid} {score:.2f}"
        (tw, th), _ = cv2.getTextSize(rot, cv2.FONT_HERSHEY_SIMPLEX, fonte * 0.8, 1)
        y_txt = max(th + 2, p1[1] - 3)
        cv2.rectangle(out, (p1[0], y_txt - th - 2), (p1[0] + tw + 2, y_txt + 2), cor, -1)
        cv2.putText(out, rot, (p1[0] + 1, y_txt), cv2.FONT_HERSHEY_SIMPLEX, fonte * 0.8, (0, 0, 0), 1,
                    cv2.LINE_AA)
    # faixa superior semitransparente
    faixa_h = int(28 * fonte / 0.6)
    sub = out[:faixa_h]
    sub[:] = (sub.astype(np.float32) * 0.35).astype(np.uint8)
    cv2.putText(out, titulo, (8, int(faixa_h * 0.7)), cv2.FONT_HERSHEY_SIMPLEX, fonte, (255, 255, 255), 1,
                cv2.LINE_AA)
    if rodape:
        cv2.putText(out, rodape, (8, h - 8), cv2.FONT_HERSHEY_SIMPLEX, fonte * 0.7, (255, 255, 255), 2,
                    cv2.LINE_AA)
        cv2.putText(out, rodape, (8, h - 8), cv2.FONT_HERSHEY_SIMPLEX, fonte * 0.7, (0, 0, 0), 1, cv2.LINE_AA)
    return out
