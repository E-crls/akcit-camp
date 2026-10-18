"""Série de NDVI de um polígono a partir do Sentinel-2 L2A (COG janelado + máscara SCL).

Metodologia (vai para o laudo, MCR 2-7 item 4: satélite, sensor, datas, resolução, bandas):
- cenas do Earth Search (`sentinel-2-c1-l2a`) que intersectam o polígono no período;
- uma cena por data (a que contém o polígono, com menor nuvem);
- leitura só da janela que cobre o polígono: B04 (vermelho, 665 nm) e B08 (NIR, 842 nm) a 10 m,
  SCL (classificação de cena) a 20 m replicada para 10 m;
- reflectância = DN * escala + offset (do `raster:bands` do STAC);
- pixel "limpo" = centro dentro do polígono e SCL em {4 vegetação, 5 solo exposto, 6 água};
  NDVI calculado nos pixels limpos de vegetação/solo (SCL 4 e 5);
- uma data conta como observação limpa se a fração de pixels limpos >= `limiar_frac_limpa`;
- menos de 2 observações limpas => abstenção (`NUVEM`).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
from shapely.geometry.base import BaseGeometry

from laudo.geo import stac
from laudo.geo.geometria import area_ha, reprojetar

SCL_LIMPO = (4, 5, 6)
SCL_NDVI = (4, 5)
VERSAO_METODO = "ndvi-s2c1-scl456-v1"
RAIZ = Path(__file__).resolve().parents[3]


def dir_cache() -> Path:
    base = os.environ.get("LAUDO_DADOS_LOCAIS")
    return (Path(base) if base else RAIZ / "dados_locais") / "ndvi_cache"


@dataclass
class ObsNdvi:
    data: str
    item_id: str
    tile: str | None
    plataforma: str | None
    nuvem_cena: float | None
    n_pixels: int
    n_limpos: int
    frac_limpa: float
    ndvi_p10: float | None
    ndvi_p50: float | None
    ndvi_p90: float | None
    ndvi_media: float | None
    limpa: bool = False
    bytes: int = 0
    requisicoes: int = 0
    segundos: float = 0.0
    cache: bool = False


def estatisticas(red: np.ndarray, nir: np.ndarray, scl: np.ndarray, dentro: np.ndarray,
                 escala_red: float = 1e-4, offset_red: float = 0.0, escala_nir: float = 1e-4,
                 offset_nir: float = 0.0, nodata: float | None = 0) -> dict[str, Any]:
    """NDVI p10/p50/p90 e fração limpa dos pixels `dentro` do polígono. Função pura (testável)."""
    dentro = dentro.astype(bool)
    n_pix = int(dentro.sum())
    valido = dentro.copy()
    if nodata is not None:
        valido &= (red != nodata) & (nir != nodata)
    limpo = valido & np.isin(scl, SCL_LIMPO)
    n_limpo = int(limpo.sum())
    usar = valido & np.isin(scl, SCL_NDVI)
    out: dict[str, Any] = {"n_pixels": n_pix, "n_limpos": n_limpo,
                           "frac_limpa": round(n_limpo / n_pix, 4) if n_pix else 0.0,
                           "ndvi_p10": None, "ndvi_p50": None, "ndvi_p90": None, "ndvi_media": None}
    if usar.any():
        r = red[usar].astype(np.float64) * escala_red + offset_red
        n = nir[usar].astype(np.float64) * escala_nir + offset_nir
        soma = n + r
        ok = soma > 0
        if ok.any():
            v = np.clip((n[ok] - r[ok]) / soma[ok], -1.0, 1.0)
            p10, p50, p90 = np.percentile(v, [10, 50, 90])
            out.update(ndvi_p10=round(float(p10), 4), ndvi_p50=round(float(p50), 4),
                       ndvi_p90=round(float(p90), 4), ndvi_media=round(float(v.mean()), 4))
    return out


def hash_geom(geom_wgs84: BaseGeometry) -> str:
    return hashlib.sha256(geom_wgs84.wkt.encode()).hexdigest()[:16]


def _caminho_cache(item: dict, gh: str, base: Path) -> Path:
    return base / (item.get("tile") or "sem_tile") / item["data"] / f"{item['id']}_{gh}_{VERSAO_METODO}.json"


def ler_observacao(item: dict, geom_wgs84: BaseGeometry, cliente=None) -> ObsNdvi:
    """Lê B04, B08 e SCL da janela do polígono numa cena e calcula as estatísticas."""
    from rasterio.features import geometry_mask

    from laudo.geo.cog import Medidor, ler_janela, novo_cliente

    t0 = time.perf_counter()
    med = Medidor()
    proprio = cliente is None
    cli = cliente or novo_cliente()
    try:
        a = item["assets"]
        crs = a["red"]["crs"] or item["crs"]
        geom = reprojetar(geom_wgs84, "EPSG:4326", crs)
        b = geom.bounds
        # 10 m alinhado a pares de pixels => a janela de 20 m da SCL é exata (mesma origem do tile)
        jr = ler_janela(a["red"]["href"], b, cli, med, multiplo=2)
        with ThreadPoolExecutor(max_workers=2) as ex:
            janela = (jr.col_off, jr.row_off, jr.dados.shape[1], jr.dados.shape[0])
            fn = ex.submit(ler_janela, a["nir"]["href"], b, cli, med, 1, janela)
            fs = ex.submit(ler_janela, a["scl"]["href"], b, cli, med, 1,
                           (jr.col_off // 2, jr.row_off // 2, jr.dados.shape[1] // 2, jr.dados.shape[0] // 2))
            jn, js = fn.result(), fs.result()
        scl = np.repeat(np.repeat(js.dados, 2, axis=0), 2, axis=1)[: jr.dados.shape[0], : jr.dados.shape[1]]
        dentro = geometry_mask([geom], out_shape=jr.dados.shape, transform=jr.transform, invert=True)
        if not dentro.any():  # polígono menor que um pixel: usa os pixels tocados
            dentro = geometry_mask([geom], out_shape=jr.dados.shape, transform=jr.transform, invert=True,
                                   all_touched=True)
        est = estatisticas(jr.dados, jn.dados, scl, dentro, a["red"]["escala"], a["red"]["offset"],
                           a["nir"]["escala"], a["nir"]["offset"], nodata=jr.nodata if jr.nodata is not None else 0)
    finally:
        if proprio:
            cli.close()
    return ObsNdvi(data=item["data"], item_id=item["id"], tile=item.get("tile"), plataforma=item.get("plataforma"),
                   nuvem_cena=item.get("nuvem"), bytes=med.bytes, requisicoes=med.requisicoes,
                   segundos=round(time.perf_counter() - t0, 2), **est)


def serie_ndvi(geom_wgs84: BaseGeometry, inicio: date, fim: date, *, max_nuvem_cena: float = 80.0,
               limiar_frac_limpa: float = 0.6, max_datas: int = 12, colecao: str = stac.COLECAO,
               cache: Path | None = None,
               buscar: Callable[..., list[dict]] | None = None,
               ler: Callable[[dict, BaseGeometry], ObsNdvi] | None = None) -> dict[str, Any]:
    """Monta a série. `buscar` e `ler` são injetáveis (testes sem rede); o padrão é resolvido na
    chamada (`stac.buscar` e `ler_observacao`), o que também permite monkeypatch."""
    t0 = time.perf_counter()
    injetado = buscar is not None
    buscar = buscar or stac.buscar
    ler = ler or ler_observacao
    base = cache or dir_cache()
    gh = hash_geom(geom_wgs84)
    stac_do_cache = False
    cache_busca = base / "stac" / f"{gh}_{inicio.isoformat()}_{fim.isoformat()}_{colecao}_{max_nuvem_cena:g}.json"
    if not injetado and cache_busca.exists() and os.environ.get("LAUDO_STAC_SEM_CACHE") != "1":
        # Mesma gleba e mesmo período: a lista de cenas fica congelada na primeira consulta. Isso torna o
        # laudo reprodutível (e a demo offline); para atualizar, apague o arquivo ou use LAUDO_STAC_SEM_CACHE=1.
        itens = json.loads(cache_busca.read_text(encoding="utf-8"))
        stac_do_cache = True
    else:
        itens = buscar(geom_wgs84, inicio, fim, colecao=colecao, max_nuvem=max_nuvem_cena)
        if not injetado:
            cache_busca.parent.mkdir(parents=True, exist_ok=True)
            cache_busca.write_text(json.dumps(itens, ensure_ascii=False), encoding="utf-8")
    por_data = stac.escolher_por_data(itens, geom_wgs84)
    escolhidos = stac.amostrar_datas(por_data, max_datas)
    obs: list[ObsNdvi] = []
    erros: list[dict[str, str]] = []
    for it in escolhidos:
        cp = _caminho_cache(it, gh, base)
        if cp.exists():
            o = ObsNdvi(**json.loads(cp.read_text(encoding="utf-8")))
            o.cache, o.bytes, o.requisicoes, o.segundos = True, 0, 0, 0.0
        else:
            try:
                o = ler(it, geom_wgs84)
            except Exception as e:  # noqa: BLE001 — uma data ruim não derruba a série; vira registro de erro
                erros.append({"data": it["data"], "item_id": it["id"], "erro": f"{type(e).__name__}: {e}"[:200]})
                continue
            cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_text(json.dumps(asdict(o), ensure_ascii=False), encoding="utf-8")
        o.limpa = bool(o.frac_limpa >= limiar_frac_limpa and o.ndvi_p50 is not None)
        obs.append(o)
    limpas = [o for o in obs if o.limpa]
    p50 = [o.ndvi_p50 for o in limpas]
    lidas = [o for o in obs if not o.cache]
    return {
        "area_ha": round(area_ha(geom_wgs84), 2),
        "periodo": {"inicio": inicio.isoformat(), "fim": fim.isoformat()},
        "n_cenas_stac": len(itens),
        "n_datas_disponiveis": len(por_data),
        "n_datas_lidas": len(obs),
        "n_obs_limpas": len(limpas),
        "serie": [asdict(o) for o in obs],
        "erros": erros,
        "resumo": {
            "ndvi_p50_mediana": round(float(np.median(p50)), 4) if p50 else None,
            "ndvi_p50_min": round(float(np.min(p50)), 4) if p50 else None,
            "ndvi_p50_max": round(float(np.max(p50)), 4) if p50 else None,
            "primeira_limpa": limpas[0].data if limpas else None,
            "ultima_limpa": limpas[-1].data if limpas else None,
        },
        "custo": {
            "bytes_total": int(sum(o.bytes for o in obs)),
            "requisicoes_total": int(sum(o.requisicoes for o in obs)),
            "bytes_por_data_lida": int(np.mean([o.bytes for o in lidas])) if lidas else 0,
            "segundos_por_data_lida": round(float(np.mean([o.segundos for o in lidas])), 2) if lidas else 0.0,
            "datas_do_cache": int(sum(o.cache for o in obs)),
            "busca_stac_do_cache": stac_do_cache,
            "segundos_total": round(time.perf_counter() - t0, 2),
        },
        "metadados_laudo": {
            "satelite": sorted({o.plataforma for o in obs if o.plataforma}) or ["sentinel-2"],
            "sensor": "MSI (MultiSpectral Instrument)",
            "produto": f"Sentinel-2 L2A, coleção {colecao} (Earth Search / Element 84, COG)",
            "bandas": {"B04": "vermelho, 665 nm, 10 m", "B08": "infravermelho próximo, 842 nm, 10 m",
                       "SCL": "classificação de cena, 20 m (replicada para 10 m)"},
            "resolucao_m": 10,
            # MSI quantiza em 12 bits; o L2A é distribuído em inteiros de 16 bits (DN = reflectância × 10000)
            "resolucao_radiometrica_bits": 12,
            "resolucao_temporal": "revisita de até 5 dias (constelação Sentinel-2A/2B/2C)",
            "datas": [o.data for o in obs],
            "metodologia": (f"{VERSAO_METODO}: NDVI=(B08-B04)/(B08+B04) sobre reflectância de superfície; "
                            f"pixels com centro no polígono; limpos = SCL {list(SCL_LIMPO)}; NDVI em SCL "
                            f"{list(SCL_NDVI)}; data limpa se fração limpa >= {limiar_frac_limpa}; "
                            f"até {max_datas} datas (menos nublada por faixa do período); nuvem da cena <= "
                            f"{max_nuvem_cena}%"),
            "uso_na_fiscalizacao": (
                "A série de NDVI da gleba (mediana p50 por data limpa) indica presença e vigor de vegetação "
                "(pastagem) ao longo do período, para apurar a existência de pastagem compatível com o "
                "empreendimento pecuário (MCR 2-7-9). Não conta animais nem identifica benfeitorias; se for "
                "inconclusiva, a fiscalização segue pelos métodos documental e presencial (MCR 2-7-10)."),
            "licenca": "Copernicus Sentinel data (licença livre e aberta Copernicus)",
        },
    }
