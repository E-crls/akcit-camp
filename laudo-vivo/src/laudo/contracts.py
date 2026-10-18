"""Contratos compartilhados do Laudo Vivo.

Este módulo é a fronteira entre as peças construídas em paralelo (dados, regras, visão,
documentos fiscais, agente, interface). Mudanças aqui precisam ser combinadas: todas as
outras partes importam daqui.

Princípios (ver docs/arquitetura.md):
- Ferramentas calculam; a política decide se uma transição pode acontecer; o verificador
  atribui o status; o humano assina. O LLM conduz a conversa, extrai alegações e redige
  texto citando IDs, mas nunca calcula número nem define status.
- Toda ferramenta devolve um `Envelope`. Erro nunca vira valor inventado: vira campo
  "pendente" com motivo.
- Evidência é append-only e encadeada por hash.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Callable
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Envelope comum das ferramentas
# ---------------------------------------------------------------------------


class CodigoErro(StrEnum):
    TIMEOUT = "TIMEOUT"
    SEM_DADOS = "SEM_DADOS"
    NUVEM = "NUVEM"
    ENTRADA_INVALIDA = "ENTRADA_INVALIDA"
    FORA_DO_ESCOPO = "FORA_DO_ESCOPO"
    BLOQUEADO_POLITICA = "BLOQUEADO_POLITICA"
    ERRO_INTERNO = "ERRO_INTERNO"


class ErroFerramenta(BaseModel):
    code: CodigoErro
    retryable: bool = False
    msg: str


class Envelope(BaseModel):
    """Resposta padrão de toda ferramenta."""

    ok: bool
    data: dict[str, Any] | None = None
    error: ErroFerramenta | None = None
    ferramenta: str
    trace_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    latency_ms: int = 0
    fonte_versao: str = ""  # ex.: "sicor@2026-10-07", "rulebook-mcr-2-7@0.1.0"

    @classmethod
    def sucesso(cls, ferramenta: str, data: dict[str, Any], fonte_versao: str = "", t0: float | None = None):
        return cls(ok=True, data=data, ferramenta=ferramenta, fonte_versao=fonte_versao,
                   latency_ms=_ms(t0))

    @classmethod
    def falha(cls, ferramenta: str, code: CodigoErro, msg: str, retryable: bool = False,
              t0: float | None = None, data: dict[str, Any] | None = None, fonte_versao: str = ""):
        return cls(ok=False, data=data, error=ErroFerramenta(code=code, retryable=retryable, msg=msg),
                   ferramenta=ferramenta, latency_ms=_ms(t0), fonte_versao=fonte_versao)


def _ms(t0: float | None) -> int:
    return int((time.perf_counter() - t0) * 1000) if t0 is not None else 0


# ---------------------------------------------------------------------------
# Status e classes de evidência
# ---------------------------------------------------------------------------

StatusChecagem = Literal["ok", "divergente", "indeterminado", "erro"]
StatusCampo = Literal["verificado", "divergente", "pendente", "abstencao"]
TipoEvidencia = Literal["foto", "video", "audio", "nfe_xml", "gta", "documento", "satelite", "ocorrencia",
                        "declaracao", "quadro_chave"]
MetodoFiscalizacao = Literal["remoto", "documental", "presencial", "autofiscalizacao_assistida"]
TipoFiscalizacao = Literal["fiscalizacao_aplicacao", "excecao_socioambiental", "comprovacao_perdas"]

# Mapeamento do status próprio de cada ferramenta para o vocabulário comum `StatusChecagem`.
# Ferramentas devem preferir devolver `data["status"]` já no vocabulário comum; quando não for
# possível, o executor usa este mapa.
_MAPA_STATUS: dict[str, str] = {
    "ok": "ok", "verificado": "ok", "dentro": "ok", "coerente": "ok", "conforme": "ok", "valido": "ok",
    "divergente": "divergente", "fora": "divergente", "inconsistente": "divergente", "invalido": "divergente",
    "válido": "ok", "integra": "ok", "íntegra": "ok",
    "nao_conforme": "divergente", "incoerente": "divergente", "inválido": "divergente", "suspeita": "divergente",
    "indeterminado": "indeterminado", "pendente": "indeterminado", "abstencao": "indeterminado",
    "abstenção": "indeterminado", "inconclusivo": "indeterminado",
    "nuvem": "indeterminado", "nao_verificado": "indeterminado",
    "erro": "erro",
}


def para_status_checagem(status: str | None) -> str:
    """Converte o status de uma ferramenta para `StatusChecagem` (desconhecido → "indeterminado")."""
    if not status:
        return "indeterminado"
    return _MAPA_STATUS.get(str(status).strip().lower(), "indeterminado")


class GPS(BaseModel):
    lat: float
    lon: float
    precisao_m: float | None = None
    fonte: Literal["exif", "app", "manual", "desconhecida"] = "desconhecida"
    capturada_em: datetime | None = None
    mock: bool | None = None  # localização simulada detectada pelo app (None = desconhecido)


# ---------------------------------------------------------------------------
# Caso: a operação de crédito rural a fiscalizar
# ---------------------------------------------------------------------------


class ItemFinanciado(BaseModel):
    """Um item do orçamento/projeto que precisa ser comprovado."""

    id: str
    tipo: Literal["bovinos", "cerca", "curral", "galpao", "maquina", "lavoura", "pastagem", "benfeitoria",
                  "outro"]
    descricao: str
    quantidade: float | None = None
    unidade: str | None = None  # "cabeca", "UA_450kg" (unidade usual do Sicor), "m", "m2", "un", "ha"
    valor_rs: float | None = None
    categoria_animal: str | None = None  # ex.: "garrote", "novilha", "vaca"
    sexo: Literal["M", "F", "misto"] | None = None
    cronograma_fim: date | None = None  # fim do cronograma físico (benfeitorias, MCR 2-7 item 16)
    exige_numero_serie: bool = True  # máquinas


class Operacao(BaseModel):
    """Operação de crédito rural (espelha campos públicos do Sicor/BCB + dados do projeto).

    Nunca carregar CPF/CNPJ do tomador aqui; usar `tomador_ref` pseudonimizado.
    """

    ref_bacen: str
    tomador_ref: str = "anon"
    tomador_doc_sha256: str | None = None  # hash do CPF/CNPJ com sal por instalação (nunca o documento)
    uf: str = "GO"
    municipio_ibge: str | None = None
    municipio_nome: str | None = None
    instituicao: str | None = None
    finalidade: Literal["custeio", "investimento", "comercializacao", "industrializacao"] | None = None
    empreendimento: str | None = None
    data_contratacao: date | None = None
    data_liberacao: date | None = None
    valor_rs: float | None = None
    area_financiada_ha: float | None = None  # VL_AREA_FINANC: proporcional ao crédito, não é o pasto
    area_informada_ha: float | None = None
    area_total_ha: float | None = None  # "área total" do MCR 2-7 item 5 (quando conhecida)
    modulos_fiscais: float | None = None
    fonte_recursos: Literal["controlados", "direcionados", "livres", "nao_controlados"] | None = None
    car_ref: str | None = None  # código do CAR (dado público do imóvel) ou referência pseudonimizada
    codigo_estabelecimento: str | None = None  # código da exploração na defesa sanitária (Agrodefesa)
    glebas_wkt: list[str] = Field(default_factory=list)  # WGS84
    itens: list[ItemFinanciado] = Field(default_factory=list)
    fonte: str = "sicor"  # "sicor", "sintetico", "piloto"


# ---------------------------------------------------------------------------
# Evidências, checagens, campos do laudo
# ---------------------------------------------------------------------------


class Evidencia(BaseModel):
    id: str = Field(default_factory=lambda: "ev_" + uuid.uuid4().hex[:10])
    tipo: TipoEvidencia
    caminho: str | None = None  # caminho local do arquivo (fora do repositório quando tiver PII)
    sha256: str
    hash_anterior: str = ""
    capturada_em: datetime | None = None
    recebida_em: datetime = Field(default_factory=datetime.now)
    gps: GPS | None = None
    derivada_de: str | None = None  # ex.: quadro-chave → id do vídeo de origem
    meta: dict[str, Any] = Field(default_factory=dict)  # EXIF, transcrição, phash, etc.


class Checagem(BaseModel):
    id: str = Field(default_factory=lambda: "chk_" + uuid.uuid4().hex[:10])
    ferramenta: str
    entrada_hash: str
    status: StatusChecagem
    resultado: dict[str, Any] = Field(default_factory=dict)
    evidencias: list[str] = Field(default_factory=list)
    item_id: str | None = None
    regra_id: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    criada_em: datetime = Field(default_factory=datetime.now)
    substitui: list[str] = Field(default_factory=list)  # ids de checagens que esta torna obsoletas
    fonte_versao: str = ""


class CampoLaudo(BaseModel):
    campo: str  # ex.: "item:bov1:quantidade", "item:cerca1:existencia", "documento:nfe"
    valor: Any | None = None
    status: StatusCampo
    regra_id: str
    evidencias: list[str] = Field(default_factory=list)
    checagens: list[str] = Field(default_factory=list)
    span_ids: list[str] = Field(default_factory=list)
    motivo: str = ""
    ressalvas: list[str] = Field(default_factory=list)  # ex.: "cadeia ICP-Brasil não verificada offline"
    justificativa_humana: str | None = None


class Bloqueio(BaseModel):
    """Pendência que impede uma transição (compartilhado por regras, política e emissão do laudo)."""

    regra_id: str
    campo: str | None = None
    status: StatusCampo | None = None
    falta: str


class Requisito(BaseModel):
    campo: str
    item_id: str | None = None
    descricao: str
    pedido: str = ""  # instrução de captura para o fiscal
    tipos_evidencia: list[str] = Field(default_factory=list)
    ferramenta: str | None = None
    regra_id: str
    obrigatorio: bool = True


class Alegacao(BaseModel):
    """Afirmação extraída da fala ou de documento, com ponteiro para o trecho de origem."""

    id: str = Field(default_factory=lambda: "al_" + uuid.uuid4().hex[:10])
    texto: str
    campo: str | None = None
    valor: Any | None = None
    unidade: str | None = None
    evidencia_id: str | None = None
    inicio: int | None = None
    fim: int | None = None


class Ocorrencia(BaseModel):
    id: str = Field(default_factory=lambda: "oc_" + uuid.uuid4().hex[:10])
    tipo: Literal["pressao", "injecao", "fora_de_escopo", "falha_ferramenta", "outro"]
    descricao: str
    evidencia_ref: str | None = None
    em: datetime = Field(default_factory=datetime.now)


class AprovacaoHumana(BaseModel):
    papel: Literal["fiscal", "agronomo_responsavel", "analista_if"]
    nome_ref: str
    em: datetime = Field(default_factory=datetime.now)
    hash_assinado: str


class Fiscalizacao(BaseModel):
    """Estado de uma fiscalização (append-only no que diz respeito a evidências e checagens)."""

    id: str = Field(default_factory=lambda: "fis_" + uuid.uuid4().hex[:10])
    operacao: Operacao
    tipo: TipoFiscalizacao = "fiscalizacao_aplicacao"
    metodo: MetodoFiscalizacao | None = None
    estado_fsm: str = "BRIEFING"
    rulebook_versao: str = ""
    rulebooks: list[str] = Field(default_factory=list)  # ex.: ["mcr_2_7@0.1.0"]
    data_referencia: date | None = None  # data "de hoje" usada nas regras (replay determinístico)
    data_fiscalizacao: date | None = None
    prioridade_verificacao: str | None = None  # vinda da triagem da carteira (alta/média/baixa/sem sinal)
    requisitos: list[dict[str, Any]] = Field(default_factory=list)  # ver `Requisito`
    evidencias: list[Evidencia] = Field(default_factory=list)
    alegacoes: list[dict[str, Any]] = Field(default_factory=list)  # ver `Alegacao`
    checagens: list[Checagem] = Field(default_factory=list)
    campos: dict[str, CampoLaudo] = Field(default_factory=dict)
    ocorrencias: list[Ocorrencia] = Field(default_factory=list)
    aprovacoes: list[AprovacaoHumana] = Field(default_factory=list)
    laudos: list[dict[str, Any]] = Field(default_factory=list)  # rascunhos emitidos (hash, caminhos)
    criada_em: datetime = Field(default_factory=datetime.now)

    def ultimo_hash(self) -> str:
        """sha256 do conteúdo da última evidência. Para a cabeça da cadeia use `laudo.audit.hashchain`."""
        return self.evidencias[-1].sha256 if self.evidencias else ""


# ---------------------------------------------------------------------------
# Registro de ferramentas
# ---------------------------------------------------------------------------


class Ferramenta(BaseModel):
    """Descrição de uma ferramenta exposta ao agente (e ao servidor MCP)."""

    nome: str
    descricao: str
    entrada: type[BaseModel]
    funcao: Callable[..., Envelope]
    deterministica: bool = True
    timeout_s: float = 10.0

    model_config = {"arbitrary_types_allowed": True}

    def schema_ollama(self) -> dict[str, Any]:
        return {"type": "function", "function": {"name": self.nome, "description": self.descricao,
                                                 "parameters": self.entrada.model_json_schema()}}


REGISTRO: dict[str, Ferramenta] = {}


def registrar(nome: str, descricao: str, entrada: type[BaseModel], deterministica: bool = True,
              timeout_s: float = 10.0, registro: dict[str, Ferramenta] | None = None):
    """Decorador: registra uma função `f(args: Entrada) -> Envelope` como ferramenta.

    `registro` permite que testes usem um dicionário próprio sem tocar o `REGISTRO` global.
    """

    def deco(funcao: Callable[..., Envelope]):
        alvo = REGISTRO if registro is None else registro
        alvo[nome] = Ferramenta(nome=nome, descricao=descricao, entrada=entrada, funcao=funcao,
                                deterministica=deterministica, timeout_s=timeout_s)
        return funcao

    return deco


# ---------------------------------------------------------------------------
# Utilidades de hash
# ---------------------------------------------------------------------------


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_arquivo(caminho: str, bloco: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        while chunk := f.read(bloco):
            h.update(chunk)
    return h.hexdigest()


def hash_entrada(obj: Any) -> str:
    """Hash canônico de argumentos (para idempotência e trilha)."""
    s = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]
