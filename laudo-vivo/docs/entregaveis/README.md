# Entregáveis do edital (AKCIT Camp 2026, §8.1) dentro do repositório

O edital exige os entregáveis no GitHub até o congelamento da entrega (24/10/2026, 15h30). **Esta pasta é a fonte
canônica** de BMC, pitches, Q&A, mercado e números: edite aqui. A pasta `negocio/`, fora do repositório, guarda o
plano de negócio de trabalho e o kit de validação e só aponta para cá (desde 09/10/2026 não há mais cópia; `make
entregaveis` não copia nada, só confere os números). Tudo o que a banca precisa ler para conferir um número está
dentro do repositório.

| Entregável (§8.1) | Arquivo | Observação |
|---|---|---|
| 1. Protótipo funcional do agente | código em `src/laudo/`, interface em `apps/web/`; como rodar no `README.md` | demo de 3 min: [`apps/web/ROTEIRO_DEMO.md`](../../apps/web/ROTEIRO_DEMO.md) (caso `DEMO-0001`, operação fictícia, 19 passos com a foto do DANFE, faixa e selo "DEMONSTRAÇÃO — dados sintéticos") |
| 1a. Demo gravada (≤ 3 min) | [`video/laudo-vivo-demo.mp4`](video/laudo-vivo-demo.mp4): 2:50, 1920x1080, legendas em pt-BR, tarja DEMONSTRAÇÃO (replay de uma gravação real) | roteiro, sha256 e como regravar em [`video/README.md`](video/README.md) |
| 2. Business Model Canvas | [`bmc-v1.pdf`](bmc-v1.pdf) (1 página A4 paisagem, gerado do HTML por `node scripts/gerar_pdf_bmc.cjs`), [`bmc-v1.md`](bmc-v1.md) e [`bmc-v1.html`](bmc-v1.html) | a v0 é a tese da inscrição; números de mercado conferidos por `scripts/py.sh scripts/checar_numeros_fixos.py` |
| 3. Pitch | [`pitch-regional-3min.md`](pitch-regional-3min.md) (regional, versões de 3 e 5 min); [`pitch-final-5min.md`](pitch-final-5min.md) (final); [`qa-banca.md`](qa-banca.md) (perguntas); [`KIT_APRESENTADOR.md`](KIT_APRESENTADOR.md) (papéis, demo cronometrada, contingências, checklist do dia; tempo estimado por `scripts/py.sh scripts/tempo_pitch.py`) | slides: [`deck/index.html`](deck/index.html) (16:9, sem rede) e [`deck.pdf`](deck.pdf), gerado por `node scripts/gerar_pdf.cjs` (regenerar depois da r4: [`deck/README.md`](deck/README.md)); ⚠ PREENCHER (equipe): o slide de Equipe |
| 4. Documentação do fluxo do agente | [`docs/fluxo_do_agente.md`](../fluxo_do_agente.md) (inputs, lógica, outputs, LGPD, observabilidade) | também [`docs/privacidade.md`](../privacidade.md) e [`docs/runbook.md`](../runbook.md) |

**Apoio aos entregáveis (onde a banca confere o que o pitch e o BMC dizem):**

| O quê | Arquivo | Observação |
|---|---|---|
| Mercado | [`mercado.md`](mercado.md) | cada número com tipo (fato, dado calculado, estimativa, hipótese), fonte e como conferir; custo e margem estimados na seção 8 |
| Decisão de produto | [`docs/decisao.md`](../decisao.md) | versão pública das decisões de 08/10 e de 16/10/2026 (o painel que as analisou foi de papéis simulados, sem pessoas de fora) |
| Validação (Problema) | [`validacao/README.md`](../../validacao/README.md) e [`validacao/fontes.yaml`](../../validacao/fontes.yaml) | o que o regulador, o auditor e o juiz escreveram e o que os microdados do BCB mostram; URL, data, o que prova e o que não prova |
| Consentimento | [`docs/tcle_modelo.md`](../tcle_modelo.md) | modelo de termo para entrevista e para filmagem, voz e teste (nenhuma entrevista registrada até 16/10/2026) |
| Evolução por rodada | [`CHANGELOG.md`](../../CHANGELOG.md) | r1 a r3 a partir dos relatórios datados; a r4 entra quando rodar |
| Números de palco | [`numeros.md`](numeros.md) / `numeros.json` | fonte única, gerada dos relatórios (abaixo) |
| Avaliação | [`eval/SLIDE.md`](../../eval/SLIDE.md), `eval/reports/` | slide único com n e IC 95% |
| Saída do agente (exemplo) | [`docs/exemplos/`](../exemplos/README.md) | laudo selado do caso `DEMO-0001` (operação fictícia, marca d'água "DEMONSTRAÇÃO — dados sintéticos") em HTML, JSON e PDF, com o pacote de exibição e a trilha item → evidência → checagem → trace; `scripts/py.sh docs/exemplos/conferir_exemplo.py` confere o selo; a versão está em `gerado_com.json` |
| Equipe e licenças | [`docs/EQUIPE.md`](../EQUIPE.md), [`LICENSE`](../../LICENSE), [`THIRD_PARTY.md`](../../THIRD_PARTY.md) | `EQUIPE.md` ainda é modelo a preencher |

**Os três congelamentos** (os textos usam sempre estes nomes):

| Nome | Quando | O que fica parado | Estado em 16/10/2026 |
|---|---|---|---|
| **Congelamento do teste** | 16/10/2026, 00:58 | o split de teste do golden set (`eval/golden/casos/SPLIT.yaml` com `congelado: true`; `sha256_split` `9e51b912…0f38`, conteúdo do teste `f47e4446…735dcd`; protocolo em `eval/README.md`) | **feito** |
| **Congelamento do código (r4)** | quando o lote de `src/` da onda 3 fechar (prazo: até 22/10/2026) | o `sha256(src/)` em que a avaliação r4 roda uma vez, com `--final`; as contingências, os replays e o vídeo da demo são gravados nesse código | a fazer |
| **Congelamento da entrega** | 24/10/2026, 15h30 | os entregáveis no GitHub (tag `regional-2026-10-24` e Release até 15h00) | a fazer |

"r4" é a **avaliação** final do regional. "Rodada 4" em textos de 09/10/2026 queria dizer outra coisa (as mudanças de
código feitas depois da r3); onde ainda aparecer, leia "revisão de 09/10".

**Números:** todo número de avaliação e de custo citado aqui vem de [`numeros.md`](numeros.md) / `numeros.json`,
gerados dos relatórios de uma mesma versão por `scripts/py.sh scripts/gerar_numeros.py`. Nos textos, os números
ficam entre marcadores invisíveis no GitHub (`<!--n:recall_teste.fmt-->1,00 [0,70–1,00] (9/9)<!--/n-->`);
`--aplicar` reescreve todos de uma vez (depois da r4, com a versão r4) e `--verificar` (no `make ci`) falha se algum
texto divergir da fonte, se o `eval/SLIDE.md` não for o dos mesmos relatórios ou se voltar um número antigo
conhecido.

**Frases:** `scripts/py.sh scripts/checar_frases_proibidas.py` (também em `make frases`, `make ci` e
`make entregaveis`) varre esta pasta, `validacao/`, o `README.md`, `docs/decisao.md`, `docs/privacidade.md`,
`docs/fluxo_do_agente.md`, `docs/runbook.md` e `../negocio/`, e falha se voltar uma frase da lista de
`../negocio/afirmacoes_proibidas.md` (memorando de 16/10/2026, seção 4): exclusividade que não verificamos,
acusação a operação real, comparação de crescimento numa série com quebra, persona sem fonte, entrevista que não
houve e o R$ 79 sem "preço-alvo". Acentos e maiúsculas não importam, e a forma negada que deixa a frase
certa ("ainda não testamos preço") passa. `--regras` mostra cada regra com o "diga no lugar". O script
acusa a frase e as variantes próximas, não o sentido: a leitura do pitch e do Q&A com a lista na mão continua
valendo (seção 0 da lista). O passo "Frases proibidas" do GitHub Actions (`.github/workflows/ci.yml`, na
raiz do repositório) é da área de Avaliação e roda a cada push e pull request que mexe no produto.

Marcadores **⚠ PREENCHER (equipe)** dependem só da equipe (nomes, entrevistas, cartas, vídeo) e trazem a frase
alternativa para o caso de o dado não existir no dia.
