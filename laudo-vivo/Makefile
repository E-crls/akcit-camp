# Atalhos finos para scripts/tarefas.sh (que faz o trabalho). O interpretador vem de PY
# (padrão scripts/py.sh; no CI, PY=python). Argumentos extras: make custo ARGS="--ajuda".
# Avaliação final (split de teste congelado): make r4 ARGS="--a-seco" (só imprime), make r4,
# make r4 ARGS="--retomar".
ALVOS := testes lint pii demo replay avaliacao r4 custo mcp numeros expurgo caso-demo ci ajuda
ARGS ?=

# Sem PY definido: scripts/py.sh se houver ../.ferramentas/micromamba.exe (ambiente "lv"); senão o Python
# que scripts/instalar.sh registrou em dados_locais/interpretador; senão o python do ambiente ativado.
ifeq ($(origin PY),undefined)
  ifneq ($(wildcard ../.ferramentas/micromamba.exe),)
    PY := scripts/py.sh
  else ifneq ($(wildcard dados_locais/interpretador),)
    PY := $(strip $(shell cat dados_locais/interpretador))
  else
    PY := python
  endif
endif
export PY
PY_RUN := $(if $(filter %.sh,$(firstword $(PY))),bash $(PY),$(PY))
export PYTHONUTF8 := 1

.DEFAULT_GOAL := ajuda
.PHONY: $(ALVOS) eval instalar demo-web avaliar

$(ALVOS):
	bash scripts/tarefas.sh $@ $(ARGS)

# REQ-31 do edital pede "make eval".
eval: avaliacao

# --- para quem avalia (docs/COMO_RODAR.md) ---------------------------------------------------------------
# instalar: ambiente (conda-forge ou venv), ativos da demo com sha256 e teste rápido (scripts/instalar.sh)
instalar:
	bash scripts/instalar.sh $(ARGS)

# demo-web: interface web em replay em http://127.0.0.1:8000 (o mesmo que scripts/rodar_demo.sh --replay,
# sem abrir o navegador): caso DEMO-0001, ferramentas reais, LLM e leitura do papel gravados, fala digitada
demo-web:
	@echo "Interface web em replay: http://127.0.0.1:8000/?apresentacao=1  (Ctrl+C encerra)"
	PYTHONPATH=src $(PY_RUN) -m laudo.api --caso DEMO-0001 --ferramentas reais --perfil campo --llm replay \
	    --asr desligado $(ARGS)

# avaliar: suíte de testes, conferência do laudo selado de exemplo, os 19 passos da interface pela API
# (replay, sem navegador) e avaliação determinística só do dev (golden set e red-team sem LLM; relatórios em
# dados_locais/avaliacao, sem tocar em eval/reports)
avaliar:
	bash scripts/tarefas.sh testes
	PYTHONPATH=src $(PY_RUN) docs/exemplos/conferir_exemplo.py
	PYTHONPATH=src $(PY_RUN) scripts/gravar_contingencia_web.py --conferir
	SAIDA_EVAL=dados_locais/avaliacao bash scripts/tarefas.sh avaliacao
