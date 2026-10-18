"""Ética da demo: o caso DEMO-0001 não aponta para operação, instituição ou gleba reais, e todo laudo/tela de
operação sintética leva a marca d'água "DEMONSTRAÇÃO — dados sintéticos".

Se este teste falhar depois de regerar o caso (`eval/golden/gerador/gerar_casos.py --so-demo`), rode
`scripts/py.sh scripts/mascarar_demo.py`.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

from laudo import demonstracao
from laudo.agent import estado as est
from laudo.agent.ferramentas_falsas import criar_ferramentas_falsas, operacao_exemplo
from laudo.agent.politica import Politica
from laudo.agent.verificador import Verificador
from laudo.audit import otel
from laudo.tools import laudo as ferr_laudo

RAIZ = Path(__file__).resolve().parents[2]
CASO = RAIZ / "eval" / "golden" / "demo" / "DEMO-0001"

pytestmark = pytest.mark.skipif(not (CASO / "caso.yaml").exists(), reason="DEMO-0001 não montado")


def _mascarar():
    spec = importlib.util.spec_from_file_location("mascarar_demo", RAIZ / "scripts" / "mascarar_demo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_demo_nao_aponta_para_operacao_gleba_ou_if_reais():
    dados = yaml.safe_load((CASO / "caso.yaml").read_text(encoding="utf-8"))
    problemas = _mascarar().verificar(dados)
    assert problemas == [], "rode scripts/py.sh scripts/mascarar_demo.py: " + "; ".join(problemas)
    op = dados["operacao"]
    assert op["ref_bacen"] == "000000001" and "fictícia" in op["instituicao"]
    assert demonstracao.eh_demonstracao(op)
    assert dados["demonstracao"]["marca_dagua"] == demonstracao.MARCA_DAGUA


def test_documentos_da_demo_nao_citam_ref_nem_banco_real():
    from laudo.geo import bench

    try:
        refs = set(bench.operacoes()["ref_bacen"].astype(str))
    except bench.BenchAusente:
        pytest.skip("bench Fiscal-GO ausente")
    for arq in [*CASO.glob("*.json"), *CASO.glob("*.xml"), *CASO.glob("*.html"), CASO / "caso.yaml"]:
        texto = arq.read_text(encoding="utf-8", errors="ignore")
        assert "BCO DO BRASIL" not in texto.upper(), arq.name
        assert not [r for r in refs if r in texto], arq.name


def test_carregar_operacao_devolve_triagem_da_operacao_ficticia():
    from laudo.contracts import REGISTRO
    from laudo.tools import carteira  # noqa: F401  (registra a ferramenta)

    f = REGISTRO["carregar_operacao"]
    env = f.funcao(f.entrada.model_validate({"ref_bacen": "000000001"}))
    assert env.ok and env.data["demonstracao"] is True
    assert env.data["triagem"]["prioridade_nivel"] == "media"
    assert "6,0 cab/ha" in env.data["motivo"] and "não é indício de irregularidade" in env.data["motivo"]
    lot = REGISTRO["checar_lotacao"]
    e2 = lot.funcao(lot.entrada.model_validate({"ref_bacen": "000000001"}))
    assert e2.ok and e2.data["fonte"] == "demonstracao" and round(e2.data["lotacao_cab_ha"], 1) == 6.0


@pytest.fixture()
def repo(tmp_path):
    otel.configurar(tmp_path / "traces")
    r = est.RepositorioFiscalizacoes(tmp_path)
    reg = criar_ferramentas_falsas()
    ferr_laudo.configurar(r, Politica(Verificador(reg), reg))
    yield r
    ferr_laudo.configurar(None, None)


def test_laudo_de_operacao_sintetica_tem_marca_dagua_e_sem_caminho_absoluto(repo):
    fis = repo.criar(operacao_exemplo())
    res = Politica().verificador.recalcular(fis)
    laudo = ferr_laudo.montar_laudo(fis, res)
    assert laudo["demonstracao"]["marca_dagua"] == demonstracao.MARCA_DAGUA
    html = ferr_laudo.renderizar_html(laudo)
    assert "DEMONSTRAÇÃO — dados sintéticos" in html and "marca-dagua" in html and "[DEMONSTRAÇÃO]" in html
    assert ":\\" not in laudo["trace"]["arquivo"] and not laudo["trace"]["uri"].startswith("file:")


def test_laudo_de_operacao_do_sicor_nao_tem_marca_dagua(repo):
    op = operacao_exemplo().model_copy(update={"ref_bacen": "123456789", "fonte": "sicor"})
    fis = repo.criar(op)
    laudo = ferr_laudo.montar_laudo(fis, Politica().verificador.recalcular(fis))
    assert laudo["demonstracao"] is None
    assert 'marca-dagua"' not in ferr_laudo.renderizar_html(laudo)
