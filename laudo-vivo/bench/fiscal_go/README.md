# Fiscal-GO 2026 — data card

Operações de crédito rural de Goiás emitidas em 2026 (Sicor/BCB, microdados públicos), com os polígonos
públicos das glebas e sinais de **prioridade de verificação** para a fiscalização da aplicação do crédito
(MCR 2-7, Res. CMN 5.267/2025). Gerado a partir dos arquivos do BCB atualizados em 07/10/2026 (emissões de
02/01 a 30/09/2026) e da PPM 2025 do IBGE.

> **Prioridade de verificação não é indício de irregularidade.** Os sinais apontam onde a evidência de campo
> ou documental tem mais valor para a amostra da fiscalização. Nenhuma operação recebe rótulo: os sinais são só prioridade de verificação.
> A lotação implícita, por exemplo, sobe quando a área informada não é todo o pasto, quando os animais
> ficam em semiconfinamento ou quando há erro de digitação no registro.

## Arquivos

| Arquivo | Linhas | Conteúdo |
|---|---:|---|
| `fiscal_go_2026.parquet` | 28.637 | uma linha por operação (`ref_bacen`), com empreendimento decodificado, valores, áreas, lotação, sobreposição, município, rebanho municipal, prioridade e motivos |
| `itens_go_2026.parquet` | 30.518 | uma linha por item (`ref_bacen`, `nu_ordem`) — cada ordem do Sicor é um empreendimento da cédula |
| `glebas_go_2026.parquet` | 11.453 | polígonos das glebas (WKT 2D, WGS84, 7 casas) e área em ha (Albers/IBGE) |
| `rebanho_municipal_go.parquet` | 246 | rebanho bovino (PPM 2025), área territorial, densidade e compra de gado financiada em 2026 por município |
| `resumo.json` | — | números-chave, limiares e fontes (URL, Last-Modified, bytes, sha256) |
| `casos_demo.json` | 3 | casos reais para a demo (só campos públicos), escolhidos por `casos_demo.py` |
| `ndvi_demo.json` | 3 | séries de NDVI (Sentinel-2) dos casos da demo, com bytes e tempo medidos |

## Fontes, licença e atribuição

| Fonte | Uso | Atribuição |
|---|---|---|
| BCB, Sicor — `SICOR_OPERACAO_BASICA_ESTADO_2026.gz`, `SICOR_GLEBAS_WKT_2026.gz`, `Empreendimento.csv`, `CategoriaEmitente.csv`, `Programa.csv`, `FonteRecursos.csv`, `FaseCicloProducao.csv`, `SICOR_LISTA_IFS.csv` ([página](https://www.bcb.gov.br/estabilidadefinanceira/tabelas-credito-rural-proagro), [dicionário](https://www.bcb.gov.br/htms/sicor/manualDadosSicorCompleto.pdf)) | operações, itens, glebas, nomes de códigos | "Fonte: Banco Central do Brasil — Sicor (microdados do crédito rural)". A página de download dos microdados não traz licença explícita; o conjunto do Sicor no Portal de Dados Abertos do BCB ("Matriz de Dados do Crédito Rural", BCB/Derop) está sob **ODbL** (conferido em out/2026, [`THIRD_PARTY.md`](../../THIRD_PARTY.md)). Por isso os derivados desta pasta são publicados sob ODbL 1.0 ([`LICENSE`](LICENSE)). |
| IBGE — PPM, [SIDRA 3939](https://apisidra.ibge.gov.br/values/t/3939/n6/in%20n3%2052/v/105/p/last%201/c79/2670) (efetivo bovino, 2025); [malha municipal](https://servicodados.ibge.gov.br/api/v3/malhas/estados/52?intrarregiao=municipio&qualidade=maxima&formato=application/vnd.geo%2Bjson); [localidades](https://servicodados.ibge.gov.br/api/v1/localidades/estados/52/municipios) | rebanho, área e município das glebas | "Fonte: IBGE — Pesquisa da Pecuária Municipal 2025; Malha Municipal". Dados públicos com citação obrigatória; não achamos licença aberta formal para esses produtos: confirmar os termos com o IBGE antes de publicar o bench como dataset separado. |
| Copernicus Sentinel-2 L2A via Earth Search (`sentinel-2-c1-l2a`, Element 84, AWS Open Data) | só `ndvi_demo.json` | "Contém dados Copernicus Sentinel modificados (2026)". Sentinel Data Legal Notice: acesso livre, completo e aberto. |

**Licença dos dados: ODbL 1.0** ([`LICENSE`](LICENSE)). Os arquivos de dados desta pasta (`*.parquet` e
`*.json`) formam um banco de dados derivado do Sicor e são publicados sob a
[Open Database License 1.0](http://opendatacommons.org/licenses/odbl/1.0/); os valores calculados pelo projeto
(lotação, sobreposição, prioridade, motivos) ficam sob a
[Database Contents License 1.0](http://opendatacommons.org/licenses/dbcl/1.0/). Quem publicar um derivado mantém a
ODbL (compartilhamento pela mesma licença) e cita, junto com o uso:

> Fiscal-GO 2026, projeto Laudo Vivo, disponível sob a Open Database License 1.0. Fonte: Banco Central do
> Brasil — Sicor (microdados do crédito rural). Fonte: IBGE — Pesquisa da Pecuária Municipal 2025; Malha
> Municipal. Contém dados Copernicus Sentinel modificados (2026).

Os campos do IBGE (`rebanho_municipal_go.parquet` e as colunas de município, rebanho e densidade de
`fiscal_go_2026.parquet`) seguem os termos do IBGE, e a ODbL não concede sobre eles mais do que o IBGE concede. Os
scripts (`build.py`, `casos_demo.py`) são código, sob Apache-2.0 como o resto do repositório. A atribuição
Copernicus só é exigida de quem usa `ndvi_demo.json`.

**Sem PII.** Os arquivos do Sicor usados não têm CPF/CNPJ nem nome do tomador; `REF_BACEN` já vem mascarado
pelo BCB. `if_cnpj_base` e `cadastrante_cnpj_base` são a raiz (8 dígitos) do CNPJ da **instituição
financeira**. `build.py` recusa gravar coluna com nome de documento pessoal ou valor com formato de CPF/CNPJ
completo. A ligação operação → CAR existe em `SICOR_PROPRIEDADES.gz` (493 MB, traz CPF/CNPJ do
proprietário) e **não** foi usada.

## Campos principais de `fiscal_go_2026.parquet`

| Campo | Definição |
|---|---|
| `ref_bacen`, `n_itens` | operação (mascarada) e número de itens (ordens) |
| `dt_emissao`, `ano_agricola` | emissão e ano agrícola jul–jun (ex.: 05/2026 → `2025/26`) |
| `instituicao`, `segmento_if`, `sistema_cooperativo` | IF concedente (tabela de IFs do Sicor); sistema pelo cadastrante (Sicoob, Sicredi, Cresol) |
| `finalidade`, `atividade`, `modalidade`, `produto`, `variedade`, `fase_ciclo` | empreendimento do item de maior valor, decodificado |
| `modalidades`, `tipos_itens` | todas as modalidades e tipos de item (`bovinos`, `lavoura`, `pastagem`, `galpao`, `maquina`, `outro`) |
| `valor_rs`, `recurso_proprio_rs` | soma de `VL_PARC_CREDITO` e `VL_REC_PROPRIO` dos itens |
| `area_informada_ha`, `area_financiada_ha` | maior `VL_AREA_INFORMADA` / `VL_AREA_FINANC` entre os itens (os itens costumam repetir a área do imóvel) |
| `eh_pecuaria_bovina`, `eh_compra_gado`, `compra_gado_tipo` | tem item `BOVINOS`; compra = investimento "AQUISIÇÃO DE ANIMAIS" ou custeio "AQUISIÇÃO E MANUTENÇÃO DE ANIMAIS" |
| `qtd_bovinos`, `unidade_qtd_bovinos` | soma de `VL_QUANTIDADE` dos itens bovinos; `UA` (unidade animal de 450 kg) ou `cab` (cabeças) conforme a unidade do empreendimento |
| `lotacao_implicita_cab_ha` | `qtd_bovinos / area_lotacao_ha`, onde `area_lotacao_ha` = maior entre a área informada dos itens bovinos e a maior área informada da operação (conservador: há itens bovinos com área-placeholder de 0,02–0,06 ha) |
| `lotacao_area_financiada_cab_ha`, `lotacao_gleba_cab_ha` | mesma conta com `VL_AREA_FINANC` e com a área dos polígonos |
| `confinamento` | algum item bovino com fase "Engorda em confinamento" (código 60): lotação por área não se aplica |
| `valor_por_cabeca_rs`, `valor_cabeca_fora_faixa`, `faixa_valor_cabeca` | R$ financiado por cabeça/UA e se está fora de p1–p99 das operações de mesma compra e unidade |
| `tem_poligono`, `n_glebas`, `area_glebas_ha`, `lon`, `lat` | glebas públicas; área da união das glebas (Albers/IBGE); ponto representativo da maior parte |
| `municipio_ibge`, `municipio_nome`, `municipio_fonte` | município que contém o ponto representativo (malha IBGE); `poligono` ou `sicor_complemento` |
| `rebanho_municipal_cab`, `densidade_bovina_mun_cab_ha`, `razao_lotacao_densidade`, `frac_rebanho_mun` | IBGE PPM 2025 e comparação com a operação |
| `n_ops_sobrepostas`, `sobreposicao_max_frac`, `sobreposicao_ha`, `refs_sobrepostas`, `sobrepoe_outra_if`, `sobrepoe_compra_gado` | sobreposição com glebas de **outras** operações do **mesmo ano agrícola** (STRtree do shapely em Albers; par entra com ≥ 0,5 ha e ≥ 5% de uma das duas) |
| `area_total_ha`, `acima_300ha`, `exige_sensoriamento_remoto` | maior entre área informada e área dos polígonos; > 300 ha em custeio/investimento emitido a partir de 01/03/2026 → sensoriamento remoto obrigatório (MCR 2-7 item 5) |
| `prioridade_verificacao`, `prioridade_nivel`, `motivos`, `motivos_codigos`, `observacoes` | pontos, nível (`alta` ≥ 4, `media` 2–3, `baixa` 1, `sem_sinal` 0), motivos em texto e notas de método (não pontuam) |
| `fonte_versao` | `sicor@2026-10-07;ibge-ppm@2025` |

### Regras de pontuação (`src/laudo/geo/triagem.py`, limiares em `resumo.json`)

| Código | Regra | Pontos |
|---|---|---|
| `LOTACAO_ALTA` | compra de matrizes/reprodutores (investimento): > 2, > 3, > 5 cab/ha; aquisição para recria/engorda (custeio): > 3, > 5; não se aplica a confinamento | 1/2/3 e 1/2 |
| `SOBREPOSICAO_GLEBAS` | gleba coberta em ≥ 10% / ≥ 50% por outra operação da mesma safra; +1 se a outra operação é de outra IF | 1/2 (+1) |
| `AREA_DIVERGENTE` | área dos polígonos < 0,5× ou > 2× a área informada | 1 |
| `VALOR_CABECA_ATIPICO` | valor por cabeça fora de p1–p99 de operações semelhantes | 1 |
| `FRACAO_REBANHO_MUNICIPAL` | uma operação financia ≥ 5% do rebanho bovino do município | 1 |

Os limiares de lotação são parâmetros de triagem, não norma.

## Números-chave (`resumo.json`)

- **28.637 operações** (30.518 itens), **R$ 16,49 bi**; **7.499 com polígono** (11.453 glebas).
- Pecuária bovina: **19.009 operações (66,4%)**, R$ 5,93 bi (36,0% do valor).
- **Compra de gado: 13.385 operações**, R$ 4,76 bi, 4.357 com polígono:
  investimento (matrizes/reprodutores) 6.235 (R$ 1,23 bi; 3.110 com polígono);
  custeio de aquisição e manutenção 7.150 (R$ 3,53 bi; 1.247 com polígono); 4 em confinamento.
- Lotação implícita, compra por investimento (n = 6.204): p50 0,86, p75 1,67, p90 3,13, p95 4,69 cab/ha;
  **20,7% acima de 2, 10,8% acima de 3, 4,4% acima de 5**. Custeio de aquisição (n = 7.142): p50 0,84,
  p90 2,93; 7,8% acima de 3.
- Valor por cabeça (investimento): mediana R$ 4.545 por UA e R$ 8.000 por cabeça.
- Sobreposição: 388 pares na mesma safra; 657 operações com sobreposição (485 com ≥ 50%; 97 com outra IF;
  391 delas são compra de gado).
- Acima de 300 ha: 1.696; sensoriamento remoto obrigatório pelo item 5: 1.315.
- Prioridade: alta 50, média 1.386, baixa 1.175, sem sinal 26.026. Motivos: lotação 1.842,
  sobreposição 628, valor por cabeça 260, área divergente 14, fração do rebanho 1.

## Notas de método

1. **Município só para operações com polígono (7.499 de 28.637).** O município oficial da operação está em
   `SICOR_COMPLEMENTO_OPERACAO_BASICA.gz` (449 MB), que `scripts/dados_sicor.py --complemento` lê em streaming
   (guarda só `REF_BACEN, NU_ORDEM, CD_IBGE_MUNICIPIO`); este bench não usa esse arquivo. Com polígono, o
   município vem do ponto representativo da maior gleba na malha IBGE.
2. **Quantidade e área são declaradas.** `VL_QUANTIDADE` pode ser cabeças ou UA de 450 kg; a área informada
   pode não ser todo o pasto; há erros evidentes de registro (ex.: 478.708 UA em 335 ha) — que a triagem
   prioriza justamente por isso.
3. **Sobreposição legítima existe**: o mesmo produtor costuma ter custeio pecuário e investimento na mesma
   terra; o motivo diz se a outra operação é de outra IF. O Sicor público não identifica o tomador.
4. A densidade municipal usa área territorial (não área de pastagem) e o rebanho da PPM 2025.
5. Recorte só de emissões em 2026 (jan–set); sobreposição com operações de 2025 não é verificada.
6. O NDVI não está no bench inteiro (custo de rede); só nos casos da demo (`ndvi_demo.json`).

## NDVI dos casos da demo

`serie_ndvi` (Earth Search `sentinel-2-c1-l2a`, B04/B08 a 10 m + SCL, leitura janelada de COG com rasterio),
período 01/04–08/10/2026, 12 datas por caso, cache vazio:

| Caso | Área | Obs. limpas | Bytes por data | Tempo por data | Total |
|---|---:|---:|---:|---:|---:|
| normal (522802455) | 20,7 ha | 12/12 | 3,9 MB | 3,7 s | 46,8 MB, 47 s |
| lotação alta (521669903) | 5,7 ha | 11/12 | 3,2 MB | 3,1 s | 38,3 MB, 38 s |
| sobreposição (523169441) | 53,8 ha | 12/12 | 3,1 MB | 3,2 s | 37,2 MB, 40 s |

O custo por data é dominado pelo bloco de 1024×1024 px do COG (~1,3 MB por banda de 10 m; 2 blocos quando a
gleba cruza a borda do bloco). Com cache em disco (`dados_locais/ndvi_cache/<tile>/<data>/`), a segunda
consulta não transfere nada.

## Como reproduzir

```bash
# da raiz do repositório laudo-vivo
scripts/py.sh scripts/dados_sicor.py        # ~165 MB transferidos em streaming, ~60 s; grava dados_locais/sicor/
scripts/py.sh scripts/dados_ibge.py         # ~2 MB; grava dados_locais/ibge/
scripts/py.sh bench/fiscal_go/build.py      # ~15 s; grava os parquets e resumo.json
scripts/py.sh bench/fiscal_go/casos_demo.py --limpar-cache   # escolhe os casos e roda serie_ndvi (~2 min, ~120 MB)
scripts/py.sh -m pytest tests/unit -q -k geo                  # testes sem rede
export LAUDO_TESTES_REDE=1; scripts/py.sh -m pytest tests/unit/test_geo_rede.py -q   # teste com rede
```
