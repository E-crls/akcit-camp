"""Baixa o rebanho bovino por município de Goiás (IBGE PPM) e a malha municipal de GO.

Uso (da raiz do repositório):
    scripts/py.sh scripts/dados_ibge.py [--uf 52]

Saída em `dados_locais/ibge/`:
    ppm_bovinos_go.parquet   cod_ibge, municipio, ano, bovinos_cab (última data disponível no SIDRA)
    municipios_go.parquet    cod_ibge, municipio, area_ha (Albers/IBGE, calculada da malha), wkt (WGS84)
    fontes.json              URLs, bytes e sha256

Fontes (IBGE, dados abertos; atribuição "Fonte: IBGE"):
    PPM, tabela SIDRA 3939 ("Efetivo dos rebanhos, por tipo de rebanho"), variável 105, rebanho 2670
    (Bovino), último período:
        https://apisidra.ibge.gov.br/values/t/3939/n6/in%20n3%2052/v/105/p/last%201/c79/2670
    Malha municipal (API de malhas v3, qualidade máxima):
        https://servicodados.ibge.gov.br/api/v3/malhas/estados/52?intrarregiao=municipio&qualidade=maxima
        &formato=application/vnd.geo+json
    Nomes dos municípios: https://servicodados.ibge.gov.br/api/v1/localidades/estados/52/municipios
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from shapely.geometry import shape

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from laudo.geo.fontes import InfoDownload, baixar_bytes
from laudo.geo.geometria import area_ha, corrigir

SAIDA = RAIZ / "dados_locais" / "ibge"


def baixar_ppm(cod_uf: str) -> tuple[pd.DataFrame, InfoDownload]:
    url = (f"https://apisidra.ibge.gov.br/values/t/3939/n6/in%20n3%20{cod_uf}/v/105/p/last%201/"
           "c79/2670")
    info = InfoDownload(url=url)
    dados = json.loads(baixar_bytes(url, info))
    reg = []
    for d in dados[1:]:  # a primeira linha é o cabeçalho
        v = d["V"]
        reg.append({
            "cod_ibge": d["D1C"],
            "municipio": d["D1N"].rsplit(" - ", 1)[0],
            "ano": int(d["D3C"]),
            # "-" = zero absoluto; "..."/"X" = não disponível/sigilo
            "bovinos_cab": 0.0 if v == "-" else pd.to_numeric(v, errors="coerce"),
        })
    df = pd.DataFrame(reg)
    info.linhas_mantidas = len(df)
    return df, info


def baixar_malha(cod_uf: str) -> tuple[pd.DataFrame, InfoDownload, InfoDownload]:
    url = (f"https://servicodados.ibge.gov.br/api/v3/malhas/estados/{cod_uf}?intrarregiao=municipio"
           "&qualidade=maxima&formato=application/vnd.geo%2Bjson")
    info = InfoDownload(url=url)
    gj = json.loads(baixar_bytes(url, info))
    url_n = f"https://servicodados.ibge.gov.br/api/v1/localidades/estados/{cod_uf}/municipios"
    info_n = InfoDownload(url=url_n)
    nomes = {str(m["id"]): m["nome"] for m in json.loads(baixar_bytes(url_n, info_n))}
    reg = []
    for f in gj["features"]:
        cod = str(f["properties"]["codarea"])
        g = corrigir(shape(f["geometry"]))
        reg.append({"cod_ibge": cod, "municipio": nomes.get(cod), "area_ha": round(area_ha(g), 1),
                    "wkt": g.wkt})
    df = pd.DataFrame(reg).sort_values("cod_ibge").reset_index(drop=True)
    info.linhas_mantidas = len(df)
    return df, info, info_n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--uf", default="52", help="código IBGE da UF (52 = Goiás)")
    args = ap.parse_args()
    SAIDA.mkdir(parents=True, exist_ok=True)
    fontes = {}
    t = time.perf_counter()
    ppm, info = baixar_ppm(args.uf)
    ppm.to_parquet(SAIDA / "ppm_bovinos_go.parquet", index=False)
    fontes["ppm_3939"] = info.como_dict() | {"segundos": round(time.perf_counter() - t, 1)}
    print(f"PPM {ppm.ano.max()}: {len(ppm)} municípios, {ppm.bovinos_cab.sum():,.0f} bovinos")
    t = time.perf_counter()
    mun, info, info_n = baixar_malha(args.uf)
    mun.to_parquet(SAIDA / "municipios_go.parquet", index=False, compression="zstd")
    fontes["malha"] = info.como_dict() | {"segundos": round(time.perf_counter() - t, 1)}
    fontes["localidades"] = info_n.como_dict()
    print(f"malha: {len(mun)} municípios, área {mun.area_ha.sum() / 100:,.0f} km²")
    fontes["_gerado_em"] = datetime.now(UTC).astimezone().isoformat(timespec="seconds")
    (SAIDA / "fontes.json").write_text(json.dumps(fontes, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
