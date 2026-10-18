"""Números em pt-BR para textos lidos por gente (motivos das regras, falas, laudo).

`fmt_br(42.75)` → "42,75"; `fmt_br(633.48, 1)` → "633,5"; `fmt_br(1000.0)` → "1000". Sem separador de milhar
(evita "1.000" ser lido como um vírgula zero) e sem zeros à direita. O grounding (POL-05) lê os dois formatos.

Tabelas da tela e do laudo (`fmt_milhar`, `fmt_valor`): com separador de milhar ("1.200", "250.800"),
intervalo "12 a 17" e o valor apurado de um campo sem dicionário cru:
`{"contagem": 12, "intervalo": [12, 17]}` → "12 (12 a 17)"; dicionário só de textos (status de uma checagem)
→ "—". Motivos sem ids crus no laudo para imprimir: `texto_sem_ids`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

# Método de fiscalização legível: a tela e o laudo não mostram o id interno
ROTULO_METODO = {
    "autofiscalizacao_assistida": "autofiscalização assistida",
    "presencial": "presencial",
    "documental": "documental",
    "remoto": "sensoriamento remoto",
}


def rotulo_metodo(metodo: Any) -> str:
    """ "autofiscalizacao_assistida" → "autofiscalização assistida"; vazio → "não definido"."""
    if not metodo:
        return "não definido"
    return ROTULO_METODO.get(str(metodo), str(metodo).replace("_", " "))


# Ids técnicos fora do texto lido por gente, na mesma ordem de `semIds` (apps/web/js/ui.js): o laudo
# HTML para imprimir usa este filtro e a tela usa o do JS. O id continua no JSON do laudo e no title da linha.
_RX_IDS = (
    (re.compile(r"\s*\((?:item|documento|operacao|laudo)(?::[\w-]+)+\)"), ""),
    (re.compile(r"\b(?:item|documento|laudo):[\w:-]+:\s+"), ""),
    (re.compile(r"\s*(?:—\s*)?checagem\s+chk_[0-9a-z]+", re.IGNORECASE), ""),
    (re.compile(r"\b(?:chk|ev|oc|alg|al)_[0-9a-z_]+\b"), ""),
)


def texto_sem_ids(texto: Any, rotulos: Mapping[str, str] | None = None) -> str:
    """Motivo/justificativa legível: tira "(item:bov1:quantidade)", o prefixo "item:bov1:gta_data: ",
    "checagem chk_…" e ids `ev_`/`chk_`/`oc_`; troca o id do método e, com `rotulos` (ferramenta → rótulo),
    "integridade_foto: ok" por "Integridade da foto: ok"; e não repete um trecho igual separado por "; ".
    Mudar esta função muda o HTML do laudo: mude junto a versão no comentário do template (`laudo.html.j2`),
    para o selo tratar laudos antigos como "template mudou" e não como HTML editado."""
    s = str(texto or "")
    for rx, novo in _RX_IDS:
        s = rx.sub(novo, s)
    s = re.sub(r"\b[a-z]+(?:_[a-z]+)+\b", lambda m: ROTULO_METODO.get(m.group(0), m.group(0)), s)
    if rotulos:
        s = re.sub(r"\b([a-z]+(?:_[a-z]+)*)(?=:\s)", lambda m: rotulos.get(m.group(1), m.group(1)), s)
    partes: list[str] = []
    for p in (x.strip() for x in s.split("; ")):
        if p and p not in partes:
            partes.append(p)
    s = "; ".join(partes)
    s = re.sub(r"\s{2,}", " ", s)
    s = re.sub(r"\s+([.,;:)])", r"\1", s)
    return re.sub(r"^[\s:;,.—-]+", "", s).strip()


def fmt_milhar(v: Any, casas: int = 2) -> str:
    """Número com separador de milhar e vírgula decimal (`casas` casas); None → "—"; bool → "sim"/"não";
    lista de 2 → "a a b"; outra lista → itens separados por vírgula; texto fica como está."""
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "sim" if v else "não"
    if isinstance(v, (int, float)):
        if float(v).is_integer():
            return f"{int(v):,}".replace(",", ".")
        return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if isinstance(v, (list, tuple)):
        partes = [fmt_milhar(x, casas) for x in v]
        return " a ".join(partes) if len(partes) == 2 else ", ".join(partes)
    return str(v)


def fmt_valor(v: Any) -> str:
    """Valor apurado de um campo do laudo, legível: número, intervalo de contagem, método, prazo; dicionário
    sem número (status de checagem) vira "—", nunca o `repr` do dicionário."""
    if v is None:
        return "—"
    if isinstance(v, dict):
        if v.get("contagem") is not None:
            iv = v.get("intervalo")
            return fmt_milhar(v["contagem"]) + (f" ({fmt_milhar(iv)})" if iv else "")
        if v.get("metodo"):
            return rotulo_metodo(v["metodo"])
        if v.get("data_limite"):
            return f"até {v['data_limite']}"
        escalares = [(k, x) for k, x in v.items() if isinstance(x, (int, float)) and not isinstance(x, bool)]
        if escalares:
            return ", ".join(f"{str(k).replace('_', ' ')}: {fmt_milhar(x)}" for k, x in escalares[:2])
        return "—"
    if isinstance(v, (list, tuple)) and any(isinstance(x, dict) for x in v):
        return "; ".join(fmt_valor(x) for x in v)
    return fmt_milhar(v)


def fmt_br(v: Any, casas: int = 2) -> str:
    """Número com vírgula decimal, no máximo `casas` casas, sem zeros à direita. Não número: `str(v)`."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return str(v)
    f = float(v)
    if f.is_integer():
        return str(int(f))
    s = f"{f:.{casas}f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")
