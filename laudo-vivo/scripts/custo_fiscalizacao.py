"""Custo por fiscalização medido no trace (tokens e tempos) e equivalente estimado em nuvem e energia.

Lê o trace OpenTelemetry JSONL (`<dados>/traces/<fiscalizacao>.jsonl`), soma por fiscalização os tokens de
prompt e de geração de cada chamada ao Ollama, o tempo de LLM e de cada ferramenta, e estima:
- o custo se os MESMOS tokens fossem para modelos pequenos de nuvem (preços públicos com fonte e data em
  `laudo.audit.custo.PRECOS`), em R$ pela PTAX;
- a energia local (tempo de GPU × potência + tempo de ferramentas × potência da CPU) × tarifa.

Uso:
  scripts/py.sh scripts/custo_fiscalizacao.py dados_locais/demo/traces/fis_demo_0001.jsonl
  scripts/py.sh scripts/custo_fiscalizacao.py dados_locais/api/traces            # todas as fiscalizações
  scripts/py.sh scripts/custo_fiscalizacao.py <trace> --json --tarifa-kwh 0.95 --cambio 5.10
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from laudo.audit import custo


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Custo por fiscalização medido no trace.")
    ap.add_argument("caminho", type=Path, help="arquivo de trace JSONL ou diretório com traces")
    ap.add_argument("--fis", help="só esta fiscalização")
    ap.add_argument("--json", action="store_true", help="saída JSON em vez de markdown")
    ap.add_argument(
        "--cambio", type=float, default=custo.CAMBIO_PADRAO, help="R$ por US$ (padrão: PTAX 07/10)"
    )
    ap.add_argument("--tarifa-kwh", type=float, default=custo.TARIFA_KWH_RS, help="R$ por kWh")
    ap.add_argument("--potencia-gpu-w", type=float, default=custo.POTENCIA_GPU_W)
    ap.add_argument("--potencia-cpu-w", type=float, default=custo.POTENCIA_CPU_W)
    a = ap.parse_args(argv)
    if a.caminho.is_dir():
        arquivos = sorted(p for p in a.caminho.glob("*.jsonl") if p.name != "geral.jsonl")
    elif a.caminho.is_file():
        arquivos = [a.caminho]
    else:
        print(f"trace não encontrado: {a.caminho}", file=sys.stderr)
        return 2
    usos = custo.somar(custo.ler_spans(arquivos))
    usos.pop("geral", None)
    if a.fis:
        usos = {k: v for k, v in usos.items() if k == a.fis}
    if not usos:
        print("nenhuma fiscalização no trace", file=sys.stderr)
        return 1
    estimativas = [
        custo.estimar(u, a.cambio, a.potencia_gpu_w, a.potencia_cpu_w, a.tarifa_kwh) for u in usos.values()
    ]
    if a.json:
        print(json.dumps(estimativas, ensure_ascii=False, indent=1))
    else:
        print("\n\n".join(custo.relatorio_md(e) for e in estimativas))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
