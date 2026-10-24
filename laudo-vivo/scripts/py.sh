#!/usr/bin/env bash
# Executa Python no ambiente conda-forge "lv" (rede local bloqueia files.pythonhosted.org; ver docs/adr/002-ambiente.md).
# Uso: scripts/py.sh caminho/script.py [args]   |   scripts/py.sh -m pytest
AKCIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export MAMBA_ROOT_PREFIX="$AKCIT_DIR/.ferramentas/mamba"
REPO="$AKCIT_DIR/laudo-vivo"
export PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONUTF8=1
if [ -x "$AKCIT_DIR/.ferramentas/micromamba.exe" ]; then
  exec "$AKCIT_DIR/.ferramentas/micromamba.exe" run -n lv python "$@"
fi
# Sem o micromamba em ../.ferramentas: LAUDO_PY, o interpretador gravado por scripts/instalar.sh, ou o python do PATH.
PY="${LAUDO_PY:-}"
[ -z "$PY" ] && [ -f "$REPO/dados_locais/interpretador" ] && PY="$(cat "$REPO/dados_locais/interpretador")"
[ -z "$PY" ] && PY="$(command -v python3 || command -v python)"
# O instalador pode gravar um comando de várias palavras (ex.: "micromamba run -n laudo-vivo python").
if [ ! -e "$PY" ] && [[ "$PY" == *" "* ]]; then
  read -r -a CMD <<< "$PY"
  exec "${CMD[@]}" "$@"
fi
exec "$PY" "$@"
