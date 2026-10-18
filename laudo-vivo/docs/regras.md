# Regras do MCR como código

O Laudo Vivo transforma normas em **rulebooks** versionados, citáveis e testados. Cada campo do laudo aponta
para uma regra (`regra_id`), cada regra aponta para o trecho literal da norma, e um teste confere que esse
trecho existe no texto oficial salvo no repositório.

| Peça | Onde |
|---|---|
| Texto normativo literal (com URL, data de acesso e número do item) | `docs/normas/mcr_2_7.md`, `docs/normas/mcr_2_9.md`, `docs/normas/in_bcb_758.md` (reversão de desclassificação, lida por `laudo.rulebooks.normas`; só a seção "Texto literal" é transcrição, amarrada por sha256 à conferência contra a API do BCB: editada, deixa de sair como conferida) |
| Rulebooks (dados) | `src/laudo/rulebooks/mcr_2_7.yaml`, `src/laudo/rulebooks/mcr_2_9.yaml` |
| Esquema, carregamento e condições | `src/laudo/rulebooks/__init__.py` |
| Ferramentas `planejar_metodo`, `avaliar_regras`, `explicar_regra` | `src/laudo/tools/regras.py` |
| Testes por tabela | `tests/unit/test_regras_*.py` |

Para rodar, a partir da raiz do repositório: `scripts/py.sh -m pytest tests/unit -q -k regras`.

## 1. Norma × parâmetro operacional

Toda regra declara a sua `origem`:

- **`norma`**: o que o MCR manda. O id tem prefixo `MCR-` (ex.: `MCR-2-7-item16-maquinas-60d`) e a regra
  exige `citacao` literal curta. O campo `item` traz o localizador completo (`MCR 2-7-16-b-II`).
- **`parametro_operacional`**: escolha nossa para tornar a norma executável. O id tem prefixo `OP-` e a regra
  exige `justificativa` e `base_normativa` (os itens da norma que o parâmetro implementa). Os valores
  numéricos ficam em `parametros:` (`PAR-...`), cada um com sua justificativa e com o que falta para
  calibrá-lo.

Parâmetros operacionais do rulebook MCR 2-7 (v0.5.0, 16/10/2026):

| Parâmetro | Valor | Por que não é norma |
|---|---|---|
| `PAR-contagem-tolerancia-pct` | 5 % | O MCR não fixa tolerância de contagem. Ela vale só para menos (mais animais não é desvio). |
| `PAR-tentativas-inconclusivas-max` | 2 | Limite de recoleta antes de o sistema se abster e passar a decisão ao humano. |
| `PAR-geofence-perto-m` | 100 m | O MCR não exige foto georreferenciada no 2-7. O valor cobre o erro de GPS e a cerca na divisa. |
| `PAR-geofence-longe-m` | 1000 m | Acima disso a foto diverge; entre 100 e 1000 m, o campo fica pendente (refazer ou justificar). |
| `PAR-area-total-usa-financiada` | true | O Sicor público não traz a "área total" do item 5-b. |
| `PAR-custeio-lotacao-atencao-cab-ha` | 3 cab/ha | A norma não fixa lotação. É o limiar da triagem para custeio (`lot_cust_1`); acima dele, ponto de atenção não bloqueante. |
| `PAR-pacote-prazo-contestacao-dias` (0.5.0) | 15 dias corridos | O MCR não fixa prazo de contestação. O 2-8-3 dá à IF 60 dias da ciência do fato para desclassificar; 15 dias da ciência do mutuário deixam tempo para a IF examinar a contestação. Escolha da IF, com pendência de compliance/jurídico. Usado pelo pacote de exibição (termo de ciência). |
| regra `OP-perfil-custeio-animais` | — | O 2-7 não tem alínea para custeio pecuário: o item 1 deixa o procedimento com a IF, e o perfil é esse procedimento documentado (1-c). |
| regra `OP-custeio-lotacao` | — | Lotação do lote na área: sinal para o fiscal, nunca divergência. |
| regra `OP-bovinos-gta` | — | A GTA vem da defesa sanitária, não do MCR. |
| regra `OP-metodo-autofiscalizacao-enquadramento` | — | A autofiscalização assistida é enquadrada como método documental (item 3-b). |
| regra `OP-metodo-escolha-por-item` | — | Método por tipo de item × prioridade da triagem. |

Tipos de regra (`tipo`): `requisito_metodo`, `prazo`, `requisito_evidencia`, `requisito_laudo` e
`criterio_status`. Uma regra sem `avaliador` é **informativa**: pode ser citada (`explicar_regra`), mas não
é executada. O campo `usado_por` diz qual ferramenta executa a regra.

## 2. Estrutura de um rulebook

```yaml
id: mcr-2-7
versao: 0.1.0                 # semver (seção 4)
vigencia_inicio: 2026-03-01   # Res. CMN 5.267, art. 2º
texto_normativo: docs/normas/mcr_2_7.md
fontes: [{id, descricao, url, acesso}]
revisao: {estado: rascunho_tecnico, revisores: [], pendencias: [...]}
parametros: [{id: PAR-..., valor, unidade, justificativa, base_normativa, calibrar}]
regras:
  - id: MCR-2-7-item16-maquinas-60d
    item: "MCR 2-7-16-b-II"
    tipo: prazo
    origem: norma
    citacao: "as ações de monitoramento e fiscalização devem ocorrer até sessenta dias da liberação do crédito"
    aplica_a: [maquina]
    efeito: {ancora: data_liberacao, dias: 60, inclusivo: true}
    avaliador: prazo_dias_apos           # função em tools/regras.py::AVALIADORES
    pedido: "informar a data de liberação do crédito"
    criterios: {verificado: "...", divergente: "...", pendente: "..."}
fluxos:                       # tipo de item → campos do laudo, cada um com sua regra
  maquina: {tipos_item: [maquina], campos: [{campo: prazo_60d, regra: MCR-2-7-item16-maquinas-60d}, ...]}
campos_laudo:                 # campos do laudo que não pertencem a um item
  - {campo: "laudo:independencia_fiscal", regra: MCR-2-7-item15-independencia-fiscal}
```

**Condições** (`condicao`) são declarativas e usam lógica de três valores. Dado ausente vira
**indeterminado**, nunca "falso". Um exemplo é o item 5 com a área desconhecida: a obrigatoriedade fica
indeterminada e o campo, pendente.

```yaml
condicao:
  todas:
    - {campo: operacao.finalidade, op: in, valor: [custeio, investimento]}
    - {campo: operacao.data_contratacao, op: gte, valor: 2026-03-01}
    - {campo: operacao.area_total_ha, op: gt, valor: 300}    # 300 ha exatos → falso
```

Operadores disponíveis: `eq`, `ne`, `in`, `nin`, `gt`, `gte`, `lt`, `lte`, `existe`, combinados com
`todas`, `alguma` e `nao`. O valor pode vir de um parâmetro: `{param: PAR-...}`.

## 3. Como checagens viram status (`avaliar_regras`)

1. As **ferramentas** calculam e gravam `Checagem` (status `ok`, `divergente`, `indeterminado` ou `erro`, mais
   o `resultado`).
2. Cada campo do fluxo lê as checagens da sua regra, filtradas por `ferramentas` e pelo `item_id`, e converte
   cada uma num veredito: verificado, divergente, inconclusivo, incompleto ou erro. A contagem e o geofence
   **recalculam** a partir do `resultado` com os parâmetros do rulebook. Para elas, o status da ferramenta
   só vale como abstenção ou erro.
3. Os vereditos são agregados (`OP-status-mapeamento-checagem`):
   - sem checagem: **pendente** ("evidência ausente: <pedido>");
   - agregação `consenso`: conclusivas iguais dão esse status. Conclusivas **conflitantes** dão **pendente**
     com revisão humana, porque recontar até passar não resolve;
   - agregação `qualquer_divergente` (integridade e geofence): basta uma divergente; sem divergente, uma
     captura inconclusiva só é superada por uma verificada **posterior** (0.2.0: a foto boa anterior não
     "absolve" a cópia enviada depois; a foto refeita de dentro da gleba resolve a de fora);
   - checagem com `resultado.substitui` (NF-e/GTA reconciliadas com todos os documentos do item) tira as
     checagens substituídas da agregação (0.2.0);
   - medição precisa na faixa intermediária do geofence (0.3.0: foto fora da gleba entre `PAR-geofence-perto-m`
     e `PAR-geofence-longe-m`): veredito **justificável** → **pendente** com pedido de nova captura ou
     justificativa do fiscal; não conta como tentativa inconclusiva (nunca vira abstenção) e, justificado, deixa
     de bloquear (o campo continua pendente no laudo, com as palavras do fiscal);
   - classificação da foto pelo VLM (`classificar_foto`) na conclusão da obra (0.3.0): só verifica se a classe for
     a do item (cerca para cerca); outra classe ou abstenção é inconclusiva; o VLM nunca dá divergência;
   - requisito da norma ausente no documento (`resultado.requisitos_ausentes`): **pendente**;
   - inconclusiva: **pendente** com pedido de nova coleta. Ao atingir `PAR-tentativas-inconclusivas-max`,
     vira **abstenção**;
   - só erros: **pendente** (repetir). Erros não contam como tentativa.
4. O status do item é o pior entre os seus campos (`OP-agregacao-item`): divergente > pendente > abstenção >
   verificado. Desde a 0.4.0, campo de regra **não bloqueante** (lotação e método documentado do perfil de
   custeio) aparece no valor do item, mas não decide o status dele: sinal não é achado. O motivo do item diz
   quando há sinal pendente ("exigências bloqueantes verificadas; ponto de atenção não bloqueante: lotacao
   (pendente)"), em vez de "todas as exigências verificadas" (essa frase só sai quando nenhum campo do item,
   bloqueante ou não, está pendente).
5. **Bloqueios**: todo campo pendente, e toda abstenção sem `justificativa_humana`, gera um bloqueio com
   `regra_id` e o que falta. Campo **divergente não bloqueia** aqui: ele é um achado do laudo. Quem exige a
   justificativa do fiscal é a política (POL-02, `agent/politica.py`). A `justificativa_humana` já gravada
   em `Fiscalizacao.campos` sobrevive à reavaliação. Campo de regra `bloqueante: false` nunca gera bloqueio.
6. **Pendente que não bloqueia (decisão de 16/10/2026, rulebook 0.5.0).** Lotação acima do parâmetro e método
   do perfil sem o método de campo continuam com status **pendente**: o vocabulário de status é o do contrato
   (`StatusCampo`), e a pendência é real (falta confirmar a área de pasto ou registrar o método). Mas eles
   **aparecem diferente** do pendente que bloqueia, em três lugares: a ressalva
   `RESSALVA_NAO_BLOQUEANTE` em `CampoLaudo.ressalvas` ("não bloqueante: ponto de atenção; não impede o
   rascunho nem entra no status do item"), o motivo terminando em "(não bloqueia o laudo)" e a lista
   `nao_bloqueantes` do resultado de `avaliar_regras`, separada de `bloqueios`. Assim a tela e o laudo podem
   mostrar "atenção (não bloqueia)" em vez de "pendente", e ninguém lê o sinal como impedimento. O `resumo`
   por status continua contando o campo como pendente.

**Contexto vindo dos contratos (integração de 08/10/2026).** `planejar_metodo` e `avaliar_regras` completam o
`ContextoRegras` com os campos que agora existem em `contracts.py` (`completar_contexto`): `Operacao.data_liberacao`,
`area_total_ha`, `modulos_fiscais`, `fonte_recursos`, `ItemFinanciado.cronograma_fim` e `exige_numero_serie`,
`Fiscalizacao.data_fiscalizacao` e `rulebooks`. O que vier explícito no contexto prevalece. O executor do agente
preenche `data_referencia` com `Fiscalizacao.data_referencia` (replay determinístico) e
`contexto.prioridade_verificacao` com a triagem da operação (`carregar_operacao`; `sem_sinal` conta como baixa).
Toda ferramenta devolve `status` no vocabulário comum (`ok`, `divergente`, `indeterminado`, `erro`); as de
documento devolvem o pior status dos seus campos, e `geofence` devolve a posição em `posicao`.

A data da fiscalização usada nos prazos é a informada em `contexto.data_fiscalizacao`. Sem ela, vale a
primeira captura de campo (foto, vídeo ou áudio) ligada às checagens do item, no dia civil de
America/Sao_Paulo. Documentos não contam, porque a data deles é a de emissão.

### Contrato de leitura das checagens

| Regra | `ferramenta` | O que é lido de `resultado` |
|---|---|---|
| `OP-bovinos-contagem-tolerancia` | `contar_bovinos_video`, `contagem_manual` | `contagem`, `intervalo: [inf, sup]`, `status` ("indeterminado" = abstenção), `motivos` |
| `MCR-2-5-item10-comprovante-aquisicao`, `MCR-2-7-item16-maquinas-nfe` | `conciliar_nfe` | status da checagem (o pior dos `campos`); `requisitos_ausentes` (máquina: `discriminacao_bem`, `comprador`, `identificacao_if`) |
| `OP-bovinos-gta` | `conciliar_gta` | status da checagem; `requisitos_ausentes` |
| `OP-evidencia-integridade-foto` | `integridade_foto` | status da checagem, `motivos` |
| `OP-benfeitoria-geofence` | `geofence` | `posicao` (dentro/fora/indeterminado; `status` legado aceito), `distancia_borda_m` |
| `MCR-2-7-item16-benfeitorias-conclusao` | `classificar_foto`, `declaracao_conclusao` | status da checagem (`declaracao_conclusao` é a ação interna `registrar_conclusao_obra` do condutor: trecho literal da fala do fiscal) |
| `MCR-2-7-item16-maquinas-numero-serie` | `conferir_numero_serie` | status da checagem (número lido × NF-e) |
| `MCR-2-7-item5-...`, `MCR-2-7-item4-metadados-sr` | `serie_ndvi`, `anomalia_ndvi`, `sensoriamento_remoto` | status da checagem; metadados em `metadados_laudo`, `metadados_sr` ou no topo do resultado |
| `MCR-2-7-item15-independencia-fiscal` | evidência `declaracao` | `meta.assunto = "independencia_fiscal"`, `meta.conflito` |
| `OP-2-9-prodes-status` | `consultar_prodes` + evidências `documento` | status da checagem; `meta.tipo_documento`, `meta.data_emissao` |
| `OP-custeio-lotacao` (0.4.0) | `checar_lotacao` (opcional) | última checagem ok: `lotacao_cab_ha`, `classe` (`nao_aplicavel_confinamento`), `cabecas`, `area_ha`; sem ela, soma das cabeças dos itens de bovinos ÷ área informada (senão a financiada, com aviso; senão a total) |
| `MCR-2-7-item1-metodo-documentado-if` (0.4.0) | nenhuma | `efeito.perfil` → `efeito.metodo` do perfil (componentes em `efeito.componentes`; `efeito.campos` liga cada componente ao campo do fluxo, e componente cujo campo tem condição falsa para o item fica em `valor.nao_aplicaveis`) e `Fiscalizacao.metodo` |

As conciliações de documento (docs_fiscais 0.2.0) acrescentam dois campos lidos pelo mesmo
`status_checagem` de `OP-bovinos-gta` e `MCR-2-5-item10-comprovante-aquisicao` (o status da checagem é o pior
dos campos):

- `documento:gta:nfe_guia` (regra `NT-2024.003-ZF`). Leiaute conferido no PDF da NT 2024.003 v1.03: ZF01
  `agropecuario` 0-1 com ZF04 `guiaTransito` 1-1, ou seja, **uma guia por NF-e**; ZF07 `serieGuia` é C 1-9 e
  opcional. Por NF-e: a GTA citada está entre as apresentadas → ok; não está (ou o mesmo número com outra UF
  ou série, ou número ilegível na foto) → pendente, com o pedido "apresente a GTA citada na nota". **Nunca
  divergente**: o fiscal pode só não ter enviado a GTA citada. GTA apresentada que nenhuma nota cita não muda
  o status (numa compra em várias cargas com uma NF-e, só uma GTA cabe no grupo): fica em
  `valores.gtas_sem_citacao`. Nota sem o grupo não gera o campo (ausência neutra, decisão do memorando).
  Atenção: a regra ZF05-10 (rejeição 836) está ativa para NCM 0102 em BA, GO, MA e MT (tabela 4.1 das v1.03
  e v1.10: 01/10/2025; pelo cronograma da v1.10, as regras de validação da NT entraram em produção em
  01/03/2026), então em GO a NF-e real de compra de gado traz o grupo. Tratar a ausência em nota de GO
  posterior a essa data como alerta muda a saída das ferramentas e, com ela, a chave dos replays: fica para
  quando os replays forem regravados.
- `documento:gta:reuso` / `documento:nfe:reuso` (regra `MCR-2-7-item6`; análogo da regra 10ZF04-20, rejeição
  838 "Guia de Trânsito já utilizada"). Índice local (`docs_fiscais/indice.py`) com os documentos de **laudos
  selados**, só HMAC com o sal da instalação, **por operação** (HMAC da ref. Bacen): documento em laudo selado
  de outra operação → divergente; da mesma operação e só de outro item → pendente; mesma operação e mesmo
  item (refiscalização) → ok, também quando o laudo selado aceitou o documento em dois itens (uma NF-e de dois
  lotes: a decisão foi do fiscal que assinou e a refiscalização não a reabre). As ferramentas só **consultam** (quando recebem `indice_documentos` e
  `operacao_ref`); o registro é da selagem, para que documento enviado por engano ou estado intermediário
  nunca entre no índice. **Ligado no produto desde 16/10/2026 (onda 3, `laudo.agent.indice`):**
  - consulta: o executor (`preencher_argumentos`) preenche `indice_documentos` =
    `<dir_dados>/indices/documentos.jsonl` (ao lado de `fotos.jsonl`) e `operacao_ref` = ref. Bacen da
    operação. O LLM não vê nem escolhe os dois campos (ficam fora do esquema dele e, se vierem, são
    descartados);
  - registro: `registrar_na_selagem(fis, dir_dados)`, chamado por `tools/laudo.py::selar` depois da assinatura
    humana. Só grava com a etapa SELADO e a assinatura registrada, e só os documentos que **comprovaram** o
    item (`docs_fiscais.indice.documentos_selaveis`): conciliação final (não substituída), status `ok`, ligada a
    evidência da fiscalização e de um item da operação. Fica de fora a GTA enviada por engano (a conciliação que
    a inclui diverge ou fica indeterminada), a leitura de foto não validada e o documento acusado de reuso.
    Falha de disco no índice não desfaz a selagem: vira span com erro no trace;
  - a chave de contexto é **operação (ref. Bacen) + item**, nunca o id da fiscalização: a refiscalização
    legítima da mesma operação (nova fiscalização, mesmos documentos) dá ok;
  - as descrições de `conciliar_nfe` e `conciliar_gta` que o LLM lê passaram a citar o reuso (e, na GTA, o
    grupo ZF). Isso muda o hash do esquema das duas ferramentas e, com ele, a chave dos replays gravados com
    ferramentas reais, que são regravados na r4 (registro em `tools/documentos.py`).

Uma `Checagem` com `regra_id` apontando para **outra** regra conhecida do rulebook não é usada por esta.

## 4. Versionamento

- **Versão semântica** em `versao`, gravada em todo `Envelope.fonte_versao` (`rulebook-mcr-2-7@0.1.0`) e em
  `Fiscalizacao.rulebook_versao`. O `sha256` do YAML carregado sai em `explicar_regra` e deve ir para o laudo
  selado. Assim, um laudo de março pode ser reproduzido com o rulebook de março.
  - **MAJOR**: nova resolução muda a semântica de uma regra (ex.: o CMN altera o prazo de 60 dias) ou uma
    regra é removida. Fiscalizações abertas continuam na versão antiga.
  - **MINOR**: regra nova, parâmetro operacional recalibrado ou critério de status alterado. Qualquer
    mudança que altere o status de algum caso de teste existente é, no mínimo, MINOR.
  - **PATCH**: correção de citação, texto, pedido ou fonte, sem mudança de status em nenhum teste.
- **Vigência**: `vigencia_inicio` do rulebook, e `vigencia_inicio` por regra quando o item tem data própria
  (ex.: MCR 2-9-16 desde 01/07/2026). Datas de início que dependem do caso, como as faixas de módulos
  fiscais do 2-9-17, ficam no `efeito`, nunca em código.
- **Vigilância de alteração normativa**: a seção "Fontes" de `docs/normas/*.md` registra a varredura feita
  (Resoluções CMN 5.269 a 5.343, nenhuma altera o 2-7). Para repetir: API de normativos do BCB
  (`/api/conteudo/app/normativos/exibenormativo?p1=Resolução CMN&p2=<n>`), campo `Referencias` contendo
  "MCR 2-7" ou "MCR 2-9". Também vale conferir o cabeçalho "Atualização MCR nº" da seção no SGM.
- Cada mudança de versão vai num commit próprio (`regras: mcr-2-7 0.1.0 → 0.2.0`), com a lista de casos de
  teste cujo status mudou.

### Perfis (0.4.0; revisão 0.5.0): custeio de aquisição e manutenção de animais

Um **perfil** é uma regra com `efeito.fluxo` e `condicao` sobre a operação e o item.
`tools/regras.py::fluxo_do_item` escolhe o fluxo do perfil quando a condição é **verdadeira**; condição
indeterminada (finalidade desconhecida) ou falsa mantém o fluxo do tipo de item de antes. Um fluxo reservado a
perfil nunca é escolhido só pelo tipo.

`OP-perfil-custeio-animais` (operação de `custeio` com item de `bovinos`) escolhe o fluxo `custeio_animais`:

| Campo | Regra | Observação |
|---|---|---|
| `quantidade` | `OP-bovinos-contagem-tolerancia` | a mesma contagem do investimento (intervalo contra Q × (1 − 5%)) |
| `comprovante_nfe` | `MCR-2-5-item10-comprovante-aquisicao` | só quando o item é de aquisição (`item.aquisicao`); "manutenção" sem compra dispensa |
| `gta` | `OP-bovinos-gta` | idem; inclui o grupo ZF e o índice de reuso das conciliações |
| `lotacao` | `OP-custeio-lotacao` | não bloqueante; acima de `PAR-custeio-lotacao-atencao-cab-ha` ou sem área: pendente |
| `metodo_if` | `MCR-2-7-item1-metodo-documentado-if` | norma (item 1-c, citação literal); registra perfil, versão e sha256 do rulebook e os componentes que se aplicam ao item (só manutenção: contagem e lotação); não bloqueante |

`item.aquisicao` vem da descrição do item (`eh_aquisicao`): "aquisição"/"compra" → verdadeiro; só
"manutenção" → falso; nada disso → indeterminado, e o campo de NF-e/GTA é mantido (nunca dispensado por falta
de dado). A marcação dos animais (`MCR-3-3-item10-marcacao-animais`, crédito de investimento) deixou de ser
recomendada em operação de custeio. Para investimento, ou finalidade desconhecida, nada muda: os mesmos três
campos de antes.

**Plano (0.5.0).** O `planejar_metodo` mostra o método do perfil por item com a mesma regra do campo
`metodo_if` (`tools/regras.py::componentes_aplicaveis`): `metodos_por_item[i].perfil` traz `metodo_if` só com
os componentes que se aplicam, `componentes` e `nao_aplicaveis`. Item só de manutenção: contagem e lotação,
mais a nota `manutencao` ("NF-e e GTA de compra não se aplicam"), e nunca NF-e nem GTA. Item de aquisição, ou
que não dá para classificar: contagem, NF-e, GTA e lotação, sem a nota de manutenção.

Casos de dev do perfil (4, nunca para o número do slide): `CUSTEIO_DEV` em
`eval/golden/gerador/casos_publicos.py`, versionados em `eval/golden/casos_publicos/dev_custeio/` (split
`dev_custeio`, com SPLIT.yaml próprio) e rodados no modo determinístico por
`tests/unit/test_regras_custeio.py`; os 6 casos públicos ficam no split separado `eval/golden/casos_publicos/`
(`tests/unit/test_casos_publicos.py`).

## 5. Revisão por especialista (agrônomo e compliance)

O rulebook nasce em `revisao.estado: rascunho_tecnico`. O caminho até `aprovado`:

1. **Ler sem código.** Para cada regra do YAML, o revisor confere `titulo`, `citacao`, `criterios` e `pedido`.
   `explicar_regra` devolve o mesmo conteúdo em JSON, junto com a fonte.
2. **Conferir a citação.** `test_citacao_literal_existe_no_texto_normativo` garante que o trecho está em
   `docs/normas`. O revisor confere que o trecho de `docs/normas` é o do MCR vigente (link do SGM e data de
   acesso).
3. **Julgar os parâmetros operacionais.** O agrônomo valida tolerância, distâncias e tentativas, e o
   compliance valida enquadramentos (autofiscalização = documental, GTA, área total). Cada pendência está em
   `revisao.pendencias`.
4. **Casos de borda.** Os testes `test_regras_*.py` são tabelas legíveis: cada linha é um caso, com o item da
   norma no id. O revisor pode propor casos novos como linhas novas. Uma divergência de entendimento vira um
   caso que falha.
5. **Registrar.** Ao aprovar, a revisão é registrada no próprio YAML, sem PII (use referência pseudonimizada
   e, para o agrônomo, o número da ART). Exemplo:
   `revisores: [{papel: agronomo, ref: "rev-agro-01", art: "<nº ART>", em: 2026-10-20, versao: 0.2.0}]` e
   `estado: revisado_especialista`. Só passa a `aprovado` com compliance e agronomia registrados.
6. Mudança feita depois da aprovação volta o estado para `revisado_especialista` até nova aprovação.

## 6. Adicionar o rulebook de perdas (Proagro, Res. CMN 5.315/2026) depois

A Res. CMN 5.315, de 25/06/2026 (em vigor desde 01/07/2026), alterou o **MCR 12-4, itens 15 e 16** (Proagro,
comprovação de perdas). O item 16-"e" exige, em cada visita, "pelo menos três fotos coloridas" com pontos de
referência, uma delas "com o agricultor ou seu preposto", e tecnologia que ateste a captura dentro das
coordenadas da área enquadrada. Esses requisitos hoje estão como POL-01 na política do agente.

Passos:

1. **Texto.** Obter o texto do MCR 12-4 no SGM (https://manuais.bcb.gov.br/app/manual/mcr/publico, capítulo
   12, seção 4) e a Res. 5.315 na API de normativos. Salvar os trechos literais em
   `docs/normas/mcr_12_4.md`, com URL, data de acesso e número do item.
2. **YAML.** Criar `src/laudo/rulebooks/mcr_12_4.yaml` (`id: mcr-12-4`, `vigencia_inicio: 2026-07-01`) e
   registrá-lo em `ARQUIVOS` (`rulebooks/__init__.py`). Regras candidatas:
   - `MCR-12-4-item16-fotos-minimas` (`requisito_evidencia`, norma): ≥ 3 fotos coloridas por visita;
   - `MCR-12-4-item16-foto-agricultor` (norma): uma foto com o agricultor ou preposto;
   - `MCR-12-4-item16-fotos-na-area` (norma): fotos dentro das coordenadas da área enquadrada. Pode
     reaproveitar o avaliador `geofence_distancia` com `PAR-geofence-perto-m: 0`, já que a norma diz "contida
     nas coordenadas";
   - `MCR-12-4-item15-visita-unica` (norma): condições da vistoria única em perda parcial de alta gravidade;
   - parâmetros operacionais de estimativa (n mínimo de amostras, CV máximo) com justificativa.
3. **Fluxo.** Adicionar `fluxos.lavoura_perda` com `tipos_item: [lavoura]`. Hoje `lavoura` cai em
   `OP-escopo-itens-regional` e bloqueia.
4. **Avaliadores novos**, só se nenhum existente servir: por exemplo `contagem_evidencias` (n fotos válidas
   por visita, com classe "agricultor") e `estimativa_intervalo` (produtividade com intervalo × perda
   declarada, no mesmo desenho da contagem de bovinos). Cada avaliador novo entra em
   `tools/regras.py::AVALIADORES` e ganha testes por tabela.
5. **Seleção do rulebook.** `ContextoRegras.rulebooks` já permite `["mcr-12-4"]`. É preciso só generalizar o
   laço de `avaliar()` sobre os rulebooks pedidos. O ideal é a fiscalização ter um tipo (fiscalização ×
   comprovação de perdas); ver as propostas para `contracts.py` no relatório.
6. **Testes.** Criar `tests/unit/test_regras_proagro_*.py` com casos de borda: exatamente 3 fotos, 2 fotos
   válidas mais 1 sem GPS, foto do agricultor fora da área, e vistoria única com e sem alta gravidade.
7. **Política.** Quando o rulebook cobrir o 12-4-16-e, POL-01 passa a citar o `regra_id` do rulebook, e não
   um texto solto.

## 7. Lacunas conhecidas

Estão documentadas no fim de `docs/normas/mcr_2_7.md` e `docs/normas/mcr_2_9.md`:

- não há tolerância de contagem nem prazo específico para animais no 2-7;
- a GTA está fora do MCR;
- a "área total" não é definida;
- as remissões do 2-9-18 ficaram desatualizadas depois da Res. 5.314;
- a conformidade de ASV com a Conama 510 não é verificável automaticamente;
- a "lista do MMA" ainda não tem formato definido.
