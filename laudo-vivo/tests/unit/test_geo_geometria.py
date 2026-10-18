"""Geometria das glebas: área, correção de WKT, união e sobreposição (sem rede)."""

from __future__ import annotations

import pytest
import shapely
from shapely.geometry import Polygon, box

from laudo.geo.geometria import (
    area_ha,
    corrigir,
    ler_wkt,
    para_albers,
    para_albers_vetor,
    ponto_representativo,
    sobreposicoes,
    uniao,
)

# quadrado de ~1 km perto de Goiânia: 0,009 grau de latitude ~ 1 km
LAT0, LON0 = -16.68, -49.26


def quadrado_m(lado_m: float, dx_m: float = 0.0, dy_m: float = 0.0) -> Polygon:
    """Quadrado em graus com lado aproximado em metros (para testes de ordem de grandeza)."""
    import math

    dlat = 1 / 110_574.0
    dlon = 1 / (111_320.0 * math.cos(math.radians(LAT0)))
    x0, y0 = LON0 + dx_m * dlon, LAT0 + dy_m * dlat
    return box(x0, y0, x0 + lado_m * dlon, y0 + lado_m * dlat)


def test_area_ha_de_quadrado_de_1km():
    assert area_ha(quadrado_m(1000)) == pytest.approx(100.0, rel=0.01)


def test_area_ha_vazia_e_zero():
    assert area_ha(Polygon()) == 0.0


def test_corrigir_remove_z_e_conserta_gravata():
    gravata = ler_wkt("POLYGON Z ((0 0 1, 1 1 1, 1 0 1, 0 1 1, 0 0 1))")
    assert not shapely.has_z(gravata)
    assert gravata.is_valid
    assert gravata.geom_type in ("Polygon", "MultiPolygon")
    assert gravata.area == pytest.approx(0.5)


def test_corrigir_descarta_partes_nao_poligonais():
    g = shapely.GeometryCollection([box(0, 0, 1, 1), shapely.LineString([(0, 0), (5, 5)])])
    assert corrigir(g).geom_type == "Polygon"


def test_uniao_de_glebas_sobrepostas():
    a, b = quadrado_m(1000), quadrado_m(1000, dx_m=500)
    u = uniao([a.wkt, b.wkt, "POLYGON EMPTY"])
    assert area_ha(u) == pytest.approx(150.0, rel=0.02)


def test_para_albers_vetor_igual_ao_escalar():
    gs = [quadrado_m(300), quadrado_m(800, dx_m=2000)]
    vet = para_albers_vetor(gs)
    for g, v in zip(gs, vet, strict=True):
        assert v.area == pytest.approx(para_albers(g).area, rel=1e-9)


def test_sobreposicoes_respeita_grupo_e_limiares():
    g = [para_albers(x) for x in (quadrado_m(1000), quadrado_m(1000, dx_m=500), quadrado_m(1000, dx_m=990),
                                  quadrado_m(1000, dx_m=5000))]
    # 0 e 1 se sobrepõem em 50%; 0 e 2 só numa lasca de 10 m (1 ha, 1%); 3 está longe
    pares = sobreposicoes(g, grupos=["s1", "s1", "s1", "s1"], min_area_ha=0.5, min_frac=0.05)
    chaves = {(p.i, p.j) for p in pares}
    assert (0, 1) in chaves
    assert (0, 2) not in chaves  # lasca filtrada por min_frac
    assert all(3 not in k for k in chaves)
    p01 = next(p for p in pares if (p.i, p.j) == (0, 1))
    assert p01.frac_i == pytest.approx(0.5, abs=0.02)
    assert p01.area_inter_ha == pytest.approx(50.0, rel=0.03)
    # safras diferentes não se comparam
    assert sobreposicoes(g[:2], grupos=["2025/26", "2026/27"]) == []


def test_ponto_representativo_cai_dentro_da_maior_parte():
    mp = shapely.MultiPolygon([quadrado_m(100), quadrado_m(1000, dx_m=3000)])
    lon, lat = ponto_representativo(mp)
    assert quadrado_m(1000, dx_m=3000).contains(shapely.Point(lon, lat))
    assert ponto_representativo(Polygon()) is None
