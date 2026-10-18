#!/usr/bin/env bash
# Publicação do Laudo Vivo no GitHub: tag de congelamento (inscrição, relatório, regional) e push. SÓ com o OK
# explícito da equipe (memorando de 16/10/2026, 5A: "push público com tag, que só acontece com OK explícito
# da equipe").
#
# Por padrão este script NÃO executa nada: imprime a checagem prévia e os comandos, na ordem, para conferir.
# O modo sai do estado do git:
#   - modo "tag" (o caso de hoje): o repositório já tem commit e remoto `origin`. Passos: checagem completa,
#     árvore limpa no ramo, tag anotada e push do ramo e da tag;
#   - modo "primeiro": repositório sem commit (por exemplo, a pasta laudo-vivo/ publicada à parte). Passos:
#     checagem, conferência do que entra, primeiro commit, remoto, tag e push.
#
#   scripts/publicar.sh [--tag NOME] [--ramo main]                  # só imprime (nenhum comando roda)
#   scripts/publicar.sh --executar --tag regional-2026-10-24       # modo tag, passo a passo
#   scripts/publicar.sh --executar --remoto URL [--tag NOME]       # modo primeiro, passo a passo
#
# Com --executar, CADA passo mostra o comando e espera a palavra PUBLICAR digitada no terminal (lida de
# /dev/tty; sem terminal interativo, o script recusa e não roda nada). Enter vazio ou qualquer outra
# resposta encerra ali. Só o responsável pela publicação roda --executar: é ele quem digita a confirmação.
#
#   --remoto URL   só no modo primeiro: repositório vazio já criado no GitHub
#                  (ex.: https://github.com/<conta>/laudo-vivo.git)
#   --tag NOME     tag anotada (padrão: inscricao-AAAAMMDD de hoje; ver ../negocio/inscricao.md, "Depois de
#                  enviar"); no congelamento do regional, use regional-2026-10-24
#   --ramo NOME    ramo publicado (padrão: main)
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTO="<URL do repositório vazio no GitHub>"
TAG="inscricao-$(date +%Y%m%d)"
RAMO="main"
EXECUTAR=0

while [ $# -gt 0 ]; do
  case "$1" in
    --executar) EXECUTAR=1 ;;
    --remoto) REMOTO="${2:?--remoto precisa de URL}"; shift ;;
    --tag) TAG="${2:?--tag precisa de nome}"; shift ;;
    --ramo) RAMO="${2:?--ramo precisa de nome}"; shift ;;
    -h|--help)
      awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "${BASH_SOURCE[0]}"
      exit 0 ;;
    *) echo "opção desconhecida: $1 (veja --help)" >&2; exit 2 ;;
  esac
  shift
done

cd "$RAIZ"
if git rev-parse --verify -q HEAD > /dev/null 2>&1; then
  MODO="tag"
  REMOTO="$(git remote get-url origin 2> /dev/null | sed -E 's#://[^/@]+@#://#' || true)"
  REMOTO="${REMOTO:-<sem remoto origin>}"
else
  MODO="primeiro"
fi

MENSAGEM="Laudo Vivo: primeira versão pública (AKCIT Camp 2026, regional Centro-Oeste)

Agente de fiscalização do crédito rural (MCR 2-7): triagem da carteira, coleta guiada,
conciliação de vídeo, NF-e e GTA, laudo com status por item, abstenção e assinatura humana.
Avaliação em eval/ (golden set com split de teste congelado em 16/10/2026, red-team, A/B);
números do pitch em docs/entregaveis/numeros.md, conferidos por scripts/gerar_numeros.py."

# Caminhos que nunca entram no git (dados brutos, segredos, pesos, vídeos, Sicor bruto ou com CPF).
PROIBIDOS='(^|/)dados_locais/|(^|/)\.env$|\.(onnx|gguf|safetensors|pt|pth|mov)$|SICOR_|sicor_.*\.gz$'
NOVOS="git ls-files --others --exclude-standard"
CHECAGEM="checagem completa: lint, testes, dados pessoais, frases proibidas e números (scripts/tarefas.sh ci)"

# Passos: título e comando (o texto exibido é o mesmo que roda com bash -c no --executar).
if [ "$MODO" = "tag" ]; then
  TITULOS=(
    "$CHECAGEM"
    "árvore limpa no ramo $RAMO (tudo o que vai na tag já está em commit)"
    "tag anotada $TAG"
    "push do ramo e da tag"
  )
  COMANDOS=(
    "bash scripts/tarefas.sh ci"
    "if [ -n \"\$(git status --porcelain)\" ]; then
       git status --short; echo 'há mudanças sem commit: faça o commit antes da tag' >&2; exit 1
     fi
     if [ \"\$(git rev-parse --abbrev-ref HEAD)\" != '$RAMO' ]; then
       echo 'o ramo atual não é $RAMO: pare' >&2; exit 1
     fi
     echo 'ok: árvore limpa no ramo $RAMO'"
    "git tag -a $TAG -m 'Laudo Vivo: $TAG'"
    "git push origin $RAMO && git push origin $TAG"
  )
else
  TITULOS=(
    "$CHECAGEM"
    "conferir o que vai entrar: nada de dados_locais/, pesos, vídeos, .env ou Sicor bruto; nada > 50 MB"
    "preparar o commit (git add -A respeita o .gitignore)"
    "primeiro commit (a mensagem está no fim desta tela)"
    "renomear o ramo local para $RAMO"
    "apontar o remoto"
    "tag anotada $TAG"
    "push do ramo e da tag (a partir daqui o repositório fica público, se o remoto for público)"
  )
  COMANDOS=(
    "bash scripts/tarefas.sh ci"
    "if $NOVOS | grep -E '$PROIBIDOS'; then
       echo 'proibido fora do .gitignore: pare' >&2; exit 1
     fi
     if $NOVOS -z | xargs -0 -r du -m | awk '\$1 > 50' | grep .; then
       echo 'acima de 50 MB: pare' >&2; exit 1
     fi
     echo 'ok: nada proibido nem grande'"
    "git add -A
     if git diff --cached --name-only | grep -E '$PROIBIDOS'; then
       echo 'proibido no índice: pare (git rm --cached)' >&2; exit 1
     fi
     echo \"\$(git diff --cached --name-only | wc -l) arquivos no índice\""
    "git commit -F <arquivo temporário com a mensagem abaixo>"
    "git branch -M $RAMO"
    "git remote add origin $REMOTO"
    "git tag -a $TAG -m 'Laudo Vivo: primeira versão pública ($TAG)'"
    "git push -u origin $RAMO && git push origin $TAG"
  )
fi

imprimir() {
  printf 'Publicação do Laudo Vivo (raiz: %s; modo: %s)\n' "$RAIZ" "$MODO"
  printf 'Remoto: %s | ramo: %s | tag: %s\n\n' "$REMOTO" "$RAMO" "$TAG"
  printf 'Antes de tudo (fora deste script):\n'
  printf '  - OK explícito da equipe para publicar;\n'
  if [ "$MODO" = "primeiro" ]; then
    printf '  - repositório criado VAZIO no GitHub (sem README, sem licença: os dois já estão aqui);\n'
  else
    printf '  - visibilidade do repositório no GitHub decidida (a banca precisa abrir o link);\n'
  fi
  printf '  - docs/EQUIPE.md e os ⚠ PREENCHER da equipe revistos (o que for público fica público);\n'
  printf '  - git config user.name / user.email com a identidade que deve aparecer no histórico.\n\n'
  local i
  for i in "${!TITULOS[@]}"; do
    printf '%d. %s\n   $ %s\n' "$((i + 1))" "${TITULOS[$i]}" "${COMANDOS[$i]}"
  done
  if [ "$MODO" = "primeiro" ]; then
    printf '\nMensagem do commit:\n%s\n' "$MENSAGEM" | sed 's/^/   /'
  fi
  printf '\nDepois: abrir o repositório numa aba anônima; conferir que o CI (GitHub Actions) ficou\n'
  printf 'verde; colar o link no formulário da inscrição e no README ("Tema registrado na inscrição").\n'
}

confirmar() {
  local resposta=""
  printf '\n>>> %s\n    $ %s\n' "$1" "$2" > /dev/tty
  printf '    Digite PUBLICAR para executar este passo (qualquer outra coisa encerra): ' > /dev/tty
  IFS= read -r resposta < /dev/tty || resposta=""
  [ "$resposta" = "PUBLICAR" ]
}

imprimir
if [ "$EXECUTAR" -ne 1 ]; then
  if [ "$MODO" = "tag" ]; then
    printf '\nNada foi executado (modo padrão). Para executar passo a passo: --executar --tag NOME.\n'
  else
    printf '\nNada foi executado (modo padrão). Para executar passo a passo: --executar --remoto URL.\n'
  fi
  exit 0
fi

# --- daqui para baixo só com --executar, terminal interativo e confirmação digitada em cada passo ---
if ! { exec 3<> /dev/tty; } 2> /dev/null; then
  echo "sem terminal interativo (/dev/tty): nada foi executado" >&2
  exit 3
fi
exec 3>&-
if git rev-parse -q --verify "refs/tags/$TAG" > /dev/null; then
  echo "a tag $TAG já existe: escolha outro nome com --tag; nada foi executado" >&2
  exit 2
fi
if [ "$MODO" = "tag" ]; then
  if ! git remote get-url origin > /dev/null 2>&1; then
    echo "o repositório tem commit mas não tem remoto 'origin' (veja git remote -v); nada foi executado" >&2
    exit 2
  fi
else
  case "$REMOTO" in
    https://github.com/*/*.git|git@github.com:*/*.git) ;;
    *) echo "--remoto inválido ou ausente ($REMOTO): nada foi executado" >&2; exit 2 ;;
  esac
  if git remote get-url origin > /dev/null 2>&1; then
    echo "já existe um remoto 'origin': confira com git remote -v; nada foi executado" >&2
    exit 2
  fi
  MSG_ARQ="$(mktemp)"
  trap 'rm -f "$MSG_ARQ"' EXIT
  printf '%s\n' "$MENSAGEM" > "$MSG_ARQ"
  COMANDOS[3]="git commit -F '$MSG_ARQ'"
fi

for i in "${!TITULOS[@]}"; do
  if ! confirmar "$((i + 1)). ${TITULOS[$i]}" "${COMANDOS[$i]}"; then
    printf 'Encerrado no passo %d sem executá-lo; o que já rodou fica (veja git status).\n' "$((i + 1))"
    exit 1
  fi
  bash -c "set -euo pipefail; ${COMANDOS[$i]}"
done
printf '\nPublicado: %s (ramo %s, tag %s). Confira o CI no GitHub.\n' "$REMOTO" "$RAMO" "$TAG"
