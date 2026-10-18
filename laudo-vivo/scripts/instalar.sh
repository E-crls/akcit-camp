#!/usr/bin/env bash
# Instalador do Laudo Vivo (Linux, macOS e Git Bash no Windows). Um comando, na pasta laudo-vivo/:
#
#   bash scripts/instalar.sh            # ambiente + ativos da demo + teste rápido (~3 a 10 min na 1ª vez)
#
# O que faz, em ordem:
#   1. ambiente: com micromamba, mamba ou conda no PATH (nessa ordem), cria ou atualiza o ambiente
#      "laudo-vivo" a partir do environment.yml (conda-forge). Sem nenhum deles, cria .venv/ com Python 3.12 e
#      instala o pyproject.toml do PyPI (extras geo, vision e voice e o grupo dev);
#   2. voz: no ambiente conda, tenta `pip install faster-whisper` (só existe no PyPI; é opcional) e, no
#      Windows, aplica o ajuste de OpenMP da docs/adr/002-ambiente.md (preparar_demo.py --ajustar-openmp);
#   3. ativos: scripts/preparar_demo.py (vídeo e satélite da demo vêm do repositório; o detector YOLOX é
#      baixado da release oficial; tudo com sha256 conferido);
#   4. teste rápido: a demo da linha de comando com ferramentas reais e LLM gravado (19 passos, ~15 s) e a
#      conferência do laudo selado de exemplo.
# O comando do Python fica registrado em dados_locais/interpretador (o Makefile usa).
#
# Opções:
#   --venv          usa venv + pip mesmo com conda/micromamba disponível
#   --nome NOME     nome do ambiente conda (padrão: laudo-vivo)
#   --sem-voz       não tenta instalar o faster-whisper
#   --sem-teste     não roda o teste rápido
#   -h, --help      esta ajuda
#
# Requisitos, tempos e problemas comuns: docs/COMO_RODAR.md. Nada aqui exige GPU nem login em serviço algum.
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ"
export PYTHONPATH="$RAIZ/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONUTF8=1

NOME="laudo-vivo"; FORCAR_VENV=0; VOZ=1; TESTE=1
while [ $# -gt 0 ]; do
  case "$1" in
    --venv) FORCAR_VENV=1 ;;
    --nome) NOME="${2:?--nome precisa de um nome}"; shift ;;
    --sem-voz) VOZ=0 ;;
    --sem-teste) TESTE=0 ;;
    -h|--help)
      awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "${BASH_SOURCE[0]}"
      exit 0 ;;
    *) echo "opção desconhecida: $1 (veja --help)" >&2; exit 2 ;;
  esac
  shift
done

etapa() { printf '\n== %s ==\n' "$*"; }
T0=$(date +%s)

# --- 1. ambiente -----------------------------------------------------------------------------------------
GERENTE=""
if [ "$FORCAR_VENV" = 0 ]; then
  for g in micromamba mamba conda; do
    if command -v "$g" >/dev/null 2>&1; then GERENTE="$g"; break; fi
  done
fi

if [ -n "$GERENTE" ]; then
  etapa "1/4 ambiente conda-forge \"$NOME\" com $GERENTE (environment.yml)"
  if [ "$GERENTE" = conda ]; then
    RODAR=(conda run --no-capture-output -n "$NOME")
  else
    RODAR=("$GERENTE" run -n "$NOME")
  fi
  # micromamba aceita o .yml em create/install; conda e mamba, em env create/env update (sem perguntar)
  export CONDA_ALWAYS_YES=true MAMBA_ALWAYS_YES=true
  if "${RODAR[@]}" python -c "import sys" >/dev/null 2>&1; then
    echo "o ambiente já existe: atualizando"
    if [ "$GERENTE" = micromamba ]; then
      micromamba install -y -n "$NOME" -f environment.yml
    else
      "$GERENTE" env update -n "$NOME" -f environment.yml
    fi
  else
    if [ "$GERENTE" = micromamba ]; then
      micromamba create -y -n "$NOME" -f environment.yml
    else
      "$GERENTE" env create -n "$NOME" -f environment.yml
    fi
  fi
  PY=("${RODAR[@]}" python)
  if [ "$VOZ" = 1 ]; then
    etapa "2/4 voz (opcional): faster-whisper do PyPI"
    if "${PY[@]}" -m pip install --retries 1 --timeout 20 "faster-whisper>=1.1"; then
      echo "voz: ok"
      # Windows: o ctranslate2 do PyPI e o shim de OpenMP do conda-forge (docs/adr/002-ambiente.md)
      "${PY[@]}" scripts/preparar_demo.py --ajustar-openmp
    else
      echo "AVISO: faster-whisper não instalado (PyPI inacessível?). A demo em replay não depende dele;"
      echo "       sem ele, a fala é digitada e os 5 testes de tests/unit/test_voz_asr.py falham."
    fi
  else
    etapa "2/4 voz: pulada (--sem-voz)"
  fi
else
  etapa "1/4 ambiente: venv + pip (Python 3.12), sem conda/micromamba no PATH"
  BASE=""
  for c in python3.12 python3 python py; do
    command -v "$c" >/dev/null 2>&1 || continue
    if [ "$c" = py ]; then CAND=(py -3.12); else CAND=("$c"); fi
    if "${CAND[@]}" -c "import sys; sys.exit(sys.version_info[:2] != (3, 12))" >/dev/null 2>&1; then
      BASE="${CAND[*]}"; break
    fi
  done
  if [ -z "$BASE" ]; then
    echo "Python 3.12 não encontrado. Instale o Python 3.12 ou o micromamba (docs/COMO_RODAR.md)." >&2
    exit 1
  fi
  read -r -a BASE_CMD <<< "$BASE"
  [ -d .venv ] || "${BASE_CMD[@]}" -m venv .venv
  if [ -x .venv/bin/python ]; then PY_REL=.venv/bin/python; else PY_REL=.venv/Scripts/python.exe; fi
  PY=("$RAIZ/$PY_REL")
  # um .venv criado por outra ferramenta pode vir sem o pip
  "${PY[@]}" -m pip --version >/dev/null 2>&1 || "${PY[@]}" -m ensurepip --upgrade
  "${PY[@]}" -m pip install --upgrade "pip>=25.1"
  if [ "$VOZ" = 1 ]; then EXTRAS="geo,vision,voice"; else EXTRAS="geo,vision"; fi
  # O pyproject.toml só tem mínimos; os tetos abaixo são os do environment.yml: o OpenCV 5 muda a saída do
  # HoughLinesP usada na integridade da foto e o PyAV 19 quebra o faster-whisper 1.2.1.
  "${PY[@]}" -m pip install -e ".[$EXTRAS]" "opencv-python-headless<5" "av<19" "pillow<13"
  "${PY[@]}" -m pip install --group dev
  etapa "2/4 voz: $( [ "$VOZ" = 1 ] && echo 'incluída no extra voice' || echo 'pulada (--sem-voz)')"
fi
mkdir -p dados_locais
# no caso do venv, o caminho relativo à pasta laudo-vivo/ (sem espaços nem barras invertidas para o make)
printf '%s\n' "${PY_REL:-${PY[*]}}" > dados_locais/interpretador
"${PY[@]}" -c "import sys; print('Python', sys.version.split()[0], 'em', sys.executable)"

# --- 3. ativos da demo -----------------------------------------------------------------------------------
etapa "3/4 ativos da demo (vídeo, satélite e detector YOLOX, com sha256)"
"${PY[@]}" scripts/preparar_demo.py

# --- 4. teste rápido -------------------------------------------------------------------------------------
if [ "$TESTE" = 1 ]; then
  etapa "4/4 teste rápido: demo de 19 passos (ferramentas reais, LLM gravado) e laudo de exemplo"
  LOG=dados_locais/instalar_demo.log
  if "${PY[@]}" scripts/demo_cli.py --sem-cor --ferramentas reais --llm replay \
      --replay tests/unit/dados_agente/replay_demo_real_qwen35_4b.jsonl > "$LOG" 2>&1; then
    grep -E "Etapa final|tempo total" "$LOG" || true
  else
    tail -20 "$LOG"
    echo "a demo não chegou ao SELADO (log completo em $LOG; veja docs/COMO_RODAR.md)" >&2
    exit 1
  fi
  "${PY[@]}" docs/exemplos/conferir_exemplo.py | tail -3
else
  etapa "4/4 teste rápido: pulado (--sem-teste)"
fi

# --- pronto ----------------------------------------------------------------------------------------------
echo
echo "Pronto em $(( $(date +%s) - T0 )) s. Python registrado em dados_locais/interpretador: ${PY[*]}"
if [ -n "$GERENTE" ]; then
  echo "Para usar o ambiente neste terminal: $GERENTE activate $NOME   (e export PYTHONPATH=src)"
else
  echo "Para usar o ambiente neste terminal: . .venv/bin/activate (Windows: .venv\\Scripts\\activate)"
  echo "                                     e export PYTHONPATH=src"
fi
cat <<'FIM'
Próximos passos (na pasta laudo-vivo/):
  make replay      # demo da linha de comando: 19 passos, ferramentas reais, LLM gravado (~15 s)
  make demo-web    # interface web em replay: http://127.0.0.1:8000 (Ctrl+C encerra)
  make avaliar     # testes, laudo de exemplo, 19 passos pela API e avaliação só do dev
Sem make, os comandos equivalentes estão em docs/COMO_RODAR.md.
FIM
