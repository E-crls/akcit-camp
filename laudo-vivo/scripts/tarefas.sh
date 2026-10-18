#!/usr/bin/env bash
# Tarefas do Laudo Vivo num só lugar (Git Bash no Windows e Linux no CI). Rode a partir de qualquer pasta:
#
#   scripts/tarefas.sh <tarefa> [argumentos]
#
# O interpretador vem de PY (padrão: scripts/py.sh, ambiente conda-forge; no CI: PY=python).
# Tarefas:
#   testes        pytest tests -q (lentos e de rede pulados; LAUDO_LENTO=1 / LAUDO_TESTES_REDE=1 para rodar)
#   lint          ruff check src tests eval scripts
#   pii           varredura de dados pessoais, incluindo colunas de texto dos .parquet
#   demo          demo de linha de comando sem GPU nem rede (LLM roteirizado, ferramentas falsas)
#   replay        demo do caso real com ferramentas reais e o LLM gravado (sem GPU; precisa do yolox_m,
#                 do vídeo semissintético e do cache de NDVI; ver README)
#   avaliacao     SÓ DEV: golden set (split dev; o teste está congelado e exige --final) e red-team
#                 original+v2 no modo determinístico (sem LLM nem GPU); relatórios em SAIDA_EVAL (padrão:
#                 eval/reports). Os números publicados são os da avaliação final (tarefa r4)
#   r4            avaliação final no split de teste congelado, em série, um modelo por vez
#                 (eval/rodada_r4.py): --a-seco só imprime a sequência; --retomar continua de onde parou.
#                 Ao fim, os números dos textos são atualizados a partir dos relatórios
#   custo         scripts/custo_fiscalizacao.py com os argumentos repassados
#   mcp           servidor MCP do domínio (python -m laudo.mcp_server) com os argumentos repassados
#   numeros       fonte única de números: docs/entregaveis/numeros.json|md a partir de eval/reports e
#                 atualização dos textos (--verificar só confere: código 1 se algum número divergir)
#   caso-demo     regera o DEMO-0001 (com a foto do DANFE) e o torna fictício (scripts/mascarar_demo.py);
#                 --verificar só confere
#   expurgo       retenção e expurgo LGPD por chave (scripts/expurgo_lgpd.py) com os argumentos repassados
#   ci            lint + testes + pii + números contra os relatórios. O GitHub Actions roda os mesmos passos,
#                 um a um, em ../.github/workflows/ci.yml (raiz do repositório, de dentro de laudo-vivo/), e
#                 ainda a avaliação só do dev; .github/workflows/ci.yml, nesta pasta, é a cópia para usar
#                 laudo-vivo/ como repositório próprio. Pesado (pytest inteiro e pii --parquet)
#   ajuda         esta mensagem
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ"
export PYTHONPATH="$RAIZ/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONUTF8=1

read -r -a PY_CMD <<< "${PY:-scripts/py.sh}"
# Script .sh vai pelo bash: no Linux o bit de execução nem sempre sobrevive ao clone feito no Windows.
case "${PY_CMD[0]}" in *.sh) PY_CMD=(bash "${PY_CMD[@]}") ;; esac

py() { "${PY_CMD[@]}" "$@"; }

ajuda() { awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "${BASH_SOURCE[0]}"; }

etapa() { printf '\n== %s ==\n' "$*"; }

testes() { py -m pytest tests -q "$@"; }

lint() { py -m ruff check src tests eval scripts "$@"; }

pii() { py scripts/checar_pii.py --parquet "$@"; }

demo() { py scripts/demo_cli.py "$@"; }

replay() {
  py scripts/demo_cli.py --ferramentas reais --llm replay \
    --replay tests/unit/dados_agente/replay_demo_real_qwen35_4b.jsonl "$@"
}

avaliacao() {
  # Só dev: com o split de teste congelado, run_eval.py sem --final roda só o dev (o teste fica para a
  # avaliação final, com --final --motivo e registro em eval/golden/casos/registro_teste.jsonl); o red-team
  # usa casos do dev como base e deixa o conjunto cego v3 de fora. Serve para desenvolvimento e para o CI.
  local saida="${SAIDA_EVAL:-eval/reports}"
  mkdir -p "$saida"
  etapa "golden set, split dev, modo determinístico (relatório em $saida)"
  py eval/run_eval.py --modo deterministico --split dev --saida "$saida"
  etapa "red-team original+v2, modo determinístico (relatório em $saida)"
  py eval/run_redteam.py --modo deterministico --saida "$saida"
}

r4() { py eval/rodada_r4.py "$@"; }

custo() { py scripts/custo_fiscalizacao.py "$@"; }

mcp() { py -m laudo.mcp_server "$@"; }

caso_demo() {
  if [ "${1:-}" != "--verificar" ]; then
    py eval/golden/gerador/gerar_casos.py --so-demo
    py eval/golden/gerador/gerar_danfe_demo.py
    py scripts/mascarar_demo.py
  fi
  py scripts/mascarar_demo.py --verificar
}

expurgo() { py scripts/expurgo_lgpd.py "$@"; }

numeros() {
  if [ "${1:-}" = "--verificar" ]; then
    shift
    py scripts/gerar_numeros.py --verificar "$@"
  else
    py scripts/gerar_numeros.py --aplicar "$@"
  fi
}

ci() {
  etapa "lint"
  lint
  etapa "testes"
  testes
  etapa "dados pessoais"
  pii
  etapa "números dos textos contra os relatórios"
  py scripts/gerar_numeros.py --verificar
}

tarefa="${1:-ajuda}"
[ $# -gt 0 ] && shift
case "$tarefa" in
  testes|lint|pii|demo|replay|avaliacao|r4|custo|mcp|numeros|expurgo|ci|ajuda)
    "$tarefa" "$@" ;;
  caso-demo) caso_demo "$@" ;;
  -h|--help|help) ajuda ;;
  *) echo "tarefa desconhecida: $tarefa" >&2; ajuda >&2; exit 2 ;;
esac
