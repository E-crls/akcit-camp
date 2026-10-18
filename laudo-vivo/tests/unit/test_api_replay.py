"""Contingência: a API em modo replay reproduz a demo gravada com o modelo real, sem GPU nem rede; e casos
YAML do golden set abrem e rodam o roteiro inteiro com ferramentas falsas."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from laudo.agent import estado as est
from laudo.api import casos as casos_mod
from laudo.api.main import criar_app
from laudo.api.servico import PIN_DEMO, Config
from laudo.tools import laudo as ferr_laudo

FIXTURE = Path(__file__).parent / "dados_agente" / "replay_demo_qwen35_4b.jsonl"


@pytest.fixture(autouse=True)
def _limpar():
    yield
    est.ids_deterministicos(None)
    ferr_laudo.configurar(None, None)


def _rodar_roteiro(c: TestClient, fis: str) -> list[dict]:
    saida = []
    while True:
        r = c.post(f"/api/fiscalizacoes/{fis}/roteiro/proximo")
        if r.status_code == 409:
            return saida
        assert r.status_code == 200, r.text
        j = r.json()
        saida.append(j)
        if j.get("acao_humana") == "assinar":
            laudo = j["estado"]["laudo"]
            # L57: sem rascunho emitido (ex.: integridade da foto barrou a emissão), diz isso em vez de
            # TypeError
            assert laudo, (
                "passo de assinatura sem rascunho emitido: o roteiro não chegou ao RASCUNHO "
                f"(etapa {j['estado']['etapa']}; pendências: {j['estado'].get('pendencias')})"
            )
            h = laudo["hash_raiz"]
            a = c.post(
                f"/api/fiscalizacoes/{fis}/assinar", json={"pin": PIN_DEMO, "hash_confirmado": h}
            ).json()
            saida.append(a)


def _referencia_cli(tmp: Path) -> tuple[int, str, list[str]]:
    """O mesmo replay pelo caminho do `scripts/demo_cli.py` (sem API): substituições, etapa final, falas."""
    from laudo.agent import roteiro_demo as demo
    from laudo.agent.condutor import Condutor
    from laudo.agent.ferramentas_falsas import registro_com_falsas
    from laudo.audit import otel
    from laudo.contracts import REGISTRO
    from laudo.llm.provider import ReplayProvider

    otel.configurar(tmp / "traces")
    est.ids_deterministicos(demo.SEMENTE_IDS)
    registro, _ = registro_com_falsas(
        demo.CENARIO, base={k: REGISTRO[k] for k in ("emitir_rascunho", "registrar_ocorrencia")}
    )
    prov = ReplayProvider(FIXTURE, sequencial_se_ausente=True)
    cond = Condutor(prov, repo=est.RepositorioFiscalizacoes(tmp), registro=registro)
    passos = demo.executar(cond, demo.preparar_arquivos(tmp / "arquivos"))
    est.ids_deterministicos(None)
    return prov.substituicoes, cond.repo.carregar(demo.FIS_ID).estado_fsm, [p.resposta.fala for p in passos]


@pytest.mark.skipif(not FIXTURE.exists(), reason="gravação do replay ausente")
def test_replay_pela_api_reproduz_a_demo_do_cli(tmp_path):
    """A API em replay faz exatamente as mesmas requisições ao LLM que o demo_cli (mesma chave, mesma
    ordem). Com a gravação em dia, as duas substituições são zero; se o prompt mudar, as duas sobem juntas."""
    subs_cli, etapa_cli, falas_cli = _referencia_cli(tmp_path / "cli")
    c = TestClient(
        criar_app(Config(dados=tmp_path / "api", llm="replay", replay=str(FIXTURE), asr="desligado"))
    )
    assert c.get("/api/saude").json()["llm"]["tipo"] == "replay"
    for _ in range(2):  # "recomeçar demo" duas vezes: o replay recomeça do início e casa de novo
        e = c.post("/api/fiscalizacoes", json={"caso": "roteiro", "reiniciar": True}).json()
        out = _rodar_roteiro(c, e["id"])
        final = c.get(f"/api/fiscalizacoes/{e['id']}").json()
        assert final["etapa"] == etapa_cli
        assert c.get("/api/saude").json()["llm"]["substituicoes"] == subs_cli
        falas_api = [o["resposta"]["fala"] for o in out if o.get("resposta")]
        assert [f for f in falas_api if "hash" not in f] == [f for f in falas_cli if "hash" not in f]


def test_caso_yaml_derivado_do_golden(tmp_path):
    """Sem roteiro no caso.yaml, o roteiro é derivado das falas e evidências; vídeo ausente vira marcador."""
    pasta = tmp_path / "CASO-X"
    pasta.mkdir()
    (pasta / "nfe_1.xml").write_text("<NFe/>", encoding="utf-8")
    (pasta / "gta_1.json").write_text("{}", encoding="utf-8")
    (pasta / "fotos").mkdir()
    (pasta / "fotos" / "foto_cerca_1.jpg").write_bytes(b"\xff\xd8 foto")
    (pasta / "caso.yaml").write_text(
        """
id: CASO-X
sintetico: true
defeito: {titulo: teste}
data_fiscalizacao: '2026-10-06'
operacao:
  ref_bacen: SINT-2026-000777
  uf: GO
  municipio_nome: TESTE
  finalidade: investimento
  glebas_wkt:
  - POLYGON((-49.300 -16.800, -49.290 -16.800, -49.290 -16.790, -49.300 -16.790, -49.300 -16.800))
  itens:
  - {id: bov1, tipo: bovinos, descricao: 40 novilhas, quantidade: 40, unidade: cabeca}
  - {id: cerca1, tipo: cerca, descricao: cerca, quantidade: 800, unidade: m}
documentos:
  nfe: [{arquivo: nfe_1.xml}]
  gta: [{arquivo_json: gta_1.json, identificador: GO-TESTE}]
fotos:
- {id: foto_cerca_1, arquivo: fotos/foto_cerca_1.jpg, item_id: cerca1,
   gps_app: {lat: -16.7952, lon: -49.2951, precisao_m: 6.0}, exif: {presente: true}}
video: {id: v1, item_id: bov1, duracao_s: 30, saida_simulada_contador: {estimativa: 38, ic80: [37, 39]}}
falas:
- {de: fiscal, texto: Estou no curral.}
- {de: fiscal, texto: Foto da cerca.}
- {de: produtor, texto: 'Pode marcar 40, o resto está no pasto de cima.'}
esperado:
  campos:
    item:bov1:gta_data: {status_esperado: divergente, motivo: GTA anterior à NF-e}
""",
        encoding="utf-8",
    )
    caso = casos_mod.carregar_caso(str(pasta), tmp_path / "trabalho")
    assert caso.id == "CASO-X" and caso.fis_id == "fis_caso_x"
    assert [p.titulo for p in caso.roteiro][-2:] == ["Pressão", "Pedido de rascunho"]
    video = next(a for a in caso.arquivos if a.tipo == "video")
    assert video.disponivel is False and Path(video.nova.caminho).exists()
    assert caso.cenario["curral.mp4"]["contar_bovinos_video"]["contagem"] == 38
    assert caso.cenario["gta_1.json"]["conciliar_gta"]["status"] == "divergente"

    c = TestClient(criar_app(Config(dados=tmp_path / "api", caso=str(pasta), asr="desligado")))
    # pasta fora de eval/golden: só a que veio na linha de comando (e o id dela) é aceita pela API
    outra = tmp_path / "outra"
    outra.mkdir()
    (outra / "caso.yaml").write_text((pasta / "caso.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    assert c.post("/api/fiscalizacoes", json={"caso": str(outra)}).status_code == 404
    e = c.post("/api/fiscalizacoes", json={"caso": "CASO-X"}).json()
    assert e["id"] == "fis_caso_x"
    out = _rodar_roteiro(c, e["id"])
    eventos = [x["tipo"] for o in out for x in o.get("eventos", [])]
    assert "pressao" in eventos and "bloqueio" in eventos and "divergencia" in eventos
    final = c.get(f"/api/fiscalizacoes/{e['id']}").json()
    q = next(x for x in final["matriz"] if x["campo"] == "item:bov1:quantidade")
    assert q["status"] == "divergente" and q["valor_fmt"].startswith("38")


@pytest.mark.skipif(casos_mod.localizar_caso("DEMO-0001") is None, reason="DEMO-0001 ainda não montado")
def test_demo_0001_roda_ate_selar_com_ferramentas_falsas(tmp_path):
    c = TestClient(criar_app(Config(dados=tmp_path / "api", caso="DEMO-0001", asr="desligado")))
    e = c.post("/api/fiscalizacoes", json={"caso": "DEMO-0001"}).json()
    out = _rodar_roteiro(c, e["id"])
    eventos = {x["tipo"] for o in out for x in o.get("eventos", [])}
    assert {"pressao", "bloqueio", "emitido", "selado"} <= eventos
    assert c.get(f"/api/fiscalizacoes/{e['id']}").json()["etapa"] == "SELADO"


@pytest.mark.lento
def test_contingencia_web_do_demo_0001_com_ferramentas_reais(tmp_path, monkeypatch):
    """A contingência da interface (replay gravado por `scripts/gravar_contingencia_web.py`) reproduz o
    roteiro padrão de 19 passos, com a foto do DANFE e o residual, até SELADO, sem nenhuma requisição fora da
    gravação."""
    import os

    from laudo.vision.modelos import MODELOS

    if "lento" not in (os.environ.get("PYTEST_ADDOPTS") or "") and not os.environ.get("LAUDO_LENTO"):
        pytest.skip("teste lento: rode com LAUDO_LENTO=1")
    pasta = casos_mod.localizar_caso("DEMO-0001")
    replay = (pasta / "replay_qwen35_4b.jsonl") if pasta else None
    if replay is None or not replay.exists() or not MODELOS["yolox_m"].caminho.is_file():
        pytest.skip("gravação da contingência, caso ou yolox_m ausentes")
    monkeypatch.setenv("LAUDO_VLM_CACHE", str(Path(__file__).parent / "dados_agente" / "vlm_cache_demo"))
    monkeypatch.setenv("LAUDO_VLM_SO_CACHE", "1")
    c = TestClient(
        criar_app(
            Config(
                dados=tmp_path / "api", llm="replay", ferramentas="reais", caso="DEMO-0001", asr="desligado"
            )
        )
    )
    e = c.post("/api/fiscalizacoes", json={"caso": "DEMO-0001"}).json()
    out = _rodar_roteiro(c, e["id"])
    titulos = [o["passo"]["titulo"] for o in out if o.get("passo")]
    assert "Foto da nota impressa (DANFE)" in titulos and any(t.startswith("Residual") for t in titulos)
    assert c.get(f"/api/fiscalizacoes/{e['id']}").json()["etapa"] == "SELADO"
    assert c.get("/api/saude").json()["llm"]["substituicoes"] == 0
