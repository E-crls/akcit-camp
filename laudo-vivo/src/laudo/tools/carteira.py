"""Ferramentas de carteira sobre o bench Fiscal-GO 2026 (Sicor/BCB + glebas + IBGE PPM).

- `triar_carteira`: lista ranqueada por prioridade de verificação, com motivos legíveis.
- `carregar_operacao`: REF_BACEN -> `Operacao` (glebas WKT e itens derivados do Sicor).
- `checar_lotacao`: cabeças (ou UA) financiadas por hectare e comparação com o rebanho municipal.

Prioridade de verificação não é indício de irregularidade: orienta a amostra e o método da
fiscalização (Res. CMN 5.267/2025, MCR 2-7; item 12 admite amostragem estatística).
"""

from __future__ import annotations

import math
import time
import unicodedata
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field, model_validator

from laudo.contracts import CodigoErro, Envelope, ItemFinanciado, Operacao, registrar
from laudo.geo import bench
from laudo.geo.triagem import LIMIARES, classe_lotacao, fmt

AVISO = ("Prioridade de verificação não é indício de irregularidade: indica onde a evidência de campo "
         "ou documental tem mais valor. Limiares de triagem configuráveis (não são norma).")
REGRA_TRIAGEM = "MCR-2-7-item12"  # amostragem (Res. CMN 5.267/2025)

TIPOS = Literal["compra_gado", "compra_gado_investimento", "compra_gado_custeio", "pecuaria_bovina", "lavoura",
                "maquinas", "benfeitorias", "todos"]
FINALIDADES = {"custeio": "Custeio", "investimento": "Investimento", "comercializacao": "Comercialização",
               "industrializacao": "Industrialização"}
FINALIDADE_CONTRATO = {v: k for k, v in FINALIDADES.items()}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return " ".join(s.lower().split())


def _limpo(v: Any) -> Any:
    """Converte NaN/NaT/numpy para JSON simples."""
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, pd.Timestamp):
        return None if pd.isna(v) else v.date().isoformat()
    if hasattr(v, "tolist") and not isinstance(v, str):
        return v.tolist()
    if hasattr(v, "item"):
        return v.item()
    return v


def _resolver_municipio(municipio: str) -> tuple[str | None, str | None]:
    reb = bench.rebanho()
    m = municipio.strip()
    if m.isdigit():
        linha = reb[reb["cod_ibge"] == m]
    else:
        alvo = _norm(m.split(" - ")[0].replace("(GO)", ""))
        linha = reb[reb["municipio"].map(_norm) == alvo]
    if linha.empty:
        return None, None
    return str(linha["cod_ibge"].iloc[0]), str(linha["municipio"].iloc[0])


# ---------------------------------------------------------------------------
# triar_carteira
# ---------------------------------------------------------------------------


class EntradaTriarCarteira(BaseModel):
    municipio: str | None = Field(None, description="Município de GO (nome ou código IBGE de 7 dígitos). "
                                                    "Só operações com polígono têm município conhecido.")
    tipo_empreendimento: TIPOS = Field("compra_gado", description="Recorte do empreendimento.")
    finalidade: Literal["custeio", "investimento", "comercializacao", "industrializacao"] | None = None
    instituicao: str | None = Field(None, description="Trecho do nome da IF, ex.: 'SICOOB', 'BRASIL'.")
    so_com_poligono: bool = Field(False, description="Só operações com glebas públicas (verificação remota).")
    prioridade_minima: int = Field(1, ge=0, le=20, description="Pontuação mínima de prioridade.")
    limite: int = Field(20, ge=1, le=200)


def _filtrar_tipo(op: pd.DataFrame, tipo: str) -> pd.Series:
    mod = op["modalidades"].map(lambda xs: " | ".join(xs) if xs is not None else "")
    tipos = op["tipos_itens"].map(lambda xs: set(xs) if xs is not None else set())
    return {
        "compra_gado": op["eh_compra_gado"],
        "compra_gado_investimento": op["compra_gado_tipo"].eq("investimento"),
        "compra_gado_custeio": op["compra_gado_tipo"].eq("custeio"),
        "pecuaria_bovina": op["eh_pecuaria_bovina"],
        "lavoura": tipos.map(lambda s: "lavoura" in s),
        "maquinas": tipos.map(lambda s: "maquina" in s),
        "benfeitorias": mod.str.contains("SERVIÇOS PROFISSIONAIS|ATIVOS OPERACIONAIS", regex=True)
        & op["finalidade"].eq("Investimento"),
        "todos": pd.Series(True, index=op.index),
    }[tipo].fillna(False).astype(bool)


COLS_SAIDA = ["ref_bacen", "municipio_ibge", "municipio_nome", "instituicao", "finalidade", "modalidade", "produto",
              "variedade", "dt_emissao", "valor_rs", "qtd_bovinos", "unidade_qtd_bovinos", "area_informada_ha",
              "area_glebas_ha", "lotacao_implicita_cab_ha", "n_ops_sobrepostas", "sobreposicao_max_frac",
              "tem_poligono", "exige_sensoriamento_remoto", "prioridade_verificacao", "prioridade_nivel", "motivos",
              "observacoes"]


@registrar("triar_carteira",
           "Lista operações de crédito rural de GO (Sicor 2026) ordenadas por prioridade de verificação, com "
           "motivos legíveis (lotação implícita, sobreposição de glebas, área, valor por cabeça). Não acusa "
           "ninguém: só orienta a amostra da fiscalização.",
           EntradaTriarCarteira)
def triar_carteira(args: EntradaTriarCarteira) -> Envelope:
    t0 = time.perf_counter()
    nome = "triar_carteira"
    try:
        op = bench.operacoes()
    except bench.BenchAusente as e:
        return Envelope.falha(nome, CodigoErro.SEM_DADOS, str(e), t0=t0)
    filtros: dict[str, Any] = {"tipo_empreendimento": args.tipo_empreendimento}
    m = _filtrar_tipo(op, args.tipo_empreendimento)
    if args.municipio:
        cod, nome_mun = _resolver_municipio(args.municipio)
        if cod is None:
            return Envelope.falha(nome, CodigoErro.ENTRADA_INVALIDA,
                                  f"município '{args.municipio}' não encontrado em GO", t0=t0)
        m &= op["municipio_ibge"].eq(cod)
        filtros["municipio"] = {"cod_ibge": cod, "nome": nome_mun}
    if args.finalidade:
        m &= op["finalidade"].eq(FINALIDADES[args.finalidade])
        filtros["finalidade"] = args.finalidade
    if args.instituicao:
        m &= op["instituicao"].fillna("").map(_norm).str.contains(_norm(args.instituicao), regex=False)
        filtros["instituicao"] = args.instituicao
    if args.so_com_poligono:
        m &= op["tem_poligono"]
    m &= op["prioridade_verificacao"] >= args.prioridade_minima
    filtros["prioridade_minima"] = args.prioridade_minima
    sel = op[m].sort_values(["prioridade_verificacao", "valor_rs"], ascending=[False, False])
    linhas = []
    for pos, r in enumerate(sel.head(args.limite)[COLS_SAIDA].to_dict("records"), start=1):
        linhas.append({"posicao": pos} | {k: _limpo(v) for k, v in r.items()})
    dados = {
        "status": "ok",  # StatusChecagem: consulta respondida (prioridade não é irregularidade)
        "filtros": filtros,
        "total_filtrado": len(sel),
        "retornados": len(linhas),
        "por_nivel": {k: int(v) for k, v in sel["prioridade_nivel"].value_counts().items()},
        "operacoes": linhas,
        "aviso": AVISO,
        "regra_ref": REGRA_TRIAGEM,
        "limiares": LIMIARES,
    }
    if args.municipio:
        dados["nota_municipio"] = ("município inferido pelo polígono das glebas; operações sem polígono "
                                   "não entram no filtro por município")
    return Envelope.sucesso(nome, dados, fonte_versao=bench.versao(), t0=t0)


# ---------------------------------------------------------------------------
# carregar_operacao
# ---------------------------------------------------------------------------


class EntradaCarregarOperacao(BaseModel):
    ref_bacen: str = Field(..., pattern=r"^\d{5,12}$", description="REF_BACEN (mascarado) do Sicor.")


def _descricao_item(r: dict) -> str:
    if r["tipo_item"] == "outro" and "Cercas" in (r.get("produto") or ""):
        return ("Benfeitorias (terraços, porteiras, mata-burros, currais, cochos ou cercas; o Sicor não "
                "discrimina o tipo, confirmar no projeto)")
    partes = [r.get("modalidade"), r.get("produto")]
    var = r.get("variedade")
    desc = " — ".join(p for p in partes if p)
    if var and var != "NÃO SE APLICA":
        desc += f" ({var})"
    return desc


def itens_da_operacao(ref_bacen: str) -> list[ItemFinanciado]:
    it = bench.itens()
    sub = it[it["ref_bacen"] == ref_bacen].sort_values("nu_ordem")
    out = []
    for r in sub.to_dict("records"):
        r = {k: _limpo(v) for k, v in r.items()}
        tipo = r["tipo_item"]
        qtd = r.get("quantidade")
        unidade = r.get("unidade_item")
        if tipo in ("lavoura", "pastagem") and not qtd:
            qtd, unidade = r.get("area_financiada_ha"), "ha"
        out.append(ItemFinanciado(
            id=f"it{r['nu_ordem']}", tipo=tipo, descricao=_descricao_item(r), quantidade=qtd, unidade=unidade,
            valor_rs=r.get("valor_rs"), categoria_animal=_categoria_animal(r) if tipo == "bovinos" else None))
    return out


def _categoria_animal(r: dict) -> str | None:
    v = (r.get("variedade") or "").upper()
    if "MATRIZES" in v:
        return "matrizes (vacas e crias fêmeas)"
    if "REPRODUTORES" in v:
        return "reprodutores (touros e tourinhos)"
    if r.get("fase") and r["fase"] != "Não se aplica":
        return str(r["fase"]).lower()
    return None


def glebas_da_operacao(ref_bacen: str) -> list[str]:
    gl = bench.glebas()
    sub = gl[gl["ref_bacen"] == ref_bacen].sort_values(["nu_ordem", "nu_indice"])
    vistos, out = set(), []
    for w in sub["wkt"]:
        if w and w not in vistos and not w.endswith("EMPTY"):
            vistos.add(w)
            out.append(w)
    return out


def montar_operacao(r: dict) -> Operacao:
    emp = " · ".join(str(r[c]) for c in ("finalidade", "atividade", "modalidade", "produto") if r.get(c))
    dt = r.get("dt_emissao")
    return Operacao(
        ref_bacen=r["ref_bacen"], uf="GO", municipio_ibge=_limpo(r.get("municipio_ibge")),
        municipio_nome=_limpo(r.get("municipio_nome")), instituicao=_limpo(r.get("instituicao")),
        finalidade=FINALIDADE_CONTRATO.get(r.get("finalidade")), empreendimento=emp or None,
        data_contratacao=dt.date() if isinstance(dt, pd.Timestamp) and not pd.isna(dt) else None,
        valor_rs=_limpo(r.get("valor_rs")), area_financiada_ha=_limpo(r.get("area_financiada_ha")),
        glebas_wkt=glebas_da_operacao(r["ref_bacen"]), itens=itens_da_operacao(r["ref_bacen"]), fonte="sicor")


def _operacao_demonstracao(ref_bacen: str, t0: float) -> Envelope | None:
    """Operação FICTÍCIA de um caso de demonstração (`eval/golden/demo/*/caso.yaml` mascarado por
    `scripts/mascarar_demo.py`, ou um caso de `LAUDO_CASOS_DIR` com o bloco `demonstracao:`): não está no bench
    público; a triagem vem do caso, calculada pela mesma regra de lotação do Fiscal-GO sobre os números fictícios, e
    o aviso é o do caso (`demonstracao.aviso_do_caso`; no DEMO-0001, o `AVISO` fixo)."""
    from laudo import demonstracao

    caso = demonstracao.caso_demo_por_ref(ref_bacen)
    if caso is None:
        return None
    operacao = Operacao.model_validate(caso["operacao"])
    triagem = dict(caso.get("triagem") or {})
    triagem["fonte"] = "caso de demonstração (operação fictícia)"
    motivos = "; ".join(triagem.get("motivos") or []) or "sem sinal de triagem"
    motivo = (f"prioridade de verificação {triagem.get('prioridade_nivel')}: {motivos} (não é indício de "
              "irregularidade)")
    return Envelope.sucesso("carregar_operacao",
                            {"status": "ok", "motivo": motivo, "operacao": operacao.model_dump(mode="json"),
                             "triagem": triagem, "aviso": f"{AVISO} {demonstracao.aviso_do_caso(caso)}",
                             "demonstracao": True},
                            fonte_versao=str(triagem.get("fonte_versao") or "demo"), t0=t0)


@registrar("carregar_operacao",
           "Carrega uma operação do Sicor/BCB (GO, 2026) pelo REF_BACEN: empreendimento decodificado, valor, área, "
           "polígonos das glebas (WKT WGS84), itens financiados e o resultado da triagem.",
           EntradaCarregarOperacao)
def carregar_operacao(args: EntradaCarregarOperacao) -> Envelope:
    t0 = time.perf_counter()
    nome = "carregar_operacao"
    try:
        op = bench.operacoes()
    except bench.BenchAusente as e:
        return Envelope.falha(nome, CodigoErro.SEM_DADOS, str(e), t0=t0)
    sub = op[op["ref_bacen"] == args.ref_bacen]
    if sub.empty:
        demo = _operacao_demonstracao(args.ref_bacen, t0)
        if demo is not None:
            return demo
        return Envelope.falha(nome, CodigoErro.SEM_DADOS,
                              f"REF_BACEN {args.ref_bacen} não está no Fiscal-GO 2026 (GO, emissão em 2026)", t0=t0)
    r = sub.iloc[0].to_dict()
    operacao = montar_operacao(r)
    triagem = {k: _limpo(r.get(k)) for k in
               ["prioridade_verificacao", "prioridade_nivel", "motivos", "motivos_codigos", "observacoes",
                "lotacao_implicita_cab_ha", "area_lotacao_ha", "area_glebas_ha", "area_informada_ha",
                "n_ops_sobrepostas", "sobreposicao_max_frac", "refs_sobrepostas", "sobrepoe_outra_if",
                "exige_sensoriamento_remoto", "eh_compra_gado", "compra_gado_tipo", "qtd_bovinos",
                "unidade_qtd_bovinos", "valor_por_cabeca_rs", "rebanho_municipal_cab",
                "densidade_bovina_mun_cab_ha", "municipio_fonte", "lon", "lat", "programa", "categoria_emitente"]}
    motivos = "; ".join(triagem.get("motivos") or []) or "sem sinal de triagem"
    motivo = f"prioridade de verificação {triagem.get('prioridade_nivel')}: {motivos} (não é indício de irregularidade)"
    return Envelope.sucesso(nome, {"status": "ok", "motivo": motivo, "operacao": operacao.model_dump(mode="json"),
                                   "triagem": triagem, "aviso": AVISO}, fonte_versao=bench.versao(), t0=t0)


# ---------------------------------------------------------------------------
# checar_lotacao
# ---------------------------------------------------------------------------


class EntradaChecarLotacao(BaseModel):
    ref_bacen: str | None = Field(None, pattern=r"^\d{5,12}$",
                                  description="Se informado, usa quantidade e área do Sicor.")
    cabecas: float | None = Field(None, ge=0, description="Cabeças (ou UA) financiadas/declaradas.")
    area_ha: float | None = Field(None, ge=0, description="Área de pasto (ha) que recebe os animais.")
    municipio_ibge: str | None = Field(None, pattern=r"^52\d{5}$", description="Código IBGE (GO).")
    unidade: Literal["cab", "UA"] = "cab"
    compra: Literal["investimento", "custeio"] = Field(
        "investimento", description="investimento = matrizes/reprodutores (pasto); custeio = recria/engorda")

    @model_validator(mode="after")
    def _algum(self):
        if not self.ref_bacen and self.cabecas is None:
            raise ValueError("informe ref_bacen ou cabecas")
        return self


@registrar("checar_lotacao",
           "Calcula a lotação implícita (cabeças ou UA financiadas por hectare) e compara com a densidade e o "
           "rebanho bovino do município (IBGE PPM). Abstém-se quando não há área.",
           EntradaChecarLotacao)
def checar_lotacao(args: EntradaChecarLotacao) -> Envelope:
    t0 = time.perf_counter()
    nome = "checar_lotacao"
    cab, area, mun, unidade, compra = args.cabecas, args.area_ha, args.municipio_ibge, args.unidade, args.compra
    confinamento, area_gleba, fonte = False, None, "entrada"
    try:
        if args.ref_bacen:
            op = bench.operacoes()
            sub = op[op["ref_bacen"] == args.ref_bacen]
            from laudo import demonstracao

            caso_demo = demonstracao.caso_demo_por_ref(args.ref_bacen) if sub.empty else None
            if caso_demo is not None:  # operação fictícia da demo: quantidade, área e município do próprio caso
                op_demo = Operacao.model_validate(caso_demo["operacao"])
                bov = next((i for i in op_demo.itens if i.tipo == "bovinos"), None)
                cab = cab if cab is not None else (bov.quantidade if bov else None)
                area = area if area is not None else op_demo.area_financiada_ha
                mun = mun or op_demo.municipio_ibge
                fonte = "demonstracao"
            elif sub.empty:
                return Envelope.falha(nome, CodigoErro.SEM_DADOS, f"REF_BACEN {args.ref_bacen} fora do bench", t0=t0)
        if args.ref_bacen and fonte != "demonstracao":
            r = sub.iloc[0]
            if not bool(r["eh_pecuaria_bovina"]):
                return Envelope.falha(nome, CodigoErro.FORA_DO_ESCOPO,
                                      "operação sem item bovino: lotação não se aplica", t0=t0)
            cab = cab if cab is not None else _limpo(r["qtd_bovinos"])
            area = area if area is not None else _limpo(r["area_lotacao_ha"])
            mun = mun or _limpo(r["municipio_ibge"])
            unidade = "UA" if r["unidade_qtd_bovinos"] == "UA" else "cab"
            compra = _limpo(r["compra_gado_tipo"]) or compra
            confinamento = bool(r["confinamento"])
            area_gleba = _limpo(r["area_glebas_ha"])
            fonte = "sicor"
    except bench.BenchAusente as e:
        return Envelope.falha(nome, CodigoErro.SEM_DADOS, str(e), t0=t0)
    try:
        reb = bench.rebanho()
    except bench.BenchAusente:
        reb = None  # sem bench: calcula a lotação, mas sem comparar com o município

    base = {"cabecas": cab, "unidade": unidade, "area_ha": area, "fonte": fonte, "compra": compra,
            "status": "indeterminado"}
    if cab is None or cab <= 0:
        return Envelope.falha(nome, CodigoErro.SEM_DADOS, "sem quantidade de animais: abstenção",
                              t0=t0, data=base | {"motivo": "quantidade ausente"})
    if area is None or area <= 0:
        return Envelope.falha(nome, CodigoErro.SEM_DADOS, "sem área: lotação indeterminada (abstenção)",
                              t0=t0, data=base | {"motivo": "área ausente ou zero"})
    lot = cab / area
    pontos, rotulo = (0, None) if confinamento else classe_lotacao(lot, compra)
    dados: dict[str, Any] = base | {
        "status": "ok",  # StatusChecagem: lotação calculada (sinal de triagem, nunca divergência)
        "lotacao_cab_ha": round(lot, 4),
        "classe": "nao_aplicavel_confinamento" if confinamento else (rotulo or "dentro_dos_limiares"),
        "pontos_triagem": pontos,
        "sinal": "prioridade_verificacao" if pontos else "sem_sinal",
        "limiares": {k: v for k, v in LIMIARES.items() if k.startswith("lot_")},
    }
    if area_gleba:
        dados["lotacao_area_glebas_cab_ha"] = round(cab / area_gleba, 4)
    if mun and reb is not None:
        linha = reb[reb["cod_ibge"] == str(mun)]
        if not linha.empty:
            l0 = linha.iloc[0]
            dens = _limpo(l0["densidade_bovina_cab_ha"])
            rebanho = _limpo(l0["bovinos_cab"])
            dados["municipio"] = {
                "cod_ibge": str(mun), "nome": l0["municipio"], "rebanho_bovino_cab": rebanho,
                "ano_ppm": _limpo(l0["ano"]), "area_territorial_ha": _limpo(l0["area_ha"]),
                "densidade_bovina_cab_ha": round(dens, 4) if dens else None,
                "financiado_compra_gado_2026": _limpo(l0.get("qtd_compra_gado_2026")),
            }
            if dens:
                dados["razao_lotacao_densidade_municipal"] = round(lot / dens, 2)
            if rebanho:
                dados["fracao_rebanho_municipal"] = round(cab / rebanho, 6)
    txt = f"lotação implícita de {fmt(lot, 2)} {unidade}/ha"
    if confinamento:
        txt += " (engorda em confinamento: a comparação por área não se aplica)"
    elif rotulo:
        txt += f" ({rotulo} {unidade}/ha: prioridade de verificação, não irregularidade)"
    if "razao_lotacao_densidade_municipal" in dados:
        txt += (f"; {fmt(dados['razao_lotacao_densidade_municipal'], 1)}x a densidade bovina do município "
                f"({fmt(dados['municipio']['densidade_bovina_cab_ha'], 2)} cab/ha, IBGE PPM)")
    dados["texto"] = txt
    dados["motivo"] = txt
    dados["regra_ref"] = "MCR-2-7 (Res. CMN 5.267/2025) — triagem de plausibilidade; limiares não normativos"
    return Envelope.sucesso(nome, dados, fonte_versao=bench.versao(), t0=t0)
