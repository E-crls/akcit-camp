"""Ferramenta `serie_ndvi`: série Sentinel-2 (NDVI p10/p50/p90 por data) de uma gleba.

Aceita um polígono WKT (WGS84) ou um REF_BACEN do Fiscal-GO 2026 (usa a união das glebas).
Abstém-se (`NUVEM`) quando há menos de 2 observações limpas no período. Os metadados exigidos
para o laudo remoto (MCR 2-7 item 4: satélite, sensor, datas, resolução, bandas, metodologia)
vão em `metadados_laudo`.
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime

import httpx
from pydantic import BaseModel, Field, model_validator
from shapely.errors import ShapelyError

from laudo.contracts import CodigoErro, Envelope, registrar
from laudo.geo import bench
from laudo.geo.geometria import area_ha, ler_wkt, uniao
from laudo.geo.stac import COLECAO

MAX_AREA_HA = 5_000.0  # janela de ~7 km: acima disso o custo por data foge do orçamento da ferramenta
MIN_OBS_LIMPAS = 2


class EntradaSerieNdvi(BaseModel):
    poligono_wkt: str | None = Field(None, description="POLYGON ou MULTIPOLYGON em WGS84 (lon lat).")
    ref_bacen: str | None = Field(None, pattern=r"^\d{5,12}$", description="Usa as glebas públicas da operação.")
    inicio: date
    fim: date
    max_nuvem_cena: float = Field(80.0, ge=0, le=100, description="Filtro eo:cloud_cover da cena (%).")
    limiar_frac_limpa: float = Field(0.6, ge=0.05, le=1.0,
                                     description="Fração mínima de pixels limpos no polígono para a data contar.")
    max_datas: int = Field(12, ge=1, le=40, description="Máximo de datas lidas (a menos nublada por faixa).")

    @model_validator(mode="after")
    def _validar(self):
        if not self.poligono_wkt and not self.ref_bacen:
            raise ValueError("informe poligono_wkt ou ref_bacen")
        if self.fim < self.inicio:
            raise ValueError("fim anterior ao início")
        return self


@registrar("serie_ndvi",
           "Série temporal de NDVI (Sentinel-2 L2A, 10 m) de um polígono ou das glebas de uma operação: p10/p50/p90 "
           "por data, fração limpa (máscara SCL), bytes e tempo. Abstém-se com NUVEM se houver menos de 2 datas limpas.",
           EntradaSerieNdvi, timeout_s=240.0)
def serie_ndvi(args: EntradaSerieNdvi) -> Envelope:
    from laudo.geo.ndvi import serie_ndvi as calcular

    t0 = time.perf_counter()
    nome = "serie_ndvi"
    origem = "wkt"
    try:
        if args.poligono_wkt:
            geom = ler_wkt(args.poligono_wkt)
        else:
            gl = bench.glebas()
            wkts = gl.loc[gl["ref_bacen"] == args.ref_bacen, "wkt"].tolist()
            if not wkts:
                return Envelope.falha(nome, CodigoErro.SEM_DADOS,
                                      f"REF_BACEN {args.ref_bacen} sem polígono público no Sicor", t0=t0)
            geom = uniao(wkts)
            origem = f"sicor:{args.ref_bacen}"
    except bench.BenchAusente as e:
        return Envelope.falha(nome, CodigoErro.SEM_DADOS, str(e), t0=t0)
    except (ShapelyError, ValueError, TypeError) as e:
        return Envelope.falha(nome, CodigoErro.ENTRADA_INVALIDA, f"WKT inválido: {e}", t0=t0)
    if geom.is_empty or geom.geom_type not in ("Polygon", "MultiPolygon"):
        return Envelope.falha(nome, CodigoErro.ENTRADA_INVALIDA, "geometria vazia ou não poligonal", t0=t0)
    minx, miny, maxx, maxy = geom.bounds
    if not (-75 <= minx <= maxx <= -30 and -35 <= miny <= maxy <= 6):
        return Envelope.falha(nome, CodigoErro.FORA_DO_ESCOPO,
                              "polígono fora do Brasil ou em coordenadas não WGS84 (lon lat)", t0=t0)
    a = area_ha(geom)
    if a > MAX_AREA_HA:
        return Envelope.falha(nome, CodigoErro.FORA_DO_ESCOPO,
                              f"área de {a:,.0f} ha acima do limite de {MAX_AREA_HA:,.0f} ha da ferramenta", t0=t0)
    try:
        res = calcular(geom, args.inicio, args.fim, max_nuvem_cena=args.max_nuvem_cena,
                       limiar_frac_limpa=args.limiar_frac_limpa, max_datas=args.max_datas)
    except (httpx.TimeoutException, TimeoutError) as e:
        return Envelope.falha(nome, CodigoErro.TIMEOUT, f"tempo esgotado no STAC/COG: {e}", retryable=True, t0=t0)
    except (httpx.HTTPError, OSError) as e:
        return Envelope.falha(nome, CodigoErro.ERRO_INTERNO, f"falha de rede no STAC/COG: {e}"[:300], retryable=True,
                              t0=t0)
    res["origem_poligono"] = origem
    fv = f"earth-search:{COLECAO}@{datetime.now(UTC).date().isoformat()}"
    if res["n_cenas_stac"] == 0:
        return Envelope.falha(nome, CodigoErro.SEM_DADOS, "nenhuma cena Sentinel-2 no período", t0=t0, data=res)
    if res["n_obs_limpas"] < MIN_OBS_LIMPAS:
        res["status"] = "indeterminado"
        return Envelope.falha(nome, CodigoErro.NUVEM,
                              f"só {res['n_obs_limpas']} observação(ões) limpa(s) de {res['n_datas_lidas']} lidas: "
                              "abstenção (pedir outro período ou verificação presencial)", t0=t0, data=res)
    # StatusChecagem: "ok" = série conclusiva (≥ 2 datas limpas). A ferramenta não julga a pastagem; o
    # resumo (NDVI p50) vai para o laudo e para o fiscal.
    res["status"] = "ok"
    r = res.get("resumo") or {}
    res["motivo"] = (f"{res['n_obs_limpas']} data(s) limpa(s) de {res['n_datas_lidas']}; NDVI p50 mediano "
                     f"{r.get('ndvi_p50_mediana')} (mín. {r.get('ndvi_p50_min')}, máx. {r.get('ndvi_p50_max')})")
    return Envelope.sucesso(nome, res, fonte_versao=fv, t0=t0)
