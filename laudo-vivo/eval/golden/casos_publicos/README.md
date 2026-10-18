# Casos públicos (split separado)

Seis cenários sintéticos que reproduzem o **mecanismo** de casos noticiados ou de regras públicas: a GTA é
necessária, mas não suficiente. Não entram no dev nem no test do golden principal (`../casos/SPLIT.yaml`,
congelado em 16/10/2026), não calibram limiar e não medem frequência.

| Caso | Mecanismo | Inspiração (fonte no `caso.yaml`) | Item normativo | Esperado no laudo (modo determinístico) |
|---|---|---|---|---|
| PUB-0001 | uma NF-e e 4 GTAs coerentes (a nota cita a GTA da carga 1 no grupo ZF); 5 de 160 animais no curral | Pains (MG): 1.553 financiadas, 47 achadas (CompreRural, 09/01/2026) | MCR 2-7-2-a-I, 2-5-10; `OP-bovinos-contagem-tolerancia` | quantidade **divergente**; NF-e e GTA verificadas |
| PUB-0002 | o grupo ZF da NF-e cita uma GTA que não está entre as apresentadas; fiscalização documental (sem vídeo) | Operação Boi de Papel (CompreRural, 08/03/2024; R$ 94 mi é o crédito concedido) | NT 2024.003 v1.03 grupo ZF; `OP-bovinos-gta` | GTA **pendente** (`documento:gta:nfe_guia`: apresente a GTA citada); quantidade pendente. Pendência, não acusação: o fiscal pode só não ter enviado a GTA citada |
| PUB-0003 | origem da GTA em outro produtor e outro município que o vendedor da NF-e | GTA com origem falsa em Orizona/Vianópolis (CompreRural, 17/09/2026; Mais Goiás) | Manual SDA, item 11; `OP-bovinos-gta` | GTA **pendente** (incoerência vai para o humano, nunca acusação) |
| PUB-0004 | a mesma NF-e e a mesma GTA já em laudo selado de **outra operação** | regra 10ZF04-20 da NT 2024.003 v1.03 (rejeição 838, "Guia de Trânsito já utilizada") | MCR 2-7-6-b e 7-d (pecuária pelo item 9); NT 2024.003 ZF04-20 | NF-e e GTA **divergentes** (`documento:*:reuso`); contagem verificada |
| PUB-0005 | GTA com destino em outro estabelecimento do mesmo município | **cenário construído** pela equipe (`natureza: cenario_construido`), sem notícia de origem; só a regra do destino vem do Manual SDA | Manual SDA, item 12; `OP-bovinos-gta` | GTA **divergente** (`gta_destino`) |
| PUB-0006 | custeio de engorda: 120 na NF-e e nas GTAs, 100 financiadas, 30 contadas | gado "fantasma" em confinamento nos EUA: 89.522 declaradas em dez/2022, 10.559 achadas (WLJ, 19/05/2023) | `OP-perfil-custeio-animais` (MCR 2-7-1-c) | quantidade **divergente**; lotação e método do perfil verificados |

**Uma guia por NF-e.** O leiaute da NT 2024.003 (v1.03 e v1.10) admite um grupo `agropecuario` (0-1) com
uma `guiaTransito` (1-1). Em GO, a regra ZF05-10 exige a GTA na NF-e de NCM 0102 (tabela 4.1: 01/10/2025;
regras de validação em produção desde 01/03/2026), então a NF-e real de compra de gado traz o grupo com uma
guia; numa compra em várias cargas com uma NF-e, as outras GTAs não aparecem no grupo e isso não muda nenhum
status.

**PUB-0005 não vem de notícia (correção de 16/10/2026, gerador 0.2.1).** Até a versão 0.2.0 o caso citava
a notícia de Pains (MG) como inspiração. A notícia relata gado financiado ausente nas propriedades
vistoriadas; não descreve GTA com destino em outro imóvel. O mecanismo é construção da equipe a partir da regra
de destino da GTA, e o `caso.yaml` agora diz isso (`inspiracao.natureza: cenario_construido`, fonte = Manual
SDA). Os outros cinco casos citam a fonte do próprio mecanismo. O PUB-0005 fica **sem data de acesso**
(`acesso: null` e `acesso_nota`): a regra do destino vem de `src/laudo/docs_fiscais/fontes.py`
(`MAPA-SDA-BOV-item12`), que registra a URL do manual sem data, e o manual não foi relido em 16/10/2026 (a
página só abre o cabeçalho sem script e a rede desta máquina recusou o download); pôr a data de hoje seria
afirmar um acesso que não houve.

**Dados 100% sintéticos.** Produtor, vendedor, fazendas e estabelecimentos são marcadores (`TESTE PUB NN`,
CPF 000.000.7xx, CNPJ 99.999.999/07xx, códigos `TESTE-<IBGE>-NNNN`); NF-e de homologação assinada por uma AC
de teste; GTAs com `sintetico: true`. Os municípios usados **não** são os das notícias: nenhum caso aponta
para pessoa ou imóvel real. A inspiração cita só a fonte pública, sem nome de pessoa.

## Como gerar e rodar

```bash
scripts/py.sh eval/golden/gerador/casos_publicos.py --gerar    # regrava este diretório e dev_custeio/
scripts/py.sh eval/golden/gerador/casos_publicos.py --rodar    # condutor sem LLM; sai 1 se algum diferir
scripts/py.sh eval/golden/gerador/casos_publicos.py --rodar --custeio   # os 4 de dev do perfil custeio
scripts/py.sh -m pytest tests/unit/test_casos_publicos.py -q
```

`SPLIT.yaml` registra o sha256 de cada arquivo e o `sha256_conteudo` do conjunto; o teste regera os casos e
confere byte a byte. A consulta ao índice de documentos de laudos selados é a do produto: o executor preenche
`indice_documentos` (`<dir_dados>/indices/documentos.jsonl`) + `operacao_ref` = ref. Bacen em
`conciliar_nfe`/`conciliar_gta` (`laudo.agent.indice`); o runner só fixa o arquivo quando o índice é
compartilhado entre execuções. No PUB-0004, um laudo selado sintético de outra operação (`pre_indice`)
registra os documentos antes. As ferramentas só leem o índice; o registro é o da selagem
(`laudo.agent.indice.registrar_na_selagem` no produto; `docs_fiscais.indice.registrar_fiscalizacao`, com a
mesma seleção de documentos, quando o runner simula a selagem).

## `dev_custeio/`

Os 4 casos de desenvolvimento do perfil "custeio de aquisição e manutenção de animais" (rulebook mcr-2-7
0.4.0): CUS-0001 válido, CUS-0002 contagem abaixo, CUS-0003 uma GTA para outro estabelecimento, CUS-0004 só
manutenção com lotação de 5 cab/ha (ponto de atenção não bloqueante). **Não são casos públicos**: ficam neste
diretório porque a frente B só escreve aqui e em `gerador/`; a área de Avaliação decide se migram para
`eval/golden/`. SPLIT.yaml próprio (split `dev_custeio`), conferido byte a byte por
`tests/unit/test_regras_custeio.py`.

**Versionado como split de dev (decisão de 16/10/2026, gerador 0.2.1).** O `SPLIT.yaml` diz `split:
dev_custeio` e `papel: dev`: os 4 casos servem para desenvolver e ajustar o perfil e podem ser regerados.
Não têm split de teste, então nenhum número deles vai para slide. Não entram em `eval/golden/casos/` porque o
split de lá está congelado desde 16/10/2026 (`sha256_split`); acrescentar casos mudaria o hash congelado. Um
teste do perfil de custeio, se houver, será um conjunto novo, escrito e congelado antes de rodar.

## O que não provam

Frequência de desvio, fraude ou irregularidade de alguém. São testes do mecanismo de conferência, como o resto
do golden set. O caso estrangeiro (PUB-0006) só ilustra o mecanismo; nada diz do crédito rural brasileiro.
