# Observatório de desclassificações do crédito rural — data card

Desclassificações de operações de crédito rural registradas pelo BCB no Sicor (microdados públicos), com os
atributos da operação de cada uma (UF, empreendimento, IF, ano, valor) e os denominadores (operações por ano, UF e
empreendimento, 2013 a 2026). Base da linha 3 e 4 da matriz de validação (`validacao/README.md`) e do rótulo do
retro-teste (`eval/retroteste/`). Porte em Python dos scripts `.awk` da análise exploratória original.

> **Desclassificação registrada não é ilícito.** É o registro, pela IF, de que a operação perdeu o enquadramento
> no crédito rural (MCR). O número depende de a IF fiscalizar e registrar, e a série tem quebra de registro.
> Dizer "desclassificações registradas"; nunca rotular operação real.

## Arquivos

| Arquivo | Conteúdo |
|---|---|
| `desclassificacoes.parquet` | um registro por linha (`ref_bacen`, `nu_ordem`, `dt_desc`, `cd_motivo`, `vl_desc`, `tipo_desc`) mais a operação: `ano_operacao` (arquivo anual em que ela está), `uf`, `cd_empreendimento` e `categoria` (finalidade, atividade e modalidade do 1º item, como o `agg.awk`), `if_cnpj_base`, `cadastrante_cnpj_base`, `sistema`, `valor_operacao_rs`; versão: `na_versao_atual` e `no_snapshot_memorando` (versão de 07/10/2026) |
| `base_operacoes.parquet` | denominadores: `n_operacoes` (no empreendimento do 1º item, como o `base.awk`), `n_itens` e `valor_itens_rs` por `ano_operacao`, `uf` e `cd_empreendimento` |
| `empreendimento.parquet` | tabela de domínio do BCB usada no cálculo (para recalcular sem rede) |
| `resumo.json` | números (as duas versões do arquivo), controles de honestidade, itens com animais por faixa de área e fontes (URL, Last-Modified, bytes, sha256 de cada arquivo lido) |
| `observatorio.py` | leitura em streaming: `join.awk`, `agg.awk`, `base.awk` e `area.awk` portados, e o recorte do retro-teste |
| `numeros.py` | números a partir das tabelas derivadas, sem rede (testado em `tests/unit/test_desclassificacao_observatorio.py`) |
| `build.py` | baixa em streaming, grava as tabelas e o `resumo.json` |

| awk original (análise exploratória) | Python |
|---|---|
| `join.awk`: atributos do 1º item e valor somado das operações desclassificadas | `LeitorOperacoes.juncao` |
| `agg.awk`: categoria, UF, sistema da IF, ano da operação | `enriquecer`, `sistema`, `Empreendimento.categoria` |
| `base.awk`: operações por categoria e UF (2022–2024) | `LeitorOperacoes.base` (todos os anos, por empreendimento) |
| `area.awk`: itens com animais por faixa de área (0, até 300 ha, acima de 300 ha) | `LeitorOperacoes.area` |

## Fontes, licença e versão

BCB, "Tabelas e Microdados do Crédito Rural e do Proagro" (<https://www.bcb.gov.br/estabilidadefinanceira/tabelas-credito-rural-proagro>):
`DadosBrutos/sicor_desclassificacao.gz`, `DadosBrutos/SICOR_OPERACAO_BASICA_ESTADO_<2013..2026>.gz`,
`Empreendimento.csv`, `MotivoDesclassificacao.csv` (e, para o retro-teste, `SICOR_GLEBAS_WKT_<2022..2024>.gz`
e as tabelas de domínio). Atribuição: "Fonte: Banco Central do Brasil — Sicor (microdados do crédito rural)".
URL, Last-Modified, bytes e sha256 de cada arquivo estão em `resumo.json` (`fontes`).

**Duas versões do arquivo de desclassificações.** A análise original usou a versão de 07/10/2026 (15.902
registros, último em 06/10/2026). O BCB republicou o arquivo em 14/10/2026 (Last-Modified
<!--n:desc.fonte_last_modified-->14/10/2026<!--/n-->, sha256 `<!--n:desc.fonte_sha256-->99773830eb187f7b<!--/n-->…`):
54 registros novos (48 com data de 2026, até 13/10) e 2 que saíram. Como a versão de 07/10/2026 não pode mais
ser baixada, ela está marcada registro a registro no parquet (`no_snapshot_memorando`), a partir de uma cópia
local daquela versão (`--snapshot-anterior`); as marcas são preservadas quando o parquet é refeito. O parquet
reconstrói aquela versão linha a linha (sha256 das 15.902 linhas ordenadas, sem cabeçalho:
`1b879ad93d647b3c…`, conferido em `test_parquet_reconstroi_o_arquivo_do_memorando`). O sha256 do `.gz` de
07/10/2026 não está disponível.

**Sem PII.** O Sicor público não traz CPF/CNPJ nem nome do tomador; `REF_BACEN` vem mascarado pelo BCB;
`if_cnpj_base` e `cadastrante_cnpj_base` são a raiz (8 dígitos) do CNPJ da instituição financeira.
`SICOR_PROPRIEDADES.gz` (traz CPF/CNPJ) não é baixado. O bruto não é gravado: só agregados e os atributos das
operações desclassificadas.

## Números (chaves `desc.*` de `docs/entregaveis/numeros.md`)

| | Versão de 07/10/2026 | Versão atual (14/10/2026) |
|---|---:|---:|
| Registros no arquivo | <!--n:desc.memorando.total-->15.902<!--/n--> | <!--n:desc.total-->15.954<!--/n--> |
| 2025 (ano inteiro) | <!--n:desc.memorando.ano_2025-->4.072<!--/n--> | <!--n:desc.ano_2025-->4.075<!--/n--> |
| 2026 (até) | <!--n:desc.memorando.ano_2026-->4.553<!--/n--> (<!--n:desc.memorando.ate-->06/10/2026<!--/n-->) | <!--n:desc.ano_2026-->4.599<!--/n--> (<!--n:desc.ate-->13/10/2026<!--/n-->) |
| Motivo 013 em 2025 / 2026 | <!--n:desc.memorando.motivo013_2025-->349<!--/n--> / <!--n:desc.memorando.motivo013_2026-->364<!--/n--> | <!--n:desc.motivo013_2025-->349<!--/n--> / <!--n:desc.motivo013_2026-->368<!--/n--> |
| Motivo 013 em GO, 2024–2026 | <!--n:desc.memorando.go_motivo013_2024_2026.fmt-->14,5% [11,9–17,7%] (82/564)<!--/n--> | <!--n:desc.go_motivo013_2024_2026.fmt-->14,5% [11,8–17,7%] (82/565)<!--/n--> |
| Motivo 013 no país, 2024–2026 | <!--n:desc.memorando.br_motivo013_2024_2026.fmt-->7,8% [7,4–8,3%] (961/12.293)<!--/n--> | <!--n:desc.br_motivo013_2024_2026.fmt-->7,8% [7,4–8,3%] (965/12.343)<!--/n--> |
| Custeio de aquisição em GO, 2024–2026 | <!--n:desc.memorando.go_custeio_aquisicao_2024_2026-->158<!--/n--> registros, R$ <!--n:desc.memorando.go_custeio_aquisicao_valor-->169,5 mi<!--/n--> | <!--n:desc.go_custeio_aquisicao_2024_2026-->158<!--/n--> registros, R$ <!--n:desc.go_custeio_aquisicao_valor-->169,5 mi<!--/n--> |

**Taxa por coorte (operações de 2022 a 2024 com pelo menos um registro, IC de Wilson):**

- custeio de aquisição e manutenção de animais: <!--n:desc.taxa_custeio_aquisicao.fmt-->5,2‰ [5,0–5,4] (2.220/429.011)<!--/n-->;
- compra de animais por investimento: <!--n:desc.taxa_investimento_aquisicao.fmt-->0,6‰ [0,6–0,7] (621/988.708)<!--/n-->;
- média de todas as operações: <!--n:desc.taxa_media.fmt-->1,4‰ [1,4–1,4] (7.532/5.425.438)<!--/n-->.

O custeio de aquisição fica em <!--n:desc.razao_custeio_media-->3,7 vezes<!--/n--> a média (razão contra as demais
operações: <!--n:desc.razao_custeio_demais.valor_ic-->4,9 [4,6–5,1]<!--/n-->); a compra por investimento, abaixo
(razão contra as demais: <!--n:desc.razao_investimento_demais.valor_ic-->0,40 [0,37–0,44]<!--/n-->). Por coorte, a razão
contra a média cai de 5,8 (2022) para 3,1 (2023) e 2,9 (2024).

Na versão de 07/10/2026, a conta em **registros por mil operações** (não é proporção: uma operação pode ter
vários registros) dá, nas coortes 2022–2024: custeio de aquisição de
<!--n:desc.memorando.custeio_aquisicao_registros_por_mil_min-->4,4<!--/n--> a
<!--n:desc.memorando.custeio_aquisicao_registros_por_mil_max-->6,9<!--/n-->; investimento de
<!--n:desc.memorando.investimento_aquisicao_registros_por_mil_min-->0,6<!--/n--> a
<!--n:desc.memorando.investimento_aquisicao_registros_por_mil_max-->0,8<!--/n-->. Para citar com intervalo, use as
taxas por operação acima.

## Controles de honestidade

1. **Quebra de série.** Registros por ano: 2021 <!--n:desc.serie_2021-->498<!--/n-->, 2022
   <!--n:desc.serie_2022-->118<!--/n-->, 2023 <!--n:desc.serie_2023-->1.102<!--/n-->. O motivo 013 só aparece a
   partir de 2022; o 999 ("Outro") era <!--n:desc.pct_motivo999_2024-->64%<!--/n--> dos registros de 2024 e é
   <!--n:desc.pct_motivo999_2026-->29%<!--/n--> dos de 2026; há códigos sem descrição publicada (000 em 2017, 201 em
   2019, 014 em 2025–2026, este com 142 registros em 2026). Parte do crescimento é efeito de registro. Compara-se só
   2026 parcial com 2025 inteiro, sem multiplicadores.
2. **Participação dos animais.** Pecuária: <!--n:desc.part_pecuaria_operacoes.valor-->54,1%<!--/n--> das operações
   de 2022–2024 e <!--n:desc.part_pecuaria_registros.valor-->58,3%<!--/n--> dos registros de 2024–2026 (proporcional;
   em GO, 63% e 55%). Aquisição de animais (custeio e investimento): <!--n:desc.part_aquisicao_animais_operacoes.valor-->26,1%<!--/n-->
   das operações, <!--n:desc.part_aquisicao_animais_registros.valor-->33,6%<!--/n--> dos registros e
   <!--n:desc.part_aquisicao_animais_desclassificadas.valor-->37,7%<!--/n--> das operações desclassificadas das
   mesmas coortes: **não** é proporcional, e o excesso vem do custeio de aquisição (7,9% das operações, 29,5% das
   desclassificadas); a compra por investimento é sub-representada (18,2% contra 8,2%). Leitura correta: o
   custeio de aquisição desclassifica acima da média e a compra por investimento, abaixo; a pecuária como um
   todo não concentra as desclassificações.
3. **Censura.** A mediana entre a emissão e o registro é de 1 a 2 anos: coortes recentes ainda acumulam.
4. **Denominadores.** A operação conta no empreendimento do 1º item (como no `base.awk`); operações com vários
   itens de categorias diferentes ficam numa só.
5. **Satélite obrigatório (área.awk).** Itens com animais em GO até 300 ha: 97,3% em 2025 e 97,9% em 2026 (contando
   itens, não operações; por operação bovina, o Fiscal-GO dá 97,8% até 300 ha).

## Como reproduzir

```bash
# da raiz do repositório; ~1 GB em streaming, ~8 min, pico < 1,5 GB de RAM
scripts/py.sh -I bench/desclassificacao/build.py --trabalho <pasta fora do repositório>
scripts/py.sh -m pytest tests/unit/test_desclassificacao_observatorio.py -q
scripts/py.sh scripts/gerar_numeros.py && scripts/py.sh scripts/gerar_numeros.py --verificar
```

Sem `--snapshot-anterior`, as marcas da versão de 07/10/2026 do parquet anterior são preservadas. A pasta
`--trabalho` recebe o recorte do retro-teste (só colunas de originação) e deve ser apagada ao fim.
