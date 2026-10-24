# Componentes de terceiros e licenças

O código do Laudo Vivo é Apache-2.0 ([`LICENSE`](LICENSE)). Este arquivo lista tudo o que vem de terceiros
(bibliotecas, modelos, front-end e dados), com a licença **conferida em outubro de 2026** e o método usado em
cada caso. Nada aqui foi preenchido de memória: onde não deu para conferir, está escrito.

## Pontos de atenção

| Item | Situação | O que fazer |
|---|---|---|
| `hypothesis` (MPL-2.0) | copyleft por arquivo; usado **só nos testes**, não é distribuído nem modificado | nada; não copiar código dele para `src/` |
| FFmpeg do ambiente conda (`lv`, `environment.yml` e a imagem do `Dockerfile`) | build **GPL-2.0-or-later** do conda-forge (com x264 e x265, GPL), carregado pelo PyAV em execução; o `Dockerfile` e os instaladores montam o ambiente na máquina de quem roda, e o projeto não publica imagem nem binário | se um dia publicar a imagem, usar a variante `lgpl` do FFmpeg do conda-forge (a decodificação do vídeo da demo não precisa do x264) ou cumprir a GPL |
| Bibliotecas nativas LGPL | GEOS (via shapely), libsndfile (via soundfile), LAME (via FFmpeg), carregadas dinamicamente | nada enquanto não houver redistribuição de binários |
| Fiscal-GO (`bench/fiscal_go/`) | derivado de microdados do BCB; o conjunto do Sicor no Portal de Dados Abertos do BCB é **ODbL** | publicado sob ODbL com atribuição em [`bench/fiscal_go/LICENSE`](bench/fiscal_go/LICENSE), não sob Apache-2.0 |
| Dados do IBGE | uso livre com citação da fonte, mas **não achamos licença aberta formal** para PPM e malha | confirmar com o IBGE antes de republicar os derivados como dataset |
| Vídeos CC BY-SA 4.0 e semissintéticos | só o vídeo de corredor da demo (`s03_fila_colada.mp4`) é versionado, em [`ativos/`](ativos/README.md): obra derivada, distribuída sob **CC BY-SA 4.0** com as atribuições (Gpkp, CC BY-SA 4.0; Marie Nouvellon, CC BY 2.0). Os vídeos do Commons e os outros semissintéticos não entram no git | manter as atribuições junto do arquivo (`ativos/README.md`, `ativos/manifesto.json`) e na demo gravada |
| Whisper large-v3 | o repositório `openai/whisper` diz MIT (código e pesos); o card do Hugging Face `openai/whisper-large-v3` diz Apache-2.0; a conversão da Systran diz MIT | nada: todas permissivas; citar as três |
| `gemma3:4b` | instalado no Ollama da máquina, licença **Gemma Terms of Use** (não OSI) | **não é usado** pelo produto (ADR 001); não usar sem rever |
| `tests/unit/dados_voz/fala_contagem_sapi.wav` | fala sintética da voz pt-BR do Windows (SAPI); termos da voz não conferidos | se for publicar como dado, trocar por gravação própria com consentimento ou TTS aberto |

## 1. O que está no git e o que é baixado na execução

**Nenhum peso de modelo é versionado.** O `.gitignore` exclui `dados_locais/`, `*.onnx`, `*.mp4`, `*.webm`,
`*.mov`, `*.avi`, `*.mkv`, `*.safetensors`, `*.gguf`, `*.pt`, `*.pth` e `*.ckpt`. Há duas exceções de vídeo,
por nome no `.gitignore`: o vídeo semissintético de corredor da demo, em `ativos/` (1,2 MB, CC BY-SA 4.0),
para um clone novo rodar a demo com ferramentas reais, e a demo gravada da interface, em
`docs/entregaveis/video/` (créditos no `README.md` da pasta). O `scripts/preparar_demo.py` copia os ativos de
`ativos/` para `dados_locais/` e baixa o detector, conferindo o sha256 de cada arquivo.

| Item | No git? | Onde fica | Como obter |
|---|---|---|---|
| Código, rulebooks, normas, golden set sintético, red-team | sim | `src/`, `docs/`, `eval/` | — |
| Fiscal-GO (derivados do Sicor e do IBGE) | sim | `bench/fiscal_go/*.parquet`, `*.json` | `bench/fiscal_go/build.py` a partir dos brutos |
| Gravações do LLM para o replay | sim | `tests/unit/dados_agente/*.jsonl` | saídas do `qwen3.5:4b` gravadas pela demo |
| Fala sintética do teste de ASR | sim | `tests/unit/dados_voz/fala_contagem_sapi.wav` | — |
| Leaflet 1.9.4 | sim (vendorizado) | `apps/web/vendor/leaflet-1.9.4/` | — |
| Fonte Barlow (OFL-1.1) e ícones Phosphor (MIT) e Lucide (ISC) | sim (vendorizados) | `apps/web/vendor/fonts/`, `apps/web/vendor/icones/` | — (origem e licenças na seção 4) |
| Detector YOLOX (`yolox_tiny/s/m.onnx`) | não | `dados_locais/modelos/` | `scripts/preparar_demo.py` (o `yolox_m` da demo) ou `scripts/baixar_modelos.py --todos`; ambos conferem o sha256 |
| Whisper (`Systran/faster-whisper-large-v3`) | não | cache do Hugging Face do usuário | baixado à parte; o código só lê do cache (`local_files_only`) |
| `qwen3.5:4b`, `qwen3:14b` | não | servidor Ollama local | `ollama pull qwen3.5:4b` |
| Vídeos do Wikimedia Commons | não | `dados_locais/videos/` | `scripts/baixar_videos_teste.py --contato <e-mail>` |
| Vídeo semissintético da demo (`s03_fila_colada.mp4`) | sim | `ativos/demo/video/` → `dados_locais/videos/sinteticos/` | versionado (CC BY-SA 4.0); `scripts/preparar_demo.py` copia e confere o sha256 |
| Outros vídeos semissintéticos (`s01`, `s02`, `s04`, `s05`) | não | `dados_locais/videos/sinteticos/` | `eval/golden/visao/gerar_semissintetico.py` |
| Série de NDVI da gleba da demo (busca STAC e estatísticas por data, sem pixels; 66 kB) | sim | `ativos/demo/ndvi/` → `dados_locais/ndvi_cache/` | versionada; `scripts/preparar_demo.py` copia e confere o sha256 |
| Cenas Sentinel-2 (COG) de outras glebas | não | `dados_locais/ndvi_cache/` | lidas sob demanda pela ferramenta de NDVI (~40 MB por gleba) |
| Imagens de contêiner `mambaorg/micromamba:2.9.0-debian12-slim` e `ollama/ollama:0.32.4` | não | Docker Hub | baixadas pelo `docker compose` (seção 3) |
| Microdados brutos do Sicor, malha do IBGE | não | `dados_locais/sicor/`, `dados_locais/ibge/` | `scripts/dados_sicor.py`, `scripts/dados_ibge.py` |
| Tiles do OpenStreetMap | não | — | carregados pelo navegador quando há internet |

## 2. Dependências Python

Método: `importlib.metadata` no ambiente conda-forge `lv` (campos `License-Expression`, `License` e
classificadores `License ::`); quando o metadado vinha vazio ou genérico ("BSD License"), conferimos o arquivo
de licença do pacote e o campo `license` do `conda-meta`. A versão é a instalada no ambiente `lv`; o CI
instala as versões mais recentes compatíveis com o `pyproject.toml`.

| Pacote | Versão | Licença | No `pyproject.toml` | Uso no projeto |
|---|---|---|---|---|
| Python | 3.12.15 | PSF-2.0 | `requires-python` | interpretador |
| pydantic (+ pydantic-core) | 2.13.5 | MIT | base | contratos e validação de entrada e saída das ferramentas |
| pyyaml | 6.0.3 | MIT | base | rulebooks, casos do golden set e do red-team |
| httpx | 0.28.1 | BSD-3-Clause | base | STAC/Earth Search, COG, Ollama, download de modelos e vídeos |
| numpy | 2.5.3 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | base | NDVI, visão, áudio |
| pandas | 3.0.6 | BSD-3-Clause | base | Fiscal-GO, triagem da carteira, mapa |
| pyarrow | 15.0.2 | Apache-2.0 | base (`>=17`; ver nota) | parquet (pandas) e varredura de PII |
| shapely | 2.2.0 | BSD-3-Clause | base | glebas, geofence, recorte do NDVI |
| pyproj | 3.8.0 | MIT | base | projeções UTM e Albers (geofence, áreas) |
| jinja2 | 3.1.6 | BSD-3-Clause | base | laudo HTML e GTA sintética |
| lxml | 6.1.3 | BSD-3-Clause (libxml2: MIT) | base | NF-e e XMLDSig |
| pillow | 12.3.0 | MIT-CMU | base | EXIF das fotos, fotos e documentos sintéticos |
| imagehash | 4.3.2 | BSD-2-Clause | base | detecção de foto duplicada (pHash) |
| fastapi | 0.142.4 | MIT | base | API |
| starlette | 1.7.0 | BSD-3-Clause | via fastapi (importado em `api/main.py`) | API |
| uvicorn | 0.54.0 | BSD-3-Clause | base | servidor da API |
| python-multipart | 0.0.32 | Apache-2.0 | base | upload de áudio, foto e documento |
| opentelemetry-sdk (+ -api) | 1.45.1 | Apache-2.0 | base | trace por sessão |
| rasterio | 1.5.0 | BSD-3-Clause | extra `geo` | leitura de COG do Sentinel-2 |
| pystac-client | 0.9.0 | Apache-2.0 | extra `geo` | **não importado** (a busca STAC usa httpx direto) |
| onnxruntime | 1.30.0 | MIT (conda-forge: MIT AND BSL-1.0) | extra `vision` | inferência do YOLOX em CPU; VAD Silero do faster-whisper |
| opencv-python-headless | 4.11.0 | Apache-2.0 (metadado pip vazio; conferido no conda-forge `py-opencv`/`libopencv`) | extra `vision` | vídeo, imagem, anotação, fluxo ótico |
| scipy | 1.18.1 | BSD-3-Clause | extra `vision` | associação húngara do rastreador |
| av (PyAV) | 15.1.0 | BSD-3-Clause (FFmpeg à parte: ver atenção) | extra `vision` | decodificação de vídeo e de áudio |
| faster-whisper | 1.2.1 | MIT | extra `voice` | ASR local |
| ctranslate2 | 4.8.1 | MIT | via faster-whisper (importado em `speech/asr.py`) | motor de inferência do Whisper |
| huggingface_hub | 1.32.0 | Apache-2.0 | via faster-whisper (importado em `speech/asr.py`) | localizar o modelo no cache, sem baixar |
| tokenizers | 0.22.2 | Apache-2.0 | via faster-whisper | tokenizador do Whisper |
| soundfile | 0.14.0 | BSD-3-Clause | extra `voice` | **não importado** (o áudio é decodificado pelo PyAV) |
| pytest | 9.1.1 | MIT | grupo `dev` | testes |
| ruff | 0.16.10 | MIT | grupo `dev` | lint |
| hypothesis | 6.168.5 | **MPL-2.0** | grupo `dev` | testes de propriedade (`test_visao_geofence`, `test_voz_numeros`) |
| hatchling | — (não instalado no `lv`) | MIT (repositório `pypa/hatch`, via API do GitHub) | `build-system` | empacotamento |

Bibliotecas nativas que vêm com esses pacotes no conda-forge (carregadas em execução, não redistribuídas):
FFmpeg 7.1.1 (variante `gpl`: GPL-2.0-or-later; x264 e x265 GPL-2.0-or-later; LAME LGPL-2.0-only), GEOS 3.14.1
(LGPL-2.1-only), PROJ 9.8.1 (MIT), GDAL (`libgdal-core` 3.12.4, MIT), libsndfile 1.2.2 (LGPL-2.1-or-later),
Arrow C++ 15.0.2 (Apache-2.0). Nas wheels do PyPI (usadas pelo CI) essas bibliotecas vêm embutidas; a licença
do FFmpeg embutido na wheel do PyAV não foi conferida.

**Fora da máquina da equipe** (`environment.yml`, `scripts/instalar.sh`, `scripts/instalar.ps1` e
`Dockerfile`): o `environment.yml` usa só o conda-forge, com os mínimos do `pyproject.toml` e teto na versão
maior. Ele resolve versões mais novas que as do `lv`, com as mesmas licenças da tabela acima
(no Windows: numpy 2.5.4, pandas 3.0.6, pyarrow 25.0.0, OpenCV 4.13.0, PyAV 18.1.0, FFmpeg 9.0.2,
onnxruntime 1.31.0; no Linux da imagem, PyAV 18.0.0 e FFmpeg 8.1.2). O PyAV fica abaixo da 19 porque o
`faster-whisper` 1.2.1 passa ao `av.open` um argumento que a 19 removeu. O `faster-whisper` 1.2.1 e o
`ctranslate2` 4.8.3 não existem no conda-forge e vêm do PyPI pelo instalador e pela imagem; os dois são MIT
(API do GitHub, `SYSTRAN/faster-whisper` e `OpenNMT/CTranslate2`).

Imagens de contêiner do `docker-compose.yml`, conferidas pela API do GitHub (outubro de 2026):
`mambaorg/micromamba:2.9.0-debian12-slim` (repositório `mamba-org/micromamba-docker`: Apache-2.0; o
micromamba, de `mamba-org/mamba`: BSD-3-Clause; a base Debian 12 traz os pacotes e as licenças da
distribuição) e `ollama/ollama:0.32.4` (MIT, `ollama/ollama`), só no perfil `ao-vivo`.

## 3. Modelos

| Modelo | Uso | Licença | Como conferimos |
|---|---|---|---|
| YOLOX tiny/s/m (Megvii), ONNX da release `0.1.1rc0`, treinado no COCO 2017 | detector de bovinos em CPU (`yolox_m` é o padrão) | Apache-2.0 | API do GitHub (`Megvii-BaseDetection/YOLOX`: Apache-2.0); URLs e sha256 em [`docs/modelos.md`](docs/modelos.md) |
| Whisper large-v3 (OpenAI), pesos originais | base do ASR | MIT no repositório `openai/whisper` (código e pesos); o card `openai/whisper-large-v3` do Hugging Face declara Apache-2.0 | API do GitHub e API do Hugging Face |
| `Systran/faster-whisper-large-v3` (conversão CTranslate2), revisão `edaa852ec7e1…` (a mesma do cache local) | ASR local (`src/laudo/speech/asr.py`, `MODELO_PADRAO`) | MIT | API do Hugging Face (`license: mit`) |
| faster-whisper e CTranslate2 (bibliotecas) | execução do Whisper | MIT | metadado do pacote e API do GitHub (`SYSTRAN/faster-whisper`, `OpenNMT/CTranslate2`) |
| Silero VAD v6 (`silero_vad_v6.onnx`, embutido no pacote faster-whisper) | descartar áudio sem fala antes do Whisper | MIT | API do GitHub (`snakers4/silero-vad`) |
| `qwen3.5:4b` no Ollama (4,7 B, Q4_K_M; tools e visão) | condutor do agente (perfis `campo` e `escritorio`) e VLM de `classificar_foto` (`src/laudo/vision/vlm.py`) | Apache-2.0 | `ollama show qwen3.5:4b --license` imprime o texto integral da Apache License 2.0 (cabeçalho abaixo); card `Qwen/Qwen3.5-4B` do Hugging Face: `apache-2.0` |
| `qwen3:14b` no Ollama | perfil `lote` (golden set à noite) e bake-off da ADR 001 | Apache-2.0 | camada de licença do manifesto local do Ollama, lida do disco sem carregar o modelo: Apache License 2.0 com "Copyright 2024 Alibaba Cloud"; card `Qwen/Qwen3-14B`: `apache-2.0` |
| Ollama 0.32.4 | servidor local dos LLMs (não distribuído) | MIT | API do GitHub (`ollama/ollama`) |
| `gemma3:4b` | **não usado** (ADR 001: sem tool calling no Ollama) | Gemma Terms of Use (não OSI) | camada de licença do manifesto local do Ollama |

Cabeçalho exato da saída de `ollama show qwen3.5:4b --license`:

```text
                                Apache License
                           Version 2.0, January 2004
                        http://www.apache.org/licenses/
```

O texto é idêntico ao `LICENSE-2.0.txt` oficial, exceto pela linha em branco inicial e um espaço a menos na
primeira linha.

As gravações em `tests/unit/dados_agente/*.jsonl` são saídas do `qwen3.5:4b`; a Apache-2.0 não restringe o uso
das saídas.

## 4. Front-end (`apps/web/`)

- **Leaflet 1.9.4**, BSD-2-Clause, vendorizado com o `LICENSE` original em `apps/web/vendor/leaflet-1.9.4/`
  (origem e sha256 em [`apps/web/vendor/LICENCAS.md`](apps/web/vendor/LICENCAS.md)); licença conferida no
  arquivo local e na API do GitHub (`Leaflet/Leaflet`).
- **Nenhuma outra biblioteca JS**: o `index.html` carrega só o Leaflet e os módulos próprios de
  `apps/web/js/`; não há npm, CDN, axe nem build.
- **Fonte Barlow** (Barlow 500, 600 e 700; Barlow Semi Condensed 600 e 700; Barlow Condensed 700 e 800), da
  The Barlow Project Authors, sob a **SIL Open Font License 1.1**. Os 7 arquivos `.woff2` (subconjunto latino) vêm
  do Google Fonts (`fonts.gstatic.com`, baixados em 23/10/2026) e ficam locais em `apps/web/vendor/fonts/`,
  com o `OFL.txt` ao lado. A interface funciona offline. A fonte não foi modificada e não é vendida à parte.
- **Ícones Phosphor 2.1.1** (pesos Bold e Fill), **MIT**, `LICENSE-phosphor.txt` ao lado. São 48 SVGs (45 Bold e 3 Fill) de
  `https://unpkg.com/@phosphor-icons/core@2.1.1/assets/`, em `apps/web/vendor/icones/phosphor-bold/` e
  `phosphor-fill/`.
- **Ícone Lucide 0.460.0** (`satellite`), **ISC**, `LICENSE-lucide.txt` ao lado, em `apps/web/vendor/icones/lucide/`.
  O traço foi ajustado para 2,25 px, o peso da Phosphor Bold.
- Os ícones `cerca`, `area` e `esquadro`, a marca (o esquadro na placa ipê) e o favicon (`apps/web/icone.svg`)
  são **desenhos próprios do projeto**, com a licença do projeto. O sprite inline do `index.html` sai de
  `scripts/montar_sprite_web.py`. Nenhum logotipo, nome ou ativo de marca de terceiros entrou na interface.
- **Tiles do OpenStreetMap** (`tile.openstreetmap.org`), carregados pelo navegador só quando há internet, com
  a atribuição "© OpenStreetMap" e link para `openstreetmap.org/copyright` no mapa. Dados © colaboradores do
  OpenStreetMap, ODbL; uso leve de demonstração dentro da política de tiles da OSMF.
- **Voz falada**: Web Speech API do navegador; nada é distribuído.

## 5. Dados

| Fonte | No git | Baixado na execução | Licença ou termos (conferidos em outubro de 2026) | Atribuição |
|---|---|---|---|---|
| BCB, Sicor (microdados de crédito rural: operações, glebas em WKT e tabelas de códigos) | derivados em `bench/fiscal_go/` (só campos públicos; data card no [`README`](bench/fiscal_go/README.md)) | brutos em `dados_locais/sicor/` (`scripts/dados_sicor.py`) | dados abertos do BCB. A página de download dos microdados não traz licença explícita; o conjunto do Sicor no Portal de Dados Abertos do BCB ("Matriz de Dados do Crédito Rural", BCB/Derop) está sob **ODbL** (API CKAN de `dadosabertos.bcb.gov.br`). Tratamos os derivados como ODbL | "Fonte: Banco Central do Brasil — Sicor (microdados do crédito rural)" |
| IBGE: PPM 2025 (SIDRA 3939), malha municipal e localidades de GO | `rebanho_municipal_go.parquet` e o município de cada operação no Fiscal-GO | malha em `dados_locais/ibge/` (`scripts/dados_ibge.py`); o contorno de Goiás do mapa é gerado em execução a partir dela | dados públicos com citação obrigatória da fonte. Não achamos licença aberta formal para esses produtos: a página do IBGE no gov.br indica CC BY-ND 3.0 para o conteúdo do site, e os produtos cartográficos têm termo de uso próprio. **Confirmar com o IBGE antes de republicar os derivados** | "Fonte: IBGE — Pesquisa da Pecuária Municipal 2025; Malha Municipal" |
| Copernicus Sentinel-2 L2A (ESA), coleção `sentinel-2-c1-l2a` do Earth Search (Element 84) no AWS Open Data | `bench/fiscal_go/ndvi_demo.json` e `ativos/demo/ndvi/` (séries de NDVI derivadas, sem pixels) | COGs lidos por janela; cache em `dados_locais/ndvi_cache/` | Sentinel Data Legal Notice: acesso livre, completo e aberto (o STAC da coleção declara `license: proprietary` com link para esse aviso) | "Contém dados Copernicus Sentinel modificados (2026)" |
| MCR (Seções 2-7 e 2-9) e Resoluções CMN | texto literal em `docs/normas/` | — | atos oficiais, sem proteção de direito autoral (Lei 9.610/1998, art. 8º, IV) | fonte e data de acesso em cada arquivo |
| Wikimedia Commons, vídeos de teste da visão (tabela abaixo) | os originais não; só contagens de referência e sha256 em `eval/golden/visao/contagens_referencia.yaml`, e o semissintético da demo (obra derivada) em `ativos/` | `dados_locais/videos/` | por arquivo, lida da API do Commons (`LicenseShortName`) no download e gravada em `dados_locais/videos/LICENSES.md` | autor e licença de cada vídeo |
| Golden set, caso da demo, red-team (`eval/golden/`, `eval/redteam/`) | sim | — | sintéticos, gerados pelo projeto (fotos desenhadas com Pillow, NF-e e GTA sintéticas); Apache-2.0 como o resto do repositório | — |

Vídeos do Wikimedia Commons (versão 480p VP9 do próprio Commons, sem edição):

| Arquivo local | Arquivo no Commons | Autor | Licença |
|---|---|---|---|
| `v01_estrada_oregon.webm` | [Cattle drive on southern Oregon road (41211547371).webm](https://commons.wikimedia.org/wiki/File:Cattle_drive_on_southern_Oregon_road_(41211547371).webm) | BLM Oregon & Washington | domínio público (obra do governo dos EUA) |
| `v02_mata_burro_noite.webm` | [Cow crosses cattle grid.webm](https://commons.wikimedia.org/wiki/File:Cow_crosses_cattle_grid.webm) | Luke Byers | CC BY 3.0 |
| `v03_zebuinos_estabulo.webm` | [Cows at Dharmasthala (2025) 01.webm](https://commons.wikimedia.org/wiki/File:Cows_at_Dharmasthala_(2025)_01.webm) | Gpkp | CC BY-SA 4.0 |
| `v04_manejo_a_cavalo.webm` | [Herding the cows video.webm](https://commons.wikimedia.org/wiki/File:Herding_the_cows_video.webm) | Marie Nouvellon (via Flickr) | CC BY 2.0 |
| `v05_bufalas_ordenha.webm` | [Cows at Dharmasthala (2025) 02.webm](https://commons.wikimedia.org/wiki/File:Cows_at_Dharmasthala_(2025)_02.webm) | Gpkp | CC BY-SA 4.0 |

- **Semissintéticos** (`s01` a `s05`, em `dados_locais/videos/sinteticos/`): recortes de v03 e v04 sobre um
  fundo de pasto do v04; obra derivada, CC BY-SA 4.0 (Gpkp) + CC BY 2.0 (Marie Nouvellon). O
  `s03_fila_colada.mp4` é o vídeo de corredor da demo com ferramentas reais e o único versionado (`ativos/`,
  sob CC BY-SA 4.0).
- **Extras** (`--extras`, ainda sem contagem de referência e fora das métricas): oito candidatos em domínio
  público, CC0, CC BY e CC BY-SA, listados em `scripts/baixar_videos_teste.py`; a licença de cada um é lida da
  API do Commons no download.

## 6. Como reconferir

```bash
scripts/py.sh -c "import importlib.metadata as m; d = m.distribution('hypothesis'); \
print(d.version, d.metadata['License-Expression'])"
ollama show qwen3.5:4b --license | head -3
```

Ao acrescentar dependência, modelo ou dado, atualize este arquivo no mesmo commit.
