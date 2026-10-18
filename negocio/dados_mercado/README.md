# Dados de mercado do Laudo Vivo (Sicor/BCB, 2025)

Calculado a partir dos microdados públicos do Sicor 2025. Os arquivos aqui são **agregados**: não há CPF, nome de
produtor nem coordenada. O único identificador é o CNPJ-base de instituições financeiras, que é dado
institucional público.

## Fonte

- `SICOR_OPERACAO_BASICA_ESTADO_2025.gz` (64.720.611 bytes, Last-Modified 07/10/2026):
  https://www.bcb.gov.br/htms/sicor/DadosBrutos/SICOR_OPERACAO_BASICA_ESTADO_2025.gz
- Tabela de empreendimentos (latin1, convertida para UTF-8): https://www.bcb.gov.br/htms/sicor/Empreendimento.csv
- Processamento em *streaming* (`curl | gunzip | awk`), sem gravar o arquivo bruto em disco.

## Como reproduzir

```bash
B=https://www.bcb.gov.br/htms/sicor
curl -s $B/Empreendimento.csv | iconv -f latin1 -t utf-8 > emp_utf8.csv
# categoria de empreendimento e sistema cooperativo
curl -s $B/DadosBrutos/SICOR_OPERACAO_BASICA_ESTADO_2025.gz | gunzip \
  | awk -f agg.awk emp_utf8.csv - > sicor2025_por_categoria_e_sistema.tsv
# faixas de valor, empreendimento e GO (uma saída, separada pelo tipo de linha)
curl -s $B/DadosBrutos/SICOR_OPERACAO_BASICA_ESTADO_2025.gz | gunzip | awk -f agg2.awk emp_utf8.csv - > tmp.tsv
grep '^COD' tmp.tsv > sicor2025_por_empreendimento.tsv
grep -v '^COD' tmp.tsv > sicor2025_faixas_e_GO.tsv
# instituição financeira
curl -s $B/DadosBrutos/SICOR_OPERACAO_BASICA_ESTADO_2025.gz | gunzip \
  | awk -f agg3.awk emp_utf8.csv - > sicor2025_por_instituicao.tsv
```

Tipos de linha: `TOTAL_LINHAS`, `CAT` e `SYS` em `sicor2025_por_categoria_e_sistema.tsv`; `BKT` (faixa de
valor), `SB` (sistema × faixa) e `GO` em `sicor2025_faixas_e_GO.tsv`; `COD` (código de empreendimento) em
`sicor2025_por_empreendimento.tsv`.

Colunas de `sicor2025_por_instituicao.tsv`: `CNPJ_IF`, `CD_CNPJ_CADASTRANTE` (o banco do sistema cooperativo,
quando houver), linhas (itens financiados), operações (`REF_BACEN` distintas), valor (R$), itens físicos
≥ R$ 20 mil, linhas em GO, itens físicos ≥ R$ 20 mil em GO.

## Definições

- **Item (linha)**: uma linha do arquivo = um empreendimento financiado dentro de uma operação. Nas cooperativas,
  linha ≈ operação (Sicredi: 237.387 linhas e 237.387 operações).
- **Item físico**: empreendimento cuja aplicação é um bem físico que a imagem de 10 m não prova: investimento em
  aquisição de animais; investimento pecuário em "serviços profissionais/técnicos" (o produto mais frequente é
  "Terraços, porteiras, mata-burros, currais, cochos, cercas"); custeio de aquisição e manutenção de animais;
  custeio de bovinocultura; máquinas, equipamentos e utensílios (agrícolas e pecuários).
- **Corte de R$ 20 mil**: separa o microcrédito (dominado pelo BNB/Pronaf B), em que uma fiscalização paga por
  unidade não fecha a conta, das operações em que um preço de R$ 50 a R$ 300 é menos de 1,5% do crédito.
- **Sistemas cooperativos**: identificados pelo `CD_CNPJ_CADASTRANTE` (Sicoob = 02038232; Sicredi = 01181521;
  terceiro sistema = 01401771, inferido como Cresol porque a Cresol Goiás usa esse cadastrante). "Singular" =
  `CNPJ_IF` diferente do banco do sistema.

## Resultados principais (2025, Brasil)

| Recorte | Número |
|---|---|
| Operações | 1.830.128 (R$ 361,2 bi) |
| Itens (linhas) | 2.456.396 |
| ... do BNB (microcrédito, maioria abaixo de R$ 20 mil) | 1.341.598 (55% das linhas; R$ 23,3 bi) |
| Itens físicos (todas as faixas) | 1.556.243 (63% das linhas; R$ 123,1 bi) |
| **Itens físicos ≥ R$ 20 mil** | **525.340 (R$ 115,8 bi)** |
| ... Banco do Brasil | 221.197 (42%) |
| ... sistemas cooperativos (Sicoob, Sicredi, Cresol) | 159.630 (30%) |
| Singulares de cooperativa com crédito rural em 2025 | 335 |
| Operações por singular (mediana; p75; p90) | 298; 1.428; 3.223 |
| Itens físicos ≥ R$ 20 mil por singular (mediana; p75; p90) | 156; 477; 1.114 |
| Singulares com ≥ 300 itens físicos ≥ R$ 20 mil | 109 (somam 105.346 itens, 82% do total das singulares) |
| Singulares com ≥ 500 itens físicos ≥ R$ 20 mil | 78 |

Compra de bovinos (investimento): 300.921 linhas e R$ 15,52 bi. Benfeitorias do tipo cercas, currais, cochos e
porteiras: 223.577 linhas (pecuário + agrícola) e R$ 5,06 bi.

## Resultados (2025, Goiás)

| Recorte | Número |
|---|---|
| Itens (linhas) | 52.080 |
| Itens físicos ≥ R$ 20 mil | 34.890 (67% das linhas) |
| ... Banco do Brasil | 26.951 (77%) |
| ... cooperativas (três sistemas) | 3.743 (10,7%) |
| ... Bradesco / Caixa / outras | 2.315 / 692 / 1.184 |
| Singulares com ao menos uma operação em GO | 74 |
| Singulares com ≥ 100 itens em GO | 16 (3.116 itens) |

Maiores singulares por itens em GO em 2025 (nome pelo CNPJ, consulta pública em out/2026): Sicoob Credi-Rural
(Rio Verde) 675; Cresol Goiás (Orizona) 335; Sicredi Planalto Central (Cristalina) 229; Sicoob Credicitrus
(Bebedouro/SP) 202; Sicredi Cerrado GO (Goiânia) 187; Sicoob Centro-Sul (Morrinhos) 173; Sicoob Agrorural
(Quirinópolis) 161; Sicredi Celeiro Centro Oeste (São Gabriel do Oeste/MS) 154; Sicoob Cerrado (Piracanjuba)
145; Sicoob Secovicred (Goiânia) 136; Sicoob do Vale (Rubiataba) 133; Sicoob Unicentro BR (Goiânia) 129.

## Notas de método

- Um ano só (2025). O recorte de Goiás em 2026 (jan–set) está no bench do produto,
  [`../../laudo-vivo/bench/fiscal_go/`](../../laudo-vivo/bench/fiscal_go/README.md), e em
  [`../../laudo-vivo/docs/entregaveis/mercado.md`](../../laudo-vivo/docs/entregaveis/mercado.md), seção 2.
- "Item físico" é uma classificação nossa por modalidade; parte das linhas de "serviços" é residência rural, poço
  ou barragem.
- A taxa de fiscalização (amostragem) que cada IF aplica **não é pública**; é a principal hipótese do
  dimensionamento de mercado.
- Nomes de cooperativas vêm da consulta pública de CNPJ (publica.cnpj.ws) e devem ser conferidos antes de
  qualquer abordagem.
