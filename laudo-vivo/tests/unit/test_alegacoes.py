"""`conciliar_alegacoes`: fala livre da fiscal × checagens, status por alegação (nunca muda campo do laudo)."""

from __future__ import annotations

from datetime import date

import pytest

from laudo.agent import estado as est
from laudo.agent.condutor import Condutor, RespostaTurno
from laudo.contracts import Fiscalizacao, ItemFinanciado, Operacao
from laudo.llm.provider import ProvedorRoteirizado
from laudo.tools import alegacoes as A

BOV = ItemFinanciado(id="bov1", tipo="bovinos", descricao="29 vacas leiteiras", quantidade=29, unidade="cabeca",
                     valor_rs=87_000.0, categoria_animal="vaca leiteira")
CERCA = ItemFinanciado(id="cerca1", tipo="cerca", descricao="1.200 m de cerca", quantidade=1200, unidade="m")
ITENS = [BOV, CERCA]
VIDEO = {"ferramenta": "contar_bovinos_video", "status": "ok", "item_id": "bov1",
         "resultado": {"contagem": 12, "intervalo": [12, 17]}}
NFE = {"ferramenta": "conciliar_nfe", "status": "ok", "item_id": "bov1",
       "resultado": {"totais": {"cabecas": 29, "valor_bovinos_rs": 87_000.0}}}


def _al(trecho: str, grandeza: str, valor: float, item_id: str | None = "bov1", unidade: str | None = None) -> dict:
    return {"id": "alg_1", "trecho": trecho, "grandeza": grandeza, "valor": valor, "item_id": item_id,
            "unidade": unidade, "ponteiro": {"evidencia_id": "ev_fala", "inicio": 0, "fim": len(trecho)}}


def _st(al: dict, checagens: list[dict] | None = None) -> dict:
    r = A.conciliar([al], ITENS, [VIDEO, NFE] if checagens is None else checagens)
    return r["alegacoes"][0]


def test_contagem_declarada_fora_do_intervalo_do_video_e_divergente():
    r = _st(_al("contei 29 vacas", "quantidade", 29))
    assert r["status"] == "divergente" and r["regra_id"] == "OP-alegacao-declaracao-x-evidencia"
    assert "12 [12–17]" in r["motivo"] and r["ponteiro"]["evidencia_id"] == "ev_fala"


def test_contagem_dentro_do_intervalo_confere():
    assert _st(_al("contei 15 vacas", "quantidade", 15))["status"] == "confere"


def test_sem_contagem_conclusiva_compara_com_a_nf_e_sem_nada_fica_sem_evidencia():
    abst = {**VIDEO, "status": "indeterminado"}
    assert _st(_al("contei 29 vacas", "quantidade", 29), [abst, NFE])["status"] == "confere"
    assert _st(_al("contei 28 vacas", "quantidade", 28), [abst, NFE])["status"] == "divergente"
    assert _st(_al("contei 29 vacas", "quantidade", 29), [])["status"] == "sem_evidencia"


def test_cerca_menor_que_o_projeto_e_pendencia_e_contradiz_obra_concluida():
    r = _st(_al("fizeram só 800 m de cerca", "comprimento", 800, "cerca1"))
    assert r["status"] == "pendente" and "67%" in r["motivo"]
    concl = {"ferramenta": "declaracao_conclusao", "status": "ok", "item_id": "cerca1", "resultado": {}}
    assert _st(_al("fizeram só 800 m de cerca", "comprimento", 800, "cerca1"), [concl])["status"] == "divergente"
    assert _st(_al("a cerca tem os 1.200 metros", "comprimento", 1200, "cerca1"))["status"] == "confere"


@pytest.mark.parametrize("trecho,grandeza,valor", [
    ("ele comprou também 2 tratores", "quantidade", 2),
    ("fez um galpão de 300 metros quadrados", "area", 300),
    ("tem uns 6 bezerros que nasceram aqui", "quantidade", 6),  # categoria diferente da financiada
    ("comprou 15 garrotes por fora", "quantidade", 15),
])
def test_item_nao_financiado_vira_registro(trecho, grandeza, valor):
    assert _st(_al(trecho, grandeza, valor))["status"] == "registro"


@pytest.mark.parametrize("trecho,grandeza,valor,unidade", [
    ("o produtor tem 3 filhos", "quantidade", 3, None),
    ("a estrada tem uns 30 km de chão", "comprimento", 30, "km"),
    ("cheguei às 8,5 vacas", "quantidade", 8.5, None),  # hora mal normalizada grudada no substantivo
])
def test_numero_sem_objeto_financiado_nunca_vira_divergencia(trecho, grandeza, valor, unidade):
    item = "cerca1" if grandeza == "comprimento" else "bov1"
    assert _st(_al(trecho, grandeza, valor, item, unidade))["status"] == "registro"


def test_objeto_do_trecho_manda_sobre_o_item_sugerido():
    # o extrator sugeriu bov1, mas o trecho fala de trator: não pode virar contagem do lote
    r = _st(_al("2 tratores novos", "quantidade", 2, "bov1"))
    assert r["status"] == "registro" and r["item_id"] is None
    # "contei 29 no curral": curral é lugar, não o objeto contado
    assert _st(_al("contei 29 no curral", "quantidade", 29, None))["status"] == "divergente"


def test_ferramenta_le_a_fiscalizacao_e_agrega_status():
    fis = Fiscalizacao(operacao=Operacao(ref_bacen="SINT-1", itens=ITENS))
    fis.alegacoes = [_al("contei 29 vacas", "quantidade", 29), _al("comprou 2 tratores", "quantidade", 2)]
    env = A.conciliar_alegacoes(A.EntradaConciliarAlegacoes(fiscalizacao={
        **fis.model_dump(mode="json"), "checagens": [VIDEO, NFE]}))
    assert env.ok and env.data["status"] == "divergente"
    assert env.data["contagem_status"] == {"confere": 0, "divergente": 1, "pendente": 0, "registro": 1,
                                           "sem_evidencia": 0}
    vazio = A.conciliar_alegacoes(A.EntradaConciliarAlegacoes(itens=ITENS))
    assert not vazio.ok and vazio.error.code == "SEM_DADOS"


def test_condutor_aceita_numero_por_extenso_na_alegacao_do_llm(tmp_path):
    """Antes da rodada 2 a alegação "vinte e nove vacas" era descartada (sem algarismo no trecho)."""
    texto = "contei no olho vinte e nove vacas no curral"
    prov = ProvedorRoteirizado([{"conteudo": '{"alegacoes": [{"grandeza": "quantidade", "valor": 29, '
                                             '"unidade": "cabeca", "item_id": "bov1", '
                                             '"trecho": "vinte e nove vacas"}]}'}])
    cond = Condutor(prov, repo=est.RepositorioFiscalizacoes(tmp_path), registro={}, hoje=date(2026, 10, 8))
    fis = Fiscalizacao(operacao=Operacao(ref_bacen="SINT-1", itens=ITENS))
    resp = RespostaTurno(fiscalizacao_id=fis.id, turno=1, etapa=fis.estado_fsm, fala="")
    als = cond._extrair_alegacoes(fis, texto, "ev_fala", resp)
    assert [(a["valor"], a["item_id"], a["trecho"]) for a in als] == [(29.0, "bov1", "vinte e nove vacas")]
    assert als[0]["ponteiro"]["inicio"] == texto.index("vinte")
    assert A.conciliar(als, ITENS, [VIDEO])["alegacoes"][0]["status"] == "divergente"
