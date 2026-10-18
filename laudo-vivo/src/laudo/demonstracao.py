"""Casos de demonstração e do golden set: como reconhecê-los e como avisar que são sintéticos.

Regra ética da equipe (`../negocio/afirmacoes_proibidas.md`, seção 2): nenhuma tela pode
sugerir irregularidade de um produtor real. Por isso:

- a operação da demo (`eval/golden/demo/DEMO-0001`) é **fictícia**: deriva de um registro público
  do Sicor/BCB, mas REF, instituição, data, valores, área e geometria foram alterados por
  `scripts/mascarar_demo.py` (o REF `000000001` não existe no Sicor);
- todo laudo, JSON e tela de uma operação sintética leva a marca d'água `MARCA_DAGUA` e o aviso `AVISO`.

`caso_demo_por_ref` deixa a ferramenta `carregar_operacao` devolver a triagem da operação fictícia (calculada
pela mesma regra de lotação do Fiscal-GO), já que ela não está no bench público.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from laudo.contracts import Operacao

REPO = Path(__file__).resolve().parents[2]
DIR_DEMO = REPO / "eval" / "golden" / "demo"

MARCA_DAGUA = "DEMONSTRAÇÃO — dados sintéticos"
AVISO = (
    "Operação fictícia de demonstração: REF, instituição, datas, valores, área e geometria foram alterados a "
    "partir de um registro público do Sicor/BCB; dados de campo (vídeo, fotos, falas), documentos (NF-e, "
    "GTA) e todos os defeitos são sintéticos e plantados. Não descreve nenhuma operação, propriedade ou "
    "produtor real."
)
AVISO_GOLDEN = (
    "Operação sintética de teste (golden set ou roteiro): operação, documentos, fotos, falas e defeitos "
    "são inventados. Não descreve nenhuma operação, propriedade ou produtor real."
)


def eh_demonstracao(op: Operacao | dict[str, Any] | None) -> bool:
    """Operação sintética (golden set, roteiro da demo ou DEMO-0001 mascarado)? Operação do Sicor: não."""
    if op is None:
        return False
    fonte = op.get("fonte") if isinstance(op, dict) else op.fonte
    return "sintetico" in str(fonte or "").lower()


def aviso_de(op: Operacao | dict[str, Any] | None) -> str | None:
    """Aviso a exibir com a marca d'água (None para operação real)."""
    if not eh_demonstracao(op):
        return None
    ref = str((op.get("ref_bacen") if isinstance(op, dict) else op.ref_bacen) or "")  # type: ignore[union-attr]
    return AVISO if caso_demo_por_ref(ref) else AVISO_GOLDEN


def bloco_laudo(op: Operacao | dict[str, Any] | None) -> dict[str, Any] | None:
    """Bloco `demonstracao` do laudo JSON (None para operação real)."""
    aviso = aviso_de(op)
    if aviso is None:
        return None
    return {"marca_dagua": MARCA_DAGUA, "aviso": aviso}


@lru_cache(maxsize=1)
def _casos_demo() -> dict[str, dict[str, Any]]:
    """REF fictício → caso.yaml dos casos de demonstração (só os mascarados, com `demonstracao:`)."""
    saida: dict[str, dict[str, Any]] = {}
    if not DIR_DEMO.is_dir():
        return saida
    for arq in sorted(DIR_DEMO.glob("*/caso.yaml")):
        try:
            dados = yaml.safe_load(arq.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        ref = str((dados.get("operacao") or {}).get("ref_bacen") or "")
        if ref and dados.get("demonstracao"):
            saida[ref] = dados
    return saida


def caso_demo_por_ref(ref_bacen: str) -> dict[str, Any] | None:
    """caso.yaml do caso de demonstração com esse REF fictício (ou None)."""
    return _casos_demo().get(str(ref_bacen))


def limpar_cache() -> None:
    _casos_demo.cache_clear()
