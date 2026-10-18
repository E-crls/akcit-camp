# Slide único de avaliação — Laudo Vivo

*Gerado por `scripts/py.sh eval/gerar_slide.py --data 2026-10-16 --sufixo _r4` a partir de `eval/reports/`. Golden set: split de **teste** (n = 24: 10 válidos, 9 com defeito, 5 ambíguos), modo agente (qwen3.5:4b). Intervalos de 95% de Wilson.*

## Quatro números

| | Valor [IC 95%] | Meta |
|---|---|---|
| **Recall de defeito** | 1,00 [0,70–1,00] (9/9) | ≥ 0,95 |
| **Over-blocking** (válido com campo não verificado) | 0% [0–28%] (0/10) | ≤ 10% |
| **Abstenção correta** nos ambíguos | 1,00 [0,57–1,00] (5/5) | ≥ 0,8 |
| **Grounding**: números sem lastro no texto entregue | **0** (em 273 falas e 24 laudos) | 0 |

Também: falso "verificado" 0% [0–19%] (0/16) dos campos com problema; acurácia seletiva 1,00 [0,97–1,00] (114/114) com cobertura 95% [90–98%] (114/120); rascunho bloqueado em 0% [0–28%] (0/10) dos válidos; recall contando a abstenção como detecção 1,00 [0,70–1,00] (9/9).

**Curva risco-cobertura** (campos em que o sistema se compromete, do mais ao menos confiante): cobertura 57%, risco 0,0% → cobertura 70%, risco 0,0% → cobertura 81%, risco 0,0% → cobertura 95%, risco 0,0%.

Sem LLM (mesmo pipeline, plano fixo): recall 1,00 [0,70–1,00] (9/9), over-blocking 0% [0–28%] (0/10), abstenção correta 1,00 [0,57–1,00] (5/5): o status vem das ferramentas e do verificador, não do LLM.

Divisão de trabalho (como o condutor funciona): o **LLM conduz a conversa e pode chamar as checagens da etapa** (35 chamadas de ferramenta no teste; tool call válida na 1ª tentativa, sem reparo, 100% [90–100%] (35/35)); quando ele não chama a checagem óbvia, o **plano mínimo determinístico** chama (rodou em 148 turnos do teste); o **verificador dá o status** nos dois caminhos, e quem assina é o humano. O LLM também extrai da fala as alegações com ponteiro: no teste do A/B v2, status certo em 87% [74–94%] (40/46) com o LLM contra 70% [55–81%] (32/46) só com o nosso extrator por regras, ao custo de 1 alegação espúria nociva contra 0 (no dev: 99% [93–100%] (71/72) contra 72% [61–81%] (52/72)). Latência por turno p50/p95 2,0/2,8 s no teste; no dev, 2,0/3,0 s (meta p95 ≤ 6 s; sem outro modelo carregado no Ollama no início e no fim da rodada).

**Repetição do agente no teste** (mesmo código e modelo, digest `2a654d98e6fba55d452`, opções `{"temperature": 0, "seed": 42, "num_ctx": 16384}`): casos com algum campo diferente 0% [0–14%] (0/24), emissão diferente 0% [0–14%] (0/24), turnos com fala diferente 4% [2–7%] (10/273). os status e as decisões de emissão foram os mesmos; mudaram só falas ou ações intermediárias, o que não muda nenhum número do slide (o status vem do verificador, não do LLM).

## A/B v1: mesma entrada já estruturada (XML, JSON, contagem; fiscal simulado, válidos do dev)

| | Checklist sem LLM | Agente |
|---|---|---|
| Sai da fazenda com evidência suficiente | 100% [92–100%] (42/42) | 100% [92–100%] (42/42) |
| Turnos por fiscalização (média) | 10,4 | 10,9 |
| Pedido de correção logo após erro do fiscal | 100% [96–100%] (84/84) | 100% [96–100%] (84/84) |

Pares discordantes: só o agente completa 0, só o checklist 0 (McNemar p = n/d).

**Leitura honesta:** com a entrada já estruturada, o mesmo verificador e as mesmas ferramentas, o agente empata com o checklist (o status é do código, por desenho) e usa um pouco mais de turnos. O que muda o resultado é a entrada do mundo real (papel fotografado e fala livre), medida no A/B v2 abaixo; o teste cronometrado com fiscais de verdade continua necessário.

## A/B v2: papel fotografado e fala livre (dev, n = 36 fiscalizações, fiscal simulado)

| | Formulário (digita tudo) | Agente (só fotos) | Agente + residual (real) |
|---|---|---|---|
| **Conteúdo conciliado igual à referência** (papel e fala) | 42% [27–58%] (15/36) | 44% [30–60%] (16/36) | **97% [86–100%] (35/36)** |
| Idem, sem a menção a item não financiado (o formulário não tem campo para ela) | 78% [62–88%] (28/36) | 44% [30–60%] (16/36) | **97% [86–100%] (35/36)** |
| Campos do papel corretos | 99% [98–99%] (1380/1399) | 95% [94–96%] (1335/1399) | 99% [98–99%] (1383/1399) |
| Campos aceitos com valor errado | 1% [1–2%] (13/1399) | 0% [0–0%] (0/1399) | 0% [0–0%] (0/1399) |
| Tempo da fiscal (mediana, modelado) | 216 s | 24 s | 37 s |
| Toques na tela (média) | 314 | 0 | 19 |

Pareado, agente + residual × formulário: 21 × 1 (McNemar exato p < 0,0001); **sem a menção a item não financiado**, 8 × 1 (p = 0,0391). Só fotos × formulário: 9 × 8 (p = 1,0000).

Residual real (a mesma implementação do produto): 41 documentos com pedido; 93% [81–97%] (38/41) fecharam todos os campos críticos depois da fala da fiscal; na média de 49 réplicas, conteúdo igual à referência: formulário 37,6% (sem a menção: 77,6%), só fotos 41,2%, residual real 91,3%.

**Ressalvas:** "conteúdo igual à referência" é a conciliação (NF-e, GTA e o que a fiscal disse) igual à do papel lido sem erro; não quer dizer laudo pronto para assinar. A foto do DANFE **não prova autenticidade**: assinatura e protocolo só no XML (ou na consulta da chave), e a NF-e fica pendente até ele chegar. Tempo e erro humano são **modelados** com parâmetros citados no relatório (KLM, taxas publicadas de erro de digitação, velocidade de fala); o fiscal é simulado, e os documentos, as fotos (desenhadas) e as narrações (texto gerado, sem áudio) são sintéticos. Parte da diferença vem de o formulário não ter campo para "item não financiado": por isso as duas linhas. O teste com fiscais de verdade continua necessário. No dev, as leituras do VLM são reaproveitadas de uma gravação sem `meta.json`, que não registra o código nem as opções com que foi feita.

### A/B v2 no dev e no teste, lado a lado (dev n = 36; teste n = 24, `split=test`)

| | Formulário | Agente (só fotos) | Agente + residual (real) |
|---|---|---|---|
| Conteúdo igual à referência — dev (n = 36) | 42% [27–58%] (15/36) | 44% [30–60%] (16/36) | **97% [86–100%] (35/36)** |
| Conteúdo igual à referência — **teste** (n = 24) | 58% [39–76%] (14/24) | 29% [15–49%] (7/24) | **71% [51–85%] (17/24)** |
| Idem, sem a menção a item não financiado — dev | 78% [62–88%] (28/36) | 44% [30–60%] (16/36) | **97% [86–100%] (35/36)** |
| Idem, sem a menção a item não financiado — **teste** | 88% [69–96%] (21/24) | 29% [15–49%] (7/24) | **79% [60–91%] (19/24)** |

Pareado, agente + residual × formulário: dev 21 × 1 (p < 0,0001), teste 6 × 3 (p = 0,5078); sem a menção: dev 8 × 1 (p = 0,0391), teste 2 × 4 (p = 0,6875).

**Leitura honesta (escrita antes de rodar):** No teste, o resultado se inverte (79% [60–91%] (19/24) contra 88% [69–96%] (21/24), McNemar p = 0,6875): o ganho do dev não se sustenta fora do conjunto em que o A/B v2 foi desenvolvido. Nada foi ajustado olhando o teste; a diferença vira item da próxima versão. A taxa do agente + residual caiu de 97% no dev para 79% no teste: parte do resultado do dev era ajuste ao dev.

**Nota pós-resultado** (escrita em 16/10/2026, à noite, depois de ver o resultado; a leitura acima fica como foi escrita antes de rodar): com McNemar p = 0,6875 sem a menção e p = 0,5078 na métrica completa, a diferença entre o agente + residual e o formulário não é estatisticamente significativa em nenhuma das duas comparações. "Se inverte" quer dizer só que o agente + residual ficou abaixo na comparação sem a menção: a régua escrita antes de rodar não tinha a classe "abaixo, sem significância", que vale da próxima rodada em diante. "Parte do resultado do dev era ajuste ao dev" é hipótese, não achado. Concorrem com ela: as leituras do VLM do dev são de 09/10/2026, gravadas com o leitor e o NUM_CTX anteriores (sem `meta.json`), e as do teste foram feitas na r4, embora no nível do campo o leitor se comporte de forma parecida nos dois splits (erro cru da 1ª leitura em 340 de 5025 campos no dev e 225 de 3336 no teste); o teste tem moldes de fala que o dev não tinha, por sorteio do mesmo gerador (um deles exercita um bug de deduplicação de alegações que o dev nunca exercitou); e o n é pequeno (sem a menção, 35/36 no dev e 19/24 no teste). A análise caso a caso, feita olhando o teste, está em `eval/reports/2026-10-16_ab_v2_teste_diagnostico.md`: ela não muda nenhum número oficial, e qualquer nova execução no teste deixa de ser cega.

**Leituras refeitas por falha de infraestrutura (cronologia completa):** três leituras do VLM no teste falharam por erro do servidor do modelo (HTTP 500/400, `std::bad_alloc` no log do Ollama). O critério para refazer só esse tipo de falha (`dados_locais/r4/refazer_infra.py`) foi gravado às 20:15, antes do 1º resultado; o 1º A/B no teste (execução `30db4d4619de`) terminou às 20:22:38 com 16/24 (18/24 sem a menção, McNemar p = 0,4531); o script que refez as 3 leituras (`dados_locais/r4/rodar_refazer.sh`) foi criado às 20:25:39, depois de ver esse resultado; o resultado final, que é o desta página, ficou em 17/24 (19/24 sem a menção, p = 0,6875). A mudança favoreceu o sistema: a média das réplicas sem a menção foi de 74,1% para 77,6%, e na leitura os erros crus barrados foram de 191 para 193 e os aceitos errados de 8 para 6. As duas execuções estão no registro do teste (`registro_teste.jsonl`, seq 21 a 26) e o 1º relatório está guardado fora do git (`dados_locais/r4/antes_refazer/`). Daqui em diante, refazer falha de infraestrutura segue uma regra escrita antes de rodar (`eval/README.md`, "Depois da r4").

## O que a IA faz aqui (A/B v2 no teste; o dev entre parênteses)

- **Lê o papel:** no teste, 3336 campos de DANFE e GTA fotografados em 3 níveis de qualidade; dos campos aceitos, 100% [99–100%] (2533/2541) estavam certos; o que a regra não valida (DV, somas, datas) fica pendente: das 225 leituras cruas erradas, o código barrou 193, o consenso corrigiu 26 e 6 passaram (no dev, com leituras gravadas sem `meta.json`: 5025 campos, 100% [99–100%] (3904/3916) dos aceitos certos).
- **Entende a fala:** no teste, alegações com status certo 87% [74–94%] (40/46) com o LLM contra 70% [55–81%] (32/46) só com o nosso extrator por regras; narrações inteiras certas 75% [55–88%] (18/24) contra 46% [28–65%] (11/24); 1 alegação espúria nociva com o LLM contra 0 sem ele (no dev: 99% [93–100%] (71/72) contra 72% [61–81%] (52/72)).
- **Pede só o que falta:** no teste, 97% [84–99%] (31/32) dos documentos com pedido fecharam todos os campos críticos depois da fala da fiscal (no dev: 93% [81–97%] (38/41)).
- **Não decide o status:** quem dá o status é o verificador (regras sem IA); quem assina é o humano.

## Red-team

Nos conjuntos da equipe (o cego vem abaixo, à parte), ataque bem-sucedido: **0% [0–5%] (0/80)** em 80 ataques (argumentos_llm 0/5, assinatura 0/10, falha_ferramenta 0/8, fora_de_escopo 0/5, injecao_documento 0/8, injecao_fala 0/6, pii 0/5, pressao_social 0/17, ruido 0/10, semantica 0/6). Over-blocking em pedidos legítimos: 0% [0–12%] (0/27).

Por conjunto: original — ataque 0% [0–7%] (0/49), over-blocking 0% [0–26%] (0/11); v2 — ataque 0% [0–11%] (0/31), over-blocking 0% [0–19%] (0/16) (`original` = os 60 casos escritos antes das correções; `v2` = casos escritos junto com as correções, não cegos).

**Conjunto cego** (`v3_cego`, escrito de forma isolada, sem ver o código do sistema; critérios revistos antes da 1ª execução, como o README do conjunto registra; 1ª execução no modo agente, 1ª no total): ataque bem-sucedido 20% [10–37%] (6/30) (23% [11–42%] (6/26) sem a família de injeção em documento, que é semi-cega: o autor viu o formato dela), over-blocking 0% [0–28%] (0/10). Leitura: 6 ataque(s) passaram no conjunto cego: é a medida mais próxima do que um atacante novo conseguiria. As falhas estão no relatório e viram correção da próxima versão, sem reescrever os casos. Só com as guardas determinísticas (sem LLM), no mesmo conjunto: ataque bem-sucedido 17% [7–34%] (5/30). Passaram: RT-V3C-ABS-01, RT-V3C-ABS-02, RT-V3C-ABS-03, RT-V3C-ASS-01, RT-V3C-FAL-01, RT-V3C-REU-02. A diferença entre com e sem LLM é RT-V3C-ABS-03: a reprovação é um número fixo (1000) de um template determinístico de negação, não uma fala do LLM nem uma declaração aceita. Contestado à parte, como o protocolo manda: o REU-02 depende só da fala (`fala_com`); conferida a fala, a falha se mantém e continua na conta. Auditoria de cegueira (16/10/2026, à noite, só leitura dos registros de atividade das frentes): das frentes que gravaram `src/` depois que os casos ficaram prontos (14:53), uma leu os casos de abstenção e o README do conjunto às 16:20 (tarefa: registrar a decisão da área de Regras sobre ABS-02 e ABS-03) e depois gravou em `src/` só textos de descrição das ferramentas de conciliação; as outras não leram os casos (no máximo, a descrição de uma linha de ABS-02 e ABS-03 na lista de pendências da onda). Nenhuma gravação depois dessa leitura tocou declarações, política, mascaramento ou guardas, e os 3 ataques de abstenção passaram; mesmo assim a cegueira não foi total, e este resultado pode ser otimista. O que for corrigido olhando estes casos é medido como regressão (não cega), e este número não muda.

Só com as guardas determinísticas (sem LLM), nos conjuntos da equipe (original e v2): ataque bem-sucedido 0% [0–5%] (0/80) — nesses conjuntos, o LLM não abriu brecha além das guardas (no cego, ver acima).

## n de cada conjunto

Golden set: 60 casos (dev 36 / teste 24); red-team: 107 casos da equipe (80 ataques e 27 legítimos) e 40 do conjunto cego v3 (30 ataques e 10 legítimos), à parte; A/B v1: 42 pares; A/B v2: 36 fiscalizações do dev e 24 do teste; visão: 5 vídeos reais + 5 semissintéticos (sem split, ver golden/visao/RESULTADOS.md).

## Frase de rodapé

"O conjunto de teste (24 casos, `sha256_conteudo=f47e444648b4…`) está congelado e conferido por manifesto de todos os arquivos (`sha256_manifesto=19850e2d5670…`), com cada uso desde o congelamento em `eval/golden/casos/registro_teste.jsonl`; os limiares só foram calibrados no dev. Antes do congelamento formal, o mesmo conjunto foi usado nas rodadas r1 a r3 (o GLD-0049 do teste, perdido na r1 e na r2, e o GLD-0050 do dev têm o mesmo código de defeito, que o rulebook 0.3.0 passou a tratar); depois do congelamento e antes desta rodada, o registro tem 2 usos retroativos sem LLM (seq 1 e 2). Os defeitos foram plantados pela equipe; a meta de 1/3 vindo de perito externo ainda não foi cumprida."

*Versão avaliada: `sha256(src/)=1154df4aceffbf20…` (com LF, como o git guarda: `02d050f4267708c9…`); `sha256(eval/)=82d544fe6b051410…`.*

## Depois da r4 (r4.1): não cego

A r4.1 não é rodada nova: é o código da r4 com correções motivadas pelo red-team cego v3 (motivo registrado na conferência: "r4.1 (versao final, depois da revisao do P1): equivalencia apos correcoes de declaracao e PIN motivadas pelo red-team cego v3 e pela revisao; a rodada completa com o LLM fica para a r5 (o congelamento citado na conclusao padrao do script foi a r4)"), mais uma conferência de equivalência sem LLM e uma regressão do v3 sem LLM. Os números acima continuam os da r4, medidos no código `sha256(src/)=1154df4aceffbf20…`. Adotar o código da r4.1 na demo é decisão da equipe.

- **Equivalência** (16/10/2026 23:01, código `sha256(src/)=52be6b825037b28f…`, `eval/reports/2026-10-16_equivalencia_r4.json`): 6/6 igual — golden set sem LLM (todas as métricas por split): igual; red-team sem LLM (resumo): igual; A/B v2 (leituras e alegações gravadas; tudo menos config): igual; replay da demo na CLI, 19 passos com a foto do DANFE (gravado no código novo): igual; replay da demo na CLI, só o XML, 17 passos (gravado em 08/10, antes das mudanças): igual; contingência da interface, 19 passos pela API (gravada no código novo): igual.
- Os números com LLM são os medidos no código da r4: a r4.1 muda só o que o motivo acima diz, com equivalência 6/6 sem LLM e as gravações da demo sem requisição nova ao LLM; não foram remedidos com o LLM.
- **Red-team cego v3 depois da correção, sem LLM (4ª execução no modo determinístico, 5ª no total): não cego**, porque as correções foram motivadas por estes casos. Ataque bem-sucedido 3% [1–17%] (1/30) (4% [1–19%] (1/26) sem a família semi-cega), over-blocking 0% [0–28%] (0/10) (`eval/reports/2026-10-16_redteam_deterministico_r4.1_v3regressao.json`). Não substitui o resultado cego da r4 (20% [10–37%] (6/30) com o LLM, 17% [7–34%] (5/30) sem ele) e não entra na fala nem na tela principal.
