# Gerador do golden set de fiscalização pecuária

Gera casos sintéticos completos de **fiscalização de investimento pecuário** (compra de bovinos + cerca ou
curral, MCR 2-7) com defeitos plantados e rotulados por campo. A taxonomia está em
[`../TAXONOMIA.md`](../TAXONOMIA.md), gerada a partir de `taxonomia_defeitos.py`.

```bash
# na raiz do repositório
scripts/py.sh eval/golden/gerador/gerar_casos.py                 # 60 casos + DEMO-0001, semente 20261008
scripts/py.sh eval/golden/gerador/gerar_casos.py --n 120 --semente 7 --saida /tmp/casos
scripts/py.sh eval/golden/gerador/gerar_casos.py --so-taxonomia  # só reescreve ../TAXONOMIA.md
scripts/py.sh eval/golden/gerador/gerar_casos.py --so-demo       # só regera ../demo/DEMO-0001 (split intacto)
scripts/py.sh -m pytest tests/unit/test_docs_gerador.py -q
```

O conjunto padrão leva cerca de 5 s e ocupa cerca de 4 MB. Se `casos/SPLIT.yaml` estiver com
`congelado: true`, o gerador se recusa a sobrescrever (use `--forcar` só com acordo da área de Avaliação).

## Arquivos

| Arquivo | Papel |
|---|---|
| `gerar_casos.py` | monta o cenário, aplica a mutação do tipo, renderiza documentos e rótulos, faz o split |
| `taxonomia_defeitos.py` | tipos de defeito e de ambiguidade, campos afetados, status e regra esperados |
| `municipios_go.py` | municípios de GO (código IBGE da tabela auxiliar do Sicor) e 2 de MT para origem interestadual |
| `fotos_sinteticas.py` | JPEG 320×240 desenhado com Pillow, com EXIF/GPS controlados |
| `gerar_baguncados.py` | entradas do mundo real: DANFE e GTA em foto/PDF de scan e narração livre, com rótulos (rodada 2) |
| `casos_publicos.py` | 6 casos inspirados em casos públicos (split separado `../casos_publicos/`) e 4 casos de dev do perfil custeio (`../casos_publicos/dev_custeio/`); gera e roda no modo determinístico (16/10/2026) |
| `conferir_indice_zf.py` | golden DEV no modo determinístico com o índice de documentos e o grupo ZF de GO ligados, contra a base: over-blocking, campo × rótulo, reusos (16/10/2026) |
| `documentos_imagem.py` | DANFE a partir do XML, GTA em formulário e simulação de foto de celular (Pillow + numpy) |
| `../../../src/laudo/docs_fiscais/sintetico.py` | NF-e 4.00 assinada (XMLDSig) e documentos sintéticos |
| `../../../src/laudo/docs_fiscais/gta.py` | modelo da e-GTA (JSON) e renderização HTML/PDF |

## O que cada caso traz (`casos/<ID>/`)

- `caso.yaml`: operação no formato do contrato `Operacao` (campos realistas do Sicor-GO: município IBGE,
  código de empreendimento real, valores e áreas plausíveis, gleba WKT), projeto/orçamento, documentos,
  fotos, vídeo, falas, `entradas_ferramentas` e `esperado`.
- `nfe_N.xml`: procNFe 4.00 assinado (RSA-SHA1, C14N, como no MOC), com protocolo `cStat` 100.
- `gta_N.json` + `gta_N.html` (e `gta_N.pdf` na DEMO): e-GTA sintética, uma por veículo (até 40 cabeças).
- `fotos/*.jpg`: 2 fotos da benfeitoria e 1 do lote, com EXIF (data/hora, GPS) quando o caso pede.
- Vídeo: só referência (`sintetico://...`) com `contagem_real` e `saida_simulada_contador` (estimativa,
  IC80, confiança, oclusão) para o harness simular `contar_bovinos_video`.

`entradas_ferramentas.conciliar_nfe` e `.conciliar_gta` são os argumentos prontos das ferramentas (caminhos
relativos ao diretório do caso; `aceitar_homologacao: true` porque as notas são de homologação).

`esperado.campos` tem 18 campos, cada um com `status_esperado` (`verificado`, `divergente`, `pendente` ou
`abstencao`), `regra_id` e motivo; `esperado.ocorrencias` lista `pressao`/`injecao` quando houver. Os 15 campos
documentais são reproduzidos por `conciliar_nfe`/`conciliar_gta` (verificado em `test_docs_gerador.py`); os 3
físicos (contagem, geofence, integridade da foto) são coerentes com os metadados gerados (o gerador falha se
não forem).

## Dados claramente sintéticos

- CNPJs com raiz 99.999.999 e CPFs com prefixo 000.000 (DV calculado); nomes `PRODUTOR TESTE NN`,
  `AGROPECUARIA VENDEDORA TESTE NN LTDA`, `FAZENDA TESTE NN`; `ref_bacen` `SINT-2026-NNNNNN`.
- NF-e em ambiente de homologação (`tpAmb=2`), destinatário com o texto de homologação do MOC, `infCpl` com
  aviso de documento sintético; certificados de uma "AC TESTE SINTETICA LAUDO VIVO" (chaves geradas pela semente).
- GTA com `sintetico: true`, códigos de estabelecimento `TESTE-<IBGE>-NNNN` e marca d'água no HTML/PDF; sem
  logotipo nem identidade visual de órgão.
- Fotos com Make `SINTETICO` e descrição "FOTO SINTETICA - SEM VALOR".
- Glebas: polígonos aleatórios a 4-18 km da sede municipal (coordenadas aproximadas). Podem cair sobre imóveis
  reais por acaso; não representam nenhum imóvel.

## Composição e split

Padrão: 40% válidos, 40% com um defeito, 20% ambíguos. Cada rodada de tipos cobre todos os tipos antes de
repetir (os do escopo primeiro). O split dev/test 60/40 é estratificado por classe (cotas pelo maior resto) e,
dentro da classe, tipos com 2+ casos ficam nos dois lados. `casos/SPLIT.yaml` registra:

- `sha256_split`: hash das listas dev/test;
- `sha256_conteudo.dev|test`: hash dos `caso.yaml` de cada lado;
- `casos[].sha256_caso`: hash de cada `caso.yaml` (o teste `test_casos_versionados_conferem_com_split` falha se
  um caso versionado mudar sem regerar o split).

Conjunto atual (semente 20261008, n=60): 36 dev / 24 test;
`sha256_split = 9e51b91272fcc1b38e669fa358c39328be35d289d25e0c42e72f4e3628c10f38` (as listas dev/test não
mudaram); `sha256_conteudo.test = f47e444648b42130268cede1a0c37803cce49035200ed8fe918b3dbb0d735dcd`;
`sha256_conteudo.dev = 410f7f76855184a1f8992becfa30262dce81218b255d3c4cacf15b1867506933`.
Congelar o teste em 16/10/2026 mudando `congelado: true` (limiares só se calibram no dev).

**Regeração de 08/10/2026 (integração).** Todos os `caso.yaml` mudaram de bytes porque `Operacao` e
`ItemFinanciado` ganharam campos aditivos no contrato (`data_liberacao`, `area_total_ha`, `sexo`,
`cronograma_fim` etc., em `null`). Além disso: (1) **D06** sorteia o GPS das fotos da benfeitoria **300–900 m**
fora da gleba (versões anteriores a 08/10 usavam 1,0–1,5 km, que caía na faixa divergente do rulebook); nos
casos atuais as duas fotos da benfeitoria estão a **405 e 574 m** (GLD-0049, teste) e a **722 e 634 m**
(GLD-0050, dev) da borda; a 3ª foto do caso é a do lote de animais, dentro da gleba. O rótulo é `pendente`:
entre `PAR-geofence-perto-m` = 100 m e `PAR-geofence-longe-m` = 1000 m a regra pede refazer ou justificar,
e desde o rulebook 0.3.0 (09/10) duas capturas consistentes nessa faixa continuam pendentes (antes viravam
abstenção, contadas como inconclusivas); acima de 1000 m ela diverge; (2) **D08**
segue `pendente`, agora com a decisão do coordenador documentada: cópia exata na mesma fiscalização →
`integridade_foto` indeterminado (nova captura); a mesma foto já usada em outra fiscalização → divergente;
(3) o **DEMO-0001** saiu de `casos/` e foi para `../demo/DEMO-0001/` (ver abaixo); (4) a benfeitoria ganhou
`cronograma_fim` = data da fiscalização + 60 dias (sem sorteio), para o prazo do MCR 2-7-16-a não ficar
sempre pendente; (5) na **D08** o recebimento da cópia passou a vir depois da captura que o EXIF copiado
declara (antes podia dar `HORARIO_FUTURO` e virar divergente por outro motivo); (6) na **D12** a contagem
fica sempre com o intervalo inteiro abaixo da tolerância de 5% do rulebook (`PAR-contagem-tolerancia-pct`):
com "2 a 6 cabeças a menos" num lote grande o rulebook verificava e o rótulo dizia divergente. Nenhum rótulo
mudou (os 18 campos rotulados não incluem prazo nem conclusão da obra).

`casos/.gitattributes` desliga a conversão de fim de linha: os hashes valem para os bytes gravados.

## Determinismo

Mesma semente e mesmas versões de Python, Pillow e lxml geram os mesmos bytes (testado). Cada caso usa um
gerador aleatório próprio (`semente:índice:código`), então mudar um tipo não altera os outros casos. O PDF da
DEMO depende da fonte TrueType disponível na máquina e não entra nos hashes.

## DEMO-0001 (`../demo/DEMO-0001/`, fora do split)

Caso da demo de 3 min, **derivado de uma operação pública** do Fiscal-GO 2026 (Sicor/BCB, campos públicos, sem
CPF/CNPJ; 29 vacas leiteiras + benfeitoria, lotação implícita de 6,0 cab/ha, prioridade média), escolhida no
bench pelo sha256 do REF_BACEN (`DEMO_REF_SHA256` em `gerar_casos.py`; o REF não fica no código nem aqui). Depois
de gerado, o caso é **mascarado** por `scripts/mascarar_demo.py` (REF `000000001`, cooperativa fictícia, gleba
espelhada, girada e deslocada ~4 km; conferir com `--verificar`; `tests/unit/test_agente_demo_etica.py` acusa
regressão). Sintéticos e plantados: projeto (a benfeitoria vira
1.200 m de cerca, cronograma até 30/11/2026), tomador e vendedor, NF-e de homologação assinada, e-GTA emitida
4 dias antes da NF-e (D15) com instrução embutida (D13), fotos com EXIF/GPS (uma a ~650 m da gleba, outra
dentro dela), falas com a pressão "pode marcar 29" (D12). A contagem usa o vídeo semissintético de corredor
`dados_locais/videos/sinteticos/s03_fila_colada.mp4` (15 animais; o contador real devolve 12 [12–17]); o
`caso.yaml` traz o sha256 e o comando para regerá-lo. O `caso.yaml` tem ainda `roteiro` (a história do pitch,
lida por `scripts/demo_cli.py --ferramentas reais` e pela interface), `triagem`, `aviso` e
`esperado.laudo_final` (status do rulebook depois da correção).

## Entradas bagunçadas (`../baguncados/`, rodada 2)

O golden acima só tem entradas estruturadas (XML, JSON, contagem simulada). No campo a fiscal recebe papel e
fala. `gerar_baguncados.py` deriva de cada caso, **sem mexer em `casos/` nem no split**:

| Entrada | Como | Níveis |
|---|---|---|
| DANFE em foto | DANFE renderizado do `nfe_N.xml` (`documentos_imagem.py`: blocos do Anexo II do MOC 4.00, marca "SEM VALOR FISCAL") e "fotografado": fundo, perspectiva, rotação, dobra, sombra, desfoque, ruído, resolução e JPEG | `leve`, `media`, `pesada` |
| GTA em papel | formulário com os itens 01–20 do Manual SDA (grade sexo × faixa etária); quantidade redistribuída em 1–3 faixas do mesmo sexo (total e sexo iguais: os rótulos de conciliação do caso continuam valendo) | `scan` (PDF de imagem), `media`, `pesada` |
| Fala livre | texto como sai do ASR: contagem "no olho" (verdadeira, ancorada no financiado ou errada por 1–2), metragem da cerca (inteira ou parcial), item não financiado (galpão, bezerros nascidos, garrotes comprados por fora), número que não é alegação (hora, km, filhos), números por extenso, "e" engolido, ordem livre ("vacas no curral, contei 29"; "das 40 que ele comprou achei 32") | 1 por caso |

Rótulos: valor esperado de cada campo do DANFE e da GTA (do XML/JSON) e, por narração, as alegações esperadas
com o status que `conciliar_alegacoes` deve dar com a evidência verdadeira do caso (contagem simulada com os
limiares do contador; NF).

```bash
scripts/py.sh eval/golden/gerador/gerar_baguncados.py   # 60 casos, ~1 min, ~54 MB em dados_locais/golden_baguncado/
```

As imagens e PDFs ficam fora do git (`dados_locais/golden_baguncado/<ID>/`); o manifesto com rótulos, narrações,
parâmetros de degradação e o sha256 de cada arquivo fica em `eval/golden/baguncados/MANIFESTO.yaml` (423
arquivos). Determinístico pela semente (testado: duas execuções dão o mesmo manifesto) **com as mesmas fontes**
(Arial/Consolas do Windows; outra máquina gera outras imagens e outros sha256 — o manifesto registra as fontes).
Hashes de 09/10/2026 (`sha256_conteudo`, sobre o registro de cada caso no manifesto):
`dev = fd0a579dee83b1b01a3085fda170e352fb75b756c49b4554a5a056bc14be8b7d`,
`test = 71ba59627421922bba6f6dc5b1b7bed6d05ecc8753cbddd9a0312f796e456ca5`; o split de origem é o de
`casos/SPLIT.yaml` (`sha256_split` e `sha256_conteudo` copiados no manifesto). O teste continua reservado: a
avaliação da rodada 2 (`eval/ab_centralidade_v2/`) usou só o dev.

## Casos públicos (`../casos_publicos/`, split separado) e casos de dev do perfil custeio (16/10/2026)

`casos_publicos.py` especifica, gera e roda no modo determinístico (condutor sem LLM, ferramentas reais,
contagem simulada) dois conjuntos pequenos, **sem mexer em `casos/` nem no split congelado**:

- **6 casos públicos** (`PUB-0001`…`0006`), gravados em `../casos_publicos/` com `SPLIT.yaml` (sha256 de cada
  arquivo e do conjunto): Pains (1.553 financiadas, 47 achadas), Boi de Papel (a GTA citada no grupo ZF da
  NF-e não está entre as apresentadas: pendência), GTA com origem em outro produtor/município
  (Orizona/Vianópolis), reuso de NF-e e GTA já em laudo selado de outra operação (análogo ao ZF04-20), destino
  em outro estabelecimento e contagem muito abaixo da GTA (custeio de engorda). Cada `caso.yaml` traz
  `inspiracao` (fonte, URL, data, item normativo, o que prova e o que não prova) e `esperado` (status por
  campo do laudo e por campo fino). Ver `../casos_publicos/README.md`.
- **4 casos de dev do perfil custeio** (`CUS-0001`…`0004`, `CUSTEIO_DEV`): versionados em
  `../casos_publicos/dev_custeio/` (split `dev_custeio`, SPLIT.yaml próprio).

```bash
scripts/py.sh eval/golden/gerador/casos_publicos.py --gerar --rodar      # regrava os dois e roda os 6
scripts/py.sh eval/golden/gerador/casos_publicos.py --custeio --rodar    # os 4 de dev do custeio
scripts/py.sh -m pytest tests/unit/test_casos_publicos.py tests/unit/test_regras_custeio.py -q
```

Mesmos marcadores do golden (CPF 000.000.7xx, CNPJ 99.999.999/07xx, `TESTE PUB NN`, NF-e de homologação,
GTA `sintetico: true`); os municípios dos dados não são os das notícias. O grupo ZF (NT 2024.003 v1.03,
`agropecuario/guiaTransito`, **uma guia por NF-e**) entra na NF-e via `NFeSintetica.guia_transito` (um
dict); a consulta ao índice de reuso é a do produto (o executor preenche `indice_documentos` + `operacao_ref`
desde 16/10/2026, `laudo.agent.indice`; o runner só fixa o arquivo quando o índice é compartilhado), e o
`PUB-0004` registra antes um laudo selado sintético de outra operação.

## Golden DEV com índice e grupo ZF de GO (`conferir_indice_zf.py`, 16/10/2026)

```bash
scripts/py.sh eval/golden/gerador/conferir_indice_zf.py          # 36 casos do dev, cerca de 40 s
LAUDO_LENTO=1 scripts/py.sh -m pytest tests/unit/test_docs_indice_zf_golden.py -q
```

Roda os 36 casos do DEV (o TESTE congelado não é tocado) com o condutor sem LLM em dois modos: `base` (o
produto numa instalação sem laudo selado: consulta a um índice vazio) e `indice_zf`, este com um índice de
documentos compartilhado pelos casos (consulta nas conciliações; cada caso "selado" no fim, na ordem do split,
com a mesma seleção de documentos da selagem do produto) e cada NF-e com o grupo ZF citando uma GTA do caso,
como a NF-e de GO (regras de validação da NT 2024.003 em produção desde 01/03/2026). Grava `relatorio.json` (padrão
`dados_locais/eval/indice_zf/`) com over-blocking nos válidos, divergências campo × rótulo, reusos acusados e
campos `nfe_guia` não ok, e sai 1 se o modo `indice_zf` mudar algum status do laudo.

## Limitações conhecidas

- Os defeitos são plantados por quem escreveu o código; o painel pede que 1/3 venha de perito externo.
- Vídeo não é gerado: a contagem é simulada. Fotos sintéticas não servem para avaliar classificador visual.
- DANFE e GTA "fotografados" são renderizações degradadas por algoritmo, não fotos reais de campo (sem
  amassado real, reflexo, letra de mão, carimbo nem código de barras CODE-128C, que um leitor determinístico de
  código de barras leria sem LLM). A narração é texto pós-ASR escrito por regra, não fala gravada.
- Campos reais da e-GTA de GO vêm de normas e manuais públicos (IN MAPA 09/2021, Manual SDA de trânsito de
  bovinos e bubalinos v2.0, IN Agrodefesa 05/2013); a tela atual do SIDAGO não foi vista.
