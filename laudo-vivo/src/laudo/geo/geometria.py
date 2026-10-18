"""Geometria das glebas: leitura de WKT, projeção métrica, área e sobreposição.

Todas as contas de área e interseção são feitas na projeção cônica equivalente de Albers
usada pelo IBGE para o Brasil (SIRGAS 2000; paralelos-padrão -2 e -22, meridiano central -54),
que preserva área. As geometrias de entrada estão em WGS84 (lon, lat), como no Sicor.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import shapely
from pyproj import CRS, Transformer
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

ALBERS_IBGE = CRS.from_proj4("+proj=aea +lat_0=-12 +lon_0=-54 +lat_1=-2 +lat_2=-22 +x_0=5000000 "
                             "+y_0=10000000 +ellps=GRS80 +towgs84=0,0,0,0,0,0,0 +units=m +no_defs")
WGS84 = CRS.from_epsg(4326)


@lru_cache(maxsize=16)
def _transformador(origem: str, destino: str) -> Transformer:
    return Transformer.from_crs(CRS.from_user_input(origem), CRS.from_user_input(destino), always_xy=True)


def reprojetar(geom: BaseGeometry, origem: str | CRS = "EPSG:4326", destino: str | CRS = ALBERS_IBGE
               ) -> BaseGeometry:
    o = origem.to_string() if isinstance(origem, CRS) else origem
    d = destino.to_string() if isinstance(destino, CRS) else destino
    tr = _transformador(o, d)
    return shapely.transform(geom, tr.transform, interleaved=False)


def para_albers(geom: BaseGeometry) -> BaseGeometry:
    return reprojetar(geom, "EPSG:4326", ALBERS_IBGE)


def para_albers_vetor(geoms: Sequence[BaseGeometry]) -> np.ndarray:
    """Reprojeta um vetor de geometrias WGS84 para Albers de uma vez (rápido para milhares)."""
    tr = _transformador("EPSG:4326", ALBERS_IBGE.to_string())
    arr = np.asarray(geoms, dtype=object)
    return shapely.transform(arr, tr.transform, interleaved=False)


def corrigir(geom: BaseGeometry) -> BaseGeometry:
    """Remove Z, conserta autointerseções e mantém só a parte poligonal."""
    if geom is None or geom.is_empty:
        return Polygon()
    g = shapely.force_2d(geom)
    if not g.is_valid:
        g = shapely.make_valid(g)
    if g.geom_type in ("Polygon", "MultiPolygon"):
        return g
    partes = [p for p in getattr(g, "geoms", [g]) if p.geom_type in ("Polygon", "MultiPolygon")]
    if not partes:
        return Polygon()
    return shapely.union_all(partes)


def ler_wkt(wkt: str) -> BaseGeometry:
    return corrigir(shapely.from_wkt(wkt))


def area_ha(geom_wgs84: BaseGeometry) -> float:
    if geom_wgs84 is None or geom_wgs84.is_empty:
        return 0.0
    return para_albers(geom_wgs84).area / 10_000.0


def uniao(wkts: Iterable[str]) -> BaseGeometry:
    geoms = [ler_wkt(w) for w in wkts]
    geoms = [g for g in geoms if not g.is_empty]
    if not geoms:
        return Polygon()
    return corrigir(shapely.union_all(geoms))


def como_multipoligono(geom: BaseGeometry) -> MultiPolygon:
    if isinstance(geom, MultiPolygon):
        return geom
    if isinstance(geom, Polygon):
        return MultiPolygon([geom]) if not geom.is_empty else MultiPolygon()
    return MultiPolygon([p for p in getattr(geom, "geoms", []) if isinstance(p, Polygon)])


@dataclass
class ParSobreposto:
    i: int
    j: int
    area_inter_ha: float
    frac_i: float  # fração da geometria i coberta pela j
    frac_j: float


def sobreposicoes(geoms_metricas: Sequence[BaseGeometry], grupos: Sequence[str] | None = None,
                  min_area_ha: float = 0.5, min_frac: float = 0.05) -> list[ParSobreposto]:
    """Pares de geometrias (em CRS métrico) que se sobrepõem, usando STRtree.

    `grupos` restringe a comparação a geometrias do mesmo grupo (ex.: mesma safra). Um par só
    entra se a interseção tiver ao menos `min_area_ha` e cobrir ao menos `min_frac` de uma das duas
    (filtra lascas de digitalização entre vizinhos).
    """
    geoms = np.asarray(geoms_metricas, dtype=object)
    arvore = shapely.STRtree(geoms)
    ii, jj = arvore.query(geoms, predicate="intersects")
    pares: list[ParSobreposto] = []
    for i, j in zip(ii.tolist(), jj.tolist(), strict=True):
        if j <= i:
            continue
        if grupos is not None and grupos[i] != grupos[j]:
            continue
        gi, gj = geoms[i], geoms[j]
        inter = gi.intersection(gj).area
        if inter <= 0:
            continue
        ai, aj = gi.area, gj.area
        fi = inter / ai if ai > 0 else 0.0
        fj = inter / aj if aj > 0 else 0.0
        if inter / 10_000.0 < min_area_ha or max(fi, fj) < min_frac:
            continue
        pares.append(ParSobreposto(i=i, j=j, area_inter_ha=inter / 10_000.0, frac_i=fi, frac_j=fj))
    return pares


def ponto_representativo(geom: BaseGeometry) -> tuple[float, float] | None:
    """(lon, lat) de um ponto garantidamente dentro da maior parte da geometria."""
    if geom is None or geom.is_empty:
        return None
    partes = list(getattr(geom, "geoms", [geom]))
    maior = max(partes, key=lambda p: p.area)
    p = maior.representative_point()
    return (p.x, p.y)
