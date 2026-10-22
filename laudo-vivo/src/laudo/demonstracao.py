"""Casos de demonstração e do golden set: como reconhecê-los e como avisar que são sintéticos.

Regra ética da equipe (`../negocio/afirmacoes_proibidas.md`, seção 2): nenhuma tela pode
sugerir irregularidade de um produtor real. Por isso:

- a operação da demo (`eval/golden/demo/DEMO-0001`) é **fictícia**: deriva de um registro público
  do Sicor/BCB, mas REF, instituição, data, valores, área e geometria foram alterados por
  `scripts/mascarar_demo.py` (o REF `000000001` não existe no Sicor);
- todo laudo, JSON e tela de uma operação sintética leva a marca d'água `MARCA_DAGUA` e o aviso `AVISO`.

`caso_demo_por_ref` deixa a ferramenta `carregar_operacao` devolver a triagem da operação fictícia (calculada
pela mesma regra de lotação do Fiscal-GO), já que ela não está no bench público.

Casos de demonstração fora do repositório: `LAUDO_CASOS_DIR` (uma ou mais pastas separadas por `os.pathsep`;
cada subpasta com `caso.yaml` é um caso, ou a própria pasta, se tiver `caso.yaml`). Eles entram na carteira, abrem
pelo botão e, com o bloco `demonstracao:`, têm o REF fictício indexado como os de `eval/golden/demo` (que vêm
antes: um REF repetido fora do repositório não substitui o de dentro).

Aviso de cada caso (`aviso_do_caso`): `demonstracao.aviso` do `caso.yaml`, se houver; senão, no caso mascarado a
partir do Sicor por `scripts/mascarar_demo.py` (bloco `demonstracao` com `mascarado_versao`, o DEMO-0001), o `AVISO`
fixo; senão, o `aviso` do próprio caso; senão, o `AVISO_GOLDEN`. Assim o DEMO-0001 continua com o mesmo texto, e um
caso num local real (ex.: "local real, operação fictícia, dados sintéticos") mostra o aviso verdadeiro dele.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from laudo.contracts import Operacao

REPO = Path(__file__).resolve().parents[2]
DIR_DEMO = REPO / "eval" / "golden" / "demo"
ENV_CASOS_DIR = "LAUDO_CASOS_DIR"

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
    caso = caso_demo_por_ref(ref)
    return aviso_do_caso(caso) if caso is not None else AVISO_GOLDEN


def aviso_do_caso(caso: Mapping[str, Any]) -> str:
    """Aviso de um caso de demonstração indexado (ver a docstring do módulo para a ordem)."""
    bloco = caso.get("demonstracao")
    bloco = bloco if isinstance(bloco, Mapping) else {}
    if str(bloco.get("aviso") or "").strip():
        return " ".join(str(bloco["aviso"]).split())
    if bloco.get("mascarado_versao") is not None:  # derivado do Sicor por scripts/mascarar_demo.py (DEMO-0001)
        return AVISO
    if str(caso.get("aviso") or "").strip():
        return " ".join(str(caso["aviso"]).split())
    return AVISO_GOLDEN


def bloco_laudo(op: Operacao | dict[str, Any] | None) -> dict[str, Any] | None:
    """Bloco `demonstracao` do laudo JSON (None para operação real)."""
    aviso = aviso_de(op)
    if aviso is None:
        return None
    return {"marca_dagua": MARCA_DAGUA, "aviso": aviso}


def dirs_casos_externos(env: Mapping[str, str] | None = None) -> list[Path]:
    """Pastas de `LAUDO_CASOS_DIR` (várias separadas por `os.pathsep`), sem repetir."""
    bruto = (os.environ if env is None else env).get(ENV_CASOS_DIR) or ""
    out: list[Path] = []
    for parte in bruto.split(os.pathsep):
        if parte.strip() and (p := Path(parte.strip()).expanduser()) not in out:
            out.append(p)
    return out


def pastas_de_casos(bases: list[Path] | tuple[Path, ...]) -> list[Path]:
    """Pastas de caso (com `caso.yaml`) dentro de cada base, na ordem; a base que já é um caso entra sozinha."""
    out: list[Path] = []
    for base in bases:
        if (base / "caso.yaml").is_file():
            cands = [base]
        elif base.is_dir():
            cands = [d for d in sorted(base.iterdir()) if (d / "caso.yaml").is_file()]
        else:
            cands = []
        out += [d for d in cands if d not in out]
    return out


def pastas_casos_externos() -> list[Path]:
    """Pastas de caso de `LAUDO_CASOS_DIR`."""
    return pastas_de_casos(dirs_casos_externos())


def _ler_caso(arq: Path) -> dict[str, Any] | None:
    try:
        dados = yaml.safe_load(arq.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    return dados if isinstance(dados, dict) else None


@lru_cache(maxsize=8)
def _indice(externos: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    saida: dict[str, dict[str, Any]] = {}
    if DIR_DEMO.is_dir():
        for arq in sorted(DIR_DEMO.glob("*/caso.yaml")):
            dados = _ler_caso(arq)
            ref = str(((dados or {}).get("operacao") or {}).get("ref_bacen") or "")
            if dados and ref and dados.get("demonstracao"):
                saida[ref] = dados
    for pasta in pastas_de_casos([Path(x) for x in externos]):
        dados = _ler_caso(pasta / "caso.yaml")
        ref = str(((dados or {}).get("operacao") or {}).get("ref_bacen") or "")
        if dados and ref and dados.get("demonstracao"):
            saida.setdefault(ref, dados)  # o do repositório (eval/golden/demo) vem antes
    return saida


def _casos_demo() -> dict[str, dict[str, Any]]:
    """REF fictício → caso.yaml dos casos de demonstração com `demonstracao:` (eval/golden/demo e as pastas de
    `LAUDO_CASOS_DIR`)."""
    return _indice(tuple(str(p) for p in dirs_casos_externos()))


def caso_demo_por_ref(ref_bacen: str) -> dict[str, Any] | None:
    """caso.yaml do caso de demonstração com esse REF fictício (ou None)."""
    return _casos_demo().get(str(ref_bacen))


def limpar_cache() -> None:
    _indice.cache_clear()
