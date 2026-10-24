"""Carteira para o mapa: `triar_carteira` (Fiscal-GO 2026) + geometria simplificada das glebas.

A triagem é da ferramenta de dados (`laudo.tools.carteira`); aqui só juntamos ponto representativo e contorno
das glebas (simplificado para o navegador), a abertura "por que caiu na amostra" de cada operação (código,
pontos e critério de cada motivo de `laudo.geo.triagem`, em `amostra`) e o contorno de Goiás (malha IBGE, se
estiver em `dados_locais/ibge/municipios_go.parquet`) para o fundo do mapa quando não há internet.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from laudo.api.visao import glebas_coords

REPO = Path(__file__).resolve().parents[3]
TOLERANCIA_GLEBA = 0.00015  # ~15 m: contorno legível sem mandar milhares de vértices


def _limpo(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if hasattr(v, "tolist") and not isinstance(v, str):
        return v.tolist()
    if hasattr(v, "item"):
        return v.item()
    return v


def triar(
    limite: int = 60,
    tipo: str = "compra_gado",
    municipio: str | None = None,
    prioridade_minima: int = 1,
    so_com_poligono: bool = True,
    instituicao: str | None = None,
) -> dict[str, Any]:
    from laudo.contracts import REGISTRO
    from laudo.tools import carteira  # noqa: F401  (registra triar_carteira)

    ferr = REGISTRO["triar_carteira"]
    entrada = ferr.entrada.model_validate(
        {
            "limite": limite,
            "tipo_empreendimento": tipo,
            "municipio": municipio or None,
            "prioridade_minima": prioridade_minima,
            "so_com_poligono": so_com_poligono,
            "instituicao": instituicao or None,
        }
    )
    env = ferr.funcao(entrada)
    if not env.ok:
        return {
            "ok": False,
            "erro": env.error.msg if env.error else "falha",
            "operacoes": [],
            "fonte_versao": env.fonte_versao,
        }
    dados = dict(env.data or {})
    ops = dados.get("operacoes") or []
    _anexar_geometria(ops)
    from laudo.tools.pacote import por_que_na_amostra

    for o in ops:
        o["amostra"] = por_que_na_amostra(o, compacto=True)
    dados["ok"] = True
    dados["fonte_versao"] = env.fonte_versao
    dados["latencia_ms"] = env.latency_ms
    return dados


def _anexar_geometria(ops: list[dict[str, Any]]) -> None:
    if not ops:
        return
    from laudo.geo import bench

    refs = {o["ref_bacen"] for o in ops}
    base = bench.operacoes()
    pontos = base[base["ref_bacen"].isin(refs)][
        [
            "ref_bacen",
            "lon",
            "lat",
            "lotacao_implicita_cab_ha",
            "area_glebas_ha",
            "n_glebas",
            "motivos_codigos",
        ]
    ]
    por_ref = {r["ref_bacen"]: r for r in pontos.to_dict("records")}
    gl = bench.glebas()
    sub = gl[gl["ref_bacen"].isin(refs)]
    wkts: dict[str, list[str]] = {}
    for r in sub[["ref_bacen", "wkt"]].to_dict("records"):
        w = r["wkt"]
        if w and not str(w).endswith("EMPTY"):
            wkts.setdefault(r["ref_bacen"], []).append(w)
    for o in ops:
        p = por_ref.get(o["ref_bacen"], {})
        o["lat"], o["lon"] = _limpo(p.get("lat")), _limpo(p.get("lon"))
        o["n_glebas"] = _limpo(p.get("n_glebas"))
        o["motivos_codigos"] = _limpo(p.get("motivos_codigos")) or []
        o["glebas"] = glebas_coords(list(dict.fromkeys(wkts.get(o["ref_bacen"], [])))[:8], TOLERANCIA_GLEBA)


@lru_cache(maxsize=1)
def _contorno_cache(caminho: str, mtime: float) -> dict[str, Any] | None:
    import pandas as pd
    from shapely import wkt as shp_wkt
    from shapely.ops import unary_union

    df = pd.read_parquet(caminho, columns=["wkt"])
    geoms = [shp_wkt.loads(w) for w in df["wkt"] if w]
    if not geoms:
        return None
    go = unary_union(geoms).simplify(0.01, preserve_topology=True)
    polys = list(getattr(go, "geoms", [go]))
    aneis = [[[round(y, 4), round(x, 4)] for x, y in p.exterior.coords] for p in polys if p.area > 0.01]
    return {"nome": "Goiás", "fonte": "IBGE — Malha Municipal (simplificada)", "aneis": aneis}


def contorno_go(dados_dir: Path | None = None) -> dict[str, Any] | None:
    """Contorno de GO a partir da malha municipal do IBGE (cache em memória e em disco)."""
    cache = (dados_dir / "contorno_go.json") if dados_dir else None
    if cache and cache.exists():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    p = REPO / "dados_locais" / "ibge" / "municipios_go.parquet"
    if not p.exists():
        # sem a malha do IBGE (imagem Docker, clone novo): o contorno simplificado versionado em ativos/ (preparar_demo)
        pronto = REPO / "dados_locais" / "mapa" / "contorno_go.json"
        try:
            return json.loads(pronto.read_text(encoding="utf-8")) if pronto.exists() else None
        except (OSError, json.JSONDecodeError):
            return None
    c = _contorno_cache(str(p), p.stat().st_mtime)
    if c and cache:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(c), encoding="utf-8")
        except OSError:
            pass
    return c
