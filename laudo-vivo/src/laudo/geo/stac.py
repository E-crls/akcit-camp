"""Busca de cenas Sentinel-2 L2A no Earth Search (Element 84) via STAC, direto por HTTP.

Coleção padrão: `sentinel-2-c1-l2a` (Collection 1). Os hrefs dos assets vêm do próprio item
(o caminho no S3 tem o mês sem zero à esquerda, ex.: `.../2026/9/...`), por isso nunca montamos
URL à mão. Escala/offset de reflectância vêm de `raster:bands` do asset.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any

import httpx
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry

EARTH_SEARCH = "https://earth-search.aws.element84.com/v1"
COLECAO = "sentinel-2-c1-l2a"
ASSETS = {"red": "B04", "nir": "B08", "scl": "SCL"}


def _escala(asset: dict) -> tuple[float, float]:
    rb = (asset.get("raster:bands") or [{}])[0]
    return float(rb.get("scale", 1.0) or 1.0), float(rb.get("offset", 0.0) or 0.0)


def simplificar_item(it: dict) -> dict[str, Any]:
    """Reduz um item STAC ao que a série de NDVI precisa."""
    p = it.get("properties", {})
    assets = it.get("assets", {})
    out: dict[str, Any] = {
        "id": it["id"],
        "datetime": p.get("datetime"),
        "data": (p.get("datetime") or "")[:10],
        "nuvem": p.get("eo:cloud_cover"),
        "tile": p.get("s2:mgrs_tile") or (p.get("grid:code") or "").replace("MGRS-", "") or None,
        "crs": p.get("proj:code") or (f"EPSG:{p['proj:epsg']}" if p.get("proj:epsg") else None),
        "plataforma": p.get("platform"),
        "instrumento": ",".join(p.get("instruments") or []) or None,
        "baseline": p.get("s2:processing_baseline"),
        "geometry": it.get("geometry"),
        "assets": {},
    }
    for chave, banda in ASSETS.items():
        a = assets.get(chave) or assets.get(banda)
        if a is None:
            continue
        esc, off = _escala(a)
        out["assets"][chave] = {"href": a["href"], "escala": esc, "offset": off,
                                "crs": (a.get("proj:code") or out["crs"])}
    return out


def buscar(geom_wgs84: BaseGeometry, inicio: date, fim: date, colecao: str = COLECAO,
           max_nuvem: float | None = None, limite_total: int = 300, cliente: httpx.Client | None = None,
           url: str = EARTH_SEARCH) -> list[dict]:
    """Itens STAC que intersectam a geometria no período (todas as páginas, até `limite_total`)."""
    corpo: dict[str, Any] = {
        "collections": [colecao],
        "intersects": mapping(geom_wgs84.envelope),
        "datetime": f"{inicio.isoformat()}T00:00:00Z/{fim.isoformat()}T23:59:59Z",
        "limit": 100,
    }
    if max_nuvem is not None:
        corpo["query"] = {"eo:cloud_cover": {"lte": max_nuvem}}
    proprio = cliente is None
    cli = cliente or httpx.Client(timeout=30.0)
    itens: list[dict] = []
    try:
        req: tuple[str, str, dict | None] = ("POST", f"{url}/search", corpo)
        while req and len(itens) < limite_total:
            metodo, alvo, body = req
            r = cli.post(alvo, json=body) if metodo == "POST" else cli.get(alvo)
            r.raise_for_status()
            fc = r.json()
            itens.extend(simplificar_item(f) for f in fc.get("features", []))
            prox = next((lk for lk in fc.get("links", []) if lk.get("rel") == "next"), None)
            if not prox or not fc.get("features"):
                break
            if prox.get("method", "GET").upper() == "POST":
                b = dict(corpo) if prox.get("merge") else {}
                b.update(prox.get("body") or {})
                req = ("POST", prox["href"], b or corpo)
            else:
                req = ("GET", prox["href"], None)
    finally:
        if proprio:
            cli.close()
    return itens[:limite_total]


def escolher_por_data(itens: list[dict], geom_wgs84: BaseGeometry) -> list[dict]:
    """Uma cena por data: a que contém a geometria inteira (menor nuvem); senão, a de maior interseção.

    Em áreas de sobreposição de tiles MGRS a mesma passagem aparece em dois itens.
    """
    por_data: dict[str, list[dict]] = defaultdict(list)
    for it in itens:
        if not it.get("assets", {}).keys() >= {"red", "nir", "scl"}:
            continue
        por_data[it["data"]].append(it)
    escolhidos = []
    for d in sorted(por_data):
        cands = []
        for it in por_data[d]:
            pe = shape(it["geometry"]) if it.get("geometry") else None
            contem = bool(pe is not None and pe.contains(geom_wgs84))
            inter = pe.intersection(geom_wgs84).area if pe is not None else 0.0
            nuvem = it.get("nuvem") if it.get("nuvem") is not None else 100.0
            cands.append((not contem, -inter, nuvem, it["id"], it))
        cands.sort(key=lambda t: t[:4])
        if cands and cands[0][1] < 0:
            escolhidos.append(cands[0][4] | {"contem_poligono": not cands[0][0]})
    return escolhidos


def amostrar_datas(itens: list[dict], max_datas: int) -> list[dict]:
    """Se houver mais datas que `max_datas`, divide o período em faixas iguais e fica com a cena
    menos nublada de cada faixa (mantém a cobertura temporal da série)."""
    if len(itens) <= max_datas:
        return list(itens)
    ds = [datetime.fromisoformat(it["data"]).toordinal() for it in itens]
    ini, fim = min(ds), max(ds)
    passo = (fim - ini + 1) / max_datas
    faixas: dict[int, dict] = {}
    for it, d in zip(itens, ds, strict=True):
        k = min(int((d - ini) / passo), max_datas - 1)
        atual = faixas.get(k)
        nuvem = it.get("nuvem") if it.get("nuvem") is not None else 100.0
        if atual is None or nuvem < (atual.get("nuvem") if atual.get("nuvem") is not None else 100.0):
            faixas[k] = it
    return [faixas[k] for k in sorted(faixas)]
