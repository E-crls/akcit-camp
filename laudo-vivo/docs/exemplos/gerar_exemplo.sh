#!/usr/bin/env bash
# Gera de novo o laudo selado de exemplo de docs/exemplos/ (caso DEMO-0001, operação fictícia), sem GPU:
# roda a demo da CLI com as ferramentas reais e o LLM em replay numa pasta de dados FORA do repositório, confere o
# selo na instalação, monta tudo (laudo HTML e JSON, pacote de exibição, PDF, SHA256SUMS, gerado_com.json) numa
# pasta de montagem também fora do repositório, confere a montagem (selo, PII e frases proibidas, inclusive dentro
# do ZIP) e SÓ ENTÃO troca os arquivos de docs/exemplos/ e reescreve o bloco de estado do README.md.
#
# Quando: depois do FIM da r4 (dados_locais/r4/rodar_r4b.sh), que regrava as fixtures de replay e o cache do VLM
# no código congelado. Enquanto a r4 roda, o script recusa: a demo usa CPU e memória e a etapa "custo" da r4 roda
# a mesma demo ao vivo. Também recusa sem folga de memória (conferir_exemplo.py --folga).
#
# Uso (Git Bash, na raiz do repositório):
#   bash docs/exemplos/gerar_exemplo.sh               # 19 passos: roteiro do palco, com a foto do DANFE
#   bash docs/exemplos/gerar_exemplo.sh --passos 17   # 17 passos: só o XML da NF-e (= --sem-danfe)
#   opções: --dados DIR    pasta de dados (padrão ../.tmp_exemplo_laudo, irmã do repositório)
#           --manter       não apaga DIR no fim
#           --reusar       não roda a demo: usa a geração que já está em DIR (de um --manter anterior, com o
#                          mesmo --passos) e refaz do portão em diante (ex.: o PDF falhou)
#           --destino DIR  troca os arquivos em DIR em vez de docs/exemplos (para testar o script)
#           --ignorar-r4   roda mesmo com a r4 rodando (não use durante a r4 de verdade)
#
# Fixture de replay usada: 19 passos → tests/unit/dados_agente/replay_demo_real_qwen35_4b.jsonl;
# 17 passos → tests/unit/dados_agente/replay_demo_real_sem_danfe_qwen35_4b.jsonl.
# O script RECUSA uma geração incompleta (não SELADO, replay fora da gravação, LLM fora em algum turno, VLM fora
# do cache, falha de ferramenta, laudo sem satélite), e qualquer falha antes do passo 9 (a troca) deixa
# docs/exemplos/ como estava. Grave a fixture de novo (runbook, seção 8) ou use o outro caminho.
#
# Precisa: ambiente `lv` (scripts/py.sh), o vídeo semissintético e o modelo de contagem (docs/runbook.md, seção 1),
# o cache do satélite da gleba da demo em dados_locais/ndvi_cache, o Microsoft Edge instalado e um node_modules com
# playwright-core (padrão ../../personas-ux/app/node_modules; troque com NODE_PATH=...). Não usa Ollama nem GPU.
# Memória: um processo Python por vez e um Edge headless (sem GPU), fechado ao fim.
set -u
cd "$(dirname "$0")/../.." || exit 1
REPO="$(pwd)"
EX="docs/exemplos"
DEST="$EX"
PASSOS=19
MANTER=0
REUSAR=0
IGNORAR_R4=0
DADOS="$(cd .. && pwd)/.tmp_exemplo_laudo"
NODE_MODS="${NODE_PATH:-$(cd ../.. && pwd)/personas-ux/app/node_modules}"

while [ $# -gt 0 ]; do
  case "$1" in
    --passos) PASSOS="${2:-}"; shift 2 ;;
    --sem-danfe) PASSOS=17; shift ;;
    --dados) DADOS="${2:-}"; shift 2 ;;
    --manter) MANTER=1; shift ;;
    --reusar) REUSAR=1; MANTER=1; shift ;;
    --destino) DEST="${2:-}"; shift 2 ;;
    --ignorar-r4) IGNORAR_R4=1; shift ;;
    -h|--help) sed -n '2,31p' "$0"; exit 0 ;;
    *) echo "opção desconhecida: $1 (veja --help)"; exit 2 ;;
  esac
done

case "$PASSOS" in
  19) FIXTURE=tests/unit/dados_agente/replay_demo_real_qwen35_4b.jsonl; EXTRA=() ;;
  17) FIXTURE=tests/unit/dados_agente/replay_demo_real_sem_danfe_qwen35_4b.jsonl; EXTRA=(--sem-danfe) ;;
  *) echo "--passos tem de ser 19 ou 17"; exit 2 ;;
esac
[ -d "$DEST" ] || { echo "--destino não existe: $DEST"; exit 2; }
DEST="$(cd "$DEST" && pwd)"

passo() { echo; echo "== $*"; }
falha() { echo "FALHOU: $*"; echo "($DEST não mudou; pasta de dados mantida em $DADOS)"; exit 1; }

passo "0. pré-condições: r4 parada e folga de memória"
if ps -ef 2>/dev/null | grep -E "rodar_r4|rodada_r4\.py|tarefas\.sh r4" | grep -v grep > /dev/null; then
  if [ "$IGNORAR_R4" -eq 1 ]; then echo "AVISO: a r4 está rodando e --ignorar-r4 foi pedido"
  else echo "RECUSADO: a r4 está rodando (ps). Gere o exemplo depois do FIM dela."; exit 3; fi
else
  echo "r4: não está rodando"
fi
scripts/py.sh "$EX/conferir_exemplo.py" --folga \
  || { echo "RECUSADO: sem folga de memória; tente mais tarde"; exit 3; }

# a CLI apaga as subpastas de --dados: nunca dentro do repositório
mkdir -p "$DADOS" || exit 1
DADOS="$(cd "$DADOS" && pwd)"
case "$DADOS/" in
  "$REPO"/*) echo "--dados tem de ficar fora do repositório: $DADOS"; exit 2 ;;
esac
# só esvazia uma pasta criada por este script (marcador) ou vazia: nunca uma pasta qualquer passada por engano
if [ -n "$(ls -A "$DADOS" 2>/dev/null)" ] && [ ! -f "$DADOS/.pasta_exemplo_laudo" ]; then
  echo "--dados $DADOS não está vazia e não foi criada por este script: escolha outra pasta"; exit 2
fi
if [ "$REUSAR" -eq 1 ]; then
  [ -f "$DADOS/demo_cli.log" ] || { echo "--reusar: $DADOS/demo_cli.log não existe"; exit 2; }
else
  rm -rf "${DADOS:?}"/* 2>/dev/null
fi
touch "$DADOS/.pasta_exemplo_laudo"
MONTA="$DADOS/montagem"

if [ "$REUSAR" -eq 1 ]; then
  passo "1. demo da CLI: reusada de $DADOS (--reusar)"
else
  passo "1. demo da CLI em replay ($PASSOS passos; fixture $FIXTURE)"
  CMD=(scripts/py.sh scripts/demo_cli.py --ferramentas reais --llm replay --replay "$FIXTURE" "${EXTRA[@]}"
       --sem-cor --dados "$DADOS" --pacote)
  echo "+ ${CMD[*]}"
  "${CMD[@]}" > "$DADOS/demo_cli.log" 2>&1
  RC=$?
  grep -E "^Etapa final|replay:|tempo total" "$DADOS/demo_cli.log"
  [ $RC -eq 0 ] || falha "a demo saiu com código $RC (log em $DADOS/demo_cli.log)"
fi

passo "2. portão: a geração mostra o caso inteiro?"
scripts/py.sh "$EX/conferir_exemplo.py" --portao "$DADOS" "$DADOS/demo_cli.log" --passos "$PASSOS" \
  || falha "geração incompleta"

passo "3. selo conferido na instalação (cadeia, rascunho assinado, aprovações, HTML)"
scripts/py.sh -m laudo.audit.selo --dados "$DADOS" fis_demo_0001 > "$DADOS/selo.json"
RC=$?
grep -E '"(valido|motivo)"' "$DADOS/selo.json"
[ $RC -eq 0 ] || falha "laudo.audit.selo não confere (veja $DADOS/selo.json)"

passo "4. montagem em $MONTA (fora do repositório; $DEST ainda não muda)"
LAUDOS="$DADOS/laudos/fis_demo_0001"
ZIPS=("$LAUDOS"/pacote/DEMONSTRACAO_pacote_exibicao_*.zip)
[ "${#ZIPS[@]}" -eq 1 ] && [ -f "${ZIPS[0]}" ] \
  || falha "pacote de exibição ausente ou mais de um ZIP em $LAUDOS/pacote"
BYTES=$(wc -c < "${ZIPS[0]}")
[ "$BYTES" -lt 2097152 ] || falha "pacote de exibição com $BYTES bytes (limite de 2 MB para o repositório)"
rm -rf "$MONTA" && mkdir -p "$MONTA" || falha "não consegui criar $MONTA"
cp "$LAUDOS/laudo_selado.json" "$LAUDOS/laudo_selado.html" "$MONTA/" || falha "cópia do laudo"
cp "${ZIPS[0]}" "$MONTA/DEMONSTRACAO_pacote_exibicao.zip" || falha "cópia do pacote"
echo "laudo_selado.json, laudo_selado.html e DEMONSTRACAO_pacote_exibicao.zip ($BYTES bytes)"

passo "5. PDF com o Edge (playwright-core em $NODE_MODS)"
NODE_MODS_W="$(cygpath -w "$NODE_MODS" 2>/dev/null || echo "$NODE_MODS")"
NODE_PATH="$NODE_MODS_W" node "$EX/gerar_pdf.cjs" "$MONTA/laudo_selado.html" "$MONTA/laudo_selado.pdf" \
  || falha "PDF (Edge instalado? NODE_PATH com playwright-core?)"

passo "6. SHA256SUMS e gerado_com.json na montagem"
scripts/py.sh "$EX/conferir_exemplo.py" --registrar --pasta "$MONTA" --log "$DADOS/demo_cli.log" \
  --fixture "$FIXTURE" --selo-json "$DADOS/selo.json" || falha "registro"

passo "7. conferência da montagem (sem a instalação)"
scripts/py.sh "$EX/conferir_exemplo.py" --pasta "$MONTA" || falha "a montagem em $MONTA não confere"

passo "8. PII e frases proibidas: a montagem e o conteúdo do ZIP"
rm -rf "$DADOS/zip" && mkdir -p "$DADOS/zip" \
  && (cd "$DADOS/zip" && unzip -oq "$MONTA/DEMONSTRACAO_pacote_exibicao.zip") \
  || falha "não consegui abrir o ZIP para a varredura"
scripts/py.sh scripts/checar_pii.py "$MONTA" "$DADOS/zip" || falha "checar_pii acusou algo"
scripts/py.sh scripts/checar_frases_proibidas.py "$MONTA" "$DADOS/zip" \
  || falha "frase proibida na montagem ou no ZIP"

passo "9. troca em $DEST e bloco de estado do README"
# os dados primeiro, o registro por último: se algo falhar aqui, a conferência do passo 10 acusa
for f in laudo_selado.json laudo_selado.html laudo_selado.pdf DEMONSTRACAO_pacote_exibicao.zip SHA256SUMS \
         gerado_com.json; do
  mv -f "$MONTA/$f" "$DEST/$f" \
    || { echo "FALHOU: troca de $f em $DEST (troca parcial; rode de novo com --reusar)"; exit 1; }
done
if [ -f "$DEST/README.md" ]; then
  scripts/py.sh "$EX/conferir_exemplo.py" --atualizar-readme --pasta "$DEST" || { echo "FALHOU: README"; exit 1; }
fi

passo "10. conferência final de $DEST e frases proibidas do README"
scripts/py.sh "$EX/conferir_exemplo.py" --pasta "$DEST" || { echo "FALHOU: $DEST não confere"; exit 1; }
scripts/py.sh scripts/checar_frases_proibidas.py "$DEST" || { echo "FALHOU: frase proibida em $DEST"; exit 1; }

if [ "$MANTER" -eq 0 ]; then rm -rf "$DADOS"; else echo "pasta de dados mantida: $DADOS"; fi
passo "pronto: $DEST (confira também o repositório inteiro com scripts/py.sh scripts/checar_pii.py --parquet)"
