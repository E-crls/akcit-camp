#!/usr/bin/env bash
# Sobe a demo do Laudo Vivo: Ollama (se preciso) → aquece o modelo e o Whisper → API + web → abre o navegador.
#
# Uso (na raiz do repositório laudo-vivo):
#   scripts/rodar_demo.sh                 # ao vivo: Ollama + Whisper na GPU + caso DEMO-0001 (ou o roteiro)
#   scripts/rodar_demo.sh --gravar        # ao vivo, gravando as respostas do LLM para a contingência
#   scripts/rodar_demo.sh --replay        # CONTINGÊNCIA: reproduz a demo gravada, sem GPU nem rede
#
# Opções:
#   --caso ID|roteiro        caso do botão "Abrir demo" (padrão: DEMO-0001 se existir; senão o roteiro do agente)
#   --casos-dir DIR          pasta(s) de casos de demonstração fora do repositório (LAUDO_CASOS_DIR): entram na
#                            carteira e abrem por id (ex.: --casos-dir ../casos --caso CAMPO-0001)
#   --ferramentas MODO       falsas | mistas | reais (padrão: reais no caso do golden; falsas no roteiro).
#                            mistas = documentos, fotos e regras reais, contagem de vídeo simulada (instantânea)
#   --replay-arquivo ARQ     gravação JSONL específica (padrão: dados_locais/api/gravacoes/<caso>.jsonl,
#                            replay*.jsonl da pasta do caso ou, no roteiro, a fixture do teste de replay)
#   --modelo M | --perfil P  modelo do Ollama (padrão: perfil campo = qwen3.5:4b)
#   --porta N (8000) · --host H (127.0.0.1; use 0.0.0.0 para o celular na mesma rede)
#   --https                  certificado autoassinado (o celular só libera microfone e GPS em HTTPS)
#   --sem-voz                não carrega o Whisper (a fala é digitada)
#   --com-voz                carrega o Whisper também no --replay (usa GPU se houver)
#   --sem-navegador          não abre o navegador
#   --hoje AAAA-MM-DD        data de referência fixa
#   --descarregar            ao sair, descarrega o modelo do Ollama (libera a VRAM)
#   --pin NNNN               PIN da assinatura (padrão: LAUDO_PIN ou o PIN de demonstração 2410)
#   --vlm-gravado            (PADRÃO) ao vivo, lê a foto do DANFE da demo pelo cache gravado do VLM
#                            (instantâneo, mesma foto e mesmo pedido; foto nova continua indo ao VLM). No
#                            --replay é sempre assim.
#   --vlm-ao-vivo            ao vivo, manda a foto do DANFE ao VLM de verdade (~15 s; mostra o modelo lendo o
#                            papel)
#   --vlm-cache-gravacao DIR onde gravar as respostas NOVAS do VLM (foto fora do cache da demo; também lidas no
#                            --replay). Padrão: LAUDO_VLM_CACHE_GRAVACAO ou dados_locais/vlm_cache (nunca tests/)
#   --sem-apresentacao       abre o navegador sem o modo apresentação (o padrão é com: cabeçalho recolhido,
#                            conversa grande, prova numa gaveta; o botão "Modo apresentação" no topo alterna)
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ"
DADOS="$RAIZ/dados_locais/api"
mkdir -p "$DADOS/gravacoes"

MODO="aovivo"; CASO="${LAUDO_CASO_DEMO:-}"; FERR=""; REPLAY_ARQ=""; MODELO=""; PERFIL="campo"; VLM_GRAVADO=1
APRESENTACAO=1
PORTA=8000; HOST=127.0.0.1; HTTPS=0; VOZ=""; NAVEGADOR=1; HOJE=""; DESCARREGAR=0; GRAVAR=0
while [ $# -gt 0 ]; do
  case "$1" in
    --replay) MODO="replay" ;;
    --gravar) GRAVAR=1 ;;
    --caso) CASO="$2"; shift ;;
    --casos-dir) export LAUDO_CASOS_DIR="$2"; shift ;;
    --ferramentas) FERR="$2"; shift ;;
    --replay-arquivo) REPLAY_ARQ="$2"; shift ;;
    --modelo) MODELO="$2"; shift ;;
    --perfil) PERFIL="$2"; shift ;;
    --porta) PORTA="$2"; shift ;;
    --host) HOST="$2"; shift ;;
    --https) HTTPS=1 ;;
    --sem-voz) VOZ="desligado" ;;
    --com-voz) VOZ="auto" ;;
    --sem-navegador) NAVEGADOR=0 ;;
    --hoje) HOJE="$2"; shift ;;
    --descarregar) DESCARREGAR=1 ;;
    --pin) export LAUDO_PIN="$2"; shift ;;
    --vlm-gravado) VLM_GRAVADO=1 ;;
    --vlm-ao-vivo) VLM_GRAVADO=0 ;;
    --sem-apresentacao) APRESENTACAO=0 ;;
    --vlm-cache-gravacao) export LAUDO_VLM_CACHE_GRAVACAO="$2"; shift ;;
    -h|--help) sed -n '2,34p' "$0"; exit 0 ;;
    *) echo "opção desconhecida: $1 (veja --help)" >&2; exit 2 ;;
  esac
  shift
done

# caso padrão: o da demo do regional, se o integrador já montou; senão o roteiro do agente
if [ -z "$CASO" ]; then
  if [ -f eval/golden/demo/DEMO-0001/caso.yaml ] || [ -f eval/golden/casos/DEMO-0001/caso.yaml ]; then
    CASO="DEMO-0001"
  else
    CASO="roteiro"
  fi
fi
if [ -z "$FERR" ]; then
  if [ "$CASO" = "roteiro" ]; then FERR="falsas"; else FERR="reais"; fi
fi
OLLAMA_URL="${OLLAMA_HOST:-http://127.0.0.1:11434}"
case "$OLLAMA_URL" in http*) ;; *) OLLAMA_URL="http://$OLLAMA_URL" ;; esac

ARGS=(--porta "$PORTA" --host "$HOST" --caso "$CASO" --ferramentas "$FERR" --perfil "$PERFIL")
if [ "$VLM_GRAVADO" = 1 ] && [ "$MODO" != "replay" ]; then
  ARGS+=(--vlm-cache "$RAIZ/tests/unit/dados_agente/vlm_cache_demo")
  echo "▶ Leitura do DANFE da demo pelo cache gravado do VLM (--vlm-ao-vivo para mandar a foto ao modelo)."
fi
[ -n "$MODELO" ] && ARGS+=(--modelo "$MODELO")
[ -n "$HOJE" ] && ARGS+=(--hoje "$HOJE")

if [ "$MODO" = "replay" ]; then
  ARGS+=(--llm replay --asr "${VOZ:-desligado}")
  [ -n "$REPLAY_ARQ" ] && ARGS+=(--replay "$REPLAY_ARQ")
  [ "${VOZ:-desligado}" != "desligado" ] && ARGS+=(--aquecer)
  echo "▶ CONTINGÊNCIA (replay): caso $CASO, ferramentas $FERR, sem LLM ao vivo."
else
  ARGS+=(--llm ollama --asr "${VOZ:-auto}" --aquecer)
  if ! curl -fsS --max-time 3 "$OLLAMA_URL/api/version" >/dev/null 2>&1; then
    if command -v ollama >/dev/null 2>&1; then
      echo "▶ Ollama fora do ar: iniciando 'ollama serve'…"
      (ollama serve >"$DADOS/ollama.log" 2>&1 &)
      for _ in $(seq 1 30); do
        curl -fsS --max-time 2 "$OLLAMA_URL/api/version" >/dev/null 2>&1 && break
        sleep 1
      done
    fi
  fi
  if curl -fsS --max-time 3 "$OLLAMA_URL/api/version" >/dev/null 2>&1; then
    echo "▶ Ollama em $OLLAMA_URL (o modelo é aquecido pela API na subida)."
  else
    echo "⚠ Ollama indisponível: o agente segue com o plano mínimo determinístico. Para contingência: --replay"
  fi
  if [ "$GRAVAR" = 1 ]; then
    # o replay procura gravacoes/<id do caso.yaml>.jsonl: com --caso <pasta>, o nome sai do id, não do caminho
    ID_CASO="$CASO"
    if [ -f "$CASO/caso.yaml" ]; then
      ID_CASO="$(sed -n 's/^id:[[:space:]]*//p' "$CASO/caso.yaml" | head -n 1 | tr -d "\"'\r")"
      [ -n "$ID_CASO" ] || ID_CASO="$(basename "$CASO")"
    fi
    G="$DADOS/gravacoes/$ID_CASO.jsonl"
    [ -f "$G" ] && mv "$G" "$G.$(date +%Y%m%d-%H%M%S).bak"
    ARGS+=(--gravar "$G")
    echo "▶ Gravando as respostas do LLM em $G (use depois: scripts/rodar_demo.sh --replay --caso $CASO)."
  fi
fi

ESQUEMA="http"
if [ "$HTTPS" = 1 ]; then
  TLS="$DADOS/tls"; mkdir -p "$TLS"
  if [ ! -f "$TLS/cert.pem" ]; then
    command -v openssl >/dev/null 2>&1 || { echo "openssl não encontrado para gerar o certificado" >&2; exit 1; }
    MSYS_NO_PATHCONV=1 openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj "/CN=laudo-vivo-demo" \
      -keyout "$TLS/key.pem" -out "$TLS/cert.pem" >/dev/null 2>&1
  fi
  ARGS+=(--ssl-certfile "$TLS/cert.pem" --ssl-keyfile "$TLS/key.pem")
  ESQUEMA="https"
fi

PIDF="$DADOS/api.pid"
rm -f "$PIDF"
encerrar() {
  if [ -f "$PIDF" ]; then
    PID="$(cat "$PIDF")"
    if command -v taskkill >/dev/null 2>&1; then
      taskkill //PID "$PID" //T //F >/dev/null 2>&1 || true
    else
      kill "$PID" 2>/dev/null || true
    fi
    rm -f "$PIDF"
  fi
  if [ "$DESCARREGAR" = 1 ] && [ "$MODO" != "replay" ]; then
    M="${MODELO:-qwen3.5:4b}"
    curl -fsS --max-time 20 "$OLLAMA_URL/api/generate" -d "{\"model\":\"$M\",\"keep_alive\":0}" >/dev/null 2>&1 || true
    echo "▶ Modelo $M descarregado do Ollama."
  fi
}
trap encerrar EXIT INT TERM

echo "▶ Subindo a API (carregar o Whisper leva ~5 s na GPU)…"
"$RAIZ/scripts/py.sh" -m laudo.api "${ARGS[@]}" &
API_BG=$!

URL_LOCAL="$ESQUEMA://127.0.0.1:$PORTA/"
URL_ABRIR="$URL_LOCAL"
[ "$APRESENTACAO" = 1 ] && URL_ABRIR="${URL_LOCAL}?apresentacao=1"
for _ in $(seq 1 180); do
  curl -fsSk --max-time 2 "${URL_LOCAL}api/saude" >/dev/null 2>&1 && break
  if ! kill -0 "$API_BG" 2>/dev/null; then echo "a API não subiu (veja a saída acima)" >&2; exit 1; fi
  sleep 1
done
curl -fsSk --max-time 5 "${URL_LOCAL}api/saude" >/dev/null || { echo "a API não respondeu em 180 s" >&2; exit 1; }

echo "▶ Pronto: $URL_LOCAL  (caso $CASO · F11 para tela cheia · Ctrl+C para encerrar)"
if [ "$HOST" = "0.0.0.0" ]; then
  IP="$( (ipconfig 2>/dev/null | grep -a -m1 -E 'IPv4' | sed -E 's/.*: *//') || hostname -I 2>/dev/null | awk '{print $1}')"
  [ -n "$IP" ] && echo "▶ No celular (mesma rede): $ESQUEMA://${IP//[$'\r']/}:$PORTA/"
fi
if [ "$NAVEGADOR" = 1 ]; then
  if command -v cmd.exe >/dev/null 2>&1; then cmd.exe /c start "" "$URL_ABRIR" >/dev/null 2>&1 || true
  elif command -v open >/dev/null 2>&1; then open "$URL_ABRIR" || true
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL_ABRIR" >/dev/null 2>&1 || true
  fi
fi
wait "$API_BG"
