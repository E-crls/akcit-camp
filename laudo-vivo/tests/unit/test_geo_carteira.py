"""Ferramentas de carteira sobre um bench sintético mínimo (sem rede; REF_BACEN fictícios)."""

from __future__ import annotations

import math
import re

import pandas as pd
import pytest
from shapely.geometry import box

from laudo.contracts import REGISTRO, CodigoErro, Operacao
from laudo.geo import bench
from laudo.tools.carteira import (
    EntradaCarregarOperacao,
    EntradaChecarLotacao,
    EntradaTriarCarteira,
    carregar_operacao,
    checar_lotacao,
    triar_carteira,
)

MUN = "5299999"  # código fictício em GO


def op(ref: str, **kw) -> dict:
    base = {"ref_bacen": ref, "finalidade": "Investimento", "atividade": "Pecuário(a)",
            "modalidade": "AQUISIÇÃO DE ANIMAIS", "produto": "BOVINOS", "variedade": "CARNE - MATRIZES",
            "modalidades": ["AQUISIÇÃO DE ANIMAIS"], "tipos_itens": ["bovinos"], "dt_emissao": pd.Timestamp("2026-05-02"),
            "valor_rs": 100_000.0, "area_financiada_ha": 40.0, "area_informada_ha": 40.0, "area_glebas_ha": 40.0,
            "area_lotacao_ha": 40.0, "qtd_bovinos": 40.0, "unidade_qtd_bovinos": "UA", "eh_compra_gado": True,
            "compra_gado_tipo": "investimento", "eh_pecuaria_bovina": True, "confinamento": False,
            "lotacao_implicita_cab_ha": 1.0, "municipio_ibge": MUN, "municipio_nome": "Vila Teste",
            "instituicao": "BANCO FICTICIO S.A.", "tem_poligono": True, "n_ops_sobrepostas": 0,
            "sobreposicao_max_frac": math.nan, "refs_sobrepostas": [], "exige_sensoriamento_remoto": False,
            "prioridade_verificacao": 0, "prioridade_nivel": "sem_sinal", "motivos": [], "motivos_codigos": [],
            "observacoes": [], "fonte_versao": "sicor@teste;ibge-ppm@teste"}
    return base | kw


@pytest.fixture
def bench_falso(tmp_path, monkeypatch):
    ops = pd.DataFrame([
        op("900000001"),
        op("900000002", qtd_bovinos=240.0, lotacao_implicita_cab_ha=6.0, prioridade_verificacao=3,
           prioridade_nivel="media", motivos=["lotação implícita de 6,0 UA/ha (+3)"], motivos_codigos=["LOTACAO_ALTA"],
           valor_rs=500_000.0),
        op("900000003", prioridade_verificacao=3, prioridade_nivel="media", valor_rs=900_000.0,
           motivos=["gleba sobreposta (+3)"], motivos_codigos=["SOBREPOSICAO_GLEBAS"], instituicao="COOP FICTICIA"),
        op("900000004", finalidade="Custeio", modalidade="LAVOURA", produto="SOJA", modalidades=["LAVOURA"],
           tipos_itens=["lavoura"], eh_compra_gado=False, compra_gado_tipo=None, eh_pecuaria_bovina=False,
           qtd_bovinos=math.nan, prioridade_verificacao=1, prioridade_nivel="baixa"),
        op("900000005", area_lotacao_ha=math.nan, area_glebas_ha=math.nan, tem_poligono=False, municipio_ibge=None,
           prioridade_verificacao=2, prioridade_nivel="media"),
        op("900000006", confinamento=True, lotacao_implicita_cab_ha=50.0, qtd_bovinos=2000.0),
    ])
    itens = pd.DataFrame([
        {"ref_bacen": "900000001", "nu_ordem": 1, "tipo_item": "bovinos", "quantidade": 40.0, "unidade_item": "UA_450kg",
         "area_financiada_ha": 40.0, "valor_rs": 90_000.0, "modalidade": "AQUISIÇÃO DE ANIMAIS", "produto": "BOVINOS",
         "variedade": "CARNE - MATRIZES (VACAS E CRIAS FÊMEAS PARA POVOAMENTO)", "fase": "Não se aplica"},
        {"ref_bacen": "900000001", "nu_ordem": 2, "tipo_item": "outro", "quantidade": 1.0, "unidade_item": "un",
         "area_financiada_ha": 40.0, "valor_rs": 10_000.0, "modalidade": "SERVIÇOS PROFISSIONAIS/TÉCNICOS",
         "produto": "Terraços, Porteiras, Mata-burros, Currais, Cochos, Cercas", "variedade": "CONSTRUÇÃO OU REFORMA",
         "fase": "Não se aplica"},
    ])
    g = box(-49.30, -16.70, -49.29, -16.69).wkt
    glebas = pd.DataFrame([{"ref_bacen": "900000001", "nu_ordem": 1, "nu_indice": 0, "area_ha": 40.0, "wkt": g},
                           {"ref_bacen": "900000001", "nu_ordem": 2, "nu_indice": 0, "area_ha": 40.0, "wkt": g}])
    reb = pd.DataFrame([{"cod_ibge": MUN, "municipio": "Vila Teste", "area_ha": 100_000.0, "ano": 2025,
                         "bovinos_cab": 80_000.0, "densidade_bovina_cab_ha": 0.8, "qtd_compra_gado_2026": 500.0}])
    for nome, df in [("fiscal_go_2026", ops), ("itens_go_2026", itens), ("glebas_go_2026", glebas),
                     ("rebanho_municipal_go", reb)]:
        df.to_parquet(tmp_path / f"{nome}.parquet", index=False)
    monkeypatch.setenv("LAUDO_BENCH_DIR", str(tmp_path))
    bench.limpar_cache()
    yield tmp_path
    bench.limpar_cache()


def test_ferramentas_registradas():
    for nome in ("triar_carteira", "carregar_operacao", "checar_lotacao", "serie_ndvi"):
        __import__("laudo.tools.ndvi")
        assert nome in REGISTRO
        assert REGISTRO[nome].schema_ollama()["function"]["name"] == nome


def test_triar_ordena_por_prioridade_e_valor(bench_falso):
    env = triar_carteira(EntradaTriarCarteira())
    assert env.ok and env.ferramenta == "triar_carteira"
    refs = [o["ref_bacen"] for o in env.data["operacoes"]]
    assert refs == ["900000003", "900000002", "900000005"]  # 3 (maior valor) > 3 > 2; lavoura fora
    assert env.data["operacoes"][0]["posicao"] == 1
    assert "não é indício de irregularidade" in env.data["aviso"]
    assert env.fonte_versao == "sicor@teste;ibge-ppm@teste"


def test_triar_filtros(bench_falso):
    env = triar_carteira(EntradaTriarCarteira(municipio="vila teste", so_com_poligono=True, prioridade_minima=0))
    assert {o["ref_bacen"] for o in env.data["operacoes"]} == {"900000001", "900000002", "900000003", "900000006"}
    env = triar_carteira(EntradaTriarCarteira(instituicao="coop", prioridade_minima=0))
    assert [o["ref_bacen"] for o in env.data["operacoes"]] == ["900000003"]
    env = triar_carteira(EntradaTriarCarteira(tipo_empreendimento="lavoura", finalidade="custeio"))
    assert [o["ref_bacen"] for o in env.data["operacoes"]] == ["900000004"]
    env = triar_carteira(EntradaTriarCarteira(municipio="Atlantida"))
    assert not env.ok and env.error.code == CodigoErro.ENTRADA_INVALIDA


def test_carregar_operacao_monta_contrato(bench_falso):
    env = carregar_operacao(EntradaCarregarOperacao(ref_bacen="900000001"))
    assert env.ok
    o = Operacao.model_validate(env.data["operacao"])
    assert o.finalidade == "investimento" and o.tomador_ref == "anon" and o.fonte == "sicor"
    assert o.municipio_ibge == MUN and str(o.data_contratacao) == "2026-05-02"
    assert len(o.glebas_wkt) == 1  # WKT repetido em duas ordens entra uma vez
    bov, benf = o.itens
    assert (bov.id, bov.tipo, bov.quantidade, bov.unidade) == ("it1", "bovinos", 40.0, "UA_450kg")
    assert bov.categoria_animal.startswith("matrizes")
    assert benf.tipo == "outro" and "Sicor não discrimina" in benf.descricao
    assert "triagem" in env.data
    nao = carregar_operacao(EntradaCarregarOperacao(ref_bacen="123456789"))
    assert not nao.ok and nao.error.code == CodigoErro.SEM_DADOS


def test_carregar_sem_bench(tmp_path, monkeypatch):
    monkeypatch.setenv("LAUDO_BENCH_DIR", str(tmp_path / "nao_existe"))
    bench.limpar_cache()
    env = carregar_operacao(EntradaCarregarOperacao(ref_bacen="900000001"))
    assert not env.ok and env.error.code == CodigoErro.SEM_DADOS
    bench.limpar_cache()


def test_checar_lotacao_por_ref_compara_municipio(bench_falso):
    env = checar_lotacao(EntradaChecarLotacao(ref_bacen="900000002"))
    assert env.ok
    d = env.data
    assert d["lotacao_cab_ha"] == pytest.approx(6.0)
    assert d["pontos_triagem"] == 3 and d["sinal"] == "prioridade_verificacao"
    assert d["razao_lotacao_densidade_municipal"] == pytest.approx(7.5)
    assert d["fracao_rebanho_municipal"] == pytest.approx(240 / 80_000)
    assert "não irregularidade" in d["texto"]


def test_checar_lotacao_abstem_sem_area(bench_falso):
    env = checar_lotacao(EntradaChecarLotacao(ref_bacen="900000005"))
    assert not env.ok and env.error.code == CodigoErro.SEM_DADOS
    assert env.data["status"] == "indeterminado"
    env = checar_lotacao(EntradaChecarLotacao(cabecas=30, area_ha=0))
    assert not env.ok and env.data["motivo"].startswith("área")


def test_checar_lotacao_entrada_livre_e_confinamento(bench_falso):
    env = checar_lotacao(EntradaChecarLotacao(cabecas=30, area_ha=20, municipio_ibge=MUN))
    assert env.ok and env.data["lotacao_cab_ha"] == 1.5 and env.data["sinal"] == "sem_sinal"
    conf = checar_lotacao(EntradaChecarLotacao(ref_bacen="900000006"))
    assert conf.ok and conf.data["classe"] == "nao_aplicavel_confinamento" and conf.data["pontos_triagem"] == 0
    lav = checar_lotacao(EntradaChecarLotacao(ref_bacen="900000004"))
    assert not lav.ok and lav.error.code == CodigoErro.FORA_DO_ESCOPO


def test_bench_real_sem_pii():
    """Se o bench real existir, nenhuma coluna ou valor com cara de CPF/CNPJ completo."""
    bench.limpar_cache()
    try:
        op_real = bench.operacoes()
    except bench.BenchAusente:
        pytest.skip("bench Fiscal-GO não gerado")
    proibidas = re.compile(r"CPF|MUTUARIO|AGENCIA|CEDULA|NIRF|SNCR|CD_CAR", re.IGNORECASE)
    assert not [c for c in op_real.columns if proibidas.search(c)]
    assert op_real["if_cnpj_base"].str.fullmatch(r"\d{8}").all()  # raiz de 8 dígitos da IF, não do tomador
    assert op_real["ref_bacen"].is_unique
