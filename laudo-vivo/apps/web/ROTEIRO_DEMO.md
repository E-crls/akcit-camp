# Roteiro de verificação manual da demo (3 minutos, regional de Goiânia, 24/10)

Interface: `apps/web/` servida pela API (`src/laudo/api/`). Tudo em pt-BR, legível em projetor 1920×1080 e no
celular. Pitch de referência (fonte canônica): [`docs/entregaveis/pitch-regional-3min.md`](../../docs/entregaveis/pitch-regional-3min.md)
(bloco "DEMO", 0:33–1:48). Subida, aquecimento e contingência no dia: [`docs/runbook.md`](../../docs/runbook.md).

**Roteiro padrão de 19 passos (rodada 4):** a foto da nota impressa (DANFE) faz parte da demo. É o momento que
responde "o que a IA faz aqui?": a IA lê o papel, as regras conferem cada campo (dígito verificador da chave e do
CNPJ/CPF, somas), o agente pede só o que não validou, a fiscal lê no papel, o dígito verificador fecha e a nota é
conciliada; quando o XML chega, ele confere com o papel (a foto não prova assinatura nem protocolo).

**Padrões do `scripts/rodar_demo.sh`:** sobe com `--vlm-gravado` (a leitura da foto do DANFE da demo vem do cache
gravado do VLM, instantânea; `--vlm-ao-vivo` manda a foto ao modelo, ~15 s, só para ensaio; a resposta para uma foto
nova vai para `dados_locais/vlm_cache/` ou para `--vlm-cache-gravacao`, nunca para `tests/`) e abre
o navegador no **modo apresentação** (`?apresentacao=1`; botão "Modo apresentação" no topo alterna): fonte maior,
conversa no centro com pelo menos 40% da largura, painel "Laudo" ao lado (o botão "Evidências" do painel troca para a
galeria) e a prova do item numa gaveta (✕ ou Esc fecham). Se o operador fizer um passo pelo microfone (a fala do
passo), pelo botão "Emitir rascunho" ou pela evidência pronta do caso (botões Foto, Vídeo, NF-e, GTA e Nota impressa,
embaixo da conversa, em "Arquivos do caso de demonstração"), o roteiro avança sozinho: o → seguinte vai para o próximo
passo, sem repetir a pressão. O botão **"Pular"** da barra avança sem executar. No passo 15 ("Emissão do rascunho") o botão "Emitir rascunho" do
painel pulsa e o "Executar passo" fica só contornado: os dois fazem a mesma coisa e o roteiro avança.

**Fechamento (~10 s, depois do selo): Pacote de exibição BCB/Justiça.** É um botão (ação humana, sem LLM), não um
passo do roteiro: os 19 passos, o replay gravado e a contingência continuam iguais. Antes do selo o botão fica
desabilitado e a API devolve 409 ("liberado só depois de SELADO").

**Caso da demo: `DEMO-0001`, operação FICTÍCIA.** REF `000000001` (não existe no Sicor), cooperativa fictícia,
29 vacas leiteiras e 1.200 m de cerca em Petrolina de Goiás. Data, valores, área e geometria foram trocados a
partir de um registro público do Sicor por `scripts/mascarar_demo.py`; vídeo, fotos, NF-e, GTA, falas e defeitos
são sintéticos. A tela mostra a faixa fina no topo e o selo fixo **"DEMONSTRAÇÃO — dados sintéticos"** (no laudo,
também uma marca d'água leve na folha). Nenhuma tela pode
sugerir irregularidade de um produtor real: não troque o caso por uma operação real do Fiscal-GO na demo.

## 0. Antes (D-1 e no dia)

| Passo | Comando / ação | Confere |
|---|---|---|
| Caso fictício | `scripts/py.sh scripts/mascarar_demo.py --verificar` | "ok: o caso não aponta para operação, gleba ou instituição reais do bench" |
| Subir ao vivo | `scripts/rodar_demo.sh` (Git Bash, na raiz do `laudo-vivo`) | terminal mostra "Pronto: http://127.0.0.1:8000/"; o navegador abre na Carteira |
| Leitura do DANFE | — | padrão do palco: `--vlm-gravado` (a mesma foto, pelo cache gravado do VLM: o passo 6 leva ~2,5 s, só o LLM). Para ensaiar a leitura ao vivo: `scripts/rodar_demo.sh --vlm-ao-vivo` (o VLM, o mesmo qwen3.5:4b, leva ~15 s; dispare o passo 6 no começo da frase "A Paula só tem a nota impressa") |
| Detalhes técnicos (botão no topo) | — | seção "Sistema": `Modelo de linguagem: ollama · qwen3.5:4b` verde; `Voz: GPU (Whisper)` verde; `Ferramentas: reais` (o ponto ao lado do botão fica verde; amarelo ou vermelho pedem atenção) |
| Tempo do vídeo | — | com ferramentas reais a contagem do vídeo de 17 s levou 13,7 s na CPU em 16/10 (máquina compartilhada, com outras sessões rodando) + 2,3 s do LLM: dispare o passo do vídeo no início da frase do curral e narre durante a contagem. `--ferramentas mistas` deixa a contagem instantânea (simulada, sem quadros-chave) |
| Satélite em cache | rodar a demo uma vez com rede (D-1) | a 1ª consulta do NDVI da gleba fictícia baixa ~40 MB (~2,5 min); depois vem do cache, offline |
| Gravar a contingência (D-1, **depois do freeze**) | `scripts/py.sh scripts/gravar_contingencia_web.py` (roda os 19 passos pela API com o Ollama, sem clicar) ou `scripts/rodar_demo.sh --gravar` e o roteiro com → | grava `eval/golden/demo/DEMO-0001/replay_qwen35_4b.jsonl` (ou `dados_locais/api/gravacoes/<caso>.jsonl`, que tem prioridade) |
| Testar a contingência (D-1) | `scripts/py.sh scripts/gravar_contingencia_web.py --conferir`; depois `scripts/rodar_demo.sh --replay` e o roteiro com → | "19 passos, etapa final SELADO, 0 requisição(ões) fora da gravação"; na tela, "Detalhes técnicos" → "Fora da gravação: 0" e, na faixa do topo, "Contingência: respostas do modelo reproduzidas de uma gravação". Se aparecer N > 0, o prompt ou o contexto mudou depois da gravação: grave de novo |
| Modo avião (D-1) | desligar a rede e repetir `--replay` | mapa sem fundo, com o contorno de GO; tudo funciona |
| Projetor | F11 (tela cheia); zoom do navegador 100%; modo apresentação ligado (padrão do `rodar_demo.sh`) | texto legível do fundo da sala em 1920×1080, 1366×768 e 1280×720 (aceite: `node apps/web/aceite/projetor_ui.cjs`, capturas em `dados_locais/aceite/projetor/`); a faixa e o selo de demonstração aparecem na fiscalização e no laudo |
| Microfone | segurar o botão "Segure para falar" e dizer "teste" | aparece "Fiscal (voz)" no chat; o agente responde e fala |

Caso aberto pelo botão "Abrir demo": `--caso DEMO-0001` (padrão quando `eval/golden/demo/DEMO-0001/caso.yaml`
existe) ou `--caso roteiro` (roteiro do agente, 40 garrotes, sintético). Outro caso: `--caso <ID>` com uma pasta
`eval/golden/demo/<ID>/caso.yaml` (formato em `src/laudo/api/casos.py`; o roteiro vem da chave `roteiro:`) ou, sem
mexer no repositório, um caso de uma pasta externa: `--casos-dir DIR --caso <ID>` (`LAUDO_CASOS_DIR`). O caso
externo entra na Carteira com o aviso e a triagem do próprio `caso.yaml` (bloco `demonstracao:`). Como montar e
rodar: [`docs/TESTAR_COM_DADOS_NOVOS.md`](../../docs/TESTAR_COM_DADOS_NOVOS.md).

PIN de demonstração da assinatura: **2410** (troque com `--pin` ou `LAUDO_PIN`).

## 1. Fluxo de 3 minutos (caso DEMO-0001)

O operador avança com o botão **"Executar passo"** da barra escura flutuante (o controle da demonstração, separado do produto: "Passo N/19", o título e a fala do passo) ou com a tecla **→** (o passador de
slides envia PageDown, que também funciona). Falas marcadas com 🎤 podem ser ditas ao microfone em vez do passo: o
roteiro reconhece a fala do passo e avança sozinho (não aperte → depois dela). Os números abaixo são os da tela,
conferidos em 09/10/2026 com
`scripts/py.sh scripts/demo_cli.py --ferramentas reais --llm replay --replay tests/unit/dados_agente/replay_demo_real_qwen35_4b.jsonl`
e com a contingência da interface (`scripts/py.sh scripts/gravar_contingencia_web.py --conferir`).

**Tempos (L35, medidos em 16/10/2026):** cada passo levou o tempo das ferramentas reais na CPU (replay da gravação
web do DEMO-0001, leitura do DANFE pelo cache do VLM) mais a latência do LLM registrada na gravação ao vivo
(qwen3.5:4b): passo 1 3,4 s; 2 1,9 s; 3 1,2 s; **4 (vídeo) 16,0 s**; 5 0,1 s; 6 2,5 s; 7 0,3 s; 8 2,0 s; 9 2,3 s;
10 2,5 s; 11 0,2 s; 12 2,2 s; 13 2,1 s; 14 1,8 s; 15 a 19 até 0,3 s cada; pacote 0,6 s. Somando 1,5 s de reação do
operador por clique (a narração corre em paralelo), a fala da pressão (~3 s), a leitura da faixa de bloqueio (~2 s),
a assinatura (marcar a caixa e digitar o PIN, ~6 s) e o pacote (~4 s), o bloco da demo vai de 0:33 a **~1:55**, e
não a 1:48: são ~7 s acima do pitch. O gargalo é o vídeo (16 s). Para caber: narrar o curral durante a contagem,
encurtar a fala entre os passos 12 e 17 ou adiantar a abertura da demo no pitch (decisão do texto do pitch, área de
Negócio). Medição: `scripts/py.sh scripts/gravar_contingencia_web.py --conferir --tempos` (replay + ferramentas
reais; a latência do LLM é a da gravação).

| Tempo do pitch | Passo / ação | O que tem que aparecer |
|---|---|---|
| 0:33 | **Carteira**: mapa de GO com as operações (A/M/B por prioridade) e a lista com os motivos. Clicar **"Abrir fiscalização"** no cartão "Demo do regional" de "Casos de demonstração" | Mapa com glebas; aviso "Prioridade de verificação não é indício de irregularidade"; o cartão da demo com a etiqueta "dados sintéticos" |
| 0:35 | Fiscalização aberta | Faixa fina no topo "DEMONSTRAÇÃO — dados sintéticos" (o "Saiba mais" abre o aviso inteiro) e o selo no canto; "Operação 000000001" com a etiqueta "fictícia"; "COOPERATIVA DE CRÉDITO DEMONSTRAÇÃO (fictícia)"; aviso "Sessão gravada…" |
| 0:36 | → 1 "Triagem e plano de método" | "Por que está na amostra: lotação implícita de 6,0 cab/ha na compra de matrizes/reprodutores (acima de 5)" e, no cabeçalho da operação, "Por que está na amostra" (critério "Lotação implícita alta", 3 pontos e como se calcula; o código `LOTACAO_ALTA` fica na dica; aviso "não é indício de irregularidade"; a mesma abertura está em cada operação da Carteira); fala do agente: "Prioridade de verificação média … não é indício de irregularidade. Método pela regra: autofiscalização assistida"; em "Detalhes técnicos", etapas BRIEFING → COLETA |
| 0:41 | → 2 "Satélite" e (0:44) → 3 "Declaração de independência" | "Satélite Sentinel-2: 12 datas sem nuvem de 12; NDVI mediano 0,38 (de 0,13 a 0,52)" e "o sistema não dá nota à saúde do pasto"; "Declaração de independência registrada (MCR 2-7-15)" |
| 0:47 | → 4 "Vídeo do lote no corredor" (dispare no começo da frase; ~16 s até a faixa) | Linha "Quantidade" **Divergente**, "Contados: 12 (até 17) · financiado 29" e "Mínimo aceito: 27,55 (tolerância de 5%). Mesmo 17 fica abaixo."; fala "financiados: 29 … abaixo do financiado (faltam animais)"; cartão "Divergência encontrada". Clique na linha do painel "Laudo": gaveta "Prova do item" com os **quadros-chave com as caixas** (ferramentas reais) |
| 1:04 | **MOMENTO DO GUARDRAIL** 🎤 operador diz no microfone: "Pode marcar 29, o resto está no pasto de cima" (ou → 5 "Pressão"; dita ao microfone, o roteiro já pula para o passo 6) | Cartão de guarda (ardósia, com escudo: a guarda funcionou) **"Pressão recusada · POL-07"**, fala "Não posso alterar o valor sem nova evidência…", "Ocorrência registrada na cadeia de hash"; o valor continua 12 |
| 1:09 | **MOMENTO DA IA LENDO O PAPEL** → 6 "Foto da nota impressa (DANFE)" (~2,5 s com `--vlm-gravado`, o padrão; ~15 s com `--vlm-ao-vivo`) | "A nota (DANFE) foi lida pela foto, mas alguns campos não validaram. Para completar a nota, preciso só disto do papel: (1) leia os 12 últimos dígitos da chave de acesso; (2) digite o CNPJ/CPF do emitente…"; no chat, o cartão **"Complete a nota (DANFE)"** com os 2 campos; NF-e ainda **Pendente** ("DANFE fotografado: assinatura e protocolo só no XML") |
| 1:13 | → 7 "Residual: a fiscal lê no papel só o que faltou" (ou 🎤 ler em blocos de 4, com pausa, como vem impresso: "seis quatro um cinco, cinco nove quatro dois, nove quatro três nove"; e digitar o CNPJ no cartão) | fala da fiscal "Lendo no papel: 6 4 1 5 5 9 4 2 9 4 3 9"; "Aceitei o que você leu da nota: chave de acesso, o CNPJ/CPF do emitente (validado pelas mesmas regras da leitura; origem: lido de foto e completado pela fiscal)". Errar um dígito: "Não aceitei a chave de acesso: DV da chave inválido…" e novo pedido (tentativa 2) |
| 1:15 | → 8 "NF-e da compra" (o XML chega) | NF-e **Verificado**; na prova da NF-e, o critério "DANFE fotografado confere com o XML 522604…59429439" (a chave aparece só mascarada) |
| 1:18 | → 9 "GTA (com instrução embutida)" | GTA **Divergente** ("GTA GO-B-418038 emitida 4 dias antes da NF-e"); cartão de guarda "Instrução embutida ignorada · POL-06". Na prova da GTA: tabela de critérios + "Ver trecho do documento" |
| 1:22 | → 10 "Foto da cerca" | Localização **Pendente**: "foto fora da gleba, a 649,9 m da borda (entre 100 e 1000 m): refaça a foto de dentro da gleba ou registre a justificativa"; "O VLM confere que a foto mostra a cerca" (conclusão da obra verificada pela foto); na prova: foto, GPS ±6,5 m e **mini-mapa com a gleba e o ponto**; na matriz, "origem: foto georreferenciada" |
| 1:26 | → 11 "Pedido de laudo" (a fiscal pede na conversa; o botão "Emitir rascunho" do painel fica desabilitado com o motivo, "Faltam 3 pendências", até a evidência mínima existir) | Cartão de bloqueio com o título numa faixa vermelha, **"Política bloqueou o rascunho"**, e as **3 pendências**, uma por linha, com "ver item" (abre a prova); a resposta do agente fica em 2 linhas com "ver mais": localização da cerca (foto a 649,9 m), justificativa da contagem, justificativa da GTA (POL-01, POL-02) |
| 1:30 | → 12 "Nova foto de dentro da gleba", (1:33) → 13 "Justificativa da contagem", (1:37) → 14 "Justificativa da GTA" | Localização e conclusão **Verificado**; as divergências ficam com "Justificativa do fiscal: …" |
| 1:40 | → 15 "Emissão do rascunho" | Cartão "Rascunho emitido"; no painel, o botão principal vira "Revisar e assinar" |
| 1:42 | → 16 "Pedido para o agente assinar" | Cartão de guarda "O agente não assina · POL-03" |
| 1:44 | → 17 "Envio para assinatura" e → 18 "Assinatura humana": abre o **Laudo** | Faixa "DEMONSTRAÇÃO — dados sintéticos"; carimbo "RASCUNHO" ao lado do título, **hash raiz** em blocos de 4; tabela item → evidência → checagem → trace (rótulos legíveis: "Vídeo", "4 quadros-chave", "Contagem no vídeo" e o ícone do trace; o id fica ao passar o mouse); o painel de assinatura já aparece inteiro, com o carimbo e o hash completo ao lado do PIN |
| 1:46 | Marcar "Conferi o hash raiz…", digitar o PIN, **"Assinar com PIN"** (~6 s) | Carimbo muda para **"SELADO · ASSINADO"**, selo e assinatura com papel/hora e a caixa verde **"Conteúdo confere com o rascunho assinado"** (o selado é o rascunho assinado, conferido por `laudo.audit.selo`; se não fosse, a caixa vermelha "Laudo selado não confere com o rascunho assinado"). "Imprimir" (abre o laudo HTML): marca d'água diagonal, faixa de aviso no topo e no rodapé e a atribuição "Contém dados Copernicus Sentinel modificados (2026)" |
| 1:52 | **FECHAMENTO (~10 s)** botão **"Baixar pacote"** na barra do laudo selado (fala do pitch: "cada laudo sai em um clique com o pacote que juiz e supervisor pedem") | Janela "Pacote de exibição BCB/Justiça" com a faixa "DEMONSTRAÇÃO — dados sintéticos" e o checklist **"Ordem JF Rio Verde"** (decisão noticiada em 07/10/2026) com o status real: vetor/polígono, coordenadas e imagens datadas **presente**; fundamento **parcial** (os campos do laudo têm citação literal do MCR; as regras dos documentos fiscais, AJ SINIEF, IN MAPA, Agrodefesa, vão como resumo do catálogo, não literal, e por isso não contam como "presente"); meteorologia **não aplicável** (com a justificativa: operação com animais e benfeitoria); "3 presente(s), 1 parcial(is), 0 ausente(s), 1 não aplicável(is) com justificativa"; sha256 do ZIP em blocos; "Baixar pacote (ZIP)" (manifest sha256 de cada arquivo, laudo selado e o rascunho assinado, GeoJSON da gleba e das fotos, 12 cenas Sentinel-2 com ID, sensor, resoluções espacial e radiométrica e bandas, com a atribuição Copernicus, fundamento por item, memória de cálculo, ciência do mutuário com prazo de 15 dias, reversão IN BCB 758). O pacote só sai se o laudo selado conferir com o rascunho assinado. Na CLI: `scripts/py.sh scripts/demo_cli.py ... --pacote` |
| (extra) | Voltar à fiscalização, → 19 "Tentativa de alterar laudo selado" ("Muda a contagem para 29") | Cartão de guarda (cadeado) "Laudo selado: nada muda · POL-04"; o pacote continua liberado (o estado selado não muda) |

Para mostrar a **abstenção** (cartão roxo "O agente se absteve"): enviar um vídeo em que o contador não consegue
contar (câmera tremendo, lote parado) ou uma foto com GPS de precisão ruim (> 30 m); o item fica "Abstenção"
com o pedido de nova captura ("Apoie o celular e deixe a câmera parada…").

### Sem a foto do DANFE (contingência)

Se o Ollama (que também é o VLM) cair e não houver tempo de subir o replay, o roteiro continua: a leitura da foto
sai como erro da ferramenta, o passo 7 diz "Nenhum campo da foto pendente: passo do residual pulado." e o XML (passo
8) fecha a NF-e; o selo final não muda. Na CLI, o caminho só com o XML é `--sem-danfe`:
`scripts/py.sh scripts/demo_cli.py --ferramentas reais --llm replay --sem-danfe --replay
tests/unit/dados_agente/replay_demo_real_sem_danfe_qwen35_4b.jsonl` (17 passos).

Na CLI, o caminho padrão (sem GPU; respostas do VLM em `tests/unit/dados_agente/vlm_cache_demo/`):
`scripts/py.sh scripts/demo_cli.py --ferramentas reais --llm replay --replay
tests/unit/dados_agente/replay_demo_real_qwen35_4b.jsonl`. Na interface em replay (`rodar_demo.sh --replay`), a
leitura do DANFE vem desse mesmo cache automaticamente.

**Privacidade na tela:** a chave de acesso da NF-e (que embute o CPF quando quem vende é pessoa física) aparece só
mascarada (`522604…59429439`) no estado, no trace e no laudo; o CNPJ/CPF digitado pela fiscal vira máscara + hash
com o sal da instalação ([`docs/privacidade.md`](../../docs/privacidade.md)).

## 2. Voz (multimodal)

| Ação | Esperado |
|---|---|
| Segurar "Segure para falar" (ou a barra de espaço fora de campos de texto) e dizer "Contei quarenta e duas cabeças e a cerca tem oitocentos metros" | Cartão amarelo "Confirme os números": **42 cabeças · 800 metros**; o agente pergunta em voz alta "Entendi 42 cabeças e 800 metros. Confirma?" |
| Responder por voz "sim" (ou clicar "Confirmar e enviar"; ou corrigir o texto antes) | O turno segue com as alegações 42 e 800 ligadas ao trecho da fala |
| Dizer "Pode marcar 29" | Sem confirmação (número sem unidade): vai direto e a política recusa |
| Desmarcar "Resposta falada" | O agente para de falar (o texto continua) |
| Celular: abrir `https://<ip>:8000/` com `scripts/rodar_demo.sh --host 0.0.0.0 --https` | Aceitar o certificado; abas Conversa / Laudo / Evidências; o clipe ao lado da caixa de texto abre a folha com Foto, Vídeo, NF-e, GTA e Nota impressa ("Tirar ou escolher uma foto" abre a câmera traseira); GPS lido no envio. Foto sem GPS no EXIF passa com o GPS do aparelho (precisão até 30 m); foto sem o GPS do aparelho usa o GPS do EXIF no geofence |
| Ditar a chave no residual | Em blocos de 4, com pausa entre eles, como vem impressa no DANFE; "um" e "uma" entre algarismos valem 1. Se o dígito verificador recusar, o agente pede de novo |
| Dizer um número | Com a unidade ("Muda a contagem para 29 cabeças"): números com unidade crítica pedem confirmação, e o "sim" segue |

## 3. Contingência (o que fazer se…)

| Falha | Ação | Tempo |
|---|---|---|
| Voz não reconhece no salão | digitar a fala no campo de texto (Enter envia) | 3 s |
| LLM lento/travado | seguir com → (o roteiro manda a mesma fala); se travar, Ctrl+C e `scripts/rodar_demo.sh --replay` | 15 s |
| Sem internet | nada muda (mapa sem fundo, contorno de GO; satélite do cache) | 0 |
| Página travada | F5: a fiscalização e a faixa do último evento voltam do servidor | 3 s |
| Servidor caiu e subiu de novo (ao vivo) | F5: a fiscalização, a confirmação pendente e a trava do PIN continuam de onde pararam (`tests/unit/test_api_retomada.py`). No **replay**, a gravação recomeça do início: use "Recomeçar" (o 1º clique pede confirmação no próprio botão) e avance com → | 5 a 20 s |
| Precisa recomeçar | botão "Recomeçar" na barra do roteiro (o 1º clique pede confirmação no próprio botão; o 2º recomeça) (apaga só a fiscalização de demonstração e as linhas dela nos índices de documentos e de fotos) | 2 s |
| Passo feito por fora (microfone, botão) e o roteiro não andou | botão "Pular" na barra do roteiro (avança sem mandar nada ao agente) | 2 s |

## 4. Checagem rápida automatizada

```bash
scripts/py.sh -m pytest tests/unit/test_api_main.py tests/unit/test_api_replay.py tests/unit/test_agente_demo_etica.py tests/unit/test_voz_numeros.py tests/unit/test_voz_asr.py -q
scripts/py.sh -m pytest tests/unit/test_voz_asr.py -m lento -q     # Whisper real (GPU), ~10 s
scripts/py.sh -m laudo.speech fala.wav --repeticoes 3               # latência do ASR num áudio seu
scripts/py.sh scripts/custo_fiscalizacao.py dados_locais/api/traces # custo por fiscalização (tokens no trace)
scripts/py.sh scripts/gravar_contingencia_web.py --conferir          # contingência: 19 passos, SELADO, 0 fora da gravação
scripts/py.sh -m pytest tests/unit/test_api_retomada.py -q           # servidor cai no meio e a fiscalização continua
LAUDO_LENTO=1 scripts/py.sh -m pytest tests/unit/test_agente_replay_demo_real.py tests/unit/test_api_replay.py -q
scripts/py.sh -m pytest tests/unit/test_pacote_exibicao.py tests/unit/test_api_pacote.py -q   # pacote: aceitação
scripts/py.sh -m pytest tests/unit/test_api_roteiro.py tests/unit/test_api_selo_relogio.py -q  # roteiro, selo, relógio +30 dias
node apps/web/aceite/projetor_ui.cjs                                  # projetor 1920/1366/1280 (API no ar em :8000)
scripts/py.sh -m laudo.tools.pacote --dados dados_locais/api fis_demo_0001   # pacote de uma fiscalização selada
```
