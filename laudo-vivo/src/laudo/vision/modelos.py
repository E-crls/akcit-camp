"""Registro dos modelos de visão (fonte, hash e licença). Detalhes em `docs/modelos.md`.

Os arquivos ficam em `dados_locais/modelos/` (fora do git) e são baixados por
`scripts/baixar_modelos.py`, que confere o sha256 abaixo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parents[3]
DIR_MODELOS = Path(os.environ.get("LAUDO_DIR_MODELOS", RAIZ_REPO / "dados_locais" / "modelos"))

_BASE_YOLOX = "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/"


@dataclass(frozen=True)
class InfoModelo:
    nome: str
    url: str
    sha256: str
    licenca: str
    entrada: int  # lado da entrada quadrada (px)
    padrao: bool = False

    @property
    def caminho(self) -> Path:
        return DIR_MODELOS / f"{self.nome}.onnx"

    @property
    def versao(self) -> str:
        return f"{self.nome}@0.1.1rc0"


# YOLOX (Megvii, Apache-2.0), pesos COCO (80 classes) do release oficial 0.1.1rc0.
# Padrão: yolox_m (melhor em cena real; ~0,4 s por segundo de vídeo a 8 quadros/s em CPU).
MODELOS: dict[str, InfoModelo] = {
    "yolox_s": InfoModelo("yolox_s", _BASE_YOLOX + "yolox_s.onnx",
                          "c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063",
                          "Apache-2.0", 640),
    "yolox_m": InfoModelo("yolox_m", _BASE_YOLOX + "yolox_m.onnx",
                          "21ff6cfdeb53b013bac2249599e55f00bff3cfdfdab37ed7a4620818c1d15b3f",
                          "Apache-2.0", 640, padrao=True),
    "yolox_tiny": InfoModelo("yolox_tiny", _BASE_YOLOX + "yolox_tiny.onnx",
                             "427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7",
                             "Apache-2.0", 416),
}

MODELO_PADRAO = next(n for n, m in MODELOS.items() if m.padrao)
