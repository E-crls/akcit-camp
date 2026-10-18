"""STAC (Earth Search): simplificação de item, escolha por data, amostragem e paginação (sem rede)."""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest
from shapely.geometry import box

from laudo.geo.stac import amostrar_datas, buscar, escolher_por_data, simplificar_item

GLEBA = box(-50.96, -17.86, -50.95, -17.85)


def item_stac(id_: str, dt: str, nuvem: float, footprint, tile: str = "22KDF") -> dict:
    base = f"https://e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com/sentinel-2-c1-l2a/22/K/DF/2026/9/{id_}"
    banda10 = {"raster:bands": [{"nodata": 0, "scale": 0.0001, "offset": -0.1, "spatial_resolution": 10}]}
    return {
        "id": id_, "geometry": footprint.__geo_interface__,
        "properties": {"datetime": dt, "eo:cloud_cover": nuvem, "s2:mgrs_tile": tile, "proj:code": "EPSG:32722",
                       "platform": "sentinel-2c", "instruments": ["msi"], "s2:processing_baseline": "05.13"},
        "assets": {"red": {"href": f"{base}/B04.tif"} | banda10, "nir": {"href": f"{base}/B08.tif"} | banda10,
                   "scl": {"href": f"{base}/SCL.tif", "raster:bands": [{"nodata": 0, "spatial_resolution": 20}]}},
    }


def test_simplificar_item_usa_href_do_stac_e_escala():
    it = simplificar_item(item_stac("S2C_T22KDF_20260905T133147_L2A", "2026-09-05T13:37:27Z", 3.2, box(-51, -18, -50, -17)))
    assert it["data"] == "2026-09-05" and it["tile"] == "22KDF" and it["crs"] == "EPSG:32722"
    assert it["assets"]["red"]["href"].endswith("/2026/9/S2C_T22KDF_20260905T133147_L2A/B04.tif")  # mês sem zero
    assert it["assets"]["red"]["escala"] == 0.0001 and it["assets"]["red"]["offset"] == -0.1
    assert it["assets"]["scl"]["escala"] == 1.0 and it["assets"]["scl"]["offset"] == 0.0


def test_escolher_por_data_prefere_tile_que_contem_a_gleba():
    so_borda = box(-50.955, -18, -50, -17)  # corta a gleba ao meio
    contem = box(-51.5, -18, -50.5, -17)
    itens = [simplificar_item(item_stac("A", "2026-09-05T13:37:27Z", 1.0, so_borda, "22KEF")),
             simplificar_item(item_stac("B", "2026-09-05T13:37:30Z", 30.0, contem, "22KDF")),
             simplificar_item(item_stac("C", "2026-09-10T13:37:30Z", 10.0, so_borda, "22KEF")),
             simplificar_item(item_stac("D", "2026-09-15T13:37:30Z", 10.0, box(-40, -10, -39, -9)))]
    esc = escolher_por_data(itens, GLEBA)
    assert [e["id"] for e in esc] == ["B", "C"]  # D não toca a gleba
    assert esc[0]["contem_poligono"] is True and esc[1]["contem_poligono"] is False


def test_amostrar_datas_mantem_cobertura_e_menor_nuvem():
    itens = [{"id": str(i), "data": f"2026-08-{i:02d}", "nuvem": float(30 - i)} for i in range(1, 31)]
    am = amostrar_datas(itens, 3)
    assert len(am) == 3
    datas = [a["data"] for a in am]
    assert datas == sorted(datas)
    assert datas[0] < "2026-08-11" and datas[-1] >= "2026-08-21"
    assert amostrar_datas(itens[:2], 5) == itens[:2]


def test_buscar_pagina_com_link_next_post():
    paginas = {
        None: {"features": [item_stac("p1", "2026-09-01T13:00:00Z", 1.0, box(-51, -18, -50, -17))],
               "links": [{"rel": "next", "href": "https://stac.invalid/v1/search", "method": "POST",
                          "body": {"next": "tok2"}, "merge": True}]},
        "tok2": {"features": [item_stac("p2", "2026-09-06T13:00:00Z", 2.0, box(-51, -18, -50, -17))],
                 "links": []},
    }
    corpos = []

    def responder(req: httpx.Request) -> httpx.Response:
        corpo = json.loads(req.content)
        corpos.append(corpo)
        return httpx.Response(200, json=paginas[corpo.get("next")])

    cli = httpx.Client(transport=httpx.MockTransport(responder))
    itens = buscar(GLEBA, date(2026, 9, 1), date(2026, 9, 30), max_nuvem=50, cliente=cli, url="https://stac.invalid/v1")
    assert [i["id"] for i in itens] == ["p1", "p2"]
    assert corpos[0]["collections"] == ["sentinel-2-c1-l2a"]
    assert corpos[0]["query"] == {"eo:cloud_cover": {"lte": 50}}
    assert corpos[0]["datetime"] == "2026-09-01T00:00:00Z/2026-09-30T23:59:59Z"
    assert corpos[1]["next"] == "tok2" and corpos[1]["collections"] == ["sentinel-2-c1-l2a"]  # merge


def test_buscar_propaga_erro_http():
    cli = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(502)))
    with pytest.raises(httpx.HTTPStatusError):
        buscar(GLEBA, date(2026, 9, 1), date(2026, 9, 2), cliente=cli, url="https://stac.invalid/v1")
