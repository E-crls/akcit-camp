"""Casos de demonstração fora do repositório (`LAUDO_CASOS_DIR`, P1-5) e o aviso de cada caso.

Um caso montado fora de `eval/golden/demo` (ex.: o dataset sintético, ignorado pelo git) entra na carteira, abre pelo
botão e, com o bloco `demonstracao:`, tem a triagem e o aviso lidos do próprio `caso.yaml`. O DEMO-0001 continua com
o mesmo aviso fixo (o texto entra no contexto do LLM e na contingência gravada).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from laudo import demonstracao
from laudo.agent import estado as est
from laudo.agent.ferramentas_falsas import operacao_exemplo
from laudo.api import casos as casos_mod
from laudo.api.main import criar_app
from laudo.api.servico import Config
from laudo.tools import laudo as ferr_laudo

RAIZ = Path(__file__).resolve().parents[2]
DEMO = RAIZ / "eval" / "golden" / "demo" / "DEMO-0001"
AVISO_UFG = ("LOCAL REAL, OPERAÇÃO FICTÍCIA, DADOS SINTÉTICOS: o local de teste é usado só como cenário; operação, "
             "partes, documentos e evidências são sintéticos.")
TRIAGEM = {"prioridade_verificacao": 0, "prioridade_nivel": "sem_sinal", "motivos": [],
           "observacoes": ["operação de teste incluída por amostragem"]}


def _caso(pasta: Path, cid: str = "UFG-TESTE-0001", ref: str = "000000099", **extra) -> Path:
    op = operacao_exemplo(ref).model_dump(mode="json")
    op["fonte"] = "sintetico+local_real_osm"
    dados = {
        "id": cid, "sintetico": True, "data_fiscalizacao": "2026-10-20", "data_referencia": "2026-10-20",
        "defeito": {"titulo": "Operação fictícia, dados sintéticos", "descricao": "caso de teste"},
        "operacao": op, "triagem": TRIAGEM, "aviso": AVISO_UFG,
        "demonstracao": {"marca_dagua": demonstracao.MARCA_DAGUA, "nota_geometria": "local de teste"},
        "roteiro": [{"titulo": "Triagem", "fala": "Bom dia."}],
        **extra,
    }
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "caso.yaml").write_text(yaml.safe_dump(dados, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return pasta


@pytest.fixture()
def externos(tmp_path, monkeypatch):
    base = tmp_path / "sinteticos" / "casos"
    _caso(base / "UFG-TESTE-0001")
    monkeypatch.setenv(demonstracao.ENV_CASOS_DIR, str(base))
    demonstracao.limpar_cache()
    yield base
    monkeypatch.delenv(demonstracao.ENV_CASOS_DIR)
    demonstracao.limpar_cache()
    est.ids_deterministicos(None)
    ferr_laudo.configurar(None, None)


def test_caso_externo_e_listado_e_localizado(externos):
    ids = casos_mod.listar_casos_disponiveis()
    assert "UFG-TESTE-0001" in ids
    if DEMO.joinpath("caso.yaml").exists():
        assert ids.index("DEMO-0001") < ids.index("UFG-TESTE-0001")  # os do repositório vêm antes
    assert casos_mod.localizar_caso("UFG-TESTE-0001") == externos / "UFG-TESTE-0001"
    # pasta com outro nome: achada pelo id do caso.yaml
    _caso(externos / "pasta-qualquer", cid="UFG-TESTE-0002", ref="000000098")
    assert casos_mod.localizar_caso("UFG-TESTE-0002") == externos / "pasta-qualquer"
    assert casos_mod.localizar_caso("NAO-EXISTE") is None
    with pytest.raises(FileNotFoundError, match="sinteticos"):
        casos_mod.carregar_caso("NAO-EXISTE", externos / "trabalho")


def test_aviso_lido_do_caso_e_demo_0001_identico(externos):
    op = operacao_exemplo("000000099").model_copy(update={"fonte": "sintetico+local_real_osm"})
    assert demonstracao.aviso_de(op) == AVISO_UFG
    assert demonstracao.bloco_laudo(op) == {"marca_dagua": demonstracao.MARCA_DAGUA, "aviso": AVISO_UFG}
    # o bloco demonstracao.aviso vence o aviso de topo
    _caso(externos / "UFG-TESTE-0003", cid="UFG-TESTE-0003", ref="000000097",
          demonstracao={"marca_dagua": demonstracao.MARCA_DAGUA, "aviso": "Aviso do bloco."})
    demonstracao.limpar_cache()
    assert demonstracao.aviso_de(op.model_copy(update={"ref_bacen": "000000097"})) == "Aviso do bloco."
    # caso indexado sem aviso nem máscara do Sicor: o aviso genérico (verdadeiro), nunca o do DEMO-0001
    assert demonstracao.aviso_do_caso({"demonstracao": {"marca_dagua": "x"}}) == demonstracao.AVISO_GOLDEN
    if not DEMO.joinpath("caso.yaml").exists():
        pytest.skip("DEMO-0001 não montado")
    # DEMO-0001 (mascarado do Sicor): o AVISO fixo de sempre, mesmo com o aviso próprio no caso.yaml
    dados = yaml.safe_load(DEMO.joinpath("caso.yaml").read_text(encoding="utf-8"))
    assert dados.get("aviso") and dados["demonstracao"].get("mascarado_versao") is not None
    assert demonstracao.aviso_do_caso(dados) == demonstracao.AVISO
    demo_op = dados["operacao"]
    assert demonstracao.aviso_de(demo_op) == demonstracao.AVISO
    # uma cópia do DEMO-0001 fora do repositório (mesmo REF, outro aviso) não substitui o de dentro
    _caso(externos / "DEMO-COPIA", cid="DEMO-COPIA", ref=str(demo_op["ref_bacen"]),
          demonstracao={"marca_dagua": demonstracao.MARCA_DAGUA, "aviso": "outro aviso"})
    demonstracao.limpar_cache()
    assert demonstracao.aviso_de(demo_op) == demonstracao.AVISO


def test_carregar_operacao_do_caso_externo_traz_triagem_e_aviso_do_caso(externos):
    from laudo.contracts import REGISTRO
    from laudo.geo import bench
    from laudo.tools import carteira  # noqa: F401  (registra as ferramentas)

    try:
        bench.operacoes()
    except bench.BenchAusente:
        pytest.skip("bench Fiscal-GO ausente")
    f = REGISTRO["carregar_operacao"]
    env = f.funcao(f.entrada.model_validate({"ref_bacen": "000000099"}))
    assert env.ok and env.data["demonstracao"] is True
    assert env.data["triagem"]["prioridade_nivel"] == "sem_sinal" and AVISO_UFG in env.data["aviso"]
    assert demonstracao.AVISO not in env.data["aviso"]
    lot = REGISTRO["checar_lotacao"]
    e2 = lot.funcao(lot.entrada.model_validate({"ref_bacen": "000000099"}))
    assert e2.ok and e2.data["fonte"] == "demonstracao"
    if DEMO.joinpath("caso.yaml").exists():  # o DEMO-0001 segue com o aviso fixo na ferramenta
        e3 = f.funcao(f.entrada.model_validate({"ref_bacen": "000000001"}))
        assert e3.ok and e3.data["aviso"].endswith(demonstracao.AVISO)


def test_caso_externo_na_carteira_abre_pelo_botao(externos, tmp_path):
    c = TestClient(criar_app(Config(dados=tmp_path / "api", asr="desligado")))
    casos = {x["id"]: x for x in c.get("/api/fiscalizacoes").json()["casos"]}
    assert "UFG-TESTE-0001" in casos and not casos["UFG-TESTE-0001"].get("erro")
    assert casos["UFG-TESTE-0001"]["demonstracao"]["aviso"] == AVISO_UFG
    r = c.post("/api/fiscalizacoes", json={"caso": "UFG-TESTE-0001"})
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["id"] == "fis_ufg_teste_0001" and e["triagem"]["prioridade_nivel"] == "sem_sinal"
    assert e["demonstracao"]["aviso"] == AVISO_UFG and e["operacao"]["ref_bacen"] == "000000099"
