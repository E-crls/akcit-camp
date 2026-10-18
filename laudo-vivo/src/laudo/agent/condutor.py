"""Condutor: o laço do agente.

A cada turno recebe um evento (fala do fiscal vinda do ASR ou texto, e/ou upload de evidência) e:
1. registra o evento na cadeia de hash (a fala vira evidência "declaracao"; o upload, evidência do seu tipo);
   fala que é ruído (ou com confiança baixa do ASR) só gera um pedido de repetição;
2. aplica as guardas determinísticas da política sobre a fala (POL-03 assinatura, POL-06 injeção,
   POL-07 pressão forte) e sobre textos de dado (OCR/documento: POL-06). Guarda acionada responde por template;
   pressão incerta só pede esclarecimento (sem ocorrência). Comando humano explícito (emitir o rascunho,
   mandar para assinatura) é reconhecido sem LLM: essas duas ações nunca são decisão do LLM;
3. extrai **alegações** numéricas da fala (saída estruturada com JSON Schema; ponteiro para o trecho); se há
   um **residual** pendente (campos de DANFE/GTA que a foto não validou) e a fala traz esses valores, o turno é o
   da completação: `completar_leitura_documento` revalida com as regras determinísticas, sem LLM;
4. pede ao LLM a próxima ação entre as permitidas no estado da FSM (tool calling nativo; contingência por
   saída estruturada `{acao, argumentos, fala_para_o_fiscal}`), autoriza cada ação na política, executa pelo
   REGISTRO e registra a checagem; se o LLM falhar ou não chamar a ferramenta óbvia, um plano mínimo
   determinístico cobre;
5. o verificador independente recalcula os status; a FSM avança (ou volta para COLETA com pedido);
6. a fala é **fatos por template** (resultado de checagens e ações, `fatos.py`) + **condução do LLM**, que passa
   pela consistência semântica (POL-09) e pelo grounding numérico (POL-05); se falhar, vale o template.

O condutor nunca assina: `assinar()` é chamado pela interface, como ação humana, com confirmação do hash.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from laudo import privacidade
from laudo.agent import declaracoes as decl
from laudo.agent import estado as est
from laudo.agent import fatos as fatos_mod
from laudo.agent import fsm, intencao
from laudo.agent.executor import (
    CAMPOS_DE_EVIDENCIA,
    DOCUMENTOS_CUMULATIVOS,
    ExecutorFerramentas,
    preencher_argumentos,
    resumo_envelope,
    sobre_evidencia,
)
from laudo.agent.pii import mascarar, mascarar_obj
from laudo.agent.politica import Decisao, Politica
from laudo.agent.verificador import ResultadoVerificacao, Verificador, extrair_numeros
from laudo.audit import otel
from laudo.audit import selo as selo_mod
from laudo.audit.cofre import Cofre
from laudo.contracts import (
    GPS,
    REGISTRO,
    AprovacaoHumana,
    CodigoErro,
    Envelope,
    Ferramenta,
    Fiscalizacao,
    Operacao,
    TipoEvidencia,
    hash_entrada,
)
from laudo.docs_fiscais import residual as residual_mod
from laudo.llm.provider import (
    ChamadaFerramenta,
    ErroLLM,
    ProvedorLLM,
    RespostaLLM,
    chamadas_do_texto,
    pedir_json,
)

_PROMPTS = Path(__file__).resolve().parent / "prompts"


def carregar_prompt(nome: str) -> tuple[str, str]:
    """Devolve (texto, versão). A versão é `<arquivo>@<sha8>` e vai para os spans."""
    p = _PROMPTS / nome
    texto = p.read_text(encoding="utf-8").strip()
    return texto, f"{p.stem}@{hash_entrada(texto)[:8]}"


# ---------------------------------------------------------------------------
# Tipos de entrada e saída do turno
# ---------------------------------------------------------------------------


class NovaEvidencia(BaseModel):
    tipo: TipoEvidencia
    caminho: str | None = None
    conteudo_texto: str | None = None  # conteúdo pequeno inline (testes, declarações)
    sha256: str | None = None  # hash calculado na captura
    gps: GPS | None = None
    capturada_em: datetime | None = None
    recebida_em: datetime | None = None  # momento do recebimento no app (padrão: agora)
    item_id: str | None = None
    lote: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class Evento(BaseModel):
    texto: str = ""
    origem: Literal["fala_fiscal", "asr", "texto"] = "fala_fiscal"
    evidencia: NovaEvidencia | None = None
    # Confiança do ASR (0–1, `speech.asr.Transcricao.confianca`); abaixo de `intencao.LIMIAR_CONFIANCA_ASR` o
    # agente pede para repetir em vez de interpretar.
    confianca_asr: float | None = None
    # Residual digitado na interface (campo → valor), para os campos que a foto do DANFE/GTA não validou.
    residual: dict[str, str] | None = None


class AcaoExecutada(BaseModel):
    acao: str
    argumentos: dict[str, Any] = Field(default_factory=dict)
    origem: str = "llm"  # llm | fallback | guarda | humano
    permitido: bool = True
    rule_id: str = ""
    ok: bool | None = None
    resultado: str = ""
    checagem_id: str | None = None
    span_id: str = ""
    dados: dict[str, Any] | None = None


class RespostaTurno(BaseModel):
    fiscalizacao_id: str
    turno: int
    etapa: str
    fala: str
    fala_origem: str = "template"  # llm (fatos por template + condução do LLM) | template | guarda
    fatos: list[str] = Field(default_factory=list)  # frases de resultado geradas por template (fatos.py)
    acoes: list[AcaoExecutada] = Field(default_factory=list)
    alegacoes: list[dict[str, Any]] = Field(default_factory=list)
    ocorrencias: list[str] = Field(default_factory=list)
    pendencias: list[dict[str, Any]] = Field(default_factory=list)
    transicoes: list[str] = Field(default_factory=list)
    laudo: dict[str, Any] | None = None
    avisos: list[str] = Field(default_factory=list)
    llm: dict[str, Any] = Field(default_factory=dict)
    # Pedido do residual pendente depois do turno (campos de DANFE/GTA a ler no papel), para a interface.
    residual: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Ações internas expostas ao LLM e esquemas
# ---------------------------------------------------------------------------


class ArgsPedirEvidencia(BaseModel):
    tipo_evidencia: str = Field(description="video | foto | nfe_xml | gta | documento")
    item_id: str | None = Field(default=None, description="id do item financiado")
    instrucao: str = Field(description="como capturar, em uma frase (ex.: filme o lote passando no corredor)")


class ArgsJustificativa(BaseModel):
    campo: str = Field(description="campo do laudo, ex.: item:bov1:quantidade")
    trecho: str = Field(description="trecho literal da fala do fiscal neste turno que justifica")


class ArgsConclusao(BaseModel):
    item_id: str = Field(description="id do item de benfeitoria (cerca, curral, galpão)")
    trecho: str = Field(description="trecho literal da fala do fiscal neste turno sobre a obra")


class ArgsAvancar(BaseModel):
    para: str = Field(description="etapa de destino")


class ArgsVazio(BaseModel):
    pass


_INTERNAS: dict[str, tuple[str, type[BaseModel]]] = {
    "pedir_evidencia": (
        ("Pede ao fiscal uma evidência específica que falta (use as pendências do contexto)."),
        ArgsPedirEvidencia,
    ),
    "registrar_justificativa": (
        (
            "Registra a justificativa do fiscal (trecho literal da fala) para um campo "
            "divergente ou em abstenção."
        ),
        ArgsJustificativa,
    ),
    "registrar_conclusao_obra": (
        (
            "Registra o que o fiscal atestou sobre a conclusão de uma benfeitoria (cerca, curral, galpão), "
            "com o trecho literal da fala dele neste turno."
        ),
        ArgsConclusao,
    ),
    "avancar_etapa": (
        (
            "Pede a transição da fiscalização para outra etapa (raramente necessário: as etapas "
            "avançam sozinhas)."
        ),
        ArgsAvancar,
    ),
    "solicitar_assinatura": (
        (
            "Use quando o fiscal pedir para assinar ou enviar para assinatura: envia o rascunho "
            "já emitido para a assinatura humana (o agente não assina)."
        ),
        ArgsVazio,
    ),
}

# Campos que o condutor preenche a partir do estado (o LLM não precisa nem deve copiá-los).
_AUTO = {
    "caminho",
    "arquivo",
    "caminho_arquivo",
    "caminho_video",
    "caminho_foto",
    "caminho_xml",
    "caminho_documento",
    "video",
    "foto",
    "xml",
    "path",
    "video_path",
    "foto_path",
    "xml_path",
    "caminhos",
    "nfe_caminhos",
    "xmls",
    "nfe_xmls",
    "gtas",
    "gleba_wkt",
    "poligono_wkt",
    "wkt",
    "poligono",
    "glebas_wkt",
    "fiscalizacao_id",
    "fiscalizacao",
    "operacao",
    "lat",
    "lon",
    "precisao_m",
    "ponto",
    "gps",
    "gps_app",
    "meta",
    "exif",
    "sha256",
    "itens",
    "ref_bacen",
    "municipio_ibge",
    "municipio_nome",
    "uf",
    "uf_operacao",
    "area_ha",
    "area_financiada_ha",
    "data_contratacao",
    "data_fiscalizacao",
    "data_referencia",
    "inicio",
    "fim",
    "valor_rs",
    "item",
    "item_financiado",
    "quantidade_esperada",
    "quantidade_financiada",
    "categoria_animal",
    "cabecas",
    "compra",
    "lote",
    "evidencia_ids",
    "capturada_em",
    "recebida_em",
    "metodo",
    # índice de documentos de laudos selados (agent/indice.py): caminho e operação vêm do estado, nunca do LLM
    "indice_documentos",
    "operacao_ref",
}
_CAMPOS_DE_EVIDENCIA = CAMPOS_DE_EVIDENCIA
# Disjuntor do LLM: falhas de transporte (o modelo não respondeu no tempo, o servidor sumiu)
# desligam o LLM no resto do turno e, no perfil de palco, nos turnos seguintes até passar
# `espera_disjuntor_s`. Erro de formato ou HTTP 4xx não: o modelo respondeu, e a contingência (saída
# estruturada, template) já cobre.
_CODIGOS_DISJUNTOR = frozenset({"TIMEOUT", "INDISPONIVEL"})
_RX_ID_EVIDENCIA = re.compile(r"^ev_[0-9A-Za-z_]+$")
_DO_PROVEDOR = "provedor"
# Opcionais que o LLM pode decidir; os demais (parâmetros técnicos) ficam com o padrão da ferramenta.
_OPCIONAIS_LLM = {
    "item_id",
    "texto_redigido",
    "evidencia_ref",
    "regra_id",
    "municipio",
    "finalidade",
    "tipo_empreendimento",
    "instituicao",
    "limite",
    "prioridade_minima",
    "so_com_poligono",
    "descricao",
    "tipo",
}

# Plano mínimo determinístico por tipo de evidência (quando o LLM não chama a ferramenta óbvia).
PLANO_MINIMO: dict[str, list[str]] = {
    "video": ["contar_bovinos_video"],
    "foto": ["integridade_foto", "geofence"],
    "nfe_xml": ["conciliar_nfe"],
    "gta": ["conciliar_gta"],
}


_TIPOS_ESTRUTURA = ("cerca", "curral", "galpao")


def plano_da_evidencia(fis: Fiscalizacao, ev, classificar_fotos: bool = False) -> list[str]:
    """Plano mínimo do upload. Foto/PDF de DANFE ou GTA (tipo `documento`): leitura por VLM com validação
    determinística (`ler_documento_foto`) e, depois dela, a conciliação do tipo que foi lido. Foto de cerca,
    curral ou galpão (com `classificar_fotos`): depois da integridade e do geofence, o VLM confere se a foto mostra
    a estrutura do item (`classificar_foto`, MCR-2-7-item16-benfeitorias-conclusao), uma vez por foto."""
    if ev.tipo == "foto":
        item = next((i for i in fis.operacao.itens if i.id == ev.meta.get("item_id")), None)
        extra = ["classificar_foto"] if classificar_fotos and item is not None and item.tipo in _TIPOS_ESTRUTURA \
            else []
        return PLANO_MINIMO["foto"] + extra
    if ev.tipo != "documento":
        return PLANO_MINIMO.get(ev.tipo, [])
    leitura = next((c for c in reversed(fis.checagens)
                    if c.ferramenta == "ler_documento_foto" and ev.id in c.evidencias and c.status != "erro"), None)
    if leitura is None or not leitura.resultado.get("documento"):
        return ["ler_documento_foto"]
    conc = {"danfe": "conciliar_nfe", "gta": "conciliar_gta"}.get(str(leitura.resultado.get("tipo_documento")))
    return ["ler_documento_foto"] + ([conc] if conc else [])


class ResidualPendente(BaseModel):
    """Campos de um DANFE/GTA lido por foto que ainda esperam a fiscal (o pedido mais recente)."""

    pedido: residual_mod.PedidoResidual
    checagem_id: str
    evidencia_id: str
    item_id: str | None = None

    model_config = {"arbitrary_types_allowed": True}

    def para_interface(self) -> dict[str, Any]:
        return {**self.pedido.model_dump(), "evidencia_id": self.evidencia_id, "item_id": self.item_id,
                "checagem_id": self.checagem_id}


_LEITURAS = ("ler_documento_foto", residual_mod.FERRAMENTA)


def residual_pendente(fis: Fiscalizacao) -> ResidualPendente | None:
    """Pedido do residual que ainda vale: o da leitura (ou completação) mais recente de cada documento (tipo e
    item), se ela não validou tudo e se não chegou depois o documento estruturado (XML da NF-e, e-GTA) do item."""
    ultimas: dict[tuple[str, str | None], Any] = {}
    for c in fis.checagens:
        if c.ferramenta in _LEITURAS and c.status != "erro" and c.resultado.get("tipo_documento") in ("danfe", "gta"):
            ultimas[(str(c.resultado["tipo_documento"]), c.item_id)] = c
    ordem = {e.id: i for i, e in enumerate(fis.evidencias)}
    melhor = None
    for (tipo, item), c in ultimas.items():
        ped = c.resultado.get("pedido_residual")
        if c.status == "ok" or not ped or not c.evidencias:
            continue
        estruturado = "nfe_xml" if tipo == "danfe" else "gta"
        depois = [e for e in fis.evidencias if e.tipo == estruturado and e.meta.get("item_id") in (None, item)
                  and ordem[e.id] > ordem.get(c.evidencias[0], -1)]
        if depois:
            continue
        if melhor is None or fis.checagens.index(c) > fis.checagens.index(melhor):
            melhor = c
    if melhor is None:
        return None
    try:
        pedido = residual_mod.PedidoResidual.model_validate(melhor.resultado["pedido_residual"])
    except ValidationError:
        return None
    return ResidualPendente(pedido=pedido, checagem_id=melhor.id, evidencia_id=melhor.evidencias[0],
                            item_id=melhor.item_id)


# Ferramentas cujo resultado não vira Checagem (consulta, laudo, ocorrência). A triagem vira checagem: a
# prioridade dela entra no plano de método (executor.prioridade_da_triagem).
_NAO_CHECAGEM = {"emitir_rascunho", "registrar_ocorrencia", "explicar_regra", "avaliar_regras"}
# Pré-requisito determinístico: o plano de método usa a prioridade da triagem da operação.
_DEPENDENCIAS = {"planejar_metodo": "carregar_operacao"}
# Emitir o rascunho e enviar para assinatura: só por comando humano (intencao.comando_humano), nunca pelo LLM.
# Pergunta "o que falta?": as pendências vêm por template (as mesmas que a política usa para bloquear).
_RX_O_QUE_FALTA = re.compile(r"\b(?:o que (?:ainda )?falta|falta o que|o que (?:ainda )?precisa|pendencias?|"
                             r"o que (?:ainda )?esta faltando|falta (?:alguma|mais) (?:coisa|algo))\b")
_NIVEL_FALADO = {"alta": "alta", "media": "média", "baixa": "baixa", "sem_sinal": "sem sinal"}
_METODO_FALADO = {"autofiscalizacao_assistida": "autofiscalização assistida", "presencial": "presencial",
                  "documental": "documental", "remoto": "sensoriamento remoto"}
_RX_HASH = re.compile(r"\b[0-9a-f]{12,64}\b")
_CHAVES_TEXTO_DADO = (
    "texto_ocr",
    "ocr",
    "transcricao",
    "texto",
    "observacao",
    "observacoes",
    "descricao",
    "informacoes_complementares",
    "infCpl",
)


def schema_para_llm(ferr: Ferramenta) -> dict[str, Any]:
    """Esquema da ferramenta como o LLM vê: sem os campos que o condutor preenche do estado; com
    `evidencia_id`/`item_id` quando a ferramenta trabalha sobre uma evidência ou item."""
    s = json.loads(json.dumps(ferr.entrada.model_json_schema()))
    props: dict[str, Any] = s.get("properties", {})
    req = set(s.get("required", []))
    removidos = {k for k in props if k in _AUTO}
    precisa_ev = bool(removidos & _CAMPOS_DE_EVIDENCIA)
    tecnicos = {k for k in props if k not in removidos and k not in req and k not in _OPCIONAIS_LLM}
    for k in removidos | tecnicos:
        props.pop(k, None)
    req -= removidos
    if precisa_ev and "evidencia_id" not in props:
        props["evidencia_id"] = {"type": "string", "description": "id da evidência no contexto (ev_...)"}
        req.add("evidencia_id")
    if (precisa_ev or "item" in removidos or "quantidade_esperada" in removidos) and "item_id" not in props:
        props["item_id"] = {"type": "string", "description": "id do item financiado"}
    s["properties"] = props
    s["required"] = sorted(req)
    s.pop("title", None)
    return {
        "type": "function",
        "function": {"name": ferr.nome, "description": ferr.descricao, "parameters": s},
    }


def schema_interna(nome: str) -> dict[str, Any]:
    desc, modelo = _INTERNAS[nome]
    p = modelo.model_json_schema()
    p.pop("title", None)
    return {"type": "function", "function": {"name": nome, "description": desc, "parameters": p}}


class DecisaoEstruturada(BaseModel):
    """Contingência quando o tool calling nativo falha: uma ação por passo, validada por schema."""

    acao: str
    argumentos: dict[str, Any] = Field(default_factory=dict)
    fala_para_o_fiscal: str = ""


class Alegacao(BaseModel):
    grandeza: Literal["quantidade", "comprimento", "area", "valor", "data", "outro"]
    valor: float
    unidade: str | None = None
    item_id: str | None = None
    trecho: str


class ListaAlegacoes(BaseModel):
    alegacoes: list[Alegacao] = Field(default_factory=list)


def esquema_decisao(acoes: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "acao": {"type": "string", "enum": sorted(set(acoes) | {"responder"})},
            "argumentos": {"type": "object"},
            "fala_para_o_fiscal": {"type": "string"},
        },
        "required": ["acao", "argumentos", "fala_para_o_fiscal"],
    }


# ---------------------------------------------------------------------------
# Extração determinística de alegações (reserva quando o LLM falha)
# ---------------------------------------------------------------------------

_RX_QTD = re.compile(
    r"(\d[\d.,]*)\s*(cabe[cç]as?|bois|garrotes?|novilh[oa]s?|vacas?|bezerr[oa]s?|animais|"
    r"reses|bovinos)",
    re.IGNORECASE,
)
_RX_COMP = re.compile(r"(\d[\d.,]*)\s*(m|metros?)\b", re.IGNORECASE)
_RX_AREA = re.compile(r"(\d[\d.,]*)\s*(ha|hectares?)\b", re.IGNORECASE)
_NUM_PALAVRA = re.compile(
    r"\b(um|uma|dois|duas|tr[eê]s|quatro|cinco|seis|sete|oito|nove|dez|onze|doze|vinte|"
    r"trinta|quarenta|cinquenta|sessenta|setenta|oitenta|noventa|cem|cento|duzent\w+|"
    r"trezent\w+|quatrocent\w+|quinhent\w+|mil)\b",
    re.IGNORECASE,
)


def _norm(t: str) -> str:
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode("ascii").lower()


def localizar_trecho(texto: str, trecho: str) -> tuple[int, int] | None:
    """Posição do trecho no texto original (tolerante a caixa, acentos e espaços)."""
    if not trecho.strip():
        return None
    i = texto.find(trecho)
    if i >= 0:
        return i, i + len(trecho)
    nt, ntr = _norm(texto), re.sub(r"\s+", " ", _norm(trecho)).strip()
    nt_esp = re.sub(r"\s+", " ", nt)
    j = nt_esp.find(ntr)
    if j < 0:
        return None
    # mapeia de volta (texto normalizado tem o mesmo comprimento salvo espaços múltiplos)
    if nt_esp == nt:
        return j, j + len(ntr)
    return None


def alegacoes_regex(texto: str, operacao: Operacao) -> list[Alegacao]:
    def item_de(tipos: tuple[str, ...]) -> str | None:
        return next((i.id for i in operacao.itens if i.tipo in tipos), None)

    saida = []
    for rx, grandeza, unidade, tipos in (
        (_RX_QTD, "quantidade", "cabeca", ("bovinos",)),
        (_RX_COMP, "comprimento", "m", ("cerca",)),
        (_RX_AREA, "area", "ha", ("pastagem", "lavoura")),
    ):
        for m in rx.finditer(texto):
            nums, _, _ = extrair_numeros(m.group(1))
            if not nums:
                continue
            corte = max(texto.rfind(x, 0, m.start()) for x in ".,;!?:") + 1
            ini = corte + re.search(r"(?:\S+\s+){0,3}$", texto[corte : m.start()]).start()
            saida.append(
                Alegacao(
                    grandeza=grandeza,
                    valor=nums[0].valor,
                    unidade=unidade,  # type: ignore[arg-type]
                    item_id=item_de(tipos),
                    trecho=texto[ini : m.end()],
                )
            )
    return saida


def _data_do_laudo(laudo: dict[str, Any] | None) -> date | None:
    """Data de referência gravada no laudo (rascunho emitido); None se ausente ou inválida."""
    try:
        return date.fromisoformat(str((laudo or {}).get("data_referencia")))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Condutor
# ---------------------------------------------------------------------------


class Condutor:
    def __init__(
        self,
        provedor: ProvedorLLM | None,
        repo: est.RepositorioFiscalizacoes | None = None,
        registro: dict[str, Ferramenta] | None = None,
        politica: Politica | None = None,
        modo: Literal["tools", "estruturado"] = "tools",
        max_passos: int = 4,
        hoje: date | None = None,
        extrair_alegacoes_llm: bool = True,
        classificar_fotos: bool | None = None,
        espera_disjuntor_s: float | None | str = _DO_PROVEDOR,
        relogio: Callable[[], float] = time.monotonic,
    ):
        self.provedor = provedor
        # Disjuntor: por quanto tempo o LLM fica de fora depois de TIMEOUT/servidor fora. Padrão: o do
        # provedor (perfil de palco: 60 s; escritório, lote, replay e roteiro: sem disjuntor entre turnos).
        self.espera_disjuntor_s: float | None = (
            getattr(provedor, "espera_disjuntor_s", None) if espera_disjuntor_s == _DO_PROVEDOR
            else espera_disjuntor_s  # type: ignore[assignment]
        )
        self._relogio = relogio
        self._disjuntor_ate: float | None = None
        self._disjuntor_codigo = ""
        self.repo = repo or est.RepositorioFiscalizacoes()
        self.registro = REGISTRO if registro is None else registro
        self.executor = ExecutorFerramentas(self.registro)
        self.verificador = Verificador(self.registro, ExecutorFerramentas(self.registro))
        self.politica = politica or Politica(self.verificador, self.registro)
        self.modo = modo
        self.max_passos = max_passos
        self.hoje = hoje
        self.extrair_alegacoes_llm = extrair_alegacoes_llm
        # VLM no plano (classificar a foto da benfeitoria): ligado quando há modelo local (o modo sem LLM, braço
        # determinístico da avaliação, não usa modelo nenhum)
        self.classificar_fotos = provedor is not None if classificar_fotos is None else classificar_fotos
        self.dir_dados = self.repo.dir.parent  # índice de fotos e quadros-chave ficam junto do estado
        # cofre da fiscalização (crypto-shredding): chave de acesso inteira e leituras brutas do VLM, cifradas
        self.cofre = Cofre(self.dir_dados / "chaves")
        self._resp_turno: RespostaTurno | None = None
        self._ev_fala_id: str | None = None
        self._upload_turno = None  # evidência recebida no turno corrente (POL-09: "recebi a foto")
        self._llm_falhou = False
        self.prompt_condutor, self.versao_prompt = carregar_prompt("condutor.v3.md")
        self.prompt_alegacoes, self.versao_prompt_alegacoes = carregar_prompt("alegacoes.v1.md")
        from laudo.tools import laudo as ferr_laudo  # registra emitir_rascunho/registrar_ocorrencia

        ferr_laudo.configurar(self.repo, self.politica)
        for nome in ("emitir_rascunho", "registrar_ocorrencia"):
            if nome not in self.registro and nome in REGISTRO:
                self.registro[nome] = REGISTRO[nome]

    # -- ciclo de vida -------------------------------------------------------
    def abrir(self, operacao: Operacao, **campos: Any) -> Fiscalizacao:
        # referência pública ao documento do tomador (sha256:<hex>, sem sal) não é guardada: vira o hash com o sal
        # desta instalação (laudo.privacidade) antes de entrar no estado
        ref = operacao.tomador_ref
        if not ref.startswith("hmac:") and (h := privacidade.hash_referencia(ref)):
            operacao = operacao.model_copy(update={"tomador_ref": f"hmac:{h}"})
        fis = self.repo.criar(operacao, **campos)
        with (
            otel.contexto_fiscalizacao(fis.id),
            otel.span("agente.abrir", **{"laudo.ref_bacen": operacao.ref_bacen}),
        ):
            pass
        return fis

    def turno(self, fis_id: str, evento: Evento) -> RespostaTurno:
        fis = self.repo.carregar(fis_id)
        n = len(self.repo.ler_conversa(fis_id)) + 1
        with (
            otel.contexto_fiscalizacao(fis.id),
            otel.span(
                "agente.turno",
                **{
                    "laudo.turno": n,
                    "laudo.etapa_inicial": fis.estado_fsm,
                    "laudo.prompt.versao": self.versao_prompt,
                },
            ) as s,
        ):
            try:
                with self._orcamento_llm():
                    r = self._turno(fis, evento, n)
            except (est.ViolacaoAppendOnly, fsm.TransicaoInvalida, ValueError, OSError) as e:
                # Falha interna: nada do turno é persistido (o estado em memória é descartado).
                otel.marcar_erro(s, f"{type(e).__name__}: {e}")
                r = RespostaTurno(
                    fiscalizacao_id=fis_id,
                    turno=n,
                    etapa=self.repo.carregar(fis_id).estado_fsm,
                    fala="Tive um erro interno e nada foi alterado. Pode repetir?",
                    avisos=[mascarar(f"{type(e).__name__}: {e}")[:300]],
                )
            otel.definir(
                s,
                **{
                    "laudo.etapa_final": r.etapa,
                    "laudo.fala_origem": r.fala_origem,
                    "laudo.n_acoes": len(r.acoes),
                },
            )
        self.repo.anexar_conversa(
            fis.id,
            {
                "turno": n,
                "fiscal": evento.texto,
                "evidencia": evento.evidencia.tipo if evento.evidencia else None,
                "agente": r.fala,
                "etapa": r.etapa,
                "acoes": [f"{a.acao}:{'ok' if a.permitido else 'negado'}" for a in r.acoes],
            },
        )
        return r

    # -- turno -----------------------------------------------------------------
    def _turno(self, fis: Fiscalizacao, evento: Evento, n: int) -> RespostaTurno:
        resp = RespostaTurno(fiscalizacao_id=fis.id, turno=n, etapa=fis.estado_fsm, fala="")
        if fis.estado_fsm == fsm.Etapa.SELADO:
            d = self.politica.autorizar("evento", fis)
            resp.fala, resp.fala_origem = (
                ("Esta fiscalização está selada; nada pode ser alterado. Correção exige nova fiscalização."),
                "guarda",
            )
            resp.acoes.append(
                AcaoExecutada(
                    acao="evento",
                    origem="guarda",
                    permitido=False,
                    rule_id=d.rule_id,
                    resultado=d.motivo,
                    span_id=d.span_id,
                )
            )
            return resp
        texto = (evento.texto or "").strip()
        n_oc = len(fis.ocorrencias)
        ev_fala = None
        if texto:
            texto_mascarado = mascarar(texto)
            meta_fala: dict[str, Any] = {"texto": texto_mascarado, "origem": evento.origem, "turno": n}
            conflito = decl.declaracao_independencia(texto)
            if conflito is not None:  # MCR 2-7-15: declaração do fiscal, lida de forma determinística
                meta_fala.update(assunto="independencia_fiscal", conflito=conflito)
            # o sha256 da evidência é o do texto já mascarado (igual ao meta.texto): PIN, CPF e telefone não
            # saem por força bruta do hash. Texto sem dado pessoal fica com os bytes e o sha256 do original.
            ev_fala = est.adicionar_evidencia(fis, "declaracao", conteudo=texto_mascarado.encode("utf-8"),
                                              meta=meta_fala)
            if conflito is not None:
                resp.acoes.append(
                    AcaoExecutada(
                        acao="declaracao_independencia",
                        origem="fallback",
                        ok=True,
                        rule_id="MCR-2-7-item15-independencia-fiscal",
                        resultado=(
                            "Declaração de independência do fiscal registrada (MCR 2-7-15)."
                            if not conflito
                            else "Declaração registra conflito: fiscal vedado pelo MCR 2-7-15."
                        ),
                    )
                )
        self._resp_turno, self._ev_fala_id = resp, (ev_fala.id if ev_fala else None)
        # disjuntor aberto (falha recente do LLM, perfil de palco): o turno inteiro segue sem LLM
        self._llm_falhou = self.provedor is not None and self._disjuntor_aberto()
        ev_nova = self._registrar_upload(fis, evento.evidencia, resp) if evento.evidencia else None
        self._upload_turno = ev_nova

        # 0. ruído ou confiança baixa do ASR: pede para repetir e não interpreta nada (nem alegação, nem ação)
        if texto and (ruido := intencao.eh_ruido(texto, evento.confianca_asr)):
            span = otel.registrar_decisao("ASR-ruido", "esclarecer", "fala", ruido)
            resp.acoes.append(AcaoExecutada(acao="pedir_repeticao", origem="esclarecimento", rule_id="ASR-ruido",
                                            resultado=ruido, span_id=span))
            if ev_nova is None:
                resp.fala, resp.fala_origem = intencao.PEDIDO_REPETICAO, "template"
                return self._fechar(fis, resp, n_oc, recalcular=False)
            resp.avisos.append(f"fala ignorada ({ruido}); só a evidência foi processada")
            texto = ""

        # 1. guardas determinísticas da fala. Pressão forte bloqueia e grava ocorrência; pressão incerta só pede
        # esclarecimento (nada vai para a cadeia imutável).
        decisoes: list[Decisao] = []
        esclarecer = ""
        if texto:
            decisoes = self.politica.avaliar_fala(texto, fis, houve_nova_evidencia=ev_nova is not None)
            bloqueios = [d for d in decisoes if not d.permitido]
            for d in decisoes:
                if d.ocorrencia:
                    est.registrar_ocorrencia(
                        fis,
                        d.ocorrencia,
                        f"{d.rule_id}: {d.motivo}",
                        evidencia_ref=ev_fala.id if ev_fala else None,
                    )
                if d.esclarecer:
                    esclarecer = d.esclarecer
                    resp.acoes.append(AcaoExecutada(acao="pedir_esclarecimento", origem="esclarecimento",
                                                    rule_id=d.rule_id, resultado=d.motivo, span_id=d.span_id))
                    continue
                resp.acoes.append(
                    AcaoExecutada(
                        acao="guarda",
                        origem="guarda",
                        permitido=False,
                        rule_id=d.rule_id,
                        resultado=d.motivo,
                        span_id=d.span_id,
                    )
                )
            if bloqueios:
                if ev_nova is None:
                    resp.fala, resp.fala_origem = self._fala_guarda(bloqueios), "guarda"
                    return self._fechar(fis, resp, n_oc, recalcular=False)
                resp.avisos.append(self._fala_guarda(bloqueios))

        # Residual pendente (campos de DANFE/GTA que a foto não validou) e a fala (ou o formulário) traz esses
        # valores: turno de completação, determinístico (sem LLM, sem alegação: é leitura do papel)
        if ev_nova is None and (texto or evento.residual) and not any(not d.permitido for d in decisoes):
            pend = residual_pendente(fis) if residual_mod.FERRAMENTA in self.registro else None
            respostas = residual_mod.interpretar_resposta(pend.pedido, texto, evento.residual) if pend else {}
            if pend is not None and respostas:
                return self._turno_residual(fis, pend, respostas, resp, n_oc, texto)

        # Comando humano explícito (emitir o rascunho, enviar para assinatura): reconhecido sem LLM; o LLM não
        # tem essas ações em estado nenhum.
        comando = intencao.comando_humano(texto) if texto and not any(not d.permitido for d in decisoes) else None
        if esclarecer and comando is None and ev_nova is None:
            resp.fala, resp.fala_origem = esclarecer, "template"
            return self._fechar(fis, resp, n_oc, recalcular=False)

        # 2. alegações da fala (pedido de alterar valor, mesmo incerto, não é alegação)
        if texto and ev_fala is not None and not any(d.rule_id == "POL-07" for d in decisoes):
            resp.alegacoes = self._extrair_alegacoes(fis, texto, ev_fala.id, resp)

        # 3. declarações literais do fiscal (conclusão de obra, justificativa de divergência): reconhecidas de
        # forma determinística antes do LLM, que só conduz (o agente não redige atestação)
        if texto and not any(d.rule_id == "POL-07" for d in decisoes):
            self._declaracoes(fis, texto, resp)

        # 4. upload em etapa avançada volta para COLETA e entra em CHECAGEM
        if ev_nova is not None:
            self._ir(fis, fsm.Etapa.CHECAGEM, resp)

        # 5. decisão do LLM (com política em cada ação), vendo o status já recalculado. Turno de comando humano
        # é determinístico: o LLM não é consultado.
        res = self.verificador.recalcular(fis)
        self.verificador.aplicar(fis, res)
        fala_llm = "" if comando else self._laco_llm(fis, evento, texto, ev_nova, resp)

        # 6. plano mínimo determinístico (checagem que o LLM não chamou para a evidência nova)
        self._plano_minimo(fis, ev_nova, resp)

        # 6b. alegações da fala × checagens (determinístico; registra, não muda campo do laudo)
        self._conciliar_alegacoes(fis, ev_nova, resp)

        # 7. verificação independente e avanço da FSM; depois, o comando humano (passa pela política)
        res = self.verificador.recalcular(fis)
        self.verificador.aplicar(fis, res)
        if res.aviso:
            resp.avisos.append(res.aviso)
        self._avancar_automatico(fis, res, resp)
        if comando:
            resp.acoes.append(self.executar_acao(fis, comando[0], {}, origem="comando", fala_atual=texto))
            res = self.verificador.recalcular(fis)
            self.verificador.aplicar(fis, res)

        # 8. fala final: fatos por template (resultado das checagens e ações do turno) + condução do LLM, que
        # passa pela consistência semântica (POL-09) e pelo grounding numérico (POL-05)
        resp.fatos = self._fatos(fis, res, resp, texto, ev_nova)
        conducao = self._conducao_llm(fis, res, resp, fala_llm, texto)
        if conducao and any(a.acao in _LEITURAS and a.ok for a in resp.acoes) and residual_pendente(fis):
            # a leitura da foto acabou de gerar o pedido do residual (dito pelo template): a condução do LLM não
            # pode mandar refazer a foto nem pedir outra coisa por cima dele
            resp.avisos.append("condução por template: pedido do residual da leitura da foto")
            conducao = ""
        removeu = bool((resp.llm.get("semantica") or {}).get("frases_resultado_removidas"))
        if conducao and not resp.fatos and removeu and self.politica.pendencias_emissao(fis, res):
            # o LLM afirmou resultado e a frase saiu: o contexto da condução vem do template (próximo passo)
            resp.fatos = [self._proximo_passo(fis, res)]
        if esclarecer:
            resp.fatos.append(esclarecer)
        if conducao:
            resp.fala, resp.fala_origem = " ".join([*resp.fatos, conducao]).strip(), "llm"
        else:
            resp.fala = self._fala_template(fis, res, resp)
        return self._fechar(fis, resp, n_oc, res=res)

    def _turno_residual(self, fis: Fiscalizacao, pend: ResidualPendente, respostas: dict[str, str],
                        resp: RespostaTurno, n_oc: int, texto: str) -> RespostaTurno:
        """A fiscal leu no papel os campos que a foto não validou: `completar_leitura_documento` revalida tudo com
        as regras determinísticas (DV, somas, datas) e, se algo foi aceito, a conciliação do documento roda de novo
        com a leitura completada. Os valores não aparecem nos argumentos da ação (CPF/CNPJ digitado)."""
        nome = residual_mod.FERRAMENTA
        if fis.estado_fsm != fsm.Etapa.CHECAGEM:
            self._ir(fis, fsm.Etapa.CHECAGEM, resp)
        dec = self.politica.autorizar(nome, fis, {}, origem="residual")
        base = {"acao": nome, "argumentos": {"evidencia_id": pend.evidencia_id, "campos": sorted(respostas)},
                "origem": "residual", "rule_id": dec.rule_id}
        if not dec.permitido:
            resp.acoes.append(AcaoExecutada(**base, permitido=False, ok=False, span_id=dec.span_id,
                                            resultado=f"NEGADO ({dec.rule_id}): {dec.motivo}"))
        else:
            leitura = privacidade.restaurar_resultado(  # a chave inteira volta do cofre, só em memória
                next(c for c in fis.checagens if c.id == pend.checagem_id).resultado, fis.id, self.cofre)
            args = {"leitura": leitura, "respostas": respostas,
                    "data_referencia": (self.hoje or fis.data_referencia or datetime.now().astimezone().date())
                    .isoformat()}
            env, span_id, h = self.executor.executar(nome, args)
            evs = [pend.evidencia_id] + ([self._ev_fala_id] if self._ev_fala_id else [])
            chk = est.registrar_checagem(fis, nome, h, env, item_id=pend.item_id, evidencias=evs, span_id=span_id,
                                         cofre=self.cofre)
            resp.acoes.append(AcaoExecutada(**base, ok=env.ok, checagem_id=chk.id, span_id=span_id,
                                            resultado=f"checagem {chk.id}: status {chk.status}. "
                                                      f"{self._resultado_para_llm(env)}"))
            if env.ok and (env.data or {}).get("aceitos_da_fiscal"):
                conc = {"danfe": "conciliar_nfe", "gta": "conciliar_gta"}[pend.pedido.tipo_documento]
                if conc in self.registro:
                    resp.acoes.append(self.executar_acao(fis, conc, {"evidencia_id": pend.evidencia_id},
                                                         origem="residual"))
        res = self.verificador.recalcular(fis)
        self.verificador.aplicar(fis, res)
        self._avancar_automatico(fis, res, resp)
        resp.fatos = self._fatos(fis, res, resp, "", None)
        resp.fala = self._fala_template(fis, res, resp)
        resp.llm["residual"] = {"campos_respondidos": sorted(respostas), "turno_sem_llm": True}
        return self._fechar(fis, resp, n_oc, res=res)

    def _conducao_llm(
        self, fis: Fiscalizacao, res: ResultadoVerificacao, resp: RespostaTurno, fala_llm: str, texto: str
    ) -> str:
        """Frases de condução do LLM que sobrevivem às regras da fala. Se a política negou uma ação proposta pelo
        LLM, ou há afirmação inconsistente com o estado (POL-09), ou número sem lastro (POL-05), vale o template
        inteiro (o fiscal não ouve "feito" do que não foi, nem "excesso" quando falta)."""
        limpa = fatos_mod.limpar_marcacoes(fala_llm)
        if limpa != fala_llm.strip():
            resp.avisos.append("marcação interna removida da fala do LLM (<dado>, <contexto>, <hash>...)")
        fala_llm = limpa
        if not fala_llm:
            return ""
        negadas = [a for a in resp.acoes if a.origem == "llm" and not a.permitido]
        if negadas:
            resp.avisos.append(f"fala do LLM trocada pelo template: ação negada ({negadas[0].rule_id})")
            return ""
        if any(a.acao == "carregar_operacao" and a.ok for a in resp.acoes):
            # por que a operação está na amostra e qual método a regra pede: fatos determinísticos, ditos pelo
            # template (o modelo pequeno já inverteu "acima do limite" para "dentro do limite")
            resp.avisos.append("fala do plano por template (triagem e método vêm das ferramentas)")
            return ""
        d_sem, analise = self.politica.checar_semantica(fala_llm, fis, res, acoes=self._contexto_acoes(resp, fis))
        resp.llm["semantica"] = {
            "violacoes": [v.model_dump() for v in analise.violacoes],
            "frases_conducao": len(analise.conducao),
            "frases_resultado_removidas": len(analise.removidas),
            "span_id": d_sem.span_id,
        }
        if not d_sem.permitido:
            resp.avisos.append(f"fala do LLM trocada pelo template ({d_sem.rule_id}: {d_sem.motivo[:200]})")
            return ""
        if analise.removidas:
            resp.avisos.append(f"{len(analise.removidas)} frase(s) do LLM com resultado trocada(s) pelo template")
        conducao = " ".join(analise.conducao).strip()
        if not conducao:
            return ""
        d = self.politica.checar_texto(conducao, fis, extras=[texto], acao="fala_agente")
        if not d.permitido:
            resp.avisos.append(f"fala do LLM descartada ({d.motivo})")
            return ""
        return conducao

    def _contexto_acoes(self, resp: RespostaTurno, fis: Fiscalizacao) -> fatos_mod.ContextoAcoes:
        """O que de fato aconteceu no turno (POL-09: a fala do LLM não afirma ação que não está aqui nem no
        estado)."""
        feitas = [a for a in resp.acoes if a.permitido and a.ok is not False]
        chks = {a.checagem_id for a in feitas if a.checagem_id}
        return fatos_mod.ContextoAcoes(
            acoes=[a.acao for a in feitas],
            checagens=[c.ferramenta for c in fis.checagens if c.id in chks],
            upload=self._upload_turno.tipo if self._upload_turno is not None else None,
            alegacoes=len(resp.alegacoes),
        )

    def _fechar(
        self,
        fis: Fiscalizacao,
        resp: RespostaTurno,
        n_oc: int,
        recalcular: bool = True,
        res: ResultadoVerificacao | None = None,
    ) -> RespostaTurno:
        if recalcular or res is not None:
            res = res or self.verificador.recalcular(fis)
            resp.pendencias = self.politica.pendencias_emissao(fis, res)
        resp.etapa = fis.estado_fsm
        if residual_mod.FERRAMENTA in self.registro:
            pend = residual_pendente(fis)
            resp.residual = pend.para_interface() if pend else None
        resp.ocorrencias = [o.id for o in fis.ocorrencias[n_oc:]]
        self.repo.salvar(fis)
        return resp

    # -- upload ---------------------------------------------------------------
    def _registrar_upload(self, fis: Fiscalizacao, nova: NovaEvidencia, resp: RespostaTurno):
        meta = dict(nova.meta)
        if nova.item_id:
            meta["item_id"] = nova.item_id
        if nova.lote:
            meta["lote"] = nova.lote
        conteudo = nova.conteudo_texto.encode("utf-8") if nova.conteudo_texto is not None else None
        ev = est.adicionar_evidencia(
            fis,
            nova.tipo,
            conteudo=conteudo,
            caminho=nova.caminho,
            sha256=nova.sha256,
            meta=mascarar_obj(meta),
            gps=nova.gps,
            capturada_em=nova.capturada_em,
            recebida_em=nova.recebida_em,
        )
        self._varrer_dado(fis, meta, origem=f"evidencia:{nova.tipo}", ref=ev.id, resp=resp)
        return ev

    def _varrer_dado(
        self, fis: Fiscalizacao, dados: Any, origem: str, ref: str | None, resp: RespostaTurno
    ) -> None:
        """POL-06: procura instrução embutida em texto de dado (OCR, documento, transcrição)."""
        textos: list[str] = []

        def walk(o: Any, chave: str = "") -> None:
            if isinstance(o, str) and (chave in _CHAVES_TEXTO_DADO or len(o) > 20):
                textos.append(o)
            elif isinstance(o, dict):
                for k, v in o.items():
                    walk(v, str(k))
            elif isinstance(o, list):
                for v in o:
                    walk(v, chave)

        walk(dados)
        for t in textos:
            d = self.politica.avaliar_dado(t, origem, ref)
            if d:
                est.registrar_ocorrencia(fis, "injecao", f"{d.rule_id}: {d.motivo}", evidencia_ref=ref)
                resp.acoes.append(
                    AcaoExecutada(
                        acao="guarda",
                        origem="guarda",
                        permitido=False,
                        rule_id=d.rule_id,
                        resultado=d.motivo,
                        span_id=d.span_id,
                    )
                )
                break

    # -- alegações ------------------------------------------------------------
    def _extrair_alegacoes(
        self, fis: Fiscalizacao, texto: str, ev_id: str, resp: RespostaTurno
    ) -> list[dict]:
        if not (re.search(r"\d", texto) or _NUM_PALAVRA.search(texto)):
            return []
        candidatas: list[tuple[Alegacao, str]] = []
        if self.provedor is not None and self.extrair_alegacoes_llm and self._llm_falhou:
            resp.llm.setdefault("alegacoes", {"pulado": "disjuntor", "codigo": self._disjuntor_codigo})
        elif self.provedor is not None and self.extrair_alegacoes_llm:
            itens = [{"id": i.id, "tipo": i.tipo, "descricao": i.descricao} for i in fis.operacao.itens]
            msgs = [
                {"role": "system", "content": self.prompt_alegacoes},
                {
                    "role": "user",
                    "content": f"Itens: {json.dumps(itens, ensure_ascii=False)}\n"
                    f'Fala do fiscal: "{self._para_llm(texto)}"',
                },
            ]
            r = pedir_json(
                self.provedor,
                msgs,
                ListaAlegacoes,
                reparos=1,
                metadados={"laudo.prompt.versao": self.versao_prompt_alegacoes},
            )
            resp.llm.setdefault(
                "alegacoes",
                {
                    "valido_1a": r.valido_primeira,
                    "valido": r.valido,
                    "tentativas": r.tentativas,
                    "latencia_ms": r.latencia_ms,
                },
            )
            if r.codigo_erro in _CODIGOS_DISJUNTOR:
                # o modelo não respondeu: o resto do turno segue sem LLM (a condução não tenta de novo, e o
                # fiscal não espera o timeout duas vezes); o extrator determinístico cobre as alegações
                resp.avisos.append(f"LLM indisponível ({r.codigo_erro}) nas alegações; extrator "
                                   "determinístico")
                self._falha_llm(r.codigo_erro)
            elif r.respostas:
                self._llm_respondeu()
            if r.valido and r.objeto is not None:
                candidatas = [(a, "llm") for a in r.objeto.alegacoes]
        # O extrator determinístico complementa o LLM (união; o LLM pode deixar escapar uma alegação).
        vistos = {(a.grandeza, a.valor) for a, _ in candidatas}
        candidatas += [
            (a, "regex") for a in alegacoes_regex(texto, fis.operacao) if (a.grandeza, a.valor) not in vistos
        ]
        ids_itens = {i.id for i in fis.operacao.itens}
        saida = []
        for a, origem in candidatas:
            pos = localizar_trecho(texto, a.trecho)
            nums, _, _ = extrair_numeros(a.trecho)
            if not nums:  # número por extenso ("vinte e nove vacas"): leitura determinística de laudo.speech
                from laudo.speech.numeros import normalizar as numeros_falados

                nums = numeros_falados(a.trecho).numeros  # type: ignore[assignment]
            if pos is None or not nums:
                motivo = "trecho não está na fala" if pos is None else "sem número legível no trecho"
                resp.avisos.append(f"alegação descartada ({motivo}): {a.trecho[:60]}")
                continue
            # O número vem da leitura determinística do trecho, não do LLM ("1.200" é mil e duzentos).
            if not any(abs(x.valor - a.valor) < 1e-9 for x in nums):
                if len(nums) != 1:
                    resp.avisos.append(f"alegação descartada (número ambíguo no trecho): {a.trecho[:60]}")
                    continue
                a = a.model_copy(update={"valor": nums[0].valor})
            if (a.grandeza, a.valor) in {(x["grandeza"], x["valor"]) for x in saida}:
                continue
            item_id = a.item_id if a.item_id in ids_itens else None
            if item_id is None:
                tipo = {
                    "quantidade": ("bovinos", "maquina"),
                    "comprimento": ("cerca",),
                    "area": ("pastagem", "lavoura"),
                }.get(a.grandeza, ())
                item_id = next((i.id for i in fis.operacao.itens if i.tipo in tipo), None)
            reg = est.registrar_alegacao(
                fis,
                {
                    "grandeza": a.grandeza,
                    "valor": a.valor,
                    "unidade": a.unidade,
                    "item_id": item_id,
                    "trecho": texto[pos[0] : pos[1]],
                    "ponteiro": {"evidencia_id": ev_id, "inicio": pos[0], "fim": pos[1]},
                    "origem_extracao": origem,
                },
            )
            saida.append(reg)
        return saida

    # -- LLM ------------------------------------------------------------------
    def _para_llm(self, texto: str) -> str:
        return mascarar(texto) if getattr(self.provedor, "externo", False) else texto

    def _contexto(self, fis: Fiscalizacao) -> dict[str, Any]:
        pend = self.politica.pendencias_emissao(fis)
        res_campos = [
            {
                "campo": c.campo,
                "status": c.status,
                "valor": c.valor,
                "motivo": c.motivo[:160],
                "justificativa": bool(c.justificativa_humana),
            }
            for c in fis.campos.values()
        ]
        evs = [
            {"id": e.id, "tipo": e.tipo, "item_id": e.meta.get("item_id"), "lote": e.meta.get("lote")}
            for e in fis.evidencias
            if e.tipo not in ("declaracao", "ocorrencia", "quadro_chave")
        ][-8:]
        return {
            "etapa": fis.estado_fsm,
            "metodo": fis.metodo,
            "operacao": {
                "ref_bacen": fis.operacao.ref_bacen,
                "municipio": fis.operacao.municipio_nome,
                "finalidade": fis.operacao.finalidade,
                "itens": [
                    {
                        "id": i.id,
                        "tipo": i.tipo,
                        "descricao": i.descricao,
                        "quantidade": i.quantidade,
                        "unidade": i.unidade,
                    }
                    for i in fis.operacao.itens
                ],
            },
            "campos": res_campos,
            "evidencias_recentes": evs,
            # as mesmas pendências que a política usa para bloquear o rascunho (POL-01/POL-02)
            "pendencias": [f"{p.get('campo') or p['regra_id']}: {str(p.get('falta'))[:120]}" for p in pend][:6],
            "rascunho_pode_ser_emitido": not pend,
            "residual_pendente": (rp.pedido.texto if (rp := residual_pendente(fis)) else None),
            "ocorrencias": len(fis.ocorrencias),
        }

    def _mensagens(self, fis: Fiscalizacao, evento: Evento, texto: str, ev_nova) -> list[dict[str, Any]]:
        msgs: list[dict[str, Any]] = [{"role": "system", "content": self.prompt_condutor}]
        for h in self.repo.ler_conversa(fis.id, ultimos=3):
            if h.get("fiscal"):
                msgs.append({"role": "user", "content": f'Fala do fiscal: "{h["fiscal"]}"'})
            if h.get("agente"):  # hashes não servem ao LLM (e mudariam a chave do replay a cada execução)
                msgs.append({"role": "assistant", "content": _RX_HASH.sub("<hash>", h["agente"])})
        partes = [f"<contexto>{json.dumps(self._contexto(fis), ensure_ascii=False, default=str)}</contexto>"]
        if ev_nova is not None:
            dado = {k: v for k, v in ev_nova.meta.items() if k not in ("item_id", "lote")}
            partes.append(
                f"Evidência recebida: id={ev_nova.id} tipo={ev_nova.tipo} "
                f"item={ev_nova.meta.get('item_id')} lote={ev_nova.meta.get('lote')}"
                + (
                    f'\n<dado origem="metadados">{json.dumps(dado, ensure_ascii=False)[:800]}</dado>'
                    if dado
                    else ""
                )
            )
        if texto:
            partes.append(f'Fala do fiscal: "{self._para_llm(texto)}"')
        msgs.append({"role": "user", "content": "\n".join(partes)})
        return msgs

    # -- orçamento e disjuntor do LLM ------------------------------------------------
    def _orcamento_llm(self) -> AbstractContextManager[Any]:
        """Orçamento de LLM do turno, quando o provedor tem (perfil de palco do Ollama)."""
        abrir = getattr(self.provedor, "orcamento_do_turno", None)
        return abrir() if callable(abrir) else nullcontext()

    def _disjuntor_aberto(self) -> bool:
        return self._disjuntor_ate is not None and self._relogio() < self._disjuntor_ate

    def _falha_llm(self, codigo: str) -> None:
        """O LLM falhou neste turno: nada mais de LLM até o fim do turno (`_llm_falhou`). Falha de transporte
        (TIMEOUT, servidor fora), com disjuntor configurado, deixa o LLM de fora também nos turnos seguintes,
        até passar `espera_disjuntor_s`; o primeiro turno depois disso tenta de novo (meio-aberto)."""
        self._llm_falhou = True
        if codigo in _CODIGOS_DISJUNTOR and self.espera_disjuntor_s:
            self._disjuntor_ate = self._relogio() + self.espera_disjuntor_s
            self._disjuntor_codigo = codigo

    def _llm_respondeu(self) -> None:
        """Resposta do LLM: o disjuntor fecha."""
        self._disjuntor_ate, self._disjuntor_codigo = None, ""

    def _laco_llm(self, fis: Fiscalizacao, evento: Evento, texto: str, ev_nova, resp: RespostaTurno) -> str:
        if self.provedor is None:
            return ""
        if self._llm_falhou:
            if self._disjuntor_ate is None:  # falhou antes, neste turno (alegações), sem disjuntor no perfil
                resp.avisos.append("LLM indisponível (falhou neste turno); plano mínimo determinístico")
                return ""
            espera = max(0.0, self._disjuntor_ate - self._relogio())
            resp.avisos.append(f"LLM indisponível ({self._disjuntor_codigo}; disjuntor aberto por mais "
                               f"{espera:.0f} s); plano mínimo determinístico")
            resp.llm["disjuntor"] = {"aberto": True, "codigo": self._disjuntor_codigo,
                                     "reabre_em_s": round(espera, 1)}
            return ""
        msgs = self._mensagens(fis, evento, texto, ev_nova)
        fala = ""
        stats = resp.llm.setdefault(
            "condutor",
            {
                "chamadas_llm": 0,
                "tool_calls": 0,
                "tool_calls_validas": 0,
                "reparos": 0,
                "latencia_ms": 0,
                "modo": self.modo,
                "modelo": getattr(self.provedor, "modelo", ""),
            },
        )
        forcou = False
        for _ in range(self.max_passos + 1):
            permitidas = fsm.nomes_permitidos(fis.estado_fsm, self.registro)
            if not permitidas:
                break
            try:
                if self.modo == "tools":
                    try:
                        chamadas, conteudo = self._passo_tools(msgs, permitidas, stats)
                    except ErroLLM as e:
                        if e.codigo not in ("HTTP", "FORMATO"):
                            raise
                        # Tool call malformada (o Ollama devolve 500 ao não conseguir ler a chamada): a
                        # contingência é a saída estruturada com JSON Schema (ADR 001), no mesmo passo.
                        resp.avisos.append(f"tool calling falhou ({e.codigo}); contingência: saída estruturada")
                        stats["contingencia_estruturada"] = stats.get("contingencia_estruturada", 0) + 1
                        chamadas, conteudo = self._passo_estruturado(msgs, permitidas, stats)
                else:
                    chamadas, conteudo = self._passo_estruturado(msgs, permitidas, stats)
            except ErroLLM as e:
                resp.avisos.append(f"LLM indisponível ({e.codigo}); plano mínimo determinístico")
                self._falha_llm(e.codigo)
                return ""
            origem = "llm"
            if not chamadas:
                faltam = self._faltantes(fis, ev_nova)
                if not faltam or forcou:
                    fala = conteudo
                    break
                # O modelo não chamou a checagem óbvia: o plano mínimo executa agora, e o modelo redige a fala
                # já vendo o resultado (em vez de falar antes da checagem).
                forcou, origem = True, "fallback"
                chamadas = [ChamadaFerramenta(nome=n, argumentos=a) for n, a in faltam]
            if self.modo == "estruturado" and conteudo and origem == "llm":
                fala = conteudo
            msgs.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": c.nome, "arguments": c.argumentos}} for c in chamadas
                    ],
                }
            )
            for c in chamadas[:3]:
                if origem == "llm":
                    stats["tool_calls"] += 1
                if dup := self._ja_feita_no_turno(resp, c.nome, dict(c.argumentos)):
                    # a rede de segurança determinística já registrou a mesma declaração neste turno: o LLM
                    # recebe o resultado, mas a ação não aparece duas vezes ([fallback] + [llm])
                    if origem == "llm":
                        stats["tool_calls_validas"] += 1
                    msgs.append({"role": "tool", "tool_name": c.nome, "content": dup})
                    continue
                acao = self.executar_acao(fis, c.nome, dict(c.argumentos), origem=origem, fala_atual=texto)
                if origem == "llm" and acao.permitido and acao.ok is not False:
                    stats["tool_calls_validas"] += 1
                resp.acoes.append(acao)
                msgs.append(
                    {"role": "tool", "tool_name": c.nome, "content": self._para_llm(acao.resultado)[:1500]}
                )
        return fala

    @staticmethod
    def _ja_feita_no_turno(resp: RespostaTurno, nome: str, args: dict[str, Any]) -> str:
        """Declaração (justificativa, conclusão de obra) já registrada neste turno para o mesmo campo/item."""
        chave = {"registrar_justificativa": "campo", "registrar_conclusao_obra": "item_id"}.get(nome)
        if chave is None:
            return ""
        for a in resp.acoes:
            if a.acao == nome and a.permitido and a.ok and str(a.argumentos.get(chave)) == str(args.get(chave)):
                return f"(já registrado neste turno pela leitura determinística da fala) {a.resultado}"
        return ""

    def _faltantes(self, fis: Fiscalizacao, ev_nova) -> list[tuple[str, dict[str, Any]]]:
        """Checagens do plano mínimo que ainda não rodaram neste turno (plano no BRIEFING; checagem do
        upload)."""
        planejado = any(c.ferramenta == "planejar_metodo" and c.status == "ok" for c in fis.checagens)
        if fis.estado_fsm == fsm.Etapa.BRIEFING and "planejar_metodo" in self.registro and not planejado:
            return [("planejar_metodo", {})]
        if ev_nova is None or fis.estado_fsm != fsm.Etapa.CHECAGEM:
            return []
        feitas = {c.ferramenta for c in fis.checagens if ev_nova.id in c.evidencias}
        return [
            (n, {"evidencia_id": ev_nova.id})
            for n in plano_da_evidencia(fis, ev_nova, self.classificar_fotos)
            if n not in feitas and n in self.registro
        ]

    def _passo_tools(self, msgs, permitidas, stats) -> tuple[list, str]:
        tools = [self._schema(n) for n in permitidas]
        r: RespostaLLM = self.provedor.chat(
            msgs,
            ferramentas=tools,  # type: ignore[union-attr]
            metadados={"laudo.prompt.versao": self.versao_prompt},
        )
        stats["chamadas_llm"] += 1
        stats["latencia_ms"] += r.latencia_ms
        self._llm_respondeu()
        chamadas = list(r.chamadas)
        if (
            not chamadas
            and r.conteudo
            and ("<tool_call>" in r.conteudo or r.conteudo.lstrip().startswith("{"))
        ):
            chamadas = chamadas_do_texto(r.conteudo)
            if chamadas:
                stats["reparos"] += 1
                return chamadas, ""
        return chamadas, re.sub(r"<think>.*?</think>", "", r.conteudo, flags=re.DOTALL).strip()

    def _schema(self, nome: str) -> dict[str, Any]:
        return schema_para_llm(self.registro[nome]) if nome in self.registro else schema_interna(nome)

    def _passo_estruturado(self, msgs, permitidas, stats) -> tuple[list, str]:
        catalogo = "\n".join(
            f"- {n}: {self._schema(n)['function']['description']} Argumentos: "
            f"{json.dumps(self._schema(n)['function']['parameters'], ensure_ascii=False)}"
            for n in permitidas
        )
        m = msgs + [
            {"role": "user", "content": "Ações disponíveis (use 'responder' para só falar):\n" + catalogo}
        ]
        r = pedir_json(
            self.provedor,
            m,
            DecisaoEstruturada,
            reparos=1,  # type: ignore[arg-type]
            esquema=esquema_decisao(permitidas),
            metadados={"laudo.prompt.versao": self.versao_prompt},
        )
        stats["chamadas_llm"] += r.tentativas
        stats["latencia_ms"] += r.latencia_ms
        if not r.valido_primeira and r.valido:
            stats["reparos"] += 1
        if r.codigo_erro:  # falha do provedor (TIMEOUT, servidor fora): o disjuntor precisa do código certo
            raise ErroLLM(r.codigo_erro, r.erro)
        if r.respostas:
            self._llm_respondeu()
        if not r.valido:
            raise ErroLLM("FORMATO", r.erro or "decisão fora do schema")
        dec: DecisaoEstruturada = r.objeto
        if dec.acao == "responder":
            return [], dec.fala_para_o_fiscal
        return [ChamadaFerramenta(nome=dec.acao, argumentos=dec.argumentos)], dec.fala_para_o_fiscal

    # -- execução de ações -------------------------------------------------------
    def _args_do_llm(self, nome: str, args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        """O LLM só decide os argumentos do esquema que recebe (`schema_para_llm`: `evidencia_id`,
        `item_id` e os opcionais de negócio). Caminho, GPS, item financiado, leitura, parâmetros técnicos e
        tudo o que o condutor preenche do estado (`_AUTO`) vindos dele são descartados: senão o LLM poderia apontar a
        ferramenta para um arquivo qualquer do disco, ou para coordenadas que não são as da foto."""
        if not isinstance(args, dict):
            return {}, ["<argumentos não são objeto>"]
        props = set(self._schema(nome)["function"]["parameters"].get("properties") or {})
        fora = sorted(k for k in args if k not in props)
        if not fora:
            return args, []
        otel.registrar_decisao(
            "POL-00", "transformar", nome,
            f"argumentos fora do esquema do LLM descartados: {', '.join(fora)}",
            **{"policy.origem": "llm"},
        )
        limpos = {k: v for k, v in args.items() if k in props}
        # o modelo que pôs o id da evidência no campo do caminho (`caminho_video: ev_...`) quis dizer a
        # evidência: vale como `evidencia_id` (que ainda precisa existir nesta fiscalização); o caminho, nunca
        ids = {v for k, v in args.items()
               if (k in _CAMPOS_DE_EVIDENCIA or k.startswith("caminho") or k.endswith("_path"))
               and isinstance(v, str) and _RX_ID_EVIDENCIA.match(v)}
        if "evidencia_id" in props and not limpos.get("evidencia_id") and len(ids) == 1:
            limpos["evidencia_id"] = ids.pop()
        return limpos, fora

    @staticmethod
    def _item_da_evidencia(
        fis: Fiscalizacao, nome: str, args: dict[str, Any]
    ) -> tuple[dict[str, Any], list[str]]:
        """A evidência enviada para um item (`meta.item_id` do upload) define o item da checagem; o
        `item_id` que o LLM mandar diferente é descartado (senão o vídeo do lote de um item definiria o campo
        de outro)."""
        ev_id = args.get("evidencia_id")
        ev = est.evidencia_por_id(fis, ev_id) if isinstance(ev_id, str) else None
        do_upload = ev.meta.get("item_id") if ev is not None else None
        pedido = args.get("item_id")
        if not do_upload or pedido in (None, "", do_upload):
            return args, []
        otel.registrar_decisao(
            "POL-00", "transformar", nome,
            f"item_id {pedido} do LLM trocado pelo item da evidência {ev.id} ({do_upload})",
            **{"policy.origem": "llm"},
        )
        return {**args, "item_id": do_upload}, [f"item_id={pedido}"]

    def executar_acao(
        self, fis: Fiscalizacao, nome: str, args: dict[str, Any], origem: str = "llm", fala_atual: str = ""
    ) -> AcaoExecutada:
        descartados: list[str] = []
        if origem == "llm" and nome in self.registro:
            args, descartados = self._args_do_llm(nome, args)
            args, trocados = self._item_da_evidencia(fis, nome, args)
            descartados += trocados
        acao = self._executar_acao(fis, nome, args, origem, fala_atual)
        if descartados:
            acao.resultado = (f"(argumentos ignorados: {', '.join(descartados)}; valem os do estado da "
                              f"fiscalização) {acao.resultado}")
        return acao

    def _executar_acao(
        self, fis: Fiscalizacao, nome: str, args: dict[str, Any], origem: str, fala_atual: str
    ) -> AcaoExecutada:
        dec = self.politica.autorizar(nome, fis, args, origem=origem, fala_atual=fala_atual)
        if not dec.permitido:
            pend = (
                f" Pendências: {json.dumps(dec.pendencias[:5], ensure_ascii=False, default=str)}"
                if dec.pendencias
                else ""
            )
            return AcaoExecutada(
                acao=nome,
                argumentos=args,
                origem=origem,
                permitido=False,
                rule_id=dec.rule_id,
                ok=False,
                resultado=f"NEGADO ({dec.rule_id}): {dec.motivo}.{pend}",
                span_id=dec.span_id,
                dados={"pendencias": dec.pendencias},
            )
        if nome in fsm.ACOES_INTERNAS:
            return self._acao_interna(fis, nome, args, origem, dec)
        if nome == "registrar_ocorrencia":
            tipo = str(args.get("tipo") or "outro")
            if tipo not in ("pressao", "injecao", "fora_de_escopo", "falha_ferramenta", "outro"):
                tipo = "outro"
            oc = est.registrar_ocorrencia(fis, tipo, mascarar(str(args.get("descricao") or ""))[:500])
            return AcaoExecutada(
                acao=nome,
                argumentos=args,
                origem=origem,
                ok=True,
                rule_id=dec.rule_id,
                resultado=f"ocorrência {oc.id} registrada",
                span_id=dec.span_id,
            )
        return self._ferramenta(fis, nome, args, origem)

    def _acao_interna(self, fis, nome, args, origem, dec: Decisao) -> AcaoExecutada:
        base = {
            "acao": nome,
            "argumentos": args,
            "origem": origem,
            "rule_id": dec.rule_id,
            "span_id": dec.span_id,
        }
        if nome == "pedir_evidencia":
            try:
                a = ArgsPedirEvidencia.model_validate(args)
            except ValidationError as e:
                return AcaoExecutada(**base, ok=False, resultado=f"argumentos inválidos: {e.errors()[:2]}")
            return AcaoExecutada(
                **base, ok=True, resultado=f"pedido registrado: {a.instrucao}", dados=a.model_dump()
            )
        if nome == "registrar_justificativa":
            campo = fis.campos[str(args["campo"])]
            # o trecho literal vai para o estado e o laudo já mascarado (PIN, CPF, telefone ditos na mesma fala)
            campo.justificativa_humana = mascarar(str(args.get("trecho") or args.get("justificativa")).strip())
            return AcaoExecutada(**base, ok=True, resultado=f"justificativa registrada em {campo.campo}")
        if nome == "registrar_conclusao_obra":
            # trecho mascarado na checagem (a política já conferiu o literal contra a fala do turno)
            item_id, trecho = str(args["item_id"]), mascarar(str(args["trecho"]).strip())
            h = hash_entrada({"item_id": item_id, "trecho": trecho})
            if (chk := est.checagem_existente(fis, decl.FERRAMENTA_CONCLUSAO, h)) is not None:
                return AcaoExecutada(**base, ok=True, checagem_id=chk.id,
                                     resultado=f"(idempotente) declaração já registrada em {chk.id}")
            # retirada em 1ª pessoa ("me enganei") substitui as declarações anteriores do item
            anteriores = decl.declaracoes_ativas(fis, item_id) if decl.eh_retirada(trecho) else []
            env = decl.envelope_conclusao(item_id, trecho, substitui=anteriores)
            with otel.span(f"tool {decl.FERRAMENTA_CONCLUSAO}", **{"tool.name": decl.FERRAMENTA_CONCLUSAO}) as s:
                span_id = otel.id_span(s)
            chk = est.registrar_checagem(
                fis,
                decl.FERRAMENTA_CONCLUSAO,
                h,
                env,
                item_id=item_id,
                evidencias=[self._ev_fala_id] if self._ev_fala_id else [],
                span_id=span_id,
            )
            res = self.verificador.recalcular(fis)
            self.verificador.aplicar(fis, res)
            c = res.campos.get(f"item:{item_id}:conclusao")
            extra = f" Verificador: {c.campo} = {c.status}." if c else ""
            return AcaoExecutada(
                **base,
                ok=True,
                checagem_id=chk.id,
                resultado=f"checagem {chk.id}: status {chk.status}. {env.data['motivo']}.{extra}",
                dados=env.data,
            )
        if nome == "avancar_etapa":
            para = str(args.get("para") or args.get("etapa")).upper()
            fsm.transitar(fis, para)
            return AcaoExecutada(**base, ok=True, resultado=f"etapa agora {para}")
        if nome == "solicitar_assinatura":
            fsm.transitar(fis, fsm.Etapa.ASSINATURA)
            return AcaoExecutada(**base, ok=True, resultado="rascunho enviado para assinatura humana")
        return AcaoExecutada(**base, ok=False, permitido=False, resultado="ação interna desconhecida")

    def _ferramenta(self, fis: Fiscalizacao, nome: str, args: dict[str, Any], origem: str) -> AcaoExecutada:
        ferr = self.registro[nome]
        ev_id = args.get("evidencia_id")
        ev = est.evidencia_por_id(fis, ev_id) if isinstance(ev_id, str) else None
        # Sem fonte, sem afirmação. Id de evidência que não existe, ou ferramenta sobre evidência chamada
        # sem evidência, é ENTRADA_INVALIDA (nenhuma checagem é registrada; nenhum campo muda)
        if ev_id not in (None, "") and ev is None:
            return self._entrada_invalida(nome, args, origem,
                                          f"evidência {ev_id} não existe nesta fiscalização")
        if ev is None and sobre_evidencia(nome, self.registro):
            return self._entrada_invalida(
                nome, args, origem,
                f"{nome} trabalha sobre uma evidência: informe o evidencia_id de uma evidência desta "
                "fiscalização",
            )
        # item que não existe na operação (o LLM escolhe o item só quando a evidência não tem item no upload)
        item_pedido = args.get("item_id")
        itens = {i.id for i in fis.operacao.itens}
        if origem == "llm" and item_pedido not in (None, "") and str(item_pedido) not in itens:
            return self._entrada_invalida(nome, args, origem, f"item {item_pedido} não existe nesta operação")
        previa = self._dependencia(fis, _DEPENDENCIAS[nome]) if nome in _DEPENDENCIAS else None
        item_id = args.get("item_id") or (ev.meta.get("item_id") if ev else None)
        if (nome in DOCUMENTOS_CUMULATIVOS and ev is not None and ev.tipo == "documento"
                and "ler_documento_foto" in self.registro
                and not any(c.ferramenta == "ler_documento_foto" and ev.id in c.evidencias for c in fis.checagens)):
            # foto/PDF de documento: a conciliação usa o que foi lido e validado; a leitura vem antes
            leitura = self.executar_acao(fis, "ler_documento_foto", {"evidencia_id": ev.id}, origem="fallback")
            if self._resp_turno is not None:
                self._resp_turno.acoes.append(leitura)
        if nome == "geofence" and ev is not None:
            self._integridade_antes_do_geofence(fis, ev)
        if nome == "emitir_rascunho":
            args["fiscalizacao_id"] = fis.id
            res = self.verificador.recalcular(fis)
            self.verificador.aplicar(fis, res)
            self.repo.salvar(fis)  # a ferramenta lê o estado persistido
        completos = preencher_argumentos(ferr, fis, args, hoje=self.hoje, dir_dados=self.dir_dados)
        h = hash_entrada(completos)
        if nome not in _NAO_CHECAGEM and ferr.deterministica:
            chk = est.checagem_existente(fis, nome, h)
            if chk is not None:
                return AcaoExecutada(
                    acao=nome,
                    argumentos=args,
                    origem=origem,
                    ok=chk.status != "erro",
                    checagem_id=chk.id,
                    span_id=chk.trace_id or "",
                    resultado=f"(idempotente) checagem {chk.id} já existente: status {chk.status}",
                )
        env, span_id, h = self.executor.executar(nome, completos)
        if nome == "geofence" and ev is not None:
            env = self._geofence_conforme_integridade(fis, ev, env)
        acao = AcaoExecutada(
            acao=nome,
            argumentos=args,
            origem=origem,
            ok=env.ok,
            span_id=span_id,
            resultado=self._resultado_para_llm(env),
            dados=env.data,
        )
        if nome not in _NAO_CHECAGEM:
            evs = [ev.id] if ev else []
            if ev is not None and env.ok and env.data:
                evs += self._quadros_chave(fis, ev, item_id, env.data)
            if nome in DOCUMENTOS_CUMULATIVOS and ev is not None and env.ok and env.data is not None:
                # a conciliação usou todos os documentos do item: liga todos e substitui as anteriores
                tipo = DOCUMENTOS_CUMULATIVOS[nome]
                docs = [e.id for e in fis.evidencias if e.tipo == tipo and e.meta.get("item_id") in (None, item_id)]
                evs = list(dict.fromkeys(docs + evs))
                anteriores = [c.id for c in fis.checagens if c.ferramenta == nome and c.item_id == item_id]
                if anteriores:
                    env.data["substitui"] = anteriores
            chk = est.registrar_checagem(fis, nome, h, env, item_id=item_id, evidencias=evs, span_id=span_id,
                                         cofre=self.cofre)
            if env.data:
                self._ocorrencias_sugeridas(fis, nome, env.data, ref=ev.id if ev else chk.id)
            acao.checagem_id = chk.id
            acao.resultado = f"checagem {chk.id}: status {chk.status}. {acao.resultado}"
            if env.ok and env.data:
                self._varrer_dado(
                    fis,
                    env.data,
                    origem=f"ferramenta:{nome}",
                    ref=chk.id,
                    resp=RespostaTurno(fiscalizacao_id=fis.id, turno=0, etapa="", fala=""),
                )
        if nome == "planejar_metodo" and env.ok and env.data:
            self._aplicar_plano(fis, env)
        if acao.checagem_id:
            # O LLM redige a fala vendo o status já recalculado pelo verificador (não o calcula).
            res = self.verificador.recalcular(fis)
            self.verificador.aplicar(fis, res)
            campo = self._campo_de_chk(fis, acao.checagem_id)
            c = res.campos.get(campo or "")
            if c is not None:
                acao.resultado += f" Verificador: {c.campo} = {c.status} ({c.motivo[:200]})."
        if nome == "emitir_rascunho":
            self._pos_emissao(fis, env, acao)
        if previa is not None and previa.ok:  # o LLM vê o pré-requisito (ex.: por que a operação está na amostra)
            acao.resultado = f"[{previa.acao}] {previa.resultado} || {acao.resultado}"
        return acao

    def _entrada_invalida(self, nome: str, args: dict[str, Any], origem: str, motivo: str) -> AcaoExecutada:
        """Envelope ENTRADA_INVALIDA com span da ferramenta (a trilha mostra a tentativa), sem checagem."""
        env = Envelope.falha(nome, CodigoErro.ENTRADA_INVALIDA, motivo)
        with otel.span_ferramenta(nome, args) as s:
            otel.definir(s, **{"tool.ok": False, "tool.error_code": str(CodigoErro.ENTRADA_INVALIDA),
                               "tool.origem": origem})
            otel.marcar_erro(s, motivo)
            span_id = otel.id_span(s)
        return AcaoExecutada(acao=nome, argumentos=args, origem=origem, ok=False, span_id=span_id,
                             resultado=self._resultado_para_llm(env))

    def _integridade_antes_do_geofence(self, fis: Fiscalizacao, ev) -> None:
        """A localização depende da integridade da mesma foto: se o LLM pedir o geofence primeiro, a integridade
        roda antes (uma vez por foto)."""
        if "integridade_foto" not in self.registro or any(
            c.ferramenta == "integridade_foto" and ev.id in c.evidencias for c in fis.checagens
        ):
            return
        acao = self.executar_acao(fis, "integridade_foto", {"evidencia_id": ev.id}, origem="dependencia")
        if self._resp_turno is not None:
            self._resp_turno.acoes.append(acao)

    @staticmethod
    def _geofence_conforme_integridade(fis: Fiscalizacao, ev, env: Envelope) -> Envelope:
        """Foto com integridade em erro (arquivo ilegível ou truncado) ou reprovada (tela, reaproveitada,
        metadados incoerentes): o ponto do GPS não pode ser atribuído a ela, e a localização vira
        indeterminada (RT-FAL-04). Integridade inconclusiva (sem EXIF, duplicata na mesma fiscalização) mantém
        a posição do GPS do app; o campo de integridade continua pendente."""
        integ = [c for c in fis.checagens if c.ferramenta == "integridade_foto" and ev.id in c.evidencias]
        if not integ or not env.ok or not env.data or integ[-1].status not in ("erro", "divergente"):
            return env
        chk = integ[-1]
        r = chk.resultado
        motivo_i = str(r.get("motivo") or (r.get("erro") or {}).get("msg") or "; ".join(
            str(m.get("msg", m) if isinstance(m, dict) else m) for m in r.get("motivos") or []) or chk.status)
        data = dict(env.data)
        data.update(
            status_geofence=data.get("status"),
            posicao_geofence=data.get("posicao"),
            status="indeterminado",
            posicao="indeterminado",
            motivo=(f"localização indeterminada: a integridade da foto deu {chk.status} ({motivo_i[:120]}); o "
                    "ponto do GPS não pode ser atribuído a esta foto, refaça a foto pelo app"),
            depende_de_integridade=chk.id,
        )
        return env.model_copy(update={"data": data})

    def _dependencia(self, fis: Fiscalizacao, nome: str) -> AcaoExecutada | None:
        """Roda a ferramenta pré-requisito uma vez por fiscalização (ex.: a triagem da operação antes do
        plano de método). Só para operação do Sicor (REF_BACEN numérico)."""
        if nome not in self.registro or any(c.ferramenta == nome and c.status != "erro" for c in fis.checagens):
            return None
        if nome == "carregar_operacao" and not re.fullmatch(r"\d{5,12}", fis.operacao.ref_bacen or ""):
            return None
        acao = self.executar_acao(fis, nome, {}, origem="dependencia")
        if self._resp_turno is not None:
            self._resp_turno.acoes.append(acao)
        return acao

    @staticmethod
    def _quadros_chave(fis: Fiscalizacao, video, item_id: str | None, data: dict[str, Any]) -> list[str]:
        """Quadros-chave anotados da contagem viram evidências derivadas do vídeo (o laudo liga o item a eles)."""
        ids: list[str] = []
        for q in data.get("quadros_chave") or []:
            caminho, sha = q.get("caminho"), q.get("sha256")
            if not caminho or not sha or not Path(caminho).is_file():
                continue
            nova = est.adicionar_evidencia(
                fis,
                "quadro_chave",
                caminho=caminho,
                sha256=sha,
                meta={
                    "item_id": item_id,
                    "t_s": q.get("t_s"),
                    "quadro": q.get("quadro"),
                    "contagem_ate_aqui": q.get("contagem_ate_aqui"),
                },
                derivada_de=video.id,
            )
            ids.append(nova.id)
        return ids

    def _ocorrencias_sugeridas(self, fis: Fiscalizacao, nome: str, data: dict[str, Any], ref: str) -> None:
        """POL-06: instrução embutida que a própria ferramenta detectou no documento (ela devolve só o padrão e
        o hash do texto) vira ocorrência; nenhum campo muda."""
        for o in data.get("ocorrencias_sugeridas") or []:
            if not isinstance(o, dict) or o.get("tipo") != "injecao":
                continue
            d = self.politica._decidir(
                False,
                "POL-06",
                f"dado:ferramenta:{nome}",
                f"instrução embutida em {o.get('fonte', '?')} tratada como dado (padrões: "
                f"{', '.join(o.get('padroes') or [])})",
                ocorrencia="injecao",
            )
            est.registrar_ocorrencia(fis, "injecao", f"{d.rule_id}: {d.motivo}", evidencia_ref=ref)
            if self._resp_turno is not None:
                self._resp_turno.acoes.append(
                    AcaoExecutada(
                        acao="guarda",
                        origem="guarda",
                        permitido=False,
                        rule_id=d.rule_id,
                        resultado=d.motivo,
                        span_id=d.span_id,
                    )
                )

    def _declaracoes(self, fis: Fiscalizacao, texto: str, resp: RespostaTurno) -> None:
        """Rede de segurança determinística para o que o fiscal atestou na fala, quando o LLM não registrou:
        conclusão de obra (MCR 2-7-16-a) e justificativa de divergência (POL-02). Sempre com o trecho literal;
        a política confere de novo."""
        validas = [a for a in resp.acoes if a.permitido and a.ok is not False]
        feitas = {str(a.argumentos.get("item_id")) for a in validas if a.acao == "registrar_conclusao_obra"}
        pares = decl.declaracoes_conclusao(texto, fis)
        # retirada sem nova atestação ("me enganei, retiro o que eu disse") também vira checagem do item
        pares += [p for p in decl.retiradas_conclusao(texto, fis) if p[0] not in {i for i, _ in pares}]
        for item_id, trecho in pares:
            if item_id in feitas or "registrar_conclusao_obra" not in fsm.acoes_permitidas(fis.estado_fsm):
                continue
            args = {"item_id": item_id, "trecho": trecho}
            resp.acoes.append(
                self.executar_acao(fis, "registrar_conclusao_obra", args, origem="fallback", fala_atual=texto)
            )
        if any(a.acao == "registrar_justificativa" for a in validas):
            return
        res = self.verificador.recalcular(fis)
        self.verificador.aplicar(fis, res)
        campo = decl.campo_justificado(texto, fis)
        if campo and "registrar_justificativa" in fsm.acoes_permitidas(fis.estado_fsm):
            args = {"campo": campo, "trecho": texto.strip()}
            resp.acoes.append(
                self.executar_acao(fis, "registrar_justificativa", args, origem="fallback", fala_atual=texto)
            )

    @staticmethod
    def _resultado_para_llm(env: Envelope) -> str:
        if env.ok and env.ferramenta == "emitir_rascunho":  # o hash não serve ao LLM (e mudaria o replay)
            return "rascunho emitido; aguarda revisão e assinatura humana (o agente não assina)"
        if env.ok:
            return resumo_envelope(env)
        pend = (env.data or {}).get("pendencias")
        extra = f" Pendências: {json.dumps(pend[:5], ensure_ascii=False, default=str)}" if pend else ""
        return f"{resumo_envelope(env)}.{extra}"

    def _aplicar_plano(self, fis: Fiscalizacao, env: Envelope) -> None:
        d = env.data or {}
        if d.get("metodo") in ("remoto", "documental", "presencial", "autofiscalizacao_assistida"):
            fis.metodo = d["metodo"]
        if isinstance(d.get("requisitos"), list) and not fis.requisitos:
            fis.requisitos = [r for r in d["requisitos"] if isinstance(r, dict)]
        if env.fonte_versao and not fis.rulebook_versao:
            fis.rulebook_versao = env.fonte_versao

    def _pos_emissao(self, fis: Fiscalizacao, env: Envelope, acao: AcaoExecutada) -> None:
        from laudo.tools import laudo as ferr_laudo

        if env.ok and env.data:
            ferr_laudo.registrar_emissao(fis, env.data)
            if fis.estado_fsm != fsm.Etapa.RASCUNHO:
                fsm.ir_para(fis, fsm.Etapa.RASCUNHO)

    # -- plano mínimo e FSM ------------------------------------------------------
    def _plano_minimo(self, fis: Fiscalizacao, ev_nova, resp: RespostaTurno) -> None:
        if (
            fis.estado_fsm == fsm.Etapa.BRIEFING
            and "planejar_metodo" in self.registro
            and not any(c.ferramenta == "planejar_metodo" and c.status == "ok" for c in fis.checagens)
        ):
            resp.acoes.append(self.executar_acao(fis, "planejar_metodo", {}, origem="fallback"))
        if ev_nova is None:
            return
        for _ in range(2):  # 2ª passada: foto de documento só sabe a conciliação depois da leitura
            feitas = {(c.ferramenta) for c in fis.checagens if ev_nova.id in c.evidencias}
            for nome in plano_da_evidencia(fis, ev_nova, self.classificar_fotos):
                if nome in feitas or nome not in self.registro:
                    continue
                if fis.estado_fsm != fsm.Etapa.CHECAGEM:
                    self._ir(fis, fsm.Etapa.CHECAGEM, resp)
                resp.acoes.append(self.executar_acao(fis, nome, {"evidencia_id": ev_nova.id}, origem="fallback"))

    def _conciliar_alegacoes(self, fis: Fiscalizacao, ev_nova, resp: RespostaTurno) -> None:
        """Roda `conciliar_alegacoes` quando há alegação nova ou chegou evidência que pode confrontá-las."""
        if "conciliar_alegacoes" not in self.registro or not fis.alegacoes:
            return
        if not (resp.alegacoes or (ev_nova is not None and ev_nova.tipo in ("video", "nfe_xml", "documento"))):
            return
        if "conciliar_alegacoes" in fsm.acoes_permitidas(fis.estado_fsm):
            resp.acoes.append(self.executar_acao(fis, "conciliar_alegacoes", {}, origem="fallback"))

    def _ir(self, fis: Fiscalizacao, para: fsm.Etapa, resp: RespostaTurno) -> None:
        if fis.estado_fsm == para:
            return
        de = fis.estado_fsm
        rota = fsm.ir_para(fis, para)
        resp.transicoes.append(f"{de}→" + "→".join(rota))

    def _avancar_automatico(self, fis: Fiscalizacao, res: ResultadoVerificacao, resp: RespostaTurno) -> None:
        e = fsm.etapa(fis)
        if e == fsm.Etapa.BRIEFING and (fis.metodo or "planejar_metodo" not in self.registro):
            self._ir(fis, fsm.Etapa.COLETA, resp)
        elif (
            e == fsm.Etapa.COLETA
            and fis.checagens
            and not [
                p for p in self.politica.pendencias_emissao(fis, res) if p["regra_id"].startswith("POL-01")
            ]
        ):
            self._ir(fis, fsm.Etapa.REVISAO, resp)
        elif e == fsm.Etapa.CHECAGEM:
            faltam = [
                p for p in self.politica.pendencias_emissao(fis, res) if p["regra_id"].startswith("POL-01")
            ]
            if faltam:
                self._ir(fis, fsm.Etapa.COLETA, resp)
            else:
                self._ir(fis, fsm.Etapa.REVISAO, resp)

    # -- falas de template (sempre com números do estado) ------------------------
    @staticmethod
    def _fala_guarda(decisoes: list[Decisao]) -> str:
        regras = {d.rule_id for d in decisoes}
        partes = []
        if "POL-06" in regras:
            partes.append(
                "Não executo instruções fora do protocolo; registrei a ocorrência e sigo o roteiro."
            )
        if "POL-03" in regras:
            partes.append(
                "Eu não assino nem aprovo laudo: a assinatura é sua, depois de conferir o hash do rascunho."
            )
        if "POL-07" in regras:
            if any(d.ocorrencia == "pressao" for d in decisoes):
                partes.append(
                    "Não posso alterar o valor sem nova evidência: o número vem da checagem, não do "
                    "pedido. Registrei a ocorrência de pressão. Se há algo a corrigir, envie nova "
                    "evidência (vídeo, foto ou documento)."
                )
            else:
                partes.append(
                    "O valor não muda por pedido: vou usar o resultado da checagem da nova evidência."
                )
        return " ".join(partes)

    def _fatos(
        self, fis: Fiscalizacao, res: ResultadoVerificacao, resp: RespostaTurno, texto: str = "", ev_nova=None
    ) -> list[str]:
        """Frases que afirmam resultado (checagens, declarações e ações do turno), por template a partir do
        estado (`fatos.py`). O LLM não afirma resultado: só conduz."""
        partes: list[str] = []
        vistos: set[str] = set()
        plano = any(a.acao == "planejar_metodo" and a.ok for a in resp.acoes)
        for a in resp.acoes:
            if a.origem == "llm" and not a.permitido:
                motivo = a.resultado.split(": ", 1)[-1].split(" Pendências:")[0].rstrip(".")
                partes.append(f"Não executei {a.acao}: {motivo}.")
            elif a.acao == "emitir_rascunho":
                pend = (a.dados or {}).get("pendencias") or []
                if a.ok:
                    h = (a.dados or {}).get("hash_raiz", "")
                    partes.append(f"Rascunho emitido (hash {h[:12]}). Confira o hash e assine com o PIN; eu não "
                                  "assino.")
                elif pend:
                    faltas = "; ".join(
                        str(p.get("falta")) + (f" ({p['campo']})" if p.get("campo") else "") for p in pend[:3]
                    )
                    partes.append(f"Rascunho bloqueado: {len(pend)} pendência(s). Falta: {faltas}.")
                else:
                    motivo = a.resultado.split(": ", 1)[-1].split(" Pendências:")[0].rstrip(".")
                    partes.append(f"Não emiti o rascunho: {motivo}.")
            elif a.acao == "solicitar_assinatura":
                if a.ok:
                    partes.append("Rascunho enviado para a sua assinatura: confira o hash e assine com o PIN; eu não "
                                  "assino.")
                else:
                    pend = (a.dados or {}).get("pendencias") or []
                    faltas = "; ".join(str(p.get("falta")) for p in pend[:3])
                    motivo = faltas or a.resultado.split(": ", 1)[-1].split(" Pendências:")[0].rstrip(".")
                    partes.append(f"Não enviei para assinatura: {motivo}.")
            elif a.acao == "registrar_justificativa" and a.permitido and a.ok:
                campo = str(a.argumentos.get("campo") or "")
                partes.append(f"Justificativa do fiscal registrada ({fatos_mod.rotulo(campo)}): a divergência "
                              "continua no laudo, com as suas palavras; o valor não muda.")
            elif a.acao == "planejar_metodo" and a.ok:
                partes.extend(self._fala_plano(fis, res))
            elif a.acao == "carregar_operacao" and a.ok:
                if not plano:
                    partes.extend(self._fala_triagem(fis))
            elif a.checagem_id and a.permitido:
                chk = next((c for c in fis.checagens if c.id == a.checagem_id), None)
                if chk is None:
                    continue
                if chk.ferramenta in _LEITURAS:
                    partes.append(fatos_mod.fato_leitura(chk))
                    continue
                campo = self._campo_de_chk(fis, chk.id)
                chave = f"{chk.ferramenta}:{campo or chk.id}"
                if chave in vistos:
                    continue
                vistos.add(chave)
                partes.append(fatos_mod.fato_checagem(chk, campo, res.campos, fis))
            elif a.acao == "declaracao_independencia":
                partes.append(a.resultado)
        if resp.alegacoes:
            trechos = "; ".join(f"«{mascarar(str(x.get('trecho')))}»" for x in resp.alegacoes[:3])
            partes.append(f"Anotei como alegação sua: {trechos}. O resultado do laudo vem das checagens.")
        if not partes and texto and ev_nova is None:
            if _RX_O_QUE_FALTA.search(decl.norm(texto)):
                pend = self.politica.pendencias_emissao(fis, res)
                faltas = "; ".join(
                    str(p.get("falta")) + (f" ({p['campo']})" if p.get("campo") else "") for p in pend[:3]
                )
                partes.append(f"Falta para o rascunho: {faltas}." if pend else
                              "Nada falta: todos os requisitos têm evidência.")
            else:
                partes = fatos_mod.fatos_da_pergunta(texto, fis, res.campos)
        return partes

    def _proximo_passo(self, fis: Fiscalizacao, res: ResultadoVerificacao) -> str:
        if residual_mod.FERRAMENTA in self.registro and (rp := residual_pendente(fis)) is not None:
            return f"Próximo passo: {rp.pedido.texto}"
        pend = self.politica.pendencias_emissao(fis, res)
        if pend:
            p = pend[0]
            falta = str(p.get("falta"))
            if " — nova coleta: " in falta:  # o motivo inteiro já foi dito no fato; o próximo passo é a coleta
                falta = "nova coleta: " + falta.split(" — nova coleta: ", 1)[1]
            return f"Próximo passo: {falta}" + (f" ({p['campo']})" if p.get("campo") else "") + "."
        if fis.estado_fsm == fsm.Etapa.REVISAO:
            return "Todos os requisitos têm evidência. Para gerar o rascunho, diga «emitir o laudo» ou use o botão."
        return ""

    def _fala_template(self, fis: Fiscalizacao, res: ResultadoVerificacao, resp: RespostaTurno) -> str:
        """Fatos do turno + condução por template (o próximo passo vem das pendências da política)."""
        partes = list(resp.fatos)
        ja_listado = any(p.startswith(("Rascunho bloqueado", "Falta para o rascunho")) for p in partes)
        precisa = not ja_listado and (not partes or fis.estado_fsm in (fsm.Etapa.COLETA, fsm.Etapa.REVISAO))
        passo = self._proximo_passo(fis, res) if precisa else ""
        if passo and passo.removeprefix("Próximo passo: ") not in " ".join(partes):
            partes.append(passo)
        return " ".join(partes) or "Entendido."

    @staticmethod
    def _fala_triagem(fis: Fiscalizacao) -> list[str]:
        """Por que a operação está na amostra (prioridade de verificação, nunca acusação)."""
        tri = next((c for c in reversed(fis.checagens) if c.ferramenta == "carregar_operacao" and c.status == "ok"),
                   None)
        if tri is None:
            return []
        t = tri.resultado.get("triagem") or {}
        motivos = "; ".join(re.sub(r"\s*\(\+\d+\)", "", str(m)) for m in t.get("motivos") or [])
        nivel = _NIVEL_FALADO.get(str(t.get("prioridade_nivel")), "sem sinal")
        return [f"Prioridade de verificação {nivel}" + (f": {motivos}" if motivos else "")
                + ". Isso orienta a amostra; não é indício de irregularidade."]

    @staticmethod
    def _fala_plano(fis: Fiscalizacao, res: ResultadoVerificacao) -> list[str]:
        """Triagem (por que está na amostra), método pela regra e o que vai ser pedido."""
        partes: list[str] = Condutor._fala_triagem(fis)
        plano = next((c for c in reversed(fis.checagens) if c.ferramenta == "planejar_metodo" and c.status == "ok"),
                     None)
        enq = (plano.resultado.get("enquadramento_normativo") if plano else None) or ""
        metodo = _METODO_FALADO.get(str(fis.metodo), str(fis.metodo or "definido"))
        partes.append(f"Método pela regra: {metodo}" + (f" (enquadramento {enq})" if enq and enq not in metodo
                                                         else "") + ".")
        reqs = [r.get("pedido") or r.get("descricao", "") for r in res.requisitos if r.get("obrigatorio", True)][:4]
        if reqs:
            partes.append("Vou precisar de: " + "; ".join(reqs) + ".")
        return partes

    @staticmethod
    def _campo_de_chk(fis: Fiscalizacao, chk_id: str) -> str | None:
        """Campo do laudo afetado pela checagem: o que a cita (avaliar_regras) ou o do mapa provisório."""
        citado = [c.campo for c in fis.campos.values() if chk_id in c.checagens and c.campo.count(":") >= 2]
        if citado:
            return citado[0]
        from laudo.agent.verificador import campo_da_checagem

        chk = next((c for c in fis.checagens if c.id == chk_id), None)
        return campo_da_checagem(chk) if chk else None

    # -- ações humanas (fora do alcance do LLM) ----------------------------------
    def assinar(
        self, fis_id: str, papel: str, nome_ref: str, hash_confirmado: str, pin_ok: bool
    ) -> RespostaTurno:
        """Assinatura humana (POL-03): exige PIN conferido pela interface e o hash raiz exato do último
        rascunho, sem evidência nova depois dele."""
        from laudo.tools import laudo as ferr_laudo

        fis = self.repo.carregar(fis_id)
        resp = RespostaTurno(fiscalizacao_id=fis.id, turno=0, etapa=fis.estado_fsm, fala="")
        with otel.contexto_fiscalizacao(fis.id), otel.span("humano.assinar", **{"laudo.papel": papel}):
            rasc = ferr_laudo.ultimo_rascunho(fis)
            # o rascunho que vai ser assinado (JSON da cadeia) e a data de referência dele: o selado usa a
            # mesma (a emissão não recebe `hoje`; com `self.hoje` diferente, o selado sairia com outra data)
            rascunho = self._rascunho_emitido(fis, rasc)
            data_ref = _data_do_laudo(rascunho) or self.hoje
            if fis.estado_fsm == fsm.Etapa.RASCUNHO:
                fsm.transitar(fis, fsm.Etapa.ASSINATURA)
            erro = None
            if fis.estado_fsm != fsm.Etapa.ASSINATURA:
                erro = f"etapa {fis.estado_fsm} não aceita assinatura"
            elif not rasc:
                erro = "não há rascunho emitido"
            elif rasc.get("hash_raiz") != hash_confirmado:
                erro = "hash confirmado não confere com o do último rascunho"
            elif any(
                e.tipo != "declaracao"
                for e in fis.evidencias[[x.id for x in fis.evidencias].index(rasc["evidencia_id"]) + 1 :]
            ):
                erro = "há evidência ou ocorrência nova depois do rascunho; emita o rascunho de novo"
            elif not pin_ok:
                erro = "PIN não confirmado"
            if erro:
                d = otel.registrar_decisao("POL-03", "negar", "assinar", erro, **{"policy.origem": "humano"})
                resp.fala, resp.fala_origem = f"Assinatura recusada: {erro}.", "guarda"
                resp.acoes.append(
                    AcaoExecutada(
                        acao="assinar",
                        origem="humano",
                        permitido=False,
                        rule_id="POL-03",
                        resultado=erro,
                        span_id=d,
                    )
                )
                return resp
            span_d = otel.registrar_decisao(
                "POL-03",
                "permitir",
                "assinar",
                "assinatura humana com hash e PIN",
                **{"policy.origem": "humano"},
            )
            fis.aprovacoes.append(
                AprovacaoHumana(
                    papel=papel,
                    nome_ref=nome_ref,  # type: ignore[arg-type]
                    hash_assinado=hash_confirmado,
                )
            )
            fsm.transitar(fis, fsm.Etapa.SELADO, humano=True)
            res = self.verificador.recalcular(fis)
            selado = ferr_laudo.selar(fis, res, hoje=data_ref)
            self.repo.salvar(fis)
            # Confere na hora o que foi selado contra o rascunho assinado (cadeia de hash): conteúdo do
            # JSON (hash raiz recalculado), HTML, cadeia e aprovações
            conf = selo_mod.verificar_em_disco(Path(selado["laudo_json"]).parent, fis)
            with otel.span("audit.conferir_selo", **{"selo.valido": conf.valido, "selo.motivo": conf.motivo}):
                pass
            selado = {**selado, "conteudo_confere": conf.valido, "verificacao": conf.motivo}
        resp.etapa = fis.estado_fsm
        resp.fala, resp.fala_origem = (
            "Laudo assinado e selado. Nenhuma alteração é possível a partir daqui.",
            "template",
        )
        if not selado["conteudo_confere"]:
            # defesa em profundidade: `selar` copia o rascunho assinado; se o selado não conferir com ele
            # (laudo.audit.selo), a resposta leva o motivo no aviso
            resp.avisos.append(f"laudo selado não confere com o rascunho assinado: {selado['verificacao'][:300]}")
        resp.laudo = selado
        resp.acoes.append(
            AcaoExecutada(
                acao="assinar",
                origem="humano",
                ok=True,
                rule_id="POL-03",
                resultado="selado",
                span_id=span_d,
                dados=selado,
            )
        )
        self.repo.anexar_conversa(
            fis.id,
            {"turno": "assinatura", "agente": resp.fala, "etapa": resp.etapa, "acoes": ["assinar:humano"]},
        )
        return resp

    @staticmethod
    def _rascunho_emitido(fis: Fiscalizacao, rasc: dict[str, Any] | None) -> dict[str, Any] | None:
        """JSON do último rascunho (o arquivo da evidência `documento` com `meta.laudo` na cadeia)."""
        ev = est.evidencia_por_id(fis, rasc.get("evidencia_id")) if rasc else None
        return selo_mod.ler_laudo(ev.caminho if ev else None)

    def ultimo_laudo(self, fis_id: str) -> dict[str, Any] | None:
        from laudo.tools import laudo as ferr_laudo

        return ferr_laudo.ultimo_rascunho(self.repo.carregar(fis_id))
