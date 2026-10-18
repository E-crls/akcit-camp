"""Foto do DANFE do DEMO-0001 para o turno opcional "foto da nota impressa" da demo (rodada 3).

Renderiza o DANFE a partir do `nfe_1.xml` do caso (homologação, partes sintéticas), "fotografa" no nível pedido
(o mesmo simulador das entradas bagunçadas, `documentos_imagem.fotografar`) e grava em
`eval/golden/demo/DEMO-0001/fotos/danfe_1.jpg`. Grava também, em `danfe_1.verdade.json`, o que está impresso no
papel (no espaço dos campos validados), que o roteiro usa para a fala da fiscal quando o agente pede o residual.

Uso (na raiz): scripts/py.sh eval/golden/gerador/gerar_danfe_demo.py [--nivel media]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
REPO = AQUI.parents[2]

import documentos_imagem as DI
from gerar_baguncados import rotulos_danfe

CASO = REPO / "eval" / "golden" / "demo" / "DEMO-0001"
SEMENTE = "DEMO-0001:danfe:2"  # nível média: a foto deixa a chave (DV) e o CNPJ do emitente sem validar


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nivel", default="media", choices=["leve", "media", "pesada"])
    ap.add_argument("--semente", default=SEMENTE)
    a = ap.parse_args()
    xml = (CASO / "nfe_1.xml").read_bytes()
    foto, meta = DI.fotografar(DI.renderizar_danfe(xml), a.nivel, random.Random(a.semente))
    b = DI.jpeg_bytes(foto, meta["jpeg_q"])
    (CASO / "fotos" / "danfe_1.jpg").write_bytes(b)
    verdade = rotulos_danfe(xml)
    (CASO / "fotos" / "danfe_1.verdade.json").write_text(
        json.dumps({"nivel": a.nivel, "semente": a.semente, "meta": meta, "campos": verdade}, ensure_ascii=False,
                   indent=1), encoding="utf-8")
    print(f"danfe_1.jpg: {len(b)} bytes, nível {a.nivel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
