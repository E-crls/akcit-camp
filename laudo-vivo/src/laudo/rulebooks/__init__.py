"""Rulebooks: normas do MCR como dados versionados, citáveis e validados.

Cada rulebook é um YAML neste diretório (`mcr_2_7.yaml`, `mcr_2_9.yaml`). Este módulo:

- define o esquema (Pydantic) e recusa YAML malformado ao carregar;
- separa **norma** (`origem: norma`, exige `citacao` literal) de **parâmetro operacional** nosso
  (`origem: parametro_operacional`, exige `justificativa`);
- avalia condições declarativas com lógica de três valores (verdadeiro/falso/indeterminado), para que
  dado ausente vire "indeterminado" (abstenção) e não "falso".

A interpretação das regras (avaliadores de status, prazos) fica em `laudo.tools.regras`.
Ver docs/regras.md (versionamento e revisão por especialista).
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from functools import cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

DIR = Path(__file__).resolve().parent

TipoRegra = Literal["requisito_metodo", "prazo", "requisito_evidencia", "requisito_laudo", "criterio_status"]
OrigemRegra = Literal["norma", "parametro_operacional"]

RE_ID_REGRA = re.compile(r"^(MCR-\d+-\d+-item[0-9A-Za-z]+(-[a-z0-9]+)+|OP-[a-z0-9]+(-[a-z0-9]+)*)$")
RE_ID_PARAM = re.compile(r"^PAR-[a-z0-9]+(-[a-z0-9]+)*$")
RE_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


class Fonte(BaseModel):
    id: str
    descricao: str
    url: str
    acesso: date
    observacao: str = ""


class Revisao(BaseModel):
    estado: Literal["rascunho_tecnico", "revisado_especialista", "aprovado"] = "rascunho_tecnico"
    revisores: list[dict[str, Any]] = Field(default_factory=list)  # {papel, ref, em, versao}
    pendencias: list[str] = Field(default_factory=list)


class Parametro(BaseModel):
    """Parâmetro operacional: escolha nossa (não é norma), sempre com justificativa."""

    id: str
    valor: Any
    unidade: str = ""
    origem: Literal["parametro_operacional"] = "parametro_operacional"
    justificativa: str = Field(min_length=20)
    base_normativa: list[str] = Field(default_factory=list)
    calibrar: str = ""

    @model_validator(mode="after")
    def _id_valido(self):
        if not RE_ID_PARAM.match(self.id):
            raise ValueError(f"id de parâmetro inválido: {self.id}")
        return self


class Regra(BaseModel):
    id: str
    item: str  # localizador do item, ex.: "MCR 2-7-16-b-II"; para parâmetro operacional, "operacional"
    tipo: TipoRegra
    origem: OrigemRegra
    titulo: str
    citacao: str | None = None  # trecho literal curto (conferido por teste contra docs/normas)
    citacoes_adicionais: list[str] = Field(default_factory=list)
    resumo: str = ""
    justificativa: str | None = None
    base_normativa: list[str] = Field(default_factory=list)
    aplica_a: list[str] = Field(default_factory=list)  # tipos de item, "operacao", "laudo", "imovel", "carteira"
    condicao: dict[str, Any] | None = None
    efeito: dict[str, Any] = Field(default_factory=dict)
    avaliador: str | None = None  # None = regra informativa (não executada)
    usado_por: list[str] = Field(default_factory=list)  # ferramentas que executam a regra
    ferramentas: list[str] = Field(default_factory=list)  # checagens lidas pelo avaliador
    parametros: list[str] = Field(default_factory=list)
    evidencias: list[str] = Field(default_factory=list)
    pedido: str = ""  # o que pedir ao fiscal quando faltar evidência
    criterios: dict[str, str] = Field(default_factory=dict)  # status -> descrição legível
    agregacao: Literal["consenso", "qualquer_divergente"] = "consenso"
    bloqueante: bool = True
    vigencia_inicio: date | None = None

    @model_validator(mode="after")
    def _coerente(self):
        if not RE_ID_REGRA.match(self.id):
            raise ValueError(f"id de regra inválido: {self.id}")
        if self.origem == "norma" and not (self.citacao and self.citacao.strip()):
            raise ValueError(f"{self.id}: regra de norma exige citacao literal")
        if self.origem == "parametro_operacional":
            if not (self.justificativa and len(self.justificativa.strip()) >= 20):
                raise ValueError(f"{self.id}: parâmetro operacional exige justificativa")
            if not self.id.startswith("OP-"):
                raise ValueError(f"{self.id}: regra operacional deve ter prefixo OP-")
        if self.origem == "norma" and not self.id.startswith("MCR-"):
            raise ValueError(f"{self.id}: regra de norma deve ter prefixo MCR-")
        if self.tipo == "criterio_status" and self.avaliador and not self.criterios:
            raise ValueError(f"{self.id}: critério de status executável precisa descrever os critérios")
        return self


class CampoFluxo(BaseModel):
    campo: str
    regra: str
    condicao: dict[str, Any] | None = None


class Fluxo(BaseModel):
    descricao: str = ""
    tipos_item: list[str]
    campos: list[CampoFluxo]


class Rulebook(BaseModel):
    id: str
    titulo: str
    versao: str
    vigencia_inicio: date
    vigencia_fim: date | None = None
    norma_base: str
    texto_normativo: str  # caminho relativo à raiz do repositório
    fontes: list[Fonte]
    revisao: Revisao = Field(default_factory=Revisao)
    parametros: list[Parametro] = Field(default_factory=list)
    regras: list[Regra]
    fluxos: dict[str, Fluxo] = Field(default_factory=dict)
    campos_laudo: list[CampoFluxo] = Field(default_factory=list)
    sha256: str = ""  # hash do arquivo YAML carregado (trilha de auditoria)

    @model_validator(mode="after")
    def _referencias(self):
        if not RE_SEMVER.match(self.versao):
            raise ValueError(f"versão não semântica: {self.versao}")
        ids = [r.id for r in self.regras]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            raise ValueError(f"ids de regra duplicados: {sorted(dup)}")
        pids = [p.id for p in self.parametros]
        if len(pids) != len(set(pids)):
            raise ValueError("ids de parâmetro duplicados")
        conhecidos = set(ids)
        for r in self.regras:
            for p in r.parametros:
                if p not in pids:
                    raise ValueError(f"{r.id}: parâmetro desconhecido {p}")
        for nome, f in self.fluxos.items():
            for c in f.campos:
                if c.regra not in conhecidos:
                    raise ValueError(f"fluxo {nome}: regra desconhecida {c.regra}")
        for c in self.campos_laudo:
            if c.regra not in conhecidos:
                raise ValueError(f"campos_laudo: regra desconhecida {c.regra}")
        return self

    # -- consultas ---------------------------------------------------------
    @property
    def fonte_versao(self) -> str:
        return f"rulebook-{self.id}@{self.versao}"

    def regra(self, regra_id: str) -> Regra:
        for r in self.regras:
            if r.id == regra_id:
                return r
        raise KeyError(regra_id)

    def param(self, param_id: str) -> Any:
        for p in self.parametros:
            if p.id == param_id:
                return p.valor
        raise KeyError(param_id)

    def fluxo_do_tipo(self, tipo_item: str) -> tuple[str, Fluxo] | None:
        for nome, f in self.fluxos.items():
            if tipo_item in f.tipos_item:
                return nome, f
        return None


# ---------------------------------------------------------------------------
# Carregamento
# ---------------------------------------------------------------------------

ARQUIVOS = {"mcr-2-7": "mcr_2_7.yaml", "mcr-2-9": "mcr_2_9.yaml"}


@cache
def carregar(rulebook_id: str) -> Rulebook:
    """Carrega e valida um rulebook pelo id (`mcr-2-7`, `mcr-2-9`). Levanta erro se inválido."""
    if rulebook_id not in ARQUIVOS:
        raise KeyError(f"rulebook desconhecido: {rulebook_id}")
    caminho = DIR / ARQUIVOS[rulebook_id]
    bruto = caminho.read_bytes()
    dados = yaml.safe_load(bruto.decode("utf-8"))
    rb = Rulebook.model_validate(dados)
    if rb.id != rulebook_id:
        raise ValueError(f"{caminho.name}: id {rb.id} difere de {rulebook_id}")
    rb.sha256 = hashlib.sha256(bruto).hexdigest()
    return rb


def todos() -> list[Rulebook]:
    return [carregar(i) for i in ARQUIVOS]


def buscar_regra(regra_id: str) -> tuple[Rulebook, Regra]:
    for rb in todos():
        for r in rb.regras:
            if r.id == regra_id:
                return rb, r
    raise KeyError(regra_id)


# ---------------------------------------------------------------------------
# Condições declarativas (lógica de três valores)
# ---------------------------------------------------------------------------
#
# Folha: {campo: "operacao.area_total_ha", op: "gt", valor: 300}
#        valor pode ser {param: "PAR-..."} (resolvido no rulebook)
# Compostas: {todas: [...]}, {alguma: [...]}, {nao: {...}}
# Resultado: True, False ou None (indeterminado: faltou dado para decidir).

_OPS = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "in": lambda a, b: a in b,
    "nin": lambda a, b: a not in b,
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
}


def avaliar_condicao(cond: dict[str, Any] | None, ctx: dict[str, Any], rb: Rulebook | None = None) -> bool | None:
    """Avalia uma condição declarativa sobre `ctx` (dicionário plano com chaves pontuadas)."""
    if cond is None:
        return True
    if "todas" in cond:
        res = [avaliar_condicao(c, ctx, rb) for c in cond["todas"]]
        if any(r is False for r in res):
            return False
        return None if any(r is None for r in res) else True
    if "alguma" in cond:
        res = [avaliar_condicao(c, ctx, rb) for c in cond["alguma"]]
        if any(r is True for r in res):
            return True
        return None if any(r is None for r in res) else False
    if "nao" in cond:
        r = avaliar_condicao(cond["nao"], ctx, rb)
        return None if r is None else not r
    campo, op = cond["campo"], cond["op"]
    alvo = ctx.get(campo)
    if op == "existe":
        return alvo is not None
    if op not in _OPS:
        raise ValueError(f"operador desconhecido: {op}")
    valor = cond.get("valor")
    if isinstance(valor, dict) and "param" in valor:
        if rb is None:
            raise ValueError("condição com parâmetro exige o rulebook")
        valor = rb.param(valor["param"])
    if alvo is None:
        return None
    return bool(_OPS[op](alvo, valor))
