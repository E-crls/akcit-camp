"""Integração agente × ferramentas reais: vocabulário de status, preenchimento de argumentos (contexto das
regras, data de referência, ids → caminhos), timeouts, POL-01 pelos bloqueios do rulebook, declarações do
fiscal (independência, conclusão de obra, justificativa) e degradação graciosa do LLM."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from pydantic import BaseModel

from laudo.agent import declaracoes as decl
from laudo.agent import estado as est
from laudo.agent.condutor import Condutor, Evento, NovaEvidencia
from laudo.agent.executor import (
    ExecutorFerramentas,
    normalizar_status,
    preencher_argumentos,
    prioridade_da_triagem,
    timeout_efetivo,
)
from laudo.agent.ferramentas_falsas import criar_ferramentas_falsas, operacao_exemplo
from laudo.agent.politica import Politica
from laudo.agent.verificador import ResultadoVerificacao, Verificador
from laudo.audit import otel
from laudo.contracts import (
    REGISTRO,
    Bloqueio,
    CampoLaudo,
    CodigoErro,
    Envelope,
    Ferramenta,
    Fiscalizacao,
    ItemFinanciado,
)
from laudo.llm.provider import ChamadaFerramenta, ErroLLM, ProvedorRoteirizado, RespostaLLM
from laudo.tools import carregar_todas
from laudo.tools import laudo as ferr_laudo

carregar_todas()


@pytest.fixture()
def traces(tmp_path):
    otel.configurar(tmp_path / "traces")
    yield tmp_path
    est.ids_deterministicos(None)
    ferr_laudo.configurar(None, None)


def _fis(**kw) -> Fiscalizacao:
    return Fiscalizacao(operacao=operacao_exemplo(), **kw)


# --- vocabulário de status ----------------------------------------------------------------------------------


def test_executor_normaliza_status_fora_do_vocabulario():
    env = normalizar_status(Envelope.sucesso("x", {"status": "dentro"}))
    assert env.data["status"] == "ok" and env.data["status_ferramenta"] == "dentro"
    assert normalizar_status(Envelope.sucesso("x", {"status": "calculado"})).data["status"] == "indeterminado"
    assert normalizar_status(Envelope.sucesso("x", {"status": "divergente"})).data == {"status": "divergente"}


def test_envelope_sem_status_nao_vira_ok():
    assert est.status_de_envelope(Envelope.sucesso("x", {"contagem": 40})) == "indeterminado"
    assert est.status_de_envelope(Envelope.sucesso("x", {"status": "fora"})) == "divergente"


def test_ferramentas_reais_devolvem_status_comum():
    from laudo.tools.geofence import EntradaGeofence, geofence

    wkt = "POLYGON ((-49.30 -16.70, -49.29 -16.70, -49.29 -16.69, -49.30 -16.69, -49.30 -16.70))"
    d = geofence(EntradaGeofence(lat=-16.695, lon=-49.295, precisao_m=5, glebas_wkt=[wkt])).data
    f = geofence(EntradaGeofence(lat=-16.60, lon=-49.295, precisao_m=5, glebas_wkt=[wkt])).data
    assert (d["status"], d["posicao"], f["status"], f["posicao"]) == ("ok", "dentro", "divergente", "fora")


# --- timeouts -----------------------------------------------------------------------------------------------


def test_timeout_da_contagem_proporcional_a_duracao(monkeypatch, tmp_path):
    from laudo.vision import video

    class Info:
        duracao_s = 20.0

    monkeypatch.setattr(video, "info_video", lambda caminho: Info())
    arq = tmp_path / "v.mp4"
    arq.write_bytes(b"x")
    ferr = REGISTRO["contar_bovinos_video"]
    curto = timeout_efetivo(ferr, ferr.entrada(caminho_video=str(arq)))
    Info.duracao_s = 120.0
    longo = timeout_efetivo(ferr, ferr.entrada(caminho_video=str(arq)))
    assert curto == pytest.approx(30 + 2 * 0.8 * 20) and longo > curto
    assert timeout_efetivo(REGISTRO["serie_ndvi"], None) == 240.0  # type: ignore[arg-type]


def test_timeout_de_ferramenta_longa_nao_e_repetido():
    class E(BaseModel):
        x: int = 1

    chamadas = []

    class Exec(ExecutorFerramentas):
        def _uma_vez(self, ferr, entrada, timeout):
            chamadas.append(timeout)
            return Envelope.falha(ferr.nome, CodigoErro.TIMEOUT, "sem resposta", retryable=True)

    reg = {"lenta": Ferramenta(nome="lenta", descricao="", entrada=E, funcao=lambda a: None, timeout_s=240)}
    env, _, _ = Exec(reg, dormir=lambda s: None).executar("lenta", {})
    assert env.error.code == CodigoErro.TIMEOUT and chamadas == [240]


# --- preenchimento de argumentos -----------------------------------------------------------------------------


def test_preenche_contexto_das_regras_e_data_de_referencia(traces):
    fis = _fis(data_referencia=date(2026, 10, 8), data_fiscalizacao=date(2026, 10, 7))
    fis.checagens.append(
        est.registrar_checagem(
            Fiscalizacao(operacao=fis.operacao), "carregar_operacao", "h",
            Envelope.sucesso("carregar_operacao", {"status": "ok", "triagem": {"prioridade_nivel": "alta"}}),
        )
    )
    args = preencher_argumentos(REGISTRO["planejar_metodo"], fis, {})
    assert args["data_referencia"] == "2026-10-08"
    assert args["contexto"] == {"data_fiscalizacao": "2026-10-07", "prioridade_verificacao": "alta"}
    assert REGISTRO["planejar_metodo"].entrada.model_validate(args)
    # integridade_foto: `contexto` é o id da fiscalização (duplicata em outra fiscalização = reuso)
    foto = est.adicionar_evidencia(fis, "foto", conteudo=b"jpg", caminho="c:/x/f.jpg", meta={"item_id": "cerca1"})
    a = preencher_argumentos(REGISTRO["integridade_foto"], fis, {"evidencia_id": foto.id}, dir_dados=Path("d"))
    assert a["contexto"] == fis.id and a["caminho_foto"] == "c:/x/f.jpg"
    assert a["indice"] == str(Path("d") / "indices" / "fotos.jsonl")


def test_prioridade_sem_sinal_conta_como_baixa():
    fis = _fis()
    fis.checagens.append(est.registrar_checagem(
        Fiscalizacao(operacao=fis.operacao), "triar_carteira", "h",
        Envelope.sucesso("triar_carteira", {"status": "ok", "operacoes": [
            {"ref_bacen": fis.operacao.ref_bacen, "prioridade_nivel": "sem_sinal"}]})))
    assert prioridade_da_triagem(fis) == "baixa"


def test_ids_de_evidencia_viram_caminhos_e_homologacao_so_em_sintetico():
    fis = _fis()
    nfe = est.adicionar_evidencia(fis, "nfe_xml", conteudo=b"<x/>", caminho="c:/docs/nfe.xml",
                                  meta={"item_id": "bov1"})
    ferr = REGISTRO["conciliar_nfe"]
    a = preencher_argumentos(ferr, fis, {"caminhos": [nfe.id], "item_id": "bov1"})
    assert a["caminhos"] == ["c:/docs/nfe.xml"] and a["parametros"] == {"aceitar_homologacao": True}
    real = fis.model_copy(update={"operacao": fis.operacao.model_copy(update={"fonte": "sicor"})})
    assert "parametros" not in preencher_argumentos(ferr, real, {"caminhos": [nfe.id], "item_id": "bov1"})


def test_hash_do_tomador_vem_do_tomador_ref():
    from laudo import privacidade

    h = "ab" * 32
    fis = Fiscalizacao(operacao=operacao_exemplo().model_copy(update={"tomador_ref": f"hmac:{h}"}))
    assert preencher_argumentos(REGISTRO["conciliar_gta"], fis, {})["tomador_doc_sha256"] == f"hmac:{h}"
    # hash público (sem sal) vira o hash da instalação; nunca é repassado como veio
    pub = Fiscalizacao(operacao=operacao_exemplo().model_copy(update={"tomador_ref": f"sha256:{h}"}))
    assert preencher_argumentos(REGISTRO["conciliar_gta"], pub, {})["tomador_doc_sha256"] == (
        f"hmac:{privacidade.hash_de_publico(h)}")
    assert "tomador_doc_sha256" not in preencher_argumentos(REGISTRO["conciliar_gta"], _fis(), {})


def test_regras_completam_contexto_com_os_contratos():
    from laudo.tools.regras import ContextoRegras, completar_contexto

    op = operacao_exemplo()
    op.itens.append(ItemFinanciado(id="cur1", tipo="curral", descricao="curral", cronograma_fim=date(2026, 11, 30)))
    ctx = completar_contexto(ContextoRegras(), op, Fiscalizacao(operacao=op, data_fiscalizacao=date(2026, 10, 8),
                                                                 rulebooks=["mcr_2_9@0.1.0"]))
    assert ctx.cronograma_fim == {"cur1": date(2026, 11, 30)} and ctx.data_fiscalizacao == date(2026, 10, 8)
    assert ctx.rulebooks == ["mcr-2-9"]
    explicito = completar_contexto(ContextoRegras(data_fiscalizacao=date(2026, 1, 1)), op,
                                   Fiscalizacao(operacao=op, data_fiscalizacao=date(2026, 10, 8)))
    assert explicito.data_fiscalizacao == date(2026, 1, 1)  # o que veio explícito prevalece


# --- POL-01 pelos bloqueios do rulebook ----------------------------------------------------------------------


def test_pol01_usa_os_bloqueios_do_verificador(traces):
    pol = Politica(Verificador(criar_ferramentas_falsas()))
    fis = _fis()
    res = ResultadoVerificacao(
        campos={"item:bov1:quantidade": CampoLaudo(campo="item:bov1:quantidade", status="pendente", regra_id="R")},
        bloqueios=[Bloqueio(regra_id="OP-bovinos-contagem-tolerancia", campo="item:bov1:quantidade",
                            status="pendente", falta="vídeo do lote")],
        provisoria=False,
    )
    pend = pol.pendencias_emissao(fis, res)
    assert pend == [{"regra_id": "POL-01/OP-bovinos-contagem-tolerancia", "campo": "item:bov1:quantidade",
                     "status": "pendente", "falta": "vídeo do lote", "origem": "avaliar_regras"}]
    res.bloqueios = []
    assert pol.pendencias_emissao(fis, res) == []


def test_status_do_item_agregado_nao_exige_justificativa(traces):
    pol = Politica(Verificador(criar_ferramentas_falsas()))
    res = ResultadoVerificacao(campos={
        "item:bov1": CampoLaudo(campo="item:bov1", status="divergente", regra_id="OP-agregacao-item"),
        "item:bov1:gta": CampoLaudo(campo="item:bov1:gta", status="divergente", regra_id="OP-bovinos-gta",
                                    justificativa_humana="GTA emitida antes da nota; cooperativa vai apurar"),
    }, provisoria=False)
    assert pol.pendencias_emissao(_fis(), res) == []


# --- declarações do fiscal -----------------------------------------------------------------------------------


@pytest.mark.parametrize("fala,esperado", [
    ("Declaro que não presto assistência técnica ao produtor nem tenho vínculo com empresa dele.", False),
    ("Declaro que presto assistência técnica a esse produtor.", True),
    ("Cheguei na fazenda e o produtor não estava.", None),
])
def test_declaracao_de_independencia(fala, esperado):
    assert decl.declaracao_independencia(fala) is esperado


@pytest.mark.parametrize("trecho,status", [
    ("A cerca está concluída, com mourões e cinco fios.", "ok"),
    ("A cerca ainda não está concluída, falta colocar os fios.", "divergente"),
    ("Fotografei a cerca do lado norte.", "indeterminado"),
])
def test_status_da_conclusao_da_obra(trecho, status):
    assert decl.status_conclusao(trecho) == status


def test_justificativa_so_reconhece_campo_divergente_unico():
    fis = _fis()
    fis.campos = {
        "item:bov1:quantidade": CampoLaudo(campo="item:bov1:quantidade", status="divergente", regra_id="R"),
        "item:bov1:gta": CampoLaudo(campo="item:bov1:gta", status="divergente", regra_id="R"),
    }
    assert decl.campo_justificado("Confirmo a divergência na contagem: o lote do pasto não veio.", fis) == \
        "item:bov1:quantidade"
    assert decl.campo_justificado("Confirmo a divergência na contagem e na GTA.", fis) is None  # ambíguo
    assert decl.campo_justificado("A contagem deu menos.", fis) is None  # não é justificativa
    assert decl.campo_justificado("Confirmo que recebi a GTA do vendedor.", fis) is None  # não fala da divergência


def test_politica_nega_justificativa_de_campo_verificado_e_conclusao_inventada(traces):
    pol = Politica(Verificador(criar_ferramentas_falsas()))
    fis = _fis(estado_fsm="COLETA")
    fis.campos = {"laudo:independencia_fiscal": CampoLaudo(campo="laudo:independencia_fiscal",
                                                           status="verificado", regra_id="R")}
    fala = "Declaro que não presto assistência técnica ao produtor."
    d = pol.autorizar("registrar_justificativa", fis, {"campo": "laudo:independencia_fiscal", "trecho": fala},
                      fala_atual=fala)
    assert not d.permitido and "divergente ou em abstenção" in d.motivo
    fala = "A cerca está concluída com cinco fios."
    ok = pol.autorizar("registrar_conclusao_obra", fis, {"item_id": "cerca1", "trecho": fala}, fala_atual=fala)
    inventada = pol.autorizar("registrar_conclusao_obra", fis, {"item_id": "cerca1", "trecho": "obra pronta e paga"},
                              fala_atual=fala)
    bov = pol.autorizar("registrar_conclusao_obra", fis, {"item_id": "bov1", "trecho": fala}, fala_atual=fala)
    assert ok.permitido and not inventada.permitido and not bov.permitido


# --- condutor: declarações, contingência e pedidos explícitos -------------------------------------------------


def _condutor(tmp_path, provedor) -> tuple[Condutor, str]:
    est.ids_deterministicos("integracao")
    reg = criar_ferramentas_falsas()
    cond = Condutor(provedor, repo=est.RepositorioFiscalizacoes(tmp_path), registro=reg)
    fis = cond.abrir(operacao_exemplo(), estado_fsm="COLETA", metodo="presencial")
    return cond, fis.id


def test_declaracoes_viram_evidencia_e_checagem_sem_llm(traces):
    cond, fid = _condutor(traces, None)
    r = cond.turno(fid, Evento(texto="Declaro que não presto assistência técnica ao produtor nem a empresa dele."))
    assert any(a.acao == "declaracao_independencia" for a in r.acoes)
    fis = cond.repo.carregar(fid)
    assert fis.evidencias[0].meta["assunto"] == "independencia_fiscal" and fis.evidencias[0].meta["conflito"] is False
    r = cond.turno(fid, Evento(texto="A cerca nova está concluída, com mourões e cinco fios em todo o trecho."))
    acao = next(a for a in r.acoes if a.acao == "registrar_conclusao_obra")
    assert acao.ok and acao.origem == "fallback"
    chk = cond.repo.carregar(fid).checagens[-1]
    assert chk.ferramenta == "declaracao_conclusao" and chk.status == "ok" and chk.item_id == "cerca1"


def test_tool_call_malformada_usa_saida_estruturada(traces):
    respostas = [ErroLLM("FORMATO", "500: XML syntax error"),
                 RespostaLLM(conteudo='{"acao": "responder", "argumentos": {}, "fala_para_o_fiscal": "Certo."}')]

    def llm(mensagens, ferramentas, formato):
        if formato and "alegacoes" in str(formato):
            return RespostaLLM(conteudo='{"alegacoes": []}')
        r = respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    cond, fid = _condutor(traces, ProvedorRoteirizado(llm))
    r = cond.turno(fid, Evento(texto="O que falta?"))
    assert any("contingência: saída estruturada" in a for a in r.avisos) and r.fala.endswith("Certo.")
    assert r.fala_origem == "llm" and r.fala.startswith("Falta para o rascunho")  # pendências por template


def test_sem_llm_o_pedido_explicito_de_laudo_ainda_e_atendido(traces):
    def caiu(mensagens, ferramentas, formato):
        raise ErroLLM("INDISPONIVEL", "Ollama fora do ar")

    cond, fid = _condutor(traces, ProvedorRoteirizado(caiu))
    r = cond.turno(fid, Evento(texto="Pode emitir o laudo agora."))
    acao = next(a for a in r.acoes if a.acao == "emitir_rascunho")
    # comando humano: reconhecido sem LLM (nem chega a consultá-lo) e sempre autorizado pela política
    assert acao.origem == "comando" and not acao.ok and "BLOQUEADO_POLITICA" in acao.resultado
    assert not any("LLM indisponível" in a for a in r.avisos) and "Rascunho bloqueado" in r.fala


def test_dependencia_triagem_antes_do_plano(traces):
    reg = criar_ferramentas_falsas()
    chamados = []

    class E(BaseModel):
        ref_bacen: str | None = None

    def carregar(a: E) -> Envelope:
        chamados.append(a.ref_bacen)
        return Envelope.sucesso("carregar_operacao", {"status": "ok", "motivo": "lotação alta",
                                                      "triagem": {"prioridade_nivel": "media"}})

    reg["carregar_operacao"] = Ferramenta(nome="carregar_operacao", descricao="", entrada=E, funcao=carregar)
    est.ids_deterministicos("dep")
    prov = ProvedorRoteirizado([RespostaLLM(chamadas=[ChamadaFerramenta(nome="planejar_metodo")]),
                                RespostaLLM(conteudo="Plano feito.")])
    cond = Condutor(prov, repo=est.RepositorioFiscalizacoes(traces), registro=reg)
    op = operacao_exemplo().model_copy(update={"ref_bacen": "123456789"})
    fis = cond.abrir(op)
    r = cond.turno(fis.id, Evento(texto="Por que esta operação está na amostra?"))
    assert chamados == ["123456789"] and [a.acao for a in r.acoes][:2] == ["carregar_operacao", "planejar_metodo"]
    plano = next(a for a in r.acoes if a.acao == "planejar_metodo")
    assert plano.resultado.startswith("[carregar_operacao]")  # o LLM vê por que a operação está na amostra


# --- satélite e documentos -----------------------------------------------------------------------------------


def test_ndvi_traz_todos_os_metadados_do_item_4b_e_cache_da_busca(monkeypatch, tmp_path):
    from laudo.geo import ndvi
    from laudo.geo.geometria import ler_wkt
    from laudo.rulebooks import carregar

    buscas = []
    itens = [{"id": "S2A_1", "data": "2026-08-01", "tile": "22KFG", "plataforma": "sentinel-2a", "nuvem": 1.0,
              "geometry": None, "assets": {}}]

    def buscar(*a, **k):
        buscas.append(1)
        return itens

    def ler(it, g):
        return ndvi.ObsNdvi(data=it["data"], item_id=it["id"], tile=it["tile"], plataforma=it["plataforma"],
                            nuvem_cena=1.0, n_pixels=10, n_limpos=10, frac_limpa=1.0, ndvi_p10=0.5, ndvi_p50=0.6,
                            ndvi_p90=0.7, ndvi_media=0.6)

    monkeypatch.setattr(ndvi.stac, "buscar", buscar)
    monkeypatch.setattr(ndvi.stac, "escolher_por_data", lambda its, g: its)
    monkeypatch.setattr(ndvi, "ler_observacao", ler)
    geom = ler_wkt("POLYGON ((-49.30 -16.70, -49.29 -16.70, -49.29 -16.69, -49.30 -16.69, -49.30 -16.70))")
    r1 = ndvi.serie_ndvi(geom, date(2026, 8, 1), date(2026, 8, 31), cache=tmp_path)
    r2 = ndvi.serie_ndvi(geom, date(2026, 8, 1), date(2026, 8, 31), cache=tmp_path)
    assert len(buscas) == 1 and r2["custo"]["busca_stac_do_cache"] and not r1["custo"]["busca_stac_do_cache"]
    md = r1["metadados_laudo"]
    exigidos = carregar("mcr-2-7").regra("MCR-2-7-item4-metadados-sr").efeito["campos_exigidos"]
    for chave, spec in exigidos.items():
        assert any(md.get(a) not in (None, "", [], {}) for a in spec["aceita"]), chave
    assert md["resolucao_radiometrica_bits"] == 12 and "MCR 2-7-9" in md["uso_na_fiscalizacao"]


def test_conciliacao_devolve_o_pior_status_dos_campos():
    from laudo.tools.documentos import _com_status

    d = _com_status({"campos": {"a": {"status": "ok", "motivos": []},
                                "b": {"status": "divergente", "motivos": ["GTA antes da NF-e"]}}}, "bov1")
    assert d["status"] == "divergente" and "GTA antes da NF-e" in d["motivo"] and d["item_id"] == "bov1"
    assert _com_status({"campos": {}}, "bov1")["status"] == "indeterminado"


def test_novaevidencia_preserva_recebida_em(traces):
    cond, fid = _condutor(traces, None)
    from datetime import datetime, timedelta, timezone

    quando = datetime(2026, 10, 8, 10, 32, tzinfo=timezone(timedelta(hours=-3)))
    (traces / "nfe.xml").write_bytes(b"<x/>")
    cond.turno(fid, Evento(evidencia=NovaEvidencia(tipo="nfe_xml", caminho=str(traces / "nfe.xml"),
                                                   item_id="bov1", recebida_em=quando)))
    ev = next(e for e in cond.repo.carregar(fid).evidencias if e.tipo == "nfe_xml")
    assert ev.recebida_em == quando
