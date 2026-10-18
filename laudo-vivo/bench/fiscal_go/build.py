"""Monta o bench "Fiscal-GO 2026" a partir dos recortes em `dados_locais/`.

Pré-requisitos (da raiz do repositório):
    scripts/py.sh scripts/dados_sicor.py
    scripts/py.sh scripts/dados_ibge.py
Depois:
    scripts/py.sh bench/fiscal_go/build.py

Gera em `bench/fiscal_go/`:
    fiscal_go_2026.parquet       uma linha por operação (REF_BACEN) de GO emitida em 2026
    itens_go_2026.parquet        uma linha por item (REF_BACEN, NU_ORDEM), empreendimento decodificado
    glebas_go_2026.parquet       polígonos das glebas (WKT 2D, WGS84) e área em ha
    rebanho_municipal_go.parquet rebanho bovino (IBGE PPM), área e densidade por município de GO
    resumo.json                  números-chave

Sem PII: os arquivos do Sicor usados não têm CPF/CNPJ nem nome do tomador; o script confere.
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import numpy as np
import pandas as pd
import shapely

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "src"))

from laudo.geo.geometria import (
    corrigir,
    para_albers_vetor,
    ponto_representativo,
    sobreposicoes,
)
from laudo.geo.triagem import LIMIARES, ano_agricola, nivel, pontuar

DL = RAIZ / "dados_locais"
SAIDA = Path(__file__).resolve().parent
ANO = 2026

SISTEMAS_COOP = {"02038232": "Sicoob", "01181521": "Sicredi", "01401771": "Cresol"}
UNIDADES = {"Unidade Animal (450kg)": "UA", "Unidade": "cab", "Quantidade": "cab"}


# ---------------------------------------------------------------------------
# Itens (uma linha por REF_BACEN x NU_ORDEM)
# ---------------------------------------------------------------------------


def tipo_item(modalidade: str | None, produto: str | None) -> str:
    m, p = (modalidade or "").upper(), (produto or "").upper()
    if p == "BOVINOS":
        return "bovinos"
    if m == "LAVOURA":
        return "lavoura"
    if "PASTAGEM" in m or "PASTAGEM" in p:
        return "pastagem"
    if "ARMAZÉM" in p or "GALPÃO" in p:
        return "galpao"
    if "MÁQUINAS" in m or "VEÍCULOS" in m:
        return "maquina"
    return "outro"


def unidade_item(tipo: str, unidade_medida: str | None) -> str | None:
    if tipo == "bovinos":
        return "UA_450kg" if unidade_medida == "Unidade Animal (450kg)" else "cabeca"
    if tipo in ("lavoura", "pastagem") or unidade_medida == "Hectare":
        return "ha"
    if unidade_medida in ("Unidade", "Quantidade"):
        return "un"
    return None


def montar_itens(ops: pd.DataFrame, tab: dict[str, pd.DataFrame]) -> pd.DataFrame:
    emp = tab["empreendimento"].drop_duplicates("CODIGO")
    cols = ["CODIGO", "FINALIDADE", "ATIVIDADE", "MODALIDADE", "PRODUTO", "VARIEDADE", "UNIDADE_MEDIDA"]
    it = ops.merge(emp[cols], left_on="CD_EMPREENDIMENTO", right_on="CODIGO", how="left")
    fase = tab["fase_ciclo_producao"].set_index("CODIGO")["DESCRICAO"]
    it["fase"] = it["CD_FASE_CICLO_PRODUCAO"].map(fase)
    bov = it["PRODUTO"].eq("BOVINOS")
    it["compra_tipo"] = np.select(
        [bov & it["FINALIDADE"].eq("Investimento") & it["MODALIDADE"].eq("AQUISIÇÃO DE ANIMAIS"),
         bov & it["FINALIDADE"].eq("Custeio") & it["MODALIDADE"].eq("AQUISIÇÃO E MANUTENÇÃO DE ANIMAIS")],
        ["investimento", "custeio"], default="")
    it["tipo_item"] = [tipo_item(m, p) for m, p in zip(it["MODALIDADE"], it["PRODUTO"], strict=True)]
    it["unidade_item"] = [unidade_item(t, u) for t, u in zip(it["tipo_item"], it["UNIDADE_MEDIDA"], strict=True)]
    return it


# ---------------------------------------------------------------------------
# Operações (uma linha por REF_BACEN)
# ---------------------------------------------------------------------------


def _lista_unica(s: pd.Series) -> list[str]:
    return sorted({str(x) for x in s.dropna()})


def agregar_operacoes(it: pd.DataFrame, tab: dict[str, pd.DataFrame]) -> pd.DataFrame:
    principal = it.sort_values(["REF_BACEN", "VL_PARC_CREDITO"], ascending=[True, False]) \
        .drop_duplicates("REF_BACEN").set_index("REF_BACEN")
    g = it.groupby("REF_BACEN")
    op = pd.DataFrame({
        "n_itens": g.size(),
        "valor_rs": g["VL_PARC_CREDITO"].sum(min_count=1),
        "recurso_proprio_rs": g["VL_REC_PROPRIO"].sum(min_count=1),
        "area_informada_ha": g["VL_AREA_INFORMADA"].max(),
        "area_financiada_ha": g["VL_AREA_FINANC"].max(),
        "modalidades": g["MODALIDADE"].agg(_lista_unica),
        "tipos_itens": g["tipo_item"].agg(_lista_unica),
    })
    for c_out, c_in in [("dt_emissao", "DT_EMISSAO"), ("dt_vencimento", "DT_VENCIMENTO"),
                        ("if_cnpj_base", "CNPJ_IF"), ("cadastrante_cnpj_base", "CD_CNPJ_CADASTRANTE"),
                        ("cd_categ_emitente", "CD_CATEG_EMITENTE"), ("cd_programa", "CD_PROGRAMA"),
                        ("cd_fonte_recurso", "CD_FONTE_RECURSO"), ("cd_empreendimento", "CD_EMPREENDIMENTO"),
                        ("finalidade", "FINALIDADE"), ("atividade", "ATIVIDADE"), ("modalidade", "MODALIDADE"),
                        ("produto", "PRODUTO"), ("variedade", "VARIEDADE"), ("unidade_medida", "UNIDADE_MEDIDA"),
                        ("fase_ciclo", "fase"), ("pc_bonus_car", "PC_BONUS_CAR")]:
        op[c_out] = principal[c_in]

    ifs = tab["lista_ifs"].drop_duplicates("CNPJ_IF").set_index("CNPJ_IF")
    op["instituicao"] = op["if_cnpj_base"].map(ifs["NOME_IF"])
    op["segmento_if"] = op["if_cnpj_base"].map(ifs["SEGMENTO_IF"])
    op["sistema_cooperativo"] = op["cadastrante_cnpj_base"].map(SISTEMAS_COOP)
    op["categoria_emitente"] = op["cd_categ_emitente"].map(
        tab["categoria_emitente"].drop_duplicates("CODIGO").set_index("CODIGO")["DESCRICAO"])
    op["programa"] = op["cd_programa"].map(tab["programa"].drop_duplicates("CODIGO").set_index("CODIGO")["DESCRICAO"])
    op["fonte_recurso"] = op["cd_fonte_recurso"].map(
        tab["fonte_recursos"].drop_duplicates("CODIGO").set_index("CODIGO")["DESCRICAO"])
    op["ano_agricola"] = [ano_agricola(d) for d in op["dt_emissao"]]

    # bovinos: compra (investimento ou custeio de aquisição) e pecuária bovina em geral
    bov = it[it["tipo_item"].eq("bovinos")]
    op["eh_pecuaria_bovina"] = op.index.isin(bov["REF_BACEN"])
    compra = bov[bov["compra_tipo"].ne("")]
    tipo_compra = compra.groupby("REF_BACEN")["compra_tipo"].agg(
        lambda s: "investimento" if (s == "investimento").any() else "custeio")
    op["compra_gado_tipo"] = tipo_compra.reindex(op.index)
    op["eh_compra_gado"] = op["compra_gado_tipo"].notna()
    # para a lotação, usa os itens de compra quando houver; senão, todos os itens bovinos
    base = pd.concat([compra, bov[~bov["REF_BACEN"].isin(compra["REF_BACEN"])]])
    gb = base.groupby("REF_BACEN")
    qtd = gb["VL_QUANTIDADE"].sum(min_count=1)
    area_inf = base.assign(a=base["VL_AREA_INFORMADA"].where(base["VL_AREA_INFORMADA"] > 0)).groupby("REF_BACEN")["a"] \
        .sum(min_count=1)
    area_fin = base.assign(a=base["VL_AREA_FINANC"].where(base["VL_AREA_FINANC"] > 0)).groupby("REF_BACEN")["a"] \
        .sum(min_count=1)
    op["qtd_bovinos"] = qtd.reindex(op.index)
    op["unidade_qtd_bovinos"] = gb["UNIDADE_MEDIDA"].agg(
        lambda s: "misto" if s.map(UNIDADES).nunique() > 1 else UNIDADES.get(s.iloc[0], "cab")).reindex(op.index)
    op["valor_bovinos_rs"] = gb["VL_PARC_CREDITO"].sum(min_count=1).reindex(op.index)
    op["confinamento"] = gb["CD_FASE_CICLO_PRODUCAO"].agg(lambda s: (s == "60").any()).reindex(op.index) \
        .fillna(False).astype(bool)
    # denominador conservador: a maior entre a área dos itens bovinos e a maior área informada de
    # qualquer item da operação (há itens bovinos com área-placeholder de 0,02–0,06 ha)
    den_inf = pd.concat([area_inf.reindex(op.index), op["area_informada_ha"].where(op["area_informada_ha"] > 0)],
                        axis=1).max(axis=1)
    den_fin = pd.concat([area_fin.reindex(op.index), op["area_financiada_ha"].where(op["area_financiada_ha"] > 0)],
                        axis=1).max(axis=1)
    op["area_lotacao_ha"] = den_inf.where(op.index.isin(base["REF_BACEN"]))
    op["lotacao_implicita_cab_ha"] = qtd.reindex(op.index) / den_inf
    op["lotacao_area_financiada_cab_ha"] = qtd.reindex(op.index) / den_fin
    op["valor_por_cabeca_rs"] = (op["valor_bovinos_rs"] / op["qtd_bovinos"]).where(op["qtd_bovinos"] > 0)
    for c in ["lotacao_implicita_cab_ha", "lotacao_area_financiada_cab_ha", "valor_por_cabeca_rs"]:
        op[c] = op[c].replace([np.inf, -np.inf], np.nan)
    return op


def faixa_valor_cabeca(op: pd.DataFrame) -> pd.DataFrame:
    """Marca valor por cabeça fora de p1–p99 entre operações de mesma compra e unidade."""
    op["valor_cabeca_fora_faixa"] = False
    op["faixa_valor_cabeca"] = None
    ok = op["eh_compra_gado"] & op["valor_por_cabeca_rs"].notna()
    for (tipo, unid), sub in op[ok].groupby(["compra_gado_tipo", "unidade_qtd_bovinos"]):
        if len(sub) < 50:
            continue
        p1, p99 = sub["valor_por_cabeca_rs"].quantile([0.01, 0.99])
        fora = (sub["valor_por_cabeca_rs"] < p1) | (sub["valor_por_cabeca_rs"] > p99)
        op.loc[sub.index, "valor_cabeca_fora_faixa"] = fora
        op.loc[sub.index, "faixa_valor_cabeca"] = f"R$ {p1:,.0f}–{p99:,.0f} por {unid}".replace(",", ".")
    return op


# ---------------------------------------------------------------------------
# Geometria: glebas, município, sobreposição
# ---------------------------------------------------------------------------


def montar_glebas(gl: pd.DataFrame) -> pd.DataFrame:
    geoms = [corrigir(shapely.from_wkt(w)) for w in gl["WKT"]]
    alb = para_albers_vetor(geoms)
    out = pd.DataFrame({"ref_bacen": gl["REF_BACEN"].values, "nu_ordem": gl["NU_ORDEM"].values,
                        "nu_indice": gl["NU_INDICE"].values,
                        "area_ha": np.round(shapely.area(alb) / 10_000.0, 4),
                        "wkt": shapely.to_wkt(np.asarray(geoms, dtype=object), rounding_precision=7)})
    out["_geom"] = geoms
    return out


def geometria_operacoes(glebas: pd.DataFrame) -> pd.DataFrame:
    validas = glebas[~shapely.is_empty(np.asarray(glebas["_geom"].tolist(), dtype=object))]
    uni = validas.groupby("ref_bacen")["_geom"].agg(lambda s: corrigir(shapely.union_all(list(s))))
    g = pd.DataFrame({"geom": uni})
    g["n_glebas"] = glebas.groupby("ref_bacen").size().reindex(g.index)
    alb = para_albers_vetor(g["geom"].tolist())
    g["geom_albers"] = list(alb)
    g["area_glebas_ha"] = shapely.area(alb) / 10_000.0
    pts = [ponto_representativo(x) for x in g["geom"]]
    g["lon"] = [p[0] if p else None for p in pts]
    g["lat"] = [p[1] if p else None for p in pts]
    return g


def atribuir_municipio(g: pd.DataFrame, mun: pd.DataFrame) -> pd.Series:
    mgeoms = np.asarray([shapely.from_wkt(w) for w in mun["wkt"]], dtype=object)
    arvore = shapely.STRtree(mgeoms)
    pts = shapely.points(g["lon"].to_numpy(dtype=float), g["lat"].to_numpy(dtype=float))
    idx_in, idx_mun = arvore.query(pts, predicate="within")
    cod = pd.Series([None] * len(g), index=g.index, dtype=object)
    cod.iloc[idx_in] = mun["cod_ibge"].to_numpy()[idx_mun]
    faltam = np.where(cod.isna().to_numpy())[0]
    if len(faltam):  # ponto na divisa ou fora de GO por imprecisão: município mais próximo
        _, viz = arvore.query_nearest(pts[faltam], return_distance=False, all_matches=False)
        cod.iloc[faltam] = mun["cod_ibge"].to_numpy()[viz]
    return cod


def calcular_sobreposicoes(op: pd.DataFrame, g: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    refs = g.index.to_numpy()
    grupos = op.loc[refs, "ano_agricola"].fillna("?").to_numpy()
    pares = sobreposicoes(g["geom_albers"].tolist(), grupos=list(grupos),
                          min_area_ha=LIMIARES["sobrep_min_ha"], min_frac=0.05)
    if_ref = op.loc[refs, "if_cnpj_base"].to_numpy()
    compra = op.loc[refs, "eh_compra_gado"].to_numpy()
    lado: dict[str, list[tuple[str, float, float, bool, bool]]] = {}
    for p in pares:
        a, b = refs[p.i], refs[p.j]
        outra = if_ref[p.i] != if_ref[p.j]
        lado.setdefault(a, []).append((b, p.frac_i, p.area_inter_ha, outra, bool(compra[p.j])))
        lado.setdefault(b, []).append((a, p.frac_j, p.area_inter_ha, outra, bool(compra[p.i])))
    reg = {}
    for ref, lst in lado.items():
        lst.sort(key=lambda t: -t[1])
        reg[ref] = {
            "n_ops_sobrepostas": len(lst),
            "sobreposicao_max_frac": round(lst[0][1], 4),
            "sobreposicao_ha": round(lst[0][2], 2),
            "refs_sobrepostas": [t[0] for t in lst[:5]],
            "sobrepoe_outra_if": any(t[3] for t in lst),
            "sobrepoe_compra_gado": any(t[4] for t in lst),
        }
    s = pd.DataFrame.from_dict(reg, orient="index")
    return s, len(pares)


# ---------------------------------------------------------------------------
# Principal
# ---------------------------------------------------------------------------


def checar_pii(df: pd.DataFrame, nome: str) -> None:
    proibidas = re.compile(r"CPF|CNPJ_CPF|MUTUARIO|NOME_TOMADOR|AGENCIA|CEDULA|SNCR|NIRF|CD_CAR", re.IGNORECASE)
    ruins = [c for c in df.columns if proibidas.search(c)]
    assert not ruins, f"{nome}: colunas com possível PII: {ruins}"
    # CPF (11 dígitos) ou CNPJ completo (14 dígitos), com ou sem pontuação. Colunas de código do
    # Sicor (cd_*, 14 dígitos no empreendimento) e a raiz de 8 dígitos do CNPJ da IF ficam de fora.
    doc = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b|\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
    for c in df.columns:
        if c.startswith("cd_") or c in ("wkt", "_geom"):
            continue
        if df[c].dtype == object:
            amostra = df[c].dropna().astype(str)
            achou = amostra[amostra.str.contains(doc)]
            assert achou.empty, f"{nome}.{c}: valor com formato de CPF/CNPJ completo: {achou.iloc[0][:40]}"


def main() -> int:
    t0 = time.perf_counter()
    sic = DL / "sicor"
    ops = pd.read_parquet(sic / f"operacoes_go_{ANO}.parquet")
    tab = {n: pd.read_parquet(sic / "tabelas" / f"{n}.parquet") for n in
           ["empreendimento", "categoria_emitente", "programa", "fonte_recursos", "lista_ifs",
            "fase_ciclo_producao"]}
    gl = pd.read_parquet(sic / f"glebas_go_{ANO}.parquet")
    ppm = pd.read_parquet(DL / "ibge" / "ppm_bovinos_go.parquet")
    mun = pd.read_parquet(DL / "ibge" / "municipios_go.parquet")
    fontes_sicor = json.loads((sic / "fontes.json").read_text(encoding="utf-8"))
    print(f"lidos: {len(ops)} itens, {len(gl)} glebas ({time.perf_counter() - t0:.1f} s)")

    it = montar_itens(ops, tab)
    op = agregar_operacoes(it, tab)
    op = faixa_valor_cabeca(op)

    glebas = montar_glebas(gl)
    g = geometria_operacoes(glebas)
    op = op.join(g[["n_glebas", "area_glebas_ha", "lon", "lat"]])
    op["tem_poligono"] = op["area_glebas_ha"].fillna(0) > 0
    op["n_glebas"] = op["n_glebas"].fillna(0).astype(int)
    op["lotacao_gleba_cab_ha"] = (op["qtd_bovinos"] / op["area_glebas_ha"]).where(op["area_glebas_ha"] > 0)

    # município: complemento do Sicor (se baixado) ou ponto representativo das glebas
    op["municipio_ibge"] = atribuir_municipio(g, mun).reindex(op.index)
    op["municipio_fonte"] = np.where(op["municipio_ibge"].notna(), "poligono", None)
    comp_p = sic / f"municipio_operacao_go_{ANO}.parquet"
    if comp_p.exists():
        comp = pd.read_parquet(comp_p).drop_duplicates("REF_BACEN").set_index("REF_BACEN")["CD_IBGE_MUNICIPIO"]
        m = comp.reindex(op.index)
        op["municipio_fonte"] = np.where(m.notna(), "sicor_complemento", op["municipio_fonte"])
        op["municipio_ibge"] = m.fillna(op["municipio_ibge"])
    nomes = mun.set_index("cod_ibge")["municipio"]
    op["municipio_nome"] = op["municipio_ibge"].map(nomes)

    # IBGE: rebanho e densidade
    reb = mun[["cod_ibge", "municipio", "area_ha"]].merge(ppm[["cod_ibge", "ano", "bovinos_cab"]], on="cod_ibge",
                                                         how="left")
    reb["densidade_bovina_cab_ha"] = reb["bovinos_cab"] / reb["area_ha"]
    ri = reb.set_index("cod_ibge")
    op["rebanho_municipal_cab"] = op["municipio_ibge"].map(ri["bovinos_cab"])
    op["densidade_bovina_mun_cab_ha"] = op["municipio_ibge"].map(ri["densidade_bovina_cab_ha"])
    op["razao_lotacao_densidade"] = op["lotacao_implicita_cab_ha"] / op["densidade_bovina_mun_cab_ha"]
    op["frac_rebanho_mun"] = (op["qtd_bovinos"] / op["rebanho_municipal_cab"]).where(op["eh_compra_gado"])
    agg_mun = op[op["eh_compra_gado"] & op["municipio_ibge"].notna()].groupby("municipio_ibge").agg(
        ops_compra_gado_2026=("qtd_bovinos", "size"), qtd_compra_gado_2026=("qtd_bovinos", "sum"))
    reb = reb.merge(agg_mun, left_on="cod_ibge", right_index=True, how="left")
    reb["frac_rebanho_financiado_2026"] = reb["qtd_compra_gado_2026"] / reb["bovinos_cab"]

    # sobreposição
    t = time.perf_counter()
    sob, n_pares = calcular_sobreposicoes(op, g)
    op = op.join(sob)
    op["n_ops_sobrepostas"] = op["n_ops_sobrepostas"].fillna(0).astype(int)
    for c in ["sobrepoe_outra_if", "sobrepoe_compra_gado"]:
        op[c] = op[c].fillna(False).astype(bool)
    op["refs_sobrepostas"] = op["refs_sobrepostas"].apply(lambda x: x if isinstance(x, list) else [])
    print(f"sobreposição: {n_pares} pares em {time.perf_counter() - t:.1f} s")

    # >300 ha (MCR 2-7 item 5)
    area_total = op[["area_informada_ha", "area_glebas_ha"]].max(axis=1)
    op["area_total_ha"] = area_total
    op["acima_300ha"] = area_total > LIMIARES["sr_area_ha"]
    op["exige_sensoriamento_remoto"] = op["acima_300ha"] & op["finalidade"].isin(["Custeio", "Investimento"]) \
        & (op["dt_emissao"] >= pd.Timestamp("2026-03-01"))

    # prioridade de verificação
    res = [pontuar(r) for r in op.reset_index().to_dict("records")]
    op["prioridade_verificacao"] = [r.pontos for r in res]
    op["prioridade_nivel"] = [nivel(r.pontos) for r in res]
    op["motivos"] = [r.motivos for r in res]
    op["motivos_codigos"] = [r.codigos for r in res]
    op["observacoes"] = [r.observacoes for r in res]

    versao = "sicor@" + parsedate_to_datetime(fontes_sicor["operacoes"]["last_modified"]).date().isoformat()
    op["fonte_versao"] = f"{versao};ibge-ppm@{int(ppm['ano'].max())}"
    op = op.reset_index().rename(columns={"REF_BACEN": "ref_bacen"})
    op = op.drop(columns=["cd_categ_emitente", "cd_fonte_recurso"])
    for c in ["lon", "lat"]:
        op[c] = op[c].round(5)
    num = ["valor_rs", "recurso_proprio_rs", "valor_bovinos_rs", "valor_por_cabeca_rs"]
    op[num] = op[num].round(2)
    for c in ["lotacao_implicita_cab_ha", "lotacao_area_financiada_cab_ha", "lotacao_gleba_cab_ha",
              "densidade_bovina_mun_cab_ha", "razao_lotacao_densidade", "frac_rebanho_mun", "area_glebas_ha",
              "area_total_ha", "area_lotacao_ha"]:
        op[c] = op[c].astype(float).round(4)

    itens = it.rename(columns={
        "REF_BACEN": "ref_bacen", "NU_ORDEM": "nu_ordem", "CD_EMPREENDIMENTO": "cd_empreendimento",
        "FINALIDADE": "finalidade", "ATIVIDADE": "atividade", "MODALIDADE": "modalidade", "PRODUTO": "produto",
        "VARIEDADE": "variedade", "UNIDADE_MEDIDA": "unidade_medida", "VL_QUANTIDADE": "quantidade",
        "VL_PARC_CREDITO": "valor_rs", "VL_REC_PROPRIO": "recurso_proprio_rs",
        "VL_AREA_INFORMADA": "area_informada_ha", "VL_AREA_FINANC": "area_financiada_ha"})[
        ["ref_bacen", "nu_ordem", "cd_empreendimento", "finalidade", "atividade", "modalidade", "produto",
         "variedade", "unidade_medida", "fase", "compra_tipo", "tipo_item", "unidade_item", "quantidade", "valor_rs",
         "recurso_proprio_rs", "area_informada_ha", "area_financiada_ha"]]
    gl_out = glebas.drop(columns=["_geom"])

    for nome, df in [("fiscal_go_2026", op), ("itens_go_2026", itens), ("glebas_go_2026", gl_out),
                     ("rebanho_municipal_go", reb)]:
        checar_pii(df, nome)
        df.to_parquet(SAIDA / f"{nome}.parquet", index=False, compression="zstd")
        print(f"{nome}: {len(df)} linhas, {(SAIDA / f'{nome}.parquet').stat().st_size / 1e6:.1f} MB")

    resumo = montar_resumo(op, itens, reb, n_pares, fontes_sicor, int(ppm["ano"].max()))
    (SAIDA / "resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(resumo["operacoes"], ensure_ascii=False))
    print(f"total {time.perf_counter() - t0:.1f} s")
    return 0


def _q(s: pd.Series) -> dict:
    s = s.dropna()
    if s.empty:
        return {}
    qs = s.quantile([0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99])
    return {f"p{int(k * 100)}": round(float(v), 3) for k, v in qs.items()} | {"n": len(s)}


def montar_resumo(op, itens, reb, n_pares, fontes, ano_ppm) -> dict:
    pec = op["eh_pecuaria_bovina"]
    cg = op["eh_compra_gado"]
    inv = op["compra_gado_tipo"].eq("investimento")
    cus = op["compra_gado_tipo"].eq("custeio")
    lot_inv = op.loc[inv & ~op["confinamento"], "lotacao_implicita_cab_ha"].dropna()
    lot_cus = op.loc[cus & ~op["confinamento"], "lotacao_implicita_cab_ha"].dropna()
    pol = op["tem_poligono"]
    r = {
        "gerado_em": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
        "fonte_versao": op["fonte_versao"].iloc[0],
        "recorte": {"uf": "GO", "ano_emissao": ANO, "emissao_min": str(op["dt_emissao"].min().date()),
                    "emissao_max": str(op["dt_emissao"].max().date())},
        "operacoes": {
            "n": len(op), "itens": len(itens), "valor_rs": round(float(op["valor_rs"].sum()), 2),
            "com_poligono": int(pol.sum()), "glebas": int(op["n_glebas"].sum()),
            "com_municipio": int(op["municipio_ibge"].notna().sum()),
        },
        "pecuaria_bovina": {
            "n": int(pec.sum()), "pct_operacoes": round(100 * pec.mean(), 1),
            "valor_rs": round(float(op.loc[pec, "valor_rs"].sum()), 2),
            "pct_valor": round(100 * op.loc[pec, "valor_rs"].sum() / op["valor_rs"].sum(), 1),
        },
        "compra_gado": {
            "n": int(cg.sum()), "valor_rs": round(float(op.loc[cg, "valor_rs"].sum()), 2),
            "com_poligono": int((cg & pol).sum()),
            "investimento": {"n": int(inv.sum()), "valor_rs": round(float(op.loc[inv, "valor_rs"].sum()), 2),
                             "com_poligono": int((inv & pol).sum())},
            "custeio_aquisicao": {"n": int(cus.sum()), "valor_rs": round(float(op.loc[cus, "valor_rs"].sum()), 2),
                                  "com_poligono": int((cus & pol).sum())},
            "confinamento": int((cg & op["confinamento"]).sum()),
        },
        "lotacao_implicita_cab_ha": {
            "definicao": ("quantidade financiada (cabeças ou UA de 450 kg) / maior área informada entre os "
                          "itens bovinos e os demais itens da operação (VL_AREA_INFORMADA); exclui confinamento"),
            "investimento_compra": _q(lot_inv) | {
                "pct_acima_2": round(100 * (lot_inv > 2).mean(), 1),
                "pct_acima_3": round(100 * (lot_inv > 3).mean(), 1),
                "pct_acima_5": round(100 * (lot_inv > 5).mean(), 1)},
            "custeio_aquisicao": _q(lot_cus) | {
                "pct_acima_3": round(100 * (lot_cus > 3).mean(), 1),
                "pct_acima_5": round(100 * (lot_cus > 5).mean(), 1)},
        },
        "valor_por_cabeca_rs": {
            "investimento_UA": _q(op.loc[inv & op["unidade_qtd_bovinos"].eq("UA"), "valor_por_cabeca_rs"]),
            "investimento_cab": _q(op.loc[inv & op["unidade_qtd_bovinos"].eq("cab"), "valor_por_cabeca_rs"]),
        },
        "sobreposicao": {
            "pares_mesma_safra": int(n_pares),
            "ops_com_sobreposicao": int((op["n_ops_sobrepostas"] > 0).sum()),
            "ops_frac_ge_50pct": int((op["sobreposicao_max_frac"] >= 0.5).sum()),
            "ops_com_outra_if": int(op["sobrepoe_outra_if"].sum()),
            "compra_gado_com_sobreposicao": int((cg & (op["n_ops_sobrepostas"] > 0)).sum()),
        },
        "sensoriamento_remoto_obrigatorio": {
            "acima_300ha": int(op["acima_300ha"].sum()),
            "exige_sr_item5": int(op["exige_sensoriamento_remoto"].sum()),
        },
        "prioridade_verificacao": {
            "por_nivel": {k: int(v) for k, v in op["prioridade_nivel"].value_counts().items()},
            "compra_gado_por_nivel": {k: int(v) for k, v in op.loc[cg, "prioridade_nivel"].value_counts().items()},
            "por_motivo": {k: int(v) for k, v in op["motivos_codigos"].explode().value_counts().items()},
        },
        "ibge_ppm": {"ano": ano_ppm, "bovinos_go": int(reb["bovinos_cab"].sum()),
                     "municipios": len(reb)},
        "limiares": LIMIARES,
        "fontes": {k: {kk: v.get(kk) for kk in ("url", "last_modified", "bytes_transferidos", "sha256")}
                   for k, v in fontes.items() if isinstance(v, dict) and "url" in v},
    }
    return r


if __name__ == "__main__":
    raise SystemExit(main())
