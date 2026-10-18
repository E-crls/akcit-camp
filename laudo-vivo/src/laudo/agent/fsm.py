"""Máquina de estados da fiscalização e ações permitidas por estado.

`BRIEFING → COLETA ⇄ CHECAGEM → CONCILIACAO → REVISAO → RASCUNHO → ASSINATURA → SELADO`

- Lacuna ou abstenção devolve para COLETA com pedido específico (CHECAGEM/CONCILIACAO/REVISAO → COLETA).
- RASCUNHO → REVISAO quando o rascunho precisa ser refeito; ASSINATURA → REVISAO quando o humano rejeita.
- ASSINATURA → SELADO só por ação humana (`assinar`), nunca pelo LLM (POL-03).

A lista de ações por estado é a *allowlist* da política (default-deny): o que não está aqui é negado.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from enum import StrEnum

from laudo.contracts import Ferramenta, Fiscalizacao


class Etapa(StrEnum):
    BRIEFING = "BRIEFING"
    COLETA = "COLETA"
    CHECAGEM = "CHECAGEM"
    CONCILIACAO = "CONCILIACAO"
    REVISAO = "REVISAO"
    RASCUNHO = "RASCUNHO"
    ASSINATURA = "ASSINATURA"
    SELADO = "SELADO"


E = Etapa
TRANSICOES: dict[Etapa, frozenset[Etapa]] = {
    E.BRIEFING: frozenset({E.COLETA}),
    E.COLETA: frozenset({E.CHECAGEM}),
    E.CHECAGEM: frozenset({E.COLETA, E.CONCILIACAO}),
    E.CONCILIACAO: frozenset({E.COLETA, E.REVISAO}),
    E.REVISAO: frozenset({E.COLETA, E.RASCUNHO}),
    E.RASCUNHO: frozenset({E.REVISAO, E.ASSINATURA}),
    E.ASSINATURA: frozenset({E.REVISAO, E.SELADO}),
    E.SELADO: frozenset(),
}
# Transições que só um humano pode disparar (fora do alcance do LLM).
TRANSICOES_HUMANAS: frozenset[tuple[Etapa, Etapa]] = frozenset({(E.ASSINATURA, E.SELADO)})

# Ferramentas do REGISTRO (por nome) permitidas em cada estado.
_CHECAGENS_DE_CAMPO = {
    "integridade_foto",
    "geofence",
    "contar_bovinos_video",
    "conciliar_nfe",
    "conciliar_gta",
    "serie_ndvi",
    "checar_lotacao",
}
_CONSULTA = {"explicar_regra"}  # só leitura: pode em qualquer etapa aberta
# Ferramentas que só o plano determinístico do condutor dispara (foto/PDF de documento → leitura por VLM com
# validação; residual lido pela fiscal → completação validada; alegações da fala × checagens; foto da benfeitoria
# → classificação da estrutura pelo VLM). A política as permite; o LLM não as recebe como tools (o upload e a fala
# já dizem o que fazer, e as requisições ao LLM ficam iguais).
FERRAMENTAS_DO_PLANO = frozenset({"ler_documento_foto", "conciliar_alegacoes", "completar_leitura_documento",
                                  "classificar_foto"})
# `triar_carteira` é da tela de carteira (escolher a amostra), não de uma fiscalização já aberta: dentro dela,
# a triagem da própria operação vem de `carregar_operacao`.
FERRAMENTAS_POR_ETAPA: dict[Etapa, frozenset[str]] = {
    E.BRIEFING: frozenset(
        {
            "carregar_operacao",
            "planejar_metodo",
            "serie_ndvi",
            "checar_lotacao",
            "avaliar_regras",
            "registrar_ocorrencia",
        }
        | _CONSULTA
    ),
    # Checagens remotas (satélite, lotação, triagem) não dependem de upload: valem também na COLETA.
    E.COLETA: frozenset(
        {"registrar_ocorrencia", "emitir_rascunho", "serie_ndvi", "checar_lotacao", "carregar_operacao",
         "conciliar_alegacoes"}
        | _CONSULTA
    ),
    E.CHECAGEM: frozenset(_CHECAGENS_DE_CAMPO | FERRAMENTAS_DO_PLANO | {"registrar_ocorrencia"} | _CONSULTA),
    E.CONCILIACAO: frozenset(
        {"conciliar_nfe", "conciliar_gta", "checar_lotacao", "avaliar_regras", "registrar_ocorrencia",
         "conciliar_alegacoes"}
        | _CONSULTA
    ),
    E.REVISAO: frozenset({"avaliar_regras", "emitir_rascunho", "registrar_ocorrencia", "conciliar_alegacoes"}
                         | _CONSULTA),
    E.RASCUNHO: frozenset({"emitir_rascunho", "registrar_ocorrencia"} | _CONSULTA),
    E.ASSINATURA: frozenset({"registrar_ocorrencia"}),
    E.SELADO: frozenset(),
}

# Ações internas do condutor (não estão no REGISTRO; expostas ao LLM como tools).
ACOES_INTERNAS = frozenset(
    {
        "pedir_evidencia",
        "registrar_justificativa",
        "registrar_conclusao_obra",
        "avancar_etapa",
        "solicitar_assinatura",
    }
)
ACOES_INTERNAS_POR_ETAPA: dict[Etapa, frozenset[str]] = {
    E.BRIEFING: frozenset({"pedir_evidencia", "avancar_etapa"}),
    E.COLETA: frozenset(
        {"pedir_evidencia", "registrar_justificativa", "registrar_conclusao_obra", "avancar_etapa"}
    ),
    E.CHECAGEM: frozenset({"pedir_evidencia", "registrar_conclusao_obra", "avancar_etapa"}),
    E.CONCILIACAO: frozenset({"registrar_justificativa", "registrar_conclusao_obra", "avancar_etapa"}),
    E.REVISAO: frozenset(
        {"pedir_evidencia", "registrar_justificativa", "registrar_conclusao_obra", "avancar_etapa"}
    ),
    E.RASCUNHO: frozenset({"registrar_justificativa", "solicitar_assinatura", "avancar_etapa"}),
    E.ASSINATURA: frozenset(),
    E.SELADO: frozenset(),
}
# Ações que o agente nunca executa, em estado nenhum (POL-03).
ACOES_HUMANAS = frozenset({"assinar", "selar", "aprovar", "rejeitar_rascunho"})
# Ações que só um comando humano dispara (fala explícita reconhecida sem LLM, `intencao.comando_humano`, ou
# botão da interface). Continuam na allowlist do estado para o humano, mas o LLM não as recebe em estado nenhum
# (`nomes_permitidos`) e a política nega quando a origem é o LLM (POL-03).
ACOES_POR_COMANDO_HUMANO = frozenset({"emitir_rascunho", "solicitar_assinatura"})


class TransicaoInvalida(Exception):
    pass


def etapa(fis: Fiscalizacao) -> Etapa:
    return Etapa(fis.estado_fsm)


def pode_transitar(de: Etapa | str, para: Etapa | str, humano: bool = False) -> bool:
    de, para = Etapa(de), Etapa(para)
    if para not in TRANSICOES[de]:
        return False
    return humano or (de, para) not in TRANSICOES_HUMANAS


def transitar(fis: Fiscalizacao, para: Etapa | str, humano: bool = False) -> Etapa:
    de = etapa(fis)
    para = Etapa(para)
    if de == para:
        return para
    if not pode_transitar(de, para, humano=humano):
        raise TransicaoInvalida(f"{de} → {para} não é permitida")
    fis.estado_fsm = para.value
    return para


def caminho(de: Etapa | str, para: Etapa | str, humano: bool = False) -> list[Etapa] | None:
    """Menor sequência de transições legais de `de` até `para` (sem incluir `de`)."""
    de, para = Etapa(de), Etapa(para)
    if de == para:
        return []
    fila: deque[tuple[Etapa, list[Etapa]]] = deque([(de, [])])
    vistos = {de}
    while fila:
        atual, rota = fila.popleft()
        for prox in sorted(TRANSICOES[atual]):
            if prox in vistos or not pode_transitar(atual, prox, humano=humano):
                continue
            if prox == para:
                return rota + [prox]
            vistos.add(prox)
            fila.append((prox, rota + [prox]))
    return None


def ir_para(fis: Fiscalizacao, para: Etapa | str, humano: bool = False) -> list[Etapa]:
    """Percorre o menor caminho legal até `para`, aplicando cada transição. Devolve os passos."""
    rota = caminho(fis.estado_fsm, para, humano=humano)
    if rota is None:
        raise TransicaoInvalida(f"sem caminho legal de {fis.estado_fsm} até {para}")
    for passo in rota:
        transitar(fis, passo, humano=humano)
    return rota


def acoes_permitidas(e: Etapa | str) -> frozenset[str]:
    e = Etapa(e)
    return FERRAMENTAS_POR_ETAPA[e] | ACOES_INTERNAS_POR_ETAPA[e]


def ferramentas_permitidas(e: Etapa | str, registro: dict[str, Ferramenta]) -> list[Ferramenta]:
    """Ferramentas do registro liberadas no estado (as ausentes do registro simplesmente não aparecem)."""
    return [registro[n] for n in sorted(FERRAMENTAS_POR_ETAPA[Etapa(e)] - FERRAMENTAS_DO_PLANO) if n in registro]


def nomes_permitidos(e: Etapa | str, registro: Iterable[str]) -> list[str]:
    """Ações oferecidas ao LLM no estado (sem as que só um comando humano dispara)."""
    reg = set(registro)
    e = Etapa(e)
    return sorted(((FERRAMENTAS_POR_ETAPA[e] & reg) | ACOES_INTERNAS_POR_ETAPA[e]) - ACOES_POR_COMANDO_HUMANO
                  - FERRAMENTAS_DO_PLANO)
