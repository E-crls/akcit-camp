"""NDVI: estatísticas com máscara SCL, série com STAC/leitura falsos, cache e abstenção (sem rede)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest
from shapely.geometry import box

from laudo.contracts import CodigoErro
from laudo.geo import ndvi as mod
from laudo.geo.ndvi import ObsNdvi, estatisticas, serie_ndvi

GEOM = box(-49.30, -16.70, -49.29, -16.69)


def dn(refl: float) -> int:
    """DN da coleção c1 (escala 1e-4, offset -0,1)."""
    return round((refl + 0.1) / 1e-4)


def test_estatisticas_ndvi_conhecido_e_mascara_scl():
    red = np.full((4, 4), dn(0.05), dtype=np.uint16)
    nir = np.full((4, 4), dn(0.45), dtype=np.uint16)  # NDVI = 0,4/0,5 = 0,8
    scl = np.full((4, 4), 4, dtype=np.uint8)
    scl[0, :] = 9  # nuvem alta
    scl[1, 0] = 6  # água: limpo, mas fora do NDVI
    dentro = np.ones((4, 4), bool)
    dentro[3, 3] = False
    e = estatisticas(red, nir, scl, dentro, 1e-4, -0.1, 1e-4, -0.1)
    assert e["n_pixels"] == 15
    assert e["n_limpos"] == 11  # 15 - 4 de nuvem
    assert e["frac_limpa"] == pytest.approx(11 / 15, abs=1e-4)
    assert e["ndvi_p50"] == pytest.approx(0.8, abs=1e-3)
    assert e["ndvi_p10"] == pytest.approx(0.8, abs=1e-3)


def test_estatisticas_tudo_nublado_ou_nodata():
    red = np.zeros((3, 3), np.uint16)
    nir = np.zeros((3, 3), np.uint16)
    scl = np.full((3, 3), 4, np.uint8)
    e = estatisticas(red, nir, scl, np.ones((3, 3), bool))
    assert e["n_limpos"] == 0 and e["frac_limpa"] == 0.0 and e["ndvi_p50"] is None


def item_falso(d: str, nuvem: float = 5.0, tile: str = "22KFG") -> dict:
    a = {"href": f"https://exemplo.invalid/{d}/B.tif", "escala": 1e-4, "offset": -0.1, "crs": "EPSG:32722"}
    return {"id": f"S2X_{tile}_{d}", "data": d, "nuvem": nuvem, "tile": tile, "crs": "EPSG:32722",
            "plataforma": "sentinel-2c", "geometry": box(-50, -17, -49, -16).__geo_interface__,
            "assets": {"red": a, "nir": a, "scl": a}}


def obs(it: dict, frac: float, p50: float | None = 0.6) -> ObsNdvi:
    return ObsNdvi(data=it["data"], item_id=it["id"], tile=it["tile"], plataforma="sentinel-2c",
                   nuvem_cena=it["nuvem"], n_pixels=100, n_limpos=int(100 * frac), frac_limpa=frac,
                   ndvi_p10=None if p50 is None else p50 - 0.1, ndvi_p50=p50, ndvi_p90=None if p50 is None else p50 + 0.1,
                   ndvi_media=p50, bytes=1000, requisicoes=6, segundos=0.1)


def test_serie_com_cache_e_metadados(tmp_path):
    itens = [item_falso("2026-08-01"), item_falso("2026-08-11", 40), item_falso("2026-08-21")]
    lidos = []

    def ler(it, geom):
        lidos.append(it["id"])
        return obs(it, 0.2 if it["data"] == "2026-08-11" else 0.95)

    r = serie_ndvi(GEOM, date(2026, 8, 1), date(2026, 8, 31), cache=tmp_path,
                   buscar=lambda *a, **k: itens, ler=ler)
    assert r["n_datas_lidas"] == 3 and r["n_obs_limpas"] == 2
    assert r["custo"]["bytes_total"] == 3000 and r["custo"]["datas_do_cache"] == 0
    assert r["metadados_laudo"]["resolucao_m"] == 10 and "B08" in r["metadados_laudo"]["bandas"]
    assert r["metadados_laudo"]["datas"] == ["2026-08-01", "2026-08-11", "2026-08-21"]
    # segunda chamada: tudo do cache em disco (por tile/data), nenhuma leitura nova
    r2 = serie_ndvi(GEOM, date(2026, 8, 1), date(2026, 8, 31), cache=tmp_path,
                    buscar=lambda *a, **k: itens, ler=ler)
    assert len(lidos) == 3
    assert r2["custo"]["datas_do_cache"] == 3 and r2["custo"]["bytes_total"] == 0
    assert list(tmp_path.glob("22KFG/2026-08-01/*.json"))


def test_serie_registra_erro_de_uma_data_sem_derrubar(tmp_path):
    itens = [item_falso("2026-08-01"), item_falso("2026-08-11")]

    def ler(it, geom):
        if it["data"] == "2026-08-11":
            raise OSError("timeout simulado")
        return obs(it, 1.0)

    r = serie_ndvi(GEOM, date(2026, 8, 1), date(2026, 8, 31), cache=tmp_path, buscar=lambda *a, **k: itens,
                   ler=ler)
    assert r["n_datas_lidas"] == 1 and len(r["erros"]) == 1


def test_ferramenta_abstem_com_nuvem(monkeypatch, tmp_path):
    from laudo.tools.ndvi import EntradaSerieNdvi
    from laudo.tools.ndvi import serie_ndvi as ferramenta

    monkeypatch.setenv("LAUDO_DADOS_LOCAIS", str(tmp_path))
    itens = [item_falso("2026-01-05", 70), item_falso("2026-01-15", 60), item_falso("2026-01-25", 50)]
    monkeypatch.setattr(mod.stac, "buscar", lambda *a, **k: itens)
    monkeypatch.setattr(mod, "ler_observacao", lambda it, g: obs(it, 0.1 if it["data"] != "2026-01-15" else 0.9))
    env = ferramenta(EntradaSerieNdvi(poligono_wkt=GEOM.wkt, inicio=date(2026, 1, 1), fim=date(2026, 1, 31)))
    assert not env.ok
    assert env.error.code == CodigoErro.NUVEM
    assert env.data["n_obs_limpas"] == 1 and env.data["n_datas_lidas"] == 3


def test_ferramenta_sucesso_e_validacoes(monkeypatch, tmp_path):
    from laudo.tools.ndvi import EntradaSerieNdvi
    from laudo.tools.ndvi import serie_ndvi as ferramenta

    monkeypatch.setenv("LAUDO_DADOS_LOCAIS", str(tmp_path))
    itens = [item_falso("2026-07-05"), item_falso("2026-07-25")]
    monkeypatch.setattr(mod.stac, "buscar", lambda *a, **k: itens)
    monkeypatch.setattr(mod, "ler_observacao", lambda it, g: obs(it, 1.0))
    env = ferramenta(EntradaSerieNdvi(poligono_wkt=GEOM.wkt, inicio=date(2026, 7, 1), fim=date(2026, 7, 31)))
    assert env.ok and env.data["n_obs_limpas"] == 2 and env.ferramenta == "serie_ndvi"
    assert env.fonte_versao.startswith("earth-search:sentinel-2-c1-l2a")
    # entradas ruins viram falha, não exceção
    ruim = ferramenta(EntradaSerieNdvi(poligono_wkt="POLYGON ((0 0, 1 1", inicio=date(2026, 7, 1),
                                       fim=date(2026, 7, 2)))
    assert not ruim.ok and ruim.error.code == CodigoErro.ENTRADA_INVALIDA
    fora = ferramenta(EntradaSerieNdvi(poligono_wkt=box(500000, 8000000, 501000, 8001000).wkt,
                                       inicio=date(2026, 7, 1), fim=date(2026, 7, 2)))
    assert not fora.ok and fora.error.code == CodigoErro.FORA_DO_ESCOPO
    grande = ferramenta(EntradaSerieNdvi(poligono_wkt=box(-50, -17, -49.5, -16.5).wkt, inicio=date(2026, 7, 1),
                                         fim=date(2026, 7, 2)))
    assert not grande.ok and grande.error.code == CodigoErro.FORA_DO_ESCOPO


def test_entrada_exige_poligono_ou_ref():
    from pydantic import ValidationError

    from laudo.tools.ndvi import EntradaSerieNdvi

    with pytest.raises(ValidationError):
        EntradaSerieNdvi(inicio=date(2026, 7, 1), fim=date(2026, 7, 2))
    with pytest.raises(ValidationError):
        EntradaSerieNdvi(poligono_wkt=GEOM.wkt, inicio=date(2026, 7, 2), fim=date(2026, 7, 1))
