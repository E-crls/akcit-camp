"""Pipeline de vídeo ponta a ponta com vídeo sintético e detector falso (sem modelo ONNX)."""

from __future__ import annotations

from pathlib import Path

import av
import cv2
import numpy as np
import pytest

from laudo.contracts import REGISTRO, CodigoErro, sha256_arquivo
from laudo.vision.contagem import ParametrosContagem
from laudo.vision.pipeline import ConfigPipeline, processar_video

L, A, FPS = 256, 144, 24


class DetectorCor:
    """Detector falso: blobs vermelhos viram "vacas" com score 0,9."""

    def detectar(self, img: np.ndarray, limiar: float | None = None) -> np.ndarray:
        b, g, r = img[..., 0].astype(int), img[..., 1].astype(int), img[..., 2].astype(int)
        mask = ((r > 150) & (g < 90) & (b < 90)).astype(np.uint8)
        _, _, stats, _ = cv2.connectedComponentsWithStats(mask)
        out = [[x, y, x + w, y + h, 0.9, 19, 0.9] for x, y, w, h, area in stats[1:] if area > 30]
        return np.array(out, dtype=np.float32).reshape(-1, 7)


def _gerar_video(caminho: Path, n_animais: int = 3, segundos: float = 4.0) -> None:
    with av.open(str(caminho), "w") as c:
        s = c.add_stream("mpeg4", rate=FPS)
        s.width, s.height, s.pix_fmt = L, A, "yuv420p"
        s.bit_rate = 2_000_000
        n = int(segundos * FPS)
        rng = np.random.default_rng(0)
        pasto = cv2.GaussianBlur(rng.integers(0, 255, (A, L), dtype=np.uint8), (0, 0), 1.2)
        pasto = cv2.merge([pasto // 4 + 30, pasto // 3 + 80, pasto // 4 + 40])  # textura estática de pasto
        for q in range(n):
            img = pasto.copy()
            for k in range(n_animais):
                x = int(-30 + (q - k * 18) * 6)
                if -30 < x < L:
                    y = 40 + (k % 2) * 40
                    cv2.rectangle(img, (max(0, x), y), (min(L - 1, x + 28), y + 18), (0, 0, 220), -1)
            fr = av.VideoFrame.from_ndarray(img, format="bgr24")
            for p in s.encode(fr):
                c.mux(p)
        for p in s.encode():
            c.mux(p)


@pytest.fixture(scope="module")
def video(tmp_path_factory) -> Path:
    p = tmp_path_factory.mktemp("vid") / "fila.mp4"
    _gerar_video(p)
    return p


def test_pipeline_linha_conta_e_salva_quadros(video, tmp_path):
    r = processar_video(str(video), DetectorCor(), ParametrosContagem(modo="linha"),
                        ConfigPipeline(fps_amostragem=8, min_acertos=2), dir_evidencias=tmp_path)
    assert r["contagem"] == 3 and r["intervalo"] == [3, 3]
    assert r["status"] == "ok" and not r["abstencao"]
    assert r["eixo_movimento"] == "horizontal"
    assert 7.5 <= r["fps_processado"] <= 8.5
    assert 3 <= len(r["quadros_chave"]) <= 6
    for q in r["quadros_chave"]:
        assert Path(q["caminho"]).is_file()
        assert sha256_arquivo(q["caminho"]) == q["sha256"]
    assert r["quadros_chave"][-1]["contagem_ate_aqui"] == 3


def test_pipeline_ids_unicos(video):
    r = processar_video(str(video), DetectorCor(), ParametrosContagem(modo="ids_unicos", min_duracao_s=0.5),
                        ConfigPipeline(fps_amostragem=8, min_acertos=2))
    assert r["contagem"] == 3


def test_ferramenta_registrada_e_erros(tmp_path, monkeypatch):
    import laudo.tools.bovinos as bov

    assert "contar_bovinos_video" in REGISTRO
    e = bov.contar_bovinos_video(bov.EntradaContarBovinos(caminho_video=str(tmp_path / "nao_existe.mp4")))
    assert not e.ok and e.error.code == CodigoErro.ENTRADA_INVALIDA

    lixo = tmp_path / "lixo.mp4"
    lixo.write_bytes(b"isto nao e video" * 10)
    monkeypatch.setattr(bov, "_hash_modelo", lambda c: bov.MODELOS[bov.MODELO_PADRAO].sha256)
    monkeypatch.setattr(bov.MODELOS[bov.MODELO_PADRAO].__class__, "caminho", property(lambda self: lixo))
    monkeypatch.setattr("laudo.vision.detector.carregar_detector", lambda *a, **k: DetectorCor())
    e2 = bov.contar_bovinos_video(bov.EntradaContarBovinos(caminho_video=str(lixo)))
    assert not e2.ok and e2.error.code == CodigoErro.ENTRADA_INVALIDA


def test_ferramenta_sem_modelo(tmp_path, monkeypatch, video):
    import laudo.tools.bovinos as bov

    monkeypatch.setattr(bov.MODELOS[bov.MODELO_PADRAO].__class__, "caminho",
                        property(lambda self: tmp_path / "ausente.onnx"))
    e = bov.contar_bovinos_video(bov.EntradaContarBovinos(caminho_video=str(video)))
    assert not e.ok and e.error.code == CodigoErro.SEM_DADOS and "baixar_modelos" in e.error.msg


def test_ferramenta_com_detector_falso(tmp_path, monkeypatch, video):
    import laudo.tools.bovinos as bov

    falso = tmp_path / "falso.onnx"
    falso.write_bytes(b"x")
    monkeypatch.setattr(bov.MODELOS[bov.MODELO_PADRAO].__class__, "caminho", property(lambda self: falso))
    monkeypatch.setattr(bov, "_hash_modelo", lambda c: bov.MODELOS[bov.MODELO_PADRAO].sha256)
    monkeypatch.setattr("laudo.vision.detector.carregar_detector", lambda *a, **k: DetectorCor())
    e = bov.contar_bovinos_video(bov.EntradaContarBovinos(caminho_video=str(video), fps_amostragem=8,
                                                          dir_evidencias=str(tmp_path / "ev")))
    assert e.ok, e.error
    assert e.data["video"]["sha256"] == sha256_arquivo(str(video))
    assert e.data["modelo"]["licenca"] == "Apache-2.0"
    assert e.fonte_versao.startswith(f"{bov.MODELO_PADRAO}@")
    assert e.data["contagem"] in (2, 3)  # min_acertos padrão (3) pode perder a borda do vídeo curto


def test_camera_em_movimento_abstem(tmp_path):
    """Panorâmica sobre pasto texturizado com dois animais parados: ids_unicos deve se abster."""
    p = tmp_path / "pan.mp4"
    rng = np.random.default_rng(1)
    grande = cv2.GaussianBlur(rng.integers(0, 255, (A, L * 3), dtype=np.uint8), (0, 0), 1.2)
    grande = cv2.merge([grande // 4 + 30, grande // 3 + 80, grande // 4 + 40])
    for x in (300, 420):
        cv2.rectangle(grande, (x, 60), (x + 28, 78), (0, 0, 220), -1)
    with av.open(str(p), "w") as c:
        s = c.add_stream("mpeg4", rate=FPS)
        s.width, s.height, s.pix_fmt, s.bit_rate = L, A, "yuv420p", 2_000_000
        for q in range(int(4 * FPS)):
            img = np.ascontiguousarray(grande[:, q * 5:q * 5 + L])
            for pk in s.encode(av.VideoFrame.from_ndarray(img, format="bgr24")):
                c.mux(pk)
        for pk in s.encode():
            c.mux(pk)
    r = processar_video(str(p), DetectorCor(), ParametrosContagem(modo="ids_unicos", min_duracao_s=0.5),
                        ConfigPipeline(fps_amostragem=8, min_acertos=2))
    assert r["movimento_camera"]["translacao_liquida"] > 0.35
    assert r["abstencao"] and any(m["codigo"] == "CAMERA_EM_MOVIMENTO" for m in r["motivos"])
