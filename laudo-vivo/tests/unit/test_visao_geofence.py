"""`geofence`: casos fixos e propriedades perto da borda (hypothesis)."""

from __future__ import annotations

import math

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pyproj import Transformer
from shapely.geometry import Polygon

from laudo.contracts import REGISTRO, CodigoErro
from laudo.tools.geofence import EntradaGeofence, epsg_utm, geofence

# Gleba sintética: quadrado de ~1 km perto de Goiânia, construído em UTM 22S.
EPSG = 32722
_ida = Transformer.from_crs(4326, EPSG, always_xy=True)
_volta = Transformer.from_crs(EPSG, 4326, always_xy=True)
X0, Y0 = _ida.transform(-49.30, -16.70)
LADO = 1000.0
QUAD_UTM = Polygon([(X0, Y0), (X0 + LADO, Y0), (X0 + LADO, Y0 + LADO), (X0, Y0 + LADO)])
QUAD_WKT = Polygon([_volta.transform(x, y) for x, y in QUAD_UTM.exterior.coords]).wkt


def _ponto_utm(x: float, y: float) -> tuple[float, float]:
    lon, lat = _volta.transform(x, y)
    return lat, lon


def _rodar(lat, lon, precisao, wkts=None, **kw):
    e = geofence(EntradaGeofence(lat=lat, lon=lon, precisao_m=precisao, glebas_wkt=wkts or [QUAD_WKT], **kw))
    assert e.ok, e.error
    return e.data


def test_registrada_e_zona():
    assert "geofence" in REGISTRO
    assert epsg_utm(-49.3, -16.7) == 32722
    assert epsg_utm(-47.9, -15.8) == 32723


def test_centro_dentro_e_longe_fora():
    d = _rodar(*_ponto_utm(X0 + 500, Y0 + 500), 5.0)
    assert d["posicao"] == "dentro" and abs(d["distancia_borda_m"] - 500) < 0.5
    assert abs(d["area_gleba_ha"] - 100) < 0.1
    f = _rodar(*_ponto_utm(X0 - 200, Y0 + 500), 5.0)
    assert f["posicao"] == "fora" and abs(f["distancia_borda_m"] - 200) < 0.5
    # `status` no vocabulário comum de Checagem (a regra recalcula pela distância)
    assert (d["status"], f["status"]) == ("ok", "divergente")


def test_precisao_ruim_ou_ausente_indeterminado():
    lat, lon = _ponto_utm(X0 + 500, Y0 + 500)
    assert _rodar(lat, lon, 31.0)["posicao"] == "indeterminado"
    assert _rodar(lat, lon, None)["posicao"] == "indeterminado"
    assert _rodar(lat, lon, 60.0, precisao_max_m=100)["posicao"] == "dentro"


def test_tolerancia_do_rulebook():
    lat, lon = _ponto_utm(X0 - 15, Y0 + 500)  # 15 m fora
    assert _rodar(lat, lon, 3.0)["posicao"] == "fora"
    d = _rodar(lat, lon, 3.0, tolerancia_m=25.0)
    assert d["posicao"] == "dentro" and not d["dentro_geometrico"]


def test_varias_glebas_e_buraco():
    outra = Polygon([_volta.transform(x, y) for x, y in
                     [(X0 + 2000, Y0), (X0 + 2500, Y0), (X0 + 2500, Y0 + 500), (X0 + 2000, Y0 + 500)]]).wkt
    assert _rodar(*_ponto_utm(X0 + 2250, Y0 + 250), 5.0, wkts=[QUAD_WKT, outra])["posicao"] == "dentro"
    furo = [(X0 + 400, Y0 + 400), (X0 + 600, Y0 + 400), (X0 + 600, Y0 + 600), (X0 + 400, Y0 + 600)]
    com_furo = Polygon([_volta.transform(x, y) for x, y in QUAD_UTM.exterior.coords],
                       [[_volta.transform(x, y) for x, y in furo]]).wkt
    d = _rodar(*_ponto_utm(X0 + 500, Y0 + 500), 5.0, wkts=[com_furo])
    assert d["posicao"] == "fora" and abs(d["distancia_borda_m"] - 100) < 0.5


def test_entradas_invalidas():
    e = geofence(EntradaGeofence(lat=-16.7, lon=-49.3, precisao_m=5, glebas_wkt=["POINT (-49.3 -16.7)"]))
    assert not e.ok and e.error.code == CodigoErro.ENTRADA_INVALIDA
    e2 = geofence(EntradaGeofence(lat=-16.7, lon=-49.3, precisao_m=5, glebas_wkt=["POLYGON ((nada))"]))
    assert not e2.ok and e2.error.code == CodigoErro.ENTRADA_INVALIDA
    # lat/lon trocados no WKT (lat lon em vez de lon lat) com latitude > 90 é recusado
    e3 = geofence(EntradaGeofence(lat=-16.7, lon=-49.3, precisao_m=5,
                                  glebas_wkt=["POLYGON ((-16 -149, -16 -148, -15 -148, -16 -149))"]))
    assert not e3.ok
    # polígono autointersectante (gravata) é corrigido e avisado
    gravata = Polygon([_volta.transform(x, y) for x, y in
                       [(X0, Y0), (X0 + 1000, Y0 + 1000), (X0 + 1000, Y0), (X0, Y0 + 1000)]]).wkt
    d = _rodar(*_ponto_utm(X0 + 900, Y0 + 500), 5.0, wkts=[gravata])
    assert d["avisos"] and d["posicao"] == "dentro"


# ---------------------------------------------------------------------------
# Propriedades perto da borda
# ---------------------------------------------------------------------------

lados = st.sampled_from(["oeste", "leste", "sul", "norte"])


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(lado=lados, ao_longo=st.floats(0.2, 0.8), d=st.floats(-80, 80), precisao=st.floats(0.5, 40),
       tol=st.sampled_from([0.0, 0.0, 10.0]))
def test_propriedade_borda(lado, ao_longo, d, precisao, tol):
    """d > 0 dentro, d < 0 fora (m, ao longo da normal da borda); confere o status esperado."""
    t = ao_longo * LADO
    x, y = {"oeste": (X0 + d, Y0 + t), "leste": (X0 + LADO - d, Y0 + t),
            "sul": (X0 + t, Y0 + d), "norte": (X0 + t, Y0 + LADO - d)}[lado]
    r = _rodar(*_ponto_utm(x, y), precisao, tolerancia_m=tol)
    assert abs(r["distancia_borda_m"] - abs(d)) < 0.05
    efetiva = d + tol
    margem = 0.05  # erro numérico da ida e volta entre projeções
    if precisao > 30 or abs(efetiva) < precisao - margem:
        assert r["posicao"] == "indeterminado"
    elif abs(efetiva) > precisao + margem:
        assert r["posicao"] == ("dentro" if efetiva > 0 else "fora")
    # monotonia: nunca "dentro" com o ponto fora além da tolerância + precisão
    if r["posicao"] == "dentro":
        assert efetiva > 0
    if r["posicao"] == "fora":
        assert efetiva < 0


@settings(max_examples=60, deadline=None)
@given(lat=st.floats(-33.0, 5.0), lon=st.floats(-73.0, -35.0), raio=st.floats(50, 3000))
def test_propriedade_centro_de_gleba_qualquer_no_brasil(lat, lon, raio):
    """Em qualquer ponto do Brasil, o centro de um quadrado de lado 2·raio está dentro, a ~raio da borda."""
    epsg = epsg_utm(lon, lat)
    ida = Transformer.from_crs(4326, epsg, always_xy=True)
    volta = Transformer.from_crs(epsg, 4326, always_xy=True)
    cx, cy = ida.transform(lon, lat)
    quad = Polygon([volta.transform(cx + a * raio, cy + b * raio) for a, b in [(-1, -1), (1, -1), (1, 1), (-1, 1)]])
    r = _rodar(lat, lon, 5.0, wkts=[quad.wkt])
    assert r["posicao"] == "dentro"
    assert math.isclose(r["distancia_borda_m"], raio, rel_tol=0.01)
