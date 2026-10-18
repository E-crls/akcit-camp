"""Trechos literais de normas fora do MCR 2-7/2-9, lidos de `docs/normas/` (nunca inventados).

Cobre a IN BCB nº 758/2026 (`docs/normas/in_bcb_758.md`), que pôs no MCR - Documento 1 (nota do Campo
60-B) os procedimentos de reversão de desclassificação no Sicor. O pacote de exibição usa `citacao_reversao()`
para citar literalmente a norma na seção de reversão (com URL e data de acesso) em vez de um resumo.

Formato do arquivo: dentro da seção "## Texto literal", cada "### <seção>" abre um trecho; a primeira linha
é a cabeça e as linhas "a) ..." são as alíneas. Sem o arquivo, ou sem o trecho pedido, as funções devolvem
None: quem cita marca "citação não conferida", nunca preenche com texto de memória.

**Amarração com a conferência:** a seção "## Texto literal" foi conferida linha a linha contra o texto da API
de normativos do BCB (na data de `acesso`) e o sha256 dela está em `FONTES[...]["sha256_texto_literal"]`
(`sha256_secao_literal`). Se o arquivo for editado depois, o hash não confere e `citacao_reversao()` devolve
None (o pacote volta a dizer "não conferida"); o teste `test_regras_normas_in758.py` acusa a diferença. Para
mudar o texto: reconferir contra a fonte oficial e só então atualizar o hash e a data de acesso.
"""

from __future__ import annotations

import hashlib
import re
from functools import cache
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
IN_BCB_758 = "in-bcb-758"
ARQUIVOS = {IN_BCB_758: "docs/normas/in_bcb_758.md"}
FONTES: dict[str, dict[str, str]] = {
    IN_BCB_758: {
        "norma": "Instrução Normativa BCB nº 758, de 08/07/2026 (DOU 10/07/2026, Seção 1, p. 196)",
        "url": "https://www.bcb.gov.br/estabilidadefinanceira/exibenormativo?tipo=Instru%C3%A7%C3%A3o%20"
               "Normativa%20BCB&numero=758",
        "acesso": "2026-10-16",
        "texto_normativo": ARQUIVOS[IN_BCB_758],
        # seção "## Texto literal" conferida contra a API de normativos do BCB na data de `acesso`
        "sha256_texto_literal": "b6c902bf0c5cd0125ee6398416932a795fb4866221eb84244e0af21c5bb27e27",
    }
}
_RX_ALINEA = re.compile(r"^([a-z])\) \S")


def _linhas_literais(norma_id: str) -> list[str] | None:
    """Linhas não vazias da seção "## Texto literal" (sem espaços nas pontas e sem "---"); None sem arquivo."""
    rel = ARQUIVOS.get(norma_id)
    p = REPO / rel if rel else None
    if p is None or not p.is_file():
        return None
    out, dentro = [], False
    for linha in p.read_text(encoding="utf-8").splitlines():
        s = linha.strip()
        if s.startswith("## "):
            dentro = s.startswith("## Texto literal")
            continue
        if dentro and s and s != "---":
            out.append(s)
    return out


def sha256_secao_literal(norma_id: str) -> str | None:
    """sha256 da seção "## Texto literal" (linhas de `_linhas_literais` unidas por quebra de linha LF); None
    sem arquivo."""
    linhas = _linhas_literais(norma_id)
    return hashlib.sha256("\n".join(linhas).encode("utf-8")).hexdigest() if linhas else None


def conferida(norma_id: str) -> bool:
    """O texto literal no arquivo é o que foi conferido contra a fonte oficial (sha256 registrado em FONTES)?"""
    esperado = FONTES.get(norma_id, {}).get("sha256_texto_literal")
    return bool(esperado) and sha256_secao_literal(norma_id) == esperado


@cache
def trechos(norma_id: str) -> dict[tuple[str, str | None], str]:
    """`{(seção, alínea ou None para a cabeça): texto literal}` do arquivo da norma (vazio se não houver)."""
    out: dict[tuple[str, str | None], str] = {}
    secao = None
    for s in _linhas_literais(norma_id) or []:
        if s.startswith("### "):
            secao = s[4:].strip()
            continue
        if secao is None:
            continue
        if m := _RX_ALINEA.match(s):
            out[(secao, m.group(1))] = s
        elif (secao, None) not in out:
            out[(secao, None)] = s
    return out


def trecho(norma_id: str, secao: str, alinea: str | None = None) -> str | None:
    """Texto literal da cabeça da seção (`alinea=None`) ou de uma alínea; None se não estiver no arquivo."""
    return trechos(norma_id).get((secao, alinea))


def citacao_reversao() -> dict[str, Any] | None:
    """Citação literal da IN BCB 758 para a reversão de desclassificação: cabeça da nota do Campo 60-B e as
    alíneas "b" (desclassificação por supervisão do BC), "c" (documentação registrada para cada operação) e
    "e" (documentação à disposição do BC), com localizador, URL e data de acesso. None se o texto não estiver
    em `docs/normas/` ou se ele mudou depois da conferência (sha256 diferente do registrado em FONTES)."""
    if not conferida(IN_BCB_758):
        return None
    secao = "Campo 60-B, Nota"
    partes = [trecho(IN_BCB_758, secao)] + [trecho(IN_BCB_758, secao, a) for a in ("b", "c", "e")]
    if any(p is None for p in partes):
        return None
    return {
        **FONTES[IN_BCB_758],
        "localizador": "IN BCB 758, art. 2º: MCR - Documento 1, Campo 60-B, Nota, alíneas b, c e e",
        "citacao_literal": " […] ".join(partes),  # type: ignore[arg-type]
        "alineas": {a: trecho(IN_BCB_758, secao, a) for a in ("a", "b", "c", "d", "e")},
        "citacao_conferida": True,  # só chega aqui com o sha256 da seção literal igual ao conferido
    }
