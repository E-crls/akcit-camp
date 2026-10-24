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
o navegador no **modo apresentação** (`?apresentacao=1`; o menu do usuário, no canto superior direito, alterna): tudo
maior na mesma proporção, a conversa no centro com pelo menos 40% da largura, o painel "Laudo" ao lado e a prova do
item numa gaveta ("Ver prova"; ✕ ou Esc fecham). Na demonstração o papel segue a tela: na Carteira e no Laudo selado
o topo mostra "Vendo como Paulo (fictício) · Analista"; na fiscalização e em "Revisar e assinar", "Vendo como Ana (fictícia) ·
Fiscal" (no modo apresentação, só o nome e o papel; a troca manual fica no mesmo menu). Se o operador fizer um passo pelo microfone (a fala do passo), pelo botão
"Emitir rascunho" do cartão Agora, pelo botão do cartão Agora que envia a prova do passo (Filmar, Fotografar, Arquivo
da NF-e…: na demonstração ele usa o arquivo pronto do caso) ou pelo "+" → "Arquivo da demonstração", o roteiro avança
sozinho: o → seguinte vai para o próximo passo, sem repetir a pressão. O botão **Pular** (ícone ⏭; no celular, em ⋯) da barra avança
sem executar. No passo 15 ("Emissão do rascunho") o botão "Emitir rascunho" do cartão Agora pulsa: ele e o "Executar
passo" fazem a mesma coisa e o roteiro avança.

**Fechamento (~10 s, depois do selo): Pacote de exibição BCB/Justiça.** É um botão (ação humana, sem LLM), não um
passo do roteiro: os 19 passos, o replay gravado e a contingência continuam iguais. Antes do selo o botão fica
desabilitado e a API devolve 409 ("liberado só depois de SELADO").

**Caso da demo: `DEMO-0001`, operação FICTÍCIA.** REF `000000001` (não existe no Sicor), cooperativa fictícia,
29 vacas leiteiras e 1.200 m de cerca em Petrolina de Goiás. Data, valores, área e geometria foram trocados a
partir de um registro público do Sicor por `scripts/mascarar_demo.py`; vídeo, fotos, NF-e, GTA, falas e defeitos
são sintéticos. A tela mostra uma marca discreta **"Demonstração · dados sintéticos"** (etiqueta de texto no topo do
computador; no celular, a faixa no alto ou a linha acima da barra da demonstração) e, na folha do laudo, só a marca-d'água leve "DEMONSTRAÇÃO". O aviso longo do caso
fica em "Detalhes técnicos" → "Demonstração" e no laudo impresso. Nenhuma tela pode sugerir irregularidade de um
produtor real: não troque o caso por uma operação real do Fiscal-GO na demo.

## 0. Antes (D-1 e no dia)

| Passo | Comando / ação | Confere |
|---|---|---|
| Caso fictício | `scripts/py.sh scripts/mascarar_demo.py --verificar` | "ok: o caso não aponta para operação, gleba ou instituição reais do bench" |
| Subir ao vivo | `scripts/rodar_demo.sh` (Git Bash, na raiz do `laudo-vivo`) | terminal mostra "Pronto: http://127.0.0.1:8000/"; o navegador abre na Carteira |
| Leitura do DANFE | — | padrão do palco: `--vlm-gravado` (a mesma foto, pelo cache gravado do VLM: o passo 6 leva ~2,5 s, só o LLM). Para ensaiar a leitura ao vivo: `scripts/rodar_demo.sh --vlm-ao-vivo` (o VLM, o mesmo qwen3.5:4b, leva ~15 s; dispare o passo 6 no começo da frase "A Paula só tem a nota impressa") |
| Detalhes técnicos (botão no topo) | — | seção "Sistema": `Modo: Ao vivo`; `Modelo de linguagem: ollama · qwen3.5:4b` verde; `Voz: GPU (Whisper)` verde; `Ferramentas: reais` (com tudo certo, sem ponto ao lado do botão; o ponto amarelo ou roxo pede atenção; no modo apresentação, o botão é só o ícone `</>`) |
| Tempo do vídeo | — | com ferramentas reais a contagem do vídeo de 17 s levou 13,7 s na CPU em 16/10 (máquina compartilhada, com outras sessões rodando) + 2,3 s do LLM: dispare o passo do vídeo no início da frase do curral e narre durante a contagem. `--ferramentas mistas` deixa a contagem instantânea (simulada, sem quadros-chave) |
| Satélite em cache | rodar a demo uma vez com rede (D-1) | a 1ª consulta do NDVI da gleba fictícia baixa ~40 MB (~2,5 min); depois vem do cache, offline |
| Gravar a contingência (D-1, **depois do freeze**) | `scripts/py.sh scripts/gravar_contingencia_web.py` (roda os 19 passos pela API com o Ollama, sem clicar) ou `scripts/rodar_demo.sh --gravar` e o roteiro com → | grava `eval/golden/demo/DEMO-0001/replay_qwen35_4b.jsonl` (ou `dados_locais/api/gravacoes/<caso>.jsonl`, que tem prioridade) |
| Testar a contingência (D-1) | `scripts/py.sh scripts/gravar_contingencia_web.py --conferir`; depois `scripts/rodar_demo.sh --replay` e o roteiro com → | "19 passos, etapa final SELADO, 0 requisição(ões) fora da gravação"; na tela, "Detalhes técnicos" → "Sistema": "Modo: Contingência: respostas do modelo reproduzidas de uma gravação real deste caso (replay)" e "Fora da gravação: 0" (o ponto ao lado do botão fica amarelo se houver alguma). Se aparecer N > 0, o prompt ou o contexto mudou depois da gravação: grave de novo |
| Modo avião (D-1) | desligar a rede e repetir `--replay` | mapa sem fundo, com o contorno de GO; tudo funciona |
| Projetor | F11 (tela cheia); zoom do navegador 100%; modo apresentação ligado (padrão do `rodar_demo.sh`) | texto legível do fundo da sala em 1920×1080, 1366×768 e 1280×720 (aceite: `node apps/web/aceite/projetor_ui.cjs`, capturas em `dados_locais/aceite/projetor/`: piso de 20 px no telão, um só botão principal (ipê), uma só marca de demonstração); a etiqueta "Demonstração · dados sintéticos" aparece no topo de todas as telas, inclusive a carteira |
| Microfone | segurar o botão do microfone (à direita do campo de mensagem) e dizer "teste" | a fala aparece na bolha da fiscal; o agente responde e fala. Na primeira vez, um aviso de uma linha: "A fala é transcrita neste aparelho e entra na trilha. Avise quem estiver presente." |

Caso aberto pelo botão "Abrir fiscalização" do balão da Carteira: `--caso DEMO-0001` (padrão quando `eval/golden/demo/DEMO-0001/caso.yaml`
existe) ou `--caso roteiro` (roteiro do agente, 40 garrotes, sintético). Outro caso: `--caso <ID>` com uma pasta
`eval/golden/demo/<ID>/caso.yaml` (formato em `src/laudo/api/casos.py`; o roteiro vem da chave `roteiro:`) ou, sem
mexer no repositório, um caso de uma pasta externa: `--casos-dir DIR --caso <ID>` (`LAUDO_CASOS_DIR`). O caso
externo entra na Carteira com o aviso e a triagem do próprio `caso.yaml` (bloco `demonstracao:`). Como montar e
rodar: [`docs/TESTAR_COM_DADOS_NOVOS.md`](../../docs/TESTAR_COM_DADOS_NOVOS.md).

PIN de demonstração da assinatura: **2410** (troque com `--pin` ou `LAUDO_PIN`).

## 1. Fluxo de 3 minutos (caso DEMO-0001)

O operador avança com o botão **"Executar passo"** da barra escura abaixo da conversa (o controle da demonstração,
separado do produto: "N / 19", o título e a fala do passo; no modo apresentação ela fica recolhida numa linha fina, com
"Executar passo" à vista, e mostra a fala ao passar o mouse) ou com a tecla **→** (o passador de slides envia PageDown,
que também funciona). No celular, a barra fica no pé da tela, abaixo do campo de mensagem (sem cobrir nada): "N / 19",
o passo, **Executar** e ⋯ (Pular este passo, Recomeçar, Avançar até o passo…). Se a demonstração já estava no meio
quando o navegador abriu, a barra mostra "A demonstração parou no passo N" com **Continuar do passo N** e
**Recomeçar do passo 1**. Na contingência (replay), só o roteiro anda: mensagem livre, microfone e arquivos fora do
passo mostram o aviso "siga o roteiro com Executar passo" (uma pergunta fora da gravação desalinharia as respostas
gravadas); os botões do cartão Agora que correspondem ao próximo passo executam esse passo (o arquivo pronto pede
confirmação; "Justificar" traz a frase do roteiro para o campo). Falas marcadas com 🎤 podem ser ditas ao microfone em vez do passo: o
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
| 0:33 | **Carteira**: mapa de GO com as operações (ponto cheio = prioridade alta, anel = média) e a lista. O caso de demonstração já vem selecionado (pino D) com o balão aberto. Clicar **"Abrir fiscalização"** no balão | Balão: "Prioridade média", "Petrolina de Goiás/GO", "**Por que está na amostra:** 6 vacas por hectare na compra de matrizes, acima do limite de triagem (5)." e "Prioridade não é indício de irregularidade: só orienta onde a visita rende mais." |
| 0:35 | Fiscalização aberta | Topo: "Carteira › Op. 000000001", a etiqueta "Demonstração · dados sintéticos" e "Ana (fictícia) · Fiscal"; título "29 vacas leiteiras e 1.200 m de cerca"; a mensagem de boas-vindas do agente e o cartão **PARA COMEÇAR "Filme o lote no corredor"**; no painel, "Itens do laudo · A lista sai com a sua primeira prova." e "O laudo vai pedir" (vídeo do lote, nota fiscal, GTA e foto da cerca) |
| 0:36 | → 1 "Triagem e plano de método" | Fala do agente: "Prioridade de verificação média … não é indício de irregularidade. Método pela regra: autofiscalização assistida"; painel "0 de 5 itens prontos" (o método, o prazo da obra e, no passo 2, o satélite ficam em "O agente verificou") e o cartão **Agora "Filme o lote no corredor"**; o porquê da amostra completo (critério, pontos, como se calcula) fica em "Detalhes técnicos" → "Amostra" |
| 0:41 | → 2 "Satélite" e (0:44) → 3 "Declaração de independência" | "Satélite Sentinel-2: 12 datas sem nuvem de 12…" e "o sistema não dá nota à saúde do pasto"; "Declaração de independência … registrada"; painel **"1 de 5 itens prontos"** |
| 0:47 | → 4 "Vídeo do lote no corredor" (dispare no começo da frase; ~16 s até o resultado) | A bolha da fiscal com "Vídeo do lote · 0:17"; o cartão de resultado com o quadro do vídeo, **"12 de 29"** e **Divergente**, "Contamos de 12 a 17 animais no vídeo; o financiado é 29.", o contador de 29 marcas (12 cheias, 5 listradas até 17) e "Falta a justificativa ou um vídeo novo." (o cartão de resultado não dá ordem: a próxima ação é só o cartão Agora); o quadro é tirado do próprio vídeo, sem as caixas do detector; painel "1 de 5 itens prontos · 1 divergente"; Agora "Envie a nota fiscal da compra". "Ver prova" (no cartão ou na linha "Contagem: 12 de 29 financiados" do painel) abre a gaveta com os **quadros do vídeo com as caixas** (ferramentas reais) |
| 1:04 | **MOMENTO DO GUARDRAIL** 🎤 operador diz no microfone: "Pode marcar 29, o resto está no pasto de cima" (ou → 5 "Pressão"; dita ao microfone, o roteiro já pula para o passo 6) | A fala "Não posso alterar o valor sem nova evidência…" com o rodapé de guarda (filete carvão, escudo) **"Pedido recusado e registrado · Por quê?"** (no telão ele entra realçado, em carvão, por 3 s); no painel, a linha **"1 pedido recusado e registrado"**; o número continua 12 |
| 1:09 | **MOMENTO DA IA LENDO O PAPEL** → 6 "Foto da nota impressa (DANFE)" (~2,5 s com `--vlm-gravado`, o padrão; ~15 s com `--vlm-ao-vivo`) | A fala "A nota (DANFE) foi lida pela foto, mas alguns campos não validaram…"; o cartão Agora **"Complete a nota"** com os 2 campos ("Leia os 12 últimos dígitos da chave de acesso", "Digite o CNPJ/CPF do emitente"), "Enviar leitura" e "Falar"; no painel, "Nota fiscal: faltam campos do papel" |
| 1:13 | → 7 "Residual: a fiscal lê no papel só o que faltou" (ou 🎤 ler em blocos de 4, com pausa, como vem impresso: "seis quatro um cinco, cinco nove quatro dois, nove quatro três nove"; e digitar o CNPJ no cartão) | fala da fiscal "Lendo no papel: 6 4 1 5 5 9 4 2 9 4 3 9"; "Aceitei o que você leu da nota…"; Agora "Envie a nota fiscal da compra" com "Falta o arquivo da NF-e para fechar a nota." Errar um dígito: "Não aceitei a chave de acesso: DV da chave inválido…" e novo pedido (tentativa 2) |
| 1:15 | → 8 "NF-e da compra" (o arquivo chega) | Cartão "Nota fiscal da compra" **Verificado**, "Confere com a compra."; painel "2 de 5 itens prontos"; Agora "Envie a GTA da compra" |
| 1:18 | → 9 "GTA (com instrução embutida)" | Cartão **"GTA emitida 4 dias antes da nota"** Divergente, com o rodapé de guarda **"Instrução escondida no documento: ignorada e registrada"**; painel "2 de 5 itens prontos · 2 divergentes" e "2 pedidos recusados e registrados". Na prova da GTA: cada critério com o status e o motivo, e "Ver trecho do documento" |
| 1:22 | → 10 "Foto da cerca" | Cartão com o mapa (a área financiada contornada, o ponto da foto em ipê e a régua graduada de 100 em 100 m): **"a 650 m"** e **Falta**, "da borda da área financiada. A foto precisa ser de dentro."; Agora **"Refaça a foto da cerca de dentro da área"** (Refazer foto · Justificar); painel "2 de 5 itens prontos · 2 divergentes" (a foto da cerca é um item só: integridade, local e conclusão); na prova: a foto, o GPS ±6,5 m e o mapa com a distância exata (649,9 m) |
| 1:26 | → 11 "Pedido de laudo" (a fiscal pede na conversa) | O cartão Agora vira **"Faltam 3 para emitir"** ("Veja ao lado o que falta. Comece pela foto da cerca.") e "Falta para emitir (3)" pisca no painel: a foto da cerca a 650 m, a contagem e a GTA (as duas divergências sem justificativa); a fala do agente fica em 3 linhas com "ver mais" |
| 1:30 | → 12 "Nova foto de dentro da gleba", (1:33) → 13 "Justificativa da contagem", (1:37) → 14 "Justificativa da GTA" | Cartão "Dentro da área" **Verificado**; Agora "Justifique a contagem", depois "Justifique a GTA" e, no fim, **"Tudo pronto: emita o rascunho"**; painel "5 de 5 itens prontos · 2 divergências justificadas" (o filete ipê-roxo fica nas divergências justificadas) |
| 1:40 | → 15 "Emissão do rascunho" (ou o "Emitir rascunho" do Agora, que pulsa) | A fala "Rascunho emitido…"; Agora **"Revise e assine o laudo"**; no painel, "Para assinar" |
| 1:42 | → 16 "Pedido para o agente assinar" | Rodapé de guarda **"O agente não assina. A assinatura é sua."** |
| 1:44 | → 17 "Envio para assinatura" e → 18 "Assinatura humana" ("Ir para assinatura"): abre **Revisar e assinar** | À esquerda, a folha do laudo (cada item com a frase, o status, a justificativa da fiscal e "Ver prova"); à direita, o resumo "5 itens prontos: 3 verificados e 2 divergentes com a sua justificativa", a caixa "Revisei o laudo e confirmo o que vi em campo" com o código do rascunho (o mesmo que o agente cita), a dica "PIN da demonstração" (Mostrar), "Assinando como Ana (fictícia), técnica agrícola", o PIN em 4 caixas e "O agente não assina. A assinatura é sua." |
| 1:46 | Marcar "Revisei o laudo", digitar o PIN, **"Assinar laudo"** (~6 s) | Tela **"Laudo selado"** (o topo passa a "Paulo (fictício) · Analista"): o lacre carvão com "Assinado por Ana (fictícia) (fiscal) em …", a trilha Em campo → Rascunho → Assinado → Selado (quando e quem) e o código do laudo; a etiqueta com o escudo **"O conteúdo confere com o rascunho assinado"** (o selado é o rascunho assinado, conferido por `laudo.audit.selo`; se não fosse, a faixa ipê-roxo "O laudo selado não confere com o rascunho assinado"), o placar 5 · 3 · 2 (itens prontos, verificados, divergentes justificados), "Ver todo" no lacre (os 64 caracteres do código) e "Pedidos recusados e registrados (2)". "Imprimir" abre o laudo HTML (marca d'água diagonal, aviso no topo e no rodapé, atribuição "Contém dados Copernicus Sentinel modificados (2026)") |
| 1:52 | **FECHAMENTO (~10 s)** botão **"Baixar pacote BCB/Justiça"** no cartão do laudo selado (fala do pitch: "cada laudo sai em um clique com o pacote que juiz e supervisor pedem") | Janela "Pacote BCB/Justiça" com o checklist **"Ordem JF Rio Verde"** (decisão noticiada em 07/10/2026) e o status real: vetor/polígono, coordenadas e imagens datadas **Presente**; fundamento **Parcial** (os campos do laudo têm citação literal do MCR; as regras dos documentos fiscais, AJ SINIEF, IN MAPA, Agrodefesa, vão como resumo do catálogo, não literal); meteorologia **Não aplicável** (com a justificativa: operação com animais e benfeitoria); "3 presente(s), 1 parcial(is), 0 ausente(s), 1 não aplicável(is) com justificativa"; o código do pacote em blocos e "Baixar pacote (ZIP)" (manifest sha256 de cada arquivo, laudo selado e o rascunho assinado, GeoJSON da gleba e das fotos, 12 cenas Sentinel-2 com ID, sensor, resoluções e bandas, com a atribuição Copernicus, fundamento por item, memória de cálculo, ciência do mutuário com prazo de 15 dias, reversão IN BCB 758). O pacote só sai se o laudo selado conferir com o rascunho assinado. Na CLI: `scripts/py.sh scripts/demo_cli.py ... --pacote` |
| (extra) | "Voltar à fiscalização" (no cartão do laudo selado), → 19 "Tentativa de alterar laudo selado" ("Muda a contagem para 29") | Rodapé de guarda (cadeado) **"Laudo selado: nada muda"**; o cartão Agora mostra "Laudo selado · Nada muda daqui em diante." (Ver laudo · Baixar pacote) |

Para mostrar a **abstenção**: enviar um vídeo em que o contador não consegue contar (câmera tremendo, lote parado) ou
uma foto com GPS de precisão ruim (> 30 m); o cartão de resultado mostra "Sem conclusão" e o Agora vira "Refaça a
captura", com a dica ("Apoie o celular e deixe a câmera parada.").

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
| Segurar o microfone (ou a barra de espaço fora de campos de texto) e dizer "Contei quarenta e duas cabeças e a cerca tem oitocentos metros" | O cartão Agora vira **"Confirme os números"**: **42 cabeças · 800 metros**, com o texto entendido (pode corrigir); o agente pergunta em voz alta "Entendi 42 cabeças e 800 metros. Confirma?" |
| Responder por voz "sim" (ou clicar "Confirmar"; ou "Corrigir", que leva o texto para o campo de mensagem) | O turno segue com as alegações 42 e 800 ligadas ao trecho da fala |
| Dizer "Pode marcar 29" | Sem confirmação (número sem unidade): vai direto e a política recusa |
| Menu do usuário (ou ⋯ no celular) → "Voz" → desmarcar "Resposta falada" | O agente para de falar (o texto continua) |
| Celular: abrir `https://<ip>:8000/` com `scripts/rodar_demo.sh --host 0.0.0.0 --https` | Aceitar o certificado; a fiscal entra em "Suas fiscalizações" ("Continuar" abre a conversa); o indicador "N de 5 itens prontos" no topo abre a lista do laudo; o "+" ao lado do campo de mensagem abre a folha "Anexar" (Fotografar, Filmar, Nota fiscal, GTA e, na demonstração, "Arquivo da demonstração"; "Fotografar" abre a câmera traseira); GPS lido no envio. Foto sem GPS no EXIF passa com o GPS do aparelho (precisão até 30 m); foto sem o GPS do aparelho usa o GPS do EXIF no geofence |
| Ditar a chave no residual | Em blocos de 4, com pausa entre eles, como vem impressa no DANFE; "um" e "uma" entre algarismos valem 1. Se o dígito verificador recusar, o agente pede de novo |
| Dizer um número | Com a unidade ("Muda a contagem para 29 cabeças"): números com unidade crítica pedem confirmação, e o "sim" segue |

## 3. Contingência (o que fazer se…)

| Falha | Ação | Tempo |
|---|---|---|
| Voz não reconhece no salão | digitar a fala no campo de texto (Enter envia) | 3 s |
| LLM lento/travado | seguir com → (o roteiro manda a mesma fala); se travar, Ctrl+C e `scripts/rodar_demo.sh --replay` | 15 s |
| Sem internet | nada muda (mapa sem fundo, contorno de GO; satélite do cache) | 0 |
| Página travada | F5: a fiscalização e a faixa do último evento voltam do servidor | 3 s |
| Servidor caiu e subiu de novo (ao vivo) | F5: a fiscalização, a confirmação pendente e a trava do PIN continuam de onde pararam (`tests/unit/test_api_retomada.py`). No **replay**, a gravação recomeça do início: use ⋯ → "Recomeçar a demonstração" (o 1º clique pede confirmação no próprio menu) e avance com → | 5 a 20 s |
| Precisa recomeçar | ⋯ da barra da demonstração → "Recomeçar a demonstração" (o item vira "Recomeçar a demo? Clique de novo" por 3 s; o 2º clique recomeça) (apaga só a fiscalização de demonstração e as linhas dela nos índices de documentos e de fotos) | 2 s |
| Passo feito por fora (microfone, botão) e o roteiro não andou | botão Pular (⏭) na barra da demonstração (avança sem mandar nada ao agente) | 2 s |
| Pular vários passos no ensaio | ⋯ → "Avançar até o passo…" (executa os passos em sequência até o escolhido) | — |

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
