"""Baixa os modelos de visão do Laudo Vivo para `dados_locais/modelos/` e confere o sha256.

Uso (na raiz do repositório):
    scripts/py.sh scripts/baixar_modelos.py            # baixa o modelo padrão (yolox_m)
    scripts/py.sh scripts/baixar_modelos.py --todos    # baixa todos os listados
    scripts/py.sh scripts/baixar_modelos.py yolox_m    # baixa um modelo específico

URL, hash e licença de cada arquivo ficam em `src/laudo/vision/modelos.py` e `docs/modelos.md`.
Os modelos ficam fora do git (`*.onnx` e `dados_locais/` estão no .gitignore).
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import httpx

from laudo.vision.modelos import MODELOS


def _sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        while bloco := f.read(1 << 20):
            h.update(bloco)
    return h.hexdigest()


def baixar(nome: str, forcar: bool = False) -> Path:
    info = MODELOS[nome]
    alvo = info.caminho
    alvo.parent.mkdir(parents=True, exist_ok=True)
    if alvo.exists() and not forcar:
        h = _sha256(alvo)
        if h == info.sha256:
            print(f"{nome}: já existe e confere ({h[:12]}…)")
            return alvo
        print(f"{nome}: hash diferente do esperado, baixando de novo")
    tmp = alvo.with_suffix(".part")
    with httpx.stream("GET", info.url, follow_redirects=True, timeout=120) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            f.writelines(r.iter_bytes(1 << 20))
    h = _sha256(tmp)
    if h != info.sha256:
        tmp.unlink(missing_ok=True)
        raise SystemExit(f"{nome}: sha256 {h} difere do esperado {info.sha256}")
    tmp.replace(alvo)
    print(f"{nome}: baixado em {alvo} sha256={h} licença={info.licenca}")
    return alvo


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("nomes", nargs="*", help="modelos a baixar (padrão: o marcado como padrão, yolox_m)")
    ap.add_argument("--todos", action="store_true")
    ap.add_argument("--forcar", action="store_true", help="baixa de novo mesmo se já existir")
    a = ap.parse_args(argv)
    nomes = list(MODELOS) if a.todos else (a.nomes or [n for n, i in MODELOS.items() if i.padrao])
    for n in nomes:
        if n not in MODELOS:
            print(f"modelo desconhecido: {n}; opções: {', '.join(MODELOS)}", file=sys.stderr)
            return 2
        baixar(n, forcar=a.forcar)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
