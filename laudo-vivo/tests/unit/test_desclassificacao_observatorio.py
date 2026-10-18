"""Observatório de desclassificações (bench/desclassificacao): porte dos .awk e números do memorando."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

RAIZ = Path(__file__).resolve().parents[2]
DIR = RAIZ / "bench" / "desclassificacao"
sys.path.insert(0, str(DIR))

import numeros as N
import observatorio as O

CAB = (
    "#REF_BACEN;NU_ORDEM;CNPJ_IF;DT_EMISSAO;DT_VENCIMENTO;CD_INST_CREDITO;CD_CATEG_EMITENTE;CD_FONTE_RECURSO;"
    "CNPJ_AGENTE_INVEST;CD_ESTADO;CD_REF_BACEN_INVESTIMENTO;CD_TIPO_SEGURO;CD_EMPREENDIMENTO;CD_PROGRAMA;"
    "CD_TIPO_ENCARG_FINANC;CD_TIPO_IRRIGACAO;CD_TIPO_AGRICULTURA;CD_FASE_CICLO_PRODUCAO;CD_TIPO_CULTIVO;"
    "CD_TIPO_INTGR_CONSOR;CD_TIPO_GRAO_SEMENTE;VL_ALIQ_PROAGRO;VL_JUROS;VL_PRESTACAO_INVESTIMENTO;VL_PREV_PROD;"
    "VL_QUANTIDADE;VL_RECEITA_BRUTA_ESPERADA;VL_PARC_CREDITO;VL_REC_PROPRIO;VL_PERC_RISCO_STN;"
    "VL_PERC_RISCO_FUNDO_CONST;VL_REC_PROPRIO_SRV;VL_AREA_FINANC;CD_SUBPROGRAMA;VL_PRODUTIV_OBTIDA;"
    "DT_FIM_COLHEITA;DT_FIM_PLANTIO;DT_INIC_COLHEITA;DT_INIC_PLANTIO;VL_JUROS_ENC_FINAN_POSFIX;"
    "VL_PERC_CUSTO_EFET_TOTAL;CD_CONTRATO_STN;CD_CNPJ_CADASTRANTE;VL_AREA_INFORMADA;CD_CICLO_CULTIVAR;"
    "CD_TIPO_SOLO;PC_BONUS_CAR"
)
COLS = [c.lstrip("#") for c in CAB.split(";")]

EMP = {
    "COMPRA_INV": O.Empreendimento(
        "Investimento", "Pecuário(a)", "AQUISIÇÃO DE ANIMAIS", "BOVINOS", "Unidade"
    ),
    "CUST_AQ": O.Empreendimento(
        "Custeio", "Pecuário(a)", "AQUISIÇÃO E MANUTENÇÃO DE ANIMAIS", "BOVINOS", "Unidade Animal (450kg)"
    ),
    "SOJA": O.Empreendimento("Custeio", "Agrícola", "LAVOURA", "SOJA", "Hectare"),
    "OVINOS": O.Empreendimento("Investimento", "Pecuário(a)", "AQUISIÇÃO DE ANIMAIS", "OVINOS", "Unidade"),
}


def linha(
    ref,
    ordem,
    emp,
    uf="GO",
    valor="1000.00",
    area_inf="10.00",
    area_fin="10.00",
    ifc="00000000",
    cad="",
    produtiv="99.9",
):
    v = dict.fromkeys(COLS, "")
    v |= {
        "REF_BACEN": ref,
        "NU_ORDEM": str(ordem),
        "CNPJ_IF": ifc,
        "DT_EMISSAO": "05/03/2024",
        "CD_ESTADO": uf,
        "CD_EMPREENDIMENTO": emp,
        "VL_PARC_CREDITO": valor,
        "VL_AREA_INFORMADA": area_inf,
        "VL_AREA_FINANC": area_fin,
        "CD_CNPJ_CADASTRANTE": cad,
        "VL_PRODUTIV_OBTIDA": produtiv,
        "DT_INIC_COLHEITA": "01/01/2025",
        "VL_QUANTIDADE": "20",
    }
    return ";".join(v[c] for c in COLS)


def test_le_desclassificacoes_com_mes_antes_do_dia():
    regs = list(
        O.ler_desclassificacoes(
            [
                "#REF_BACEN;NU_ORDEM;DT_DESC;CD_MOTIVO_DESC;VL_DESC;TIPO_DESC",
                "9000001;1;02/19/2018 00:00:00;999;277500.00;PARCIAL",
                "9000002;2;10/06/2026 00:00:00;13;10.5;TOTAL",
                "",
            ]
        )
    )
    assert [r.dt_desc for r in regs] == [date(2018, 2, 19), date(2026, 10, 6)]
    assert [r.cd_motivo for r in regs] == ["999", "013"]
    assert regs[1].chave == ("9000002", 2, "2026-10-06", "013", 1050, "TOTAL")


def test_motivos_e_empreendimentos():
    m = O.ler_motivos(["#CODIGO,DESCRICAO", '"013","Aplicação não comprovada de recursos"', '"999","Outro"'])
    assert m == {"013": "Aplicação não comprovada de recursos", "999": "Outro"}
    e = O.ler_empreendimentos(
        [
            ("#CODIGO;DATA_INICIO;DATA_FIM;FINALIDADE;ATIVIDADE;MODALIDADE;PRODUTO;VARIEDADE;"
             "CESTA;ZONEAMENTO;UNIDADE_MEDIDA"),
            ('"1";"01/01/2020";;"Custeio";"Pecuário(a)";"AQUISIÇÃO E MANUTENÇÃO DE ANIMAIS";'
             '"BOVINOS";"X";;;"Unidade"'),
            '"1";"01/01/2021";;"Custeio";"Agrícola";"LAVOURA";"SOJA";"X";;;"Hectare"',
        ]
    )
    assert e["1"].categoria == "Custeio|Pecuário(a)|AQUISIÇÃO E MANUTENÇÃO DE ANIMAIS"  # vale o primeiro
    assert O.eh_compra_gado(e["1"]) and not O.eh_compra_gado(EMP["OVINOS"]) and not O.eh_compra_gado(None)


@pytest.mark.parametrize(
    "ifc,cad,esperado",
    [
        ("00000000", "02038232", "BB"),
        ("12345678", "02038232", "SICOOB"),
        ("02038232", "", "SICOOB"),
        ("12345678", "01181521", "SICREDI"),
        ("12345678", "01401771", "CRESOL"),
        ("01401771", "", "OUTRO"),
        ("07237373", "", "BNB"),
        ("04902979", "", "BASA"),
        ("00360305", "", "CAIXA"),
        ("60746948", "", "BRADESCO"),
        ("11111111", "", "OUTRO"),
    ],
)
def test_sistema_como_no_agg_awk(ifc, cad, esperado):
    assert O.sistema(ifc, cad) == esperado


def test_leitor_base_juncao_area_e_recorte_do_retroteste():
    linhas = [
        CAB,
        linha("100", 1, "SOJA", uf="MT", valor="500"),
        linha("100", 2, "COMPRA_INV", uf="MT", valor="300", area_inf="400"),  # op com compra (2º item)
        linha("101", 1, "SOJA", uf="GO", valor="50"),  # GO sem compra
        linha("102", 1, "CUST_AQ", uf="SP", valor="70", area_inf="0", area_fin="0"),
        linha("103", 1, "OVINOS", uf="SP", valor="10"),
    ]
    lt = O.LeitorOperacoes(ano=2024, refs={"102", "100"}, empreendimentos=EMP, extrair_retro=True)
    lt.consumir(iter(linhas))
    assert lt.operacoes == 4 and lt.linhas == 5 and lt.fora_de_ordem == 0
    # base.awk: a operação conta no empreendimento do 1º item; itens e valor, no de cada item
    assert lt.base[("MT", "SOJA")] == [1, 1, 500.0]
    assert lt.base[("MT", "COMPRA_INV")] == [0, 1, 300.0]
    # join.awk: atributos do 1º item, valor somado
    assert lt.juncao["100"]["cd_empreendimento"] == "SOJA" and lt.juncao["100"]["valor_rs"] == 800.0
    assert set(lt.juncao) == {"100", "102"}
    # area.awk: maior entre área financiada e informada
    assert lt.area[("BR", "acima_300")] == 1 and lt.area[("BR", "0")] == 1 and lt.area[("BR", "ate_300")] == 1
    # retro-teste: todos os itens da operação com compra; GO inteiro; só colunas de originação
    refs_compra = [x.split(";")[0] for x in lt.retro_compra]
    assert refs_compra == ["100", "100", "102"]
    assert [x.split(";")[0] for x in lt.retro_go] == ["101"]
    assert all(len(x.split(";")) == len(O.CAMPOS_ORIGINACAO) for x in lt.retro_compra)
    assert "99.9" not in ";".join(lt.retro_compra) and "01/01/2025" not in ";".join(lt.retro_compra)


def test_leitor_conta_arquivo_fora_de_ordem():
    lt = O.LeitorOperacoes(ano=2024, refs=set(), empreendimentos=EMP)
    lt.consumir(iter([CAB, linha("200", 1, "SOJA"), linha("150", 1, "SOJA")]))
    assert lt.fora_de_ordem == 1


def test_lista_fechada_exclui_informacao_posterior():
    assert not set(O.CAMPOS_ORIGINACAO) & set(O.CAMPOS_EXCLUIDOS)
    for c in ("VL_PRODUTIV_OBTIDA", "DT_INIC_COLHEITA", "DT_FIM_COLHEITA"):
        assert c in O.CAMPOS_EXCLUIDOS and c not in O.CAMPOS_ORIGINACAO
    assert set(O.CAMPOS_ORIGINACAO) <= set(COLS)


def test_filtrar_glebas():
    gl, lidas = O.filtrar_glebas(
        iter(
            [
                "#REF_BACEN;NU_ORDEM;NU_INDICE;GT_GEOMETRIA",
                "1;1;0;POLYGON ((0 0,1 0,1 1,0 0))",
                "2;1;0;POLYGON ((0 0,1 0,1 1,0 0))",
            ]
        ),
        {"2"},
    )
    assert lidas == 2 and gl == ["2;1;0;POLYGON ((0 0,1 0,1 1,0 0))"]
    with pytest.raises(ValueError):
        O.filtrar_glebas(iter(["#A;B;C;D"]), set())


def test_wilson_e_razao():
    lo, hi = N.wilson(0, 10)
    assert lo == 0 and 0.27 < hi < 0.29
    r = N.razao_katz(50, 1000, 10, 1000)
    assert r["razao"] == pytest.approx(5.0) and r["ic95"][0] < 5 < r["ic95"][1]


def test_calcular_sintetico():
    desc = pd.DataFrame(
        [
            {
                "ref_bacen": "1",
                "nu_ordem": 1,
                "dt_desc": date(2025, 5, 1),
                "ano_desc": 2025,
                "cd_motivo": "013",
                "vl_desc": 10.0,
                "tipo_desc": "TOTAL",
                "ano_operacao": 2023,
                "uf": "GO",
                "cd_empreendimento": "CUST_AQ",
                "categoria": EMP["CUST_AQ"].categoria,
                "finalidade": "Custeio",
                "atividade": "Pecuário(a)",
                "modalidade": "AQUISIÇÃO E MANUTENÇÃO DE ANIMAIS",
                "na_versao_atual": True,
                "no_snapshot_memorando": True,
            },
            {
                "ref_bacen": "1",
                "nu_ordem": 1,
                "dt_desc": date(2026, 2, 1),
                "ano_desc": 2026,
                "cd_motivo": "014",
                "vl_desc": 5.0,
                "tipo_desc": "PARCIAL",
                "ano_operacao": 2023,
                "uf": "GO",
                "cd_empreendimento": "CUST_AQ",
                "categoria": EMP["CUST_AQ"].categoria,
                "finalidade": "Custeio",
                "atividade": "Pecuário(a)",
                "modalidade": "AQUISIÇÃO E MANUTENÇÃO DE ANIMAIS",
                "na_versao_atual": True,
                "no_snapshot_memorando": False,
            },
        ]
    )
    base = pd.DataFrame(
        [(2023, "GO", "CUST_AQ", 100, 100, 1e6), (2023, "SP", "SOJA", 900, 900, 1e7)],
        columns=["ano_operacao", "uf", "cd_empreendimento", "n_operacoes", "n_itens", "valor_itens_rs"],
    )
    emp = pd.DataFrame(
        [
            {
                "CODIGO": k,
                "FINALIDADE": e.finalidade,
                "ATIVIDADE": e.atividade,
                "MODALIDADE": e.modalidade,
                "PRODUTO": e.produto,
            }
            for k, e in EMP.items()
        ]
    )
    r = N.calcular(desc, base, emp, {"013": "Aplicação não comprovada de recursos"})
    at, me = r["versoes"]["atual"], r["versoes"]["memorando_0710"]
    assert at["registros"]["total"] == 2 and me["registros"]["total"] == 1
    assert at["comparacao_2026_2025"]["n_2026"] == 1 and me["comparacao_2026_2025"]["n_2026"] == 0
    t = at["taxas_por_coorte"]["br"]["2023"]
    assert t["custeio_aquisicao"]["k"] == 1 and t["custeio_aquisicao"]["n"] == 100
    assert t["custeio_aquisicao"]["registros_por_mil"] == pytest.approx(20.0)
    assert t["media"]["k"] == 1 and t["media"]["n"] == 1000
    assert at["quebra_de_serie"]["codigos_sem_descricao"] == {"014": {2026: 1}}
    assert r["delta_versoes"]["registros_novos"] == 1


@pytest.fixture(scope="module")
def publicado():
    p = DIR / "resumo.json"
    if not p.exists():
        pytest.skip("bench/desclassificacao ainda não gerado")
    return json.loads(p.read_text(encoding="utf-8"))


def test_reproduz_os_numeros_do_memorando(publicado):
    """Memorando de 16/10/2026, seção 3, linhas 3 e 4 (versão de 07/10/2026 do arquivo do BCB)."""
    m = publicado["versoes"]["memorando_0710"]
    assert m["registros"]["total"] == 15902
    c = m["comparacao_2026_2025"]
    assert (c["n_2025"], c["n_2026"], c["motivo013_2025"], c["motivo013_2026"]) == (4072, 4553, 349, 364)
    assert c["data_max_2026"] == "2026-10-06"
    go = m["janela_2024_2026"]["go"]
    assert (go["motivo013"]["k"], go["registros"]) == (82, 564)
    assert round(100 * go["motivo013"]["p"], 1) == 14.5
    assert round(100 * m["janela_2024_2026"]["br"]["motivo013"]["p"], 1) == 7.8
    assert go["custeio_aquisicao"]["registros"] == 158
    assert round(go["custeio_aquisicao"]["valor_desclassificado_rs"] / 1e6, 1) == 169.5
    # "4,4 a 6,9 por mil" e "0,6 a 0,8 por mil" (registros por mil operações, 2022–2024)
    tx = m["taxas_por_coorte"]["br"]
    cus = [round(tx[str(a)]["custeio_aquisicao"]["registros_por_mil"], 1) for a in (2022, 2023, 2024)]
    inv = [round(tx[str(a)]["investimento_aquisicao"]["registros_por_mil"], 1) for a in (2022, 2023, 2024)]
    assert min(cus) == 4.4 and max(cus) == 6.9
    assert min(inv) == 0.6 and max(inv) == 0.8


def test_resumo_bate_com_as_tabelas_publicadas(publicado):
    desc = pd.read_parquet(DIR / "desclassificacoes.parquet")
    base = pd.read_parquet(DIR / "base_operacoes.parquet")
    emp = pd.read_parquet(DIR / "empreendimento.parquet")
    novo = N.calcular(desc, base, emp, publicado["motivos"])
    assert json.loads(json.dumps(novo["versoes"], ensure_ascii=False)) == publicado["versoes"]
    assert publicado["juncao"]["sem_operacao"] == 0
    for nome, f in publicado["fontes"].items():
        assert f["url"].startswith("https://www.bcb.gov.br/htms/sicor/"), nome
        assert len(f["sha256"]) == 64 and f["last_modified"], nome


# sha256 das linhas (ordenadas, sem cabeçalho, LF) do arquivo de 07/10/2026 usado no memorando; o snapshot
# local foi apagado depois do porte, e o parquet o reconstrói linha a linha.
SHA256_SNAPSHOT_0710 = "1b879ad93d647b3ce8d54a2ffd9b4a1b4ffc7236eb1367e8b55446dd022fdcd2"


def test_parquet_reconstroi_o_arquivo_do_memorando(publicado):
    import hashlib

    d = pd.read_parquet(DIR / "desclassificacoes.parquet")
    d = d[d["no_snapshot_memorando"].fillna(False).astype(bool)]
    linhas = sorted(
        f"{r.ref_bacen};{r.nu_ordem};{r.dt_desc:%m/%d/%Y} 00:00:00;{int(r.cd_motivo)};"
        f"{r.vl_desc:.2f};{r.tipo_desc}"
        for r in d.itertuples()
    )
    assert len(linhas) == 15902
    assert hashlib.sha256("\n".join(linhas).encode()).hexdigest() == SHA256_SNAPSHOT_0710


def test_matriz_de_validacao_completa():
    """validacao/README.md e fontes.yaml: as 12 linhas da seção 3, com URL, data, prova e não prova."""
    import yaml

    d = yaml.safe_load((RAIZ / "validacao" / "fontes.yaml").read_text(encoding="utf-8"))
    ev = d["evidencias"]
    assert [e["id"] for e in ev] == list(range(1, 13))
    for e in ev:
        assert e["prova"].strip() and e["nao_prova"].strip() and e["data"], e["id"]
        assert e["estado"] in {"reproduzido", "citado", "pendente"}, e["id"]
        assert e["url"] or e["tipo"] == "retroteste", e["id"]
    linhas = [ln for ln in (RAIZ / "validacao" / "README.md").read_text(encoding="utf-8").splitlines()
              if ln.startswith("| ") and ln.split("|")[1].strip().isdigit()]
    assert [int(ln.split("|")[1]) for ln in linhas] == list(range(1, 13))
    assert all(len(ln.split("|")) >= 9 for ln in linhas)
