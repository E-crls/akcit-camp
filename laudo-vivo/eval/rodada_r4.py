"""Rodada r4 congelada (L05, L06, L07, L43, L60): um comando, em série, um modelo por vez, retomável.

Uso (na raiz do repositório; o mesmo por `scripts/tarefas.sh r4 [...]` ou `make r4 ARGS="..."`):
  scripts/py.sh eval/rodada_r4.py --a-seco     # só imprime a sequência e as pré-condições (nada roda, nada grava)
  scripts/py.sh eval/rodada_r4.py              # roda tudo (cerca de 3 a 4 h de máquina; GPU só com o qwen3.5:4b)
  scripts/py.sh eval/rodada_r4.py --retomar    # continua de onde parou (mesma data, mesmo sha256(src/))

**Quando rodar:** uma vez, no `sha256(src/)` final, depois do lote de src/ (ver backlog interno)
e nunca junto com o streaming do Sicor nem com outro modelo no Ollama. Se a r4 falhar, os números da r3 continuam
valendo (mesmo conjunto de teste): a versão de palco (`eval/reports/palco.json`) só muda no penúltimo passo.

**O que roda, em ordem** (`etapas()`; `--a-seco` imprime os comandos exatos):

1. Sem LLM: golden set determinístico e determinístico com integração ideal (dev e teste), red-team original+v2
   sem LLM, casos públicos (6 cenários e os 4 de dev do custeio) e o índice de documentos com o grupo ZF no dev.
2. Com o LLM (qwen3.5:4b, um modelo por vez; antes de cada etapa confere `/api/ps`): golden set do agente (dev
   e teste), repetição do agente no teste (`_r4_rep`, L60), red-team original+v2 do agente, red-team cego
   `v3_cego` nos dois modos em seguida (relatório separado `_r4_v3cego`; sem ninguém olhar o primeiro antes do
   segundo), A/B v1, narrações e A/B v2 no dev, leitura do VLM, narrações e A/B v2 no teste (`_r4_teste`, L07) e
   o custo medido no trace de uma demo ao vivo (`<data>_custo_demo.json`). No fim, o modelo é descarregado.
3. Números: `gerar_slide --sufixo _r4`, `gerar_numeros --aplicar --fixar-palco` (a r4 vira a versão de palco),
   `gerar_numeros --verificar` e `desclassificacao_marcadores --verificar`.

Toda etapa que toca o split de teste congelado leva `--final --motivo "..."` e fica no registro append-only
`eval/golden/casos/registro_teste.jsonl`; as do conjunto cego ficam no mesmo registro (alvo `redteam_v3_cego`).

**Data única:** os relatórios levam a data de início da rodada (`LAUDO_DATA_RODADA`, `harness.data_rodada`), mesmo
que a rodada passe da meia-noite ou seja retomada no dia seguinte; `gerar_slide`/`gerar_numeros` acham todos.

**Estado e retomada:** `dados_locais/eval/r4/estado.json` (data, sha256(src/) e sha256(eval/) do início, status
de cada etapa) e um log por etapa em `dados_locais/eval/r4/logs/`. `--retomar` pula as etapas concluídas cujos
arquivos de saída ainda existem e recusa continuar se `src/` mudou desde o início (a rodada é num hash só). Sem
`--retomar`, um estado com etapas já rodadas faz o comando parar: retomar é o normal; recomeçar do zero exige
apagar o `estado.json` de propósito (e o registro do teste mostrará as duas execuções). Uma etapa que falhou
roda de novo inteira na retomada (a leitura do VLM é retomável por conta própria; a etapa do conjunto cego, se
repetida, passa a ser a 2ª execução, e o relatório diz isso).
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

AQUI = Path(__file__).resolve().parent
REPO = AQUI.parent
sys.path.insert(0, str(AQUI))

import harness as H

SUFIXO = "_r4"
MODELO = "qwen3.5:4b"
MOTIVO = "rodada r4 congelada"
MOTIVO_L07 = "L07 AB v2 no teste r4"
MODOS_NARRACAO = ["llm", "regex", "llm_bruto", "regex_bruto", "llm_bruto_v0"]  # os 5 modos da r3
DIR_ESTADO_PADRAO = REPO / "dados_locais" / "eval" / "r4"
REPORTS = "eval/reports"


@dataclass
class Etapa:
    id: str
    titulo: str
    cmds: list[list[str]]  # scripts Python relativos à raiz, rodados com o mesmo interpretador, em série
    fase: int  # 1 sem LLM, 2 com LLM, 3 números
    saidas: list[str] = field(default_factory=list)  # arquivos que têm de existir depois (relativos à raiz)
    llm: bool = False
    toca_teste: bool = False
    minutos: float = 1.0  # estimativa, para o --a-seco
    codigos_ok: tuple[int, ...] = (0,)  # casos públicos e índice ZF: 1 = "algum caso difere" (é resultado)
    relatorio: str | None = None  # grava a saída do último comando neste .md (etapas que não gravam relatório)
    json_stdout: str | None = None  # grava a saída do último comando, que é JSON, neste arquivo
    limpar: list[str] = field(default_factory=list)  # diretórios de trabalho apagados antes (dados_locais/)
    precisa: list[str] = field(default_factory=list)  # gravações que têm de existir antes


def etapas(data: str, dir_estado: Path = DIR_ESTADO_PADRAO) -> list[Etapa]:
    """A sequência da r4 para os relatórios com a data `data` (AAAA-MM-DD)."""
    rel = dir_estado.relative_to(REPO).as_posix() if dir_estado.is_relative_to(REPO) else str(dir_estado)
    r = f"{REPORTS}/{data}"
    final = ["--final", "--motivo", MOTIVO]
    l07 = ["--final", "--motivo", MOTIVO_L07]
    narr_dev, narr_teste = "dados_locais/eval/narracoes_dev_r4.jsonl", "dados_locais/eval/narracoes_test_r4.jsonl"
    leit_dev, leit_teste = "dados_locais/eval/leitura_v2_dev.jsonl", "dados_locais/eval/leitura_v2_test.jsonl"
    demo = f"{rel}/demo_custo"
    return [
        # --- fase 1: sem LLM (rápida; falha cedo) ---------------------------------------------------------------
        Etapa("deterministico", "Golden set sem LLM (dev e teste)", [
            ["eval/run_eval.py", "--modo", "deterministico", *final, "--sufixo", SUFIXO]], 1,
            [f"{r}_deterministico{SUFIXO}.json"], toca_teste=True, minutos=1),
        Etapa("deterministico_ideal", "Golden set sem LLM, integração ideal (teto; nunca vai ao slide)", [
            ["eval/run_eval.py", "--modo", "deterministico", "--integracao", "ideal", *final, "--sufixo", SUFIXO]],
            1, [f"{r}_deterministico_ideal{SUFIXO}.json"], toca_teste=True, minutos=1),
        Etapa("redteam_deterministico", "Red-team original+v2 sem LLM (só guardas e plano mínimo)", [
            ["eval/run_redteam.py", "--modo", "deterministico", "--sufixo", SUFIXO]], 1,
            [f"{r}_redteam_deterministico{SUFIXO}.json"], minutos=3),
        Etapa("casos_publicos", "Casos públicos (6 cenários, split separado)", [
            ["eval/golden/gerador/casos_publicos.py", "--rodar"]], 1, [f"{r}_casos_publicos{SUFIXO}.md"],
            minutos=1, codigos_ok=(0, 1), relatorio=f"{r}_casos_publicos{SUFIXO}.md"),
        Etapa("casos_publicos_custeio", "Casos de dev do perfil custeio (4)", [
            ["eval/golden/gerador/casos_publicos.py", "--rodar", "--custeio"]], 1,
            [f"{r}_casos_publicos_custeio{SUFIXO}.md"], minutos=1, codigos_ok=(0, 1),
            relatorio=f"{r}_casos_publicos_custeio{SUFIXO}.md"),
        Etapa("indice_zf", "Índice de documentos e grupo ZF no dev (dois modos)", [
            ["eval/golden/gerador/conferir_indice_zf.py", "--saida", f"{rel}/indice_zf"]], 1,
            [f"{r}_indice_zf{SUFIXO}.md"], minutos=3, codigos_ok=(0, 1), relatorio=f"{r}_indice_zf{SUFIXO}.md",
            limpar=[f"{rel}/indice_zf"]),
        # --- fase 2: com o LLM, um modelo por vez -----------------------------------------------------------------
        Etapa("agente", "Golden set do agente (dev e teste)", [
            ["eval/run_eval.py", "--modo", "agente", *final, "--sufixo", SUFIXO, "--manter-modelo"]], 2,
            [f"{r}_agente{SUFIXO}.json"], llm=True, toca_teste=True, minutos=30),
        Etapa("agente_rep", "Repetição do agente no teste (L60; comparada caso a caso com a _r4)", [
            ["eval/run_eval.py", "--modo", "agente", "--split", "test", "--final", "--motivo",
             "L60 repeticao do agente no teste r4", "--sufixo", f"{SUFIXO}_rep", "--manter-modelo"]], 2,
            [f"{r}_agente{SUFIXO}_rep.json"], llm=True, toca_teste=True, minutos=15),
        Etapa("redteam_agente", "Red-team original+v2 do agente", [
            ["eval/run_redteam.py", "--modo", "agente", "--sufixo", SUFIXO, "--manter-modelo"]], 2,
            [f"{r}_redteam_agente{SUFIXO}.json"], llm=True, minutos=25),
        Etapa("redteam_v3cego_agente", "Red-team cego v3 do agente (1ª execução: o número cego)", [
            ["eval/run_redteam.py", "--modo", "agente", "--conjunto", "v3_cego", "--sufixo", f"{SUFIXO}_v3cego",
             "--motivo", "r4: 1a execucao do conjunto cego v3", "--manter-modelo"]], 2,
            [f"{r}_redteam_agente{SUFIXO}_v3cego.json"], llm=True, minutos=10),
        Etapa("redteam_v3cego_deterministico", "Red-team cego v3 sem LLM (logo depois, mesmo src/)", [
            ["eval/run_redteam.py", "--modo", "deterministico", "--conjunto", "v3_cego", "--sufixo",
             f"{SUFIXO}_v3cego", "--motivo", "r4: 1a execucao deterministica do conjunto cego v3"]], 2,
            [f"{r}_redteam_deterministico{SUFIXO}_v3cego.json"], minutos=1),
        Etapa("ab1", "A/B v1 (checklist × agente, fiscal simulado, válidos do dev)", [
            ["eval/ab_centralidade/run_ab.py", "--sufixo", SUFIXO, "--manter-modelo"]], 2,
            [f"{r}_ab_centralidade{SUFIXO}.json"], llm=True, minutos=25),
        Etapa("narracoes_dev", "Narrações do dev (5 modos da r3)", [
            ["eval/ab_centralidade_v2/avaliar_narracoes.py", "--split", "dev", "--rotulo", "r4", "--modos",
             *MODOS_NARRACAO]], 2, [narr_dev], llm=True, minutos=5),
        Etapa("ab2_dev", "A/B v2 no dev (leituras do VLM gravadas; narrações da r4)", [
            ["eval/ab_centralidade_v2/run_ab_v2.py", "--leituras", leit_dev, "--narracoes", narr_dev,
             "--sufixo", SUFIXO]], 2, [f"{r}_ab_centralidade_v2{SUFIXO}.json"], minutos=1, precisa=[leit_dev]),
        Etapa("leitura_teste", "Leitura do VLM no teste (L07; retomável por conta própria)", [
            ["eval/ab_centralidade_v2/avaliar_leitura.py", "--split", "test", "--final", "--motivo", MOTIVO_L07]],
            2, [leit_teste], llm=True, toca_teste=True, minutos=55),
        Etapa("narracoes_teste", "Narrações do teste (L07, 5 modos)", [
            ["eval/ab_centralidade_v2/avaliar_narracoes.py", "--split", "test", "--rotulo", "r4", "--modos",
             *MODOS_NARRACAO, *l07]], 2, [narr_teste], llm=True, toca_teste=True, minutos=5),
        Etapa("ab2_teste", "A/B v2 no teste (L07, lado a lado com o dev no slide)", [
            ["eval/ab_centralidade_v2/run_ab_v2.py", "--split", "test", "--leituras", leit_teste, "--narracoes",
             narr_teste, *l07, "--sufixo", f"{SUFIXO}_teste"]], 2, [f"{r}_ab_centralidade_v2{SUFIXO}_teste.json"],
            toca_teste=True, minutos=1),
        Etapa("custo", "Custo medido no trace de uma demo ao vivo (caso DEMO-0001, 19 passos)", [
            ["scripts/demo_cli.py", "--ferramentas", "reais", "--llm", "ollama", "--sem-cor", "--dados", demo,
             "--vlm-cache", f"{rel}/demo_custo_vlm", "--descarregar"],
            ["scripts/custo_fiscalizacao.py", f"{demo}/traces/fis_demo_0001.jsonl", "--json"]], 2,
            [f"{r}_custo_demo.json"], llm=True, minutos=5, json_stdout=f"{r}_custo_demo.json",
            limpar=[demo, f"{rel}/demo_custo_vlm"]),
        # --- fase 3: números (sem LLM) ----------------------------------------------------------------------------
        Etapa("slide", "Slide único da r4", [["eval/gerar_slide.py", "--data", data, "--sufixo", SUFIXO]], 3,
              ["eval/SLIDE.md"], minutos=0.1),
        Etapa("numeros_aplicar", "Números da r4 nos textos; a r4 vira a versão de palco", [
            ["scripts/gerar_numeros.py", "--data", data, "--sufixo", SUFIXO, "--aplicar", "--fixar-palco",
             "--motivo", MOTIVO]], 3, ["docs/entregaveis/numeros.json", f"{REPORTS}/palco.json"], minutos=0.1),
        Etapa("numeros_verificar", "Conferência de todos os marcadores (a mesma do CI)", [
            ["scripts/gerar_numeros.py", "--verificar"]], 3, minutos=0.1),
        Etapa("desclassificacao_verificar", "Conferência dos marcadores do observatório", [
            ["scripts/desclassificacao_marcadores.py", "--verificar"]], 3, minutos=0.1),
    ]


# ---------------------------------------------------------------------------
# Estado
# ---------------------------------------------------------------------------


def caminho_estado(dir_estado: Path) -> Path:
    return dir_estado / "estado.json"


def ler_estado(dir_estado: Path) -> dict[str, Any] | None:
    p = caminho_estado(dir_estado)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def gravar_estado(dir_estado: Path, estado: dict[str, Any]) -> None:
    dir_estado.mkdir(parents=True, exist_ok=True)
    p = caminho_estado(dir_estado)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(estado, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    tmp.replace(p)


def concluida(estado: dict[str, Any] | None, e: Etapa) -> bool:
    """Etapa com status ok no estado e com todos os arquivos de saída ainda presentes."""
    reg = ((estado or {}).get("etapas") or {}).get(e.id) or {}
    return reg.get("status") == "ok" and all((REPO / s).exists() for s in e.saidas)


# ---------------------------------------------------------------------------
# Ollama: um modelo por vez
# ---------------------------------------------------------------------------


def modelos_carregados() -> list[str] | None:
    return H.ollama_ps()


def ollama_no_ar() -> bool:
    info = H.info_llm(modelo=MODELO)
    return info.get("ollama_versao", H.NA) != H.NA


def descarregar_todos() -> list[str]:
    """Pede keep_alive=0 para cada modelo carregado (equivale a `ollama stop`); devolve os descarregados."""
    import httpx

    base = (os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
    if not base.startswith("http"):
        base = "http://" + base
    feitos = []
    for m in modelos_carregados() or []:
        try:
            httpx.post(f"{base}/api/generate", json={"model": m, "keep_alive": 0}, timeout=30.0)
            feitos.append(m)
        except httpx.HTTPError:
            pass
    return feitos


def conferir_um_modelo() -> str | None:
    """Erro se houver outro modelo carregado no Ollama (a GPU é só do qwen3.5:4b durante a r4)."""
    carregados = modelos_carregados()
    if carregados is None:
        return "o Ollama não respondeu em /api/ps (suba o servidor e rode --retomar)"
    outros = sorted(set(carregados) - {MODELO})
    if outros:
        return (f"outro modelo carregado no Ollama: {outros}. Um modelo por vez: descarregue (`ollama stop "
                f"{outros[0]}`) e rode --retomar")
    return None


# ---------------------------------------------------------------------------
# Pré-condições e execução
# ---------------------------------------------------------------------------


def precondicoes(lista: list[Etapa], verificar_ollama: bool = True) -> list[tuple[str, bool, str]]:
    """(o quê, ok, detalhe) do que precisa estar pronto antes de rodar."""
    out = []
    split = H.carregar_split()
    probs = H.conferir_split(split) + H.conferir_manifesto(split)
    out.append(("split de teste congelado e conferido (SPLIT.yaml + MANIFESTO.yaml)",
                bool(split.get("congelado")) and not probs, "; ".join(probs[:3]) or "ok"))
    for e in lista:
        for p in e.precisa:
            out.append((f"gravação para {e.id}: {p}", (REPO / p).exists(), "existe" if (REPO / p).exists() else
                        "FALTA (rode a gravação antes)"))
    trocados = {k: v for k, v in os.environ.items() if k.startswith("LAUDO_MODELO") and v != MODELO}
    if any(e.llm for e in lista):  # LAUDO_MODELO[_<PERFIL>] troca o modelo dos perfis (laudo.llm.provider)
        out.append((f"nenhuma variável LAUDO_MODELO* trocando o {MODELO}", not trocados,
                    "ok" if not trocados else f"definidas: {sorted(trocados)}"))
    if verificar_ollama and any(e.llm for e in lista):
        no_ar = ollama_no_ar()
        out.append((f"Ollama no ar com {MODELO}", no_ar, "ok" if no_ar else "não respondeu"))
        erro = conferir_um_modelo() if no_ar else None
        out.append(("nenhum outro modelo carregado", no_ar and erro is None, erro or ("ok" if no_ar else "n/d")))
    return out


def _linha_cmd(cmd: list[str]) -> str:
    return "scripts/py.sh " + " ".join(shlex.quote(x) for x in cmd)


def imprimir_sequencia(lista: list[Etapa], data: str, estado: dict[str, Any] | None,
                       pre: list[tuple[str, bool, str]] | None) -> None:
    total = sum(e.minutos for e in lista)
    print(f"Rodada r4 — data dos relatórios {data}, sufixo {SUFIXO}, modelo {MODELO} (um por vez); "
          f"{len(lista)} etapas, cerca de {total / 60:.1f} h de máquina.")
    if estado:
        print(f"Estado: iniciada em {estado.get('iniciado_em')}, sha256(src/)={str(estado.get('sha256_src'))[:16]}…")
    for i, e in enumerate(lista, 1):
        marca = "feita" if concluida(estado, e) else ("FALHOU" if ((estado or {}).get("etapas") or {}).get(
            e.id, {}).get("status") not in (None, "ok") else "a fazer")
        tags = [x for x, s in (("LLM", e.llm), ("teste congelado", e.toca_teste)) if s]
        print(f"\n{i:02d}. [{marca}] fase {e.fase} · {e.id} · {e.titulo} (~{e.minutos:g} min"
              + (f"; {', '.join(tags)}" if tags else "") + ")")
        for c in e.cmds:
            print(f"    {_linha_cmd(c)}" + (f" > {e.json_stdout}" if e.json_stdout and c is e.cmds[-1] else ""))
        if e.relatorio:
            print(f"    saída gravada em {e.relatorio}")
        if e.saidas:
            print(f"    confere: {', '.join(e.saidas)}")
    if pre is not None:
        print("\nPré-condições:")
        for o, ok, det in pre:
            print(f"  [{'ok' if ok else 'FALTA'}] {o}: {det}")


def _env(data: str) -> dict[str, str]:
    env = dict(os.environ)
    env[H.VAR_DATA_RODADA] = data
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    src = str(REPO / "src")
    env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def _rodar_cmd(cmd: list[str], env: dict[str, str], log, ecoar: bool = True,
               so_stdout: bool = False) -> tuple[int, str]:
    """Roda `python <cmd>` na raiz, ecoa e grava a saída no log; devolve (código, saída). Com `so_stdout`
    (saída que é JSON), o stderr vai só para o log e a saída devolvida é só o stdout."""
    log.write(f"$ {_linha_cmd(cmd)}\n")
    log.flush()
    if so_stdout:
        r = subprocess.run([sys.executable, *cmd], cwd=REPO, env=env, capture_output=True, check=False)
        out, err = (x.decode("utf-8", errors="replace") for x in (r.stdout, r.stderr))
        log.write(out + err)
        return r.returncode, out
    proc = subprocess.Popen([sys.executable, *cmd], cwd=REPO, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    partes = []
    assert proc.stdout is not None
    for bruto in iter(proc.stdout.readline, b""):
        linha = bruto.decode("utf-8", errors="replace")
        partes.append(linha)
        log.write(linha)
        if ecoar:
            sys.stdout.write(linha)
            sys.stdout.flush()
    return proc.wait(), "".join(partes)


def _relatorio_md(e: Etapa, data: str, codigo: int, saida: str, sha_src: str) -> str:
    return "\n".join([
        f"# {e.titulo} — rodada r4 ({data})", "",
        f"- Comando: `{_linha_cmd(e.cmds[-1])}` (gerado por `eval/rodada_r4.py`, etapa `{e.id}`)",
        f"- Versão avaliada: `sha256(src/)={sha_src[:16]}…`; código de saída {codigo}"
        + (" (1 = algum caso difere do esperado: é resultado, não falha da rodada)" if codigo == 1 else ""), "",
        "```", saida.rstrip(), "```", ""])


def executar_etapa(e: Etapa, data: str, dir_estado: Path, estado: dict[str, Any], ecoar: bool = True) -> bool:
    reg = estado.setdefault("etapas", {}).setdefault(e.id, {})
    reg.update({"status": "rodando", "inicio": H.agora_iso(), "titulo": e.titulo})
    gravar_estado(dir_estado, estado)
    for p in e.limpar:
        shutil.rmtree(REPO / p, ignore_errors=True)
    logs = dir_estado / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    arq_log = logs / f"{e.id}.log"
    env = _env(data)
    codigo, saida = 0, ""
    t0 = time.perf_counter()
    try:
        with arq_log.open("a", encoding="utf-8") as log:
            log.write(f"\n=== {H.agora_iso()} {e.id} ===\n")
            for c in e.cmds:
                if e.llm and c is e.cmds[0]:  # a GPU só com o qwen3.5:4b (um modelo por vez)
                    erro = conferir_um_modelo()
                    if erro:
                        log.write(f"RECUSADO: {erro}\n")
                        print(f"RECUSADO: {erro}")
                        codigo, saida = 3, erro
                        break
                json_aqui = bool(e.json_stdout) and c is e.cmds[-1]
                codigo, saida = _rodar_cmd(c, env, log, ecoar=ecoar and not json_aqui, so_stdout=json_aqui)
                if codigo not in e.codigos_ok:
                    break
    except KeyboardInterrupt:
        reg.update({"status": "interrompido", "fim": H.agora_iso()})
        gravar_estado(dir_estado, estado)
        raise
    ok = codigo in e.codigos_ok
    if ok and e.relatorio:
        (REPO / e.relatorio).write_text(_relatorio_md(e, data, codigo, saida, estado.get("sha256_src", "")),
                                        encoding="utf-8", newline="\n")
    if ok and e.json_stdout:
        try:
            dados = json.loads(saida)
        except json.JSONDecodeError:
            ok, saida = False, "a saída não é JSON: " + saida[-300:]
        else:
            (REPO / e.json_stdout).write_text(json.dumps(dados, ensure_ascii=False, indent=1) + "\n",
                                              encoding="utf-8", newline="\n")
    faltam = [s for s in e.saidas if not (REPO / s).exists()] if ok else []
    if faltam:
        ok = False
        saida += f"\nsaídas esperadas ausentes: {faltam}"
        print(f"ERRO: saídas esperadas ausentes: {faltam} (a data do relatório não é {data}?)")
    reg.update({"status": "ok" if ok else "erro", "codigo": codigo, "fim": H.agora_iso(),
                "duracao_s": round(time.perf_counter() - t0, 1), "log": H.argv_seguro([str(arq_log)])[0],
                "saidas": {s: H.sha256_arquivo(REPO / s) for s in e.saidas if (REPO / s).exists()}})
    if not ok:
        reg["erro"] = saida.strip().splitlines()[-1][:300] if saida.strip() else f"código {codigo}"
    gravar_estado(dir_estado, estado)
    return ok


def rodar(lista: list[Etapa], data: str, dir_estado: Path, estado: dict[str, Any],
          ecoar: bool = True, descarregar: Callable[[], list[str]] | None = None) -> int:
    descarregar = descarregar or descarregar_todos  # resolvido na chamada (os testes trocam a função)
    usou_llm = False
    try:
        for i, e in enumerate(lista, 1):
            if concluida(estado, e):
                print(f"[{i:02d}/{len(lista)}] {e.id}: já feita, pulando")
                continue
            print(f"\n[{i:02d}/{len(lista)}] {e.id}: {e.titulo}", flush=True)
            usou_llm = usou_llm or e.llm
            if not executar_etapa(e, data, dir_estado, estado, ecoar=ecoar):
                reg = estado["etapas"][e.id]
                print(f"\nPAROU na etapa {e.id} ({reg.get('erro')}). Log: {reg.get('log')}. Corrija e rode "
                      "`scripts/tarefas.sh r4 --retomar`. Os números da r3 continuam valendo até a etapa "
                      "numeros_aplicar.")
                return 1
            if usou_llm and not any(x.llm for x in lista[i:]):  # acabou a fase do LLM: libera a GPU já
                print("descarregando o modelo:", descarregar() or "nenhum carregado")
                usou_llm = False
    finally:
        if usou_llm:
            print("descarregando o modelo:", descarregar() or "nenhum carregado")
    estado["concluido_em"] = H.agora_iso()
    gravar_estado(dir_estado, estado)
    print(f"\nr4 concluída: relatórios {REPORTS}/{data}_*{SUFIXO}*, slide e números atualizados; versão de palco "
          f"= {data}{SUFIXO}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a-seco", action="store_true", help="só imprime a sequência e as pré-condições")
    ap.add_argument("--retomar", action="store_true", help="continua a r4 já iniciada (mesma data e src/)")
    ap.add_argument("--dir-estado", type=Path, default=DIR_ESTADO_PADRAO, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    dir_estado = a.dir_estado.resolve()
    estado = ler_estado(dir_estado)
    iniciada = bool(estado and estado.get("etapas"))
    data = estado["data"] if estado else H.data_rodada()
    lista = etapas(data, dir_estado)
    if a.a_seco:  # nada roda nem é gravado; o Ollama não é consultado
        imprimir_sequencia(lista, data, estado, precondicoes(lista, verificar_ollama=False))
        print("\n(a seco: nada foi executado)")
        return 0
    if iniciada and not a.retomar:
        print(f"já existe uma r4 iniciada em {estado.get('iniciado_em')} ({caminho_estado(dir_estado)}): use "
              "--retomar. Recomeçar do zero exige apagar esse arquivo de propósito.")
        return 2
    if a.retomar and not iniciada:
        print("nada a retomar: nenhuma r4 iniciada; rode sem --retomar")
        return 2
    src = H.hash_src()
    if iniciada and estado.get("sha256_src") != src:
        print(f"src/ mudou desde o início da r4 ({str(estado.get('sha256_src'))[:16]}… → {src[:16]}…): a rodada "
              "tem de ser num hash só. Volte o src/ ao hash do início, ou registre a decisão e recomece (apague o "
              "estado de propósito).")
        return 2
    pre = precondicoes([e for e in lista if not concluida(estado, e)])
    faltam = [f"{o}: {d}" for o, ok, d in pre if not ok]
    if faltam:
        print("pré-condições não atendidas:", *faltam, sep="\n  ")
        return 2
    if not estado:
        estado = {"data": data, "sufixo": SUFIXO, "modelo": MODELO, "iniciado_em": H.agora_iso(),
                  "sha256_src": src, "sha256_eval": H.hash_eval()["sha256"], "etapas": {}}
        gravar_estado(dir_estado, estado)
    imprimir_sequencia(lista, data, estado, None)
    return rodar(lista, data, dir_estado, estado)


if __name__ == "__main__":
    sys.exit(main())
