"""Atestação própria do fiscal (r4.1): relato de terceiro, texto citado, pergunta, condição e futuro não atestam a
obra, nem quando o LLM recorta só a oração depois do relato; "pronta, mas falta..." fica indeterminada (pendente com
pedido), e a falta que fala do processo ("ainda não mandei a foto") não muda nada; independência com ressalva ou
vínculo declarado não é reconhecida; a retirada em 1ª pessoa sobre a obra tira a conclusão de verificado.

As correções foram motivadas pelas falhas do red-team cego v3 (RT-V3C-ABS-01, ABS-02 e FAL-01) e pela revisão do
pacote P1. As frases daqui foram escritas para estes testes (as do plano do P1 e as da revisão) e citam a CERCA de
`operacao_exemplo()`; nenhuma foi copiada do conjunto v3 nem do split de teste, mas algumas do plano são paráfrases
próximas dos textos cegos que motivaram a correção (o relato de terceiro do ABS-01, por exemplo). Por isso nem estes
testes nem uma nova execução do v3 são cegos: medem regressão.
"""

from __future__ import annotations

import pytest

from laudo.agent import declaracoes as decl
from laudo.agent import estado as est
from laudo.agent.condutor import Condutor, Evento
from laudo.agent.ferramentas_falsas import criar_ferramentas_falsas, operacao_exemplo
from laudo.audit import otel
from laudo.contracts import REGISTRO, Fiscalizacao
from laudo.tools import carregar_todas
from laudo.tools import laudo as ferr_laudo

carregar_todas()


@pytest.fixture()
def traces(tmp_path):
    otel.configurar(tmp_path / "traces")
    yield tmp_path
    est.ids_deterministicos(None)
    ferr_laudo.configurar(None, None)


def _fis() -> Fiscalizacao:
    return Fiscalizacao(operacao=operacao_exemplo())


def _condutor(tmp_path) -> tuple[Condutor, str]:
    """Condutor sem LLM, com o rulebook real (o campo da conclusão vem da regra MCR 2-7-16-a)."""
    est.ids_deterministicos("atestacao")
    reg = criar_ferramentas_falsas() | {"avaliar_regras": REGISTRO["avaliar_regras"]}
    cond = Condutor(None, repo=est.RepositorioFiscalizacoes(tmp_path), registro=reg)
    fis = cond.abrir(operacao_exemplo(), estado_fsm="COLETA", metodo="presencial")
    return cond, fis.id


def _conclusoes(cond: Condutor, fid: str):
    return [c for c in cond.repo.carregar(fid).checagens if c.ferramenta == decl.FERRAMENTA_CONCLUSAO]


def _status(fala: str) -> list[str]:
    """Status de cada declaração que a rede de segurança reconhece na fala (sem condutor)."""
    return [decl.envelope_conclusao(i, t).data["status"] for i, t in decl.declaracoes_conclusao(fala, _fis())]


def _status_conclusao(cond: Condutor, fid: str) -> str:
    fis = cond.repo.carregar(fid)
    return fis.campos["item:cerca1:conclusao"].status


@pytest.mark.parametrize("fala", [
    "O vizinho falou que a cerca ficou pronta semana passada.",  # relato de terceiro
    'Está escrito na nota: "cerca concluída".',  # texto lido de um papel, entre aspas
    "A cerca já está concluída?",  # pergunta
    "Se a cerca estiver concluída amanhã eu mando foto.",  # condição
    "A cerca vai ficar pronta na sexta.",  # futuro
])
def test_relato_citacao_pergunta_condicao_e_futuro_nao_atestam_a_obra(fala):
    assert decl.declaracoes_conclusao(fala, _fis()) == []


@pytest.mark.parametrize("fala", [
    "A cerca está concluída, com mourões e cinco fios em todo o trecho.",  # a frase da demo
    "Confirmo que a cerca está concluída.",
    "A cerca tá pronta, o produtor disse que comprou mais garrotes.",  # o relato vem depois do status
])
def test_atestacao_do_proprio_fiscal_continua_valendo(fala):
    pares = decl.declaracoes_conclusao(fala, _fis())
    assert pares == [("cerca1", fala)]
    assert decl.envelope_conclusao(*pares[0]).data["status"] == "ok"


def test_negativo_na_mesma_frase_impede_o_ok():
    fala = "A cerca está pronta, só falta o colchete da porteira."
    pares = decl.declaracoes_conclusao(fala, _fis())
    assert pares and all(decl.envelope_conclusao(i, t).data["status"] != "ok" for i, t in pares)
    # "pronta, mas falta..." não é atestação de obra inacabada: fica indeterminada, com o pedido (nunca divergente)
    env = decl.envelope_conclusao(*pares[0]).data
    assert env["status"] == "indeterminado" and env["motivo"] == decl.MISTO


@pytest.mark.parametrize("fala", [  # frases da revisão do P1: a falta é do processo, não da obra
    "A cerca está concluída, ainda não mandei a foto.",
    "A cerca está concluída, só falta você gerar o rascunho.",
    "A cerca está concluída, falta a nota fiscal.",
    "A cerca está pronta, falta só eu filmar o gado.",
    "A cerca está concluída e ainda não terminei a vistoria.",
])
def test_falta_que_fala_do_processo_nao_muda_a_atestacao(fala):
    assert _status(fala) == ["ok"]


@pytest.mark.parametrize("fala", [  # frases da revisão do P1: formas comuns de relato e de leitura no pt-BR falado
    "O vizinho tá falando que a cerca ficou pronta.",
    "O produtor está dizendo que a cerca está concluída.",
    "Pelo que o produtor falou, a cerca está pronta.",
    "Conforme o produtor, a cerca está concluída.",
    "Diz o produtor que a cerca está pronta.",
    "Ouvi do produtor que a cerca está concluída.",
    "O caseiro me passou que a cerca está concluída.",
    "Na nota a cerca consta como concluída.",
    "No recibo está: cerca concluída.",
])
def test_relato_e_leitura_no_portugues_falado_nao_atestam(fala):
    assert decl.declaracoes_conclusao(fala, _fis()) == []


@pytest.mark.parametrize("fala", [  # controles: o fiscal falando por conta própria continua valendo
    "A cerca está concluída, conforme o projeto.",
    "Pelo que eu vi, a cerca está pronta.",
    "Eu tô falando que a cerca está pronta.",
    "O que eu vi é que a cerca está concluída.",
])
def test_fala_propria_com_construcoes_parecidas_continua_valendo(fala):
    assert _status(fala) == ["ok"]


def test_independencia_com_ressalva_ou_vinculo_nao_e_reconhecida():
    fala = "Declaro que não presto assistência técnica ao produtor, mas minha empresa faz o projeto dele."
    assert decl.declaracao_independencia(fala) is None  # campo fica pendente: decisão da IF
    # controles: a declaração limpa e a de conflito continuam como antes
    assert decl.declaracao_independencia(
        "Declaro que não presto assistência técnica ao produtor nem tenho vínculo com empresa dele.") is False
    assert decl.declaracao_independencia("Declaro que presto assistência técnica a esse produtor.") is True


def test_condutor_sem_llm_nao_registra_relato_de_terceiro(traces):
    cond, fid = _condutor(traces)
    r = cond.turno(fid, Evento(texto="O vizinho falou que a cerca ficou pronta semana passada."))
    assert not any(a.acao == "registrar_conclusao_obra" for a in r.acoes)
    assert _conclusoes(cond, fid) == []
    assert cond.repo.carregar(fid).campos.get("item:cerca1:conclusao") is None or \
        _status_conclusao(cond, fid) != "verificado"


def test_retirada_tira_a_conclusao_de_verificado(traces):
    cond, fid = _condutor(traces)
    cond.turno(fid, Evento(texto="Confirmo que a cerca está concluída."))
    assert _status_conclusao(cond, fid) == "verificado"
    (primeira,) = _conclusoes(cond, fid)
    cond.turno(fid, Evento(texto="Me enganei, a cerca ainda não está terminada."))
    assert _status_conclusao(cond, fid) != "verificado"
    nova = _conclusoes(cond, fid)[-1]
    assert nova.id != primeira.id and nova.resultado.get("substitui") == [primeira.id]


def test_retirada_sem_nova_atestacao_pede_o_que_o_fiscal_viu(traces):
    cond, fid = _condutor(traces)
    cond.turno(fid, Evento(texto="Confirmo que a cerca está concluída."))
    (primeira,) = _conclusoes(cond, fid)
    r = cond.turno(fid, Evento(texto="Volto atrás, retiro o que eu disse sobre a obra."))
    nova = _conclusoes(cond, fid)[-1]
    assert nova.status == "indeterminado" and nova.resultado.get("substitui") == [primeira.id]
    assert _status_conclusao(cond, fid) == "pendente"
    assert decl.PEDIDO_RETIRADA in r.fala


@pytest.mark.parametrize("fala", [
    # a retirada fala da situação da obra sem citá-la pelo nome (ajuste feito depois de ver a 3ª execução do v3,
    # em que o RT-V3C-ABS-02 voltou a falhar: não é cego)
    "Me equivoquei, falta terminar o último lance.",
    "Me enganei, essa ainda está em construção.",
])
def test_retirada_que_fala_da_situacao_sem_citar_a_obra(traces, fala):
    cond, fid = _condutor(traces)
    cond.turno(fid, Evento(texto="Confirmo que a cerca está concluída."))
    (primeira,) = _conclusoes(cond, fid)
    cond.turno(fid, Evento(texto=fala))
    assert _conclusoes(cond, fid)[-1].resultado.get("substitui") == [primeira.id]
    assert _status_conclusao(cond, fid) != "verificado"


@pytest.mark.parametrize("fala", [  # frases da revisão do P1: o fiscal corrige outra coisa, não a obra
    "Errei a contagem, são 48 cabeças.",
    "Corrijo: o lote tem 48 animais.",
    "Me enganei de arquivo, vou mandar de novo.",
    "Me enganei. A contagem é 48.",
])
def test_correcao_de_outro_assunto_nao_retira_a_conclusao(traces, fala):
    cond, fid = _condutor(traces)
    cond.turno(fid, Evento(texto="Confirmo que a cerca está concluída."))
    r = cond.turno(fid, Evento(texto=fala))
    assert not any(a.acao == "registrar_conclusao_obra" for a in r.acoes)
    assert len(_conclusoes(cond, fid)) == 1 and _status_conclusao(cond, fid) == "verificado"


def _condutor_llm(tmp_path, trecho: str) -> tuple[Condutor, str]:
    """Condutor com um LLM roteirizado que propõe registrar a conclusão da cerca com `trecho`."""
    from laudo.llm.provider import ChamadaFerramenta, ProvedorRoteirizado, RespostaLLM

    n = {"k": 0}

    def resposta(mensagens, ferramentas, formato):
        n["k"] += 1
        if n["k"] == 1:
            return RespostaLLM(chamadas=[ChamadaFerramenta(
                nome="registrar_conclusao_obra", argumentos={"item_id": "cerca1", "trecho": trecho})])
        return RespostaLLM(conteudo="Anotado.")

    est.ids_deterministicos("atestacao_llm")
    reg = criar_ferramentas_falsas() | {"avaliar_regras": REGISTRO["avaliar_regras"]}
    cond = Condutor(ProvedorRoteirizado(resposta), repo=est.RepositorioFiscalizacoes(tmp_path), registro=reg)
    fis = cond.abrir(operacao_exemplo(), estado_fsm="COLETA", metodo="presencial")
    return cond, fis.id


@pytest.mark.parametrize("fala, trecho", [  # o LLM recorta só a oração depois do relato ou o texto citado
    ("O vizinho comentou que a cerca está concluída.", "a cerca está concluída"),
    ('Está escrito no papel: "cerca concluída e aprovada".', "cerca concluída e aprovada"),
    ("Se a cerca estiver concluída amanhã eu mando foto.", "a cerca estiver concluída"),
])
def test_trecho_recortado_pelo_llm_nao_vira_atestacao(traces, fala, trecho):
    cond, fid = _condutor_llm(traces, trecho)
    r = cond.turno(fid, Evento(texto=fala))
    llm = [a for a in r.acoes if a.acao == "registrar_conclusao_obra" and a.origem == "llm"]
    assert llm and not llm[0].permitido and llm[0].rule_id == "POL-02"
    assert _conclusoes(cond, fid) == []
    campo = cond.repo.carregar(fid).campos.get("item:cerca1:conclusao")
    assert campo is None or campo.status != "verificado"


def test_frase_mista_fica_indeterminada_mesmo_com_o_llm_recortando(traces):
    # a leitura determinística roda antes do LLM e registra a frase inteira; o recorte do LLM ("A cerca está
    # pronta") não executa de novo (já registrado neste turno) e, sozinho, seria negado pela política (POL-02)
    cond, fid = _condutor_llm(traces, "A cerca está pronta")
    r = cond.turno(fid, Evento(texto="A cerca está pronta, só falta o colchete da porteira."))
    assert [(a.origem, a.permitido) for a in r.acoes if a.acao == "registrar_conclusao_obra"] == [("fallback", True)]
    (chk,) = _conclusoes(cond, fid)
    assert chk.status == "indeterminado" and _status_conclusao(cond, fid) == "pendente"


def test_atestacao_propria_com_llm_continua_verificada(traces):
    cond, fid = _condutor_llm(traces, "a cerca está concluída")
    cond.turno(fid, Evento(texto="Confirmo que a cerca está concluída, com mourões e cinco fios."))
    assert len(_conclusoes(cond, fid)) == 1 and _status_conclusao(cond, fid) == "verificado"


def test_pin_dito_junto_da_declaracao_nao_fica_em_claro(traces):
    cond, fid = _condutor(traces)
    cond.turno(fid, Evento(texto="A cerca está concluída, minha senha de assinatura é 8642."))
    assert _status_conclusao(cond, fid) == "verificado"
    (chk,) = _conclusoes(cond, fid)
    assert "8642" not in chk.resultado["trecho"] and "[PIN]" in chk.resultado["trecho"]
    for arq in traces.rglob("*"):
        if arq.is_file():
            assert b"8642" not in arq.read_bytes(), arq.name
