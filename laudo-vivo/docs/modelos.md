# Modelos e dados de visão

Tudo roda em **CPU** (onnxruntime CPU, OpenCV headless); a GPU fica com o LLM e o ASR.
Métricas medidas: `eval/golden/visao/RESULTADOS.md`.

## Detector de bovinos: YOLOX (Megvii), Apache-2.0

| Arquivo | URL oficial (release `0.1.1rc0`) | sha256 | Entrada | ms/quadro (CPU, 8 threads)* |
|---|---|---|---|---|
| `yolox_tiny.onnx` | https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_tiny.onnx | `427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7` | 416×416 | 7 |
| `yolox_s.onnx` | https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_s.onnx | `c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063` | 640×640 | 17 |
| `yolox_m.onnx` | https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_m.onnx | `21ff6cfdeb53b013bac2249599e55f00bff3cfdfdab37ed7a4620818c1d15b3f` | 640×640 | 52 |

\* Só a inferência, AMD Ryzen 9 9950X3D, `intra_op_num_threads=8`.

- **Licença:** código e pesos do repositório YOLOX sob Apache-2.0
  (https://github.com/Megvii-BaseDetection/YOLOX/blob/main/LICENSE). Pesos treinados no COCO 2017 (80
  classes).
- **Por que não Ultralytics:** YOLOv5/v8/11 da Ultralytics são AGPL-3.0; isso contaminaria o produto. O pré e
  o pós-processamento do YOLOX foram reescritos em numpy/OpenCV (`src/laudo/vision/detector.py`): letterbox no
  canto superior esquerdo com preenchimento 114, BGR 0–255 sem normalização, decodificação das grades (strides
  8/16/32), score = objetividade × probabilidade da classe, NMS guloso.
- **Classes usadas:** `cow` (19) **+** `sheep` (18), agrupadas como "bovino" (score = maior das duas).
  Bezerros e animais claros às vezes saem como "ovelha". **Cavalo fica de fora** de propósito: vaqueiro a
  cavalo é comum no curral, e nos vídeos de teste a maioria das detecções "cavalo" era cavalo de verdade. Os
  zebuínos (brancos e vermelhos) do v03 saíram como "vaca" em 97% (yolox_s) e 100% (yolox_m) das detecções de
  animal. A fração de detecções "ovelha" vai na saída (`frac_outra_classe`) e gera o aviso `CLASSE_CONFUSA`
  acima de 50%.
- **Modelo padrão da ferramenta: `yolox_m`.** O `yolox_s` subconta e fragmenta mais em cena real (ver
  RESULTADOS). O `yolox_m` custa cerca de 0,6 s por segundo de vídeo a 8 quadros/s (0,3 com o `yolox_s`, que
  fica como opção para máquina fraca).
- **Reproduzir:** `scripts/py.sh scripts/baixar_modelos.py --todos` (confere o sha256). Os arquivos ficam em
  `dados_locais/modelos/` (fora do git). O registro dos modelos está em `src/laudo/vision/modelos.py`.

## Rastreamento e contagem (código próprio, sem dependência de licença restritiva)

- Rastreador estilo SORT/ByteTrack (`src/laudo/vision/rastreador.py`): previsão por velocidade suavizada,
  associação húngara (`scipy.optimize.linear_sum_assignment`) em 3 estágios, com IoU "com buffer" para quadros
  amostrados e um 2º estágio com detecções de score baixo. Por fim, uma **extensão offline**: cada trilha é
  prolongada para trás e para frente com as detecções que sobraram, para recuperar o trecho em que o animal
  ainda estava longe ou de costas.
- **Costura em cadeias** (`src/laudo/vision/contagem.py`): trilhas que somem e reaparecem perto da posição
  extrapolada (até 2 s) viram o mesmo animal. Cada costura entra no intervalo de incerteza. O teto do
  intervalo também sobe com a taxa de oclusão (fração de caixas com ≥ 25% da área coberta por outra): `teto +=
  ⌈contagem × oclusão × 0,5⌉`.
- **Contagem por linha** (corredor/brete, modo recomendado): cruzamento líquido por cadeia, com histerese e
  linha automática perpendicular ao movimento dominante (ou informada em coordenadas normalizadas). **IDs
  únicos** (lote parado): cadeias com duração ≥ 1 s.
- **Abstenção** (`status = "indeterminado"`) quando a confiança média é < 0,5, a cobertura (fração de quadros
  em que a cadeia foi vista) é < 0,6, o intervalo é largo (meia-largura > 25% da contagem), mais de 50% dos
  quadros estão escuros ou borrados, a oclusão passa de 70%, não há cruzamento, não há bovino, ou a **câmera
  se move** (fluxo ótico do fundo com afim parcial RANSAC; translação líquida > 0,35 quadro, zoom líquido > 8%
  ou caminho > 3 quadros). Cada motivo vira um pedido de recaptura (`pedidos_recaptura`).
- **Evidência:** de 3 a 6 quadros-chave anotados (caixas, IDs, linha, contagem acumulada), em JPEG com sha256,
  em `dados_locais/evidencias/visao/<sha256 do vídeo>/`.

## VLM opcional: `classificar_foto`

`qwen3.5:4b` no Ollama local (licença Apache-2.0, capacidade `vision`), saída por JSON Schema (classes
`bovinos`, `cerca`, `curral`, `galpao`, `maquina`, `documento`, `outro`), autoconsistência k = 3 (temperatura
0,7, sementes 1000–1002) e abstenção quando a concordância é < 2/3 ou a classe é `outro`. Descarrega o modelo
na última chamada (`keep_alive: 0`). O texto na foto é tratado como dado.

## Vídeos de teste (Wikimedia Commons)

Versão transcodificada 480p VP9 do próprio Commons. Os arquivos ficam em `dados_locais/videos/` (fora do git),
com origem e licença também em `dados_locais/videos/LICENSES.md`.

| Arquivo | Commons | Autor | Licença |
|---|---|---|---|
| `v01_estrada_oregon.webm` | [Cattle drive on southern Oregon road (41211547371).webm](https://commons.wikimedia.org/wiki/File:Cattle_drive_on_southern_Oregon_road_(41211547371).webm) | BLM Oregon & Washington | Domínio público (obra do governo dos EUA) |
| `v02_mata_burro_noite.webm` | [Cow crosses cattle grid.webm](https://commons.wikimedia.org/wiki/File:Cow_crosses_cattle_grid.webm) | Luke Byers | CC BY 3.0 |
| `v03_zebuinos_estabulo.webm` | [Cows at Dharmasthala (2025) 01.webm](https://commons.wikimedia.org/wiki/File:Cows_at_Dharmasthala_(2025)_01.webm) | Gpkp | CC BY-SA 4.0 |
| `v04_manejo_a_cavalo.webm` | [Herding the cows video.webm](https://commons.wikimedia.org/wiki/File:Herding_the_cows_video.webm) | Marie Nouvellon (Flickr) | CC BY 2.0 |
| `v05_bufalas_ordenha.webm` | [Cows at Dharmasthala (2025) 02.webm](https://commons.wikimedia.org/wiki/File:Cows_at_Dharmasthala_(2025)_02.webm) | Gpkp | CC BY-SA 4.0 |

- **Reproduzir:** `scripts/py.sh scripts/baixar_videos_teste.py --contato <e-mail ou URL de quem roda>`. A
  política de User-Agent do Wikimedia exige contato; sem ele o servidor de arquivos responde 429. `--extras`
  baixa mais 8 candidatos já triados (domínio público, CC0, CC BY e CC BY-SA), ainda sem contagem de
  referência, entre eles um vídeo brasileiro ("Lida com o gado no Vale do Jequitinhonha").
- **Semissintéticos** (`dados_locais/videos/sinteticos/`, gerados por
  `eval/golden/visao/gerar_semissintetico.py`): recortes reais e curados dos vídeos v03 e v04 andando em fila
  sobre um fundo de pasto com cerca. São obra derivada (CC BY-SA 4.0 + CC BY 2.0) e servem para medir o modo
  linha (lote passando pelo corredor).

## Integridade de foto e geofence

Não usam modelo treinado. A heurística de "foto de tela" (moiré cromático, pico espectral de grade de pixels,
moldura, ausência de câmera no EXIF) foi calibrada com 37 quadros reais (sem tela) e 9 fotos de tela
**sintéticas**. O geofence projeta em UTM WGS84 da zona do centroide da gleba (`pyproj`).
