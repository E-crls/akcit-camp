"""Fotos sintéticas (JPEG pequeno desenhado com Pillow) com EXIF e GPS controlados.

Servem para exercitar integridade de foto (EXIF, GPS, horário, duplicata) e geofence; não servem para
avaliar classificador visual. Make/Model/ImageDescription marcam a imagem como sintética.
"""

from __future__ import annotations

import io
import random
from datetime import datetime

from PIL import Image, ImageDraw

_TAMANHO = (320, 240)


def _gms(valor: float) -> tuple[float, float, float]:
    v = abs(valor)
    g = int(v)
    m = int((v - g) * 60)
    s = round((v - g - m / 60) * 3600, 2)
    return float(g), float(m), s


def _cena(rng: random.Random, tipo: str) -> Image.Image:
    w, h = _TAMANHO
    img = Image.new("RGB", _TAMANHO)
    dr = ImageDraw.Draw(img)
    horizonte = int(h * rng.uniform(0.35, 0.5))
    ceu = (rng.randint(120, 170), rng.randint(170, 205), rng.randint(220, 250))
    for y in range(horizonte):
        f = y / max(horizonte, 1)
        dr.line([(0, y), (w, y)], fill=tuple(int(c * (1 - 0.25 * f)) for c in ceu))
    pasto = (rng.randint(90, 140), rng.randint(120, 160), rng.randint(50, 80))
    dr.rectangle([0, horizonte, w, h], fill=pasto)
    for _ in range(400):  # textura do pasto
        x, y = rng.randrange(w), rng.randrange(horizonte, h)
        dr.point((x, y), fill=tuple(max(0, c + rng.randint(-25, 25)) for c in pasto))
    madeira = (rng.randint(90, 130), rng.randint(60, 85), rng.randint(30, 50))
    if tipo == "cerca":
        n = rng.randint(5, 9)
        for i in range(n):
            x = int((i + 0.5) * w / n + rng.randint(-6, 6))
            alto = int(h * rng.uniform(0.25, 0.35))
            base = horizonte + int((h - horizonte) * 0.55)
            dr.rectangle([x - 3, base - alto, x + 3, base], fill=madeira)
        for k in range(5):
            y = horizonte + int((h - horizonte) * 0.55) - int(h * 0.05 * (k + 1))
            dr.line([(0, y + rng.randint(-2, 2)), (w, y + rng.randint(-2, 2))], fill=(150, 150, 150), width=1)
    elif tipo == "curral":
        topo = horizonte - int(h * 0.05)
        for k in range(5):
            y = topo + k * int(h * 0.07)
            dr.rectangle([0, y, w, y + int(h * 0.035)], fill=madeira)
        for i in range(4):
            x = int((i + 0.5) * w / 4)
            dr.rectangle([x - 5, topo - 10, x + 5, topo + int(h * 0.35)], fill=tuple(c - 20 for c in madeira))
    else:  # lote de animais
        for _ in range(rng.randint(6, 14)):
            x, y = rng.randrange(20, w - 40), rng.randrange(horizonte + 10, h - 20)
            cor = rng.choice([(235, 235, 230), (210, 205, 200), (190, 185, 180)])
            dr.ellipse([x, y, x + rng.randint(30, 45), y + rng.randint(14, 20)], fill=cor)
    return img


def gerar_jpeg(rng: random.Random, tipo: str, capturada_em: datetime | None,
               gps: tuple[float, float] | None, com_exif: bool = True) -> bytes:
    """JPEG 320x240. Sem EXIF quando `com_exif=False` (simula foto repassada por aplicativo de mensagem)."""
    img = _cena(rng, tipo)
    buf = io.BytesIO()
    if not com_exif:
        img.save(buf, "JPEG", quality=75)
        return buf.getvalue()
    ex = Image.Exif()
    ex[0x010F] = "SINTETICO"  # Make
    ex[0x0110] = "GERADOR-LAUDO-VIVO"  # Model
    ex[0x010E] = "FOTO SINTETICA - SEM VALOR"  # ImageDescription
    ex[0x0131] = "laudo-vivo golden set"  # Software
    if capturada_em is not None:
        exif_ifd = ex.get_ifd(0x8769)
        exif_ifd[0x9003] = capturada_em.strftime("%Y:%m:%d %H:%M:%S")  # DateTimeOriginal (hora local)
        if capturada_em.tzinfo is not None:
            z = capturada_em.strftime("%z")
            exif_ifd[0x9011] = f"{z[:3]}:{z[3:]}"  # OffsetTimeOriginal (EXIF 2.31)
    if gps is not None:
        lat, lon = gps
        g = ex.get_ifd(0x8825)
        g[0] = b"\x02\x02\x00\x00"
        g[1] = "S" if lat < 0 else "N"
        g[2] = _gms(lat)
        g[3] = "W" if lon < 0 else "E"
        g[4] = _gms(lon)
    img.save(buf, "JPEG", quality=75, exif=ex)
    return buf.getvalue()
