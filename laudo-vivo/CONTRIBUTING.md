# Como contribuir

Guia de quem mexe no código, nos dados e nos textos do Laudo Vivo: ambiente, tarefas, regras de código e de
dados e quem cuida de cada área. O passo a passo para rodar o produto fica no [`README.md`](README.md) e em
[`docs/COMO_RODAR.md`](docs/COMO_RODAR.md).

Leia antes: [`src/laudo/contracts.py`](src/laudo/contracts.py) (contratos),
[`docs/arquitetura.md`](docs/arquitetura.md) (peças e fronteiras),
[`docs/fluxo_do_agente.md`](docs/fluxo_do_agente.md) (fluxo) e [`docs/regras.md`](docs/regras.md) (o MCR como
código).

## Ambiente

Python 3.12. Os comandos rodam a partir desta pasta (`laudo-vivo/`).

- **Máquina com acesso ao PyPI:** `pip install -e ".[geo,vision,voice]"` e `pip install --group dev`
  (pip ≥ 25.1), com `PYTHONPATH=src` e `PY=python` para as tarefas abaixo. É o que o CI faz.
- **Só conda-forge (sem PyPI):** `micromamba env create -f environment.yml` (ou `mamba`/`conda`); o
  cabeçalho do arquivo diz o que fica de fora. O ajuste de OpenMP do Windows está na
  [`docs/adr/002-ambiente.md`](docs/adr/002-ambiente.md).
- **`scripts/py.sh`:** roda o Python do ambiente (`scripts/py.sh caminho/script.py`, `scripts/py.sh -m pytest
  tests/unit -q`), com `PYTHONPATH=src`. Usa o ambiente conda `lv` quando ele existe, o interpretador
  registrado por `scripts/instalar.sh` ou o `python` do PATH. `scripts/py.sh -c "..."` com várias linhas
  quebra no Windows: escreva um arquivo `.py`.
- **Dependência nova só combinada com a equipe** (nome, motivo, tamanho). Prefira resolver com o que existe; o
  que entrar vai para o `pyproject.toml`, o `environment.yml` e o [`THIRD_PARTY.md`](THIRD_PARTY.md) no mesmo
  commit.
- **LLM local:** servidor Ollama em `http://127.0.0.1:11434` (modelos `qwen3.5:4b` e, no perfil `lote`,
  `qwen3:14b`). Um modelo carregado por vez (VRAM); descarregue ao terminar (`ollama stop <modelo>`). O
  produto passa a data de referência da fiscalização no prompt, e o modelo não inventa data.

## Recursos

- Processe arquivos grandes em streaming ou em blocos, sem carregar tudo na memória.
- GPU: reservada ao Ollama e ao ASR. Visão roda em CPU (onnxruntime CPU).
- Disco: dados brutos em `dados_locais/` (ignorado pelo git) ou `../dados/`; nada acima de 200 MB no git.

## Tarefas

`scripts/tarefas.sh <tarefa>` ou `make <tarefa>` (`scripts/tarefas.sh ajuda` lista todas): `demo` (sem GPU),
`testes`, `lint`, `pii`, `frases`, `numeros --verificar`, `fixos`, `tempo`, `avaliacao` (golden set dev e
red-team determinísticos) e `ci` (os mesmos passos do GitHub Actions, menos a avaliação).

**Antes de abrir o pull request:** `scripts/tarefas.sh ci` verde. Testes lentos e de rede pulam por padrão
(`LAUDO_LENTO=1` e `LAUDO_TESTES_REDE=1` para rodá-los).

**CI:** o GitHub Actions roda [`../.github/workflows/ci.yml`](../.github/workflows/ci.yml), na raiz do
repositório, de dentro de `laudo-vivo/`, a cada push e pull request. Em
[`.github/workflows/ci.yml`](.github/workflows/ci.yml) fica a variante para quando esta pasta for publicada
como repositório próprio; as duas têm os mesmos passos, e `scripts/checar_ci.py` (passo do CI e da tarefa
`ci`) acusa se elas divergirem. Sem segredos e sem LLM: os números citados nos textos vêm dos relatórios da
avaliação final (rodada local, com o LLM) e são conferidos pelo passo dos números.

## Regras de código

- Toda ferramenta: `@registrar(...)` de `laudo.contracts`, entrada em Pydantic, retorno `Envelope`. Erro vira
  `Envelope.falha(...)`, nunca exceção solta nem valor inventado.
- Ferramentas determinísticas fazem todas as contas. O LLM nunca calcula número nem define status.
- Cite a norma em cada regra (`regra_id` como `MCR-2-7-item16`).
- Testes em `tests/unit/` com o prefixo da área (`test_geo_*.py`, `test_regras_*.py`, `test_visao_*.py`,
  `test_docs_*.py`, `test_agente_*.py`).
- Comentários e docs em pt-BR. Linha de até 110 colunas. `scripts/py.sh -m ruff check src tests eval scripts`
  sem achado antes de terminar.
- Mudar prompt, descrição de ferramenta ou esquema muda a chave das gravações de replay: regrave as fixtures
  (`--gravar` com o Ollama) e confira com `scripts/py.sh scripts/gravar_contingencia_web.py --conferir`.

## Dados

- Sem PII no repositório: nada de CPF, nome ou telefone reais em `eval/`, `bench/`, `tests/`. Dados sintéticos
  usam marcadores claramente falsos.
- Os marcadores aceitos estão na docstring de `scripts/checar_pii.py`: CPF `000.000.xxx-DV` e CNPJ
  `99.999.999/xxxx-DV` (gere com `cpf_sintetico`/`cnpj_sintetico` de `laudo.docs_fiscais.sintetico`), telefone
  `(62) 99999-0000`, e-mail em domínio reservado (`@exemplo.invalid`, `@example.com`; em texto de uso,
  `<seu e-mail>`) e nome com `TESTE`/`SINTETICO` ou Fulano/Beltrano. Teste que precisa de documento com forma
  real monta o valor em tempo de execução.
- Valor público que não pode virar marcador (ex.: exemplo oficial de um validador) vai para a lista
  `PERMITIDOS` do mesmo script, por valor e arquivo, com motivo e fonte, revisada pela área de Avaliação;
  dado de pessoa real nunca entra nela. Antes de terminar, `scripts/py.sh scripts/checar_pii.py --parquet`
  tem de sair com código 0.
- Pesos de modelo, vídeos e `dados_locais/` ficam fora do git. Dependência, modelo ou dado novo entra no
  [`THIRD_PARTY.md`](THIRD_PARTY.md) no mesmo commit.

## Quem cuida de cada área

Para não haver conflito, cada área mexe nos seus diretórios:

| Área | Diretórios |
|---|---|
| Dados e triagem | `src/laudo/geo/`, `src/laudo/tools/carteira.py`, `src/laudo/tools/ndvi.py`, `scripts/dados_*.py`, `bench/fiscal_go/` |
| Regras | `src/laudo/rulebooks/`, `src/laudo/tools/regras.py`, `docs/normas/` |
| Visão | `src/laudo/vision/`, `src/laudo/tools/foto.py`, `src/laudo/tools/geofence.py`, `src/laudo/tools/bovinos.py` |
| Documentos fiscais e casos sintéticos | `src/laudo/docs_fiscais/`, `src/laudo/tools/documentos.py`, `eval/golden/gerador/` |
| Agente | `src/laudo/agent/`, `src/laudo/llm/`, `src/laudo/audit/`, `src/laudo/tools/laudo.py` |
| Interface e voz | `src/laudo/api/`, `src/laudo/speech/`, `apps/web/` |
| Avaliação | `eval/` (exceto `eval/golden/gerador/`), `tests/contract/`, `.github/` |
| Negócio e pitch | `docs/entregaveis/` |

`src/laudo/contracts.py`, `pyproject.toml`, `README.md` e `docs/arquitetura.md` são da coordenação: proponha a
mudança no pull request ou numa issue.

## Licença

Ao contribuir, você concorda que sua contribuição é licenciada sob a Apache-2.0 ([`LICENSE`](LICENSE),
seção 5).
