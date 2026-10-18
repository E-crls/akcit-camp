"""Contagem em vídeos reais do Commons com o modelo ONNX (lento: ~10–40 s).

Precisa de `scripts/py.sh scripts/baixar_modelos.py --todos` e dos vídeos em dados_locais/videos
(`scripts/baixar_videos_teste.py`). Sem eles, os testes são pulados.
Rodar só estes: `scripts/py.sh -m pytest tests/unit -m lento -q` (ou LAUDO_LENTO=1).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from laudo.tools.bovinos import EntradaContarBovinos, contar_bovinos_video
from laudo.vision.modelos import MODELOS, RAIZ_REPO

pytestmark = pytest.mark.lento

VIDEOS = RAIZ_REPO / "dados_locais" / "videos"


@pytest.fixture(autouse=True)
def _so_quando_pedido(request):
    """Não pesa no `pytest tests/unit` comum: roda com `-m lento` ou LAUDO_LENTO=1."""
    if "lento" not in (request.config.getoption("markexpr") or "") and not os.environ.get("LAUDO_LENTO"):
        pytest.skip("teste lento: rode com -m lento ou LAUDO_LENTO=1")


def _precisa(video: str, modelo: str) -> Path:
    p = VIDEOS / video
    if not p.is_file() or not MODELOS[modelo].caminho.is_file():
        pytest.skip(f"faltam {video} ou {modelo}.onnx (ver docs/modelos.md)")
    return p


def test_lote_parado_de_bufalas(tmp_path):
    p = _precisa("v05_bufalas_ordenha.webm", "yolox_m")
    e = contar_bovinos_video(EntradaContarBovinos(caminho_video=str(p), modo="ids_unicos", modelo="yolox_m",
                                                  dir_evidencias=str(tmp_path)))
    assert e.ok, e.error
    d = e.data
    assert 3 <= d["contagem"] <= 5 and d["intervalo"][0] <= 4 <= d["intervalo"][1]
    assert 3 <= len(d["quadros_chave"]) <= 6 and all(Path(q["caminho"]).is_file() for q in d["quadros_chave"])
    assert d["s_por_s_video"] < 2.0  # CPU: bem abaixo de 2 s por segundo de vídeo


def test_zebuinos_parados(tmp_path):
    p = _precisa("v03_zebuinos_estabulo.webm", "yolox_m")
    e = contar_bovinos_video(EntradaContarBovinos(caminho_video=str(p), modo="ids_unicos", modelo="yolox_m",
                                                  dir_evidencias=str(tmp_path)))
    assert e.ok and 7 <= e.data["contagem"] <= 11


def test_camera_andando_no_meio_do_rebanho_abstem(tmp_path):
    p = _precisa("v04_manejo_a_cavalo.webm", "yolox_m")
    e = contar_bovinos_video(EntradaContarBovinos(caminho_video=str(p), modo="ids_unicos", modelo="yolox_m",
                                                  dir_evidencias=str(tmp_path)))
    assert e.ok and e.data["abstencao"] and e.data["status"] == "indeterminado"
    assert any(m["codigo"] == "CAMERA_EM_MOVIMENTO" for m in e.data["motivos"])
    assert e.data["pedidos_recaptura"]


@pytest.mark.parametrize("modelo", ["yolox_m", "yolox_s"])
def test_lote_parado_no_modo_linha_abstem(tmp_path, modelo):
    # lote parado não cruza a linha; com yolox_s uma cabeça que se mexe vira "cruzamento" de intervalo largo
    p = _precisa("v05_bufalas_ordenha.webm", modelo)
    e = contar_bovinos_video(EntradaContarBovinos(caminho_video=str(p), modo="linha", modelo=modelo,
                                                  dir_evidencias=str(tmp_path)))
    assert e.ok and e.data["abstencao"]
    assert {m["codigo"] for m in e.data["motivos"]} & {"SEM_CRUZAMENTO", "INTERVALO_LARGO"}
