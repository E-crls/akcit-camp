# Como rodar o Laudo Vivo

Este guia leva um clone novo do repositório até a demo rodando, sem GPU, sem conta em serviço nenhum e sem
nada da máquina da equipe. Ele cobre os três caminhos (Docker, instalador com conda-forge e venv com pip), o
modo ao vivo opcional com o LLM local e os problemas mais comuns. Os comandos são executados na pasta
`laudo-vivo/`.

| O que roda | Precisa de GPU? | Precisa de rede? |
|---|---|---|
| Demo da linha de comando, 19 passos, ferramentas reais e LLM gravado | não | só na instalação |
| Interface web em replay (a demo do palco, com o LLM gravado) | não | só na instalação; o fundo do mapa usa os tiles do OpenStreetMap quando há internet |
| Testes (~1.500), conferência do laudo de exemplo, avaliação determinística | não | não |
| Modo ao vivo (LLM `qwen3.5:4b` no Ollama; voz por Whisper) | recomendada | para baixar o modelo uma vez |

"Ferramentas reais" quer dizer que a contagem de bovinos no vídeo (YOLOX em CPU), a leitura validada da NF-e
e da GTA, a integridade e a localização das fotos, a série de NDVI do Sentinel-2, as regras do MCR, a política
e o selo rodam de verdade. No replay, só as respostas do LLM e do VLM vêm de uma gravação do `qwen3.5:4b`.

## 1. Sem instalar nada

| Abra | O que é |
|---|---|
| [`docs/exemplos/laudo_selado.html`](exemplos/laudo_selado.html) (ou o [`.pdf`](exemplos/laudo_selado.pdf)) | o laudo que a fiscal assina no fim da demo, com a prova de cada item |
| [`docs/entregaveis/video/`](entregaveis/video/) | a demo gravada da interface (19 passos, 2:50) |
| [`docs/entregaveis/deck.pdf`](entregaveis/deck.pdf), [`docs/entregaveis/bmc-v1.pdf`](entregaveis/bmc-v1.pdf) | apresentação e Business Model Canvas |
| [`eval/SLIDE.md`](../eval/SLIDE.md) | a avaliação numa página, com IC 95% |
| [`docs/fluxo_do_agente.md`](fluxo_do_agente.md) | entradas, lógica, estados, ferramentas, políticas e saídas do agente |

## 2. Requisitos

- **Sistema:** Windows 10/11, Linux (x86-64 ou ARM64) ou macOS (Intel ou Apple Silicon). O ambiente do
  `environment.yml` foi resolvido para as cinco plataformas e testado de ponta a ponta no Windows 11 e no
  Linux do contêiner.
- **Disco:** ~2,7 GB para o ambiente conda ou ~3,7 GB para a imagem Docker, mais ~100 MB do detector.
- **Memória:** 4 GB livres bastam para a demo e os testes. O modo ao vivo precisa de mais ~4 GB para o
  modelo (VRAM ou RAM).
- **Rede, só na instalação:** conda-forge (ou PyPI, no caminho com venv) e GitHub, de onde vem o detector
  YOLOX (release oficial, com o sha256 conferido). O vídeo do lote e a série do satélite da demo já estão no
  repositório ([`ativos/`](../ativos/README.md)).
- **Um** destes: Docker (com Compose v2), **ou** micromamba/mamba/conda, **ou** Python 3.12.

## 3. Caminho 1: Docker (qualquer sistema)

```bash
docker compose up --build demo        # interface web em replay: http://127.0.0.1:8000
docker compose run --rm cli           # demo da linha de comando: 19 passos, até o laudo selado
docker compose run --rm testes        # suíte de testes
docker compose run --rm exemplo       # confere o selo do laudo de exemplo
docker compose run --rm demo python scripts/gravar_contingencia_web.py --conferir   # 19 passos pela API
```

O primeiro `up --build` constrói a imagem: ambiente do conda-forge (~430 MB), `faster-whisper` do PyPI e o
detector YOLOX. Depois do build, nada mais precisa de rede. A porta fica publicada só em `127.0.0.1`. Para
encerrar, use Ctrl+C ou `docker compose down`.

Na Carteira, clique em **"Abrir fiscalização"** no cartão da demo e avance o roteiro com **"Executar passo"**,
na barra escura "Controle da demonstração" (ou a tecla →). O PIN de demonstração da assinatura é **2410**. O
roteiro passo a passo está em [`apps/web/ROTEIRO_DEMO.md`](../apps/web/ROTEIRO_DEMO.md).

## 4. Caminho 2: instalador (conda-forge ou venv)

**Linux, macOS ou Git Bash no Windows:**

```bash
bash scripts/instalar.sh
```

**Windows (PowerShell):**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\instalar.ps1
```

O instalador faz, em ordem:

1. **Ambiente.** Com `micromamba`, `mamba` ou `conda` no PATH, cria (ou atualiza) o ambiente `laudo-vivo`
   a partir do [`environment.yml`](../environment.yml), só com pacotes do conda-forge. Sem nenhum deles, cria
   `.venv/` com Python 3.12 e instala o `pyproject.toml` do PyPI (extras `geo`, `vision` e `voice` e o grupo
   `dev`, com pip ≥ 25.1), com os mesmos tetos de versão do `environment.yml` para OpenCV (< 5), PyAV
   (< 19) e Pillow (< 13).
2. **Voz.** No ambiente conda, tenta `pip install faster-whisper`, que só existe no PyPI. O passo é
   opcional: sem ele, a fala é digitada. No Windows, aplica em seguida o ajuste de OpenMP da
   [ADR 002](adr/002-ambiente.md) (`scripts/preparar_demo.py --ajustar-openmp`): sem ele, o `ctranslate2` do
   PyPI esbarra no `libiomp5md.dll` do conda-forge e o processo para numa janela de erro.
3. **Ativos da demo.** Roda [`scripts/preparar_demo.py`](../scripts/preparar_demo.py), que copia o vídeo e a
   série do satélite de `ativos/` para `dados_locais/` e baixa o detector `yolox_m.onnx`, com o sha256 de
   cada arquivo conferido.
4. **Teste rápido.** Roda a demo de 19 passos e a conferência do laudo de exemplo.

O comando do Python escolhido fica gravado em `dados_locais/interpretador`, e o `Makefile` o usa. Opções:
`--venv`, `--nome NOME`, `--sem-voz` e `--sem-teste` (no PowerShell: `-Venv`, `-Nome`, `-SemVoz` e
`-SemTeste`).

Para preferir o conda-forge sem ter nada instalado, instale o
[micromamba](https://mamba.readthedocs.io/en/latest/installation/micromamba-installation.html) (um binário
só) e rode o instalador de novo.

Também dá para fazer à mão:

```bash
micromamba env create -f environment.yml && micromamba activate laudo-vivo   # ou conda / mamba
pip install "faster-whisper>=1.1"                                             # opcional (voz)
python scripts/preparar_demo.py --ajustar-openmp                              # só no Windows, com a voz
export PYTHONPATH=src PYTHONUTF8=1          # PowerShell: $env:PYTHONPATH = "src"; $env:PYTHONUTF8 = "1"
python scripts/preparar_demo.py
```

Ou, sem conda, com Python 3.12:

```bash
python -m venv .venv && . .venv/bin/activate                  # Windows: .venv\Scripts\activate
pip install --upgrade "pip>=25.1"
pip install -e ".[geo,vision,voice]" "opencv-python-headless<5" "av<19" "pillow<13" && pip install --group dev
export PYTHONPATH=src && python scripts/preparar_demo.py
```

## 5. Depois de instalar

Com o ambiente ativado e `PYTHONPATH=src` (o `make` já cuida dos dois):

| Para | Com `make` | Sem `make` |
|---|---|---|
| Demo da linha de comando, 19 passos (foto do DANFE, divergências, recusa à pressão, selo) | `make replay` | `python scripts/demo_cli.py --ferramentas reais --llm replay --replay tests/unit/dados_agente/replay_demo_real_qwen35_4b.jsonl` |
| O mesmo caso só com o XML da NF-e (17 passos) | `make replay ARGS="--sem-danfe --replay tests/unit/dados_agente/replay_demo_real_sem_danfe_qwen35_4b.jsonl"` | `python scripts/demo_cli.py --ferramentas reais --llm replay --sem-danfe --replay tests/unit/dados_agente/replay_demo_real_sem_danfe_qwen35_4b.jsonl` |
| Interface web em replay, em http://127.0.0.1:8000 | `make demo-web` | `python -m laudo.api --caso DEMO-0001 --ferramentas reais --perfil campo --llm replay --asr desligado` |
| Os 19 passos da interface pela API, sem navegador (confere que o replay cobre tudo e termina SELADO) | (dentro do `make avaliar`) | `python scripts/gravar_contingencia_web.py --conferir` |
| Testes, laudo de exemplo, os 19 passos pela API e avaliação determinística (só dev) | `make avaliar` | `python -m pytest tests -q`, `python docs/exemplos/conferir_exemplo.py` e `python eval/run_eval.py --modo deterministico --split dev --saida dados_locais/avaliacao` |
| Pacote de exibição BCB/Justiça no fim da demo | `make replay ARGS="--pacote"` | o comando da demo com `--pacote` |
| Ferramentas do domínio por MCP (stdio) | `make mcp ARGS="--somente-leitura"` | `python -m laudo.mcp_server --somente-leitura` |
| Roteiro mínimo, sem ferramentas reais (2 s) | `make demo` | `python scripts/demo_cli.py` |
| Todas as tarefas | `make ajuda` | `bash scripts/tarefas.sh ajuda` |

O laudo selado, o rascunho e o trace (OpenTelemetry, um JSONL por fiscalização) ficam em `dados_locais/demo/`,
e a demo imprime os caminhos no fim. A interface grava o estado dela em `dados_locais/api/`. O
`scripts/rodar_demo.sh --replay` sobe a mesma interface e abre o navegador. Ele usa o `scripts/py.sh`, que
procura o ambiente `lv` da máquina de campo da equipe.

A avaliação com o LLM (golden set, red-team e A/B) usa o Ollama. Os comandos estão em
[`eval/README.md`](../eval/README.md) e os números de palco em
[`docs/entregaveis/numeros.md`](entregaveis/numeros.md). O split de teste está congelado e só roda com
registro (`--final --motivo`).

## 6. Modo ao vivo (opcional)

O LLM e o VLM rodam locais, no [Ollama](https://ollama.com), com o `qwen3.5:4b` (Apache-2.0). Carregue um
modelo por vez.

```bash
ollama pull qwen3.5:4b                                       # ~3,4 GB, uma vez
python scripts/preparar_demo.py --ao-vivo                    # confere o Ollama e o modelo
python scripts/demo_cli.py --ferramentas reais --llm ollama --perfil campo --descarregar   # ~1 min com GPU
python -m laudo.api --caso DEMO-0001 --ferramentas reais --perfil campo --llm ollama --asr desligado \
    --vlm-cache tests/unit/dados_agente/vlm_cache_demo --aquecer       # interface ao vivo (fala digitada)
```

- **Voz:** com o `faster-whisper` instalado e o Whisper `large-v3` no cache do Hugging Face
  (`Systran/faster-whisper-large-v3`, MIT, ~3 GB), a interface aceita a fala pelo microfone: troque
  `--asr desligado` por `--asr auto` (GPU se houver; senão CPU, mais lento). O código só lê o modelo do cache
  e não o baixa sozinho. Para baixar uma vez:
  `python -c "from huggingface_hub import snapshot_download as s; s('Systran/faster-whisper-large-v3')"`.
  O microfone do navegador só funciona em `localhost` ou em HTTPS.
- **Leitura do papel:** `--vlm-cache` lê a foto do DANFE da demo pela resposta gravada do VLM (a mesma foto e
  o mesmo pedido). Sem a opção, a foto vai ao modelo (~15 s).
- **Com Docker:** `docker compose --profile ao-vivo up -d ollama`, depois
  `docker compose exec ollama ollama pull qwen3.5:4b` e `docker compose --profile ao-vivo up demo-ao-vivo`
  (http://127.0.0.1:8001). Sem GPU, o Ollama roda em CPU, mais devagar. Para usar uma GPU NVIDIA, descomente o
  bloco `deploy` do serviço `ollama` no `docker-compose.yml`.

## 7. Tempos medidos

Os tempos foram medidos em 17/10/2026 num clone novo, numa máquina de mesa com Windows 11 (o Docker roda o
Linux do Docker Desktop), numa rede rápida e com outras sessões rodando ao mesmo tempo. Numa conexão lenta, a
primeira instalação demora mais.

| Etapa | Ambiente conda no Windows | Docker |
|---|---|---|
| Montar o ambiente (~430 MB de pacotes do conda-forge, ~40 MB do PyPI, ~100 MB do detector) | ~30 s com os pacotes já no cache local | 2 a 3 min no 1º `build`; imagem de ~3,7 GB |
| `scripts/preparar_demo.py` (cópia dos ativos e download do detector) | ~3 s | dentro do `build` |
| Demo da linha de comando, 19 passos (a contagem do vídeo de 17 s em CPU leva quase todo o tempo) | 12 a 15 s | ~27 s, com a subida do contêiner |
| Interface web em replay, até responder em `/api/saude` | poucos segundos | ~2 s |
| Os 19 passos pela API da interface, sem navegador (`scripts/gravar_contingencia_web.py --conferir`) | dentro do `make avaliar` (testes, exemplo, 19 passos e avaliação do dev: ~3 min) | ~27 s |
| Suíte de testes (os lentos e os que usam rede são pulados) | ~1 min 40 s (1.479 passam, 17 pulados) | ~1 min (1.478 passam, 18 pulados) |
| Conferência do laudo de exemplo | ~1 s | ~1 s |

## 8. Problemas comuns

| Sintoma | O que fazer |
|---|---|
| `scripts/py.sh: …/.ferramentas/micromamba.exe: No such file or directory` | o `scripts/py.sh` é da máquina de campo da equipe (ambiente `lv`). Use `make` (que acha o Python registrado pelo instalador) ou `python` com o ambiente ativado e `PYTHONPATH=src` |
| `Arquivos do caso ausentes (…): video_curral_1` | rode `python scripts/preparar_demo.py` (copia o vídeo de `ativos/` para `dados_locais/`) |
| `detector yolox_m: ERRO …` no preparo (proxy, rede fechada) | baixe à mão o arquivo indicado na mensagem (release `0.1.1rc0` do YOLOX no GitHub), salve em `dados_locais/modelos/yolox_m.onnx` e rode `python scripts/preparar_demo.py --conferir` |
| 5 falhas em `tests/unit/test_voz_asr.py` com `No module named 'faster_whisper'` | falta a voz: `pip install "faster-whisper>=1.1"` (no Windows com conda, depois `python scripts/preparar_demo.py --ajustar-openmp`). O resto não depende dela |
| Windows com conda: a suíte para em `tests/unit/test_voz_asr.py` (ou abre uma janela sobre `_vcomp_barrier`), ou falha com `WinError 127` | é o conflito de OpenMP da [ADR 002](adr/002-ambiente.md): `python scripts/preparar_demo.py --ajustar-openmp` no ambiente (o instalador já roda) |
| Com pip, a demo para em `COLETA` e `integridade_foto` dá `TypeError: cannot unpack non-iterable numpy.int32 object` | o pip instalou o OpenCV 5. Use os tetos do instalador: `pip install "opencv-python-headless<5" "av<19" "pillow<13"` |
| `conferir_exemplo.py` avisa que o `src/` de hoje (`5ddd97c6…`) não é o que gerou o exemplo (`52be6b82…`) | num clone, o git grava os arquivos com fim de linha LF, e o `sha256(src/)` desse script é calculado byte a byte. `5ddd97c6…` é o mesmo código congelado com LF (é o `hash_src_lf` de `eval/harness.py`). O selo, o `SHA256SUMS` e o pacote conferem igual |
| `Address already in use` (porta 8000 ocupada) | `make demo-web ARGS="--porta 8001"` ou `python -m laudo.api … --porta 8001`; no Docker, troque `127.0.0.1:8000:8000` por `127.0.0.1:8001:8000` |
| Acentos trocados no terminal do Windows | `PYTHONUTF8=1` (o `make` e os instaladores já definem) |
| `instalar.ps1 cannot be loaded because running scripts is disabled` | rode com `powershell -ExecutionPolicy Bypass -File scripts\instalar.ps1`. A opção vale só para essa execução |
| `Warning 3: Cannot find gdalvrt.xsd (GDAL_DATA is not defined)` | é inofensivo: aparece quando o Python do ambiente é chamado sem ativar o ambiente |
| Docker: `Cannot connect to the Docker daemon` | abra o Docker Desktop (Windows e macOS) ou inicie o serviço `docker` (Linux) e reserve ao menos 4 GB de memória para ele |
| Mapa da interface sem fundo | sem internet, os tiles do OpenStreetMap não carregam, e o resto funciona. O contorno de Goiás offline vem da malha do IBGE (`python scripts/dados_ibge.py`, opcional) |
| `pip install --group dev` falha | precisa de pip ≥ 25.1: `python -m pip install --upgrade pip` |
| `Recusado: … split de teste congelado` | é o esperado: casos do teste congelado só rodam pela rodada registrada (`eval/README.md`) |

## 9. Mais

- O fluxo do agente está em [`docs/fluxo_do_agente.md`](fluxo_do_agente.md) e a arquitetura em
  [`docs/arquitetura.md`](arquitetura.md).
- Para a operação no dia e as contingências, veja [`docs/runbook.md`](runbook.md).
- A implantação gerenciada, com a mesma imagem do `Dockerfile` descrita em Terraform, está em
  [`infra/gcp/README.md`](../infra/gcp/README.md).
- Licenças dos ativos, modelos e bibliotecas: [`THIRD_PARTY.md`](../THIRD_PARTY.md).
- Para contribuir com o projeto, veja [`CONTRIBUTING.md`](../CONTRIBUTING.md).
