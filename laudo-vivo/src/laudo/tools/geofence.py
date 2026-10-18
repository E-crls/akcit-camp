"""Ferramenta `geofence`: ponto (lat, lon, precisão) contra a(s) gleba(s) em WKT WGS84.

As contas são feitas em UTM local (zona do centroide da gleba, datum WGS84; a diferença para
SIRGAS 2000 é submétrica). Regras (juiz técnico, seção 5.5):

Saída: `posicao` (dentro/fora/indeterminado) e `status` no vocabulário comum `StatusChecagem`
(dentro → ok, fora → divergente, indeterminado → indeterminado).

- precisão do GPS ausente → indeterminado (não se inventa precisão);
- precisão > `precisao_max_m` (30 m) → indeterminado ("fique parado 10 s e repita");
- |distância à borda + tolerância| < precisão → indeterminado (o círculo de incerteza cruza a borda);
- senão dentro/fora pelo lado da borda.

A `tolerancia_m` é parâmetro operacional do rulebook (ex.: foto de cerca tirada do lado de fora da
divisa): um ponto até `tolerancia_m` fora da gleba conta como dentro.
"""

from __future__ import annotations

import math
import time
from functools import lru_cache
from typing import Literal

import shapely
from pydantic import BaseModel, Field, field_validator
from pyproj import Transformer
from shapely import wkt as shp_wkt
from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.ops import unary_union
from shapely.validation import make_valid

from laudo.contracts import CodigoErro, Envelope, registrar
from laudo.formatacao import fmt_br

NOME = "geofence"
VERSAO = "geofence@0.1.1"
PRECISAO_MAX_M = 30.0


class EntradaGeofence(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    precisao_m: float | None = Field(None, ge=0, description="precisão horizontal do GPS (m)")
    glebas_wkt: list[str] = Field(min_length=1, description="polígono(s) da gleba em WKT WGS84 (lon lat)")
    gleba_id: str | None = None
    tolerancia_m: float = Field(0.0, ge=0, le=500, description="parâmetro operacional do rulebook")
    precisao_max_m: float = Field(PRECISAO_MAX_M, gt=0)

    @field_validator("glebas_wkt")
    @classmethod
    def _nao_vazio(cls, v: list[str]) -> list[str]:
        if any(not s or not s.strip() for s in v):
            raise ValueError("WKT vazio")
        return v


def epsg_utm(lon: float, lat: float) -> int:
    zona = math.floor((lon + 180) / 6) % 60 + 1
    return (32700 if lat < 0 else 32600) + zona


@lru_cache(maxsize=64)
def _transformadores(epsg: int) -> tuple[Transformer, Transformer]:
    ida = Transformer.from_crs(4326, epsg, always_xy=True)
    volta = Transformer.from_crs(epsg, 4326, always_xy=True)
    return ida, volta


def avaliar_ponto(lat: float, lon: float, precisao_m: float | None, gleba_wgs84,
                  tolerancia_m: float = 0.0, precisao_max_m: float = PRECISAO_MAX_M) -> dict:
    """Núcleo determinístico (sem I/O). `gleba_wgs84` é um (Multi)Polygon shapely em lon/lat."""
    c = gleba_wgs84.centroid
    epsg = epsg_utm(c.x, c.y)
    ida, _ = _transformadores(epsg)
    gleba = shapely.transform(gleba_wgs84, ida.transform, interleaved=False)
    px, py = ida.transform(lon, lat)
    pt = Point(px, py)
    dist_borda = float(gleba.boundary.distance(pt))
    dentro_geom = bool(gleba.covers(pt))
    assinada = dist_borda if dentro_geom else -dist_borda  # + dentro, − fora
    efetiva = assinada + tolerancia_m

    posicao: Literal["dentro", "fora", "indeterminado"]
    if precisao_m is None:
        posicao, motivo = "indeterminado", "precisão do GPS ausente; refaça a captura com o GPS ligado"
    elif precisao_m > precisao_max_m:
        posicao, motivo = "indeterminado", (f"precisão {precisao_m:.0f} m > {precisao_max_m:.0f} m; "
                                            "fique parado 10 s ou entre 20 m no talhão e repita")
    elif abs(efetiva) < precisao_m:
        posicao, motivo = "indeterminado", (f"distância à borda ({fmt_br(abs(assinada), 1)} m) menor que a "
                                            f"precisão ({precisao_m:.0f} m); entre mais na gleba e repita")
    elif efetiva > 0:
        posicao = "dentro"
        motivo = "dentro da gleba" if dentro_geom else f"fora por {fmt_br(dist_borda, 1)} m, dentro da tolerância"
    else:
        posicao, motivo = "fora", f"fora da gleba por {fmt_br(dist_borda, 1)} m"
    # `status` no vocabulário comum (StatusChecagem); a posição fica em `posicao`. Quem decide se "fora a
    # 40 m" ainda comprova a benfeitoria é a regra (OP-benfeitoria-geofence), que recalcula pela distância.
    status = {"dentro": "ok", "fora": "divergente", "indeterminado": "indeterminado"}[posicao]
    return {"status": status, "posicao": posicao, "motivo": motivo, "dentro_geometrico": dentro_geom,
            "distancia_borda_m": round(dist_borda, 2), "distancia_assinada_m": round(assinada, 2),
            "precisao_m": precisao_m, "tolerancia_m": tolerancia_m, "precisao_max_m": precisao_max_m,
            "epsg_calculo": epsg, "area_gleba_ha": round(gleba.area / 10_000, 4)}


def ler_glebas(wkts: list[str]):
    """Une as glebas (WKT WGS84). Devolve (geometria, avisos). Levanta ValueError/TypeError se inválido."""
    geoms, avisos = [], []
    for s in wkts:
        g = shp_wkt.loads(s)
        if not isinstance(g, (Polygon, MultiPolygon)):
            raise TypeError(f"WKT não é polígono: {g.geom_type}")
        if g.is_empty:
            raise ValueError("polígono vazio")
        minx, miny, maxx, maxy = g.bounds
        if not (-180 <= minx <= maxx <= 180 and -90 <= miny <= maxy <= 90):
            raise ValueError("coordenadas fora de WGS84 (a ordem no WKT é lon lat)")
        if not g.is_valid:
            g = make_valid(g)
            avisos.append("polígono inválido corrigido com make_valid")
        geoms.append(g)
    u = unary_union(geoms)
    if not isinstance(u, (Polygon, MultiPolygon)):
        polys = [x for x in getattr(u, "geoms", []) if isinstance(x, (Polygon, MultiPolygon))]
        u = unary_union(polys)
    return u, avisos


@registrar(NOME, "Verifica se um ponto GPS (com precisão) está dentro, fora ou indeterminado em relação à "
                 "gleba (WKT WGS84), com distância à borda em metros (UTM local).",
           EntradaGeofence, deterministica=True, timeout_s=1.0)
def geofence(args: EntradaGeofence) -> Envelope:
    t0 = time.perf_counter()
    try:
        gleba, avisos = ler_glebas(args.glebas_wkt)
    except Exception as e:  # noqa: BLE001 — WKT inválido vira ENTRADA_INVALIDA
        return Envelope.falha(NOME, CodigoErro.ENTRADA_INVALIDA, f"gleba inválida: {e}", t0=t0)
    if gleba.is_empty:
        return Envelope.falha(NOME, CodigoErro.ENTRADA_INVALIDA, "gleba vazia após correção", t0=t0)
    try:
        dados = avaliar_ponto(args.lat, args.lon, args.precisao_m, gleba, args.tolerancia_m,
                              args.precisao_max_m)
    except Exception as e:  # noqa: BLE001
        return Envelope.falha(NOME, CodigoErro.ERRO_INTERNO, f"{type(e).__name__}: {e}", t0=t0)
    dados["avisos"] = avisos
    dados["gleba_id"] = args.gleba_id
    dados["ponto"] = {"lat": args.lat, "lon": args.lon}
    return Envelope.sucesso(NOME, dados, fonte_versao=VERSAO, t0=t0)
