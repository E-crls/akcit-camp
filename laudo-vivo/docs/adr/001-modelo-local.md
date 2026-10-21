# ADR 001: modelo local do condutor (bake-off qwen3.5:4b × qwen3:14b)

- **Status:** aceito.
- **Escopo:** LLM que conduz a fiscalização (escolha de ferramenta, pedido de evidência, extração de alegações,
  fala ao fiscal). O LLM não calcula número nem define status; quem faz isso são as ferramentas e o verificador.

## Contexto

O condutor roda local (LGPD, offline, custo marginal zero). A GPU (RTX 5070 Ti, 16 GB, ~3 GB já ocupados por
outros programas) é dividida com o ASR (faster-whisper). Só um modelo carregado por vez. Candidatos:
`qwen3.5:4b` (3,4 GB, tools + visão) e `qwen3:14b` (9,3 GB, tools). `gemma3:4b` não tem tool calling no Ollama
e ficou fora.

## Método

Script `scripts/agente_bakeoff.py`, com o **mesmo prompt, os mesmos esquemas de ferramenta e a mesma montagem de
contexto do condutor de produção** (`src/laudo/agent/prompts/`, `schema_para_llm`), ferramentas falsas
(`src/laudo/agent/ferramentas_falsas.py`) e Ollama 0.32.4 (Q4_K_M, `temperature=0`, `seed=42`, `num_ctx=8192`,
`think=false`, data de referência injetada no prompt). Um modelo por vez; descarregado com `ollama stop` ao final.

- **26 turnos de tool calling em pt-BR** cobrindo BRIEFING, COLETA, CHECAGEM, REVISAO e RASCUNHO: uploads
  (vídeo, foto com GPS, NF-e, GTA com texto de injeção no OCR), pedidos de laudo, justificativas de divergência,
  envio para assinatura, perguntas fora do escopo. Cada turno roda em dois modos: **tools nativas** e
  **saída estruturada** (contingência `{acao, argumentos, fala_para_o_fiscal}` com JSON Schema no `format`).
- **Validade:** ferramenta entre as oferecidas no estado e argumentos que validam no Pydantic da ferramenta
  (depois de o condutor preencher caminho, GPS, gleba etc. a partir do `evidencia_id`). **Reparo:** tool call
  escrita no texto é recuperada localmente; se ainda inválida, uma nova rodada mostra o erro ao modelo.
- **Acerto:** a ação escolhida está entre as esperadas para o cenário.
- **8 falas para extração de alegações** (JSON Schema): validade e acerto exato de (grandeza, valor).
- Latência por chamada (p50/p95, sem o aquecimento), tokens, VRAM (pico do `nvidia-smi` amostrado a cada 0,5 s)
  e `ollama ps`. Intervalos de 95% de Wilson entre colchetes.
- Amostra: 26 turnos e 8 falas, uma semente, cenários escritos pela equipe.

## Resultados

| Métrica | qwen3.5:4b | qwen3:14b |
|---|---|---|
| Tool call válida na 1ª tentativa (tools) | 26/26 [0,87–1,00] | 25/26 [0,81–0,99] |
| Válida após reparo (tools) | 26/26 [0,87–1,00] | 25/26 [0,81–0,99] (1 resposta vazia, repetida no reparo) |
| Ação correta (tools) | 24/26 [0,76–0,98] | 23/26 [0,71–0,96] |
| Válida na 1ª / após reparo (estruturado) | 26/26 / 26/26 | 26/26 / 26/26 |
| Ação correta (estruturado) | 24/26 [0,76–0,98] | 23/26 [0,71–0,96] |
| Alegações: JSON válido | 8/8 | 8/8 |
| Alegações: acerto exato (saída crua do LLM) | 6/8 [0,41–0,93] | 7/8 [0,53–0,98] |
| Latência por chamada p50 / p95 | **0,88 s / 1,44 s** (n=60) | 1,34 s / 2,40 s (n=61) |
| Tokens médios entrada / saída | 2.255 / 46 | 2.079 / 39 |
| Aquecimento (carga do modelo) | 3,7 s | 5,6 s |
| VRAM: pico total (Δ sobre a base de 3,0 GB) | 7,6 GB (**+4,5 GB**) | 13,4 GB (**+10,4 GB**) |
| `ollama ps` | 3,4 GB, 100% GPU, ctx 8192 | 10 GB, 100% GPU, ctx 8192 |

**Ponta a ponta** (demo `scripts/demo_cli.py`, 14 turnos, 21 chamadas ao LLM, ferramentas falsas):

| | qwen3.5:4b | qwen3:14b |
|---|---|---|
| Tempo total | 21,0 s | 29,7 s |
| Turno com LLM, p50 / p95 (sem o 1º, que inclui a carga) | 1,7 s / 2,4 s | 2,5 s / 3,7 s |
| Plano mínimo determinístico acionado | 0 vezes | 1 vez (não chamou a contagem) |
| Fala do LLM descartada pelo grounding (POL-05) | 0 | 1 (número calculado que não existia no estado) |

Na extração de alegações, o número é relido de forma determinística do trecho citado (ponteiro) e um extrator
por regex complementa o LLM (teste `test_alegacoes_com_ponteiro...`).

## Decisão

| Perfil | Modelo | Por quê |
|---|---|---|
| `campo` (notebook) | `qwen3.5:4b` | cabe em GPU de 6–8 GB; mesma validade |
| `escritorio` (demo, padrão) | `qwen3.5:4b` | mesma validade e acerto do 14b dentro do IC, 1,5× mais rápido e deixa ~8 GB para o whisper turbo fp16 na GPU; o 14b + ASR não cabe nos ~12,4 GB livres |
| `lote` (golden set) | `qwen3:14b` | sem ASR na GPU; melhor em alegações; serve de 2º leitor/redator |

Modo padrão: **tool calling nativo**; saída estruturada fica como contingência (mesma validade aqui). Configuração
em `src/laudo/llm/provider.py` (`PERFIS`), sobreponível por `LAUDO_MODELO` ou `LAUDO_MODELO_<PERFIL>`.

O condutor esconde do LLM os parâmetros técnicos opcionais das ferramentas reais (por exemplo `fps_amostragem`,
`limiar_deteccao`) e preenche `inicio`/`fim` do NDVI pelo estado: o esquema que o modelo vê fica menor.

**Janela de contexto: `NUM_CTX = 16384`** (`src/laudo/llm/provider.py`, uma constante só, usada pelo condutor,
pelos leitores de foto, `vision/vlm.py` e `tools/leitura_documentos.py`, e pelo aquecimento da API,
`Servico.aquecer_llm`). Com as ferramentas reais, o 1º pedido do condutor passa de 9 mil tokens (prompt de
sistema mais o esquema das ferramentas), e com `num_ctx=8192` o Ollama corta o prompt para
`(num_ctx − 4) // 2 + 4` tokens sem devolver erro (só `truncating input prompt` no log). Se `prompt_eval_count`
vier igual a essa assinatura de corte, o provedor escreve um aviso no stderr e marca `llm.prompt_cortado` no
trace.

## Consequências

- A tool call válida na 1ª tentativa no golden set é medida pelo avaliador (`eval/run_eval.py --modo agente`);
  o resultado está em [`eval/SLIDE.md`](../../eval/SLIDE.md).
- Gravações requisição→resposta da demo viram fixtures de replay sem GPU
  (`tests/unit/dados_agente/replay_demo_qwen35_4b.jsonl`, ferramentas falsas, e
  `replay_demo_real_qwen35_4b.jsonl`, ferramentas reais).

## Como reproduzir

```bash
scripts/py.sh scripts/agente_bakeoff.py --modelos qwen3.5:4b qwen3:14b      # ~4 min; descarrega ao final
scripts/py.sh scripts/demo_cli.py --llm ollama --modelo qwen3.5:4b --dados dados_locais/demo_e2e --descarregar
```

Resultados por modelo: `dados_locais/bakeoff/resultado_<modelo>.json` (linhas por cenário, latências, VRAM).
