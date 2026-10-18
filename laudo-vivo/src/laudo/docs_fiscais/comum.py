"""Utilidades comuns: identificadores, chave de acesso, critérios de conciliação e textos livres.

Nenhuma função daqui devolve documento (CPF/CNPJ) em claro: saídas usam máscara e hash.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

StatusCriterio = Literal["ok", "divergente", "indeterminado"]
STATUS_CAMPO: dict[str, str] = {"ok": "verificado", "divergente": "divergente", "indeterminado": "pendente"}
_GRAVIDADE = {"ok": 0, "indeterminado": 1, "divergente": 2}


class Criterio(BaseModel):
    """Resultado de uma checagem determinística sobre um documento.

    `status` usa o vocabulário de `Checagem` (ok/divergente/indeterminado); `status_campo_sugerido`
    é o mapeamento direto para o laudo (verificado/divergente/pendente). Quem atribui o status final
    do campo é o verificador.
    """

    id: str
    campo: str
    status: StatusCriterio
    regra_id: str
    motivo: str
    valores: dict[str, Any] = Field(default_factory=dict)

    @property
    def status_campo_sugerido(self) -> str:
        return STATUS_CAMPO[self.status]

    def saida(self) -> dict[str, Any]:
        d = self.model_dump()
        d["status_campo_sugerido"] = self.status_campo_sugerido
        return d


class NaoVerificado(BaseModel):
    """Aspecto que não dá para verificar offline. Vira alerta no laudo; nunca vira divergência."""

    id: str
    regra_id: str
    motivo: str
    consequencia: Literal["alerta"] = "alerta"


def pior(*status: str) -> StatusCriterio:
    """Status mais grave (divergente > indeterminado > ok)."""
    return max(status, key=lambda s: _GRAVIDADE[s]) if status else "ok"  # type: ignore[return-value]


def agregar_campos(criterios: list[Criterio]) -> dict[str, dict[str, Any]]:
    """Agrega critérios por campo do laudo: o status do campo é o do critério mais grave."""
    campos: dict[str, dict[str, Any]] = {}
    for c in criterios:
        atual = campos.get(c.campo)
        if atual is None:
            campos[c.campo] = {"status": c.status, "status_campo_sugerido": c.status_campo_sugerido,
                               "regra_id": c.regra_id, "motivos": [c.motivo], "criterios": [c.id]}
            continue
        atual["criterios"].append(c.id)
        atual["motivos"].append(c.motivo)
        if _GRAVIDADE[c.status] > _GRAVIDADE[atual["status"]]:
            atual["status"] = c.status
            atual["status_campo_sugerido"] = c.status_campo_sugerido
            atual["regra_id"] = c.regra_id
    return campos


# ---------------------------------------------------------------------------
# CPF e CNPJ (inclusive CNPJ alfanumérico, NT Conjunta 2025.001 / IN RFB 2.229/2024)
# ---------------------------------------------------------------------------

_RE_CNPJ = re.compile(r"^[0-9A-Z]{12}[0-9]{2}$")
_RE_CPF = re.compile(r"^[0-9]{11}$")


def so_alnum(s: str | None) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", s or "").upper()


def _valor_char(c: str) -> int:
    """Valor do caractere no cálculo do DV: código ASCII menos 48 (dígitos mantêm o valor)."""
    return ord(c) - 48


def _dv_mod11(corpo: str, pesos: list[int]) -> int:
    r = sum(_valor_char(c) * p for c, p in zip(corpo, pesos, strict=True)) % 11
    return 0 if r < 2 else 11 - r


def dv_cnpj(base12: str) -> str:
    base12 = base12.upper()
    d1 = _dv_mod11(base12, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = _dv_mod11(base12 + str(d1), [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return f"{d1}{d2}"


def cnpj_valido(cnpj: str | None) -> bool:
    c = so_alnum(cnpj)
    if not _RE_CNPJ.match(c) or len(set(c)) == 1:
        return False
    return dv_cnpj(c[:12]) == c[12:]


def dv_cpf(base9: str) -> str:
    d1 = sum(int(c) * p for c, p in zip(base9, range(10, 1, -1), strict=True)) * 10 % 11 % 10
    d2 = sum(int(c) * p for c, p in zip(base9 + str(d1), range(11, 1, -1), strict=True)) * 10 % 11 % 10
    return f"{d1}{d2}"


def cpf_valido(cpf: str | None) -> bool:
    c = so_alnum(cpf)
    if not _RE_CPF.match(c) or len(set(c)) == 1:
        return False
    return dv_cpf(c[:9]) == c[9:]


def tipo_documento(doc: str | None) -> Literal["cpf", "cnpj"] | None:
    c = so_alnum(doc)
    if len(c) == 11 and c.isdigit():
        return "cpf"
    if len(c) == 14:
        return "cnpj"
    return None


def mascarar_documento(doc: str | None) -> str | None:
    """CPF: ***.456.789-** ; CNPJ: 12.345.678/****-** (a raiz do CNPJ identifica a empresa)."""
    c = so_alnum(doc)
    if not c:
        return None
    t = tipo_documento(c)
    if t == "cpf":
        return f"***.{c[3:6]}.{c[6:9]}-**"
    if t == "cnpj":
        return f"{c[0:2]}.{c[2:5]}.{c[5:8]}/****-**"
    return "*" * len(c)


def hash_documento_publico(doc: str | None) -> str | None:
    """Hash **público** (sem sal, formato v1) de CPF/CNPJ: o que um sistema de fora (cadastro da IF, gerador do
    golden set) sabe calcular. O espaço de CPFs é pequeno e esse hash se desfaz por força bruta: só é aceito como
    ENTRADA, no formato `sha256:<hex>`, e é convertido na hora (`privacidade.hash_referencia`); nunca é guardado."""
    c = so_alnum(doc)
    if not c:
        return None
    return hashlib.sha256(f"laudo-vivo/doc/v1::{c}".encode()).hexdigest()


def hash_documento(doc: str | None, sal: str | None = None) -> str | None:
    """Hash de CPF/CNPJ para comparar partes sem expor o documento: HMAC-SHA256 com o **sal da instalação**
    (`laudo.privacidade`, fora do repositório) sobre o hash público. É o que vai para estado, trace e laudo.
    `sal` explícito só em teste."""
    from laudo.privacidade import hash_de_publico

    publico = hash_documento_publico(doc)
    return hash_de_publico(publico, sal) if publico else None


def mascarar_nome(nome: str | None, tipo_doc: str | None) -> str | None:
    """Nome de pessoa física vira iniciais; razão social (CNPJ) fica como está."""
    if nome is None:
        return None
    if tipo_doc == "cnpj":
        return nome
    return " ".join(p[0] + "***" for p in nome.split() if p)


# ---------------------------------------------------------------------------
# Chave de acesso da NF-e (MOC 4.00; NT 2025.001 para o CNPJ alfanumérico)
# ---------------------------------------------------------------------------

RE_CHAVE = re.compile(r"^[0-9]{6}[0-9A-Z]{12}[0-9]{26}$")


def dv_chave(chave43: str) -> int:
    """DV módulo 11 da chave: pesos 2..9 da direita para a esquerda; resto 0 ou 1 dá DV 0."""
    soma = 0
    peso = 2
    for c in reversed(chave43.upper()):
        soma += _valor_char(c) * peso
        peso = 2 if peso == 9 else peso + 1
    r = soma % 11
    return 0 if r < 2 else 11 - r


def montar_chave(c_uf: str, aamm: str, doc_emitente: str, modelo: str, serie: int | str, n_nf: int | str,
                 tp_emis: int | str, c_nf: str) -> str:
    """Monta a chave de 44 posições (CPF do emitente vai com zeros à esquerda até 14 posições)."""
    doc = so_alnum(doc_emitente).zfill(14)
    corpo = f"{c_uf}{aamm}{doc}{int(modelo):02d}{int(serie):03d}{int(n_nf):09d}{int(tp_emis)}{c_nf}"
    if len(corpo) != 43:
        raise ValueError(f"chave com {len(corpo)} posições antes do DV (esperado 43)")
    return corpo + str(dv_chave(corpo))


def decompor_chave(chave: str) -> dict[str, Any]:
    c = chave.upper()
    return {
        "c_uf": c[0:2], "aamm": c[2:6], "ano": 2000 + int(c[2:4]), "mes": int(c[4:6]),
        "doc_emitente": c[6:20], "modelo": c[20:22], "serie": int(c[22:25]), "numero": int(c[25:34]),
        "tp_emis": c[34], "c_nf": c[35:43], "dv": int(c[43]),
    }


def validar_chave(chave: str | None) -> tuple[bool, str]:
    c = (chave or "").upper()
    if not RE_CHAVE.match(c):
        return False, "chave de acesso fora do formato de 44 posições"
    dv = dv_chave(c[:43])
    if dv != int(c[43]):
        return False, f"DV da chave inválido (informado {c[43]}, calculado {dv})"
    return True, "chave de acesso com DV válido"


# ---------------------------------------------------------------------------
# Textos livres: normalização e sinais de injeção (POL-06)
# ---------------------------------------------------------------------------


def normalizar(texto: str | None) -> str:
    """Maiúsculas, sem acento e com espaços simples (para comparar nomes de município)."""
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", t).strip().upper()


_PADROES_INJECAO: list[tuple[str, re.Pattern[str]]] = [
    ("ignorar_regras", re.compile(r"\b(IGNOR|DESCONSIDER|ESQUEC)\w*\b.{0,40}\b(REGRA|INSTRUC|ORIENTAC|ANTERIOR|"
                                  r"POLITICA|VERIFICAC)", re.DOTALL)),
    ("marcar_status", re.compile(r"\b(MARQUE|MARCAR|CLASSIFIQUE|CONSIDERE|DECLARE)\b.{0,40}\b(VERIFICAD|APROVAD|"
                                 r"REGULAR|SEM DIVERGENCIA|TUDO OK)", re.DOTALL)),
    ("modo_privilegiado", re.compile(r"\bMODO\s+(ADMINISTRADOR|ADMIN|DESENVOLVEDOR|DEBUG|MANUTENCAO)\b")),
    ("aprovar_laudo", re.compile(r"\b(APROVE|APROVAR|LIBERE|LIBERAR|ASSINE|ASSINAR|EMITA)\b.{0,30}\b(LAUDO|"
                                 r"RASCUNHO|FISCALIZAC|TUDO)", re.DOTALL)),
    ("prompt", re.compile(r"\b(SYSTEM PROMPT|PROMPT DO SISTEMA|VOCE E UM (ASSISTENTE|AGENTE|MODELO))\b")),
    ("pular_checagem", re.compile(r"\b(NAO VERIFIQUE|PULE A VERIFICAC|NAO CONFIRA|SEM CONFERIR)\w*")),
]


def sinais_injecao(texto: str | None) -> list[str]:
    """IDs dos padrões de instrução embutida encontrados no texto (vazio se nenhum).

    Detector simples e determinístico: serve para registrar ocorrência (POL-06). O texto continua
    sendo tratado como dado; nada aqui altera status de campo.
    """
    t = normalizar(texto)
    return [nome for nome, rx in _PADROES_INJECAO if rx.search(t)]


def sha256_texto(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def brl(v: float) -> str:
    """Valor monetário no padrão brasileiro: R$ 126.000,00."""
    return "R$ " + f"{v:,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")
