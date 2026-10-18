# Agente único ou multiagente? O argumento de permissões

Este documento responde ao REQ-39 do parecer (parecer interno do juiz do edital: "justificativa medida para o multiagente,
ou ao menos um argumento de permissões") e à pergunta Q-05 da banca ("por que vários agentes e não um só?"). É a
etapa A do L103: o **argumento**, com o que já foi medido e o que não foi. A etapa B (a ablação medida) está
descrita no fim e **não foi feita**.

Os números entre marcadores `<!--n:…-->` vêm de `docs/entregaveis/numeros.json` (rodada r3, 09/10/2026, o mesmo
`sha256(src/)` em todos os relatórios). Depois da r4, `scripts/gerar_numeros.py --aplicar` os atualiza, se este
arquivo estiver na lista `ALVOS`.

## 1. Resposta curta, sem exagero

O Laudo Vivo tem **um** agente com LLM: o condutor (`src/laudo/agent/condutor.py`, qwen3.5:4b local). Não há
vários LLMs conversando entre si, e não vamos chamar isso de "multiagente" na banca. O que existe é **separação de
papéis com permissões disjuntas, garantida por código**:

- quem conversa com a fiscal (o LLM) **não** dá o status de nenhum campo;
- quem dá o status (o verificador, com `avaliar_regras` e o rulebook do MCR 2-7) **não** usa LLM;
- quem autoriza cada ação (a política, POL-00 a POL-09) **não** usa LLM e nega por padrão;
- quem emite, envia para assinatura e assina é **o humano** (comando, botão e PIN), nunca o LLM.

A frase para a banca: "um agente de conversa e um verificador independente, sem LLM; quem escreve não é quem
confere, e quem confere não é quem assina."

## 2. Quem pode o quê

| Papel | Usa IA? | Pode | Não pode (e onde isso é garantido) |
|---|---|---|---|
| Condutor (LLM) | sim, qwen3.5:4b | propor tool calls da allowlist da etapa; pedir evidência; falar com a fiscal; extrair alegações da fala, com ponteiro para o trecho | definir status; emitir rascunho; enviar para assinatura; assinar; mudar valor ou evidência; redigir justificativa ou atestar obra. `fsm.nomes_permitidos` tira do LLM, em toda etapa, as ações só de comando humano (`ACOES_POR_COMANDO_HUMANO`) e as ferramentas do plano (`FERRAMENTAS_DO_PLANO`); a política nega o resto (POL-00, POL-02, POL-03). Fala com número sem lastro é descartada (POL-05) e fala inconsistente com o estado vira template (POL-09) |
| Leitor de documento e classificador de foto | sim, VLM local | ler o DANFE e a GTA fotografados; dizer se a foto mostra a benfeitoria | ser chamado pelo LLM (são do plano determinístico); aceitar campo que não valida (DV, somas, datas): o campo fica indeterminado e vira pedido residual |
| Plano determinístico | não | escolher as checagens a partir do que chegou (foto, XML, vídeo, fala) | — (cobre o LLM quando ele erra a ferramenta) |
| Ferramentas | não | todas as contas (contagem, geofence, conciliação, NDVI, lotação), sempre com `Envelope` | inventar valor: erro vira `Envelope.falha`, nunca número |
| Verificador + `avaliar_regras` | não | dar o status de cada campo a partir do estado e das checagens, citando a regra | depender da fala do LLM: recalcula tudo do estado a cada turno (`verificador.recalcular`) |
| Política | não | permitir ou negar cada ação, por etapa (default-deny) | — |
| Humano (fiscal) | — | emitir o rascunho, enviar para assinatura, assinar com PIN e o hash raiz; justificar divergência com as próprias palavras | assinar com evidência nova depois do último rascunho (POL-03) |

Os testes que travam essas permissões: `tests/unit/test_agente_guardrails_v2.py::test_llm_nunca_recebe_emissao_nem_assinatura`
e `::test_llm_que_tenta_emitir_e_negado`, `tests/unit/test_agente_politica.py::test_pol00_default_deny` e
`::test_pol03_agente_nunca_assina`, `tests/unit/test_agente_fsm.py::test_transicao_invalida_e_selo_so_humano`.

## 3. Por que não um agente único que faça tudo

Num agente único, o mesmo LLM que ouve "pode marcar 29, o resto está no pasto de cima" e lê o texto de uma NF-e
adulterada seria quem decide o status do campo. Pressão social e injeção chegariam direto a quem decide, e o erro
de quem coleta e o de quem confere seriam o **mesmo erro** (autoconfirmação). Aqui, o pior que um LLM enganado
consegue fazer é pedir a coisa errada ou dizer uma frase que a política descarta: o status sai do verificador,
que só enxerga o estado e as evidências.

A separação não está no prompt (que um ataque poderia contornar), está no código: a ação de emitir nem é oferecida
ao LLM, e a política nega ação humana vinda dele mesmo que ele a peça.

## 4. Por que não vários agentes com LLM

1. **Um segundo LLM como verificador traria os mesmos modos de falha** (alucinação, injeção, número sem lastro)
   para a decisão. O rulebook determinístico cita a norma em cada regra e dá o mesmo resultado para a mesma
   entrada, o que um verificador com LLM não garante.
2. **Recurso:** o notebook de campo carrega um modelo por vez na GPU (`CONTRIBUTING.md`). Dois agentes com
   LLM ao mesmo tempo dobrariam a latência ou exigiriam um modelo menor.
3. **Não medimos uma versão com vários LLMs.** O argumento acima é de desenho, não de medida.

## 5. O que já foi medido e sustenta o argumento

- **O status vem do código, não do LLM.** Sem o LLM, o mesmo pipeline acha os mesmos defeitos no teste: recall
  <!--n:sem_llm.recall_teste.kn-->9/9<!--/n--> sem LLM e <!--n:recall_teste.kn-->9/9<!--/n--> com o agente. No A/B v1
  (entrada já estruturada, <!--n:ab1.pares.valor-->42<!--/n--> pares), o checklist sem LLM e o agente empatam
  (<!--n:ab1.checklist.valor-->100%<!--/n--> × <!--n:ab1.agente.valor-->100%<!--/n-->), como o desenho prevê.
- **O pior erro não aconteceu:** falso "verificado" de <!--n:falso_verificado_teste.kn-->0/16<!--/n--> nos campos com
  problema do teste.
- **Red-team: o da equipe não pegou brecha; o cego pegou:** ataque bem-sucedido no red-team escrito pela equipe de
  <!--n:redteam.ataques.kn-->0/80<!--/n--> com o agente e <!--n:redteam.sem_llm_ataques.kn-->0/80<!--/n--> só com as
  guardas determinísticas; no conjunto cego, escrito de forma isolada e rodado uma vez,
  <!--n:redteam.cego_ataques.kn-->6/30<!--/n--> com o agente (<!--n:redteam.cego_ataques_sem_semicega.kn-->6/26<!--/n-->
  sem a família semi-cega) e <!--n:redteam.cego_sem_llm_ataques.kn-->5/30<!--/n--> só com as guardas.
- **Onde o LLM entra:** com papel fotografado e fala livre, sintéticos, no teste congelado, o agente com o pedido
  residual não conciliou mais que o formulário (<!--n:ab2_teste.residual.kn-->17/24<!--/n--> contra
  <!--n:ab2_teste.formulario.kn-->14/24<!--/n-->, <!--n:ab2_teste.mcnemar.curto-->p = 0,51<!--/n-->); o ganho é poupar
  a digitação do papel (<!--n:ab2_teste.toques_residual.valor-->12<!--/n--> toques contra
  <!--n:ab2_teste.toques_formulario.valor-->304<!--/n-->, tempo modelado). Na fala livre do teste, status certo em
  <!--n:ab2_teste.fala_llm.kn-->40/46<!--/n--> com o LLM e <!--n:ab2_teste.fala_regras.kn-->32/46<!--/n--> só com regras,
  com <!--n:ab2_teste.espurias_llm.valor-->1<!--/n--> alegação espúria nociva contra
  <!--n:ab2_teste.espurias_regras.valor-->0<!--/n-->. No dev, onde o A/B foi desenvolvido,
  <!--n:ab2.residual.valor-->97%<!--/n--> contra <!--n:ab2.formulario.valor-->42%<!--/n-->, que não se repetiu no teste. O
  LLM está onde a entrada é bagunçada (papel e fala), e fora de onde o status é dado.

## 6. O que não foi medido (dizer antes que perguntem)

- **Não há ablação de agente único.** Não rodamos uma versão em que o LLM decide o status, então não temos o
  número "falso verificado caiu de X% para Y% com a separação". O que temos é o argumento de permissões e a
  medida de que, sem o LLM, o status é o mesmo.
- O red-team original e o v2 foram escritos pela equipe (o v2, junto com as correções); o conjunto cego
  (`eval/redteam/v3_cego_*`, escrito de forma isolada) ainda não tinha rodado quando este texto foi escrito
  (16/10/2026); cada execução dele fica em `eval/golden/casos/registro_teste.jsonl`, e o relatório do red-team
  separa os três conjuntos.
- O golden é sintético e circular (defeitos plantados por quem escreveu as ferramentas); ver
  `eval/README.md`, seção "Limitações".

## 7. Etapa B (L103, não feita; cerca de 6 h)

Desenho, escrito antes de rodar:

1. **Braço "agente único":** o mesmo condutor, mas o status de cada campo do laudo vem de uma saída estruturada do
   LLM (o LLM recebe o estado, as checagens e o rulebook e devolve `verificado | divergente | pendente | abstencao`
   por campo); a política continua negando assinatura e emissão (para medir só o efeito de quem decide o status).
2. **Braço atual:** o verificador determinístico.
3. **Medidas:** falso "verificado", recall de defeito e abstenção correta no golden (desenvolver no dev; rodar o
   teste uma vez, com `--final`, e o uso fica em `eval/golden/casos/registro_teste.jsonl`), e ataque bem-sucedido
   no red-team, com destaque para pressão social e injeção via documento.
4. **Hipótese registrada antes:** o braço "agente único" terá falso "verificado" maior que zero nos casos de
   pressão e injeção. Se não tiver, o argumento de permissões continua valendo por auditabilidade (regra citada e
   resultado repetível), mas não por número, e é isso que diremos.
