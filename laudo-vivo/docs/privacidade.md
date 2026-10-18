# Privacidade e LGPD no Laudo Vivo

> **As bases legais abaixo são a leitura da equipe e precisam ser validadas por advogado** e pelo encarregado
> (DPO) da instituição financeira antes de qualquer piloto com dado real. Nada aqui é parecer jurídico. O que
> está descrito como "implementado" tem teste no repositório; o resto está marcado como proposta ou pendência.

## 1. Papéis

| Papel (LGPD, art. 5º) | Quem | Por quê |
|---|---|---|
| Controlador | a instituição financeira (cooperativa de crédito) | é ela quem tem a obrigação de fiscalizar e documentar a operação de crédito rural (Res. CMN 5.267/2025, MCR 2-7) e decide finalidade e prazo |
| Operador | o Laudo Vivo (software e, no serviço, a equipe que revisa) | trata os dados em nome da IF, por contrato (art. 39), só para a fiscalização |
| Usuária | a fiscal da IF ou da credenciada | coleta a evidência, revisa e assina; é também titular (voz, nome, assinatura) |
| Titulares | tomador do crédito, vendedor dos animais (emitente da NF-e, às vezes pessoa física), fiscal, quem aparece ou fala no curral | — |

Não vendemos ao produtor e não trabalhamos para ele (MCR 2-7, item 15): a finalidade é sempre a fiscalização
da IF.

## 2. Dados por tipo, finalidade e base legal (a validar com advogado)

| Dado | Onde aparece | Finalidade | Base legal proposta (art. 7º) | Como é tratado |
|---|---|---|---|---|
| Operação de crédito (REF, município, valores, área, glebas) | Sicor/BCB, cadastro da IF | escolher amostra e método; conferir área e local | II (obrigação regulatória da IF) e V (execução do contrato de crédito) | dado público do Sicor, sem CPF; na demo, operação fictícia |
| CPF/CNPJ do tomador | cadastro da IF, NF-e, GTA | conferir que o comprador é o tomador | II e V | entra como **hash público** `sha256:` só na abertura e é guardado como `hmac:` (HMAC-SHA256 com o **sal da instalação**); nunca em claro |
| CPF/CNPJ e nome do vendedor (emitente) | NF-e (XML ou foto do DANFE), GTA | conferir que o vendedor não é o tomador e que a nota é da compra financiada | II (comprovar a aplicação do crédito, MCR 2-7) | máscara (`***.456.789-**`; CNPJ só a raiz) + hash com sal; nome de pessoa física em iniciais |
| **Chave de acesso da NF-e** (44 posições; embute o CNPJ ou o **CPF** do emitente) | XML, foto do DANFE, GTA (chave vinculada) | conferir integridade (DV), casar papel × XML, consultar a nota na SEFAZ | II | no estado, no trace e no laudo, **só mascarada** (`522604…59429439`) e com `chave_hash` (HMAC com o sal); a chave inteira só **cifrada no cofre** da fiscalização (seção 4) |
| CN do certificado digital (`NOME:CPF`) | assinatura do XML | conferir que quem assinou é o emitente | II | só em memória; na trilha, iniciais e documento mascarado |
| Voz e fala da fiscal e de quem está no curral | microfone do app | conduzir a coleta com as mãos livres; registrar declarações e pressões | II (fiscalização documentada, MCR 2-7, itens 3 e 4) e V (contrato da fiscal com a IF ou credenciada) | ASR **local**; o áudio é bruto (cifrável e expurgável); o texto vai para a trilha com CPF, CNPJ, telefone, e-mail e nomes após gatilhos mascarados (POL-08). A voz **não** é usada para identificar ninguém (não é biometria, art. 11) |
| Imagem do lote, da cerca, do curral | vídeo e fotos do app | contar animais, verificar a benfeitoria | II | rosto não é necessário nem analisado; brutos cifráveis e expurgáveis |
| GPS e horário das fotos | app e EXIF | provar onde e quando (MCR 2-7, item 4, metadados) | II | só coordenada e precisão; conferidos contra a gleba |
| Nome, papel e assinatura da fiscal; PIN | tela de assinatura | assinatura humana do laudo | V e II | o PIN é conferido e não é guardado; tentativas erradas ficam registradas (trava) |
| **Índice de fotos** (entre fiscalizações) | `<dados>/indices/fotos.jsonl` | detectar a mesma foto (ou quase a mesma) usada em outra fiscalização: reuso de evidência | II | sha256 e phash da imagem, com o caminho do arquivo e o id da fiscalização; registra cada foto avaliada; a imagem não entra |
| **Índice de documentos reutilizados** (entre fiscalizações) | `<dados>/indices/documentos.jsonl` (`docs_fiscais/indice.py`, `agent/indice.py`) | detectar a mesma GTA ou a mesma NF-e comprovando **outra operação** (duplicidade de crédito, MCR 2-7-6-b e 2-7-7-d) | II | só HMAC com o sal da instalação: da GTA (`UF-SÉRIE-NÚMERO`), da chave de acesso da NF-e (que embute o CPF/CNPJ do emitente) e da referência da operação, mais o item, o id da fiscalização e a data; nada em claro. Grava **só na selagem**, depois da assinatura humana, os documentos que comprovaram o item; a consulta, em toda conciliação de NF-e e GTA, só lê. Vale dentro da instalação |

Os dois índices cruzam fiscalizações de propósito, inclusive de produtores diferentes: reuso de prova entre
operações é o que eles existem para pegar. Por isso guardam só hash e não servem para montar perfil de
produtor nem de fiscal. Nenhuma outra memória fica entre fiscalizações (`docs/fluxo_do_agente.md`, seção 5).

Dado sensível (art. 11): nenhum é necessário. Se aparecer (ex.: rosto de terceiro numa foto), não é tratado
nem analisado; a orientação é refazer a captura sem pessoas.

## 3. Minimização (implementado)

- **Hash com sal por instalação.** `docs_fiscais.comum.hash_documento` = HMAC-SHA256 com um sal de 256 bits
  que fica **fora do git**, em `dados_locais/config/instalacao.json` (ou `LAUDO_CONFIG_DIR`), criado na
  primeira execução (`laudo.privacidade`). Sem o sal, o hash de um CPF não se desfaz por força bruta (são só
  10⁹ CPFs). Consequência assumida: hashes de instalações diferentes não se comparam. O hash público
  (`hash_documento_publico`, sem sal) só é aceito como **entrada** (`sha256:<hex>`) e convertido na hora.
- **Chave de acesso mascarada.** Toda checagem passa por `privacidade.proteger_resultado` antes de entrar no
  estado (`estado.registrar_checagem`): chave inteira, chave lida com erro pelo VLM, chave parcial do pedido
  do residual, referência da assinatura (`#NFe…`) e chaves vinculadas na GTA viram máscara; os textos de log e
  trace passam por `pii.mascarar`, que também mascara chave. O **dígito verificador continua validado** na
  leitura, com a chave inteira em memória; o resultado da validação (status e motivo) fica no estado.
- **Modelos locais.** LLM, VLM (leitura do papel), ASR e contagem rodam na máquina (Ollama, Whisper, YOLOX);
  nenhum provedor de nuvem está ligado. Se um for configurado (`externo=True`), o texto é mascarado antes do
  envio.
- **Nenhuma ferramenta de conciliação recebe CPF/CNPJ em claro.** CPF/CNPJ digitado pela fiscal no residual
  não entra nos argumentos registrados nem no trace.
- **Repositório sem dado pessoal.** Casos, documentos, fotos e falas do golden set e da demo são sintéticos;
  `scripts/checar_pii.py --parquet` roda no CI.

Testes: `tests/unit/test_privacidade.py` (sal criado fora do repositório; hash muda com o sal; chave mascarada
no estado, no trace e no laudo de uma fiscalização de verdade; cofre e expurgo),
`tests/unit/test_agente_pii.py`.

## 4. Retenção e expurgo

| O quê | Prazo (proposta, a validar com a IF) | Como |
|---|---|---|
| Brutos: áudio, vídeo, fotos, quadros-chave, NF-e/GTA, conversa | 90 dias depois do selo | **podem ser** cifrados com uma chave por fiscalização (`scripts/expurgo_lgpd.py cifrar <fis>`, `audit/cofre.py`; por comando, não automático no selo); `scripts/expurgo_lgpd.py vencidos --dias 90 --executar` apaga as chaves (crypto-shredding) |
| Chave de acesso inteira e leituras brutas do VLM | os mesmos 90 dias | já ficam cifradas no cofre da fiscalização (`_cofre`); o expurgo da chave as torna irrecuperáveis; a máscara e o `chave_hash` continuam no estado |
| Laudo selado, estado (com a cadeia de hash) e trace | o prazo que a IF definir para manter a documentação à disposição do BCB (MCR 2-7, item 23) | não têm CPF/CNPJ em claro nem chave inteira; a cadeia de hash continua íntegra depois do expurgo dos brutos |
| Índices de fotos e de documentos (seção 2) | proposta: o mesmo prazo do laudo selado que a linha comprova (a validar com a IF) | só hash; **ficam fora da cifra por fiscalização e do expurgo** (`expurgo_lgpd.py` não mexe neles); a remoção das linhas de uma fiscalização do índice está na seção 8 |

Consulta futura da nota (situação na SEFAZ) durante a retenção: `privacidade.chaves_para_consulta` devolve as
chaves inteiras do cofre da fiscalização; depois do expurgo, não há mais como reconstruí-las (é o objetivo).

Escopo da cifra: o texto das falas que vira evidência `declaracao` fica no estado, mascarado, e não entra na
rotina de brutos; uma cópia de backup da chave feita fora do sistema continuaria valendo; a cifra usa só a
biblioteca padrão (HMAC-SHA256 em modo contador + etiqueta), e em produção deve ser AES-256-GCM com a chave
num KMS/HSM; o expurgo é um comando, não automático no selo.

## 5. Localidade do processamento

Tudo no computador da fiscal ou no servidor da IF: estado, trace, laudo, modelos e o sal da instalação. Há
duas saídas de rede, e nenhuma leva nome, documento, foto, vídeo ou fala:

- a série do satélite: o catálogo STAC Earth Search da Element84 (`earth-search.aws.element84.com`) e as
  imagens Sentinel-2 do AWS Open Data recebem só o retângulo da gleba e as datas; depois da primeira consulta,
  vem do cache;
- o fundo do mapa da interface web: o navegador pede os tiles do OpenStreetMap (`tile.openstreetmap.org`) da
  área exibida, e o servidor de tiles vê o IP de quem abre a tela e a região do mapa (a gleba aproximada). Sem
  rede, o mapa fica sem fundo e nada mais muda. O IP é dado pessoal pela LGPD: numa operação real, a IF pode
  trocar por um servidor de tiles próprio ou desligar o fundo do mapa.

Fora o endereço IP de quem faz essas duas consultas (o notebook, no satélite; o navegador, no mapa), nenhum
dado pessoal sai da máquina.

## 6. Direitos do titular (art. 18)

Os pedidos chegam à IF (controladora); o Laudo Vivo dá os meios:

| Direito | Como atendemos |
|---|---|
| Confirmação e acesso | o laudo e a trilha da fiscalização são exportáveis (JSON e HTML), já sem CPF/CNPJ em claro |
| Correção | fiscalização selada não muda (append-only, POL-04); a correção vira nova fiscalização, com a justificativa registrada |
| Anonimização, bloqueio ou eliminação | expurgo antecipado dos brutos e do cofre por pedido (`expurgo_lgpd.py expurgar <fis> --motivo "pedido do titular"`); o laudo selado e a trilha mínima podem ter de ser mantidos pela obrigação de guarda (art. 16, I), sem dado em claro |
| Informação sobre compartilhamento | nenhum compartilhamento além da IF; modelos locais |
| Revisão de decisão automatizada (art. 20) | não há decisão só automatizada: o status é proposto pelas regras e o laudo só vale com revisão e assinatura humana; divergência nunca vira decisão sem o humano e sem chance de explicação |

## 7. RIPD (relatório de impacto) em uma página

**Tratamento:** fiscalização de operação de crédito rural com coleta em campo (fotos, vídeo, voz, documentos
fiscais) e laudo assinado por profissional habilitado. **Necessidade:** a IF tem de provar a aplicação do
crédito com métodos verificáveis (Res. CMN 5.267). **Proporcionalidade:** coleta só da evidência que a norma
pede para o item; o resto não é pedido.

| Risco | Probabilidade × impacto | Medida | Risco residual |
|---|---|---|---|
| Reidentificação de CPF por força bruta no hash | média × alto | HMAC com sal secreto por instalação, fora do repositório | baixo (depende de proteger o sal) |
| CPF do vendedor exposto pela chave da NF-e | alta × médio | chave só mascarada na trilha; inteira só cifrada | baixo |
| Vazamento dos brutos (vídeo, áudio, documentos) | média × alto | cifra por fiscalização, expurgo por chave, modelos locais | médio até haver KMS e disco cifrado |
| Gravação de terceiros sem ciência | média × médio | aviso de gravação na tela; rosto não analisado; termo de consentimento (TCLE) para quem for filmado ou gravado | médio (depende da IF e da equipe) |
| Uso da triagem contra o pequeno produtor | baixa × alto | "prioridade de verificação, não indício"; humano decide; over-blocking medido | médio (medir o over-blocking por porte do produtor) |
| Índices entre fiscalizações usados para cruzar produtores fora da finalidade | baixa × médio | só hash com o sal da instalação; o de documentos grava só na selagem; nenhum campo de perfil; vale dentro da instalação | baixo (com o comando de remoção por fiscalização, seção 8) |
| Erro do modelo prejudicando o titular | média × médio | abstenção, verificador independente, falso "verificado" com meta zero, revisão humana | baixo |
| Acesso indevido ao notebook da fiscal | média × alto | PIN na assinatura, append-only com hash | médio: recomendar disco cifrado (BitLocker/FileVault) e conta própria |

**Conclusão provisória:** risco aceitável para piloto **depois** de: parecer jurídico sobre as bases legais,
contrato de operador com a IF, prazo de retenção definido pela IF, TCLE para filmagens, encarregado indicado e
chave do cofre em KMS. Revisar este RIPD a cada mudança de finalidade ou de fornecedor.

## 8. Antes de um piloto com dado real (fora do código)

- Validar com advogado as bases legais da seção 2 e o papel de operador.
- Termo de consentimento (TCLE) com revisão jurídica para quem for filmado, gravado ou entrevistado; os termos
  assinados ficam fora do repositório.
- Comando para tirar dos índices de fotos e de documentos as linhas de uma fiscalização expurgada ou
  corrigida, e o prazo de guarda dessas linhas com a IF.
- Prazo de retenção e encarregado (DPO) com a cooperativa do piloto.
- Em produção: AES-GCM com KMS, expurgo automático no fim da retenção, disco cifrado no notebook.
