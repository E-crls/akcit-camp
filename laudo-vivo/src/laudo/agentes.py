"""Registro dos agentes do Laudo Vivo (arquitetura v2): quem age, quando, com que modelo e com que ferramentas.

Um **Condutor** supervisiona a visita e delega a **especialistas** (Visão, Documentos, Território), cada um com seu
modelo, suas ferramentas e o direito de se abster. A **Triagem** age antes do campo. O **Auditor** revisa o
rascunho antes da assinatura e não muda nenhum status. Os **guarda-corpos** não são agentes: a política (sem IA)
autoriza ou nega cada ação, o verificador (sem IA, `avaliar_regras`) dá o status de cada item citando o MCR 2-7, e o
selo (cadeia de hash) e a assinatura com PIN fecham o laudo. Quem conversa não confere.

Este módulo só descreve: ele nomeia os papéis que o caminho atual (condutor, política, verificador, ferramentas) já
tem e não muda nenhum deles. As ferramentas são as reais de `laudo.tools`; `agente_da_ferramenta` diz de quem é
cada uma (a tela mostra o especialista de cada ação, e o teste confere que toda ferramenta tem dono).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Agente(BaseModel):
    id: str
    nome: str
    curto: str  # rótulo do chip na conversa
    papel: str
    quando_age: str
    modelo: str
    ferramentas: list[str] = Field(default_factory=list)
    guarda_corpo: str
    saida: str
    novo: bool = False  # acrescentado na v2 e ainda não avaliado no golden set


class GuardaCorpo(BaseModel):
    id: str
    nome: str
    ia: bool = False
    faz: str
    ferramentas: list[str] = Field(default_factory=list)


AGENTES: tuple[Agente, ...] = (
    Agente(
        id="triagem",
        nome="Agente de Triagem e Plano",
        curto="Triagem",
        papel="Escolhe o que fiscalizar na carteira, confere a lotação e planeja o método de cada item.",
        quando_age="antes do campo",
        modelo="regras + LLM que explica",
        ferramentas=["triar_carteira", "checar_lotacao", "planejar_metodo", "carregar_operacao"],
        guarda_corpo="A prioridade não é indício de irregularidade; o método vem da regra.",
        saida="Operações priorizadas com o motivo e o método de fiscalização de cada item.",
    ),
    Agente(
        id="condutor",
        nome="Agente Condutor de Campo",
        curto="Condutor",
        papel="Supervisor: conversa com a fiscal, pede só a próxima prova e delega aos especialistas.",
        quando_age="durante a visita",
        modelo="LLM local qwen3.5:4b (na nuvem da demo, Gemini 3.1 Flash-Lite) + Whisper para a voz",
        ferramentas=["conciliar_alegacoes", "registrar_ocorrencia", "explicar_regra", "emitir_rascunho"],
        guarda_corpo="Política default-deny (POL-00 a POL-09) em cada ação.",
        saida="A próxima ação para a fiscal e o rascunho do laudo quando a política deixa.",
    ),
    Agente(
        id="visao",
        nome="Agente de Visão",
        curto="Visão",
        papel="Conta os animais no vídeo do brete e classifica a foto do bem.",
        quando_age="vídeo do brete, foto",
        modelo="YOLOX + rastreamento; VLM para classificar a foto",
        ferramentas=["contar_bovinos_video", "classificar_foto"],
        guarda_corpo="Se abstém com oclusão ou incerteza; mostra os quadros-chave.",
        saida="Contagem com intervalo e quadros-chave, ou abstenção com o motivo.",
    ),
    Agente(
        id="documentos",
        nome="Agente de Documentos",
        curto="Documentos",
        papel="Lê a nota, a GTA e o XML e confere com a operação.",
        quando_age="foto da nota, GTA, XML",
        modelo="VLM + conferência determinística (dígito verificador, somas, datas)",
        ferramentas=["ler_documento_foto", "completar_leitura_documento", "conciliar_nfe", "conciliar_gta"],
        guarda_corpo="Pede só o campo que faltou (residual).",
        saida="Campos lidos e conferidos, com o que não validou pedido de volta.",
    ),
    Agente(
        id="territorio",
        nome="Agente de Território",
        curto="Território",
        papel="Confere a gleba por satélite e a foto pelo GPS.",
        quando_age="gleba, foto com GPS",
        modelo="Sentinel-2/NDVI, geometria",
        ferramentas=["serie_ndvi", "geofence", "integridade_foto"],
        guarda_corpo="Inconclusivo vira pendência, não \"ok\".",
        saida="Série de NDVI, foto dentro ou fora da gleba e integridade da foto.",
    ),
    Agente(
        id="auditor",
        nome="Agente Auditor",
        curto="Auditor",
        papel="Revisa o rascunho antes da assinatura: aponta riscos e lacunas por item, citando o item.",
        quando_age="antes da assinatura",
        modelo="LLM com saída estruturada (o mesmo do condutor)",
        ferramentas=[],  # lê o rascunho, as provas e o resultado do verificador; não chama ferramenta
        guarda_corpo="Não muda nenhum status; a fiscal decide.",
        saida="Parecer: itens em risco com o motivo, as evidências e a pergunta para a fiscal.",
        novo=True,
    ),
)

GUARDA_CORPOS: tuple[GuardaCorpo, ...] = (
    GuardaCorpo(
        id="politica",
        nome="Política",
        faz="Autoriza ou nega cada ação do agente (default-deny, POL-00 a POL-09).",
    ),
    GuardaCorpo(
        id="verificador",
        nome="Verificador",
        faz="Dá o status de cada item citando o MCR 2-7.",
        ferramentas=["avaliar_regras"],
    ),
    GuardaCorpo(
        id="selo",
        nome="Selo",
        faz="Cadeia de hash: o laudo selado confere com o rascunho assinado.",
    ),
    GuardaCorpo(
        id="assinatura",
        nome="Assinatura",
        faz="A fiscal assina com o PIN; o agente não assina.",
    ),
)

_POR_FERRAMENTA: dict[str, str] = {f: a.id for a in AGENTES for f in a.ferramentas} | {
    f: g.id for g in GUARDA_CORPOS for f in g.ferramentas
}


def agente(id_: str) -> Agente | None:
    return next((a for a in AGENTES if a.id == id_), None)


def agente_da_ferramenta(nome: str) -> str | None:
    """O agente (ou o guarda-corpo, para `avaliar_regras`) dono da ferramenta; None se ninguém a declara."""
    return _POR_FERRAMENTA.get(nome)


def ferramentas_por_agente() -> dict[str, str]:
    return dict(_POR_FERRAMENTA)


def descrever() -> dict[str, Any]:
    """Agentes e guarda-corpos para a tela e para `GET /api/agentes`."""
    return {
        "agentes": [a.model_dump() for a in AGENTES],
        "guarda_corpos": [g.model_dump() for g in GUARDA_CORPOS],
        "ferramenta_agente": ferramentas_por_agente(),
    }
