"""Mede o ASR: `scripts/py.sh -m laudo.speech arquivo.wav [arquivo2.webm ...] [--repeticoes 3] [--cpu]`.

Carrega o modelo uma vez (mede a carga), transcreve cada arquivo N vezes e imprime latência, RTF, texto e a
normalização de números. Sem download: usa só o cache local.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys

from laudo.speech.asr import TranscritorWhisper
from laudo.speech.numeros import normalizar


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("arquivos", nargs="+")
    ap.add_argument("--repeticoes", type=int, default=3)
    ap.add_argument("--dispositivo", default="auto", choices=["auto", "cuda", "cpu"])
    ap.add_argument("--beam", type=int, default=5)
    a = ap.parse_args()
    t = TranscritorWhisper(dispositivo=a.dispositivo, beam_size=a.beam)
    est = t.carregar()
    print(json.dumps(est, ensure_ascii=False))
    for arq in a.arquivos:
        lat = []
        r = None
        for _ in range(a.repeticoes):
            r = t.transcrever(arq)
            lat.append(r.latencia_ms)
        assert r is not None
        n = normalizar(r.texto)
        print(
            json.dumps(
                {
                    "arquivo": arq,
                    "duracao_s": r.duracao_audio_s,
                    "fala_s": r.duracao_fala_s,
                    "latencia_ms": lat,
                    "mediana_ms": statistics.median(lat),
                    "rtf": r.rtf,
                    "confianca": r.confianca,
                    "texto": r.texto,
                    "normalizado": n.texto,
                    "confirmacao": n.pedido_confirmacao(),
                    "dispositivo": r.dispositivo,
                    "compute_type": r.compute_type,
                },
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
