# Slides do pitch regional (deck 16:9)

`index.html` é o deck do pitch de 3 minutos (regional de Goiânia, 24/10/2026), em HTML 16:9 (1920×1080) que
funciona sem rede: CSS e script dentro do arquivo, imagens em `img/`, fontes do sistema. `../deck.pdf` é a
versão para entregar no GitHub, gerada deste HTML pelo `scripts/gerar_pdf.cjs`. A fala é a de
[`../pitch-regional-3min.md`](../pitch-regional-3min.md) (fonte canônica); o deck só mostra o que a banca
precisa ver enquanto o orador fala.

## As 7 telas

| Tela | No pitch (versão A) | Critério | O que mostra |
|---|---|---|---|
| 1 | S1, 0:00–0:21 | Problema | norma em vigor (Res. CMN 5.267), liminar da JF de Rio Verde/GO noticiada em 07/10/2026 (sem número de processo nem nome de parte), o que o satélite não fecha, a persona Paula com o rodapé "persona composta de fontes públicas" |
| 2 | S2, 0:21–0:33 | Validação | o que o regulador e o auditor escreveram e os 3 números do Sicor (chaves `desc.*`, com a data de corte e a versão do arquivo do BCB) |
| 3 | demo, 0:33–1:48 | Solução e IA | a frase-padrão ("a IA lê o papel e a fala; as regras, sem IA, decidem; o humano assina") e quatro capturas da demo, com a marca "DEMONSTRAÇÃO — dados sintéticos": leitura do DANFE, pressão recusada, bloqueio do rascunho, selo humano. É a tela de apoio da demo ao vivo e o plano B se ela travar |
| 4 | S3, 1:48–2:17 | Solução e IA | o slide único de avaliação: teste congelado (n, IC 95%), red-team, sem o LLM, A/B v2 nas duas comparações e o tempo modelado, com as ressalvas no rodapé |
| 5 | S4, 2:17–2:38 | Diferencial | tabela Audsat, Softfocus, Olho do Dono e credenciada com prancheta × onde entramos (somar, nunca atacar) |
| 6 | S5, 2:38–2:50 | Equipe | **⚠ PREENCHER (equipe)**: único marcador do deck, com a instrução de preenchimento no próprio slide |
| 7 | S6, 2:50–2:59 | Pitch / Viabilidade | modelo de negócio (quem paga, como cobra, custo de IA medido) e o pedido |

## Apresentar

Abra `index.html` no Edge ou no Chrome e aperte **F** (tela cheia) ou F11. Avança com →, PageDown (o passador
de slides), espaço ou clique no terço direito; volta com ←, PageUp ou clique no terço esquerdo; Home e End vão
para a primeira e a última tela; `index.html#4` abre direto na tela 4. A demo roda em outra janela (o passador
também manda PageDown para ela): troque de janela com Alt+Tab antes de apertar o passador.

## Números: só entre marcadores

Todo número de avaliação, de custo e do Sicor que aparece numa tela vem de `docs/entregaveis/numeros.json` e
está entre marcadores `<!--n:chave-->…<!--/n-->`, no formato de `scripts/gerar_numeros.py`. O deck está na lista
`ALVOS` desse script: `--verificar` (no `make ci`) falha se um número do deck divergir da fonte, e `--aplicar`
reescreve todos. Fora dos marcadores ficam só identificadores e datas (Res. CMN 5.267, MCR 2-7, Voto 166/2025,
motivo 013, DEMO-0001, datas de norma e de notícia) e, no slide da equipe, o texto do marcador.

Ficaram **fora das telas**, porque não estão em `numeros.json`: o preço-alvo de R$ 79, o piso de R$ 669 por
visita (AEA-MS), os 525 mil itens físicos e a participação do gado nas operações de Goiás. O orador continua
falando esses números (pitch, S1 e S4); para pô-los numa tela, primeiro é preciso criar a chave no
`gerar_numeros.py` (área de Avaliação).

## Depois da r4 (regenerar)

1. A r4 termina com `scripts/py.sh scripts/gerar_numeros.py --data <data da r4> --sufixo _r4 --aplicar
   --fixar-palco` (o `eval/rodada_r4.py` já faz isso): como o deck está nos `ALVOS`, os números do
   `index.html` são trocados junto com os do pitch, do Q&A e do BMC. Se o deck entrou nos `ALVOS` depois que
   esse passo rodou, rode `scripts/py.sh scripts/gerar_numeros.py --aplicar` (sem `--data`: usa a versão de
   palco de `eval/reports/palco.json`).
2. Gere o PDF de novo: `node scripts/gerar_pdf.cjs` (escreve `docs/entregaveis/deck.pdf`; usa o Edge
   instalado e o `playwright-core` de `../../personas-ux/app/node_modules`, ou de `PLAYWRIGHT_CORE_DIR`, ou de
   `NODE_PATH`). O script para com código 1 se alguma tela transbordar 1920×1080, se uma imagem não carregar
   ou se o deck pedir algo da rede, e avisa se o slide da equipe ainda tem `[[EQUIPE: …]]`.
3. Confira: `scripts/py.sh scripts/gerar_numeros.py --verificar` (0 problemas) e
   `scripts/py.sh scripts/checar_frases_proibidas.py` (0 frases).
4. Olhe as telas: `node scripts/gerar_pdf.cjs --png dados_locais/deck_png` grava uma PNG por tela com a mesma
   renderização do PDF. Abra cada uma (as telas 2, 4 e 7 mudam de número; as outras, não).

Com o slide da equipe preenchido, repita os passos 2 a 4.

## Imagens

`img/demo-*.png` são recortes das capturas da interface redesenhada da demo `DEMO-0001`, de 17/10/2026: a
demo em replay da gravação real (qwen3.5:4b, ferramentas reais), em 1440×900, sem modo apresentação. As
capturas estão em `dados_locais/auditoria/ui/interface_nova_desktop/` (fora do git); a da prova da NF-e foi
feita depois do passo 8 (clique na linha "Comprovante fiscal (NF-e)" do painel "Laudo"). Recortes com o
Pillow, em pixels da captura de 1440×900; na tela, cada recorte aparece a 1,2× (`width` e `height` do
`index.html`):

| Arquivo | Captura | Caixa (x0, y0, x1, y1) |
|---|---|---|
| `demo-papel-pedido.png` | `d_fis_06.png` (cartão "Complete a nota (DANFE)") | 354, 492, 857, 640 |
| `demo-papel-xml.png` | `d_fis_08_prova_nfe.png` (critério "integridade") | 353, 557, 929, 595 |
| `demo-pressao.png` | `d_fis_05.png` (cartão "Pressão recusada") | 312, 542, 945, 651 |
| `demo-bloqueio.png` | `d_fis_11.png` (cartão "Política bloqueou o rascunho") | 312, 453, 945, 552 |
| `demo-selado-carimbo.png` | `d_laudo_selado.png` (carimbo da folha do laudo) | 142, 552, 325, 623 |
| `demo-selado-hash.png` | `d_laudo_selado.png` ("Hash raiz assinado") | 335, 530, 892, 645 |

Os cartões são os da conversa (a interface não tem mais faixa no topo da conversa); o carimbo e o hash são os
da folha do laudo selado, porque o carimbo da barra do laudo aparece coberto pelo aviso "Laudo assinado e
selado." na captura. Se a interface mudar o que esses cartões dizem, recapture (a demo em replay numa porta
livre) e refaça os recortes. Toda captura do deck leva o selo "DEMONSTRAÇÃO — dados sintéticos"; nenhuma
mostra operação real.
