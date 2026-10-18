"""emitir_rascunho: bloqueada (BLOQUEADO_POLITICA + pendências) versus permitida (HTML, JSON e hash)."""

import json
from pathlib import Path

import pytest

from laudo.agent import estado as est
from laudo.agent.ferramentas_falsas import criar_ferramentas_falsas, operacao_exemplo
from laudo.agent.politica import Politica
from laudo.agent.verificador import Verificador
from laudo.audit import hashchain, otel
from laudo.contracts import REGISTRO, CodigoErro, Envelope
from laudo.tools import laudo as ferr_laudo


@pytest.fixture()
def ctx(tmp_path):
    otel.configurar(tmp_path / "traces")
    repo = est.RepositorioFiscalizacoes(tmp_path)
    reg = criar_ferramentas_falsas()
    ferr_laudo.configurar(repo, Politica(Verificador(reg), reg))
    yield repo
    ferr_laudo.configurar(None, None)


def _chk(fis, ferramenta, item, data, ev_tipo="foto", ev_id=None):
    if ev_id is None:
        ev_id = est.adicionar_evidencia(
            fis, ev_tipo, conteudo=f"{ferramenta}{len(fis.evidencias)}".encode(), meta={"item_id": item}
        ).id
    est.registrar_checagem(
        fis,
        ferramenta,
        f"h{len(fis.checagens)}",
        Envelope.sucesso(ferramenta, data),
        item_id=item,
        evidencias=[ev_id],
        span_id="00ff00ff00ff00ff",
    )
    return ev_id


def _fis(repo, contagem=40, gta=True, etapa="REVISAO"):
    fis = repo.criar(operacao_exemplo())
    _chk(
        fis,
        "planejar_metodo",
        None,
        {"status": "ok", "metodo": "presencial", "justificativa": "bovinos"},
        "documento",
    )
    fis.metodo = "presencial"
    _chk(fis, "conciliar_nfe", "bov1", {"status": "ok", "quantidade": 40}, "nfe_xml")
    if gta:
        _chk(fis, "conciliar_gta", "bov1", {"status": "ok", "quantidade": 40}, "gta")
    _chk(
        fis,
        "contar_bovinos_video",
        "bov1",
        {"status": "ok", "contagem": contagem, "intervalo": [contagem - 1, contagem + 1]},
        "video",
    )
    foto = _chk(fis, "integridade_foto", "cerca1", {"status": "ok"})
    _chk(fis, "geofence", "cerca1", {"status": "dentro"}, ev_id=foto)
    fis.estado_fsm = etapa
    repo.salvar(fis)
    return fis


def _emitir(fis_id, texto=None) -> Envelope:
    return ferr_laudo.emitir_rascunho(
        ferr_laudo.EntradaEmitirRascunho(fiscalizacao_id=fis_id, texto_redigido=texto)
    )


def test_registrada_no_registro_global():
    assert "emitir_rascunho" in REGISTRO and "registrar_ocorrencia" in REGISTRO
    assert REGISTRO["emitir_rascunho"].schema_ollama()["function"]["name"] == "emitir_rascunho"


def test_bloqueada_sem_evidencia_minima_e_com_divergencia(ctx):
    fis = _fis(ctx, contagem=32, gta=False)
    env = _emitir(fis.id)
    assert not env.ok and env.error.code == CodigoErro.BLOQUEADO_POLITICA
    pend = env.data["pendencias"]
    assert any(p["regra_id"].startswith("POL-01") and p["campo"] == "item:bov1:gta" for p in pend)
    assert any(p["regra_id"] == "POL-02" and p["campo"] == "item:bov1:quantidade" for p in pend)
    assert not (ctx.dir.parent / "laudos" / fis.id).exists()  # nada é gerado quando bloqueia


def test_permitida_gera_html_json_e_hash_verificavel(ctx):
    fis = _fis(ctx)
    env = _emitir(fis.id)
    assert env.ok, env.error
    html = Path(env.data["laudo_html"]).read_text(encoding="utf-8")
    laudo = json.loads(Path(env.data["laudo_json"]).read_text(encoding="utf-8"))
    assert "RASCUNHO" in html and env.data["hash_raiz"] in html and "Assinatura humana" in html
    assert "item:bov1:quantidade" in html and "00ff00ff00ff00ff" in html  # link para o span
    assert laudo["operacao"]["ref_bacen"] == "SINT-2026-0001" and "tomador_ref" in laudo["operacao"]
    assert {i["status"] for i in laudo["itens"]} == {"verificado"}
    assert all(i["evidencias"] and i["checagens"] for i in laudo["itens"])
    conteudo = {k: v for k, v in laudo.items() if k != "hash_raiz"}
    assert hashchain.hash_raiz_laudo(laudo["cadeia"]["raiz"], conteudo) == laudo["hash_raiz"]
    assert laudo["metodo"]["metodo"] == "presencial" and laudo["metodo"]["provisoria"] is True
    assert ctx.carregar(fis.id).evidencias == fis.evidencias  # a ferramenta não altera o estado


def test_divergencia_com_justificativa_humana_libera(ctx):
    fis = _fis(ctx, contagem=32)
    res = Verificador({}).recalcular(fis)
    res.campos["item:bov1:quantidade"].justificativa_humana = "oito garrotes vendidos antes da visita"
    fis.campos = res.campos
    ctx.salvar(fis)
    env = _emitir(fis.id)
    assert env.ok
    html = Path(env.data["laudo_html"]).read_text(encoding="utf-8")
    assert "oito garrotes vendidos" in html and "divergente" in html


def test_redacao_do_llm_so_entra_com_grounding(ctx):
    fis = _fis(ctx)
    ruim = _emitir(fis.id, texto="Foram contados 57 animais.")
    assert ruim.ok and ruim.data["resumo_origem"] == "template"
    bom = _emitir(fis.id, texto="Foram contados 40 animais, igual aos 40 financiados.")
    assert bom.data["resumo_origem"] == "llm"


def test_sensoriamento_remoto_exige_metadados_do_item4(ctx):
    fis = _fis(ctx)
    _chk(fis, "serie_ndvi", None, {"status": "ok", "sensor": "Sentinel-2 MSI L2A"}, "satelite")
    ctx.salvar(fis)
    env = _emitir(fis.id)
    assert not env.ok and any("sensoriamento" in p["falta"] for p in env.data["pendencias"])
    fis = ctx.carregar(fis.id)
    _chk(
        fis,
        "serie_ndvi",
        None,
        {
            "status": "ok",
            "sensor": "Sentinel-2 MSI L2A",
            "datas": ["2026-09-21"],
            "resolucao_m": 10,
            "bandas": ["B04", "B08"],
            "metodologia": "NDVI mediano",
        },
        "satelite",
    )
    ctx.salvar(fis)
    env = _emitir(fis.id)  # vale a última série da gleba; a antiga continua listada (append-only)
    assert env.ok, env.data
    laudo = json.loads(Path(env.data["laudo_json"]).read_text(encoding="utf-8"))
    sr = laudo["sensoriamento_remoto"]
    assert len(sr) == 2 and sr[1]["resolucao"] == "10 m" and sr[1]["datas"] == "2026-09-21"
    assert sr[0]["datas"] == "não informado pela ferramenta"  # nunca inventa metadado
    assert "Sentinel-2 MSI L2A" in Path(env.data["laudo_html"]).read_text(encoding="utf-8")


def test_selada_ou_em_assinatura_nao_reemite(ctx):
    fis = _fis(ctx, etapa="ASSINATURA")
    env = _emitir(fis.id)
    assert not env.ok and env.data["pendencias"][0]["regra_id"] == "POL-04"
    assert not _emitir("fis_inexistente").ok


def test_registrar_ocorrencia_entra_na_cadeia(ctx):
    fis = _fis(ctx)
    env = ferr_laudo.registrar_ocorrencia(
        ferr_laudo.EntradaOcorrencia(
            fiscalizacao_id=fis.id, tipo="pressao", descricao="pedido para marcar 40"
        )
    )
    assert env.ok
    f2 = ctx.carregar(fis.id)
    assert f2.ocorrencias[-1].id == env.data["ocorrencia_id"] and f2.evidencias[-1].tipo == "ocorrencia"
    assert hashchain.verificar_cadeia(f2.evidencias).integra
    ruim = ferr_laudo.registrar_ocorrencia(
        ferr_laudo.EntradaOcorrencia(fiscalizacao_id=fis.id, tipo="xyz", descricao="x")
    )
    assert not ruim.ok and ruim.error.code == CodigoErro.ENTRADA_INVALIDA
