# Mercado do Laudo Vivo: números conferíveis

Os números de mercado que o pitch, o BMC e o Q&A citam, cada um com o tipo, a fonte e o jeito de conferir.
Escrito em 16/10/2026 a partir do plano de negócio da equipe (versão de 08/10/2026), dos pareceres internos de
08/10/2026 e dos dados públicos do BCB, do IBGE e do MMA. Todo número calculado por nós foi **reconferido em
16/10/2026** contra os agregados ou contra o bench do repositório; onde a reconferência achou diferença, a
diferença está escrita.

**Antes de citar:**

- **Nenhum preço foi testado com cliente** e não houve entrevistas registradas até 16/10/2026. Todo preço nosso
  é preço-alvo, uma hipótese.
- **O tamanho de mercado é estimativa**, não fato. Ela depende de uma taxa de fiscalização que as instituições
  financeiras não publicam (seção 5).
- Nenhum número desta página vem de avaliação do produto. Os números de avaliação estão em
  [`numeros.md`](numeros.md), e nada simulado (A/B com fiscal simulado, golden set, red-team) é validação de
  mercado.

**Legenda:**

| Marca | Quer dizer |
|---|---|
| **[F]** | fato com fonte pública (link na linha); "citado" = vem de pesquisa de 08/10 ou 16/10/2026 e deve ser reconferido na fonte antes de ir ao palco |
| **[D]** | dado calculado por nós a partir de fonte pública, com o método escrito na seção 7 |
| **[E]** | estimativa nossa, com a conta exposta |
| **[H]** | hipótese que só entrevista ou piloto confirma |

## 1. Quantas unidades existem para provar: Sicor 2025, Brasil [D]

Fonte: microdados do Sicor/BCB,
[`SICOR_OPERACAO_BASICA_ESTADO_2025.gz`](https://www.bcb.gov.br/htms/sicor/DadosBrutos/SICOR_OPERACAO_BASICA_ESTADO_2025.gz)
(64.720.611 bytes, Last-Modified 07/10/2026) e a
[tabela de empreendimentos](https://www.bcb.gov.br/htms/sicor/Empreendimento.csv). Calculado em 08/10/2026 em
streaming, sem gravar o bruto; reconferido em 16/10/2026 contra os agregados.

| Recorte | Número | Observação |
|---|---|---|
| Operações de crédito rural | 1.830.128, R$ 361,2 bi | contagem de trocas de `REF_BACEN` entre linhas seguidas (aproximada) |
| Itens financiados (linhas: um empreendimento por linha) | 2.456.396 | |
| ... no BNB | 1.341.598 (55% das linhas), R$ 23,3 bi | quase todo microcrédito: "1,8 milhão de operações" **não** é o nosso mercado |
| Itens físicos, todas as faixas de valor | 1.556.243 (63% das linhas), R$ 123,1 bi | bem que a imagem de 10 m não prova (definição na seção 7) |
| ... abaixo de R$ 20 mil | 1.030.903, R$ 7,3 bi | microcrédito; fiscalização paga por unidade não fecha a conta |
| **Itens físicos de R$ 20 mil ou mais** | **525.340, R$ 115,8 bi** | **a base do dimensionamento** |
| ... no Banco do Brasil | 221.197 (42%) | |
| ... nos sistemas cooperativos (Sicoob, Sicredi e um terceiro sistema, inferido como Cresol) | 159.630 (30%) | inclui as operações dos próprios bancos cooperativos |
| Compra de bovinos por investimento, todas as faixas | 300.921 itens, R$ 15,52 bi | |
| Cercas, currais, cochos, porteiras e mata-burros (serviços técnicos, pecuário e agrícola) | 223.577 itens, R$ 5,07 bi | parte das linhas de "serviços" é residência, poço ou barragem |

**Cooperativas singulares** (CNPJ da instituição diferente do banco do sistema) [D]:

| Recorte | Número |
|---|---|
| Singulares com crédito rural em 2025 | 335 |
| Operações por singular: mediana; p75 | 298; 1.428 |
| Itens físicos de R$ 20 mil ou mais por singular: mediana; p75; p90 | 156; 477; cerca de 1,1 mil |
| Singulares com 300 ou mais desses itens (perfil ideal de cliente) | **109** (32,5% das 335 singulares), que somam 105.346 dos 128.056 itens das singulares (**82%** dos itens; média de 966 por singular) e 299.119 operações |
| Singulares com 500 ou mais | 78 |

**Como ler o 109 e o 82%:** 109 é a contagem de singulares (32,5% das 335); 82% é a fatia dos **itens físicos de R$
20 mil ou mais das singulares** que está nessas 109 (105.346 de 128.056). Não é 82% das singulares, nem 82% dos
159.630 itens dos sistemas cooperativos (contra esses, as 109 têm cerca de 66%, porque os 159.630 incluem as
operações dos próprios bancos cooperativos). Conferido em 16/10/2026: 109 ÷ 335 = 32,5% e 105.346 ÷ 128.056 = 82,3%.

Contexto do sistema [F, citado]: 742 cooperativas singulares, R$ 1,036 tri de ativos e 21,2 milhões de
cooperados em dez/2025
([BCB, Panorama do SNCC 2025](https://www.bcb.gov.br/content/estabilidadefinanceira/coopcredpanorama/panorama_cooperativas_sncc_anobase_dez_2025_FINAL.pdf);
[Agência Brasil, 02/07/2026](https://agenciabrasil.ebc.com.br/economia/noticia/2026-07/cooperativas-de-credito-superam-r-1-trilhao-em-ativos)).
As 742 são todas as singulares do país; as 335 são as dos três sistemas acima que tiveram crédito rural no Sicor
em 2025 (singulares de outros sistemas cooperativos não entram na conta).

## 2. Goiás: mercado de piloto, não de negócio [D]

**Em 2025** (mesma fonte da seção 1):

| Recorte | Número |
|---|---|
| Itens financiados em GO | 52.080 |
| Itens físicos de R$ 20 mil ou mais | 34.890 |
| ... no Banco do Brasil | 26.951 (77%) |
| ... nos sistemas cooperativos | 3.743 (10,7%) |
| Singulares com ao menos uma operação em GO; com 100 ou mais itens em GO | 74; 16 (3.116 itens) |

**De janeiro a setembro de 2026**, no Fiscal-GO, que está no repositório e se reproduz com
`bench/fiscal_go/build.py` ([data card](../../bench/fiscal_go/README.md)):

| Recorte | Número |
|---|---|
| Operações de crédito rural emitidas em GO | 28.637, R$ 16,49 bi (7.499 com polígono público) |
| ... com pecuária bovina | 19.009 (66,4%), R$ 5,93 bi (36,0% do valor) |
| Compra de gado | 13.385, R$ 4,76 bi |
| ... por investimento (matrizes e reprodutores) | 6.235, R$ 1,23 bi; o BB tem 86,5% dessas operações |
| ... por custeio de aquisição e manutenção de animais | 7.150, R$ 3,53 bi |
| Operações bovinas com área total acima de 300 ha | 414: as outras 97,8% (87,4% do valor) ficam até 300 ha |
| Operações bovinas no item 5 do MCR 2-7 (sensoriamento remoto obrigatório: acima de 300 ha **e** emitidas a partir de 01/03/2026) | 301: as outras 98,4% (90,3% do valor) ficam fora da obrigação |
| Rebanho bovino de GO (IBGE, PPM 2025) | 22.494.716 cabeças (`rebanho_municipal_go.parquet`) |

**Diferença achada na reconferência de 16/10/2026:** o memorando de 16/10 e a linha 5 da matriz de validação
juntam as duas linhas acima ("só 301 caem no item 5; os outros 97,8%, que são 87,4% do valor"). Os 97,8% e os
87,4% são da linha "até 300 ha" (414 operações acima); para as 301 do item 5, o certo é 98,4% e 90,3%. As 113
diferenças são operações acima de 300 ha emitidas antes de 01/03/2026. No palco, "mais de 97%" vale para as duas
leituras.

**Leitura** [E]: com 3.743 itens nas cooperativas de GO, 50% de taxa de fiscalização e o preço-alvo de R$ 79, o
software nas cooperativas goianas vale cerca de R$ 150 mil por ano. Goiás serve para validar, filmar, rotular e
conseguir as primeiras cartas de intenção; o mercado do negócio é nacional.

## 3. O que já se paga hoje [F]

| O que | Valor | Fonte | Cuidado |
|---|---|---|---|
| Piso de honorário por visita de fiscalização de crédito rural (MS, 2024) | 0,5% do saldo devedor, mínimo de 4 CA = **R$ 669** (CA = R$ 167,34) | [AEA-MS/CREA-MS, Tabela de Honorários 2024](https://creams.org.br/wp-content/uploads/2024/08/Tabela-de-Honorarios-Agronomia-2024.pdf) | piso ético de outro estado, não preço praticado em GO |
| Hora técnica de agronomia (mesma tabela) | 3 CA = R$ 502 | idem | idem |
| Credenciamento da Caixa (fiscalização, vistoria prévia, Proagro, garantias) | por hora técnica, com valores mantidos desde 2014; referência de R$ 180 por hora (2019) | [Confea, 01/2022](https://www.confea.org.br/node/226521); [Confea, 11/2019](https://www.confea.org.br/node/224215) | valor contestado pelas entidades |
| Laudo agronômico com ART para financiamento rural (particular) | R$ 1.000 a R$ 3.500 | [Freela sem Crise](https://www.freelasemcrise.com.br/quanto-cobrar/assistencia-tecnica-agronomia) | página comercial, metodologia não divulgada |
| Software com fluxo da IF para o técnico (Softfocus Assist) | R$ 49,90 por mês (Plano Gestão) a R$ 487,40 por mês (Plano 300); nos planos 100 a 300 (R$ 222,90 a R$ 487,40), o valor é o mensal da **assinatura anual** | [softfocusassist.com.br, seção de planos](https://softfocusassist.com.br/#planos), consulta de 16/10/2026 (linha 9 da [matriz](../../validacao/README.md)) | não conferimos o que cada plano inclui; reconferir antes de citar |
| Assistente de IA para análise de crédito agro (Tarken) | cerca de R$ 200 a R$ 800 por usuário por mês | [AgFeed](https://agfeed.com.br/agtech/com-novo-estrategista-no-time-tarken-tenta-ganhar-mais-espaco-no-credito-do-agro) | concessão, não fiscalização |
| Banco comprando laudo de fiscalização de terceiros | RFP BNB 2021/003, "laudo de fiscalização das operações de crédito de custeio e investimento rural" | [BNB, Aviso RFP 2021/003](https://bnb.gov.br/documents/45839/85449/Aviso%20-%20RFP%202021-003.odt/d2df03d5-bee6-ad32-1b22-413c3c7732dd) | por sensoriamento remoto; mostra a linha de orçamento, não o preço |
| Preço dos fornecedores de monitoramento e validação (Softfocus Zoom, Audsat, Agrotools, Serasa) | não publicado ("sob consulta") | levantamento de 08/10/2026 nas páginas dos fornecedores | ausência de preço não é preço baixo |

Mais sinais de que a fiscalização já é paga (desafio Sicredi, vagas de 2026) estão na linha 9 da
[matriz de validação](../../validacao/README.md).

## 4. Os nossos preços: hipóteses, nenhum testado [H]

| Produto | Unidade | Preço-alvo | Âncora [E] |
|---|---|---|---|
| Fiscalização assistida | fiscalização concluída | R$ 79 (preço-alvo; R$ 59 acima de 500 por ano) | menos de 12% do piso de R$ 669 por visita e cerca de 0,04% do crédito médio de uma compra de gado por investimento em GO (R$ 1,23 bi ÷ 6.235 ≈ R$ 197 mil), com o preço-alvo de R$ 79 |
| Licença de credenciada | fiscal por mês, 15 fiscalizações incluídas | R$ 590 | dentro da faixa do assistente da Tarken |
| Triagem de carteira | operação ativa por ano | R$ 8 | — |
| Exceção socioambiental resolvida (MCR 2-9) | exceção | R$ 490 | cerca de um terço do laudo particular com ART; **só existe se o módulo 2-9 for construído** |
| Fiscalização como serviço (fase 2) | fiscalização entregue | R$ 290 | menos da metade do piso de R$ 669, porque a visita vira exceção |
| Piloto Fundador | 90 dias, até 150 fiscalizações | R$ 5.900 | — |

Como testar: quando houver entrevistas (nenhuma até 16/10/2026), a pergunta de preço entra em cada uma (termo de
consentimento em [`docs/tcle_modelo.md`](../tcle_modelo.md)), e o resultado vai para `validacao/`. Até lá, nenhum
preço desta tabela foi perguntado a ninguém.

## 5. Tamanho de mercado (TAM, SAM, SOM) [E]

### 5.1 Hipóteses que movem a conta

| Hipótese | Valor usado | Tipo | Como validar |
|---|---|---|---|
| Fração dos itens físicos que a IF fiscaliza por ano | 20% / **50%** / 100% | [H] | entrevista ("qual a sua taxa de amostragem em investimento pecuário?"); a taxa não é pública |
| 1 item ≈ 1 fiscalização | 1,0 | [E] | nas cooperativas, linhas = operações (Sicredi: 237.387 linhas e 237.387 operações) [D] |
| Preço por fiscalização em software | preço-alvo de R$ 79 | [H] | entrevista |
| Preço por fiscalização entregue como serviço | R$ 290 | [H] | piloto |
| Exceções socioambientais por ano no Brasil (coordenada, CAR, embargo, PRODES) | 60 a 100 mil | [E] sem fonte de volume | lista do MMA e entrevistas (abaixo) |
| Preço por exceção | R$ 300 a R$ 800 | [E] | entrevista |

Sobre as exceções: a lista do MMA para o MCR
([página do MMA](https://www.gov.br/mma/pt-br/assuntos/controle-ao-desmatamento-queimadas-e-ordenamento-ambiental-territorial/controle-do-desmatamento-1/atendimento-ao-manual-de-credito-rural);
arquivo `car_lista_mcr_21092026_acima4mf_toleranc.csv`, de 21/09/2026) tem 106.024 imóveis acima de 4 módulos
fiscais no país, 6.731 em Goiás, dos quais 2.399 acima de 15 módulos [D, contado em 16/10/2026]. Imóvel listado
**não** é operação de crédito travada: a lista dá a ordem de grandeza, não o número de exceções.

### 5.2 A conta

**TAM (Brasil, por ano):**

| Camada | Conta | 20% | **50%** | 100% |
|---|---|---|---|---|
| Fiscalização assistida (software) | 525.340 × taxa × preço-alvo de R$ 79 | R$ 8,3 mi | **R$ 20,8 mi** | R$ 41,5 mi |
| Fiscalização como serviço (fase 2) | 525.340 × taxa × R$ 290 | R$ 30,5 mi | **R$ 76,2 mi** | R$ 152,3 mi |
| Exceções socioambientais (MCR 2-9) | 60 a 100 mil × R$ 300 a R$ 800 | — | **R$ 18 a 80 mi** | — |

- **TAM central: cerca de R$ 125 mi por ano** = serviço a 50% (R$ 76,2 mi) + exceções no meio da faixa (o plano
  usa R$ 48 mi; o ponto médio exato de R$ 18 a 80 mi é R$ 49 mi). Só com software e exceções: cerca de R$ 69 mi.
- Fora da conta (não prometido): microcrédito com autofiscalização (1,03 milhão de itens abaixo de R$ 20 mil),
  perdas (Proagro e seguro) e garantias para crédito privado, que não têm dado público de volume.

**SAM (cooperativas de crédito no Brasil, onde a venda começa):**

| Camada | Conta | Valor por ano |
|---|---|---|
| Fiscalização como serviço, taxa de 50% | 159.630 × 50% × R$ 290 | R$ 23,1 mi |
| Fiscalização só em software, taxa de 50% | 159.630 × 50% × preço-alvo de R$ 79 | R$ 6,3 mi |
| Exceções da carteira cooperativa | 18% × R$ 48 mi | R$ 8,6 mi |
| **SAM central** | serviço + exceções | **cerca de R$ 32 mi** (software + exceções: cerca de R$ 15 mi) |

Os 18% são a participação de Sicoob (9,3%) e Sicredi (9,0%) no valor de 2025, identificados pelo cadastrante
[D]. Com a mesma definição dos 159.630 itens (que inclui os bancos cooperativos e o terceiro sistema), seriam
cerca de 24%, e a camada de exceções subiria para cerca de R$ 11 mi. Mantemos os 18%, que são o número menor.

**SOM (36 meses):**

| Fonte de receita | Conta | Receita recorrente anual |
|---|---|---|
| 25 cooperativas do perfil ideal | 25 × 966 itens × 50% × R$ 150 (metade software, metade serviço) | R$ 1,81 mi |
| Triagem de carteira nessas 25 | 25 × cerca de 2.740 operações (299.119 ÷ 109) × R$ 8 | R$ 0,55 mi |
| 15 credenciadas com 6 fiscais | 90 licenças × R$ 590 × 12 | R$ 0,64 mi |
| Exceções socioambientais | depende de exceções por cooperativa, que não medimos | não somado |
| **SOM** | | **cerca de R$ 3,0 mi** (o plano arredonda as parcelas e escreve R$ 2,9 mi; faixa de R$ 2 a 4 mi) |

O "mix de R$ 150" é uma escolha conservadora do plano: metade ao preço-alvo de R$ 79 e metade a R$ 290 daria
R$ 184,50 por fiscalização, e a primeira linha subiria para cerca de R$ 2,2 mi (SOM de cerca de R$ 3,4 mi).
Mantemos os R$ 150 até haver preço testado.

### 5.3 Leitura honesta

- **Só com software, o mercado é de R$ 20 a 40 mi por ano** (taxa de fiscalização de 50% a 100%): um bom
  negócio, não uma tese de venture sozinho. O tamanho maior depende de (1) entregar a fiscalização como serviço,
  (2) somar as exceções socioambientais na mesma cooperativa e (3) levar o mesmo verificador ao credor privado.
- A **taxa de fiscalização** é a hipótese que mais pesa: de 20% para 100%, a conta multiplica por 5. Ela não é
  pública e só sai das entrevistas.
- A **camada de exceções** só vale se o módulo MCR 2-9 existir. Sem ele, o TAM central cai para cerca de R$ 76
  mi (serviço) ou R$ 21 mi (software), e os R$ 490 por exceção ficam como hipótese de produto.

## 6. O que ainda não sabemos

| Pergunta | Por que importa | Como e quando vamos medir |
|---|---|---|
| Quanto custa hoje uma visita de fiscalização em GO? | âncora real de preço (hoje usamos o piso de MS) | entrevistas (L10), 16 a 22/10/2026 |
| Quantas fiscalizações um fiscal faz por mês? | licença de credenciada e economia do cliente | idem |
| Que fração dos itens físicos a IF fiscaliza? | multiplica o mercado por até 5 | idem |
| Que preço a cooperativa aceita? | todos os preços desta página são preço-alvo | pergunta de preço nas entrevistas, quando houver |
| Quantas exceções socioambientais por cooperativa por ano? | camada de exceções do SAM e do SOM | lista do MMA cruzada com entrevistas, para a final |

## 7. Como conferir

**Fiscal-GO (no repositório).** Na raiz: `scripts/py.sh scripts/dados_sicor.py`, `scripts/py.sh
scripts/dados_ibge.py` e `scripts/py.sh bench/fiscal_go/build.py` (data card em
[`bench/fiscal_go/README.md`](../../bench/fiscal_go/README.md)). As contas da seção 2 usam as colunas
`eh_pecuaria_bovina`, `eh_compra_gado`, `compra_gado_tipo`, `acima_300ha`, `exige_sensoriamento_remoto` e
`valor_rs` de `fiscal_go_2026.parquet`.

**Sicor 2025 (seção 1).** Os agregados de 08/10/2026 ainda estão fora do repositório, na pasta de negócio da
equipe. Para refazer do zero, com rede e em streaming (cerca de 65 MB transferidos, nada gravado em disco):

```bash
B=https://www.bcb.gov.br/htms/sicor
curl -s $B/Empreendimento.csv | iconv -f latin1 -t utf-8 > emp_utf8.csv
curl -s $B/DadosBrutos/SICOR_OPERACAO_BASICA_ESTADO_2025.gz | gunzip | awk -f por_if.awk emp_utf8.csv - > por_if.tsv
```

`por_if.awk` (o mesmo `agg3.awk` dos agregados de 08/10/2026) escreve, por instituição: CNPJ da IF, CNPJ do
cadastrante, itens, operações, valor, itens físicos de R$ 20 mil ou mais, itens em GO e itens físicos de R$ 20
mil ou mais em GO:

```awk
BEGIN{FS=";"
 F["Investimento|Pecuário(a)|AQUISIÇÃO DE ANIMAIS"]=1
 F["Investimento|Pecuário(a)|SERVIÇOS PROFISSIONAIS/TÉCNICOS"]=1
 F["Custeio|Pecuário(a)|AQUISIÇÃO E MANUTENÇÃO DE ANIMAIS"]=1
 F["Custeio|Pecuário(a)|BOVINOCULTURA"]=1
 F["Investimento|Agrícola|MÁQUINAS, EQUIPAMENTOS, MATERIAIS E UTENSÍLIOS"]=1
 F["Investimento|Pecuário(a)|MÁQUINAS, EQUIPAMENTOS, MATERIAIS E UTENSÍLIOS"]=1
}
FNR==NR{ if(FNR>1){c=$1; gsub(/"/,"",c); f=$4; a=$5; m=$6; gsub(/"/,"",f); gsub(/"/,"",a); gsub(/"/,"",m);
         k=f"|"a"|"m; if(k in F) fis[c]=1} next }
FNR==1{next}
{
  if1=$3; cad=$43; val=$28+0
  sys[if1]=cad
  n[if1]++; v[if1]+=val
  if($1!=last[if1]){ops[if1]++; last[if1]=$1}
  if(($13 in fis) && val>=20000) nf[if1]++
  if($10=="GO"){ngo[if1]++; if(($13 in fis) && val>=20000) nfgo[if1]++}
}
END{ for(i in n) printf "%s\t%s\t%d\t%d\t%.0f\t%d\t%d\t%d\n", i, sys[i], n[i], ops[i], v[i], nf[i], ngo[i], nfgo[i] }
```

Definições usadas nas tabelas:

- **Item físico:** empreendimento das seis categorias acima (aquisição de animais; serviços técnicos pecuários,
  em que o produto mais comum é "terraços, porteiras, mata-burros, currais, cochos, cercas"; custeio de aquisição
  e manutenção de animais; custeio de bovinocultura; máquinas e equipamentos agrícolas e pecuários).
- **Sistemas cooperativos:** linhas cujo CNPJ do cadastrante **ou** da IF é o do banco do sistema (Sicoob
  02038232, Sicredi 01181521, terceiro sistema 01401771). Assim se reproduzem os 159.630 itens do Brasil e os 3.743
  de GO. Pelo cadastrante sozinho, seriam 128.056 e 2.636: a diferença são as operações dos próprios bancos
  cooperativos.
- **Banco do Brasil:** CNPJ da IF 00000000.
- **Singular:** CNPJ da IF diferente do banco do sistema, com cadastrante de um dos três sistemas.

Conferências desta versão (16/10/2026, sobre os agregados de 08/10/2026): 525.340 itens físicos de R$ 20 mil ou
mais, 159.630 nas cooperativas, 221.197 no BB, 34.890 em GO, 335 singulares, 109 com 300 ou mais itens
(105.346), 1.556.243 itens físicos em todas as faixas, 300.921 compras de bovinos e 237.387 linhas e operações do
sistema Sicredi: **todos iguais** ao plano de 08/10/2026. O valor das cercas e currais é R$ 5,065 bi (o plano
escreve 5,06; aqui, arredondado, 5,07). O p90 de itens por singular (1.114 no plano) varia de 1.114 a 1.121
conforme o método de quantil, por isso aparece como "cerca de 1,1 mil".

Licença: o Fiscal-GO, derivado do Sicor, é publicado sob a ODbL 1.0
([`bench/fiscal_go/LICENSE`](../../bench/fiscal_go/LICENSE)); se os agregados de mercado entrarem no repositório,
seguem a mesma licença. Os dados do IBGE pedem citação da fonte ([`THIRD_PARTY.md`](../../THIRD_PARTY.md)).

## 8. Custo por fiscalização e margem [E]

O que o pitch, o BMC e o Q&A dizem sobre custo e margem, com a conta do plano de negócio da equipe (versão de
08/10/2026, que fica fora do repositório). **Medido** é só o consumo do LLM na gravação da demo de 09/10/2026
(tokens e energia: chaves `custo.*` de [`numeros.md`](numeros.md), do trace em
`eval/reports/2026-10-09_custo_demo.json`). O resto é estimativa até o piloto.

**Custo de tecnologia por fiscalização** (premissas de uma fiscalização real [E]: cerca de 30 turnos, 15 min de
áudio, 1 vídeo de curral de 40 a 60 s e cerca de 20 fotos; a demo é mais curta):

| Item | Local (GPU própria, padrão do produto) | Nuvem |
|---|---|---|
| LLM | energia de centavos + amortização da máquina de R$ 0,20 a R$ 1,40 (R$ 15–20 mil em 36 meses, 400 a 2.000 fiscalizações por mês) | de R$ 0,20 a R$ 3,60 conforme o modelo (preços públicos consultados em 08/10/2026) |
| Transcrição de voz | R$ 0 (faster-whisper local) | cerca de R$ 0,50 (15 min a US$ 0,006 por minuto, [AWS Transcribe](https://aws.amazon.com/transcribe/pricing/)) |
| Visão (contagem e fotos) | centavos (CPU) | R$ 0,10 a R$ 0,50 |
| Satélite, Sicor, IBGE | R$ 0 (dados públicos) | R$ 0 |
| Guarda da evidência por 5 anos (cerca de 150 MB) | R$ 0,25 a R$ 1,50 (a conferir na calculadora da AWS, região sa-east-1) | idem |
| **Total de tecnologia** | **cerca de R$ 0,50 a R$ 3** | **cerca de R$ 1 a R$ 6** |

A inferência fica abaixo de 5% do preço-alvo em qualquer cenário; o custo que decide a margem é o humano.

**Margem bruta por produto** (preços-alvo da seção 4; nenhum testado):

| Produto | Custo variável estimado | Margem bruta estimada |
|---|---|---|
| Fiscalização assistida (preço-alvo de R$ 79; a fiscal da IF ou da credenciada assina) | tecnologia R$ 1–6 + revisão amostral nossa (10% dos casos × 10 min × R$ 125/h ≈ R$ 2) + suporte R$ 3–6 = R$ 6–14 | 82% a 92% |
| Licença de credenciada (R$ 590 por fiscal por mês, 15 fiscalizações) | 15 × R$ 1–6 + suporte R$ 40 = R$ 55–130 | 78% a 91% |
| Exceção socioambiental (R$ 490; só se o módulo 2-9 existir) | R$ 15–30 | 94% a 97% |
| Fiscalização como serviço (R$ 290) | revisão e assinatura por agrônomo da rede (20 min × R$ 125/h ≈ R$ 42) + coordenação R$ 10 + tecnologia R$ 5 + visita presencial em 15% dos casos × R$ 450 [H] ≈ R$ 68 + ART rateada ≈ R$ 2 = cerca de R$ 127 | cerca de 56% |
| Mix do ano 2 (60% software e licença, 25% serviço, 15% exceções) | | cerca de 80% |

Depois da margem bruta entram os impostos sobre o faturamento e a taxa de meio de pagamento, que dependem do regime
tributário ainda não escolhido. CAC (R$ 15–30 mil por cooperativa, R$ 2–5 mil por credenciada) e payback (4 a 7
meses) também são estimativas do plano: não houve venda nem piloto até 16/10/2026.
