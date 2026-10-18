"""Pipeline de contagem de bovinos em vídeo: amostragem → detecção → rastreamento → costura → contagem.

O detector é injetável (qualquer objeto com `detectar(img_bgr, limiar) -> (K, ≥6)`), o que permite
testar o pipeline inteiro com um detector sintético, sem o modelo ONNX.
"""

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from laudo.vision.anotacao import anotar
from laudo.vision.contagem import (
    Cadeia,
    ParametrosContagem,
    ResultadoContagem,
    alargar_por_oclusao,
    avaliar,
    contar_ids,
    contar_linha,
    costurar,
    linha_automatica,
)
from laudo.vision.detector import COCO_VACA, fracao_coberta
from laudo.vision.rastreador import Rastreador
from laudo.vision.video import info_video, iterar_quadros, qualidade_quadro

VERSAO_CONTADOR = "contador@0.2.0"


class Detector(Protocol):
    def detectar(self, img_bgr: np.ndarray, limiar: float | None = None) -> np.ndarray: ...


@dataclass
class ConfigPipeline:
    fps_amostragem: float = 8.0
    lado_max: int = 1280
    max_duracao_s: float = 180.0
    limiar_deteccao: float = 0.25  # score mínimo que entra no rastreador (estágio "baixo")
    limiar_alto: float = 0.5  # score que cria/associa trilhas no 1º estágio
    max_idade_s: float = 1.0  # tempo sem detecção até encerrar uma trilha
    min_acertos: int = 3
    n_quadros_chave: int = 4
    luminancia_min: float = 35.0
    nitidez_min: float = 15.0
    cobertura_oclusao: float = 0.25  # caixa com ≥ 25% da área coberta por outra conta como ocluída


class MovimentoCamera:
    """Estima o movimento global da câmera entre quadros (fluxo ótico esparso + afim parcial RANSAC).

    Acumula translação líquida e caminho (em larguras de quadro) e zoom líquido (log da escala).
    Tremor de mão se cancela na translação líquida; panorâmica e carro andando, não. Os pontos são
    buscados fora das caixas detectadas (os animais se movem; o fundo é que denuncia a câmera).
    """

    def __init__(self, largura_trabalho: int = 320):
        self.lt = largura_trabalho
        self.ant: np.ndarray | None = None
        self.mascara_ant: np.ndarray | None = None
        self.tx = self.ty = self.log_s = self.caminho = 0.0
        self.n_pares = self.n_falhas = 0

    def passo(self, img: np.ndarray, caixas: np.ndarray | None = None) -> None:
        h, w = img.shape[:2]
        g = cv2.cvtColor(cv2.resize(img, (self.lt, max(1, int(h * self.lt / w))), interpolation=cv2.INTER_AREA),
                         cv2.COLOR_BGR2GRAY)
        mascara = np.full(g.shape, 255, np.uint8)
        f = self.lt / w
        for x1, y1, x2, y2 in (caixas if caixas is not None else []):
            mx, my = (x2 - x1) * 0.25, (y2 - y1) * 0.25
            cv2.rectangle(mascara, (int((x1 - mx) * f), int((y1 - my) * f)), (int((x2 + mx) * f), int((y2 + my) * f)),
                          0, -1)
        if self.ant is not None and self.ant.shape == g.shape:
            self.n_pares += 1
            m = None
            p0 = cv2.goodFeaturesToTrack(self.ant, 300, 0.01, 7, mask=self.mascara_ant)
            if p0 is not None and len(p0) >= 20:
                p1, st, _ = cv2.calcOpticalFlowPyrLK(self.ant, g, p0, None, winSize=(21, 21), maxLevel=3)
                ok = st.ravel() == 1
                if ok.sum() >= 20:
                    m, inl = cv2.estimateAffinePartial2D(p0[ok], p1[ok], method=cv2.RANSAC,
                                                         ransacReprojThreshold=2.0)
                    n_inl = int(inl.sum()) if inl is not None else 0
                    if n_inl < 15 or n_inl < 0.5 * ok.sum():
                        m = None  # pouca concordância: quadro escuro/ruidoso ou dominado pelos animais
            if m is None:
                self.n_falhas += 1
            else:
                s = math.hypot(m[0, 0], m[1, 0])
                cx, cy = g.shape[1] / 2, g.shape[0] / 2
                dx = m[0, 0] * cx + m[0, 1] * cy + m[0, 2] - cx
                dy = m[1, 0] * cx + m[1, 1] * cy + m[1, 2] - cy
                self.tx += dx / self.lt
                self.ty += dy / self.lt
                self.caminho += math.hypot(dx, dy) / self.lt
                self.log_s += math.log(max(s, 1e-3))
        self.ant = g
        self.mascara_ant = mascara

    def resumo(self) -> dict:
        validos = self.n_pares - self.n_falhas
        return {"translacao_liquida": round(math.hypot(self.tx, self.ty), 3), "zoom_liquido": round(self.log_s, 3),
                "caminho": round(self.caminho, 3), "pares": self.n_pares, "falhas": self.n_falhas,
                "confiavel": self.n_pares > 0 and validos >= 0.5 * self.n_pares}


def _salvar_jpeg(img: np.ndarray, caminho: Path) -> str:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        raise RuntimeError("falha ao codificar JPEG")
    dados = buf.tobytes()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(dados)  # imencode + write_bytes funciona com caminho não ASCII no Windows
    return hashlib.sha256(dados).hexdigest()


def _escolher_quadros(res: ResultadoContagem, cadeias: list[Cadeia], n_proc: int, n: int) -> list[int]:
    if n_proc == 0:
        return []
    n = max(3, min(6, n))
    por_quadro: dict[int, int] = {}
    contadas = set(res.ids_contados)
    for c in cadeias:
        if c.id in contadas:
            for o in c.obs:
                por_quadro[o.quadro] = por_quadro.get(o.quadro, 0) + 1
    escolhidos: list[int] = []
    if por_quadro:
        escolhidos.append(max(por_quadro, key=lambda q: (por_quadro[q], -q)))
    qs = [c["quadro"] for c in res.eventos] if res.modo == "linha" else sorted(por_quadro)
    vagas = n - 1 - len(escolhidos)
    if qs and vagas > 0:
        for k in np.linspace(0, len(qs) - 1, min(vagas, len(qs))):
            escolhidos.append(int(qs[round(k)]))
    escolhidos.append(n_proc - 1)
    unicos = sorted(set(escolhidos))
    for k in np.linspace(0, n_proc - 1, n):  # completa com quadros espaçados se faltar
        if len(unicos) >= min(n, n_proc):
            break
        unicos = sorted(set(unicos) | {int(k)})
    return unicos[:n]


def processar_video(caminho: str, detector: Detector, params: ParametrosContagem | None = None,
                    cfg: ConfigPipeline | None = None, dir_evidencias: str | Path | None = None,
                    prefixo: str = "quadro") -> dict:
    """Conta bovinos no vídeo. Devolve um dicionário serializável (ver tools/bovinos.py)."""
    params = params or ParametrosContagem()
    cfg = cfg or ConfigPipeline()
    t0 = time.perf_counter()
    info = info_video(caminho)
    fps_proc_alvo = min(cfg.fps_amostragem, info.fps)
    max_idade = max(2, round(cfg.max_idade_s * fps_proc_alvo))
    rast = Rastreador(limiar_alto=cfg.limiar_alto, limiar_baixo=cfg.limiar_deteccao, max_idade=max_idade,
                      min_acertos=cfg.min_acertos)
    cam = MovimentoCamera()

    indices_decod: list[int] = []
    tempos: list[float] = []
    n_ruins = n_dets_altas = n_sobrepostas = n_outra_classe = 0
    t_det = 0.0
    largura = altura = 0
    for q in iterar_quadros(caminho, fps_proc_alvo, cfg.lado_max, cfg.max_duracao_s):
        altura, largura = q.img.shape[:2]
        lum, nit = qualidade_quadro(q.img)
        if lum < cfg.luminancia_min or nit < cfg.nitidez_min:
            n_ruins += 1
        td = time.perf_counter()
        dets = detector.detectar(q.img, cfg.limiar_deteccao)
        t_det += time.perf_counter() - td
        cam.passo(q.img, dets[:, :4] if len(dets) else None)
        altas = dets[dets[:, 4] >= cfg.limiar_alto] if len(dets) else dets
        if len(altas):
            n_dets_altas += len(altas)
            if len(altas) > 1:
                n_sobrepostas += int((fracao_coberta(altas[:, :4]).max(axis=1) >= cfg.cobertura_oclusao).sum())
            if altas.shape[1] >= 6:
                n_outra_classe += int((altas[:, 5].astype(int) != COCO_VACA).sum())
        rast.passo(dets[:, :6] if len(dets) else np.zeros((0, 6)))
        indices_decod.append(q.indice_decod)
        tempos.append(q.t_s)
    trilhas = rast.finalizar()
    n_proc = len(indices_decod)
    dur_proc = (tempos[-1] - tempos[0] + 1.0 / fps_proc_alvo) if n_proc else 0.0
    truncado = bool(info.duracao_s and info.duracao_s > cfg.max_duracao_s + 0.5)
    fps_proc = n_proc / dur_proc if dur_proc > 0 else 0.0
    cadeias = costurar(trilhas, max(1, round(params.max_gap_costura_s * (fps_proc or fps_proc_alvo))),
                       params.max_dist_costura)

    houve_mov = eixo = linha_px = None
    lw, lh = max(largura, 1), max(altura, 1)
    if params.modo == "linha":
        auto, eixo, houve_mov = linha_automatica(cadeias, lw, lh)
        if params.linha is not None:
            x1, y1, x2, y2 = params.linha
            linha_px = (x1 * largura, y1 * altura, x2 * largura, y2 * altura)
        else:
            linha_px = auto
        res = contar_linha(cadeias, linha_px, largura, altura, max(n_proc - 1, 0), max_idade, params)
    else:
        res = contar_ids(cadeias, fps_proc or fps_proc_alvo, params)

    movimento = cam.resumo()
    alargar_por_oclusao(res, n_sobrepostas / max(n_dets_altas, 1), params)
    status, abstencao, conf_media, cobertura = avaliar(
        res, cadeias, params, frac_quadros_ruins=n_ruins / max(n_proc, 1),
        oclusao=n_sobrepostas / max(n_dets_altas, 1), frac_outra_classe=n_outra_classe / max(n_dets_altas, 1),
        truncado=truncado, houve_movimento=houve_mov, duracao_s=dur_proc, camera=movimento)

    quadros_chave = _quadros_chave(caminho, cfg, res, cadeias, indices_decod, linha_px, dir_evidencias, prefixo) \
        if dir_evidencias is not None and n_proc else []

    t_total = time.perf_counter() - t0
    return {
        "contagem": res.contagem,
        "intervalo": [int(res.intervalo[0]), int(res.intervalo[1])],
        "modo": res.modo,
        "status": status,
        "abstencao": abstencao,
        "motivos": [m.como_dict() for m in res.motivos],
        "n_frames": n_proc,
        "n_frames_video": info.n_quadros,
        "fps_video": round(info.fps, 3),
        "fps_processado": round(fps_proc, 3),
        "duracao_video_s": round(info.duracao_s, 2) if info.duracao_s else None,
        "duracao_processada_s": round(dur_proc, 2),
        "resolucao_processada": [largura, altura],
        "limiar": {"deteccao": cfg.limiar_deteccao, "alto": cfg.limiar_alto,
                   "conf_media_min": params.limiar_conf_media, "cobertura_min": params.min_cobertura,
                   "max_meia_largura_rel": params.max_meia_largura_rel},
        "conf_media": round(conf_media, 3),
        "cobertura": round(cobertura, 3),
        "oclusao": round(n_sobrepostas / max(n_dets_altas, 1), 3),
        "frac_quadros_ruins": round(n_ruins / max(n_proc, 1), 3),
        "frac_outra_classe": round(n_outra_classe / max(n_dets_altas, 1), 3),
        "movimento_camera": movimento,
        "n_trilhas": len(trilhas),
        "n_cadeias": len(cadeias),
        "eixo_movimento": eixo,
        "detalhes": res.detalhes,
        "eventos": res.eventos[:200],
        "quadros_chave": quadros_chave,
        "tempo_total_s": round(t_total, 2),
        "tempo_deteccao_s": round(t_det, 2),
        "s_por_s_video": round(t_total / dur_proc, 3) if dur_proc > 0 else None,
        "parametros": {k: (list(v) if isinstance(v, tuple) else v) for k, v in asdict(params).items()},
        "config": asdict(cfg),
        "versao": VERSAO_CONTADOR,
    }


def _quadros_chave(caminho: str, cfg: ConfigPipeline, res: ResultadoContagem, cadeias: list[Cadeia],
                   indices_decod: list[int], linha_px, dir_evidencias, prefixo: str) -> list[dict]:
    """Segunda passada só nos quadros escolhidos: desenha e salva JPEG com sha256."""
    escolhidos = _escolher_quadros(res, cadeias, len(indices_decod), cfg.n_quadros_chave)
    alvo = {indices_decod[k]: k for k in escolhidos}
    contadas = set(res.ids_contados)
    obs_por_quadro: dict[int, list] = {}
    for c in cadeias:
        for o in c.obs:
            if o.quadro in alvo.values():
                obs_por_quadro.setdefault(o.quadro, []).append((c.id, o.caixa, o.score, c.id in contadas))
    out = []
    for q in iterar_quadros(caminho, 0, cfg.lado_max, cfg.max_duracao_s, indices=set(alvo)):
        k = alvo[q.indice_decod]
        if res.modo == "linha":
            ate = max([c["acumulado"] for c in res.eventos if c["quadro"] <= k], default=0)
        else:
            ate = sum(1 for c in cadeias if c.id in contadas and c.inicio <= k)
        titulo = (f"Laudo Vivo | {res.modo} | ate aqui: {ate} | final: {res.contagem} "
                  f"[{res.intervalo[0]}-{res.intervalo[1]}] | t={q.t_s:.1f}s")
        img = anotar(q.img, obs_por_quadro.get(k, []), linha_px, titulo,
                     rodape=f"quadro {q.indice_decod} | verde = contado | cinza = nao contado")
        destino = Path(dir_evidencias) / f"{prefixo}_{q.indice_decod:06d}.jpg"
        out.append({"caminho": destino.as_posix(), "sha256": _salvar_jpeg(img, destino),
                    "quadro": q.indice_decod, "t_s": round(q.t_s, 2), "contagem_ate_aqui": ate})
    return out
