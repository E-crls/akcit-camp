"""Roda o retro-teste pré-registrado da triagem (eval/retroteste/PROTOCOLO.md) e publica o relatório.

Pré-requisito (lê o Sicor em streaming e grava o recorte fora do repositório):
    scripts/py.sh -I bench/desclassificacao/build.py --trabalho <pasta>
Depois:
    scripts/py.sh -I eval/retroteste/rodar.py --dados <pasta> [--replicas 1000]

Recusa rodar se `PROTOCOLO.md` não tiver o sha256 registrado em `PROTOCOLO.sha256`. Grava
`eval/retroteste/resultado.json` e `eval/retroteste/RELATORIO.md`, qualquer que seja o resultado.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(AQUI))

import metricas as M

from laudo.geo.triagem import LIMIARES, pontuar

COORTES = (2022, 2023, 2024)
SEMENTE = 20261016
MOTIVOS_B = ("001", "013")
MIN_POSITIVOS_IF = 20
ESTRATIFICACOES = ("coorte_if", "coorte", "coorte_if_tipo")
PRIMARIA = {"escopo": "BR", "insumos": "cadastro", "rotulo": "A", "estratificacao": "coorte_if"}
LIMIAR_PALCO = 1.5
# Campos que `pontuar` lê (src/laudo/geo/triagem.py). O teste test_retroteste_metricas.py confere que
# reduzir o registro a eles não muda a pontuação do bench Fiscal-GO.
CAMPOS_CADASTRO = (
    "compra_gado_tipo",
    "unidade_qtd_bovinos",
    "lotacao_implicita_cab_ha",
    "confinamento",
    "valor_cabeca_fora_faixa",
    "valor_por_cabeca_rs",
    "faixa_valor_cabeca",
    "area_informada_ha",
)
CAMPOS_GEO = (
    "n_ops_sobrepostas",
    "sobreposicao_max_frac",
    "sobreposicao_ha",
    "sobrepoe_outra_if",
    "area_glebas_ha",
    "tem_poligono",
)


# ---------------------------------------------------------------------------
# Protocolo e software
# ---------------------------------------------------------------------------


def sha256_texto(p: Path) -> str:
    """sha256 do arquivo com fins de linha normalizados (LF), para não depender do checkout."""
    return hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def conferir_protocolo() -> dict[str, Any]:
    reg = (AQUI / "PROTOCOLO.sha256").read_text(encoding="utf-8").split()[0]
    atual = sha256_texto(AQUI / "PROTOCOLO.md")
    if atual != reg:
        raise SystemExit(f"PROTOCOLO.md mudou depois do registro ({atual[:12]} != {reg[:12]}): não rodo")
    registro = json.loads((AQUI / "registro_protocolo.json").read_text(encoding="utf-8"))
    texto = (AQUI / "PROTOCOLO.md").read_text(encoding="utf-8")
    congelados = dict(re.findall(r"\| `([^`]+\.py)`[^|]*\| `([0-9a-f]{64})` \|", texto))
    software = {}
    for arq, h in congelados.items():
        h_atual = sha256_texto(RAIZ / arq)
        software[arq] = {"registrado": h, "atual": h_atual, "igual": h_atual == h}
    return {"sha256": reg, "registrado_em": registro.get("registrado_em"), "software": software}


def carregar_bench_fiscal():
    spec = importlib.util.spec_from_file_location(
        "fiscal_go_build", RAIZ / "bench" / "fiscal_go" / "build.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Dados
# ---------------------------------------------------------------------------


def ler_operacoes(caminho: Path) -> pd.DataFrame:
    """Mesmas conversões de scripts/dados_sicor.py (texto, vazios -> None, VL_/PC_ numéricos, datas)."""
    with gzip.open(caminho, "rt", encoding="utf-8") as f:
        df = pd.read_csv(f, sep=";", dtype=str, keep_default_na=False)
    df = df.replace({"": None})
    for c in df.columns:
        if c.startswith(("VL_", "PC_")):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ("DT_EMISSAO", "DT_VENCIMENTO"):
        df[c] = pd.to_datetime(df[c], format="%d/%m/%Y", errors="coerce")
    df["NU_ORDEM"] = df["NU_ORDEM"].astype(int)
    return df


def ler_glebas(caminho: Path) -> pd.DataFrame:
    reg = []
    with gzip.open(caminho, "rt", encoding="utf-8") as f:
        next(f)
        for ln in f:
            p = ln.rstrip("\n").split(";", 3)
            reg.append((p[0], int(p[1]), int(p[2]), p[3]))
    return pd.DataFrame(reg, columns=["REF_BACEN", "NU_ORDEM", "NU_INDICE", "WKT"])


def pontuar_registros(df: pd.DataFrame, campos: tuple[str, ...]) -> tuple[np.ndarray, list[str]]:
    sub = df[[c for c in campos if c in df.columns]]
    pontos, codigos = [], []
    for r in sub.to_dict("records"):
        res = pontuar(r)
        pontos.append(res.pontos)
        codigos.append(",".join(sorted(set(res.codigos))))
    return np.asarray(pontos, dtype=np.int64), codigos


def preparar_coorte(
    B, dados: Path, ano: int, tab: dict, geo: bool
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Variáveis e pontuação da coorte nos escopos BR (cadastro) e GO (cadastro e cadastro+geo)."""
    info: dict[str, Any] = {}
    t = time.perf_counter()
    ops = ler_operacoes(dados / f"ops_compra_br_{ano}.csv.gz")
    it = B.montar_itens(ops, tab)
    del ops
    op = B.faixa_valor_cabeca(B.agregar_operacoes(it, tab))
    del it
    op = op[op["eh_compra_gado"]].copy()
    op["pontos_cadastro"], op["codigos_cadastro"] = pontuar_registros(op, CAMPOS_CADASTRO)
    br = op.reset_index()[
        [
            "REF_BACEN",
            "if_cnpj_base",
            "segmento_if",
            "compra_gado_tipo",
            "valor_rs",
            "pontos_cadastro",
            "codigos_cadastro",
        ]
    ]
    br["coorte"] = ano
    info["br_segundos"] = round(time.perf_counter() - t, 1)
    del op

    t = time.perf_counter()
    ops = ler_operacoes(dados / f"ops_go_{ano}.csv.gz")
    it = B.montar_itens(ops, tab)
    op = B.faixa_valor_cabeca(B.agregar_operacoes(it, tab))
    info["go_operacoes_carteira"] = len(op)
    pg = dados / f"glebas_go_{ano}.csv.gz"
    if geo and pg.exists():
        gl = ler_glebas(pg)
        glebas = B.montar_glebas(gl)
        g = B.geometria_operacoes(glebas)
        op = op.join(g[["n_glebas", "area_glebas_ha"]])
        op["tem_poligono"] = op["area_glebas_ha"].fillna(0) > 0
        sob, n_pares = B.calcular_sobreposicoes(op, g)
        op = op.join(sob)
        op["n_ops_sobrepostas"] = op["n_ops_sobrepostas"].fillna(0).astype(int)
        op["sobrepoe_outra_if"] = op["sobrepoe_outra_if"].fillna(False).astype(bool)
        info |= {
            "go_glebas": len(gl),
            "go_operacoes_com_poligono": int(op["tem_poligono"].sum()),
            "go_pares_sobrepostos": int(n_pares),
        }
    else:
        info["go_sem_glebas"] = True
    op = op[op["eh_compra_gado"]].copy()
    op["pontos_cadastro"], op["codigos_cadastro"] = pontuar_registros(op, CAMPOS_CADASTRO)
    if "area_glebas_ha" in op:
        op["pontos_geo"], op["codigos_geo"] = pontuar_registros(op, CAMPOS_CADASTRO + CAMPOS_GEO)
    else:
        op["pontos_geo"], op["codigos_geo"] = np.nan, None
    go = op.reset_index()[
        [
            "REF_BACEN",
            "if_cnpj_base",
            "segmento_if",
            "compra_gado_tipo",
            "valor_rs",
            "pontos_cadastro",
            "codigos_cadastro",
            "pontos_geo",
            "codigos_geo",
        ]
    ]
    go["coorte"] = ano
    info["go_segundos"] = round(time.perf_counter() - t, 1)
    return br, go, info


def rotulos(refs: pd.Series) -> tuple[np.ndarray, np.ndarray, dict]:
    d = pd.read_parquet(
        RAIZ / "bench" / "desclassificacao" / "desclassificacoes.parquet",
        columns=["ref_bacen", "cd_motivo", "na_versao_atual"],
    )
    d = d[d["na_versao_atual"].astype(bool)]
    a = set(d["ref_bacen"])
    b = set(d.loc[d["cd_motivo"].isin(MOTIVOS_B), "ref_bacen"])
    resumo = json.loads((RAIZ / "bench" / "desclassificacao" / "resumo.json").read_text(encoding="utf-8"))
    f = resumo["fontes"]["desclassificacao"]
    fonte = {k: f.get(k) for k in ("url", "last_modified", "sha256", "bytes_transferidos")}
    return refs.isin(a).to_numpy(np.float64), refs.isin(b).to_numpy(np.float64), fonte


# ---------------------------------------------------------------------------
# Análise
# ---------------------------------------------------------------------------


def _codigos(df: pd.DataFrame, cols: list[str]) -> tuple[np.ndarray, int, list]:
    cod, uniq = pd.MultiIndex.from_frame(df[cols].astype(str)).factorize()
    return cod.astype(np.int64), len(uniq), list(uniq)


def analisar(
    df: pd.DataFrame,
    escopo: str,
    insumos: list[str],
    B: int,
    rng: np.random.Generator,
    segmentos: dict[str, str],
) -> dict[str, Any]:
    """Todas as métricas de um escopo, com a mesma réplica do bootstrap para todas (comparações pareadas)."""
    n = len(df)
    yA, yB = df["rotulo_A"].to_numpy(), df["rotulo_B"].to_numpy()
    rot = {"A": yA, "B": yB}
    coorte_idx = np.searchsorted(np.array(COORTES), df["coorte"].to_numpy())
    estratos = {
        "coorte": (coorte_idx, None),
        "coorte_if": _codigos(df, ["coorte", "if_cnpj_base"]),
        "coorte_if_tipo": _codigos(df, ["coorte", "if_cnpj_base", "compra_gado_tipo"]),
    }
    est_id = {
        "coorte": coorte_idx,
        "coorte_if": estratos["coorte_if"][0],
        "coorte_if_tipo": estratos["coorte_if_tipo"][0],
    }
    # estrato -> coorte (para os números por coorte) e coorte_if -> IF
    cf = estratos["coorte_if"][2]
    mapa_coorte = {"coorte": np.arange(len(COORTES))}
    for k in ("coorte_if", "coorte_if_tipo"):
        uniq = estratos[k][2]
        mapa_coorte[k] = np.searchsorted(np.array(COORTES), np.array([int(u[0]) for u in uniq]))
    ifs = df.groupby("if_cnpj_base").size().sort_values(ascending=False)
    pos_if = df.groupby("if_cnpj_base")["rotulo_A"].sum()
    if_rotulo = {c: f"IF-{i + 1:02d}" for i, c in enumerate(ifs.index)}
    if_report = [c for c in ifs.index if pos_if[c] >= MIN_POSITIVOS_IF]
    if_idx = {c: i for i, c in enumerate(if_report)}
    mapa_if = np.array([if_idx.get(u[1], len(if_report)) for u in cf], dtype=np.int64)

    pontuacoes = {"regras_" + i: df[f"pontos_{i}"].to_numpy(np.float64) for i in insumos}
    pontuacoes["so_valor"] = df["valor_rs"].fillna(0).to_numpy(np.float64)
    ords = {(s, e): M.ordenar(est_id[e], sc) for s, sc in pontuacoes.items() for e in ESTRATIFICACOES}

    def uma(w: np.ndarray, sel: np.ndarray | None) -> dict[tuple, dict]:
        out: dict[tuple, dict] = {}
        for (s, e), o in ords.items():
            Wg = M.pesos_grupo(o, w)
            for r, y in rot.items():
                pe = M.por_estrato(o, w, y, Wg=Wg)
                out[(s, e, r, "total")] = M.agregar(pe)
                out[(s, e, r, "coorte")] = M.agregar(pe, mapa_coorte[e], len(COORTES))
                if e == "coorte_if":
                    out[(s, e, r, "if")] = M.agregar(pe, mapa_if, len(if_report) + 1)
        if sel is not None:
            for r, y in rot.items():
                out[("aleatorio", "-", r, "total")] = M.aleatorio(w, y, sel)
                out[("aleatorio", "-", r, "coorte")] = M.aleatorio(w, y, sel, coorte_idx, len(COORTES))
        return out

    t = time.perf_counter()
    ponto = uma(np.ones(n), None)
    reps: dict[tuple, dict[str, list]] = {}
    for _ in range(B):
        w = rng.poisson(1.0, n).astype(np.float64)
        sel = (rng.random(n) < M.FRACAO).astype(np.float64)
        for k, v in uma(w, sel).items():
            dst = reps.setdefault(k, {})
            for m, arr in v.items():
                dst.setdefault(m, []).append(arr)
    seg_boot = round(time.perf_counter() - t, 1)

    def resumo_chave(k: tuple, i: int) -> dict[str, Any]:
        p = ponto.get(k)
        r = {m: np.asarray(a)[:, i] for m, a in reps.get(k, {}).items()}
        out = {}
        esperado = {"lift": 1.0, "captura": M.FRACAO}  # amostra aleatória: valor esperado
        for m in ("lift", "captura", "auc", "taxa"):
            if m in r:
                val = float(p[m][i]) if p is not None and m in p else esperado.get(m)
                if val is not None and not np.isfinite(val):
                    val = None
                out[m] = {"valor": val, "ic95": M.intervalo(r[m])}
        if p is not None:
            out["n"], out["positivos"] = round(float(p["n"][i])), round(float(p["positivos"][i]))
        return out

    analises: dict[str, Any] = {}
    for s in list(pontuacoes) + ["aleatorio"]:
        for e in ESTRATIFICACOES if s != "aleatorio" else ("-",):
            for r in rot:
                k = (s, e, r, "total")
                bloco = {
                    "total": resumo_chave(k, 0),
                    "por_coorte": {
                        str(c): resumo_chave((s, e, r, "coorte"), i) for i, c in enumerate(COORTES)
                    },
                }
                if e == "coorte_if":
                    bloco["por_if"] = {}
                    for c, i in if_idx.items():
                        bloco["por_if"][if_rotulo[c]] = resumo_chave((s, e, r, "if"), i) | {
                            "segmento": segmentos.get(c)
                        }
                analises[f"{s}|{e}|{r}"] = bloco
    # diferenças pareadas regras − só valor (lift no total)
    difs = {}
    for i in insumos:
        for e in ESTRATIFICACOES:
            for r in rot:
                a = np.asarray(reps[(f"regras_{i}", e, r, "total")]["lift"])[:, 0]
                b = np.asarray(reps[("so_valor", e, r, "total")]["lift"])[:, 0]
                pa = ponto[(f"regras_{i}", e, r, "total")]["lift"][0]
                pb = ponto[("so_valor", e, r, "total")]["lift"][0]
                difs[f"regras_{i}|{e}|{r}"] = {"valor": float(pa - pb), "ic95": M.intervalo(a - b)}
    # descritivo
    desc: dict[str, Any] = {"n_operacoes": n, "por_coorte": {}, "por_tipo": {}}
    for c in COORTES:
        sub = df[df["coorte"] == c]
        desc["por_coorte"][str(c)] = {
            "n": len(sub),
            "positivos_A": int(sub["rotulo_A"].sum()),
            "positivos_B": int(sub["rotulo_B"].sum()),
            "taxa_A": _wilson(sub["rotulo_A"].sum(), len(sub)),
            "taxa_B": _wilson(sub["rotulo_B"].sum(), len(sub)),
        }
    for tp, sub in df.groupby("compra_gado_tipo"):
        desc["por_tipo"][tp] = {
            "n": len(sub),
            "positivos_A": int(sub["rotulo_A"].sum()),
            "taxa_A": _wilson(sub["rotulo_A"].sum(), len(sub)),
        }
    for i in insumos:
        col = f"pontos_{i}"
        desc[f"pontos_{i}"] = {
            "com_sinal": _wilson((df[col] > 0).sum(), n),
            "distribuicao": {str(int(k)): int(v) for k, v in df[col].value_counts().sort_index().items()},
            "taxa_A_por_pontos": {
                str(int(k)): _wilson(g["rotulo_A"].sum(), len(g)) for k, g in df.groupby(col)
            },
            "motivos": {
                k: int(v)
                for k, v in df[f"codigos_{i}"]
                .fillna("")
                .str.split(",")
                .explode()
                .replace("", np.nan)
                .dropna()
                .value_counts()
                .items()
            },
        }
    desc["ifs"] = {"n_ifs": len(ifs), "reportadas": len(if_report), "min_positivos": MIN_POSITIVOS_IF}
    return {
        "escopo": escopo,
        "descritivo": desc,
        "analises": analises,
        "diferenca_lift_regras_menos_valor": difs,
        "bootstrap_segundos": seg_boot,
    }


def _wilson(k: float, n: int) -> dict[str, Any]:
    lo, hi = M.wilson(float(k), n)
    return {"k": int(k), "n": int(n), "p": float(k) / n if n else None, "ic95": [lo, hi]}


# ---------------------------------------------------------------------------
# Relatório
# ---------------------------------------------------------------------------


def _br(x: float | None, casas: int = 2) -> str:
    if x is None:
        return "n/d"
    return f"{x:,.{casas}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def _m(b: dict, m: str, casas: int = 2, pct: bool = False) -> str:
    x = b.get(m) or {}
    v, (lo, hi) = x.get("valor"), (x.get("ic95") or [None, None])
    f = (lambda z: _br(100 * z, 1) + "%") if pct else (lambda z: _br(z, casas))
    if v is None:
        return "n/d"
    return f"{f(v)} [{f(lo) if lo is not None else 'n/d'}–{f(hi) if hi is not None else 'n/d'}]"


def relatorio(res: dict[str, Any]) -> str:
    p = res["primaria"]
    L = [
        "# Retro-teste pré-registrado da triagem: relatório",
        "",
        (
            f"*Gerado por `eval/retroteste/rodar.py` em {res['rodado_em']}. Protocolo: "
            f"`eval/retroteste/PROTOCOLO.md` (sha256 `{res['protocolo']['sha256'][:16]}…`, registrado em "
            f"{res['protocolo']['registrado_em']}). Publicado qualquer que seja o resultado.*"
        ),
        "",
        (
            "> O rótulo é **desclassificação registrada** no Sicor, que depende de a IF ter fiscalizado e "
            "registrado. Não é previsão de ilícito, e nenhuma operação é rotulada. Os números são agregados."
        ),
        "",
        "## Resultado da análise primária",
        "",
        (
            "Escopo BR, insumos de cadastro, rótulo A (qualquer motivo), coortes 2022–2024, top 10% "
            f"escolhido dentro de cada IF em cada coorte: **lift@10% = {_m(p, 'lift')}**, "
            f"captura@10% = {_m(p, 'captura', pct=True)}, AUC = {_m(p, 'auc')}; {_br(p['n'], 0)} "
            f"operações, {_br(p['positivos'], 0)} com desclassificação."
        ),
        "",
        (
            f"**Limiar de palco (IC95 inferior do lift > {_br(LIMIAR_PALCO, 1)}): "
            + ("PASSOU.**" if res["passou_limiar_palco"] else "NÃO PASSOU.**")
            + f' Linha de base "só valor" na mesma análise: lift {_m(res["primaria_so_valor"], "lift")}; '
            f"diferença pareada regras − valor: {_br(res['primaria_diferenca']['valor'])} "
            f"[{_br(res['primaria_diferenca']['ic95'][0])}–{_br(res['primaria_diferenca']['ic95'][1])}]. "
            f"Amostra aleatória: lift {_m(res['primaria_aleatorio'], 'lift')}."
        ),
        "",
        res["leitura_palco"],
        "",
    ]
    for esc in res["escopos"]:
        a = res["escopos"][esc]
        d = a["descritivo"]
        L += [
            f"## Escopo {esc}",
            "",
            "| Coorte | Operações | Rótulo A | Taxa A (por mil) | Rótulo B | Taxa B (por mil) |",
            "|---|---:|---:|---|---:|---|",
        ]
        for c, x in d["por_coorte"].items():
            ta, tb = x["taxa_A"], x["taxa_B"]
            L.append(
                f"| {c}{' (limite inferior)' if c == '2024' else ''} | {_br(x['n'], 0)} | "
                f"{_br(x['positivos_A'], 0)} | "
                f"{_br(1000 * ta['p'])} [{_br(1000 * ta['ic95'][0])}–{_br(1000 * ta['ic95'][1])}] | "
                f"{_br(x['positivos_B'], 0)} | {_br(1000 * tb['p'])} [{_br(1000 * tb['ic95'][0])}–"
                f"{_br(1000 * tb['ic95'][1])}] |"
            )
        L += [""]
        for k, v in d.items():
            if k.startswith("pontos_"):
                cs = v["com_sinal"]
                L.append(
                    f"- Insumos `{k[7:]}`: {_br(100 * cs['p'], 1)}% das operações com algum ponto; "
                    f"distribuição {v['distribuicao']}; motivos {v['motivos']}."
                )
        L += [
            "",
            "| Pontuação | Estratificação | Rótulo | Lift@10% [IC95] | Captura@10% [IC95] | AUC [IC95] |",
            "|---|---|---|---|---|---|",
        ]
        for k, b in a["analises"].items():
            s, e, r = k.split("|")
            t = b["total"]
            L.append(f"| {s} | {e} | {r} | {_m(t, 'lift')} | {_m(t, 'captura', pct=True)} | {_m(t, 'auc')} |")
        L += [
            "",
            "Por coorte (estratificação coorte×IF, rótulo A):",
            "",
            "| Pontuação | 2022 | 2023 | 2024 (limite inferior) |",
            "|---|---|---|---|",
        ]
        for s in [
            x for x in ("regras_cadastro", "regras_geo", "so_valor") if f"{x}|coorte_if|A" in a["analises"]
        ]:
            pc = a["analises"][f"{s}|coorte_if|A"]["por_coorte"]
            L.append(f"| {s} | " + " | ".join(_m(pc[str(c)], "lift") for c in COORTES) + " |")
        pc = a["analises"]["aleatorio|-|A"]["por_coorte"]
        L.append("| aleatorio | " + " | ".join(_m(pc[str(c)], "lift") for c in COORTES) + " |")
        b = a["analises"]["regras_cadastro|coorte_if|A"]
        if b.get("por_if"):
            L += [
                "",
                (
                    f"Dentro de cada IF (rótulo A, IFs com pelo menos {MIN_POSITIVOS_IF} positivos; "
                    "anonimizadas por tamanho da população):"
                ),
                "",
                "| IF | Segmento | Operações | Positivos | Lift regras | AUC regras | Lift só valor |",
                "|---|---|---:|---:|---|---|---|",
            ]
            bv = a["analises"]["so_valor|coorte_if|A"]["por_if"]
            for nome, x in b["por_if"].items():
                L.append(
                    f"| {nome} | {x.get('segmento') or 'n/d'} | {_br(x['n'], 0)} | {x['positivos']} | "
                    f"{_m(x, 'lift')} | {_m(x, 'auc')} | {_m(bv[nome], 'lift')} |"
                )
        L += [""]
    L += ["## Dados e software", ""]
    for nome, f in res["fontes"].items():
        L.append(
            f"- `{nome}`: {f.get('url')} (Last-Modified {f.get('last_modified')}; sha256 "
            f"`{str(f.get('sha256'))[:16]}…`; {_br((f.get('bytes_transferidos') or 0) / 1e6, 1)} MB)"
        )
    L += [""]
    for arq, s in res["protocolo"]["software"].items():
        L.append(
            f"- `{arq}`: {'igual ao registrado' if s['igual'] else 'DIFERENTE do registrado (desvio)'} "
            f"(`{s['atual'][:16]}…`)"
        )
    L += ["", "## Desvios", ""]
    L += [f"- {x}" for x in res["desvios"]] or ["- Nenhum."]
    L += [
        "",
        "## Como reproduzir",
        "",
        "```bash",
        "scripts/py.sh -I bench/desclassificacao/build.py --trabalho <pasta fora do repositório>",
        "scripts/py.sh -I eval/retroteste/rodar.py --dados <mesma pasta>",
        "```",
        "",
    ]
    return "\n".join(L)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--dados", type=Path, required=True, help="pasta --trabalho do bench/desclassificacao/build.py"
    )
    ap.add_argument("--replicas", type=int, default=1000)
    ap.add_argument("--saida", type=Path, default=AQUI)
    ap.add_argument("--notas", type=Path, help="arquivo de texto com registros de execução (uma linha cada)")
    a = ap.parse_args()
    t0 = time.perf_counter()
    prot = conferir_protocolo()
    desvios = [
        f"`{arq}` mudou depois do registro (registrado {s['registrado'][:12]}, atual {s['atual'][:12]})"
        for arq, s in prot["software"].items()
        if not s["igual"]
    ]
    if a.replicas != 1000:
        desvios.append(f"bootstrap com {a.replicas} réplicas em vez de 1000")
    if a.notas:
        desvios += [x.strip() for x in a.notas.read_text(encoding="utf-8").splitlines() if x.strip()]
    B = carregar_bench_fiscal()
    tab = {
        n: pd.read_parquet(a.dados / "tabelas" / f"{n}.parquet")
        for n in [
            "empreendimento",
            "categoria_emitente",
            "programa",
            "fonte_recursos",
            "lista_ifs",
            "fase_ciclo_producao",
        ]
    }
    segmentos = tab["lista_ifs"].drop_duplicates("CNPJ_IF").set_index("CNPJ_IF")["SEGMENTO_IF"].to_dict()
    fontes_trab = json.loads((a.dados / "fontes.json").read_text(encoding="utf-8"))
    brs, gos, infos = [], [], {}
    # cache da população pontuada (sem rótulo), válido só para o mesmo software congelado
    assinatura = hashlib.sha256(json.dumps({k: v["atual"] for k, v in prot["software"].items()},
                                           sort_keys=True).encode()).hexdigest()[:16]
    for ano in COORTES:
        cache = [a.dados / f"populacao_{e}_{ano}_{assinatura}.parquet" for e in ("br", "go")]
        cache_info = a.dados / f"populacao_info_{ano}_{assinatura}.json"
        if all(p.exists() for p in cache) and cache_info.exists():
            br, go = (pd.read_parquet(p) for p in cache)
            info = json.loads(cache_info.read_text(encoding="utf-8")) | {"cache": True}
        else:
            br, go, info = preparar_coorte(B, a.dados, ano, tab, geo=True)
            br.to_parquet(cache[0], index=False)
            go.to_parquet(cache[1], index=False)
            cache_info.write_text(json.dumps(info), encoding="utf-8")
        brs.append(br)
        gos.append(go)
        infos[str(ano)] = info
        print(f"coorte {ano}: BR {len(br)} operações, GO {len(go)}; {info}", flush=True)
        if info.get("go_sem_glebas"):
            desvios.append(f"glebas de GO {ano} indisponíveis: GO sem as regras geométricas nessa coorte")
    br, go = pd.concat(brs, ignore_index=True), pd.concat(gos, ignore_index=True)
    del brs, gos
    for df in (br, go):
        df["rotulo_A"], df["rotulo_B"], fonte_rotulo = rotulos(df["REF_BACEN"])
    rng = np.random.default_rng(SEMENTE)
    escopos = {}
    escopos["BR"] = analisar(br, "BR", ["cadastro"], a.replicas, rng, segmentos)
    print(f"BR analisado ({escopos['BR']['bootstrap_segundos']} s de bootstrap)", flush=True)
    insumos_go = ["cadastro"] + (["geo"] if go["pontos_geo"].notna().all() else [])
    escopos["GO"] = analisar(go, "GO", insumos_go, a.replicas, rng, segmentos)
    k = f"regras_{PRIMARIA['insumos']}|{PRIMARIA['estratificacao']}|{PRIMARIA['rotulo']}"
    prim = escopos["BR"]["analises"][k]["total"]
    lo = prim["lift"]["ic95"][0]
    passou = bool(lo is not None and lo > LIMIAR_PALCO)
    valor = escopos["BR"]["analises"]["so_valor|coorte_if|A"]["total"]
    leitura = (
        (
            "Passou no limiar pré-registrado: o resultado pode ir ao palco com os marcadores `retro.*` de "
            "numeros.md"
            + (
                ', sem atribuir o ganho às regras, porque a linha de base "só valor" tem lift igual ou maior.'
                if valor["lift"]["valor"] >= prim["lift"]["valor"]
                else "."
            )
        )
        if passou
        else (
            "Não passou no limiar pré-registrado: nada do retro-teste vai ao palco. No Q&A: "
            '"fizemos um retro-teste pré-registrado; não passou no limiar que fixamos; o relatório está '
            'publicado".'
        )
    )
    fontes = {
        k: v
        for k, v in fontes_trab.items()
        if k.startswith(("operacoes_202", "glebas_")) and k.split("_")[-1] in {str(c) for c in COORTES}
    }
    fontes["desclassificacao"] = fonte_rotulo
    res = {
        "gerado_por": "eval/retroteste/rodar.py",
        "rodado_em": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
        "protocolo": prot,
        "parametros": {
            "replicas": a.replicas,
            "semente": SEMENTE,
            "fracao": M.FRACAO,
            "limiar_palco": LIMIAR_PALCO,
            "primaria": PRIMARIA,
            "motivos_rotulo_B": list(MOTIVOS_B),
            "limiares_triagem": LIMIARES,
        },
        "preparo": infos,
        "fontes": fontes,
        "primaria": prim,
        "primaria_so_valor": valor,
        "primaria_aleatorio": escopos["BR"]["analises"]["aleatorio|-|A"]["total"],
        "primaria_diferenca": escopos["BR"]["diferenca_lift_regras_menos_valor"][
            "regras_cadastro|coorte_if|A"
        ],
        "passou_limiar_palco": passou,
        "leitura_palco": leitura,
        "desvios": desvios,
        "escopos": escopos,
        "segundos": round(time.perf_counter() - t0, 1),
    }
    a.saida.mkdir(parents=True, exist_ok=True)
    (a.saida / "resultado.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    (a.saida / "RELATORIO.md").write_text(relatorio(res), encoding="utf-8")
    print(f"primária: lift {prim['lift']} -> passou={passou}; {res['segundos']} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
