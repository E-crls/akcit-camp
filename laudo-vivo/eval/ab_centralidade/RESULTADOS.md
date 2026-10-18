# A/B de centralidade — resultado e leitura (09/10/2026)

Rodada final (rodada 3): `scripts/py.sh eval/ab_centralidade/run_ab.py --sufixo _r3` (relatório bruto em
`eval/reports/2026-10-09_ab_centralidade_r3.md` e `.json`, com o diálogo de cada episódio). 14 casos válidos do
split dev × 3 perfis de erro do fiscal × 2 braços = 42 pares; agente com `qwen3.5:4b` (perfil escritório), sem
outra rodada no Ollama; `sha256(src/)=c297955f…` (o mesmo do golden set, do red-team e do A/B v2).

| Medida | Checklist sem LLM | Agente |
|---|---|---|
| Saiu da fazenda com evidência suficiente | 100% [92–100%] (42/42) | 100% [92–100%] (42/42) |
| Pedido de correção logo depois do erro do fiscal | 100% [96–100%] (84/84) | 99% [94–100%] (83/84) |
| Turnos até ficar suficiente (mediana) | 8 | 9 |
| Turnos por fiscalização (média) | 10,4 | 10,9 |
| Turnos ociosos — o fiscal não sabe o que fazer (média) | 1,0 | 1,1 |
| Pendências nunca pedidas | 0 | 0 |
| Latência por turno p95 | 0,03 s | 3,5 s |

Nenhum par discordante (McNemar não se aplica).

## Leitura honesta

- **Empate em completude.** Com o mesmo verificador, a mesma política e as mesmas ferramentas, o agente leva o
  fiscal simulado a sair da fazenda com a mesma evidência que o checklist fixo — nem mais, nem menos.
- **O checklist ainda é um pouco mais eficiente em turnos** (0,5 turno a menos por fiscalização; na rodada 2
  eram ~2 a menos e o dobro de turnos ociosos): ele lista todas as pendências de uma vez, sempre na mesma ordem.
  A diferença caiu entre as rodadas 2 e 3 com o mesmo simulador; não isolamos qual mudança do agente a reduziu.
- **Histórico (rodadas de 08/10, outro `src/`):** 98% e 95% de suficiência para o agente contra 100% do checklist.
  O agente perdia quando um documento cobria só parte do item (NF-e com 18 de 35 cabeças: pedia "justificativa
  literal" em vez da outra nota) e quando pedia em loop uma "foto da estrutura inteira" para a conclusão da obra,
  que nenhuma ferramenta liberada usa. As correções da rodada 2 e duas correções do simulador ("já pedi vídeo" e
  pedido em frase sem o nome da evidência, como "Precisa refazer do interior", que um fiscal entenderia) fecharam
  a diferença.
- **O que este A/B não mede** (e é onde o agente pode ganhar): fiscal com as mãos ocupadas que fala em vez de
  tocar na tela; narração que vira alegação com ponteiro para o trecho (no formulário, 0 por construção);
  explicação da regra quando o fiscal pergunta. Também não mede recall de defeito, que é igual nos dois braços por
  construção (o status vem das ferramentas e do verificador).
- **Frase para o Q&A:** "Tirar o LLM devolve o formulário: no fiscal simulado ele empata com o agente em
  completude e ganha em turnos. O ganho do agente tem de aparecer com gente de verdade: tempo até o laudo com as
  mãos ocupadas e cobertura da narração, no teste com peritos de 16/10."

## Onde o agente passa o formulário: A/B v2

Com papel fotografado e fala livre (`eval/ab_centralidade_v2/`, relatório
`eval/reports/2026-10-09_ab_centralidade_v2_r3.md`, mesmo `sha256(src/)`), o agente com o residual real completa
97% [86–100%] (35/36) das fiscalizações contra 42% [27–58%] (15/36) do formulário em que a fiscal digita tudo
(pares discordantes 21 × 1, McNemar exato p < 0,0001), com 0 campo aceito errado (formulário: 13 de 1.399) e tempo
modelado da fiscal de ~37 s contra ~216 s. Na média de 49 réplicas: 91,3% contra 37,6%. Tempo e erro humano são
modelados com parâmetros citados; vale o mesmo aviso do teste com peritos.

## Como o agente pode passar o checklist

1. Toda fala termina com o **pedido específico da 1ª pendência** da política (tipo de evidência + item + como
   capturar), em template; o LLM só reescreve o começo.
2. Documento que cobre só parte do item (NF-e com menos cabeças, GTA "CARGA 1 DE 2"): perguntar se há outra
   nota/GTA da mesma compra antes de pedir justificativa.
3. Mostrar na tela, junto da voz, a lista de pendências: o produto vira checklist + voz, e o A/B passa a medir se
   o LLM atrapalha, não se ele substitui a lista.

## Limitações

O fiscal é simulado por palavras-chave (pedido = frase com marca de pedido e o tipo de evidência, com anáfora para
a frase anterior). As duas correções do simulador foram feitas depois de ler diálogos do agente; valem para os
dois braços, mas só mudam o agente — por isso o histórico acima fica registrado. Três perfis de erro, plantados
pela equipe; não há tempo de campo (só turnos). O teste com 3 a 5 peritos, cronometrado e em ordem
contrabalanceada, continua necessário.
