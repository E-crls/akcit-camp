"""Aplica ou confere os marcadores `desc.*` e `retro.*` nos textos do observatório e da validação.

Desde a onda 3 (16/10/2026) estes textos estão na lista `ALVOS` de `scripts/gerar_numeros.py`, que os confere no
`--verificar` (CI) e os reescreve no `--aplicar`, com as mesmas regras dos textos de pitch e Q&A (números antigos,
versão de palco das desclassificações com a data de corte):

    bench/desclassificacao/README.md, validacao/README.md, eval/retroteste/README.md

Este script ficou como atalho só para eles (os 81 marcadores da frente do observatório), para quem atualiza o
observatório sem mexer nos outros textos. A versão dos números é a de palco (`eval/reports/palco.json`).

Uso (na raiz do repositório):
  scripts/py.sh scripts/desclassificacao_marcadores.py              # reescreve os números entre marcadores
  scripts/py.sh scripts/desclassificacao_marcadores.py --verificar  # só confere; código 1 se algo divergir
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import gerar_numeros as GN

TEXTOS = ["bench/desclassificacao/README.md", "validacao/README.md", "eval/retroteste/README.md"]
assert set(TEXTOS) <= set(GN.ALVOS), "os textos do observatório saíram da lista ALVOS de gerar_numeros.py"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--verificar", action="store_true")
    ap.add_argument("--data", default=GN.DATA_PADRAO)
    ap.add_argument("--sufixo", default=GN.SUFIXO_PADRAO)
    a = ap.parse_args()
    if not a.verificar and (a.data, a.sufixo) != (GN.DATA_PADRAO, GN.SUFIXO_PADRAO):
        print(f"a versão de palco é {GN.DATA_PADRAO}{GN.SUFIXO_PADRAO}: para trocar, use "
              "scripts/gerar_numeros.py --aplicar --fixar-palco (todos os textos juntos)")
        return 2
    tabela = GN.plano(GN.montar(a.data, a.sufixo))
    erros: list[str] = []
    vistos = 0
    for rel in TEXTOS:
        p = REPO / rel
        texto = p.read_text(encoding="utf-8")
        if not a.verificar:
            novo, e = GN.aplicar_texto(texto, tabela)
            erros += [f"{rel}: {x}" for x in e]
            if novo != texto:
                GN.gravar_texto(p, novo)
                print(f"atualizado: {rel}")
            texto = novo
        erros += GN.conferir_texto(rel, texto, tabela)
        vistos += len(GN.RX_MARCADOR.findall(texto))
    for e in erros:
        print("ERRO:", e)
    print(f"{vistos} marcadores conferidos; {len(erros)} problema(s)")
    return 1 if erros else 0


if __name__ == "__main__":
    sys.exit(main())
