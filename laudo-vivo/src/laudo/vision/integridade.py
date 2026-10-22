"""Integridade de foto: EXIF, horário, hash, duplicata, nitidez e heurística de "foto de tela".

Tudo determinístico e local. A heurística de tela é um sinal, não uma prova: combina moiré
cromático, picos periódicos no espectro (grade de pixels), retângulo de moldura e ausência de câmera
no EXIF. Limiar inicial calibrado só em imagens sintéticas; precisa de calibração com fotos reais.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import cv2
import imagehash
import numpy as np
from PIL import Image

from laudo.formatacao import fmt_br

VERSAO_INTEGRIDADE = "integridade@0.1.1"

SOFTWARE_EDICAO = ("photoshop", "gimp", "lightroom", "snapseed", "picsart", "canva", "facetune", "pixlr",
                   "affinity", "paint.net", "faceapp", "remini", "airbrush", "vsco", "meitu")
# Resoluções típicas de captura de tela (largura × altura, em qualquer orientação).
RESOLUCOES_TELA = {(1080, 1920), (1080, 2400), (1080, 2340), (1170, 2532), (1179, 2556), (1284, 2778),
                   (1290, 2796), (720, 1600), (720, 1280), (1440, 3200), (1366, 768), (1920, 1080),
                   (1440, 900), (1536, 864), (2560, 1440), (1280, 720), (828, 1792), (750, 1334)}
# GPS do app bom o bastante para dispensar o GPS do EXIF (o mesmo limite de precisão do geofence, 30 m). Fora de
# ParametrosIntegridade de propósito: os parâmetros vão na saída de toda foto e mudariam o resultado gravado.
PRECISAO_APP_MAX_M = 30.0


@dataclass
class ParametrosIntegridade:
    max_atraso_h: float = 72.0  # captura até X h antes do recebimento (parâmetro operacional)
    max_adiantado_s: float = 300.0  # captura "no futuro" além disso = relógio incoerente
    max_delta_gps_s: float = 3600.0  # diferença tolerada entre DateTimeOriginal e o horário GPS (UTC)
    limiar_nitidez: float = 60.0
    limiar_phash: int = 6
    limiar_tela_divergente: float = 0.6
    limiar_tela_indeterminado: float = 0.4
    max_dist_gps_m: float = 100.0  # EXIF × GPS do app
    fuso_horas: float = -3.0  # Goiás (UTC-3, sem horário de verão desde 2019)
    exigir_gps: bool = True


def _motivo(codigo: str, severidade: str, msg: str) -> dict:
    return {"codigo": codigo, "severidade": severidade, "msg": msg}


# ---------------------------------------------------------------------------
# EXIF
# ---------------------------------------------------------------------------


def _racional(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _dms(v: Any) -> float | None:
    try:
        g, m, s = (float(x) for x in v)
        return g + m / 60 + s / 3600
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _data_exif(s: Any, offset: Any, fuso_padrao: timezone) -> tuple[datetime | None, bool]:
    """Data do EXIF sempre com fuso. Devolve (data, fuso_assumido).

    O EXIF guarda hora local sem fuso; se não houver OffsetTime*, assume `fuso_padrao` e avisa.
    """
    if not s or not isinstance(s, str):
        return None, False
    assumido = not (isinstance(offset, str) and re.fullmatch(r"[+-]\d\d:\d\d", offset.strip()))
    if assumido:
        seg = int(fuso_padrao.utcoffset(None).total_seconds())
        offset = f"{'+' if seg >= 0 else '-'}{abs(seg) // 3600:02d}:{abs(seg) % 3600 // 60:02d}"
    try:
        return datetime.strptime(s.strip()[:19] + offset.strip().replace(":", ""), "%Y:%m:%d %H:%M:%S%z"), assumido
    except ValueError:
        return None, False


def ler_exif(img: Image.Image) -> tuple[dict, dict | None]:
    """Devolve (exif resumido, gps_exif ou None). Valores já convertidos para tipos simples."""
    ex = img.getexif()
    sub = ex.get_ifd(0x8769) if ex else {}
    gps = ex.get_ifd(0x8825) if ex else {}

    def txt(v: Any) -> str | None:
        if v is None:
            return None
        if isinstance(v, bytes):
            v = v.decode("utf-8", "ignore")
        return str(v).strip("\x00 ").strip() or None

    resumo = {
        "presente": bool(ex) and len(ex) > 0,
        "fabricante": txt(ex.get(0x010F)),
        "modelo": txt(ex.get(0x0110)),
        "software": txt(ex.get(0x0131)),
        "data_hora_original": txt(sub.get(0x9003)),
        "data_hora_digitalizada": txt(sub.get(0x9004)),
        "data_hora_modificacao": txt(ex.get(0x0132)),
        "offset_original": txt(sub.get(0x9011)),
        "orientacao": ex.get(0x0112),
        "n_tags": len(ex) + len(sub) + len(gps),
    }
    gps_out = None
    if gps:
        lat, lon = _dms(gps.get(2)), _dms(gps.get(4))
        if lat is not None and lon is not None:
            if txt(gps.get(1)) == "S":
                lat = -lat
            if txt(gps.get(3)) == "W":
                lon = -lon
            data_gps = None
            if gps.get(0x1D) and gps.get(7):
                try:
                    h, m, s = (float(x) for x in gps.get(7))
                    d = datetime.strptime(txt(gps.get(0x1D)) + "+0000", "%Y:%m:%d%z")
                    data_gps = (d + timedelta(hours=h, minutes=m, seconds=s)).astimezone(UTC)
                except (TypeError, ValueError):
                    data_gps = None
            gps_out = {"lat": round(lat, 7), "lon": round(lon, 7),
                       "precisao_m": _racional(gps.get(0x1F)),
                       "altitude_m": _racional(gps.get(6)),
                       "data_hora_utc": data_gps.isoformat() if data_gps else None}
    return resumo, gps_out


# ---------------------------------------------------------------------------
# Sinais de imagem
# ---------------------------------------------------------------------------


def _reduzir(arr: np.ndarray, lado: int = 1024) -> np.ndarray:
    h, w = arr.shape[:2]
    r = lado / max(h, w)
    if r >= 1:
        return arr
    return cv2.resize(arr, (max(1, int(w * r)), max(1, int(h * r))), interpolation=cv2.INTER_AREA)


def nitidez(bgr: np.ndarray) -> float:
    """Variância do Laplaciano no cinza reduzido a 1024 px (escala fixa, comparável entre fotos)."""
    cinza = cv2.cvtColor(_reduzir(bgr), cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(cinza, cv2.CV_64F).var())


def _rampa(x: float, a: float, b: float) -> float:
    """0 abaixo de a, 1 acima de b, linear entre os dois."""
    return float(min(1.0, max(0.0, (x - a) / (b - a))))


def sinais_tela(bgr: np.ndarray, exif: dict, formato: str | None) -> tuple[float, dict]:
    """Score 0–1 de "foto de tela/captura de tela" e os sinais que o compõem."""
    peq = _reduzir(bgr, 768).astype(np.float32)
    ycc = cv2.cvtColor(peq.astype(np.uint8), cv2.COLOR_BGR2YCrCb).astype(np.float32)

    def energia_alta(c: np.ndarray) -> float:
        return float(np.mean(np.abs(c - cv2.GaussianBlur(c, (0, 0), 1.5))))

    e_y = energia_alta(ycc[..., 0]) + 1e-3
    razao_croma = (energia_alta(ycc[..., 1]) + energia_alta(ycc[..., 2])) / e_y

    # picos periódicos (grade de pixels/subpixels) no espectro de amplitude do luma, fora dos eixos
    y = ycc[..., 0] - ycc[..., 0].mean()
    h, w = y.shape
    janela = np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)
    f = np.abs(np.fft.fftshift(np.fft.fft2(y * janela)))
    yy, xx = np.mgrid[-(h // 2):h - h // 2, -(w // 2):w - w // 2]
    r = np.sqrt((yy / (h / 2)) ** 2 + (xx / (w / 2)) ** 2)
    anel = (r > 0.15) & (r < 0.95) & (np.abs(yy) > 2) & (np.abs(xx) > 2)
    vals = f[anel]
    pico = float(vals.max() / (np.median(vals) + 1e-6)) if vals.size else 0.0

    # retângulo de moldura: linhas longas horizontais e verticais afastadas entre si
    cinza = cv2.cvtColor(peq.astype(np.uint8), cv2.COLOR_BGR2GRAY)
    bordas = cv2.Canny(cinza, 60, 160)
    linhas = cv2.HoughLinesP(bordas, 1, np.pi / 180, 80, minLineLength=int(0.5 * min(h, w)), maxLineGap=6)
    hs, vs = [], []
    for x1, y1, x2, y2 in (linhas[:, 0] if linhas is not None else []):
        ang = abs(math.degrees(math.atan2(y2 - y1, x2 - x1))) % 180
        if ang < 4 or ang > 176:
            hs.append((y1 + y2) / 2)
        elif 86 < ang < 94:
            vs.append((x1 + x2) / 2)
    retangulo = bool(hs and vs and (max(hs) - min(hs)) > 0.35 * h and (max(vs) - min(vs)) > 0.35 * w)

    sem_camera = not (exif.get("fabricante") or exif.get("modelo"))
    dims = (bgr.shape[1], bgr.shape[0])
    captura_tela = (formato or "").upper() == "PNG" and sem_camera and (
        dims in RESOLUCOES_TELA or dims[::-1] in RESOLUCOES_TELA)

    # rampas calibradas: quadros reais de vídeo (n = 37) ficaram com croma ≤ 0,47 e
    # pico ≤ 101; fotos de tela sintéticas (n = 9) com croma ≥ 1,48 e pico ≥ 850.
    s_croma = _rampa(razao_croma, 0.5, 1.2)
    s_pico = _rampa(pico, 120.0, 400.0)
    score = 0.35 * s_croma + 0.35 * s_pico + 0.15 * float(retangulo) + 0.15 * float(sem_camera)
    if captura_tela:
        score = max(score, 0.9)
    return round(min(1.0, score), 3), {
        "razao_croma_alta_freq": round(razao_croma, 3), "pico_espectral": round(pico, 1),
        "retangulo_moldura": retangulo, "sem_camera_exif": sem_camera, "captura_de_tela": captura_tela}


# ---------------------------------------------------------------------------
# Índice local de fotos (append-only, JSONL)
# ---------------------------------------------------------------------------


class IndiceFotos:
    def __init__(self, caminho: str | Path):
        self.caminho = Path(caminho)

    def entradas(self) -> list[dict]:
        if not self.caminho.is_file():
            return []
        out = []
        with open(self.caminho, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if ln:
                    try:
                        out.append(json.loads(ln))
                    except json.JSONDecodeError:
                        continue
        return out

    def buscar(self, sha: str, phash: str, caminho: str, contexto: str | None, limiar: int) -> list[dict]:
        ph = imagehash.hex_to_hash(phash)
        achados = []
        for e in self.entradas():
            mesma = e.get("caminho") == caminho and e.get("contexto") == contexto
            if mesma and e.get("sha256") == sha:
                continue  # a própria evidência, reprocessada
            if e.get("sha256") == sha:
                achados.append({**_resumo(e), "tipo": "exata", "distancia": 0})
                continue
            try:
                d = int(ph - imagehash.hex_to_hash(e["phash"]))
            except (KeyError, ValueError):
                continue
            if d <= limiar:
                achados.append({**_resumo(e), "tipo": "quase", "distancia": d})
        return sorted(achados, key=lambda a: a["distancia"])

    def registrar(self, sha: str, phash: str, caminho: str, contexto: str | None) -> bool:
        for e in self.entradas():
            if e.get("sha256") == sha and e.get("caminho") == caminho and e.get("contexto") == contexto:
                return False
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        with open(self.caminho, "a", encoding="utf-8") as f:
            f.write(json.dumps({"sha256": sha, "phash": phash, "caminho": caminho, "contexto": contexto,
                                "registrado_em": datetime.now(UTC).isoformat()}, ensure_ascii=False) + "\n")
        return True


def _resumo(e: dict) -> dict:
    return {"sha256": e.get("sha256"), "caminho": e.get("caminho"), "contexto": e.get("contexto")}


# ---------------------------------------------------------------------------
# Avaliação
# ---------------------------------------------------------------------------


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def avaliar_integridade(caminho: str | Path, sha256: str, recebida_em: datetime | None = None,
                        gps_app: tuple[float, float] | None = None, contexto: str | None = None,
                        indice: IndiceFotos | None = None, registrar: bool = True,
                        p: ParametrosIntegridade | None = None, precisao_app_m: float | None = None,
                        gps_app_simulado: bool = False) -> dict:
    """`precisao_app_m`/`gps_app_simulado`: precisão e "localização simulada" do GPS que o app mandou com a foto.
    Foto sem GPS no EXIF com GPS do app bom (precisão ≤ `PRECISAO_APP_MAX_M`, não simulado) não fica pendente
    por isso: SEM_GPS vira informação, porque a localização sai do GPS do app (o navegador do celular costuma tirar
    o GPS do EXIF da foto). Sem GPS do app, ou com precisão pior, SEM_GPS continua indeterminado."""
    p = p or ParametrosIntegridade()
    fuso = timezone(timedelta(hours=p.fuso_horas))
    recebida = recebida_em or datetime.now(fuso)
    if recebida.tzinfo is None:
        recebida = recebida.replace(tzinfo=fuso)
    motivos: list[dict] = []

    with Image.open(caminho) as img:
        formato = img.format
        largura, altura = img.size
        exif, gps_exif = ler_exif(img)
        if formato == "JPEG":
            img.draft("RGB", (2048, 2048))
        rgb = img.convert("RGB")
    ph = str(imagehash.phash(rgb))
    bgr = cv2.cvtColor(np.asarray(rgb), cv2.COLOR_RGB2BGR)
    del rgb

    # horário
    capturada, fuso_assumido = _data_exif(exif["data_hora_original"], exif["offset_original"], fuso)
    delta_s = None
    if capturada is not None:
        cap_tz = capturada
        delta_s = (recebida - cap_tz).total_seconds()
        if delta_s < -p.max_adiantado_s:
            motivos.append(_motivo("HORARIO_FUTURO", "divergente",
                                   f"captura {-delta_s / 60:.0f} min depois do recebimento (relógio adulterado?)"))
        elif delta_s > p.max_atraso_h * 3600:
            motivos.append(_motivo("FOTO_ANTIGA", "divergente",
                                   f"captura {fmt_br(delta_s / 3600, 1)} h antes do recebimento "
                                   f"(máx. {fmt_br(p.max_atraso_h)} h)"))
        if gps_exif and gps_exif.get("data_hora_utc"):
            d_gps = abs((cap_tz - datetime.fromisoformat(gps_exif["data_hora_utc"])).total_seconds())
            if d_gps > p.max_delta_gps_s:
                motivos.append(_motivo("HORARIO_GPS_INCOERENTE", "divergente",
                                       f"horário da câmera difere do horário GPS em {fmt_br(d_gps / 3600, 1)} h"))
        mod, _ = _data_exif(exif["data_hora_modificacao"], exif["offset_original"], fuso)
        if mod is not None and abs((mod - capturada).total_seconds()) > 60:
            motivos.append(_motivo("MODIFICADA_APOS_CAPTURA", "indeterminado",
                                   "data de modificação difere da captura (edição posterior?)"))
    elif exif["presente"]:
        motivos.append(_motivo("SEM_DATA_CAPTURA", "indeterminado", "EXIF sem data/hora de captura"))
    if not exif["presente"]:
        motivos.append(_motivo("SEM_EXIF", "indeterminado",
                               "foto sem EXIF (capturada fora do app ou metadados removidos); refaça a captura no app"))
    sw = (exif.get("software") or "").lower()
    if any(s in sw for s in SOFTWARE_EDICAO):
        motivos.append(_motivo("SOFTWARE_EDICAO", "indeterminado", f"EXIF indica edição: {exif['software']}"))

    # GPS
    dist_gps = None
    if gps_exif is None:
        app_bom = (gps_app is not None and precisao_app_m is not None and not gps_app_simulado
                   and 0 <= precisao_app_m <= PRECISAO_APP_MAX_M)
        if p.exigir_gps and app_bom:
            motivos.append(_motivo("SEM_GPS", "info",
                                   f"foto sem coordenada GPS no EXIF; vale o GPS do aparelho enviado com a foto "
                                   f"(±{fmt_br(precisao_app_m, 0)} m)"))
        elif p.exigir_gps:
            motivos.append(_motivo("SEM_GPS", "indeterminado", "foto sem coordenada GPS no EXIF"))
    elif gps_app is not None:
        dist_gps = _haversine_m(gps_exif["lat"], gps_exif["lon"], gps_app[0], gps_app[1])
        if dist_gps > p.max_dist_gps_m:
            motivos.append(_motivo("GPS_DIVERGENTE", "divergente",
                                   f"GPS do EXIF a {dist_gps:.0f} m do GPS do app (máx. {p.max_dist_gps_m:g} m)"))

    # nitidez e tela
    nit = nitidez(bgr)
    if nit < p.limiar_nitidez:
        motivos.append(_motivo("DESFOCADA", "indeterminado", f"nitidez {nit:.0f} < {p.limiar_nitidez:g}"))
    score_tela, sinais = sinais_tela(bgr, exif, formato)
    if sinais["captura_de_tela"]:
        motivos.append(_motivo("CAPTURA_DE_TELA", "divergente", "PNG sem câmera com resolução de tela"))
    elif score_tela >= p.limiar_tela_divergente:
        motivos.append(_motivo("FOTO_DE_TELA", "divergente", f"provável foto de tela (score {fmt_br(score_tela)})"))
    elif score_tela >= p.limiar_tela_indeterminado:
        motivos.append(_motivo("POSSIVEL_TELA", "indeterminado", f"sinais de foto de tela (score {fmt_br(score_tela)})"))

    # duplicatas
    duplicatas: list[dict] = []
    if indice is not None:
        duplicatas = indice.buscar(sha256, ph, str(caminho), contexto, p.limiar_phash)
        # Política de foto duplicada: a mesma foto na MESMA fiscalização é falha de captura
        # (indeterminado: pede nova foto, o campo fica pendente); a mesma foto (sha256 ou phash) já usada em
        # OUTRA fiscalização é reuso de evidência (divergente).
        for d in duplicatas:
            outro_ctx = d.get("contexto") != contexto
            if d["tipo"] == "exata" and outro_ctx:
                motivos.append(_motivo("DUPLICATA_EXATA", "divergente",
                                       f"mesmo arquivo já usado em outra fiscalização ({d['contexto']}): "
                                       "reuso de evidência"))
            elif d["tipo"] == "exata":
                motivos.append(_motivo("DUPLICATA_MESMA_FISCALIZACAO", "indeterminado",
                                       "mesmo arquivo já enviado nesta fiscalização como outra foto; "
                                       "tire uma nova foto de outro ângulo"))
            elif outro_ctx:
                motivos.append(_motivo("QUASE_DUPLICATA", "divergente",
                                       f"foto quase idêntica (dist. {d['distancia']}) em outro contexto "
                                       f"({d['contexto']})"))
            else:
                motivos.append(_motivo("FOTO_REPETIDA", "info",
                                       f"foto muito parecida (dist. {d['distancia']}) na mesma fiscalização"))
        if registrar:
            indice.registrar(sha256, ph, str(caminho), contexto)

    sev = {m["severidade"] for m in motivos}
    status = "divergente" if "divergente" in sev else ("indeterminado" if "indeterminado" in sev else "ok")
    return {
        "status": status,
        "motivos": motivos,
        "sha256": sha256,
        "phash": ph,
        "formato": formato,
        "dimensoes": [largura, altura],
        "exif": exif,
        "gps_exif": gps_exif,
        "capturada_em": capturada.isoformat() if capturada else None,
        "fuso_assumido": fuso_assumido if capturada else None,
        "recebida_em": recebida.isoformat(),
        "delta_captura_s": round(delta_s, 1) if delta_s is not None else None,
        "distancia_gps_app_m": round(dist_gps, 1) if dist_gps is not None else None,
        "duplicata_de": duplicatas,
        "nitidez": round(nit, 1),
        "score_tela": score_tela,
        "sinais_tela": sinais,
        "parametros": {k: getattr(p, k) for k in p.__dataclass_fields__},
        "versao": VERSAO_INTEGRIDADE,
    }
