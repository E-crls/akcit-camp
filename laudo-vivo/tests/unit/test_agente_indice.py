"""Índice de documentos reutilizados ligado ao produto (agent/indice.py): consulta pelo executor, registro só
na selagem, chave por operação (ref. Bacen) + item.

Dados sintéticos de `docs_apoio` (CNPJ 99.999.999, CPF 000.000, nomes TESTE); ref. Bacen `SINT-...`.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import docs_apoio as A
import pytest

from laudo.agent import estado as est
from laudo.agent import indice as AI
from laudo.agent.condutor import Condutor, Evento, NovaEvidencia, schema_para_llm
from laudo.agent.executor import preencher_argumentos
from laudo.agent.ferramentas_falsas import criar_ferramentas_falsas
from laudo.audit import otel
from laudo.contracts import REGISTRO, AprovacaoHumana, Operacao
from laudo.docs_fiscais import indice as I
from laudo.docs_fiscais import sintetico as S
from laudo.docs_fiscais.gta import QuantidadeGTA
from laudo.tools import carregar_todas
from laudo.tools import laudo as ferr_laudo

carregar_todas()
HOJE = date(2026, 9, 20)
CAMPOS_REUSO = ("documento:nfe:reuso", "documento:gta:reuso")


@pytest.fixture()
def amb(tmp_path):
    otel.configurar(tmp_path / "traces")
    (tmp_path / "nfe.xml").write_bytes(A.nfe_xml())
    (tmp_path / "gta.json").write_text(json.dumps(A.gta().model_dump(mode="json")), encoding="utf-8")
    yield tmp_path
    est.ids_deterministicos(None)
    ferr_laudo.configurar(None, None)


def _operacao(ref: str, item_id: str = "bov1") -> Operacao:
    return Operacao(ref_bacen=ref, tomador_ref=A.TOMADOR_REF, uf="GO", municipio_ibge=A.NOVA_CRIXAS[0],
                    municipio_nome=A.NOVA_CRIXAS[1], finalidade="investimento", data_contratacao=A.CONTRATACAO,
                    codigo_estabelecimento=A.COD_ESTAB, itens=[A.item().model_copy(update={"id": item_id})],
                    fonte="sintetico")


def _fiscalizar(cond: Condutor, amb: Path, ref: str, item_id: str = "bov1"):
    """Abre a fiscalização e envia a NF-e e a GTA (plano mínimo, sem LLM); devolve o estado."""
    fis = cond.abrir(_operacao(ref, item_id), data_referencia=HOJE, data_fiscalizacao=HOJE)
    for tipo, arq in (("nfe_xml", "nfe.xml"), ("gta", "gta.json")):
        cond.turno(fis.id, Evento(evidencia=NovaEvidencia(tipo=tipo, caminho=str(amb / arq), item_id=item_id)))
    return cond.repo.carregar(fis.id)


def _reuso(fis) -> dict[str, str]:
    """Status sugerido dos campos de reuso nas conciliações finais."""
    out = {}
    for c in I.conciliacoes_finais(fis.checagens):
        for campo in CAMPOS_REUSO:
            if campo in (c.resultado.get("campos") or {}):
                out[campo] = c.resultado["campos"][campo]["status_campo_sugerido"]
    return out


def _selar(fis) -> None:
    """O que `Condutor.assinar` faz antes de `selar`: assinatura humana e etapa SELADO."""
    fis.aprovacoes.append(AprovacaoHumana(papel="fiscal", nome_ref="FISCAL TESTE", hash_assinado="0" * 64))
    fis.estado_fsm = "SELADO"


# ------------------------------------------------------------------------------------------- consulta


def test_executor_preenche_indice_e_operacao_do_estado(tmp_path):
    fis = est.RepositorioFiscalizacoes(tmp_path / "f").criar(_operacao("SINT-2026-000101"))
    for nome in ("conciliar_nfe", "conciliar_gta"):
        args = preencher_argumentos(REGISTRO[nome], fis, {}, hoje=HOJE, dir_dados=tmp_path)
        assert args["indice_documentos"] == str(tmp_path / "indices" / "documentos.jsonl")
        assert args["operacao_ref"] == "SINT-2026-000101"  # a operação, não o id da fiscalização
        sem = preencher_argumentos(REGISTRO[nome], fis, {}, hoje=HOJE)
        assert "indice_documentos" not in sem and "operacao_ref" not in sem  # sem diretório: desligado
    outra = preencher_argumentos(REGISTRO["avaliar_regras"], fis, {}, hoje=HOJE, dir_dados=tmp_path)
    assert "indice_documentos" not in outra  # só quem tem o campo recebe


def test_llm_nao_ve_nem_escolhe_o_indice(amb):
    for nome in ("conciliar_nfe", "conciliar_gta"):
        props = schema_para_llm(REGISTRO[nome])["function"]["parameters"]["properties"]
        assert not {"indice_documentos", "operacao_ref"} & set(props)
    cond = Condutor(None, repo=est.RepositorioFiscalizacoes(amb / "fiscalizacoes"), hoje=HOJE)
    limpos, fora = cond._args_do_llm("conciliar_nfe", {"evidencia_id": "ev_x", "operacao_ref": "OUTRA",
                                                       "indice_documentos": "/tmp/vazio.jsonl"})
    assert limpos == {"evidencia_id": "ev_x"} and fora == ["indice_documentos", "operacao_ref"]


# ------------------------------------------------------------------------------- produto, ponta a ponta


def test_reuso_em_outra_operacao_diverge_e_refiscalizacao_nao(amb):
    """MCR 2-7-6-b e 2-7-7-d (análogo NT 2024.003 ZF04-20): o laudo selado da operação A registra a NF-e e a
    GTA; a operação B com os mesmos documentos diverge; a refiscalização de A (outra fiscalização) é ok."""
    cond = Condutor(None, repo=est.RepositorioFiscalizacoes(amb / "fiscalizacoes"), hoje=HOJE)
    a = _fiscalizar(cond, amb, "SINT-2026-000201")
    assert _reuso(a) == dict.fromkeys(CAMPOS_REUSO, "verificado")  # índice vazio: consultado, nada consta
    assert {c.ferramenta: c.status for c in I.conciliacoes_finais(a.checagens)} == {
        "conciliar_nfe": "ok", "conciliar_gta": "ok"}
    indice = AI.caminho_indice(cond.dir_dados)
    assert not indice.exists()  # conciliar nunca grava
    assert AI.registrar_na_selagem(a, cond.dir_dados) == 0  # não selada: nada entra
    _selar(a)
    assert AI.registrar_na_selagem(a, cond.dir_dados) == 2  # NF-e + GTA do item bov1
    assert AI.registrar_na_selagem(a, cond.dir_dados) == 0  # selar de novo não duplica

    b = _fiscalizar(cond, amb, "SINT-2026-000202")
    assert _reuso(b) == dict.fromkeys(CAMPOS_REUSO, "divergente")
    assert b.campos["item:bov1:comprovante_nfe"].status == "divergente"
    assert "já comprovou outra operação" in b.campos["item:bov1:gta"].motivo

    refisc = _fiscalizar(cond, amb, "SINT-2026-000201")
    assert refisc.id != a.id and _reuso(refisc) == dict.fromkeys(CAMPOS_REUSO, "verificado")

    _selar(b)
    assert AI.registrar_na_selagem(b, cond.dir_dados) == 0  # o que divergiu (reuso) não entra no índice
    linhas = [json.loads(x) for x in indice.read_text(encoding="utf-8").splitlines()]
    assert {e["operacao"] for e in linhas} == {I.hash_operacao("SINT-2026-000201")}
    assert "SINT-2026-000201" not in indice.read_text(encoding="utf-8")  # só HMAC


def test_mesma_operacao_outro_item_fica_indeterminado(amb):
    """Política de duplicata: o documento do item bov1 apresentado para outro item da mesma operação não
    comprova os dois (indeterminado: o fiscal confirma a qual item pertence)."""
    cond = Condutor(None, repo=est.RepositorioFiscalizacoes(amb / "fiscalizacoes"), hoje=HOJE)
    a = _fiscalizar(cond, amb, "SINT-2026-000301")
    _selar(a)
    assert AI.registrar_na_selagem(a, cond.dir_dados) == 2
    outro = _fiscalizar(cond, amb, "SINT-2026-000301", item_id="bov2")
    assert _reuso(outro) == dict.fromkeys(CAMPOS_REUSO, "pendente")


def test_documento_enviado_por_engano_nao_entra_na_selagem(amb):
    """A GTA de outro lote enviada por engano deixa a conciliação divergente (quantidade): selada assim mesmo,
    a NF-e (ok) entra e a GTA não; a conciliação substituída também não."""
    (amb / "gta_errada.json").write_text(
        json.dumps(A.gta(quantidade=12, numero="777001").model_dump(mode="json")), encoding="utf-8")
    cond = Condutor(None, repo=est.RepositorioFiscalizacoes(amb / "fiscalizacoes"), hoje=HOJE)
    fis = cond.abrir(_operacao("SINT-2026-000401"), data_referencia=HOJE, data_fiscalizacao=HOJE)
    for tipo, arq in (("nfe_xml", "nfe.xml"), ("gta", "gta_errada.json")):
        cond.turno(fis.id, Evento(evidencia=NovaEvidencia(tipo=tipo, caminho=str(amb / arq), item_id="bov1")))
    fis = cond.repo.carregar(fis.id)
    finais = {c.ferramenta: c.status for c in I.conciliacoes_finais(fis.checagens)}
    assert finais["conciliar_nfe"] == "ok" and finais["conciliar_gta"] != "ok"
    _selar(fis)
    assert AI.registrar_na_selagem(fis, cond.dir_dados) == 1
    linhas = [json.loads(x) for x in AI.caminho_indice(cond.dir_dados).read_text(encoding="utf-8").splitlines()]
    assert [e["tipo"] for e in linhas] == ["nfe"]


def test_falha_de_disco_nao_derruba_a_selagem(amb):
    cond = Condutor(None, repo=est.RepositorioFiscalizacoes(amb / "fiscalizacoes"), hoje=HOJE)
    a = _fiscalizar(cond, amb, "SINT-2026-000501")
    _selar(a)
    bloqueio = amb / "bloqueado"
    (bloqueio / "indices" / "documentos.jsonl").mkdir(parents=True)  # diretório no lugar do arquivo
    assert AI.registrar_na_selagem(a, bloqueio) == 0


def test_sem_ref_bacen_nao_liga_a_consulta(tmp_path):
    fis = est.RepositorioFiscalizacoes(tmp_path / "f").criar(_operacao("SINT-2026-000601"))
    fis.operacao.ref_bacen = " "
    assert AI.argumentos_de_consulta(fis, tmp_path) == {}
    assert AI.argumentos_de_consulta(fis, None) == {}


# ------------------------------------------- cadeia do produto: Condutor.assinar → selar → índice → consulta

# contagem por vídeo e plano falsos (sem GPU); conciliar_nfe e conciliar_gta reais (consultam o índice)
VIDEO = {"status": "ok", "contagem": 40, "intervalo": [39, 41]}


def _condutor_ate_o_selo(amb: Path) -> Condutor:
    reg = criar_ferramentas_falsas({f"curral_{i}.mp4": {"contar_bovinos_video": VIDEO} for i in ("bov1", "bov2")})
    reg["conciliar_nfe"], reg["conciliar_gta"] = REGISTRO["conciliar_nfe"], REGISTRO["conciliar_gta"]
    for i in ("bov1", "bov2"):
        (amb / f"curral_{i}.mp4").write_bytes(f"curral {i}".encode())
    return Condutor(None, repo=est.RepositorioFiscalizacoes(amb / "fiscalizacoes"), registro=reg, hoje=HOJE)


def _fiscalizar_itens(cond: Condutor, amb: Path, ref: str, itens, nfe: str = "nfe.xml", gta: str = "gta.json"):
    """Abre a fiscalização da operação `ref` e envia NF-e, GTA e vídeo de cada item; devolve o id."""
    op = _operacao(ref).model_copy(update={"itens": itens})
    fis = cond.abrir(op, data_referencia=HOJE, data_fiscalizacao=HOJE)
    for it in itens:
        for tipo, arq in (("nfe_xml", nfe), ("gta", gta), ("video", f"curral_{it.id}.mp4")):
            ev = NovaEvidencia(tipo=tipo, caminho=str(amb / arq), item_id=it.id)
            cond.turno(fis.id, Evento(evidencia=ev))
    return fis.id


def _assinar(cond: Condutor, fis_id: str):
    """O caminho do produto: emitir o rascunho, pedir a assinatura e assinar com hash e PIN (POL-03)."""
    r = cond.turno(fis_id, Evento(texto="Pode emitir o laudo."))
    assert r.etapa == "RASCUNHO", r.pendencias
    cond.turno(fis_id, Evento(texto="Manda para a minha assinatura."))
    rasc = cond.ultimo_laudo(fis_id)
    ok = cond.assinar(fis_id, "fiscal", "FISCAL TESTE", hash_confirmado=rasc["hash_raiz"], pin_ok=True)
    assert ok.etapa == "SELADO", ok.fala
    return ok


def _linhas_do_indice(cond: Condutor) -> list[dict]:
    return [json.loads(x) for x in AI.caminho_indice(cond.dir_dados).read_text(encoding="utf-8").splitlines()]


def test_cadeia_do_produto_assinar_registra_e_a_operacao_seguinte_consulta(amb):
    """Revisão da onda 3: sem chamar `registrar_na_selagem` à mão. `Condutor.assinar` → `tools/laudo.py::selar`
    → `registrar_na_selagem` grava no mesmo arquivo que o executor consulta; a operação seguinte com os mesmos
    documentos diverge (MCR 2-7-6-b e 2-7-7-d) e a refiscalização da operação selada fica ok."""
    cond = _condutor_ate_o_selo(amb)
    a = _fiscalizar_itens(cond, amb, "SINT-2026-000701", [A.item()])
    indice = AI.caminho_indice(cond.dir_dados)
    assert not indice.exists()
    r = cond.turno(a, Evento(texto="Pode emitir o laudo."))
    assert r.etapa == "RASCUNHO" and not indice.exists()  # rascunho não registra: só a selagem
    _assinar(cond, a)
    assert {(e["tipo"], e["item_id"]) for e in _linhas_do_indice(cond)} == {("nfe", "bov1"), ("gta", "bov1")}
    assert {e["operacao"] for e in _linhas_do_indice(cond)} == {I.hash_operacao("SINT-2026-000701")}

    b = cond.repo.carregar(_fiscalizar_itens(cond, amb, "SINT-2026-000702", [A.item()]))
    assert _reuso(b) == dict.fromkeys(CAMPOS_REUSO, "divergente")
    refisc = cond.repo.carregar(_fiscalizar_itens(cond, amb, "SINT-2026-000701", [A.item()]))
    assert _reuso(refisc) == dict.fromkeys(CAMPOS_REUSO, "verificado")


def test_nfe_de_dois_lotes_refiscalizada_nao_vira_pendencia(amb):
    """Revisão da onda 3: uma NF-e (e uma GTA) de dois lotes comprova os dois itens no laudo selado. Na
    refiscalização da mesma operação, cada item fica ok (o documento já comprovou ESTE item); antes, cada um
    acusava "um documento não comprova dois itens" (conciliação indeterminada, campo pendente)."""
    lotes = [S.ItemSintetico("NOV", "NOVILHA NELORE 13-24 MESES", "01022990", "5101", "CB", 40, 3150.0),
             S.ItemSintetico("GAR", "GARROTE NELORE 13-24 MESES", "01022990", "5101", "CB", 40, 3150.0)]
    (amb / "nfe_2lotes.xml").write_bytes(A.nfe_xml(itens=lotes))
    guia = A.gta(quantidades=[QuantidadeGTA(sexo="F", faixa_etaria="13-24", quantidade=40),
                              QuantidadeGTA(sexo="M", faixa_etaria="13-24", quantidade=40)], total=80)
    (amb / "gta_2lotes.json").write_text(json.dumps(guia.model_dump(mode="json")), encoding="utf-8")
    itens = [A.item(), A.item(categoria="garrote").model_copy(update={"id": "bov2"})]
    cond = _condutor_ate_o_selo(amb)
    docs = {"nfe": "nfe_2lotes.xml", "gta": "gta_2lotes.json"}
    a = _fiscalizar_itens(cond, amb, "SINT-2026-000711", itens, **docs)
    _assinar(cond, a)
    assert len(_linhas_do_indice(cond)) == 4  # NF-e e GTA, cada uma nos dois itens

    refisc = cond.repo.carregar(_fiscalizar_itens(cond, amb, "SINT-2026-000711", itens, **docs))
    finais = I.conciliacoes_finais(refisc.checagens)
    assert {(c.ferramenta, c.item_id, c.status) for c in finais} == {
        (f, i, "ok") for f in ("conciliar_nfe", "conciliar_gta") for i in ("bov1", "bov2")}
    for c in finais:
        campo = next(v for k, v in c.resultado["campos"].items() if k in CAMPOS_REUSO)
        assert campo["status_campo_sugerido"] == "verificado" and "refiscalização" in campo["motivos"][0]
    assert _assinar(cond, refisc.id).etapa == "SELADO"  # nada bloqueia a refiscalização
    assert len(_linhas_do_indice(cond)) == 4  # selar de novo a mesma operação não duplica
