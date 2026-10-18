"""Números do Observatório de desclassificações, calculados sem rede a partir das tabelas derivadas.

`calcular(desc, base, emp, motivos)` recebe `desclassificacoes.parquet`, `base_operacoes.parquet` e
`empreendimento.parquet` (gerados por `build.py`) e devolve o bloco de números do `resumo.json`. Cada
versão do arquivo de desclassificações (`atual`, de 14/10/2026, e, se houver snapshot, `memorando_0710`, a
de 07/10/2026) tem os mesmos números, para que as duas versões sejam reproduzíveis e a atualização do BCB
fique visível.

Definições (também no README):
- registro: uma linha de `sicor_desclassificacao.gz` (operação × item × data × motivo);
- ano da desclassificação: ano de `DT_DESC`; ano da operação: o arquivo anual em que a operação está;
- categoria: finalidade|atividade|modalidade do empreendimento do 1º item da operação (como o agg.awk);
- taxa por coorte: operações da coorte com pelo menos um registro / operações da coorte (proporção com IC de
  Wilson); "registros por mil operações" é a conta alternativa (não é proporção: uma operação pode ter
  vários registros).
"""

from __future__ import annotations

import math
import re
from typing import Any

import pandas as pd

CUSTEIO_AQUISICAO = "Custeio|Pecuário(a)|AQUISIÇÃO E MANUTENÇÃO DE ANIMAIS"
INVESTIMENTO_AQUISICAO = "Investimento|Pecuário(a)|AQUISIÇÃO DE ANIMAIS"
MODALIDADES_AQUISICAO = ("AQUISIÇÃO DE ANIMAIS", "AQUISIÇÃO E MANUTENÇÃO DE ANIMAIS")
COORTES = (2022, 2023, 2024)
JANELA = (2024, 2025, 2026)  # anos de desclassificação do recorte GO × país


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float | None, float | None]:
    if n <= 0:
        return None, None
    p = k / n
    den = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / den
    meia = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centro - meia), min(1.0, centro + meia)


def proporcao(k: int, n: int) -> dict[str, Any]:
    lo, hi = wilson(k, n)
    return {"k": int(k), "n": int(n), "p": (k / n) if n else None, "ic95": [lo, hi]}


def razao_katz(k1: int, n1: int, k2: int, n2: int) -> dict[str, Any]:
    """Razão de taxas p1/p2 com IC95 de Katz (log), para grupos disjuntos."""
    if not (k1 and k2 and n1 and n2):
        return {"razao": None, "ic95": [None, None]}
    r = (k1 / n1) / (k2 / n2)
    ep = math.sqrt(1 / k1 - 1 / n1 + 1 / k2 - 1 / n2)
    return {"razao": r, "ic95": [r * math.exp(-1.959964 * ep), r * math.exp(1.959964 * ep)]}


def checar_pii(df: pd.DataFrame, nome: str) -> None:
    """Recusa coluna com nome de documento pessoal ou valor com formato de CPF/CNPJ completo."""
    proibidas = re.compile(
        r"CPF|CNPJ_CPF|MUTUARIO|NOME_TOMADOR|AGENCIA|CEDULA|SNCR|NIRF|CD_CAR", re.IGNORECASE
    )
    ruins = [c for c in df.columns if proibidas.search(c)]
    assert not ruins, f"{nome}: colunas com possível PII: {ruins}"
    doc = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b|\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
    for c in df.columns:
        if c.startswith("cd_") or c in ("ref_bacen", "categoria"):
            continue
        if df[c].dtype == object:
            s = df[c].dropna().astype(str)
            achou = s[s.str.contains(doc)]
            assert achou.empty, f"{nome}.{c}: valor com formato de CPF/CNPJ completo"


def _emp(emp: pd.DataFrame) -> pd.DataFrame:
    e = emp.drop_duplicates("CODIGO").set_index("CODIGO")
    e["categoria"] = (
        e["FINALIDADE"].fillna("") + "|" + e["ATIVIDADE"].fillna("") + "|" + e["MODALIDADE"].fillna("")
    )
    return e[["categoria", "FINALIDADE", "ATIVIDADE", "MODALIDADE", "PRODUTO"]]


def _base_cat(base: pd.DataFrame, emp: pd.DataFrame) -> pd.DataFrame:
    e = _emp(emp)
    b = base.join(e, on="cd_empreendimento")
    b["categoria"] = b["categoria"].fillna("?" + b["cd_empreendimento"].astype(str))
    return b


def _grupos(
    df: pd.DataFrame,
    cat: str = "categoria",
    ativ: str = "atividade",
    mod: str = "modalidade",
    fin: str = "finalidade",
) -> dict[str, pd.Series]:
    return {
        "pecuaria": df[ativ].eq("Pecuário(a)"),
        "aquisicao_animais": df[mod].isin(MODALIDADES_AQUISICAO) & df[ativ].eq("Pecuário(a)"),
        "custeio_aquisicao": df[cat].eq(CUSTEIO_AQUISICAO),
        "investimento_aquisicao": df[cat].eq(INVESTIMENTO_AQUISICAO),
    }


def _taxas(d: pd.DataFrame, b: pd.DataFrame, uf: str | None) -> dict[str, Any]:
    """Taxa de desclassificação por coorte (2022–2024) por categoria, contra a média e contra o resto."""
    if uf:
        d, b = d[d["uf"] == uf], b[b["uf"] == uf]
    ops_desc = d.drop_duplicates("ref_bacen")
    out: dict[str, Any] = {}
    for rotulo, anos in [(str(y), (y,)) for y in COORTES] + [("2022_2024", COORTES)]:
        dd = ops_desc[ops_desc["ano_operacao"].isin(anos)]
        rr = d[d["ano_operacao"].isin(anos)]
        bb = b[b["ano_operacao"].isin(anos)]
        n_tot, k_tot, r_tot = int(bb["n_operacoes"].sum()), len(dd), len(rr)
        bloco = {
            "media": proporcao(k_tot, n_tot)
            | {"registros": r_tot, "registros_por_mil": 1000 * r_tot / n_tot if n_tot else None}
        }
        for nome, cat in (
            ("custeio_aquisicao", CUSTEIO_AQUISICAO),
            ("investimento_aquisicao", INVESTIMENTO_AQUISICAO),
        ):
            n = int(bb.loc[bb["categoria"] == cat, "n_operacoes"].sum())
            k = int((dd["categoria"] == cat).sum())
            r = int((rr["categoria"] == cat).sum())
            p = proporcao(k, n)
            bloco[nome] = p | {
                "registros": r,
                "registros_por_mil": 1000 * r / n if n else None,
                "razao_media": (p["p"] / bloco["media"]["p"])
                if p["p"] is not None and bloco["media"]["p"]
                else None,
                "razao_demais": razao_katz(k, n, k_tot - k, n_tot - n),
            }
        out[rotulo] = bloco
    return out


def _participacao(d: pd.DataFrame, b: pd.DataFrame, uf: str | None) -> dict[str, Any]:
    """Participação de pecuária e de aquisição de animais nas operações e nas desclassificações."""
    if uf:
        d, b = d[d["uf"] == uf], b[b["uf"] == uf]
    bb = b[b["ano_operacao"].isin(COORTES)]
    bb = bb.assign(atividade=bb["ATIVIDADE"], modalidade=bb["MODALIDADE"], finalidade=bb["FINALIDADE"])
    reg_janela = d[d["ano_desc"].isin(JANELA)]
    ops_coorte = d[d["ano_operacao"].isin(COORTES)].drop_duplicates("ref_bacen")
    n_ops = bb["n_operacoes"].sum()
    gb, gr, go = _grupos(bb), _grupos(reg_janela), _grupos(ops_coorte)
    out = {}
    for g in gb:
        k_ops = int(bb.loc[gb[g], "n_operacoes"].sum())
        out[g] = {
            "pct_operacoes_2022_2024": proporcao(k_ops, int(n_ops)),
            "pct_registros_desc_2024_2026": proporcao(int(gr[g].sum()), len(reg_janela)),
            "pct_operacoes_desclassificadas_coortes_2022_2024": proporcao(int(go[g].sum()), len(ops_coorte)),
        }
    return out


def _quebra_serie(d: pd.DataFrame, motivos: dict[str, str]) -> dict[str, Any]:
    por_ano = d.groupby("ano_desc").size()
    m999 = d[d["cd_motivo"] == "999"].groupby("ano_desc").size().reindex(por_ano.index, fill_value=0)
    sem_desc = d[~d["cd_motivo"].isin(list(motivos))]
    defas = (d["ano_desc"] - d["ano_operacao"]).groupby(d["ano_desc"]).median()
    anos_013 = sorted(d.loc[d["cd_motivo"] == "013", "ano_desc"].unique().tolist())
    pct999 = {int(k): round(100 * m999[k] / por_ano[k], 1) for k in por_ano.index}

    def qtd(a: int) -> str:
        return f"{int(por_ano.get(a, 0)):,}".replace(",", ".")

    def pct(a: int) -> str:
        return f"{pct999.get(a, 0):.0f}%"

    return {
        "registros_por_ano": {int(k): int(v) for k, v in por_ano.items()},
        "pct_motivo_999_outro": pct999,
        "primeiro_ano_motivo_013": int(anos_013[0]) if anos_013 else None,
        "codigos_sem_descricao": {
            c: {int(a): int(n) for a, n in g.groupby("ano_desc").size().items()}
            for c, g in sem_desc.groupby("cd_motivo")
        },
        "mediana_anos_entre_operacao_e_desclassificacao": {int(k): float(v) for k, v in defas.items()},
        "leitura": (
            f"o registro anual cai de {qtd(2021)} (2021) para {qtd(2022)} (2022) e salta para "
            f"{qtd(2023)} (2023) e {qtd(2024)} (2024); o motivo 013 só aparece a partir de "
            f"{anos_013[0] if anos_013 else 'n/d'}, e o 999 ('Outro') passa de {pct(2024)} dos registros "
            f"(2024) para {pct(2025)} (2025) e {pct(2026)} (2026): parte do crescimento é efeito de "
            "registro, não de comportamento. Por isso só se compara 2026 parcial com 2025 inteiro, sem "
            "multiplicadores."
        ),
    }


def _bloco(d: pd.DataFrame, b: pd.DataFrame, motivos: dict[str, str]) -> dict[str, Any]:
    por_ano = d.groupby("ano_desc").size()
    m013 = d[d["cd_motivo"] == "013"].groupby("ano_desc").size()
    dmax = d["dt_desc"].max()
    jan = d[d["ano_desc"].isin(JANELA)]
    go = jan[jan["uf"] == "GO"]
    cus_go = go[go["categoria"] == CUSTEIO_AQUISICAO]
    return {
        "registros": {
            "total": len(d),
            "operacoes": int(d["ref_bacen"].nunique()),
            "data_min": str(d["dt_desc"].min().date()),
            "data_max": str(dmax.date()),
            "por_ano": {int(k): int(v) for k, v in por_ano.items()},
            "por_tipo": {k: int(v) for k, v in d.groupby("tipo_desc").size().items()},
            "sem_operacao_encontrada": int(d["uf"].isna().sum()),
        },
        "comparacao_2026_2025": {
            "n_2025": int(por_ano.get(2025, 0)),
            "n_2026": int(por_ano.get(2026, 0)),
            "data_max_2026": str(dmax.date()),
            "motivo013_2025": int(m013.get(2025, 0)),
            "motivo013_2026": int(m013.get(2026, 0)),
            "2026_parcial_supera_2025": bool(por_ano.get(2026, 0) > por_ano.get(2025, 0)),
        },
        "motivo_por_ano": {
            int(a): {m: int(n) for m, n in g.groupby("cd_motivo").size().items()}
            for a, g in d.groupby("ano_desc")
        },
        "janela_2024_2026": {
            "br": {
                "registros": len(jan),
                "motivo013": proporcao(int((jan["cd_motivo"] == "013").sum()), len(jan)),
            },
            "go": {
                "registros": len(go),
                "motivo013": proporcao(int((go["cd_motivo"] == "013").sum()), len(go)),
                "custeio_aquisicao": {
                    "registros": len(cus_go),
                    "valor_desclassificado_rs": round(float(cus_go["vl_desc"].sum()), 2),
                },
            },
        },
        "taxas_por_coorte": {"br": _taxas(d, b, None), "go": _taxas(d, b, "GO")},
        "participacao": {"br": _participacao(d, b, None), "go": _participacao(d, b, "GO")},
        "quebra_de_serie": _quebra_serie(d, motivos),
    }


def calcular(
    desc: pd.DataFrame, base: pd.DataFrame, emp: pd.DataFrame, motivos: dict[str, str]
) -> dict[str, Any]:
    b = _base_cat(base, emp)
    desc = desc.copy()
    desc["dt_desc"] = pd.to_datetime(desc["dt_desc"])
    versoes = {"atual": desc[desc["na_versao_atual"].astype(bool)]}
    snap = desc.get("no_snapshot_memorando")
    if snap is not None and snap.notna().any():
        versoes["memorando_0710"] = desc[snap.fillna(False).astype(bool)]
    out: dict[str, Any] = {
        "motivos": motivos,
        "versoes": {k: _bloco(v, b, motivos) for k, v in versoes.items()},
    }
    if "memorando_0710" in versoes:
        novos = desc[desc["na_versao_atual"].astype(bool) & ~snap.fillna(False).astype(bool)]
        sairam = desc[~desc["na_versao_atual"].astype(bool)]
        out["delta_versoes"] = {
            "registros_novos": len(novos),
            "registros_removidos": len(sairam),
            "novos_por_ano_desc": {int(k): int(v) for k, v in novos.groupby("ano_desc").size().items()},
            "novos_por_motivo": {k: int(v) for k, v in novos.groupby("cd_motivo").size().items()},
            "removidos_por_ano_desc": {int(k): int(v) for k, v in sairam.groupby("ano_desc").size().items()},
            "novos_data_max": str(novos["dt_desc"].max().date()) if len(novos) else None,
        }
    return out
