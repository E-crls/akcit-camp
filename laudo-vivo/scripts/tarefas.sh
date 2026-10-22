#!/usr/bin/env bash
# Tarefas do Laudo Vivo num só lugar (Git Bash no Windows e Linux no CI). Rode a partir de qualquer pasta:
#
#   scripts/tarefas.sh <tarefa> [argumentos]
#
# O interpretador vem de PY (padrão: scripts/py.sh, ambiente conda-forge "lv"; no CI: PY=python).
# Tarefas:
#   testes        pytest tests -q (lentos e de rede pulados; LAUDO_LENTO=1 / LAUDO_TESTES_REDE=1 para rodar)
#   lint          ruff check src tests eval scripts
#   pii           varredura de dados pessoais, incluindo colunas de texto dos .parquet
#   frases        frases proibidas (memorando de 16/10/2026, seção 4, e P20 a P25 depois da r4) nos textos
#                 públicos, em docs/exemplos/ (com o texto de dentro do .zip) e em ../negocio/
#                 (scripts/checar_frases_proibidas.py; --regras lista as regras e o "diga no lugar"; --relatorio
#                 lista sem falhar; --so P20-P25 só essas regras)
#   demo          demo de linha de comando sem GPU nem rede (LLM roteirizado, ferramentas falsas)
#   replay        demo do caso real com ferramentas reais e o LLM gravado (sem GPU; precisa do yolox_m,
#                 do vídeo semissintético e do cache de NDVI; ver README)
#   avaliacao     SÓ DEV: golden set (split dev; o teste está congelado e exige --final) e red-team
#                 original+v2 no modo determinístico (sem LLM nem GPU); relatórios em SAIDA_EVAL (padrão:
#                 eval/reports). Não é número de palco: o número final é o da r4 (tarefa r4)
#   r4            rodada r4 congelada, em série, um modelo por vez (eval/rodada_r4.py): --a-seco só imprime a
#                 sequência; --retomar continua de onde parou. Depois dela, slide e números (versão de palco)
#   custo         scripts/custo_fiscalizacao.py com os argumentos repassados
#   mcp           servidor MCP do domínio (python -m laudo.mcp_server) com os argumentos repassados
#   numeros       fonte única de números: docs/entregaveis/numeros.json|md a partir de eval/reports e
#                 atualização dos textos (--verificar só confere: código 1 se algum número divergir)
#   fixos         números de fonte fixa (mercado, Fiscal-GO, vídeo) entre marcadores <!--f:chave-->, conferidos
#                 contra a fonte (scripts/checar_numeros_fixos.py; --chaves lista as chaves)
#   tempo         tempo do pitch regional estimado do próprio texto (scripts/tempo_pitch.py --conferir): versão A
#                 até 2:50 e versão B até 4:45; argumentos extras vão para as duas (ex.: --ppm 130)
#   entregaveis   lista os entregáveis de docs/entregaveis/ (fonte canônica; nada é copiado de ../negocio)
#                 e confere as frases proibidas, os números (gerar_numeros.py --verificar), os números de fonte
#                 fixa e o tempo do pitch
#   caso-demo     regera o DEMO-0001 (com a foto do DANFE) e o torna fictício (scripts/mascarar_demo.py);
#                 --verificar só confere
#   expurgo       retenção e expurgo LGPD por chave (scripts/expurgo_lgpd.py) com os argumentos repassados
#   ci            CI da raiz = variante da pasta + lint + testes + pii + frases + números + fonte fixa + tempo
#                 do pitch. O GitHub Actions roda os mesmos passos, um a um, em ../.github/workflows/ci.yml
#                 (raiz do repositório, de dentro de laudo-vivo/), e ainda a avaliação só dev;
#                 .github/workflows/ci.yml, nesta pasta, é a variante para a pasta publicada à parte, onde
#                 o ../negocio não existe e é pulado (scripts/checar_ci.py confere que as duas têm os mesmos
#                 passos). Pesado (pytest inteiro e pii --parquet): na máquina compartilhada, rode sozinho
#                 (bash dados_locais/fila.sh scripts/tarefas.sh ci)
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

frases() {
  if [ $# -eq 0 ]; then py scripts/checar_frases_proibidas.py --autoteste; fi
  py scripts/checar_frases_proibidas.py "$@"
}

fixos() { py scripts/checar_numeros_fixos.py "$@"; }

tempo() {
  # A versão A (3 min) tem de caber em 2:50 e a B (5 min) em 4:45; o cronômetro do ensaio D-1 manda.
  py scripts/tempo_pitch.py --conferir "$@"
  py scripts/tempo_pitch.py --versao B --conferir "$@"
}

demo() { py scripts/demo_cli.py "$@"; }

replay() {
  py scripts/demo_cli.py --ferramentas reais --llm replay \
    --replay tests/unit/dados_agente/replay_demo_real_qwen35_4b.jsonl "$@"
}

avaliacao() {
  # Só dev: com o split de teste congelado, run_eval.py sem --final roda só o dev (o teste fica para a r4, com
  # --final --motivo e registro em eval/golden/casos/registro_teste.jsonl); o red-team usa casos do dev como base
  # e deixa o conjunto cego v3 de fora. Serve para desenvolvimento e para o CI, não para o slide.
  local saida="${SAIDA_EVAL:-eval/reports}"
  mkdir -p "$saida"
  etapa "golden set, split dev, modo determinístico (relatório em $saida)"
  py eval/run_eval.py --modo deterministico --split dev --saida "$saida"
  etapa "red-team original+v2, modo determinístico (relatório em $saida)"
  py eval/run_redteam.py --modo deterministico --saida "$saida"
}

r4() { py eval/rodada_r4.py "$@"; }

custo() {
  if [ ! -f scripts/custo_fiscalizacao.py ]; then
    echo "scripts/custo_fiscalizacao.py ainda não existe" >&2
    return 1
  fi
  py scripts/custo_fiscalizacao.py "$@"
}

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

entregaveis() {
  # Desde 09/10/2026 a fonte canônica de BMC, pitches, Q&A e números é docs/entregaveis/ (o edital exige no
  # GitHub). ../negocio/ guarda só o que não é entregável (plano de negócio, kit de validação) e aponta para cá.
  # Esta tarefa NÃO copia nada (copiar de ../negocio desfazia as correções): lista e confere os números.
  local destino="docs/entregaveis" arq
  [ "${1:-}" = "--simular" ] && shift
  for arq in bmc-v1.md bmc-v1.html pitch-regional-3min.md pitch-final-5min.md qa-banca.md numeros.md numeros.json; do
    if [ -f "$destino/$arq" ]; then echo "ok: $destino/$arq"; else echo "falta: $destino/$arq" >&2; return 1; fi
  done
  frases
  py scripts/gerar_numeros.py --verificar
  fixos
  tempo
}

ci() {
  etapa "CI da raiz e variante da pasta com os mesmos passos"
  py scripts/checar_ci.py
  etapa "lint"
  lint
  etapa "testes"
  testes
  etapa "dados pessoais"
  pii
  etapa "frases proibidas nos entregáveis"
  frases
  etapa "números do pitch, Q&A e slide contra os relatórios"
  py scripts/gerar_numeros.py --verificar
  etapa "números de fonte fixa (mercado, Fiscal-GO e vídeo) contra a fonte"
  fixos
  etapa "tempo do pitch (A até 2:50, B até 4:45)"
  tempo
}

tarefa="${1:-ajuda}"
[ $# -gt 0 ] && shift
case "$tarefa" in
  testes|lint|pii|frases|fixos|tempo|demo|replay|avaliacao|r4|custo|mcp|numeros|entregaveis|expurgo|ci|ajuda)
    "$tarefa" "$@" ;;
  caso-demo) caso_demo "$@" ;;
  -h|--help|help) ajuda ;;
  *) echo "tarefa desconhecida: $tarefa" >&2; ajuda >&2; exit 2 ;;
esac
