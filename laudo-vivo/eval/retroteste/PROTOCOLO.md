# Retro-teste pré-registrado da triagem (protocolo)

**Versão 1, registrada em 16/10/2026 antes de qualquer cruzamento entre a pontuação e o rótulo.**
O sha256 deste arquivo fica em `eval/retroteste/PROTOCOLO.sha256`, gravado antes de rodar.
`eval/retroteste/rodar.py` recusa rodar se o hash do protocolo não bater com o registrado. O relatório é
publicado qualquer que seja o resultado (`eval/retroteste/RELATORIO.md` e `resultado.json`).

Memorando de 16/10/2026 (`../ESTRATEGIA_FINAL.md`, seção 5A, item 6; seção 3, linha 12).

## 1. Pergunta

A pontuação de prioridade de verificação de `src/laudo/geo/triagem.py` (função `pontuar`, limiares em
`LIMIARES`), **sem retoque** e calculada **só com campos de originação**, põe no topo da fila (10% de cada
carteira) mais operações que depois tiveram desclassificação registrada pelo BCB do que uma amostra aleatória
do mesmo tamanho (a amostra aleatória é o que o MCR 2-7, item 12, admite)?

O que o retro-teste **não** mede: previsão de ilícito. O rótulo é "desclassificação registrada no Sicor", que
depende de a IF ter fiscalizado a operação e registrado o achado (viés de fiscalização). Nada aqui rotula
operação real; os resultados são agregados.

## 2. Software congelado

| Arquivo | sha256 no registro |
|---|---|
| `src/laudo/geo/triagem.py` | `509d0c5e7b65207b17ad9f1cddb92a6a937e85f9c25a8c5b796ed812ffaa113a` |
| `bench/fiscal_go/build.py` (funções `montar_itens`, `agregar_operacoes`, `faixa_valor_cabeca`, `montar_glebas`, `geometria_operacoes`, `calcular_sobreposicoes`) | `ea2d4c5ae48aee59aeb736f4c3867976415273a31414dce3f155d8ef6cc3d724` |
| `src/laudo/geo/geometria.py` | `f21702bb643528bc8ec5ee12cdc7d75b2317e4e0cd761fcef66540454d2f920a` |

As variáveis de cada operação são as que o bench Fiscal-GO 2026 já calcula, com as mesmas funções, sem
mudança de limiar, peso ou definição. Se algum desses arquivos mudar antes da rodada, o relatório registra o
hash encontrado como desvio (seção 9).

## 3. Dados

Microdados públicos do Sicor (BCB, <https://www.bcb.gov.br/htms/sicor/DadosBrutos/>), lidos em streaming; o
bruto não entra no repositório. URL, Last-Modified, bytes e sha256 de cada arquivo vão para o relatório.

- Coortes: `SICOR_OPERACAO_BASICA_ESTADO_2022.gz`, `_2023.gz` e `_2024.gz`. A coorte é o arquivo anual (ano
  de emissão).
- Glebas, só para GO: `SICOR_GLEBAS_WKT_2022.gz`, `_2023.gz` e `_2024.gz`.
- Rótulo: `sicor_desclassificacao.gz` na versão baixada na rodada (a mesma de
  `bench/desclassificacao/desclassificacoes.parquet`, coluna `na_versao_atual`).
- Tabelas de domínio: `Empreendimento.csv`, `FaseCicloProducao.csv`, `DadosBrutos/SICOR_LISTA_IFS.csv`,
  `CategoriaEmitente.csv`, `Programa.csv`, `FonteRecursos.csv`.
- Não se usa `SICOR_PROPRIEDADES` (tem CPF/CNPJ) nem `SICOR_COMPLEMENTO_OPERACAO_BASICA`.

### Campos de originação permitidos (lista fechada)

`REF_BACEN, NU_ORDEM, CNPJ_IF, DT_EMISSAO, DT_VENCIMENTO, CD_CATEG_EMITENTE, CD_FONTE_RECURSO, CD_ESTADO,
CD_EMPREENDIMENTO, CD_PROGRAMA, CD_FASE_CICLO_PRODUCAO, VL_QUANTIDADE, VL_PARC_CREDITO, VL_REC_PROPRIO,
VL_AREA_FINANC, CD_CNPJ_CADASTRANTE, VL_AREA_INFORMADA, PC_BONUS_CAR` e, em GO, os polígonos das glebas
(`REF_BACEN, NU_ORDEM, NU_INDICE, GT_GEOMETRIA`).

**Excluídos de propósito** (informação posterior à contratação ou que não é da originação):
`VL_PRODUTIV_OBTIDA`, `DT_INIC_COLHEITA`, `DT_FIM_COLHEITA` e, por precaução, `DT_INIC_PLANTIO`,
`DT_FIM_PLANTIO`, `VL_PREV_PROD` e `VL_RECEITA_BRUTA_ESPERADA`. A extração grava só as colunas da lista
fechada; um teste confere que as excluídas não estão nela.

## 4. População

Operações (`REF_BACEN`) com pelo menos um item de **compra de gado** na definição do bench
(`eh_compra_gado`): `PRODUTO = BOVINOS` e (Investimento + `AQUISIÇÃO DE ANIMAIS`) ou (Custeio +
`AQUISIÇÃO E MANUTENÇÃO DE ANIMAIS`). É o recorte "operações com animais" do memorando em que as regras da
triagem se aplicam (as regras de lotação, valor por cabeça e fração do rebanho só pontuam compra de gado).

Escopos: **BR** (todas as UFs) e **GO** (`CD_ESTADO = GO`). Cada operação entra com **todos** os seus itens
(a área informada máxima e o valor somam itens que não são de bovinos, como no bench).

## 5. Pontuação (sem retoque)

Para cada escopo e coorte, a carteira é o arquivo da coorte recortado ao escopo. Sobre ela rodam
`montar_itens`, `agregar_operacoes` e `faixa_valor_cabeca` (a faixa p1–p99 do valor por cabeça é a da própria
carteira, como no bench), e `pontuar(op).pontos` dá a pontuação (inteiro; maior = mais prioridade).

Dois conjuntos de insumos:

- **cadastro** (BR e GO): só o arquivo de operações. Pontuam `LOTACAO_ALTA` e `VALOR_CABECA_ATIPICO`. Sem
  polígono, município ou rebanho, `SOBREPOSICAO_GLEBAS`, `AREA_DIVERGENTE` e `FRACAO_REBANHO_MUNICIPAL`
  ficam sem insumo e não pontuam (comportamento nativo de `pontuar` com o campo ausente).
- **cadastro+geo** (só GO): acrescenta os polígonos de **todas** as operações de GO da coorte
  (`montar_glebas`, `geometria_operacoes`, `calcular_sobreposicoes`, sobreposição dentro do mesmo ano
  agrícola e dentro do mesmo arquivo anual, como no bench). Passam a pontuar também `SOBREPOSICAO_GLEBAS` e
  `AREA_DIVERGENTE`. `FRACAO_REBANHO_MUNICIPAL` continua sem insumo: o rebanho disponível é a PPM 2025,
  posterior às coortes.

Nenhum parâmetro é escolhido olhando o rótulo.

## 6. Rótulos (por operação)

- **A, qualquer motivo:** a operação tem pelo menos um registro em `sicor_desclassificacao.gz`.
- **B, motivos 001 e 013:** pelo menos um registro com `CD_MOTIVO_DESC` 001 ("aplicação de recursos em
  atividade diversa") ou 013 ("aplicação não comprovada de recursos").

Registros com código sem descrição publicada (ex.: 014) contam no rótulo A e não no B.

## 7. Métricas

Unidade: operação. Para cada escopo, conjunto de insumos, rótulo e estratificação:

- **Taxa-base** com IC de Wilson.
- **Top 10%:** em cada estrato, as operações são ordenadas pela pontuação (decrescente) e entram as primeiras
  10% do estrato. Empate na fronteira é resolvido pelo **valor esperado do desempate aleatório**: entra a
  fração necessária do grupo empatado, com a taxa de positivos do grupo. Isso torna o resultado determinístico.
- **Captura@10%** = positivos esperados no top 10% / positivos do estrato (somados entre estratos).
- **Lift@10%** = captura / 0,10 (= taxa no top 10% / taxa-base).
- **AUC** (Mann–Whitney, empate vale 0,5) só com pares positivo–negativo do mesmo estrato.

Estratificações:

1. **coorte×IF** (cada IF concedente, pela raiz do `CNPJ_IF`, escolhe o seu top 10% em cada coorte; somam-se
   os estratos). É a leitura "a IF aplica a triagem na própria carteira" e controla a diferença de taxa de
   desclassificação entre IFs.
2. **coorte** (top 10% do escopo inteiro em cada coorte).
3. **coorte×IF×tipo de compra** (investimento ou custeio): controle de confusão pelo tipo de compra, que tem
   taxas-base muito diferentes.

Coortes: 2022, 2023 e 2024, cada uma separada e as três empilhadas (os estratos se somam). A coorte 2024
vale só como **limite inferior**: as desclassificações das operações de 2024 ainda estão se acumulando.

Linhas de base, com a mesma estratificação:

- **Aleatório:** amostra de Bernoulli(0,10) dentro de cada estrato, sorteada de novo em cada réplica do
  bootstrap (valor esperado do lift = 1; o IC mostra a variação de uma amostra aleatória real).
- **Só valor:** ordena pelo valor financiado da operação (`valor_rs`, soma de `VL_PARC_CREDITO`; maior
  primeiro; valor ausente vale 0).
- Diferença pareada lift(regras) − lift(só valor), na mesma réplica.

**Dentro de cada IF:** tabela por IF (estratificação coorte×IF, somada nas coortes) para as IFs com pelo
menos 20 positivos no rótulo A no escopo; as IFs aparecem anonimizadas (IF-01, IF-02, ... por tamanho da
população), com o segmento da IF.

**Intervalos:** bootstrap de Poisson (peso Poisson(1) por operação), B = 1000 réplicas, semente 20261016, IC95
por percentis 2,5 e 97,5. A mesma réplica serve a todas as métricas de um escopo (comparações pareadas).

## 8. Critério de palco (decidido antes de rodar)

**Análise primária:** escopo BR, insumos "cadastro", rótulo A, coortes 2022–2024 empilhadas, estratificação
coorte×IF.

**Passa no limiar de palco se, e somente se, o limite inferior do IC95 do lift@10% da análise primária for
maior que 1,5.** Todas as outras análises são secundárias e descritivas; nenhuma delas substitui a primária
(sem "melhor de N").

- Se passar: o palco pode dizer "num retro-teste pré-registrado com as operações de compra de gado de
  2022–2024, a priorização por dado público pôs no top 10% X vezes mais desclassificações registradas que a
  amostra aleatória (IC95 a–b)", com os números entre marcadores `retro.*` de `numeros.md`. Se a linha de base
  "só valor" tiver lift igual ou maior, a frase não atribui o ganho às regras da triagem.
- Se não passar: nada do retro-teste vai ao palco. No Q&A: "fizemos um retro-teste pré-registrado; não passou
  no limiar que fixamos; o relatório está publicado".

## 9. Desvios

Qualquer mudança neste protocolo depois do registro gera uma versão nova, com hash novo, e o relatório da
versão 1 continua publicado. Desvios de execução (arquivo indisponível, falta de memória, hash de software
diferente) vão para a seção "Desvios" do relatório, com o efeito esperado.

## 10. Limitações conhecidas no registro

- Viés de fiscalização no rótulo e diferença de esforço entre IFs (por isso a estratificação por IF).
- Censura: operações recentes tiveram menos tempo para serem desclassificadas (2024 é limite inferior).
- Quebra de série no registro de desclassificações (ver `bench/desclassificacao/README.md`).
- BR sem as regras geométricas: o resultado BR mede só as regras de cadastro.
- A sobreposição em GO só enxerga operações do mesmo arquivo anual (como no bench).
