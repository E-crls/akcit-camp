"""Escolhe 3 operações reais de compra de gado em GO (com polígono) para a demo e roda `serie_ndvi`.

Uso (da raiz, depois de build.py):
    scripts/py.sh bench/fiscal_go/casos_demo.py [--sem-ndvi] [--limpar-cache]

Critérios (determinísticos; desempate pela distância a Goiânia):
- "normal": compra de matrizes (investimento), sem sinal de triagem, lotação entre 0,6 e 1,5 cab/ha,
  valor por cabeça entre p25 e p75, sem sobreposição, área de 20 a 150 ha;
- "lotacao_alta": compra de matrizes com motivo LOTACAO_ALTA (3 a 10 cab/ha), sem sobreposição e com valor
  por cabeça dentro da faixa (para isolar o sinal);
- "sobreposicao": compra de gado cuja gleba se sobrepõe em >= 50% a outra compra de gado de outra IF na mesma
  safra, com lotação abaixo de 2 cab/ha (para isolar o sinal).

Grava `casos_demo.json` (só campos públicos do Sicor/IBGE) e `ndvi_demo.json` (séries e custo medido).
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "src"))

from laudo.geo import bench
from laudo.tools.carteira import glebas_da_operacao

SAIDA = Path(__file__).resolve().parent
GOIANIA = (-49.2648, -16.6869)
PERIODO = (date(2026, 4, 1), date(2026, 10, 8))

CAMPOS = ["ref_bacen", "municipio_ibge", "municipio_nome", "instituicao", "segmento_if", "finalidade", "modalidade",
          "produto", "variedade", "programa", "categoria_emitente", "dt_emissao", "ano_agricola", "valor_rs",
          "qtd_bovinos", "unidade_qtd_bovinos", "valor_por_cabeca_rs", "area_informada_ha", "area_glebas_ha",
          "area_lotacao_ha", "n_glebas", "lotacao_implicita_cab_ha", "rebanho_municipal_cab",
          "densidade_bovina_mun_cab_ha", "razao_lotacao_densidade", "n_ops_sobrepostas", "sobreposicao_max_frac",
          "sobreposicao_ha", "refs_sobrepostas", "sobrepoe_outra_if", "exige_sensoriamento_remoto",
          "prioridade_verificacao", "prioridade_nivel", "motivos", "observacoes", "lon", "lat", "fonte_versao"]


def dist_km(lon: float, lat: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat), math.radians(GOIANIA[1])
    dl, dp = math.radians(lon - GOIANIA[0]), p2 - p1
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _json(v):
    if isinstance(v, pd.Timestamp):
        return v.date().isoformat()
    if hasattr(v, "tolist"):
        return v.tolist()
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def escolher(op: pd.DataFrame) -> dict[str, pd.Series]:
    base = op[op["eh_compra_gado"] & op["tem_poligono"] & op["municipio_ibge"].notna()].copy()
    base["dist_goiania_km"] = [dist_km(a, b) for a, b in zip(base["lon"], base["lat"], strict=True)]
    base = base.sort_values(["dist_goiania_km", "ref_bacen"])
    inv = base[base["compra_gado_tipo"].eq("investimento") & base["unidade_qtd_bovinos"].isin(["UA", "cab"])]
    vpc = inv["valor_por_cabeca_rs"]
    faixa = inv.groupby("unidade_qtd_bovinos")["valor_por_cabeca_rs"].quantile([0.25, 0.75]).unstack()

    def vpc_ok(df: pd.DataFrame) -> pd.Series:
        lo = df["unidade_qtd_bovinos"].map(faixa[0.25])
        hi = df["unidade_qtd_bovinos"].map(faixa[0.75])
        return (df["valor_por_cabeca_rs"] >= lo) & (df["valor_por_cabeca_rs"] <= hi)

    normal = inv[(inv["prioridade_verificacao"] == 0) & inv["lotacao_implicita_cab_ha"].between(0.6, 1.5)
                 & (inv["n_ops_sobrepostas"] == 0) & inv["area_glebas_ha"].between(20, 150) & vpc_ok(inv)
                 & ~inv["valor_cabeca_fora_faixa"]]
    lot = inv[inv["motivos_codigos"].map(lambda xs: "LOTACAO_ALTA" in list(xs))
              & inv["lotacao_implicita_cab_ha"].between(3, 10) & (inv["n_ops_sobrepostas"] == 0)
              & ~inv["valor_cabeca_fora_faixa"] & vpc.notna() & inv["area_glebas_ha"].between(5, 300)]
    sob = base[(base["sobreposicao_max_frac"] >= 0.5) & base["sobrepoe_outra_if"] & base["sobrepoe_compra_gado"]
               & (base["lotacao_implicita_cab_ha"] < 2) & base["area_glebas_ha"].between(5, 300)]
    out = {}
    for nome, df in [("normal", normal), ("lotacao_alta", lot), ("sobreposicao", sob)]:
        if df.empty:
            raise SystemExit(f"nenhum candidato para {nome}")
        out[nome] = df.iloc[0]
        print(f"{nome}: {len(df)} candidatos; escolhido {df.iloc[0]['ref_bacen']} "
              f"({df.iloc[0]['municipio_nome']}, {df.iloc[0]['dist_goiania_km']:.0f} km de Goiânia)")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sem-ndvi", action="store_true")
    ap.add_argument("--limpar-cache", action="store_true", help="apaga o cache de NDVI antes (mede custo real)")
    args = ap.parse_args()
    op = bench.operacoes()
    escolhidos = escolher(op)
    casos = []
    for papel, r in escolhidos.items():
        c = {"papel": papel} | {k: _json(r[k]) for k in CAMPOS}
        c["dist_goiania_km"] = round(float(r["dist_goiania_km"]), 1)
        c["glebas_wkt"] = glebas_da_operacao(r["ref_bacen"])
        if papel == "sobreposicao":
            outras = op[op["ref_bacen"].isin(list(r["refs_sobrepostas"]))]
            c["operacoes_sobrepostas"] = [{k: _json(o[k]) for k in ["ref_bacen", "instituicao", "finalidade",
                                                                     "modalidade", "dt_emissao", "valor_rs",
                                                                     "qtd_bovinos", "area_glebas_ha"]}
                                          for _, o in outras.iterrows()]
        casos.append(c)
    doc = {"gerado_em": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
           "aviso": "Prioridade de verificação não é indício de irregularidade. Dados públicos do Sicor/BCB "
                    "(REF_BACEN mascarado na origem, sem CPF/CNPJ do tomador) e IBGE PPM.",
           "casos": casos}
    (SAIDA / "casos_demo.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"casos_demo.json: {len(casos)} casos")
    if args.sem_ndvi:
        return 0

    from laudo.geo.ndvi import dir_cache
    from laudo.tools.ndvi import EntradaSerieNdvi, serie_ndvi

    if args.limpar_cache and dir_cache().exists():
        shutil.rmtree(dir_cache())
    res = {"periodo": [PERIODO[0].isoformat(), PERIODO[1].isoformat()], "casos": []}
    for c in casos:
        e = serie_ndvi(EntradaSerieNdvi(ref_bacen=c["ref_bacen"], inicio=PERIODO[0], fim=PERIODO[1], max_datas=12))
        d = e.data or {}
        res["casos"].append({"papel": c["papel"], "ref_bacen": c["ref_bacen"], "ok": e.ok,
                             "erro": e.error.model_dump(mode="json") if e.error else None,
                             "latency_ms": e.latency_ms, "fonte_versao": e.fonte_versao,
                             "n_obs_limpas": d.get("n_obs_limpas"), "resumo": d.get("resumo"),
                             "custo": d.get("custo"), "serie": d.get("serie"),
                             "metadados_laudo": d.get("metadados_laudo")})
        print(c["papel"], c["ref_bacen"], e.ok, d.get("n_obs_limpas"), json.dumps(d.get("custo")))
    (SAIDA / "ndvi_demo.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
