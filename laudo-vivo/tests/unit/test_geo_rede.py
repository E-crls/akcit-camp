"""Testes com rede (Earth Search + S3). Pulados por padrão; rode com LAUDO_TESTES_REDE=1.

    LAUDO_TESTES_REDE=1 scripts/py.sh -m pytest tests/unit/test_geo_rede.py -q
"""

from __future__ import annotations

import os
from datetime import date

import pytest
from shapely.geometry import box

pytestmark = [
    pytest.mark.rede,
    pytest.mark.skipif(os.environ.get("LAUDO_TESTES_REDE") != "1", reason="teste de rede (LAUDO_TESTES_REDE=1)"),
]


def test_serie_ndvi_real_pequena(tmp_path, monkeypatch):
    from laudo.tools.ndvi import EntradaSerieNdvi, serie_ndvi

    monkeypatch.setenv("LAUDO_DADOS_LOCAIS", str(tmp_path))
    gleba = box(-50.9560, -17.8560, -50.9520, -17.8520)  # ~18 ha em Rio Verde (área agrícola)
    env = serie_ndvi(EntradaSerieNdvi(poligono_wkt=gleba.wkt, inicio=date(2026, 8, 1), fim=date(2026, 9, 30),
                                      max_datas=3))
    assert env.data is not None and env.data["n_cenas_stac"] > 0
    assert env.data["custo"]["bytes_total"] > 0
    assert env.ok or env.error.code.value == "NUVEM"
