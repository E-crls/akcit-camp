# Vídeo da demo (entregável 1: protótipo com demo gravada)

<!-- Gerado por scripts/gravar_video_demo.cjs: para mudar o texto, edite o script e rode --so-montar. -->

Gravação da interface do Laudo Vivo conduzindo os **19 passos** do roteiro da demo
([`apps/web/ROTEIRO_DEMO.md`](../../../apps/web/ROTEIRO_DEMO.md)) no caso `DEMO-0001`, uma **operação
fictícia** (dados sintéticos). É a demo gravada do edital e o Plano C do palco
([`docs/runbook.md`](../../runbook.md)): se a demo ao vivo e o replay falharem, este vídeo passa no lugar
(abra o arquivo no navegador ou no player, em tela cheia; a legenda já está no vídeo).

| Arquivo | O quê |
|---|---|
| [`laudo-vivo-demo.mp4`](laudo-vivo-demo.mp4) | o vídeo: 1920x1080, 25 fps, H.264 (libx264), sem áudio |
| [`legendas.srt`](legendas.srt), [`legendas.vtt`](legendas.vtt) | as legendas dos passos em arquivo |
| [`tempos.json`](tempos.json) | tempo de cada passo, esperas encurtadas e avisos da gravação |

| Campo | Valor |
|---|---|
| Duração | **2:53** (173,1 s) |
| Tamanho | 10,9 MB (10942482 bytes) |
| sha256 | `a76f09d1abc16570145bad58fea70b953d4927bee530b1e8515ff55da30ef406` |
| Gravado em | 17/10/2026 |
| Código | `sha256(src/)` `52be6b82…ce01` (o cálculo de `eval/harness.py`) |
| Modelo | qwen3.5:4b, replay de `replay_qwen35_4b.jsonl` do caso; 0 fora da gravação |
| Ferramentas | reais: contagem, regras, geofence, NDVI, política e selo rodando |
| Esperas encurtadas | nenhuma |
| Avisos | nenhum: cada passo mostrou o que o roteiro pede |

## O que o vídeo mostra e como foi feito

- **Tarja fixa** no topo, do primeiro ao último quadro: "DEMONSTRAÇÃO — dados sintéticos ·
  respostas do modelo reproduzidas de uma gravação real (replay)".
- A interface é a do protótipo, em **modo replay** (`scripts/rodar_demo.sh --replay`): as respostas do
  modelo local (a conversa e a leitura da foto do DANFE) vêm de uma gravação real do mesmo caso; a contagem do
  vídeo, as regras, a geofence, o NDVI (do cache), a política e o selo **rodam de verdade** na gravação.
  Nada foi editado na tela; nesta gravação não houve corte (a espera da contagem ficou abaixo do limite).
- Um **cartão de abertura** diz o que é a gravação; o **cartão final** traz os créditos e o link do
  repositório.
- Cada passo fica alguns segundos na tela, com uma **legenda curta** embaixo explicando o que acontece.

## Roteiro por tempo

| Tempo | Momento |
|---|---|
| 0:00 | Cartão de abertura |
| 0:05 | Carteira (mapa de GO e prioridades) |
| 0:09 | Fiscalização do caso DEMO-0001 aberta |
| 0:13 | 1 · Triagem e plano de método |
| 0:19 | 2 · Satélite (NDVI) |
| 0:25 | 3 · Declaração de independência |
| 0:28 | 4 · Vídeo do lote: contagem 12 de 29 (Divergente) e quadros-chave |
| 0:49 | 5 · Pressão “pode marcar 29” recusada (POL-07) |
| 0:55 | 6 · Foto do DANFE: o agente pede só o que faltou |
| 1:02 | 7 · A fiscal lê no papel só os campos pedidos |
| 1:08 | 8 · XML da NF-e confere com o papel |
| 1:13 | 9 · GTA com instrução embutida (POL-06), Divergente |
| 1:24 | 10 · Foto da cerca fora da gleba e mini-mapa |
| 1:36 | 11 · Rascunho bloqueado pela política (3 pendências) |
| 1:43 | 12 · Correção: foto de dentro da gleba |
| 1:48 | 13 · Justificativa da contagem |
| 1:52 | 14 · Justificativa da GTA |
| 1:56 | 15 · Rascunho emitido (hash raiz) |
| 2:02 | 16 · O agente não assina (POL-03) |
| 2:07 | 17 · Envio para assinatura |
| 2:11 | 18 · Assinatura humana (hash + PIN) |
| 2:20 | SELADO · ASSINADO e conferência do selo |
| 2:28 | Pacote de exibição BCB/Justiça |
| 2:37 | 19 · Laudo selado não muda (POL-04) |
| 2:44 | Cartão de créditos |

Os números da tela (contagem 12 de 29, foto a 649,9 m da borda, GTA emitida 4 dias antes da NF-e, 3 pendências
no bloqueio) são os do roteiro e foram conferidos pelo script durante a gravação: se um cartão ou um número
esperado não aparece, ele avisa e sai com código 1.

## Créditos e licença do vídeo

- **Vídeo de corredor do passo 4** (semissintético, `s03_fila_colada.mp4`, gerado por
  `eval/golden/visao/gerar_semissintetico.py`): recortes de [Cows at Dharmasthala (2025) 01][v03], de Gpkp
  ([CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0)), sobre um fundo de pasto de
  [Herding the cows video](https://commons.wikimedia.org/wiki/File:Herding_the_cows_video.webm), de Marie
  Nouvellon, via Flickr ([CC BY 2.0](https://creativecommons.org/licenses/by/2.0)). É obra derivada sob
  CC BY-SA 4.0 e aparece no vídeo (os quadros-chave da contagem); por isso **este vídeo é distribuído sob
  CC BY-SA 4.0**, com estas atribuições. Detalhes em [`THIRD_PARTY.md`](../../../THIRD_PARTY.md) e em
  [`eval/golden/visao/`](../../../eval/golden/visao/).
- Contém dados Copernicus Sentinel modificados (2026).
- Mapa: © colaboradores do OpenStreetMap (ODbL), com Leaflet (BSD-2-Clause). Malha municipal: IBGE. A
  carteira é derivada de microdados públicos do Sicor/BCB (ODbL) e traz o aviso "prioridade de verificação
  não é indício de irregularidade".
- Caso `DEMO-0001`: operação fictícia (REF `000000001`, cooperativa fictícia); vídeo, fotos, NF-e, GTA
  e falas sintéticos. Nenhuma tela aponta irregularidade de produtor real.
- Código do Laudo Vivo: Apache-2.0. Repositório: https://github.com/E-crls/akcit-camp (pasta `laudo-vivo`).

[v03]: https://commons.wikimedia.org/wiki/File:Cows_at_Dharmasthala_(2025)_01.webm

## Como regravar

Na raiz do `laudo-vivo` (Git Bash ou PowerShell), com o ambiente do README instalado e os ativos da
demo preparados (vídeo do corredor, cache do satélite e detector:
[`ativos/README.md`](../../../ativos/README.md)), o Edge (ou o Chrome), o Node 18+, o `playwright-core`
(só a biblioteca: o navegador é o instalado) e um ffmpeg com libx264 e libass no PATH:

```bash
node scripts/gravar_video_demo.cjs                 # sobe o replay numa porta livre, grava, monta e fecha tudo
node scripts/gravar_video_demo.cjs --ritmo 0.3     # ensaio rápido (pausas de leitura mais curtas)
node scripts/gravar_video_demo.cjs --so-montar     # só remonta o .mp4 e as legendas a partir do último bruto
node scripts/gravar_video_demo.cjs --help          # todas as opções
```

O script não baixa nada: usa o navegador instalado (`channel: "msedge"`) e, se o Playwright não tiver o
ffmpeg dele, aponta o `recordVideo` para o ffmpeg do sistema. O vídeo bruto, o log do servidor e as
legendas em ASS ficam em `dados_locais/video_demo/` (fora do git). Leva uns 5 minutos: ~3,5 de gravação,
em tempo real, e ~1 de montagem. Depois de regravar, este README, as legendas e o `tempos.json` saem
atualizados, com o sha256 novo.
O `.gitignore` do projeto ignora `*.mp4`, com uma exceção para esta pasta: o vídeo entra no git.

Para conferir a olho, extraia alguns quadros (a tarja, a legenda e o SELADO no fim):
`ffmpeg -i docs/entregaveis/video/laudo-vivo-demo.mp4 -vf fps=1/20 dados_locais/video_demo/quadro_%02d.png`
