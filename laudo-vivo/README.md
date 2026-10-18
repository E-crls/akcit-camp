# Laudo Vivo — prova auditável do crédito rural, do satélite ao curral

O Laudo Vivo é um agente de IA que transforma uma operação de crédito rural em um laudo de fiscalização em que
**cada item aponta para a sua prova**. Ele escolhe o método pela regra (MCR 2-7, Res. CMN 5.267/2025), conduz
a fiscal em campo por voz, confere o vídeo do lote contra a quantidade financiada, a NF-e e a GTA (XML/JSON ou
**foto do papel**, lida por VLM e validada por dígito verificador e somas) contra o projeto, a foto da cerca
contra a gleba do Sicor e o pasto contra o satélite; classifica cada item como verificado, divergente,
pendente ou abstenção; recusa pressão ("pode marcar 29") e instrução escondida em documento; e só libera o
rascunho quando a evidência mínima existe. Quando a foto do DANFE ou da GTA deixa campos sem validar, o agente
pede **só esses campos** ("leia os 12 últimos dígitos da chave de acesso") e confere o que a fiscal leu com as
mesmas regras antes de aceitar.

- **O que a IA faz:** lê o papel e a fala, o que um formulário não consegue (modelo local, `qwen3.5:4b` no
  Ollama, para a conversa, as alegações da fala e a leitura da foto).
- **O que a IA não faz:** calcular (ferramentas determinísticas) nem dar o status (verificador independente,
  com uma política default-deny que bloqueia). O LLM pode chamar as checagens da etapa; quando não chama a
  óbvia, o plano mínimo determinístico chama; o status vem sempre das regras e do verificador.
- **A assinatura é sempre humana.**

## Como avaliar em 10 minutos

**Sem instalar nada:**

| Abra | O que mostra |
|---|---|
| [`docs/exemplos/laudo_selado.html`](docs/exemplos/laudo_selado.html) ([PDF](docs/exemplos/laudo_selado.pdf)) | o laudo selado do fim da demo: cada item com status, regra citada e prova; o selo confere sem a instalação que o gerou ([como ler](docs/exemplos/README.md)) |
| [`docs/entregaveis/video/`](docs/entregaveis/video/) | a demo gravada da interface: os 19 passos do caso `DEMO-0001`, uma operação fictícia |
| [`docs/resultados.md`](docs/resultados.md) | os resultados da avaliação: golden set no teste e no dev, red-team da equipe e cego, A/B, custo e latência, com n e IC 95% |
| [`docs/fluxo_do_agente.md`](docs/fluxo_do_agente.md) | o fluxo do agente: entradas, lógica, estados, ferramentas, políticas e saídas |
| [`docs/entregaveis/deck.pdf`](docs/entregaveis/deck.pdf), [`docs/entregaveis/bmc-v1.pdf`](docs/entregaveis/bmc-v1.pdf) | apresentação e Business Model Canvas |

**Rodando, sem GPU e sem conta em serviço nenhum** (só o Docker; a primeira vez constrói a imagem em poucos
minutos):

```bash
docker compose up --build -d demo  # 1. interface web em replay: http://127.0.0.1:8000, botão "Abrir demo"
docker compose run --rm cli        # 2. a demo no terminal: 19 passos até o laudo selado
docker compose down                # (para encerrar a interface)
docker compose run --rm testes     # 3. a suíte de testes
```

Na interface, avance com **"Executar passo"** (ou a tecla →). O PIN de demonstração da assinatura é **2410**.
Sem Docker, use `bash scripts/instalar.sh` (no Windows, `powershell -ExecutionPolicy Bypass -File
scripts\instalar.ps1`), que cria o ambiente pelo conda-forge (ou venv), prepara os ativos da demo e roda um
teste rápido. Depois, rode `make replay` e `make demo-web`.

Requisitos, Windows, Linux e macOS, modo ao vivo com o LLM local, tempos e problemas comuns estão em
[`docs/COMO_RODAR.md`](docs/COMO_RODAR.md). A mesma imagem, descrita em Terraform para um ambiente
gerenciado, está em [`infra/gcp/README.md`](infra/gcp/README.md).

## Resultados

Todos os números, com n, IC 95% de Wilson e o par teste/dev lado a lado, estão em
[`docs/resultados.md`](docs/resultados.md). Os principais, da avaliação final no split de teste congelado
(n = <!--n:golden.n_teste.valor-->24<!--/n-->):

| Medida | Resultado |
|---|---|
| Golden set, com o agente | recall de defeito <!--n:recall_teste.fmt-->1,00 [0,70–1,00] (9/9)<!--/n-->; over-blocking <!--n:overblocking_teste.fmt-->0% [0–28%] (0/10)<!--/n-->; abstenção correta <!--n:abstencao_teste.fmt-->1,00 [0,57–1,00] (5/5)<!--/n--> |
| Red-team | escrito pela equipe: <!--n:redteam.ataques.kn-->0/80<!--/n--> ataques bem-sucedidos; conjunto cego, escrito de forma isolada e rodado uma vez: <!--n:redteam.cego_ataques.kn-->6/30<!--/n--> (<!--n:redteam.cego_ataques_sem_semicega.kn-->6/26<!--/n--> sem a família semi-cega) |
| A/B v2 (papel fotografado e fala livre, sintéticos; fiscal simulado) | no teste, conteúdo conciliado <!--n:ab2_teste.residual.kn-->17/24<!--/n--> com o agente contra <!--n:ab2_teste.formulario.kn-->14/24<!--/n--> com o formulário (<!--n:ab2_teste.mcnemar.curto-->p = 0,51<!--/n-->) e, sem a menção a item não financiado, <!--n:ab2_teste.residual_sem_registro.kn-->19/24<!--/n--> contra <!--n:ab2_teste.formulario_sem_registro.kn-->21/24<!--/n--> (<!--n:ab2_teste.mcnemar_sem_registro.curto-->p = 0,69<!--/n-->); no dev, onde o A/B foi desenvolvido, <!--n:ab2.residual.kn-->35/36<!--/n--> contra <!--n:ab2.formulario.kn-->15/36<!--/n--> |
| Latência por turno | p50/p95 <!--n:agente.latencia_p50.valor-->2,0 s<!--/n-->/<!--n:agente.latencia_p95.valor-->2,8 s<!--/n--> sem outra carga no Ollama |

## Tema registrado

**Prova auditável da aplicação e da conformidade do crédito rural no campo** (AKCIT Camp 2026, Centro-Oeste).
Os módulos são aprimoramentos do mesmo problema:

| Etapa | Módulo | Norma |
|---|---|---|
| Regional | fiscalização de operações com animais (compra de gado, custeio de aquisição e manutenção, cerca e curral) | MCR 2-7 (Res. CMN 5.267/2025) |
| Final | exceções socioambientais | MCR 2-9 (Res. CMN 5.303) |
| Depois | perdas (Proagro e seguro) | MCR 12 (Res. CMN 5.315) |

## Entregáveis do edital

Os quatro entregáveis e onde conferir cada um estão em
[`docs/entregaveis/README.md`](docs/entregaveis/README.md).

| Entregável | Onde |
|---|---|
| 1. Protótipo funcional (com a demo gravada) | código em `src/laudo/` e `apps/web/`; demo em [`docs/entregaveis/video/`](docs/entregaveis/video/) e [`apps/web/ROTEIRO_DEMO.md`](apps/web/ROTEIRO_DEMO.md) |
| 2. Business Model Canvas | [`docs/entregaveis/bmc-v1.pdf`](docs/entregaveis/bmc-v1.pdf) ([texto](docs/entregaveis/bmc-v1.md)); mercado em [`docs/entregaveis/mercado.md`](docs/entregaveis/mercado.md) |
| 3. Pitch | [`docs/entregaveis/pitch-regional-3min.md`](docs/entregaveis/pitch-regional-3min.md) e os slides em [`docs/entregaveis/deck.pdf`](docs/entregaveis/deck.pdf) |
| 4. Fluxo do agente (inputs, lógica, outputs) | [`docs/fluxo_do_agente.md`](docs/fluxo_do_agente.md) |

Apoio: arquitetura e decisões em [`docs/arquitetura.md`](docs/arquitetura.md) e [`docs/adr/`](docs/adr/);
resultados em [`docs/resultados.md`](docs/resultados.md); privacidade (LGPD) em
[`docs/privacidade.md`](docs/privacidade.md); validação do problema em
[`validacao/README.md`](validacao/README.md); licença, terceiros e como contribuir em [`LICENSE`](LICENSE),
[`THIRD_PARTY.md`](THIRD_PARTY.md) e [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Como rodar

Num clone novo, o caminho é o de [`docs/COMO_RODAR.md`](docs/COMO_RODAR.md): `docker compose up --build demo`
ou `bash scripts/instalar.sh` (ambiente do [`environment.yml`](environment.yml), só conda-forge; sem conda,
venv com pip). O instalador também roda [`scripts/preparar_demo.py`](scripts/preparar_demo.py), que copia de
[`ativos/`](ativos/README.md) o vídeo do lote e a série do satélite da demo e baixa o detector YOLOX, com o
sha256 conferido. Com o ambiente pronto:

```bash
make replay      # demo da linha de comando: 19 passos, ferramentas reais, LLM gravado (~15 s, sem GPU)
make demo-web    # interface web em replay: http://127.0.0.1:8000
make avaliar     # testes, laudo de exemplo, 19 passos pela API e avaliação determinística (só dev)
```

Os mesmos caminhos, pelo `scripts/py.sh` (que usa o Python registrado pelo instalador, com `PYTHONPATH=src`):

```bash
# LLM roteirizado e ferramentas falsas (2 s, sem GPU)
scripts/py.sh scripts/demo_cli.py
# demo de 19 passos com a foto do DANFE (~12 s, sem GPU)
scripts/py.sh scripts/demo_cli.py --ferramentas reais --llm replay \
    --replay tests/unit/dados_agente/replay_demo_real_qwen35_4b.jsonl
# caminho só com o XML da NF-e (17 passos)
scripts/py.sh scripts/demo_cli.py --ferramentas reais --llm replay --sem-danfe \
    --replay tests/unit/dados_agente/replay_demo_real_sem_danfe_qwen35_4b.jsonl
# ao vivo, com o Ollama (~1 min com GPU)
scripts/py.sh scripts/demo_cli.py --ferramentas reais --llm ollama --perfil campo --descarregar
scripts/rodar_demo.sh --replay                         # interface web: demo gravada, sem GPU
scripts/rodar_demo.sh                                  # interface web ao vivo (Ollama + Whisper)
scripts/py.sh -m laudo.api                             # só desenvolvimento: LLM e ferramentas FALSOS
scripts/py.sh -m laudo.mcp_server --somente-leitura    # as ferramentas por MCP (stdio)
scripts/py.sh -m pytest tests -q                       # testes (lentos e de rede pulados; LAUDO_LENTO=1)
make ci                                                # lint + testes + varredura de PII
```

Sem o instalador, os mesmos comandos rodam com `python` no lugar de `scripts/py.sh`, com o ambiente ativado e
`PYTHONPATH=src` (tabela completa em [`docs/COMO_RODAR.md`](docs/COMO_RODAR.md), seção 5).

A interface web da demo é a do `scripts/rodar_demo.sh` e do `make demo-web` (caso `DEMO-0001`, ferramentas
reais, perfil `campo`, em http://127.0.0.1:8000). Com `--replay`, o LLM e a leitura do papel vêm da gravação,
sem GPU nem rede. O `scripts/py.sh -m laudo.api` sem opções sobe o roteiro de desenvolvimento, com LLM
roteirizado e **ferramentas falsas**: não é a demo. Operação da demo, contingências e diagnóstico:
[`docs/runbook.md`](docs/runbook.md).

A série Sentinel-2 da gleba da demo já vem calculada em `ativos/` (sem ela, a primeira execução baixa ~40 MB
em ~40 s; depois tudo roda do cache, offline). As respostas do VLM da demo (leitura do DANFE, classificação da
foto da cerca) ficam gravadas em `tests/unit/dados_agente/vlm_cache_demo/`, para o replay rodar sem GPU. Para
o LLM ao vivo: Ollama com `qwen3.5:4b` (`ollama pull qwen3.5:4b`), um modelo por vez.

### Outros comandos

| Para | Comando |
|---|---|
| Avaliação no golden set (sem LLM / com o agente) | `scripts/py.sh eval/run_eval.py --modo deterministico` · `--modo agente` |
| Red-team da equipe (original + v2) | `scripts/py.sh eval/run_redteam.py --modo agente` |
| A/B de centralidade (fiscal simulado; papel fotografado e fala livre, sintéticos) | `scripts/py.sh eval/ab_centralidade/run_ab.py` · `eval/ab_centralidade_v2/run_ab_v2.py` |
| Números citados nos textos (fonte única, gerada dos relatórios) | `scripts/py.sh scripts/gerar_numeros.py --aplicar` · `--verificar` (`make numeros`) |
| Contingência da interface (grava e confere o replay) | `scripts/py.sh scripts/gravar_contingencia_web.py` · `--conferir` |
| Custo por fiscalização (tokens, GPU, energia; do trace) | `scripts/py.sh scripts/custo_fiscalizacao.py dados_locais/demo/traces/fis_demo_0001.jsonl` |
| Cofre e expurgo LGPD (crypto-shredding por fiscalização) | `scripts/py.sh scripts/expurgo_lgpd.py cifrar <fis>` · `expurgar <fis> --motivo ...` · `vencidos --dias 90` |
| Varredura de dados pessoais | `scripts/py.sh scripts/checar_pii.py --parquet` |
| Tudo por `make` | `make ajuda` (testes, lint, pii, demo, replay, avaliacao, numeros, entregaveis, custo, mcp, expurgo, ci); para quem avalia: `make instalar`, `make demo-web`, `make avaliar` |
| Ativos da demo (vídeo, satélite, detector; sha256) | `python scripts/preparar_demo.py` · `--conferir` · `--ao-vivo` (confere o Ollama) |

## Mapa do repositório

| Caminho | O quê |
|---|---|
| `docs/fluxo_do_agente.md` | **entregável do edital**: inputs, lógica, estados, ferramentas, políticas, outputs, LGPD, observabilidade |
| `docs/resultados.md` | resultados da avaliação, com n e IC 95% |
| `docs/arquitetura.md`, `docs/adr/` | arquitetura, o porquê de cada fronteira e decisões (ADR 001: modelo local; ADR 002: ambiente) |
| `docs/regras.md`, `docs/normas/` | MCR 2-7 e 2-9 como código: texto normativo literal, versionamento e revisão |
| `docs/modelos.md` | modelos e dados de visão (licenças, sha256, métricas) |
| `docs/entregaveis/` | BMC, pitch, slides, mercado e a demo gravada |
| `src/laudo/contracts.py` | contratos compartilhados (`Operacao`, `Evidencia`, `Checagem`, `CampoLaudo`, `Bloqueio`, `Envelope`) |
| `src/laudo/agent/` | condutor (LLM + FSM), executor, verificador, política, fatos por template, estado append-only, demo |
| `src/laudo/tools/` | ferramentas registradas: carteira, NDVI, regras, foto (integridade e VLM), geofence, bovinos, documentos, leitura de foto de documento e residual, alegações, laudo |
| `src/laudo/rulebooks/` | rulebooks YAML (MCR 2-7 e MCR 2-9; a versão fica no cabeçalho de cada YAML) |
| `src/laudo/vision/`, `geo/`, `docs_fiscais/` | contagem de bovinos (YOLOX + rastreador), VLM, Sentinel-2/STAC, NF-e, GTA, leitura validada e residual |
| `src/laudo/llm/`, `audit/` | provedor Ollama/replay; trace OpenTelemetry, cadeia de hash, custo, cofre (expurgo) |
| `src/laudo/mcp_server.py` | servidor MCP (stdio, JSON-RPC) com as ferramentas do `REGISTRO` |
| `src/laudo/api/`, `speech/`, `apps/web/` | API, voz (ASR local) e interface web |
| `bench/fiscal_go/` | Fiscal-GO 2026: operações de crédito rural de GO (Sicor/BCB, público) com glebas e triagem |
| `bench/desclassificacao/` | observatório de desclassificações do Sicor (agregados públicos; base da matriz de validação) |
| `validacao/` | matriz de evidências de Problema e Validação (o que o regulador, o auditor e o juiz escreveram) |
| `eval/golden/` | golden set (60 casos com defeitos plantados), entradas "bagunçadas" (papel e fala), gerador e a demo (`demo/DEMO-0001`) |
| `eval/` | avaliação: golden set, red-team, A/B; relatórios em `eval/reports/`, resumidos em [`docs/resultados.md`](docs/resultados.md) |
| `scripts/` | demo de linha de comando, instalador, preparo dos ativos, tarefas, coleta de dados, custo, expurgo, varredura de PII |
| `tests/` | testes unitários e de contrato |
| `ativos/` | vídeo semissintético e série Sentinel-2 da gleba da demo, versionados com sha256 e licença ([`ativos/README.md`](ativos/README.md)) |
| `environment.yml`, `Dockerfile`, `docker-compose.yml` | ambiente conda-forge e imagem da demo (replay na porta 8000; Ollama opcional no perfil `ao-vivo`) |
| `infra/gcp/` | a mesma imagem descrita em Terraform para um ambiente gerenciado ([`infra/gcp/README.md`](infra/gcp/README.md)) |

## Dados e privacidade

Sem dado pessoal no repositório: o Fiscal-GO usa só campos públicos do Sicor (REF_BACEN mascarado pelo BCB,
sem CPF/CNPJ); casos, documentos, fotos e falas do golden set e da demo são sintéticos e marcados como tal. O
LLM e o VLM rodam local. CPF/CNPJ lidos de foto ou digitados pela fiscal saem só como máscara + hash com o sal
da instalação (fora do repositório, criado na primeira execução); a chave de acesso da NF-e, que embute o CPF
do emitente pessoa física, aparece só mascarada no estado, no trace e no laudo, e inteira só cifrada no cofre
da fiscalização. Os brutos de uma fiscalização podem ser cifrados com uma chave própria e expurgados apagando
a chave (`audit/cofre.py`, por comando). Entre fiscalizações ficam só dois índices, ambos só com hash: o de
fotos e o de documentos reutilizados (GTA e NF-e, gravado na selagem). Só duas consultas saem da máquina, sem
nome, documento, foto nem fala (o servidor de destino vê o IP de quem consulta): o satélite (catálogo da
Element84 e imagens Sentinel-2 no AWS Open Data) e o fundo do mapa da interface (tiles do OpenStreetMap). Base
legal, retenção e direitos do titular: [`docs/privacidade.md`](docs/privacidade.md). Prioridade de verificação
não é indício de irregularidade.

## Licença

Apache-2.0 (código, [`LICENSE`](LICENSE)). Os derivados do Sicor/BCB em `bench/` ficam sob **ODbL**
([`bench/fiscal_go/LICENSE`](bench/fiscal_go/LICENSE)); IBGE e Copernicus/Sentinel-2 com atribuição às fontes;
modelos, bibliotecas e vídeos com as licenças listadas em [`THIRD_PARTY.md`](THIRD_PARTY.md) e
`docs/modelos.md`.
