"""Confere que uma mudança em `src/` depois de uma rodada de avaliação não mexeu nas métricas.

Quando o código muda depois dos relatórios (ex.: as mudanças de 09–10/10 depois da r3: privacidade da chave e do
hash, retomada, roteiro da demo), refazer a rodada inteira com o LLM custa ~1 h de GPU e só faz sentido se as
métricas puderem mudar. Este script roda no código ATUAL o que não depende do LLM ao vivo e compara com os
relatórios de referência:

1. golden set sem LLM (`run_eval.py --modo deterministico`): todas as métricas de `splits` iguais;
2. red-team sem LLM (`run_redteam.py --modo deterministico`): `resumo` igual, recalculado só nos casos que a
   referência tinha e só nas métricas que ela tinha (caso ou métrica acrescentados depois não são diferença);
3. A/B v2 (`run_ab_v2.py`, respostas do VLM e do extrator gravadas): tudo igual, exceto `config`;
4. gravações do LLM da demo (CLI nos dois caminhos e a contingência da interface): 0 requisições fora da gravação,
   ou seja, o contexto que o LLM recebe não mudou (é isso que mantém as métricas com o LLM).

Escreve `eval/reports/<data>_equivalencia<sufixo>.json|md`, que `scripts/gerar_numeros.py` cita em `numeros.md`.

Uso (na raiz): scripts/py.sh eval/conferir_equivalencia.py --data 2026-10-09 --sufixo _r3 --final --motivo "..."
(`--sem-replay` pula o item 4, que precisa do yolox_m, do vídeo semissintético e do cache do satélite)

O item 1 roda o modo determinístico no split de TESTE congelado: por isso `--final` é obrigatório e a execução fica
no `eval/golden/casos/registro_teste.jsonl` (L41), com o motivo. O relatório traz também o sha256(eval/) e o
manifesto do golden (L59).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

AQUI = Path(__file__).resolve().parent
REPO = AQUI.parent
sys.path.insert(0, str(AQUI))
sys.path.insert(0, str(REPO / "src"))

import harness as H

DIR = AQUI / "reports"
PY = [sys.executable]


def _rodar(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(PY + args, cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          check=False)


def _diferencas(a: Any, b: Any, caminho: str = "", so_ref: bool = False) -> list[str]:
    """Diferenças entre a referência `a` e o novo `b`; com `so_ref`, chave que só existe no novo (métrica
    acrescentada depois da referência) não conta."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) if so_ref else set(a) | set(b), key=str):
            out += _diferencas(a.get(k), b.get(k), f"{caminho}/{k}", so_ref)
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return [d for i, (x, y) in enumerate(zip(a, b, strict=True))
                for d in _diferencas(x, y, f"{caminho}[{i}]", so_ref)]
    return [] if a == b else [f"{caminho}: {str(a)[:60]} ≠ {str(b)[:60]}"]


def _conferencia(nome: str, ref: dict[str, Any], novo: dict[str, Any], chaves: list[str],
                 so_ref: bool = False) -> dict[str, Any]:
    difs = [d for k in chaves for d in _diferencas(ref.get(k), novo.get(k), k, so_ref)]
    return {"nome": nome, "resultado": "igual" if not difs else "DIFERENTE", "comparado": chaves,
            "diferencas": difs[:20]}


def redteam_nos_casos_da_referencia(ref: dict[str, Any], novo: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Red-team: o resumo do código atual recalculado só nos casos que a referência tinha (casos acrescentados
    depois, como `v2_args.yaml` na onda 3, não são diferença de comportamento) e os ids dos casos novos."""
    import run_redteam as RT

    ids = {c["id"] for c in ref.get("casos") or []}
    casos = [c for c in novo.get("casos") or [] if c["id"] in ids]
    novos = sorted({c["id"] for c in novo.get("casos") or []} - ids)
    if not ids or not novo:
        return novo, novos
    return {"resumo": RT.resumo(casos)}, novos


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True)
    ap.add_argument("--sufixo", required=True)
    # padrão: as mudanças de 09–10/10 depois da r3, que alguns textos chamavam de "rodada 4" (não é a r4
    # congelada). No Windows, o micromamba repassa os argumentos pelo cmd.exe, que quebra texto com parênteses;
    # prefira o padrão ou um texto simples.
    ap.add_argument("--motivo", default="mudancas de 09-10/10 depois da r3: chave de acesso da NF-e só mascarada e "
                                        "hash com sal da instalação (laudo.privacidade), retomada após queda do "
                                        "servidor, foto do DANFE no roteiro padrão da demo e passo do residual na API")
    ap.add_argument("--sem-replay", action="store_true")
    ap.add_argument("--final", action="store_true",
                    help="obrigatório: o golden set sem LLM roda também no split de teste congelado (fica no registro)")
    a = ap.parse_args()
    if not a.final:
        print("o item 1 usa o split de teste congelado: repita com --final (a execução fica no registro_teste.jsonl)")
        return 2
    ref = {n: json.loads((DIR / f"{a.data}_{n}{a.sufixo}.json").read_text(encoding="utf-8"))
           for n in ("deterministico", "redteam_deterministico", "ab_centralidade_v2")}
    tmp = Path(tempfile.mkdtemp(prefix="laudo-equivalencia-"))
    conferencias: list[dict[str, Any]] = []
    try:
        r = _rodar(["eval/run_eval.py", "--modo", "deterministico", "--saida", str(tmp), "--sufixo", "_eq", "--final",
                    "--motivo", f"conferencia de equivalencia com {a.data}{a.sufixo}: {a.motivo}"[:300]])
        if r.returncode != 0:
            print(r.stdout[-2000:], r.stderr[-2000:])
        novo = json.loads(next(tmp.glob("*_deterministico_eq.json")).read_text(encoding="utf-8")) if r.returncode == 0 else {}
        conferencias.append(_conferencia("golden set sem LLM (todas as métricas por split)", ref["deterministico"],
                                         novo, ["splits"]))
        r = _rodar(["eval/run_redteam.py", "--modo", "deterministico", "--saida", str(tmp), "--sufixo", "_eq"])
        novo = (json.loads(next(tmp.glob("*_redteam_deterministico_eq.json")).read_text(encoding="utf-8"))
                if r.returncode == 0 else {})
        novo, casos_novos = redteam_nos_casos_da_referencia(ref["redteam_deterministico"], novo)
        nome_rt = "red-team sem LLM (resumo" + (f"; {len(casos_novos)} caso(s) novo(s) fora da comparação: "
                                                f"{', '.join(casos_novos[:6])}" if casos_novos else "") + ")"
        conferencias.append(_conferencia(nome_rt, ref["redteam_deterministico"], novo, ["resumo"], so_ref=True))
        argv, ant = [], ""
        for x in ref["ab_centralidade_v2"]["config"].get("argv") or []:  # os mesmos dados de entrada, sem saída
            if x not in ("--sufixo", "--saida") and ant not in ("--sufixo", "--saida"):
                argv.append(x)
            ant = x
        r = _rodar(["eval/ab_centralidade_v2/run_ab_v2.py", *argv, "--saida", str(tmp), "--sufixo", "_eq"])
        novo = (json.loads(next(tmp.glob("*_ab_centralidade_v2_eq.json")).read_text(encoding="utf-8"))
                if r.returncode == 0 else {})
        chaves = [k for k in ref["ab_centralidade_v2"] if k != "config"]
        conferencias.append(_conferencia("A/B v2 (leituras e alegações gravadas; tudo menos config)",
                                         ref["ab_centralidade_v2"], novo, chaves))
        if not a.sem_replay:
            for nome, extra in (("replay da demo na CLI, 19 passos com a foto do DANFE (gravado no código novo)", []),
                                ("replay da demo na CLI, só o XML, 17 passos (gravado em 08/10, antes das mudanças)",
                                 ["--sem-danfe", "--replay",
                                  "tests/unit/dados_agente/replay_demo_real_sem_danfe_qwen35_4b.jsonl"])):
                args = ["scripts/demo_cli.py", "--ferramentas", "reais", "--llm", "replay", "--sem-cor",
                        "--dados", str(tmp / "demo"), *extra]
                if "--replay" not in args:
                    args += ["--replay", "tests/unit/dados_agente/replay_demo_real_qwen35_4b.jsonl"]
                r = _rodar(args)
                m = re.search(r"replay: (\d+) requisi", r.stdout)
                selado = "Etapa final: SELADO" in r.stdout
                ok = r.returncode == 0 and selado and m is not None and m.group(1) == "0"
                conferencias.append({"nome": nome, "resultado": "igual" if ok else "DIFERENTE",
                                     "comparado": ["requisições ao LLM fora da gravação", "etapa final"],
                                     "diferencas": [] if ok else [(f"fora da gravação: {m.group(1) if m else 'n/d'}; "
                                                                  f"selado: {selado}")]})
            r = _rodar(["scripts/gravar_contingencia_web.py", "--conferir"])
            conferencias.append({"nome": "contingência da interface, 19 passos pela API (gravada no código novo)",
                                 "resultado": "igual" if r.returncode == 0 else "DIFERENTE",
                                 "comparado": ["requisições ao LLM fora da gravação", "etapa final"],
                                 "diferencas": [] if r.returncode == 0 else [r.stdout.strip().splitlines()[-1:]]})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    tudo_igual = all(c["resultado"] == "igual" for c in conferencias)
    res = {
        "data": datetime.now().astimezone().strftime("%d/%m/%Y %H:%M"),
        "referencia": {"data": a.data, "sufixo": a.sufixo,
                       "sha256_src": ref["deterministico"]["config"]["sha256_src"]},
        "sha256_src_atual": H.hash_src(),
        "sha256_eval_atual": H.hash_eval()["sha256"],
        "manifesto": H.info_manifesto(),
        "motivo": a.motivo,
        "conferencias": conferencias,
        "conclusao": ("métricas sem LLM idênticas e o contexto do LLM inalterado nas gravações: os números da "
                      "referência continuam valendo para o código atual; a rodada completa com o LLM fica para o "
                      "congelamento" if tudo_igual else
                      "ALGUMA MÉTRICA MUDOU: refaça a rodada inteira no mesmo hash e gere slide e números de novo"),
    }
    nome = f"{a.data}_equivalencia{a.sufixo}"
    (DIR / f"{nome}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    linhas = [f"# Equivalência do código atual com a rodada {a.sufixo.lstrip('_')} ({res['data']})", "",
              f"- Referência: relatórios `{a.data}_*{a.sufixo}`, `sha256(src/)={res['referencia']['sha256_src'][:16]}…`",
              (f"- Código atual: `sha256(src/)={res['sha256_src_atual'][:16]}…`, "
               f"`sha256(eval/)={res['sha256_eval_atual'][:16]}…`; manifesto do golden "
               f"`{str(res['manifesto'].get('sha256_manifesto'))[:16]}…` ({res['manifesto'].get('conferido')})"),
              f"- O que mudou: {a.motivo or 'n/d'}",
              "- Gerado por `scripts/py.sh eval/conferir_equivalencia.py`.", "",
              "| Conferência | Resultado | Diferenças |", "|---|---|---|"]
    linhas += [f"| {c['nome']} | **{c['resultado']}** | {'; '.join(map(str, c['diferencas'])) or '—'} |"
               for c in conferencias]
    linhas += ["", f"**Conclusão:** {res['conclusao']}.", ""]
    (DIR / f"{nome}.md").write_text("\n".join(linhas), encoding="utf-8")
    print("\n".join(linhas))
    return 0 if tudo_igual else 1


if __name__ == "__main__":
    sys.exit(main())
