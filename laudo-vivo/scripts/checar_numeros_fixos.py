"""Confere os números de fonte fixa (mercado e Fiscal-GO) que o pitch, o BMC, o kit e o RQ2 citam.

Os números de avaliação e de custo medido vêm de `docs/entregaveis/numeros.json`, entre marcadores
`<!--n:chave-->...<!--/n-->`, e a r4 os reescreve (`scripts/gerar_numeros.py --aplicar`). Os de mercado
(preço-alvo, piso por visita, singulares, margem estimada) e os do Fiscal-GO não saem da avaliação e não estão no
`numeros.json`. Até ganharem chaves lá, ficam entre marcadores do mesmo formato com outra letra,

    preço-alvo de <!--f:mercado.preco_fiscalizacao-->R$ 79<!--/f--> por fiscalização

e este script confere cada um contra a fonte: o valor do marcador tem de ser uma das formas aceitas da chave, e a
fonte (`docs/entregaveis/mercado.md`, `bench/fiscal_go/resumo.json` ou `eval/golden/visao/RESULTADOS.md`) ainda
tem de dizer o mesmo. Se a fonte mudar, o script acusa todas as citações de uma vez.

Migração para o `numeros.json` (quando o dono do `gerar_numeros.py` criar as chaves com os mesmos nomes): trocar
`<!--f:` por `<!--n:` e `<!--/f-->` por `<!--/n-->` nos mesmos arquivos.

Uso (na raiz do repositório):
  scripts/py.sh scripts/checar_numeros_fixos.py             # confere os textos de TEXTOS
  scripts/py.sh scripts/checar_numeros_fixos.py --chaves    # lista as chaves, as formas e a fonte

Código de saída: 0 sem problema; 1 se um marcador divergir, usar chave que não existe ou a fonte mudar.
Textos de `../negocio/` entram quando existem (no CI não existem e são pulados, e a saída diz quais).
Além de `TEXTOS`, todo .md ou .html de `PROCURAR` que tenha um marcador `<!--f:` também é conferido (desde a
noite de 16/10/2026): um texto novo com número de fonte fixa não escapa por não estar na lista.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parents[1]
MERCADO = "docs/entregaveis/mercado.md"
FISCAL_GO = "bench/fiscal_go/resumo.json"
VISAO = "eval/golden/visao/RESULTADOS.md"
TEXTOS = [
    "docs/entregaveis/pitch-regional-3min.md",
    "docs/entregaveis/pitch-final-5min.md",
    "docs/entregaveis/qa-banca.md",
    "docs/entregaveis/bmc-v1.md",
    "docs/entregaveis/bmc-v1.html",
    "docs/entregaveis/KIT_APRESENTADOR.md",
    "docs/entregaveis/deck/index.html",
    "../negocio/relatorio_quinzenal_2_rascunho.md",
]
# Onde mais procurar marcadores (os textos públicos e ../negocio, que no CI não existe).
PROCURAR = ["README.md", "docs", "validacao", "eval/SLIDE.md", "../negocio"]
EXTENSOES = {".md", ".html", ".htm"}
EXCLUIR_DIRS = {".git", "__pycache__", "node_modules", "dados_locais"}
RX = re.compile(r"<!--f:([a-z0-9_.]+)-->(.*?)<!--/f-->", re.DOTALL)


class Fixo(NamedTuple):
    formas: tuple[str, ...]  # como o número pode aparecer no texto
    fonte: str
    trecho: str  # regex que a fonte tem de conter (para mercado.md e RESULTADOS.md)


def _milhar(n: int) -> str:
    return f"{n:,}".replace(",", ".")


FIXOS: dict[str, Fixo] = {
    # mercado.md, seção 1 (Sicor 2025, Brasil)
    "mercado.itens_brasil": Fixo(("525 mil", "525.340"), MERCADO, r"\*\*525\.340, R\$ 115,8 bi\*\*"),
    "mercado.singulares_perfil": Fixo(("109",), MERCADO, r"\| \*\*109\*\* \(32,5% das 335 singulares\)"),
    "mercado.pct_itens_perfil": Fixo(("82%",), MERCADO, r"\(\*\*82%\*\* dos itens"),
    # seção 2 (Goiás)
    "mercado.itens_go": Fixo(("34.890",), MERCADO, r"\| Itens físicos de R\$ 20 mil ou mais \| 34\.890 \|"),
    "mercado.singulares_go_100": Fixo(("16",), MERCADO, r"com 100 ou mais itens em GO \| 74; 16 "),
    # seção 3 (o que já se paga)
    "mercado.piso_visita": Fixo(("R$ 669", "669"), MERCADO, r"= \*\*R\$ 669\*\*"),
    # seção 4 (preços-alvo, nenhum testado)
    "mercado.preco_fiscalizacao": Fixo(("R$ 79", "79"), MERCADO, r"\| R\$ 79 \(preço-alvo; R\$ 59 acima de 500"),
    "mercado.preco_volume": Fixo(("R$ 59",), MERCADO, r"R\$ 59 acima de 500 por ano\)"),
    "mercado.preco_licenca": Fixo(("R$ 590", "590"), MERCADO, r"15 fiscalizações incluídas \| R\$ 590 \|"),
    "mercado.preco_triagem": Fixo(("R$ 8",), MERCADO, r"operação ativa por ano \| R\$ 8 \|"),
    "mercado.preco_excecao": Fixo(("R$ 490", "490"), MERCADO, r"\| exceção \| R\$ 490 \|"),
    "mercado.preco_servico": Fixo(("R$ 290", "290"), MERCADO, r"fiscalização entregue \| R\$ 290 \|"),
    "mercado.preco_piloto": Fixo(("R$ 5.900",), MERCADO, r"até 150 fiscalizações \| R\$ 5\.900 \|"),
    "mercado.valor_itens": Fixo(("116 bilhões", "R$ 116 bi", "R$ 115,8 bi"), MERCADO, r"\*\*525\.340, R\$ 115,8 bi\*\*"),
    # seção 5 (tamanho de mercado)
    "mercado.servico_50": Fixo(("76 milhões", "R$ 76,2 mi"), MERCADO, r"\*\*R\$ 76,2 mi\*\*"),
    "mercado.tam": Fixo(("125 milhões", "~R$ 125 mi"), MERCADO, r"TAM central: cerca de R\$ 125 mi por ano"),
    "mercado.sam": Fixo(("~R$ 32 mi", "R$ 32 mi"), MERCADO, r"\*\*cerca de R\$ 32 mi\*\*"),
    # seção 8 (custo e margem, estimados)
    "mercado.tec_local": Fixo(("~R$ 0,50–3", "R$ 0,50 a 3"), MERCADO, r"\*\*cerca de R\$ 0,50 a R\$ 3\*\*"),
    "mercado.tec_nuvem": Fixo(("~R$ 1–6", "R$ 1 a 6"), MERCADO, r"\*\*cerca de R\$ 1 a R\$ 6\*\*"),
    "mercado.inferencia_pct": Fixo(("5%",), MERCADO, r"abaixo de 5% do preço-alvo"),
    "mercado.revisao_amostral": Fixo(("~R$ 2", "R$ 2"), MERCADO, r"10 min × R\$ 125/h ≈ R\$ 2\)"),
    "mercado.revisao_servico": Fixo(("~R$ 42", "R$ 42"), MERCADO, r"20 min × R\$ 125/h ≈ R\$ 42\)"),
    "mercado.margem_software": Fixo(("82–92%", "82% a 92%"), MERCADO, r"= R\$ 6–14 \| 82% a 92% \|"),
    "mercado.margem_servico": Fixo(("~56%", "56%"), MERCADO, r"cerca de R\$ 127 \| cerca de 56% \|"),
    "mercado.margem_mix": Fixo(("~80%", "80%"), MERCADO, r"15% exceções\) \| \| cerca de 80% \|"),
    "mercado.cac_cooperativa": Fixo(("R$ 15–30 mil",), MERCADO, r"CAC \(R\$ 15–30 mil por cooperativa"),
    "mercado.cac_credenciada": Fixo(("R$ 2–5 mil",), MERCADO, r"R\$ 2–5 mil por credenciada\)"),
    "mercado.payback": Fixo(("4 a 7 meses",), MERCADO, r"payback \(4 a 7"),
    # avaliação do contador de vídeo (contador 0.2.0)
    "visao.videos_reais": Fixo(("5",), VISAO, r"\(5 vídeos reais, 5 semissintéticos"),
    "visao.videos_semissinteticos": Fixo(("5",), VISAO, r"5 vídeos reais, 5 semissintéticos,"),
}


def _fiscal_go() -> dict[str, Fixo]:
    """Chaves do Fiscal-GO, com as formas calculadas do `resumo.json` (nada copiado à mão)."""
    r = json.loads((REPO / FISCAL_GO).read_text(encoding="utf-8"))
    op, bov = r["operacoes"], r["pecuaria_bovina"]
    return {
        "fiscal_go.operacoes": Fixo((_milhar(op["n"]),), FISCAL_GO, ""),
        "fiscal_go.com_poligono": Fixo((_milhar(op["com_poligono"]),), FISCAL_GO, ""),
        "fiscal_go.glebas": Fixo((_milhar(op["glebas"]),), FISCAL_GO, ""),
        "fiscal_go.pct_bovino": Fixo((f"{round(bov['pct_operacoes'])}%",), FISCAL_GO, ""),
    }


def todas() -> dict[str, Fixo]:
    return {**FIXOS, **_fiscal_go()}


def conferir_fontes(fixos: dict[str, Fixo]) -> list[str]:
    problemas = []
    cache: dict[str, str] = {}
    for chave, f in fixos.items():
        if not f.trecho:
            continue
        texto = cache.setdefault(f.fonte, (REPO / f.fonte).read_text(encoding="utf-8"))
        if not re.search(f.trecho, texto):
            problemas.append(f"{f.fonte}: a fonte de '{chave}' mudou (não achei /{f.trecho}/); confira as "
                             f"citações e atualize FIXOS")
    return problemas


def descobertos(procurar: list[str] | None = None) -> list[str]:
    """Caminhos (relativos ao repositório, com / e ../) dos .md e .html de `PROCURAR` que têm marcador <!--f:."""
    out = []
    for rel in procurar if procurar is not None else PROCURAR:
        base = REPO / rel
        if not base.exists():
            continue
        caminhos = [base] if base.is_file() else sorted(
            p for p in base.rglob("*")
            if p.is_file() and p.suffix.lower() in EXTENSOES
            and not EXCLUIR_DIRS.intersection(p.relative_to(base).parts))
        for p in caminhos:
            try:
                if "<!--f:" in p.read_text(encoding="utf-8"):
                    out.append(Path(os.path.relpath(p, REPO)).as_posix())
            except (UnicodeDecodeError, OSError):
                continue
    return out


def conferir_textos(fixos: dict[str, Fixo], textos: list[str],
                    pulados: list[str] | None = None) -> tuple[list[str], int]:
    problemas, n = [], 0
    for rel in textos:
        p = (REPO / rel).resolve()
        if not p.exists():
            # textos internos (../negocio e os roteiros da equipe) não fazem parte do repositório publicado
            if pulados is not None:
                pulados.append(rel)
            continue
        conteudo = p.read_text(encoding="utf-8")
        for m in RX.finditer(conteudo):
            n += 1
            chave, valor = m.group(1), m.group(2)
            linha = conteudo.count("\n", 0, m.start()) + 1
            if chave not in fixos:
                problemas.append(f"{rel}:{linha}: chave '{chave}' não existe em FIXOS")
            elif valor not in fixos[chave].formas:
                problemas.append(f"{rel}:{linha}: '{chave}' = {valor!r}, mas a fonte ({fixos[chave].fonte}) dá "
                                 f"{' ou '.join(repr(x) for x in fixos[chave].formas)}")
    return problemas, n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--chaves", action="store_true", help="lista as chaves, as formas aceitas e a fonte")
    args = ap.parse_args()
    fixos = todas()
    if args.chaves:
        for chave, f in sorted(fixos.items()):
            print(f"{chave:<32} {' | '.join(f.formas):<28} {f.fonte}")
        return 0
    problemas = conferir_fontes(fixos)
    extras = [rel for rel in descobertos() if rel not in TEXTOS]
    pulados: list[str] = []
    p2, n = conferir_textos(fixos, TEXTOS + extras, pulados)
    problemas += p2
    for p in problemas:
        print(p)
    if extras:
        print("também conferido(s) (têm marcador <!--f:, fora de TEXTOS):", ", ".join(extras))
    if pulados:
        print("pulado(s) (não existe aqui):", ", ".join(pulados))
    print(f"{n} marcador(es) de fonte fixa conferido(s); {len(problemas)} problema(s).")
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
