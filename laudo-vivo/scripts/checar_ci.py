"""Confere que o CI da raiz do repositório e a variante desta pasta têm os mesmos passos.

O GitHub só lê `.github/` na raiz do repositório. Aqui o produto fica em `laudo-vivo/`, então quem roda é
`../.github/workflows/ci.yml`, com `defaults.run.working-directory: laudo-vivo` e os caminhos de cache e de
artefato partindo da raiz. `.github/workflows/ci.yml` (nesta pasta) é a variante para quando a pasta for
publicada como repositório próprio. As duas têm de ter os mesmos passos (nome, comando, ação, `env`, `if` e
`with`, este com os caminhos da raiz sem o prefixo `laudo-vivo/`), o mesmo job e os mesmos gatilhos (a da raiz
ainda filtra por caminho, para não rodar quando só mudou o que não é do produto).

Uso: scripts/py.sh scripts/checar_ci.py   (código 1 se divergirem; sem o CI da raiz, só valida a variante)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

PASTA = Path(__file__).resolve().parents[1]
PREFIXO = PASTA.name + "/"
CI_PASTA = PASTA / ".github" / "workflows" / "ci.yml"
CI_RAIZ = PASTA.parent / ".github" / "workflows" / "ci.yml"
# Chaves de `with` que são caminho a partir da raiz do repositório (actions/setup-python e upload-artifact).
CAMINHOS_WITH = ("cache-dependency-path", "path")
# A da raiz só roda quando mudou o produto, os textos de negócio que o CI confere ou o próprio CI.
FILTRO_RAIZ = [PREFIXO + "**", "negocio/**", ".github/workflows/**"]


def carregar(caminho: Path) -> dict[str, Any]:
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    if not isinstance(dados, dict):
        raise TypeError(f"{caminho}: não é um mapeamento YAML")
    # YAML 1.1 lê a chave `on` como booleano True.
    if True in dados and "on" not in dados:
        dados["on"] = dados.pop(True)
    return dados


def _sem_prefixo(valor: Any) -> Any:
    if isinstance(valor, str) and valor.startswith(PREFIXO):
        return valor[len(PREFIXO):]
    return valor


def _passo(p: dict[str, Any], da_raiz: bool) -> dict[str, Any]:
    com = dict(p.get("with") or {})
    if da_raiz:
        for k in CAMINHOS_WITH:
            if k in com:
                com[k] = _sem_prefixo(com[k])
    return {"name": p.get("name"), "uses": p.get("uses"), "run": p.get("run"), "env": p.get("env"),
            "if": p.get("if"), "with": com}


def _gatilhos(on: Any, da_raiz: bool) -> dict[str, Any]:
    gat = {k: dict(v or {}) for k, v in (on or {}).items()}
    if da_raiz:
        for ev in ("push", "pull_request"):
            gat.get(ev, {}).pop("paths", None)
    return gat


def problemas(raiz: dict[str, Any], pasta: dict[str, Any]) -> list[str]:
    erros: list[str] = []
    dir_raiz = ((raiz.get("defaults") or {}).get("run") or {}).get("working-directory")
    if dir_raiz != PASTA.name:
        erros.append(f"raiz: defaults.run.working-directory é {dir_raiz!r}, devia ser {PASTA.name!r}")
    dir_pasta = ((pasta.get("defaults") or {}).get("run") or {}).get("working-directory")
    if dir_pasta not in (None, "."):
        erros.append(f"variante: defaults.run.working-directory é {dir_pasta!r}, devia ser '.'")
    shell = [((d.get("defaults") or {}).get("run") or {}).get("shell") for d in (raiz, pasta)]
    if shell[0] != shell[1]:
        erros.append(f"defaults.run.shell diferente: raiz {shell[0]!r}, variante {shell[1]!r}")
    for ev in ("push", "pull_request"):
        filtro = (((raiz.get("on") or {}).get(ev)) or {}).get("paths")
        if filtro != FILTRO_RAIZ:
            erros.append(f"raiz: on.{ev}.paths é {filtro!r}, devia ser {FILTRO_RAIZ!r}")
    if _gatilhos(raiz.get("on"), True) != _gatilhos(pasta.get("on"), False):
        erros.append("gatilhos (on) diferentes além do filtro de caminhos da raiz")
    for chave in ("permissions", "concurrency", "name"):
        if raiz.get(chave) != pasta.get(chave):
            erros.append(f"{chave} diferente")
    jobs_r, jobs_p = raiz.get("jobs") or {}, pasta.get("jobs") or {}
    if set(jobs_r) != set(jobs_p):
        erros.append(f"jobs diferentes: raiz {sorted(jobs_r)}, variante {sorted(jobs_p)}")
    for nome in sorted(set(jobs_r) & set(jobs_p)):
        jr, jp = jobs_r[nome], jobs_p[nome]
        for chave in ("runs-on", "timeout-minutes", "env", "defaults", "permissions"):
            if jr.get(chave) != jp.get(chave):
                erros.append(f"job {nome}: {chave} diferente")
        for i, p in enumerate(jr.get("steps") or [], 1):
            for k in CAMINHOS_WITH:
                v = (p.get("with") or {}).get(k)
                if isinstance(v, str) and not v.startswith(PREFIXO):
                    erros.append(f"raiz: job {nome}, passo {i}: with.{k} = {v!r} não começa com {PREFIXO!r} "
                                 "(na raiz, cache e artefato partem da raiz do repositório)")
        pr = [_passo(p, True) for p in jr.get("steps") or []]
        pp = [_passo(p, False) for p in jp.get("steps") or []]
        if len(pr) != len(pp):
            erros.append(f"job {nome}: {len(pr)} passo(s) na raiz e {len(pp)} na variante")
        for i, (a, b) in enumerate(zip(pr, pp), 1):
            if a != b:
                campos = [k for k in a if a[k] != b[k]]
                erros.append(f"job {nome}, passo {i} ({a['name'] or a['uses']}): difere em "
                             f"{', '.join(campos)}")
    return erros


def main() -> int:
    try:
        pasta = carregar(CI_PASTA)
    except (OSError, TypeError, yaml.YAMLError) as e:
        print(f"variante do CI ilegível ({CI_PASTA.relative_to(PASTA).as_posix()}): {e}")
        return 1
    if not CI_RAIZ.exists():
        print(f"ok: só a variante ({len(pasta.get('jobs') or {})} job(s)); sem CI na raiz para comparar "
              "(a pasta está publicada à parte)")
        return 0
    try:
        raiz = carregar(CI_RAIZ)
    except (OSError, TypeError, yaml.YAMLError) as e:
        print(f"CI da raiz ilegível (../.github/workflows/ci.yml): {e}")
        return 1
    erros = problemas(raiz, pasta)
    if erros:
        print("o CI da raiz e a variante da pasta divergem:", *erros, sep="\n  ")
        return 1
    n = sum(len(j.get("steps") or []) for j in (raiz.get("jobs") or {}).values())
    print(f"ok: CI da raiz (../.github/workflows/ci.yml) e variante (.github/workflows/ci.yml) com os mesmos "
          f"{n} passo(s); a raiz roda de dentro de {PASTA.name}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
