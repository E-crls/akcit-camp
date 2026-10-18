# ADR 002 — Ambiente Python (conda-forge) e conflito de OpenMP no Windows

Status: aceito.

## Contexto

- O ambiente precisa instalar sem o PyPI: há redes corporativas que bloqueiam `files.pythonhosted.org`
  (handshake TLS falha) e liberam `conda.anaconda.org` e o GitHub.
- Python 3.12 é exigido pelo conjunto de bibliotecas (rasterio, ctranslate2 etc.).

## Decisão

1. Ambiente do conda-forge ([`environment.yml`](../../environment.yml)), com builds **só CPU** de onnxruntime e
   pyarrow (a variante CUDA traz ~5 GB de bibliotecas desnecessárias). `faster-whisper` e `ctranslate2`, que não
   existem no conda-forge, entram como wheels.
2. Os comandos rodam via `scripts/py.sh`, que usa `micromamba run -n lv` quando o micromamba está em
   `../.ferramentas/` (define PATH, GDAL_DATA e PROJ_DATA) e, fora disso, o Python registrado por
   `scripts/instalar.sh`; sempre com `PYTHONPATH=src`.
3. A GPU fica com o Ollama (llama.cpp) e com o ctranslate2 (ASR em CUDA fp16). O ctranslate2 usa as DLLs de
   runtime CUDA 12 que o Ollama já traz (`%LOCALAPPDATA%/Programs/Ollama/lib/ollama/cuda_v12`), sem instalar o
   CUDA Toolkit.

## Conflito de OpenMP (popup "_vcomp_barrier não encontrado em ctranslate2.dll")

- O `ctranslate2.dll` importa `_vcomp_barrier` de `libiomp5md.dll`. A wheel traz a libiomp5md completa da Intel,
  que exporta o símbolo.
- O conda-forge instala em `Library/bin` um **shim** `libiomp5md.dll` (pacote `llvm-openmp`) que não exporta
  `_vcomp_barrier`. Se esse shim é carregado antes, o Windows abre uma caixa modal e o processo trava até alguém
  clicar em OK.
- Correção (`scripts/preparar_demo.py --ajustar-openmp`, que os instaladores rodam no Windows):
  1. `Library/bin/libiomp5md.dll` é substituída pela DLL da Intel; o shim fica preservado como
     `libiomp5md.dll.llvm-shim.bak`.
  2. `etc/conda/activate.d/laudo-omp_activate.bat` define `KMP_DUPLICATE_LIB_OK=TRUE`, porque Intel libiomp5md e
     LLVM libomp podem coexistir no processo.
  3. `site-packages/sitecustomize.py` desliga as caixas modais de erro do Windows (`SetErrorMode`), para que
     falhas de DLL virem exceção Python, e pré-carrega a libiomp5md da Intel.
- Validação: `scripts/py.sh -m laudo.speech <wav> --dispositivo auto` carrega o `faster-whisper-large-v3` em CUDA
  fp16 (4,5 s) sem popup, e a suíte de testes passa.

## Consequências

- Recriar o ambiente conda no Windows exige rodar de novo `scripts/preparar_demo.py --ajustar-openmp`.
- Numa máquina com acesso normal ao PyPI, o venv com o `pyproject.toml` também serve, e o conflito não ocorre,
  porque o shim do conda não existe ([`docs/COMO_RODAR.md`](../COMO_RODAR.md)).
