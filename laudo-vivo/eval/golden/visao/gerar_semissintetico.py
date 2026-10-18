"""Gera vídeos semissintéticos de corredor com contagem exata conhecida.

Recortes REAIS de bovinos (detectados com alta confiança nos vídeos v03 e v04 do Commons) andam em fila,
da esquerda para a direita, sobre um fundo de pasto com cerca de corredor. Serve para medir o modo
"linha" (recomendado) enquanto não há vídeo real de curral/brete da equipe. Não substitui vídeo real:
o movimento é sintético (velocidade constante, sem cabeça baixa, sem poeira).

Uso (raiz do repositório):
    scripts/py.sh eval/golden/visao/gerar_semissintetico.py
Saída: dados_locais/videos/sinteticos/{id}.mp4 + manifesto.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import av
import cv2
import numpy as np
import yaml

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ / "src"))

from laudo.contracts import sha256_arquivo
from laudo.vision.detector import DetectorYOLOX, iou_matriz
from laudo.vision.modelos import MODELOS
from laudo.vision.video import iterar_quadros

REF = Path(__file__).with_name("contagens_referencia.yaml")
SAIDA = RAIZ / "dados_locais" / "videos" / "sinteticos"
L, A, FPS = 854, 480, 15
FONTES = [("v03_zebuinos_estabulo", [x * 2.0 for x in range(13)]),
          ("v04_manejo_a_cavalo", [x * 0.5 for x in range(32)])]
# Curadoria visual (08/10/2026) dos 40 recortes extraídos: ficam só os de UM animal inteiro. Saem os que
# têm duas vacas sobrepostas (0, 2–5, 12, 15, 19), close parcial (1, 8, 13, 17, 20) e corpo cortado (30, 31).
# São 5 animais distintos em poses diferentes (zebu branco, zebu vermelho, taurino claro, Belted, preto).
N_RECORTES_ESPERADO = 40
CURADOS = [6, 9, 10, 11, 14, 16, 18, 21, 22, 24, 26, 28, 29, 32, 33, 34, 35, 36, 37]


def extrair_recortes(det: DetectorYOLOX) -> list[np.ndarray]:
    """Recortes BGRA (alfa elíptico suavizado) de bovinos isolados e nítidos."""
    recortes = []
    for vid, tempos in FONTES:
        caminho = RAIZ / "dados_locais" / "videos" / f"{vid}.webm"
        k = 0
        for q in iterar_quadros(str(caminho), fps_amostragem=30, lado_max=854):
            if k >= len(tempos) or q.t_s < tempos[k]:
                continue
            k += 1
            d = det.detectar(q.img, 0.3)
            if not len(d):
                continue
            iou = iou_matriz(d[:, :4], d[:, :4])
            np.fill_diagonal(iou, 0)
            h_img, w_img = q.img.shape[:2]
            for i, (x1, y1, x2, y2, s, *_r) in enumerate(d):
                w, h = x2 - x1, y2 - y1
                if s < 0.75 or iou[i].max() > 0.06 or h < 70 or not (0.9 <= w / h <= 2.6):
                    continue
                if x1 < 3 or y1 < 3 or x2 > w_img - 3 or y2 > h_img - 3:
                    continue
                c = q.img[int(y1):int(y2), int(x1):int(x2)].copy()
                alfa = np.zeros(c.shape[:2], np.uint8)
                cv2.ellipse(alfa, (c.shape[1] // 2, c.shape[0] // 2),
                            (int(c.shape[1] * 0.49), int(c.shape[0] * 0.49)), 0, 0, 360, 255, -1)
                alfa = cv2.GaussianBlur(alfa, (0, 0), max(1.0, c.shape[0] / 25))
                recortes.append(np.dstack([c, alfa]))
    return recortes


def fundo(rng: np.random.Generator) -> np.ndarray:
    """Pasto (ladrilho espelhado de um trecho sem animais do v04) com cerca de corredor."""
    src = next(iter(q.img for q in iterar_quadros(str(RAIZ / "dados_locais/videos/v04_manejo_a_cavalo.webm"),
                                                  fps_amostragem=30, lado_max=854) if q.t_s >= 5.6))
    p = src[300:480, 0:290]
    lin = np.hstack([p, p[:, ::-1], p, p[:, ::-1]])
    tile = np.vstack([lin, lin[::-1], lin])[:A, :L].copy()
    tile = cv2.GaussianBlur(tile, (0, 0), 0.7)
    for y in (175, 190):  # cerca do fundo
        cv2.line(tile, (0, y), (L, y), (40, 70, 110), 5)
    for x in range(20, L, 140):
        cv2.line(tile, (x, 160), (x, 200), (35, 60, 95), 9)
    return tile


def cerca_frente(img: np.ndarray) -> None:
    for y in (430, 448):
        cv2.line(img, (0, y), (L, y), (45, 80, 125), 7)
    for x in range(60, L, 160):
        cv2.line(img, (x, 405), (x, A), (35, 60, 95), 11)


def colar(img: np.ndarray, rec: np.ndarray, cx: float, cy: float) -> None:
    h, w = rec.shape[:2]
    x1, y1 = round(cx - w / 2), round(cy - h / 2)
    xa, ya, xb, yb = max(0, x1), max(0, y1), min(L, x1 + w), min(A, y1 + h)
    if xa >= xb or ya >= yb:
        return
    r = rec[ya - y1:yb - y1, xa - x1:xb - x1]
    a = r[..., 3:4].astype(np.float32) / 255
    img[ya:yb, xa:xb] = (r[..., :3] * a + img[ya:yb, xa:xb] * (1 - a)).astype(np.uint8)


def gerar(cen: dict, recortes: list[np.ndarray], rng: np.random.Generator) -> dict:
    n, faixas, voltam = cen["n"], cen["faixas"], cen.get("voltam", 0)
    ys = {1: [310], 2: [285, 335], 3: [265, 310, 355]}[faixas]
    animais, t = [], 0.5
    for i in range(n):
        rec = recortes[int(rng.integers(len(recortes)))]
        alvo_h = rng.uniform(105, 150)
        esc = min(alvo_h / rec.shape[0], 1.4)
        rec = cv2.resize(rec, (int(rec.shape[1] * esc), int(rec.shape[0] * esc)), interpolation=cv2.INTER_AREA
                         if esc < 1 else cv2.INTER_LINEAR)
        if rng.random() < 0.5:
            rec = rec[:, ::-1].copy()
        v = rng.uniform(*cen["velocidade_px_s"])
        animais.append({"rec": rec, "t0": t, "v": v, "y": float(rng.choice(ys)) + rng.normal(0, 6),
                        "volta": i in set(range(1, 1 + voltam)), "fase": 0})
        t += rng.uniform(*cen["gap_s"])
    fundo_img = fundo(rng)
    SAIDA.mkdir(parents=True, exist_ok=True)
    caminho = SAIDA / f"{cen['id']}.mp4"
    with av.open(str(caminho), "w") as c:
        s = c.add_stream("libx264", rate=FPS)
        s.width, s.height, s.pix_fmt = L, A, "yuv420p"
        s.options = {"crf": "23", "preset": "medium"}
        q = 0
        while True:
            tq = q / FPS
            img = fundo_img.copy()
            vivos = 0
            for a in sorted(animais, key=lambda a: a["y"]):
                w = a["rec"].shape[1]
                if tq < a["t0"]:
                    vivos += 1
                    continue
                x = -w / 2 + a["v"] * (tq - a["t0"])
                if a["volta"]:  # anda até 70% da largura e volta para a esquerda
                    x_max = 0.7 * L
                    if x > x_max:
                        x = x_max - (x - x_max)
                        if a["fase"] == 0:
                            a["rec"] = a["rec"][:, ::-1].copy()
                            a["fase"] = 1
                    if x < -w / 2:
                        continue
                elif x > L + w / 2:
                    continue
                vivos += 1
                colar(img, a["rec"], x, a["y"] + 2 * np.sin(tq * 6 + a["t0"]))
            cerca_frente(img)
            ruido = rng.normal(0, 3, img.shape).astype(np.float32)
            img = np.clip(img.astype(np.float32) * rng.uniform(0.97, 1.03) + ruido, 0, 255).astype(np.uint8)
            for p in s.encode(av.VideoFrame.from_ndarray(img, format="bgr24")):
                c.mux(p)
            q += 1
            if vivos == 0 or tq > 120:
                break
        for p in s.encode():
            c.mux(p)
    return {"id": cen["id"], "arquivo": caminho.relative_to(RAIZ).as_posix(), "sha256": sha256_arquivo(str(caminho)),
            "n_animais": n, "referencia_linha": n - voltam, "referencia_ids": n, "fps": FPS,
            "duracao_s": round(q / FPS, 2), "cenario": {k: v for k, v in cen.items() if k != "id"}}


def main() -> int:
    ref = yaml.safe_load(REF.read_text(encoding="utf-8"))["semissinteticos"]
    rng = np.random.default_rng(ref["semente"])
    det = DetectorYOLOX(MODELOS["yolox_m"].caminho)
    recortes = extrair_recortes(det)
    print(f"{len(recortes)} recortes de bovinos isolados")
    if len(recortes) != N_RECORTES_ESPERADO:
        raise SystemExit(f"esperava {N_RECORTES_ESPERADO} recortes (curadoria feita sobre eles); "
                         "confira os vídeos/modelo ou refaça a curadoria")
    recortes = [recortes[i] for i in CURADOS]
    manifesto = [gerar(c, recortes, rng) for c in ref["cenarios"]]
    (SAIDA / "manifesto.json").write_text(json.dumps(manifesto, ensure_ascii=False, indent=1), encoding="utf-8")
    for m in manifesto:
        print(m["id"], m["n_animais"], m["referencia_linha"], m["duracao_s"], "s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
