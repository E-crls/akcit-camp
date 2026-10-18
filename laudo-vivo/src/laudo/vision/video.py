"""Leitura de vídeo quadro a quadro (PyAV), com amostragem por tempo e redução de resolução.

Nunca carrega o vídeo inteiro: decodifica em fluxo e entrega só os quadros amostrados, já
convertidos para BGR e reduzidos (lado maior ≤ `lado_max`). Aplica a rotação da matriz de exibição
(vídeos de celular em retrato).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class InfoVideo:
    largura: int
    altura: int
    fps: float
    duracao_s: float | None
    n_quadros: int | None
    codec: str


@dataclass
class Quadro:
    indice_decod: int  # índice do quadro no fluxo decodificado
    indice_proc: int  # índice entre os quadros processados (0, 1, 2, ...)
    t_s: float
    img: np.ndarray  # BGR uint8


def info_video(caminho: str) -> InfoVideo:
    import av

    with av.open(caminho) as c:
        s = c.streams.video[0]
        fps = float(s.average_rate or s.guessed_rate or 0) or 30.0
        dur = None
        if s.duration is not None and s.time_base is not None:
            dur = float(s.duration * s.time_base)
        elif c.duration:
            dur = c.duration / 1_000_000
        return InfoVideo(s.codec_context.width, s.codec_context.height, fps, dur, s.frames or None,
                         s.codec_context.name)


def _rotacionar(img: np.ndarray, rotacao: int) -> np.ndarray:
    k = round(rotacao / 90.0) % 4
    return np.ascontiguousarray(np.rot90(img, k)) if k else img


def _dimensoes(w: int, h: int, lado_max: int) -> tuple[int, int]:
    r = min(1.0, lado_max / max(w, h))
    return max(2, round(w * r) // 2 * 2), max(2, round(h * r) // 2 * 2)


def iterar_quadros(caminho: str, fps_amostragem: float = 8.0, lado_max: int = 1280,
                   max_duracao_s: float | None = None,
                   indices: set[int] | None = None) -> Iterator[Quadro]:
    """Gera os quadros amostrados.

    - `fps_amostragem`: quadros por segundo de vídeo a entregar (≤ fps do vídeo).
    - `indices`: se dado, entrega exatamente esses índices de decodificação (segunda passada para
      os quadros-chave) e ignora `fps_amostragem`.
    """
    import av

    with av.open(caminho) as c:
        s = c.streams.video[0]
        s.thread_type = "AUTO"
        passo = 1.0 / fps_amostragem if fps_amostragem > 0 else 0.0
        proximo_t = 0.0
        n_proc = 0
        ultimo_idx = max(indices) if indices else None
        for i, fr in enumerate(c.decode(s)):
            t = float(fr.time) if fr.time is not None else i / (float(s.average_rate or 30))
            if max_duracao_s is not None and t > max_duracao_s:
                break
            if indices is not None:
                if i not in indices:
                    if ultimo_idx is not None and i > ultimo_idx:
                        break
                    continue
            elif t + 1e-6 < proximo_t:
                continue
            else:
                proximo_t = max(proximo_t + passo, t + passo * 0.5)
            w, h = _dimensoes(fr.width, fr.height, lado_max)
            img = fr.to_ndarray(format="bgr24", width=w, height=h)
            rot = getattr(fr, "rotation", 0) or 0
            if rot:
                img = _rotacionar(img, rot)
            yield Quadro(i, n_proc, t, img)
            n_proc += 1


def qualidade_quadro(img: np.ndarray) -> tuple[float, float]:
    """(luminância média 0–255, variância do Laplaciano) num cinza reduzido a 320 px de largura."""
    cinza = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = cinza.shape
    if w > 320:
        cinza = cv2.resize(cinza, (320, max(1, int(h * 320 / w))), interpolation=cv2.INTER_AREA)
    return float(cinza.mean()), float(cv2.Laplacian(cinza, cv2.CV_64F).var())
