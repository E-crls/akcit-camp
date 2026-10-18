# Runbook da demo e da operação (regional de Goiânia, 24/10/2026)

Para quem vai operar a demo no dia, ou subir o Laudo Vivo numa máquina. Roteiro dos passos na tela:
[`apps/web/ROTEIRO_DEMO.md`](../apps/web/ROTEIRO_DEMO.md); fala do pitch:
[`docs/entregaveis/pitch-regional-3min.md`](entregaveis/pitch-regional-3min.md). Todos os comandos rodam no Git Bash, na
raiz do repositório.

## 1. O que precisa estar na máquina

| Item | Como conferir | Se faltar |
|---|---|---|
| Ambiente Python `lv` | `scripts/py.sh -c "import laudo"` | `docs/adr/002-ambiente.md` |
| Ollama com `qwen3.5:4b` (LLM e leitura do papel) | `ollama list` mostra `qwen3.5:4b` | `ollama pull qwen3.5:4b` (com rede) |
| Detector de bovinos `yolox_m` | `ls dados_locais/modelos/` (ou o teste lento da demo) | `scripts/py.sh scripts/baixar_modelos.py` (baixa e confere o sha256) |
| Vídeo semissintético da demo | `ls dados_locais/videos/sinteticos/s03_fila_colada.mp4` | `scripts/py.sh eval/golden/visao/gerar_semissintetico.py` |
| Cache do satélite da gleba da demo | rodar a demo uma vez com rede (D-1) | ~40 MB na 1ª consulta |
| Whisper (voz) na GPU | em "Detalhes técnicos", `Voz (transcrição): GPU (Whisper)` verde | `scripts/rodar_demo.sh --sem-voz` e digitar |
| Sal da instalação (LGPD) | `ls dados_locais/config/instalacao.json` | é criado sozinho na primeira execução; **não copie de outra máquina nem versione** |

GPU de 16 GB: um modelo do Ollama por vez (`ollama ps` deve mostrar só o `qwen3.5:4b`) mais o Whisper.

## 2. Subir

```bash
scripts/rodar_demo.sh                 # PALCO: ao vivo (Ollama + Whisper + caso DEMO-0001, ferramentas reais),
                                      # leitura do DANFE da demo pelo cache gravado do VLM e modo apresentação
scripts/rodar_demo.sh --vlm-ao-vivo   # só para ensaio: manda a foto do DANFE ao VLM de verdade (~15 s)
scripts/rodar_demo.sh --replay        # CONTINGÊNCIA: LLM e leitura do papel gravados, sem GPU nem rede
```

Desde a onda 3 (16/10/2026, L35), dois padrões do `rodar_demo.sh` mudaram (`scripts/rodar_demo.sh --help`):

- **Leitura do DANFE gravada (`--vlm-gravado`, padrão):** a foto do DANFE da demo é lida pelo cache gravado do VLM
  (a mesma foto e o mesmo pedido; o passo 6 leva ~2,5 s, só o LLM). Foto nova continua indo ao VLM. Para ensaiar
  a leitura de verdade, `--vlm-ao-vivo` (~15 s). No `--replay` é sempre pelo cache.
- **Modo apresentação (padrão):** o navegador abre em `?apresentacao=1` (cabeçalho recolhido, conversa grande,
  prova numa gaveta; o botão "Modo apresentação" no topo alterna). `--sem-apresentacao` abre a tela normal.

**No palco, o perfil é sempre `campo`** (o padrão do `rodar_demo.sh` e de `scripts/py.sh -m laudo.api`; na CLI,
passe `--perfil campo`, porque o padrão do `demo_cli.py` é `escritorio`). Só o perfil `campo` tem o orçamento de LLM
por turno (25 s) e o disjuntor: depois de um TIMEOUT ou de o Ollama sumir, o agente fica 60 s sem LLM, segue com o
plano mínimo e as falas por template e tenta de novo no turno seguinte. Com `escritorio` ou `lote`, um Ollama travado
segura o turno por minutos. Não troque o perfil no dia.

O script sobe o Ollama se ele estiver parado, aquece o modelo (fica carregado por 30 min) e o Whisper, sobe a API em
`http://127.0.0.1:8000/` e abre o navegador. Conferir em "Detalhes técnicos" (botão no topo; o ponto ao lado
fica verde), seção "Sistema": `Modelo de linguagem: ollama · qwen3.5:4b`, `Voz (transcrição): GPU
(Whisper)` e `Ferramentas: reais`, verdes. No replay: `Modelo de linguagem: replay`, `Fora da gravação: 0`
e, na faixa do topo, "Contingência: respostas do modelo reproduzidas de uma gravação".

Saúde pela linha de comando: `curl -s http://127.0.0.1:8000/api/saude`.

## 3. Aquecer (30 min antes)

1. `ollama ps` sem outro modelo carregado; se houver, `ollama stop <modelo>`.
2. Subir com `scripts/rodar_demo.sh` e passar o roteiro inteiro uma vez com → (aquece o modelo, a contagem em CPU, o
   cache do satélite). Tempo de referência ao vivo: ~40 s nos 19 passos; o passo 6 (DANFE) leva ~2,5 s com a
   leitura gravada, que é o padrão. Se for ensaiar a leitura ao vivo (`--vlm-ao-vivo`), some ~15 s nesse passo.
3. "Recomeçar" (na barra escura "Controle da demonstração"; dois cliques, o 1º só pede confirmação no próprio
   botão) e deixar a tela na Carteira.
4. Testar o microfone: segurar "Segure para falar" e dizer "teste".

## 4. Contingência com replay

A contingência é a demo gravada com o modelo real: o replay devolve as mesmas respostas, na mesma ordem, sem GPU.

- **Gravar (na r4, depois do congelamento do código, até 22/10):**
  `scripts/py.sh scripts/gravar_contingencia_web.py` (roda os 19 passos pela API com o Ollama, sem clicar; grava
  `eval/golden/demo/DEMO-0001/replay_qwen35_4b.jsonl`).
- **Conferir:** `scripts/py.sh scripts/gravar_contingencia_web.py --conferir` tem de dizer "etapa final SELADO, 0
  requisição(ões) fora da gravação". Se der N > 0, o código mudou depois da gravação: grave de novo.
- **Relógio da demo (resolvido em 16/10/2026):** as fotos da cerca do `DEMO-0001` têm EXIF de 08/10/2026. Até
  01:24 de 16/10 a API carimbava o recebimento com a hora da máquina; desde 11/10 as fotos passavam de 72 h, saíam
  divergentes, o rascunho não saía e o `--conferir` quebrava no passo 18. A área de Interface corrigiu em
  `src/laudo/api/casos.py`: o recebimento vem do `recebida_em` do `caso.yaml`, como na CLI. Conferido às 01:47 de
  16/10 (`eval/reports/2026-10-16_equivalencia_congelamento.md`): a contingência sela com 0 fora da gravação.
  A demo ao vivo passa pelo mesmo `casos.py`, mas não foi rodada nessa conferência (precisa do Ollama): a passada
  ao vivo da seção 3 no D-1 é a prova. Se o `--conferir` falhar no D-1, use o Plano D ou o vídeo.
- **Atenção ao snapshot de rollback** (`../snapshots/laudo-vivo_pre-r4_20261016-0057.tar.gz`, `eval/README.md`):
  ele foi tirado às 00:57 de 16/10, **antes** da correção de `src/laudo/api/casos.py` das 01:24 (o `sha256(src/)`
  dele é o `48f0d4f9…` da conferência das 01:02, que deu DIFERENTE no passo 18). Restaurar o `src/` do snapshot
  traz o bug do relógio de volta: a demo web e a contingência voltam a travar na assinatura. Se precisar dele,
  restaure mantendo o `src/laudo/api/casos.py` atual e rode `gravar_contingencia_web.py --conferir` antes do palco.
- **Usar:** Ctrl+C no `rodar_demo.sh` ao vivo e `scripts/rodar_demo.sh --replay` (~15 s até a tela voltar); "Abrir
  fiscalização" no cartão da demo e seguir com →. A leitura do DANFE vem do cache gravado da mesma foto.
- **Plano C:** vídeo da demo (`docs/entregaveis/video/laudo-vivo-demo.mp4`), aberto numa aba. **Plano D:** `scripts/py.sh scripts/demo_cli.py
  --ferramentas reais --llm replay` no terminal (12 s, sem GPU).

## 5. Se cair…

| O que caiu | Como aparece | O que fazer |
|---|---|---|
| **Ollama (LLM e VLM)** | ponto de "Detalhes técnicos" vermelho (modelo indisponível); falas por template; a foto do DANFE dá erro de leitura | o agente segue com o plano determinístico e as falas por template: a demo continua e sela (o passo do residual é pulado e o XML fecha a nota). Para voltar: `ollama serve` num terminal e F5. Se for no meio do pitch, siga sem trocar; se travar, contingência (seção 4) |
| Ollama sem memória de GPU | erro "out of memory" ou resposta muito lenta | `ollama ps`; `ollama stop` em qualquer modelo que não seja o `qwen3.5:4b`; fechar o que usa a GPU (navegador com vídeo, jogos) |
| **ASR (voz)** | "Voz (transcrição): desligada" em "Detalhes técnicos" ou "não entendi a fala" repetido | digitar a fala no campo de texto (Enter envia) ou usar → (o roteiro manda a fala); para voltar, reiniciar com `--com-voz`; sem GPU, `scripts/py.sh -m laudo.api ... --asr cpu` (mais lento) |
| Leitura do DANFE lenta | o passo 6 demora mais de 20 s | seguir a fala; conferir se a demo não subiu com `--vlm-ao-vivo` (o padrão é a leitura gravada) |
| **Servidor (API)** | a página não responde | rodar `scripts/rodar_demo.sh` de novo e F5: a fiscalização continua de onde parou (estado, cadeia de hash, confirmação pendente e trava do PIN ficam em disco). No **replay**, a gravação recomeça do início: "Recomeçar" (dois cliques) e → até o ponto |
| Rede | mapa sem fundo | nada: tudo roda local; satélite do cache |
| Projetor | imagem cortada | F11 e zoom do navegador em 100% |
| PIN errado 5 vezes | "assinatura travada" (a trava sobrevive a reinício) | "Recomeçar" (dois cliques) e avançar até a assinatura |

## 6. Checklist do dia 24/10

**D-1 (23/10), depois do congelamento do código e da r4 (seção 8):**

- [ ] `make ci` verde (lint, testes, PII, frases proibidas, números). Sem `make` no Git Bash:
  `bash scripts/tarefas.sh ci`.
- [ ] A r4 terminou no `sha256(src/)` do congelamento do código e os números de palco são os dela
  (`docs/entregaveis/numeros.md` diz `_r4`); se falhou, os da r3 continuam valendo.
- [ ] `scripts/py.sh scripts/checar_frases_proibidas.py` sai com código 0 (nenhuma frase da lista de
  `../negocio/afirmacoes_proibidas.md` no pitch, no Q&A, no BMC, na inscrição nem no plano).
- [ ] Split de teste ainda congelado: `eval/golden/casos/SPLIT.yaml` com `congelado: true` e
  `sha256_conteudo.test` começando por `f47e4446` (o relatório da r4 traz os mesmos).
- [ ] `scripts/py.sh scripts/gerar_numeros.py --verificar` sai com código 0 (pitch, Q&A e slide com os números da r4).
- [ ] `scripts/py.sh scripts/mascarar_demo.py --verificar` diz "ok".
- [ ] Contingência gravada e conferida (seção 4); `LAUDO_LENTO=1 scripts/py.sh -m pytest tests/unit/test_agente_replay_demo_real.py tests/unit/test_api_replay.py -q` verde.
- [ ] Cache do satélite feito com rede; ensaio completo **em modo avião**, uma passada com a contingência.
- [ ] Vídeo de backup gravado e aberto numa aba; PDF dos slides no GitHub (equipe).

**Dia (24/10):**

- [ ] Notebook na tomada, modo de energia "desempenho", atualizações e notificações pausadas, outros apps fechados.
- [ ] `ollama ps` vazio → `scripts/rodar_demo.sh` → "Detalhes técnicos" verde → aquecer (seção 3) →
  "Recomeçar".
- [ ] Microfone testado no salão; projetor em F11; cronômetro visível para o operador.
- [ ] Terminal com `scripts/rodar_demo.sh --replay` digitado e pronto (só apertar Enter).
- [ ] Antes das 15h00: entregáveis publicados no GitHub (equipe); 15h30: congelamento da entrega. O push e a
  tag só com o OK explícito da equipe: `scripts/publicar.sh` imprime a checagem e os comandos sem rodar nada;
  `scripts/publicar.sh --executar --tag regional-2026-10-24` pede a palavra PUBLICAR, digitada, a cada
  passo (modo tag: o repositório já tem commit e remoto; checagem, árvore limpa, tag e push).
- [ ] Depois: Ctrl+C e `ollama stop qwen3.5:4b` (ou subir com `--descarregar`).

## 7. Diagnóstico rápido

```bash
curl -s http://127.0.0.1:11434/api/ps                 # o que o Ollama tem carregado
curl -s http://127.0.0.1:8000/api/saude               # LLM, voz, ferramentas e caso padrão
scripts/py.sh scripts/custo_fiscalizacao.py dados_locais/api/traces    # tokens e tempos por fiscalização
scripts/py.sh -m pytest tests/unit/test_api_retomada.py -q             # retomada depois de queda
tail -50 dados_locais/api/ollama.log                  # se o rodar_demo.sh subiu o Ollama
```

Os dados de cada fiscalização ficam em `dados_locais/api/` (estado, conversa, trace, laudos, evidências e o cofre
`chaves/`). Para apagar só a demonstração, use "Recomeçar"; para expurgo LGPD, `scripts/expurgo_lgpd.py`
(ver [`docs/privacidade.md`](privacidade.md)). Para conferir um laudo selado contra a cadeia e o rascunho assinado:
`scripts/py.sh -m laudo.audit.selo --dados dados_locais/api <id da fiscalização>` (0 = confere, 1 = não confere).

## 8. Rodada r4 (uma vez, no congelamento do código)

Os três congelamentos têm nome fixo (`docs/entregaveis/README.md` e `eval/README.md`): o **do teste** já foi feito
(16/10/2026, 00:58, `sha256_conteudo.test` `f47e4446…735dcd`); o **do código (r4)** é o `sha256(src/)` em que a
r4 roda, quando o lote de `src/` da onda 3 fechar (prazo: até 22/10); o **da entrega** é 24/10, 15h30. A r4 roda **uma vez**, nesse código, em série, um modelo por vez, nunca junto com o
streaming do Sicor nem com outro modelo no Ollama (`ollama ps` vazio antes).

```bash
bash scripts/tarefas.sh r4 --a-seco      # ou: make r4 ARGS="--a-seco"; só imprime a sequência e as pré-condições
bash scripts/tarefas.sh r4               # roda tudo (cerca de 3 a 4 h de máquina; GPU só com o qwen3.5:4b)
bash scripts/tarefas.sh r4 --retomar     # continua de onde parou, no mesmo sha256(src/)
```

A sequência (`eval/rodada_r4.py`, da área de Avaliação) leva `--final --motivo "rodada r4 congelada"` em toda
etapa que usa o split de teste e `--sufixo _r4` nos relatórios; cada uso do teste fica no registro append-only
`eval/golden/casos/registro_teste.jsonl`. O núcleo, se for preciso rodar uma etapa à mão:

```bash
scripts/py.sh eval/run_eval.py --modo deterministico --final --motivo "rodada r4 congelada" --sufixo _r4
scripts/py.sh eval/run_eval.py --modo agente --final --motivo "rodada r4 congelada" --sufixo _r4
scripts/py.sh eval/run_eval.py --modo agente --split test --final --motivo "L60 repeticao" --sufixo _r4_rep
```

Sem `--final`, com o split congelado, os scripts rodam só o dev (ou se recusam a tocar o teste). Depois da r4:
contingência regravada e conferida (seção 4), `gerar_slide --sufixo _r4`, `gerar_numeros --aplicar` e
`--verificar` com 0 problemas (o próprio `rodada_r4.py` faz os três no fim). Se a r4 falhar, os números da r3
continuam valendo (mesmo conjunto de teste).
