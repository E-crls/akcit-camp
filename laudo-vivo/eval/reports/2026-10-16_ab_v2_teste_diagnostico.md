# Anexo: A/B v2 no teste, caso a caso (16/10/2026, noite)

**Análise pós-teste, feita olhando o teste; nenhum número oficial muda.** Os números oficiais do A/B v2 no teste
são os do relatório [`2026-10-16_ab_centralidade_v2_r4_teste.md`](2026-10-16_ab_centralidade_v2_r4_teste.md)
(execução `216355e9efc1` do registro do teste, réplica 0, fiscal simulado, documentos e narrações sintéticos), e o
`SLIDE.md` traz a leitura escrita antes de rodar, a nota pós-resultado e a cronologia das leituras refeitas. Este
anexo junta o diagnóstico e a contraprova feitos na noite de 16/10, com scripts só de leitura fora do repositório,
já com as correções da contraprova. O que ela derrubou não entra aqui.

Por ter sido feito olhando o teste caso a caso, qualquer execução futura no teste deixa de ser cega para a fala e
a leitura (o registro do teste ganha a entrada "análise pós-teste caso a caso"). Tudo o que está na seção
"Para a r5" se mede no dev e em casos novos, fora do split congelado.

## Resumo

- Sem a menção a item não financiado (a comparação principal), o agente + residual ficou em 19/24 e o formulário
  em 21/24 (pares 2 × 4, McNemar p = 0,6875); na métrica completa, 17/24 contra 14/24 (6 × 3, p = 0,5078). Nas
  duas, a diferença não é estatisticamente significativa.
- **Os documentos empatam:** a conciliação documental igual à do oráculo dá 21/24 nos dois braços. O formulário
  erra GLD-0006, GLD-0038 e GLD-0044; o agente + residual erra GLD-0032, GLD-0044 e GLD-0045.
- **A diferença está na fala:** o formulário digita a contagem e a metragem (com erro só de digitação), e o
  agente extrai da fala livre.
- **Quem muda do dev para o teste é o agente, não o formulário.** A falha documental do formulário mal muda (7/36
  no dev, 3/24 no teste); a do agente + residual vai de 0/36 para 3/24. Na média das 49 réplicas, sem a menção, o
  formulário fica em 77,6% no dev e 78,8% no teste, e o agente + residual vai de 91,3% para 77,6%. O 35/36 do dev
  foi uma réplica acima da média do próprio dev.
- **"Parte do ganho do dev era ajuste ao dev" tem evidência fraca.** Das 6 falhas de fala do LLM no teste, 3
  caem em caminhos que o dev nunca exercitou, por sorteio do mesmo gerador ("contei um" e dois casos com o mesmo
  número em duas alegações); as outras 3 são erros do LLM em moldes que o dev tem e em que ele acertou. As
  leituras do VLM do dev são de 09/10/2026, sem `meta.json` e de antes da troca de NUM_CTX, mas no nível do campo
  o leitor se comporta de forma parecida nos dois splits (erro cru da 1ª leitura em 340 de 5025 campos no dev e
  225 de 3336 no teste). O honesto é: o resultado do dev não se repetiu, com n pequeno, padrões que o dev não
  tinha e bugs que ele não exercitava.

## Tabela caso a caso (réplica 0)

Cada célula: conciliação documental igual à do oráculo / alegações da fala com status certo / conteúdo igual à
referência sem a menção / conteúdo igual à referência completo. A coluna das alegações do formulário conta a
menção a item não financiado, que ele não tem campo para registrar.

| Caso | Classe | Formulário | Agente + residual | O que explica a falha (só onde há) |
|---|---|---|---|---|
| GLD-0003 | válido | sim / 2/2 / sim / sim | sim / 1/2 / **não** / **não** | Fala: "contei um" é descartado pela guarda determinística (não ler "um" como número evita o artigo); o molde só existe no teste |
| GLD-0004 | ambíguo (A03) | sim / 1/2 / sim / **não** | sim / 1/2 / sim / **não** | Só na completa: "tinha 4 touros" e "uns 4 bezerros" têm o mesmo número, e a deduplicação por (grandeza, valor) apaga a menção |
| GLD-0005 | válido | sim / 1/2 / sim / **não** | sim / 2/2 / sim / sim | Formulário: sem campo para a menção |
| GLD-0006 | ambíguo (A05) | **não** / 1/2 / **não** / **não** | sim / 2/2 / sim / sim | Formulário: não tem campo de observação, perde a carga parcial e gera falsa divergência |
| GLD-0012 | defeito (D05) | sim / 2/2 / sim / sim | sim / 2/2 / sim / sim | |
| GLD-0016 | defeito (D11) | sim / 1/1 / sim / sim | sim / 0/1 / **não** / **não** | Fala: em "contei 62 curral novo" o LLM devolveu lista vazia, e o regex não pega número sem o nome do animal depois |
| GLD-0017 | válido | sim / 1/2 / sim / **não** | sim / 2/2 / sim / sim | Formulário: sem campo para a menção |
| GLD-0019 | válido | sim / 1/1 / sim / sim | sim / 1/1 / sim / sim | |
| GLD-0022 | válido | sim / 2/2 / sim / sim | sim / 2/2 / sim / sim | |
| GLD-0024 | válido | sim / 2/2 / sim / sim | sim / 2/2 / sim / sim | |
| GLD-0032 | válido | sim / 1/2 / sim / **não** | **não** / 1/2 / **não** / **não** | Documento: na foto média, NCM 01022918 (não existe na TEC) aceito com 2/3; a foto leve leu 01022919 com 3/3, mas o mesclar do harness apagou o campo em conflito e o residual, calculado só da última foto, não pediu nada. Fala: o LLM tomou "3 filhos" como contagem (alegação espúria nociva), e o conjunto "vistos" suprimiu o 15 certo do regex |
| GLD-0037 | válido | sim / 2/2 / sim / sim | sim / 2/2 / sim / sim | |
| GLD-0038 | ambíguo (A04) | **não** / 2/3 / **não** / **não** | sim / 2/3 / sim / **não** | Formulário: código do estabelecimento digitado errado e aceito (não tem DV). Agente, só na completa: "deu 15 cabeças" e "comprou 15 garrotes por fora" têm o mesmo número, e a deduplicação apaga a menção (até o modo só com regras perde) |
| GLD-0039 | defeito (D03) | sim / 1/1 / sim / sim | sim / 1/1 / sim / sim | |
| GLD-0040 | defeito (D09) | sim / 1/1 / sim / sim | sim / 1/1 / sim / sim | |
| GLD-0042 | defeito (D02) | sim / 2/2 / sim / sim | sim / 2/2 / sim / sim | |
| GLD-0044 | defeito (D10) | **não** / 2/3 / **não** / **não** | **não** / 2/3 / **não** / **não** | Os dois erram. Agente, documento: a foto pesada leu o município do emitente como PIRANHAS nas 3 leituras (papel: FAINA); a foto média leu FAINA certo nas 3 ("FAINA", "FAINA - GO", "FAINA"), mas o `_canon` do consenso compara sem tirar o " - GO" e a barrou como não unânime; o mesclar manteve PIRANHAS. Fala: em "das 45 que ele comprou eu achei 47" o LLM pegou o 45 e perdeu o 47 |
| GLD-0045 | ambíguo (A01) | sim / 1/1 / sim / sim | **não** / 1/1 / **não** / **não** | Documento: na foto leve (a melhor), o VLM leu PORANGATU, o município do destinatário, no lugar de GOIÁS (município homônimo do estado), nas 3 leituras |
| GLD-0046 | ambíguo (A02) | sim / 2/2 / sim / sim | sim / 2/2 / sim / sim | |
| GLD-0048 | defeito (D01) | sim / 2/3 / sim / **não** | sim / 3/3 / sim / sim | Formulário: sem campo para a menção |
| GLD-0049 | defeito (D06) | sim / 2/2 / sim / sim | sim / 2/2 / sim / sim | Mudou com a releitura das 3 leituras com falha de infraestrutura (ver o `SLIDE.md`) |
| GLD-0054 | defeito (D12) | sim / 2/2 / sim / sim | sim / 2/2 / sim / sim | |
| GLD-0057 | válido | sim / 1/2 / sim / **não** | sim / 2/2 / sim / sim | Formulário: sem campo para a menção |
| GLD-0059 | válido | sim / 1/2 / sim / **não** | sim / 2/2 / sim / sim | Formulário: sem campo para a menção |

Nenhuma das 3 falhas de documento do agente virou falso "verificado": todas viraram pendência.

## Correções que a contraprova fez no diagnóstico

- **Falha documental:** a do formulário é 7/36 no dev e 3/24 no teste (quase não muda); a do agente + residual é
  0/36 no dev e 3/24 no teste. "O ganho do dev vinha dos erros de digitação do formulário" conta só metade.
- **Molde "X no curral, contei N":** aparece 8 vezes no dev, com 7 acertos do LLM (e não 6 com 5). A única falha
  (GLD-0026) tem outra causa: o trecho não está na fala. "3 filhos" aparece 6 vezes no dev, sempre certo.
- **GLD-0044:** a foto média leu FAINA certo nas 3 leituras e mesmo assim saiu indeterminada, porque o `_canon`
  do consenso não tira o " - GO" (o `validar_danfe` só tira depois). Isso acontece em 12 de 72 fotos de DANFE do
  teste e em 22 de 117 do dev, e explica parte dos campos `danfe:emitente_municipio` barrados. Mesmo corrigido, o
  mesclar do harness transformaria PIRANHAS × FAINA em vazio, e o resultado do caso não muda.
- **GLD-0032:** corrigir o conjunto "vistos" não recupera o caso, porque a alegação espúria do "3 filhos"
  continua e o caso também falha nos documentos.

## Bugs e lacunas achados olhando o teste (existem também no dev e no produto)

Corrigir é legítimo, mas tem de ser declarado como achado no teste, e a correção se mede no dev e em casos novos.

1. **Deduplicação de alegações por (grandeza, valor)** (`src/laudo/agent/condutor.py`, união LLM ∪ regex e
   saída): duas alegações diferentes com o mesmo número viram uma só. Nenhuma narração do dev tem valor repetido
   entre as alegações esperadas; no teste há duas (GLD-0004 e GLD-0038).
2. **Conjunto "vistos" montado antes da releitura determinística** (mesmo arquivo): usa o valor que o LLM
   propôs, antes de a releitura do trecho corrigi-lo, e suprime o candidato certo do regex (GLD-0032; inferido do
   código e reproduzido com LLM falso, porque a resposta crua do LLM não é gravada).
3. **Residual só da última foto** (`eval/ab_centralidade_v2/run_ab_v2.py`): não pede o campo que o conflito entre
   fotos apagou no mesclar.
4. **Leituras com erro de infraestrutura aceitas em silêncio** (mesmo harness): registros com HTTP 500/400 e
   respostas parciais entram como leitura normal, com menos leituras, sem aviso.
5. **`_canon` do consenso sem tirar o " - UF"** (`src/laudo/tools/leitura.py`): leituras certas do município são
   barradas como não unânimes.
6. **Casamento guloso no avaliador da fala** (`pontuar()` em `eval/ab_centralidade_v2/avaliar_narracoes.py`):
   casa alegação esperada com obtida por (grandeza, valor), na ordem; com valores repetidos a nota depende da
   ordem. Antes de medir a correção do item 1, o avaliador tem de casar também pela posição do trecho, e falta
   decidir o que fazer quando a fiscal repete a mesma contagem.

## O que seria ajuste ao teste (proibido)

- Ensinar "contei um", "3 filhos" ou "contei 62 curral novo" ao normalizador, ao regex ou ao prompt.
- Tornar o município do emitente crítico, ou tratar o homônimo GOIÁS, por causa do GLD-0045.
- Mudar a junção de fotos, as distribuições de qualidade ou o modelo de erro de digitação por causa destes casos.
- Reescrever a leitura escrita antes de rodar e apresentá-la como pré-registrada.

## Assimetrias do desenho (declaradas)

- O formulário digita a contagem da crença do fiscal e a metragem das alegações esperadas, só com erro de
  digitação: ele nunca perde uma alegação por extração.
- O município do formulário vem de uma lista sem erro de seleção.
- O formulário não tem campo de observação (perde a carga parcial, a favor do agente) e nunca registra a menção a
  item não financiado (por construção; por isso a comparação principal é a sem a menção).
- As leituras do VLM do dev são de 09/10/2026, sem `meta.json`; as do teste foram feitas na r4.
- A réplica 0 é um único sorteio de qualidade de foto e de erro de digitação; as 49 réplicas seguintes mostram a
  variação.

## Para a r5

Tudo medido no dev e em casos novos, escritos por quem não viu o teste, nunca no split congelado:

- os itens 1 a 6 acima, com teste unitário de frases novas (o teste proposto que copia o molde do GLD-0038 tem de
  ser declarado como derivado do teste);
- gravar a resposta crua e a validade da resposta do LLM por narração (no GLD-0016 não dá para saber se foi lista
  vazia ou JSON inválido depois do reparo);
- responder no dev como o produto trataria duas leituras de DANFE com identidades diferentes (o caso do
  GLD-0032): ele poderia acertar o documento, o que mudaria o "documentos empatam", ou criar um documento
  duplicado;
- modelar erro de seleção na lista e dar ao formulário um campo de observação.
