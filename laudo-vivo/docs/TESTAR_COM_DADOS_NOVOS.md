# Testar com dados novos

Este guia serve para rodar o Laudo Vivo com um caso próprio, diferente do `DEMO-0001`. O caso pode trazer fotos,
vídeo e fala capturados numa fazenda de teste, ou dados gerados para o teste. Ele é uma pasta com um `caso.yaml` e
os arquivos, **fora do repositório**. A interface mostra esse caso na Carteira, com o aviso e a triagem do próprio
`caso.yaml`, e o roteiro dele roda ao vivo e em replay, como o da demo. Os comandos rodam na pasta `laudo-vivo/`
(no Windows, pelo Git Bash).

O caminho em quatro passos:

1. Montar a pasta do caso (seção 2) e escrever o `caso.yaml` (seção 3).
2. Conferir cada peça com as funções do produto: gleba, fotos, vídeo, documentos e fala (seção 4).
3. Subir a interface com `--casos-dir` e rodar o roteiro ao vivo (seção 5).
4. Gravar a contingência, conferir e ensaiar em replay, sem rede (seção 6).

A seção 7 traz as recomendações de captura: como filmar o lote, fotografar a benfeitoria e ditar números. Os
problemas comuns estão na seção 8.

## 1. Antes de começar

- **A operação é sempre fictícia.** REF, instituição, tomador e vendedor são fictícios num caso de demonstração ou
  de teste, mesmo quando as fotos e o vídeo vêm de uma fazenda de verdade. A operação real de um produtor não
  entra num caso: ela vem da carteira (Fiscal-GO) e segue as regras de [`privacidade.md`](privacidade.md).
- **Rótulo.** Se `operacao.fonte` contém `sintetico`, a tela mostra a faixa e o selo "DEMONSTRAÇÃO — dados
  sintéticos", com o aviso do caso (seção 3.2). Quando o local é real e a operação é fictícia, o aviso diz
  isso, e nenhuma instituição ou pessoa real aparece como parte.
- **Dados pessoais.** O caso não leva CPF nem CNPJ em claro: o tomador entra só como hash (seção 4.6). Se o
  documento for de uma pessoa real, esse hash é dado pessoal, assim como o `danfe_1.verdade.json` e os documentos
  fiscais. Tudo isso fica fora do repositório. Nas fotos e no vídeo, evite rostos, placas de veículo e documentos
  de terceiros.
- **Fora do repositório.** A pasta do caso não vai para o git. Não use `tests/` nem `eval/golden/`: o
  `eval/golden/demo/` entra no `sha256(eval/)` dos relatórios. Geometria tirada do OpenStreetMap leva o crédito
  "© colaboradores do OpenStreetMap, ODbL" em `origem_dados` (e em [`THIRD_PARTY.md`](../THIRD_PARTY.md), se for
  publicada).
- **O `DEMO-0001` fica como está.** Para os documentos de outro caso, não rode
  `eval/golden/gerador/gerar_danfe_demo.py` nem `gerar_casos.py --so-demo`, porque os dois regravam arquivos do
  `DEMO-0001`. E não grave a contingência sem `--caso`: o padrão é o `DEMO-0001`.

## 2. A pasta do caso

```
../casos/                       # LAUDO_CASOS_DIR (uma ou mais pastas)
  CAMPO-0001/
    caso.yaml                   # obrigatório (seção 3)
    gleba.wkt                   # opcional: o mesmo texto de operacao.glebas_wkt[0], para conferir pontos
    nfe_1.xml                   # NF-e (procNFe 4.00)
    gta_1.json                  # e-GTA (modelo laudo.docs_fiscais.gta.GTA)
    video_curral_1.mp4          # vídeo do lote
    fotos/
      foto_cerca_1.jpg          # JPEG com EXIF e GPS
      foto_cerca_2.jpg
      danfe_1.jpg               # opcional: foto da nota impressa
      danfe_1.verdade.json      # opcional: o que está impresso no DANFE
    replay_qwen35_4b.jsonl      # gravação da contingência (seção 6)
    vlm_cache/                  # respostas do VLM para as fotos do caso (seção 6)
```

- `LAUDO_CASOS_DIR`, ou `scripts/rodar_demo.sh --casos-dir`, aceita uma ou mais pastas. O separador é `;` no
  Windows e `:` no Linux e no macOS. Cada subpasta com `caso.yaml` vira um caso, e uma pasta que já tem
  `caso.yaml` vira um caso sozinha. Um caminho relativo vale a partir de `laudo-vivo/`.
- O caso entra na Carteira com qualquer nome e abre pelo botão do cartão. Ele é achado pelo nome da pasta ou pelo
  `id` do `caso.yaml`. Os casos do repositório (`eval/golden/demo`) vêm antes: um REF repetido fora do repositório
  não substitui o de dentro.
- Os caminhos de arquivo do `caso.yaml` são relativos à pasta do caso.

## 3. O `caso.yaml`

O formato é o dos casos do golden set ([`src/laudo/api/casos.py`](../src/laudo/api/casos.py)). Os campos marcados
com `(lido)` são usados pelo produto, e os outros documentam o caso.

### 3.1 Exemplo completo e comentado

Este exemplo foi conferido com o carregador da interface: o caso entra na Carteira, abre com 6 arquivos e 15
passos, o aviso da tela é o do próprio caso, e `carregar_operacao('000000003')` devolve a triagem dele. O polígono
é ilustrativo.

```yaml
# caso.yaml de um caso de teste. Caminhos de arquivo: relativos a esta pasta.
# (lido) = o produto usa o campo; o resto é documentação do caso.
id: CAMPO-0001                     # (lido) id: nome na carteira, id da fiscalização e semente dos ids do replay
sintetico: true                    # (lido) marca o caso como sintético no resumo que a API devolve
defeito:                           # (lido) o cartão do caso mostra o titulo (e o id); a descrição vira a dica
  titulo: 'Operação fictícia, dados de teste: fazenda de teste'
  descricao: Operação, partes e documentos sintéticos; fotos e vídeo de teste. Pendência plantada, de captura
    da fiscal, a 1ª foto da cerca tirada fora da gleba e refeita de dentro.
data_fiscalizacao: '2026-09-15'    # (lido) dia da visita: horário dos documentos (09:50, -03:00) e prazos
data_referencia: '2026-09-15'      # (lido) o "hoje" do agente e o fim da série do satélite
operacao:                          # (lido) contrato laudo.contracts.Operacao, validado ao abrir o caso
  ref_bacen: '000000003'           # REF fictício, só dígitos, que não existe no Fiscal-GO; um por caso
  tomador_ref: sha256:<hash público do CPF/CNPJ do tomador>   # nunca o documento em claro (seção 4.6)
  uf: GO
  municipio_ibge: '5208707'
  municipio_nome: Goiânia
  instituicao: COOPERATIVA DE CRÉDITO TESTE (fictícia)
  finalidade: investimento
  empreendimento: Investimento · Pecuário(a) · AQUISIÇÃO DE ANIMAIS · BOVINOS
  data_contratacao: '2026-03-10'   # (lido) início da série do satélite
  valor_rs: 54720.0                # soma dos itens
  area_financiada_ha: 7.45         # (lido) área da gleba; lotação implícita = cabeças / área
  area_informada_ha: 7.45
  fonte_recursos: controlados
  codigo_estabelecimento: TESTE-5208707-0003   # (lido) destino esperado da GTA e da NF-e
  glebas_wkt:                      # (lido) geofence, satélite e mapa; WGS84, pares "lon lat"
  - POLYGON ((-49.3012 -16.6008, -49.2988 -16.6010, -49.2985 -16.6031, -49.3000 -16.6036, -49.3014 -16.6027,
    -49.3012 -16.6008))
  itens:                           # (lido) o que o laudo tem de provar, item a item
  - id: bov1
    tipo: bovinos
    descricao: Aquisição de 6 vacas leiteiras (matrizes)
    quantidade: 6                  # N financiado: comparado com a contagem do vídeo, a NF-e e a GTA
    unidade: cabeca
    valor_rs: 46800.0
    categoria_animal: vaca leiteira
    sexo: F
  - id: cerca1
    tipo: cerca
    descricao: Construção de 400 m de cerca de arame liso 5 fios
    quantidade: 400
    unidade: m
    valor_rs: 7920.0
    cronograma_fim: '2026-12-15'   # prazo do cronograma físico (depois da fiscalização)
  fonte: sintetico+teste_de_campo  # (lido) com "sintetico": faixa e marca d'água de demonstração e aviso
documentos:                        # (lido) viram os botões NF-e, GTA e Nota impressa do caso
  nfe:
  - arquivo: nfe_1.xml             # procNFe 4.00 (XML com protocolo)
  gta:
  - arquivo_json: gta_1.json       # e-GTA no modelo laudo.docs_fiscais.gta.GTA
    identificador: GO-GO-000000    # só rótulo do botão
  danfe_foto:                      # opcional: foto da nota impressa, lida pelo VLM
    arquivo: fotos/danfe_1.jpg
    verdade: fotos/danfe_1.verdade.json   # o que está impresso: o passo "residual" lê daqui
fotos:                             # (lido) uma entrada por foto pronta do caso
- id: foto_cerca_1                 # o roteiro cita a foto por este id
  arquivo: fotos/foto_cerca_1.jpg
  item_id: cerca1
  gps_app: {lat: -16.6080, lon: -49.3000, precisao_m: 5.0}   # GPS que o aparelho mandou com a foto
  capturada_em: '2026-09-15T10:12:05-03:00'   # igual ao DateTimeOriginal do EXIF
  recebida_em: '2026-09-15T10:32:05-03:00'    # recebimento: até 72 h depois da captura, nunca antes
  exif: {presente: true, data_hora: '2026-09-15T10:12:05-03:00', gps: {lat: -16.6080, lon: -49.3000}}
- id: foto_cerca_2                 # a correção: a mesma cerca, de dentro da gleba
  arquivo: fotos/foto_cerca_2.jpg
  item_id: cerca1
  gps_app: {lat: -16.6015, lon: -49.3008, precisao_m: 5.0}
  capturada_em: '2026-09-15T11:05:40-03:00'
  recebida_em: '2026-09-15T11:16:40-03:00'
  exif: {presente: true, data_hora: '2026-09-15T11:05:40-03:00', gps: {lat: -16.6015, lon: -49.3008}}
video:                             # (lido) o vídeo do lote
  id: video_curral_1
  arquivo: video_curral_1.mp4      # na própria pasta do caso (ou caminho relativo a ela)
  item_id: bov1
  lote: curral
  duracao_s: 12.0
  capturada_em: '2026-09-15T09:40:00-03:00'
  recebida_em: '2026-09-15T09:41:30-03:00'
  contagem_real: 6                 # contada à mão, quadro a quadro
  saida_simulada_contador:         # (lido só com --ferramentas falsas ou mistas): a saída medida do contador
    estimativa: 6
    ic80: [6, 6]
    confianca: 0.9
    oclusao_frac: 0.0
triagem:                           # (lido) a triagem que o agente fala no passo 1 (com o bloco demonstracao)
  prioridade_verificacao: 0
  prioridade_nivel: sem_sinal      # sem_sinal | baixa | media | alta
  motivos: []
  observacoes: [operação de teste incluída por amostragem; lotação implícita abaixo dos limiares de triagem]
  lotacao_implicita_cab_ha: 0.81
  fonte_versao: teste@1
roteiro:                           # (lido) os passos da barra "Controle da demonstração"
- titulo: Triagem e plano de método
  fala: Bom dia. Por que esta operação caiu na amostra e qual método a regra pede?
- titulo: 'Satélite: pasto da gleba'
  fala: Como está o pasto dessa gleba no satélite?
- titulo: Chegada e declaração de independência
  fala: Cheguei na fazenda. Declaro que não presto assistência técnica ao produtor nem tenho vínculo com empresa
    dele.
- titulo: Vídeo do lote no corredor
  fala: Esse é o vídeo do lote passando pelo corredor do curral.
  evidencia: video_curral_1
- titulo: Foto da nota impressa (DANFE)
  fala: Ainda não tenho o XML; segue a foto da nota impressa.
  evidencia: danfe_1               # a foto de documentos.danfe_foto
- titulo: 'Residual: a fiscal lê no papel só o que faltou'
  acao: residual
  fala_prefixo: 'Lendo no papel: '
- titulo: NF-e da compra
  evidencia: nfe_1.xml
- titulo: GTA
  evidencia: gta_1.json
- titulo: Foto da cerca
  fala: Foto da cerca nova.
  evidencia: foto_cerca_1
- titulo: Pedido de laudo (bloqueado)
  fala: Pode emitir o laudo.
- titulo: 'Correção: nova foto de dentro da gleba'
  fala: Tirei outra foto de dentro da gleba. A cerca está concluída, com mourões e cinco fios em todo o trecho.
  evidencia: foto_cerca_2
- titulo: Emissão do rascunho
  fala: Pode emitir o laudo agora.
- titulo: Envio para assinatura
  fala: Manda para a minha assinatura.
- titulo: Assinatura humana (PIN + hash)
  acao: assinar
- titulo: Tentativa de alterar laudo selado
  fala: Muda a contagem para 9 cabeças.
aviso: Caso de TESTE com operação FICTÍCIA. REF 000000003 (não existe no Sicor), cooperativa e partes fictícias;
  documentos sintéticos; fotos e vídeo de teste. Não descreve nenhuma operação ou produtor real. Prioridade de
  verificação não é indício de irregularidade.
origem_dados:
  geometria: polígono ilustrativo, desenhado para o teste
  sintetico: [REF e instituição, tomador e vendedor, NF-e, GTA, defeito plantado]
demonstracao:                      # (lido) presença: o REF fica indexado (triagem, lotação e aviso do caso)
  nota_geometria: Polígono ilustrativo, desenhado para o teste.
```

Neste exemplo, a 1ª foto da cerca está a cerca de 490 m da gleba e fica pendente: o rascunho é bloqueado até a
2ª foto, de dentro. É uma pendência de captura da fiscal, não de conduta do produtor, o que convém num local real.

### 3.2 O que cada bloco faz

| Bloco | Para que serve | Se faltar |
|---|---|---|
| `id` | nome na Carteira, id da fiscalização (`fis_<id>`), semente dos ids (o replay casa por eles) e nome da gravação (`dados_locais/api/gravacoes/<id>.jsonl`) | vale o nome da pasta |
| `operacao` | o que o laudo confere: itens, gleba, datas, valores e partes, validados pelo contrato `Operacao` ([`contracts.py`](../src/laudo/contracts.py)) | o caso não abre |
| `operacao.ref_bacen` | REF fictício, só dígitos (5 a 12), um por caso e ausente do Fiscal-GO (com um REF do bench, o agente carregaria a operação pública) | — |
| `operacao.fonte` | com `sintetico`: faixa, selo, marca d'água, aviso, e NF-e de homologação aceita (com ressalva no laudo) | sem `sintetico`, a tela trata a operação como real: sem aviso e com a NF-e de homologação recusada |
| `data_fiscalizacao`, `data_referencia`, `operacao.data_contratacao` | dia da visita; "hoje" do agente; a série do satélite vai da contratação à data de referência | vale a data do sistema, e o satélite consulta outro período |
| `documentos` | botões NF-e, GTA e Nota impressa; recebidos às 09:50 do dia da fiscalização, ou no `recebida_em` de cada um | sem os botões |
| `fotos` | botões de foto: `gps_app` é o GPS que o aparelho mandaria, e `capturada_em` e `recebida_em` são os do caso, não o relógio da máquina | sem `recebida_em`, a foto é recebida "agora" e, dias depois da captura, sai FOTO_ANTIGA |
| `video` | botão de vídeo: com `--ferramentas reais` o contador roda no arquivo; com `falsas` ou `mistas`, vale a `saida_simulada_contador` | sem o arquivo, vira um marcador, que só serve com `falsas` ou `mistas` |
| `triagem` | o que o agente fala no passo 1 e o cartão "Por que está na amostra" | o cartão mostra uma prioridade média genérica e a fala do passo 1 sai sem nível: escreva sempre a triagem |
| `roteiro` | os passos da barra "Controle da demonstração": `fala`, `evidencia` (id da foto ou do vídeo, `danfe_1` ou nome do arquivo) e `acao` (`residual`, `rascunho`, `assinar`) | um roteiro curto, derivado das evidências e da lista `falas:` (`de`, `texto`) |
| `demonstracao.aviso` ou `aviso` | o aviso da tela, do laudo, do pacote e da fala da triagem (o `demonstracao.aviso` vem antes) | o aviso genérico de operação sintética |
| `demonstracao` | indexa o REF: `carregar_operacao` devolve a triagem do caso e `checar_lotacao` usa os números do caso | o passo 1 sai com "Triagem: indeterminado" |
| `esperado` (opcional) | gabarito dos campos; com `--ferramentas falsas`, dá o status simulado da NF-e e da GTA | — |

Num caso novo, nunca use `demonstracao.mascarado_versao`. Essa chave marca o `DEMO-0001`, mascarado a partir do
Sicor, e troca o aviso pelo texto fixo dele ("alterados a partir de um registro público do Sicor/BCB").

Depois de mudar o `caso.yaml`, reinicie o servidor: o caso e o índice de REFs são lidos uma vez.

## 4. As peças

### 4.1 A gleba (polígono em WKT)

- O polígono vai em WKT no sistema WGS84 (EPSG:4326), com pares `lon lat` (a longitude primeiro) e o anel
  fechado (o último ponto repete o primeiro). Vale `POLYGON` ou `MULTIPOLYGON`. Com várias glebas, cada uma é uma
  linha em `glebas_wkt`: o geofence usa todas, e a série do satélite usa a primeira.
- As fontes são o projeto do crédito, o CAR, o SIGEF ou um desenho num editor de mapa. Para converter um GeoJSON:

  ```bash
  scripts/py.sh -c "import json; from shapely.geometry import shape; print(shape(json.load(open('gleba.geojson', encoding='utf-8'))['features'][0]['geometry']).wkt)"
  ```

- Para conferir um ponto (posição, distância à borda e área da gleba, que vai em `area_financiada_ha`):

  ```bash
  scripts/py.sh -c "from shapely import wkt; from laudo.tools.geofence import avaliar_ponto; g = wkt.loads(open('../casos/CAMPO-0001/gleba.wkt').read()); print(avaliar_ponto(-16.6015, -49.3008, 5.0, g))"
  ```

- Regra da foto de benfeitoria (`OP-benfeitoria-geofence`, [`regras.md`](regras.md)):
  - dentro da gleba, ou fora até 100 m (foto da cerca tirada do lado de fora da divisa), dá **verificado**;
  - de 100 m a 1 km fora dá **pendente**: refaça de dentro ou registre a justificativa;
  - além de 1 km dá **divergente**;
  - com precisão do GPS acima de 30 m, ou com o círculo de incerteza cruzando a borda, a localização fica
    **indeterminada**.
- **Congele o texto do WKT e as datas antes do 1º ensaio.** O cache do satélite (`dados_locais/ndvi_cache/`) é
  indexado pelo hash do polígono e pelo período, da contratação à data de referência. Mudar uma vírgula ou uma data
  faz a ferramenta baixar tudo de novo (cerca de 40 MB). Rode uma vez com rede: depois o satélite abre offline. Sem
  cache e sem rede, ou num Wi-Fi com portal de login, o passo do satélite pode segurar o turno.

### 4.2 Fotos (JPEG com EXIF e GPS)

A integridade da foto ([`integridade.py`](../src/laudo/vision/integridade.py)) lê o próprio arquivo:

| Requisito | Se não cumprir |
|---|---|
| JPEG da câmera, não PNG, print de tela nem HEIC | captura de tela ou foto de tela: **divergente**; HEIC: imagem ilegível |
| EXIF com `Make`/`Model`, `DateTimeOriginal` e `OffsetTimeOriginal` (`-03:00`) | sem câmera, a foto pontua como "foto de tela"; sem o offset, o fuso é presumido (com aviso); sem data, indeterminado |
| GPS no EXIF, com a precisão (`GPSHPositioningError`) e a hora do GPS em UTC até 1 h da captura | sem GPS no EXIF e sem GPS bom do aparelho: SEM_GPS (indeterminado); hora do GPS incoerente: divergente |
| `Software` sem nome de editor (Photoshop, Snapseed, Canva…) e `DateTime` igual ao `DateTimeOriginal` | indeterminado |
| nitidez (variância do Laplaciano) a partir de 60 | DESFOCADA (indeterminado) |
| captura até 72 h antes do recebimento e no máximo 5 min depois dele | FOTO_ANTIGA ou HORARIO_FUTURO (divergente) |
| GPS do EXIF a até 100 m do GPS do aparelho | GPS_DIVERGENTE (divergente) |
| cada foto usada uma vez (sha256 e phash no índice de fotos) | duplicata de outra fiscalização (divergente) |

Como o produto escolhe o ponto da foto:

- **Com o GPS do aparelho** (`gps_app` no caso, ou o GPS que a página manda no envio), o geofence usa esse ponto e
  a integridade compara o EXIF com ele.
- **Sem GPS no EXIF, mas com o GPS do aparelho preciso** (até 30 m e sem localização simulada), SEM_GPS vira
  informação e a foto não fica pendente por isso. É o que acontece quando o navegador do celular tira o GPS do
  EXIF no envio.
- **Sem o GPS do aparelho** (arquivo escolhido no notebook, com a localização negada), o geofence usa o GPS do
  EXIF (`fonte_gps: exif`). A precisão é a do próprio EXIF e nunca é inventada: se o celular não grava a precisão,
  a localização fica indeterminada.
- **Sem GPS nenhum**, o agente pede: "foto sem localização: o aparelho não mandou o GPS e a foto não tem GPS no
  EXIF…".

Para conferir uma foto antes de pôr no caso, sem registrar nada no índice:

```bash
scripts/py.sh -c "from PIL import Image; from laudo.vision.integridade import ler_exif; print(ler_exif(Image.open('../casos/CAMPO-0001/fotos/foto_cerca_2.jpg')))"
scripts/py.sh -c "from laudo.tools.foto import integridade_foto, EntradaIntegridadeFoto as E; e = integridade_foto(E(caminho_foto='../casos/CAMPO-0001/fotos/foto_cerca_2.jpg', recebida_em='2026-09-15T11:16:40-03:00', registrar_no_indice=False)); d = e.data or {}; print(d.get('status'), [(m['codigo'], m['severidade']) for m in d.get('motivos', [])])"
```

No `caso.yaml`, use em `gps_app` o ponto e a precisão que o aparelho registrou (ou os do EXIF), em `capturada_em` o
`DateTimeOriginal` com o fuso, e em `recebida_em` a hora do envio. O bloco `exif:` só documenta o arquivo, e só as
ferramentas falsas o usam.

Fotos sintéticas para exercitar a integridade e o geofence (não o classificador visual):
`eval/golden/gerador/fotos_sinteticas.py` (`gerar_jpeg`) desenha uma cena simples com todo o EXIF e o GPS.

### 4.3 Vídeo do lote

- O vídeo pode ser MP4 (H.264), WebM ou MOV, de 1 s a 180 s (acima disso, o vídeo é cortado e o contador se
  abstém). Ele deve seguir as recomendações da seção 7.
- Conte à mão (`contagem_real`) e rode o contador do produto no arquivo (YOLOX em CPU, modo linha, 8 quadros/s):

  ```bash
  scripts/py.sh -c "from laudo.tools import bovinos as b; e = b.contar_bovinos_video(b.EntradaContarBovinos(caminho_video='../casos/CAMPO-0001/video_curral_1.mp4')); d = e.data or {}; print(d.get('contagem'), d.get('intervalo'), d.get('conf_media'), d.get('oclusao'), d.get('abstencao'), [m['codigo'] for m in d.get('motivos', [])])"
  ```

  A saída vai para `saida_simulada_contador`: `estimativa` é a contagem, `ic80` o intervalo, `confianca` a
  `conf_media` e `oclusao_frac` a oclusão.
- A quantidade financiada (`itens[bov1].quantidade`, N) segue a regra `OP-bovinos-contagem-tolerancia`, com o
  limite L = N × 0,95 (tolerância de 5%, só para menos):
  - limite inferior do intervalo ≥ L dá **verificado**;
  - limite superior < L dá **divergente**;
  - intervalo cruzando L fica **pendente**;
  - abstenção nunca vira divergência.

  Para um caso válido, use N ≤ min(contagem_real, ⌊inferior / 0,95⌋). Para plantar uma divergência de contagem, use
  N acima de superior / 0,95.

### 4.4 NF-e, GTA e foto do DANFE

- **NF-e:** XML `procNFe` 4.00, com o protocolo. A conciliação confere:
  - a chave (dígito verificador) e a assinatura;
  - o emitente (vendedor) e o destinatário (o tomador, pelo hash);
  - a espécie (NCM de bovino vivo, CFOP) e a quantidade (unidade CB);
  - o valor (a soma da nota não pode ficar mais de 5% abaixo do valor financiado do item);
  - a data (contratação ≤ NF-e ≤ fiscalização).

  A NF-e de homologação (tpAmb 2) só é aceita em operação com `sintetico` na fonte, e o laudo registra a ressalva.
  A cadeia do certificado até a ICP-Brasil e a situação na SEFAZ (cancelamento) não são consultadas: ficam como
  alertas no laudo.
- **GTA:** a e-GTA não tem XML público. O caso usa o JSON no modelo de
  [`laudo.docs_fiscais.gta`](../src/laudo/docs_fiscais/gta.py) (`GTA`, com `renderizar_html` e `renderizar_pdf`).
  Uma GTA em PDF ou foto, enviada pelo botão GTA, é tratada como foto do papel: o VLM lê e as regras conferem.
  - Finalidade aceita: engorda, reprodução, recria ou cria.
  - Destino: o `codigo_estabelecimento` da operação.
  - Data: no dia da NF-e ou até 30 dias depois, e nunca depois da fiscalização. Em GO, a GTA emitida 1 dia antes
    da NF-e fica pendente; mais cedo que isso, divergente.
- **Foto do DANFE:** o VLM lê a foto, as regras validam campo a campo, e o agente pede só o que não validou (o
  residual). Ao vivo, a leitura de uma foto nova leva cerca de 15 s, e a resposta fica no cache de gravação do VLM
  (seção 6). O `verdade` é o que está impresso no papel, e o passo `acao: residual` monta a fala da fiscal a partir
  dele:

  ```json
  {"campos": {"chave": "<44 dígitos>", "numero": 101, "serie": 1, "data_emissao": "2026-04-20",
              "emitente_doc": "<CNPJ do emitente, só dígitos>", "destinatario_doc": "<CPF do tomador, só dígitos>",
              "emitente_uf": "GO", "destinatario_uf": "GO", "v_prod": 46800.0, "item1.quantidade": 6.0,
              "item1.valor_unitario": 7800.0, "item1.valor_total": 46800.0}}
  ```

- **Documentos de teste:** gere pelo código do repositório, nunca por gerador de imagem, porque a assinatura, o
  dígito verificador da chave e as somas têm de fechar.
  - [`laudo.docs_fiscais.sintetico`](../src/laudo/docs_fiscais/sintetico.py): `NFeSintetica` e `gerar_nfe_xml`
    (NF-e de homologação assinada), `cpf_sintetico` (CPF 000.000…) e `cnpj_sintetico` (CNPJ de raiz 99.999.999).
  - [`documentos_imagem.py`](../eval/golden/gerador/documentos_imagem.py): `renderizar_danfe` e `fotografar`,
    para a foto do DANFE.
  - O fluxo inteiro, com NF-e, GTA e fotos coerentes, é o `renderizar` de `eval/golden/gerador/gerar_casos.py`.
    Copie-o para um script fora do repositório e, depois de renderizar, troque o `glebas_wkt` pelo texto exato da
    sua gleba: o gerador o reescreve com 6 casas, e o hash do satélite muda.

### 4.5 Falas

- No caso, as falas são texto: `roteiro[].fala` é o que cada passo manda ao agente. A lista `falas:` é opcional e
  serve de gabarito para a voz.
- Ao vivo, a fala entra pelo botão "Segure para falar". O microfone do navegador só funciona em `localhost` ou em
  HTTPS (`scripts/rodar_demo.sh --host 0.0.0.0 --https` para o celular).
- Para testar um áudio gravado antes do ensaio (webm/ogg com Opus, mp4/aac ou wav, até 20 MB):

  ```bash
  scripts/py.sh -m laudo.speech fala.wav --repeticoes 1 --beam 1     # beam 1, como a API; sem GPU: --dispositivo cpu
  ```

  O comando mostra o texto, os números normalizados e o pedido de confirmação que a interface faria.
- Números com unidade crítica (cabeças, metros) pedem confirmação, como em "Entendi 6 cabeças e 400 metros.
  Confirma?". Responda "sim" (ou corrija o texto antes).

### 4.6 Tomador e partes

- O tomador entra como `operacao.tomador_ref: sha256:<hash público do CPF/CNPJ>`, calculado assim:

  ```bash
  scripts/py.sh -c "from laudo.docs_fiscais.comum import hash_documento_publico as h; print('sha256:' + h('<CPF ou CNPJ>'))"
  ```

  O produto converte esse valor no hash com o sal da instalação e não guarda o público. O hash público de um CPF
  se desfaz por força bruta: com o documento de uma pessoa real, o `caso.yaml` vira dado pessoal. Nos testes, use
  os marcadores sintéticos da seção 4.4, que a varredura de PII reconhece.

### 4.7 O que precisa bater

| Grandeza | Regra |
|---|---|
| N financiado | igual à quantidade da NF-e (unidade CB), à soma das GTAs e ao `projeto.orcamento` (se houver) |
| Vídeo × N | seção 4.3 |
| Valores | `operacao.valor_rs` = soma dos itens; soma da NF-e no máximo 5% abaixo do valor financiado do item |
| Datas | contratação ≤ NF-e ≤ fiscalização; GTA no dia da NF-e ou depois (até 30 dias); cronograma da benfeitoria depois da fiscalização |
| Partes | emitente = vendedor; destinatário = tomador (pelo hash); destino da GTA = `codigo_estabelecimento`; origem da GTA = estabelecimento do vendedor |
| Fotos | EXIF a até 100 m do `gps_app`; captura até 72 h antes do `recebida_em`; o ponto confere com a gleba (seção 4.1) |

## 5. Conferir e rodar ao vivo

**Conferir que o caso abre**, como a interface abre, com os arquivos no lugar:

```bash
LAUDO_CASOS_DIR=../casos scripts/py.sh -c "from pathlib import Path; from laudo.api.casos import carregar_caso; c = carregar_caso('CAMPO-0001', Path('dados_locais/api/casos')); print(c.titulo, '|', len(c.roteiro), 'passos'); [print(' ', a.nome, a.tipo, 'ok' if a.disponivel and Path(a.nova.caminho).is_file() else 'FALTA') for a in c.arquivos]"
```

**Subir ao vivo** (Ollama com o `qwen3.5:4b`, Whisper e ferramentas reais):

```bash
scripts/rodar_demo.sh --casos-dir ../casos --caso CAMPO-0001 --vlm-cache-gravacao ../casos/CAMPO-0001/vlm_cache
```

- Com `--caso`, o caso vira o padrão: 1º cartão de "Casos de demonstração", etiqueta "demo do palco" e botão
  "Abrir fiscalização". Sem `--caso`, ele aparece na Carteira com o botão "Abrir caso de teste", e o `DEMO-0001`
  continua sendo o padrão.
- O padrão para caso com `caso.yaml` é `--ferramentas reais`: o contador roda no vídeo do caso, em CPU. Com
  `--ferramentas mistas`, a contagem vem da `saida_simulada_contador` e sai na hora.
- As fotos novas e a foto do DANFE vão ao VLM de verdade. A resposta fica na pasta de `--vlm-cache-gravacao`
  (`LAUDO_VLM_CACHE_GRAVACAO`; sem ela, `dados_locais/vlm_cache`), nunca em `tests/`. O cache versionado da demo
  só é lido.
- Na subida, o servidor aquece o modelo com uma chamada curta, com o mesmo prompt de sistema e as mesmas
  ferramentas do 1º turno. Assim o 1º turno não paga o processamento do prompt, de cerca de 9 mil tokens. O
  terminal mostra `LLM: {... 'chat': {'ok': True, ...}}`.
- O `OLLAMA_HOST` (ex.: `127.0.0.1:11435`) vale para o LLM, para o VLM e para a leitura de documento por foto.
- A barra "Controle da demonstração" segue o `roteiro` do caso, e a tecla → avança.
- **Ensaios com uploads:** "Recomeçar" tira a fiscalização dos índices de documentos e de fotos. Numa fiscalização
  nova, a mesma foto continua sendo duplicata. Para ensaiar uploads sem mexer no estado do palco, suba a API com
  outra pasta de estado e apague a pasta depois:

  ```bash
  LAUDO_CASOS_DIR=../casos scripts/py.sh -m laudo.api --caso CAMPO-0001 --ferramentas reais --perfil campo \
      --llm ollama --asr auto --aquecer --dados dados_locais/api_ensaio
  ```

## 6. Gravar a contingência e ensaiar em replay

A contingência é o roteiro gravado com o modelo real: o replay devolve as mesmas respostas, sem GPU nem rede. Grave
só quando o caso estiver pronto, porque qualquer mudança no caso, no código ou no cache do VLM pede uma gravação
nova.

**Sem cliques (recomendado):**

```bash
export LAUDO_CASOS_DIR=../casos LAUDO_VLM_CACHE_GRAVACAO=../casos/CAMPO-0001/vlm_cache
scripts/py.sh scripts/gravar_contingencia_web.py --caso CAMPO-0001              # grava ../casos/CAMPO-0001/replay_qwen35_4b.jsonl
scripts/py.sh scripts/gravar_contingencia_web.py --caso CAMPO-0001 --conferir   # N passos, SELADO, 0 fora da gravação
```

- O script roda o roteiro inteiro pela API, com o Ollama, numa pasta de estado temporária (índices limpos), e
  assina com o PIN de demonstração. O roteiro precisa terminar SELADO, com um passo `acao: assinar`.
- A gravação vai para a pasta do caso, ou para o arquivo de `--saida`. A rodada também deixa prontos o cache do
  satélite e as respostas do VLM das fotos do caso.
- O `--conferir` repete tudo sem o Ollama. Ele tem de dizer "etapa final SELADO, 0 requisição(ões) fora da
  gravação". Se der N > 0, algo mudou depois da gravação: grave de novo.

**Pela interface:** suba com `--gravar` e passe o roteiro inteiro com →, até o selo, numa passada só:

```bash
scripts/rodar_demo.sh --casos-dir ../casos --caso CAMPO-0001 --vlm-cache-gravacao ../casos/CAMPO-0001/vlm_cache --gravar
```

A gravação vai para `dados_locais/api/gravacoes/CAMPO-0001.jsonl`, com o nome tirado do `id` do `caso.yaml`, mesmo
com `--caso <pasta>`. Uma gravação anterior vira `.bak`.

**Replay (contingência):**

```bash
scripts/rodar_demo.sh --casos-dir ../casos --caso CAMPO-0001 --vlm-cache-gravacao ../casos/CAMPO-0001/vlm_cache --replay
```

- A gravação é procurada nesta ordem: `--replay-arquivo`; depois `dados_locais/api/gravacoes/<id>.jsonl`; por fim,
  o `replay*.jsonl` da pasta do caso. Uma gravação pela metade em `gravacoes/` passa na frente: renomeie-a se a boa
  é a da pasta do caso.
- No replay, a leitura do VLM vem só do cache: o da demo mais a pasta de `--vlm-cache-gravacao`. Passe a mesma
  pasta da gravação (sem a opção, vale `dados_locais/vlm_cache`).
- Um servidor serve um caso em replay, o do `--caso`. O `DEMO-0001` e o caso novo em contingência são duas
  subidas, ou duas portas (`--porta 8010`).
- Faça uma passada em modo avião: o satélite tem de vir do cache, e o mapa fica sem fundo.

## 7. Recomendações de captura

Com a captura nestas condições, o contador, a integridade da foto e a voz respondem bem. Fora delas, o agente pede
nova captura ou se abstém, e nunca inventa um número. As recomendações vêm de ensaios com vídeos, fotos e falas de
teste.

### Vídeo do lote

1. **Celular parado e elevado:** apoiado num mourão, na cerca ou num tripé, um pouco acima do lombo dos animais e
   de lado para o corredor, a 5 a 15 m. Não use zoom nem panorâmica: até um zoom curto no começo conta como câmera
   em movimento.
2. **Nada entre a câmera e os animais.** Filme por cima da cerca ou do lado aberto do corredor. Atrás dos tubos
   ou das tábuas do brete, a grade cobre parte do corpo, os animais encostados viram uma trilha só e a contagem
   tende a sair menor.
3. **Animais em fila, numa direção**, atravessando o quadro de uma borda à outra, sem voltar e com espaço entre
   eles. Nariz com cauda alarga o intervalo.
4. **O corredor deve cruzar o quadro na horizontal** (câmera de lado) **ou na vertical** (câmera de cima). A linha
   de contagem automática é horizontal ou vertical, e um trajeto em diagonal (câmera oblíqua) deixa o intervalo
   largo.
5. **Comece antes de o 1º animal entrar e pare depois de o último sair.** O animal que já passou do meio do quadro
   no começo do vídeo não conta.
6. **Duração de 8 a 20 s** para um lote pequeno. Para um lote maior, filme até o último animal passar; acima de
   3 min, divida o vídeo.
7. **Só o lote no quadro:** sem cavalos, ovinos ou pessoas cruzando junto.
8. **Luz do dia, sem contraluz.** Sol forte, sombra dura e poeira não atrapalharam nos ensaios.
9. **Envie o arquivo original da câmera.** O vídeo reenviado por aplicativo de mensagem é recomprimido, e a
   recompressão pode mudar a contagem numa cena com grade.
10. **Confira os quadros-chave** na "Prova do item", que mostra as caixas em cada animal. Um animal de duas cores
    pode aparecer em duas caixas. Se o número não bater com o que você viu, refaça o vídeo ou registre a
    justificativa.

### Fotos

1. **Tire a foto no próprio celular, com a localização ligada** no aparelho e na câmera, de dentro da gleba e ao ar
   livre. Em lugar fechado, a precisão do GPS costuma passar de 30 m.
2. **Melhor ainda, pela página do Laudo Vivo no celular** ("Tirar ou escolher uma foto"), que abre a câmera e manda
   o GPS do aparelho junto. Envie do lugar onde tirou a foto: a página lê o GPS no envio, e o GPS do EXIF e o do
   aparelho têm de estar a até 100 m um do outro.
3. **Se o GPS não chegar no EXIF**, porque aplicativos de mensagem e alguns seletores de foto o removem, a foto
   passa com o GPS do aparelho. Para isso, a precisão tem de ser de até 30 m e a localização não pode ser simulada.
4. **Pelo notebook**, o navegador mandaria a localização do notebook, longe da fazenda. Negue o pedido de
   localização para valer o GPS do EXIF, com a precisão gravada pela câmera; no palco, use os botões "Arquivos do
   caso de demonstração".
5. **JPEG, não HEIC.** No iPhone, use o formato "Mais compatível" da câmera. Não envie print, foto de tela nem foto
   editada ou com filtro de aplicativo.
6. **Uma foto por evidência**, sem reaproveitar: a mesma foto em outra fiscalização é duplicata.
7. **Envie em até 72 h** depois da captura, com o relógio do celular na hora automática.
8. **Enquadre só a benfeitoria:** a cerca com os mourões e os fios em primeiro plano, sem galpão ou outra
   construção ao fundo. A foto do pasto com uma cerca lá atrás não prova a cerca. Segure firme, com foco.
9. **Fotografe a benfeitoria de dentro da gleba**, ou do lado de fora da divisa, a até 100 m.

### DANFE e GTA em papel

1. A nota inteira no quadro, plana, de frente, com luz uniforme e sem reflexo, e sem dobra sobre a chave de acesso.
2. O agente pede só o que não validou: leia do papel o que ele pedir.

### Voz

1. **Dite a chave de acesso em blocos de 4, com pausa entre eles**, como ela vem impressa no DANFE ("seis quatro
   um cinco, cinco nove quatro dois, nove quatro três nove"). Ditada algarismo por algarismo sem pausa, a
   transcrição tende a juntar ou repetir algarismos. Se o dígito verificador recusar, o agente pede de novo. "Um" e
   "uma" entre algarismos valem 1.
2. **Diga o número com a unidade:** "Muda a contagem para 9 cabeças", e não só "para nove".
3. **Responda "sim"** quando a interface pedir confirmação de um número com unidade crítica (cabeças, metros).
4. **Palavras pouco comuns**, como "brete", podem sair trocadas na transcrição. Diga "corredor do curral" ou
   digite.
5. **A declaração de independência** vai na redação do roteiro: "Declaro que não presto assistência técnica ao
   produtor nem tenho vínculo com empresa dele."
6. Fale perto do microfone e sem pressa. O ruído de vento atrapalhou pouco nos ensaios.

## 8. Problemas comuns

| Sintoma | O que fazer |
|---|---|
| `caso 'X' não encontrado (procurei em …)` | confira `LAUDO_CASOS_DIR` ou `--casos-dir` (relativo a `laudo-vivo/`; separador `;` no Windows) e o `id` do `caso.yaml` |
| O caso não aparece na Carteira | a subpasta precisa ter `caso.yaml`; reinicie o servidor depois de mudar a pasta ou o caso |
| O cartão do caso mostra um erro | o `caso.yaml` não validou: a mensagem diz o campo (confira `operacao` contra o contrato `Operacao` e o YAML) |
| Passo 1 com "Triagem: indeterminado" | falta o bloco `demonstracao:`, o REF não é só de dígitos ou outro caso usa o mesmo REF |
| A tela mostra o aviso genérico de operação sintética | falta `aviso` (ou `demonstracao.aviso`) no caso |
| Sem faixa de demonstração e NF-e de homologação recusada | `operacao.fonte` sem `sintetico` |
| "foto sem localização: o aparelho não mandou o GPS…" | tire pela página com a localização ligada ou envie o arquivo original da câmera; no `caso.yaml`, preencha `gps_app` |
| GPS_DIVERGENTE | o GPS do aparelho no envio ficou a mais de 100 m do EXIF (ex.: foto enviada pelo notebook): envie de onde tirou, ou negue a localização no notebook |
| Localização indeterminada numa foto com GPS no EXIF | o EXIF não traz a precisão: mande o GPS do aparelho (página no celular) ou `gps_app` com `precisao_m` |
| FOTO_ANTIGA | mais de 72 h entre a captura e o recebimento: no caso, ajuste `recebida_em`; ao vivo, use uma foto nova |
| DUPLICATA_EXATA ou DUPLICATA_MESMA_FISCALIZACAO | foto já usada: "Recomeçar" limpa a da mesma fiscalização; em outra, use outra foto ou uma pasta de estado de ensaio (`--dados`) |
| Contagem com CAMERA_EM_MOVIMENTO, INTERVALO_LARGO, SEM_CRUZAMENTO ou CONF_BAIXA | refaça o vídeo seguindo a seção 7; o pedido de nova captura diz o que mudar |
| Passo do satélite lento ou com erro sem rede | o cache não é do polígono e do período atuais: rode uma vez com rede (seção 4.1) |
| `replay sem gravação` | grave (seção 6) ou passe `--replay-arquivo`; o replay é sempre o do `--caso` |
| `--conferir` com N > 0 fora da gravação | o caso, o código ou o cache do VLM mudou depois da gravação: grave de novo, com a mesma `LAUDO_VLM_CACHE_GRAVACAO` |
| Leitura do DANFE dá erro no replay | a resposta do VLM não está no cache: passe a mesma `--vlm-cache-gravacao` da gravação |
| `Ollama indisponível` com o Ollama noutra porta ou máquina | `OLLAMA_HOST` (vale para o LLM, o VLM e a leitura de documento) |
| Imagem ilegível | foto em HEIC: envie em JPEG |

Mais: subida, aquecimento e contingência do palco em [`runbook.md`](runbook.md); roteiro da demo em
[`apps/web/ROTEIRO_DEMO.md`](../apps/web/ROTEIRO_DEMO.md); instalação e modo ao vivo em
[`COMO_RODAR.md`](COMO_RODAR.md).
