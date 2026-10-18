# Laudo selado de exemplo: caso `DEMO-0001` (demonstração, dados sintéticos)

> **DEMONSTRAÇÃO — dados sintéticos.** O caso `DEMO-0001` é uma **operação fictícia**. A REF é `000000001`, que
> não existe no Sicor, e a cooperativa é fictícia. O tomador aparece só como pseudônimo (`hmac:…`), e a fiscal é
> `fiscal-sintetico-01`, com o PIN de demonstração. O vídeo, as fotos, a NF-e, a GTA, as falas e **todos os
> defeitos** são sintéticos e foram plantados. A gleba nasce de uma geometria pública do Sicor/BCB, que foi
> espelhada, girada e deslocada para longe de qualquer gleba do bench. O GPS das fotos passou pela mesma
> transformação. Nada aqui descreve operação, propriedade ou produtor reais. A prioridade de verificação que
> aparece no laudo não é indício de irregularidade.

Esta pasta mostra à banca a **saída** do Laudo Vivo sem que seja preciso rodar o sistema. É o laudo que a fiscal
assina no fim da demo, como ele sai da máquina: selado, com a prova de cada item e com o que é preciso para
conferi-lo. Ele foi gerado pela demo da linha de comando, com as ferramentas reais (contagem no vídeo, NF-e, GTA,
integridade e localização das fotos, satélite, regras) e o LLM em replay, sem GPU. O replay devolve as respostas que
o `qwen3.5:4b` deu na gravação.

**Versão:** o arquivo [`gerado_com.json`](gerado_com.json) registra:

- o `sha256(src/)` do código que gerou o laudo e a fixture de replay (com o sha256);
- se o caminho foi o de 19 passos (com a foto da nota impressa) ou o de 17 (só o XML da NF-e);
- o resultado da conferência do selo feita na instalação que gerou o laudo.

Se esse arquivo traz `"provisorio": true`, o exemplo é anterior ao congelamento do código (r4) e será gerado de
novo antes da entrega (seção 6). O bloco abaixo é escrito pelo `conferir_exemplo.py` a partir do
`gerado_com.json` a cada geração, e a conferência acusa se os dois divergirem:

<!--estado_exemplo-->
> **Estado do exemplo** (escrito por `conferir_exemplo.py` a partir do `gerado_com.json`; não edite à mão):
> gerado em 16/10/2026 às 23:11. Caminho de 19 passos: com a foto do DANFE (roteiro do palco). Código:
> `sha256(src/)` `52be6b825037b28f…`. Fixture de replay: `replay_demo_real_qwen35_4b.jsonl`
> (`77d4825382a8a4aa…`). Conferência do selo na instalação: confere (laudo selado confere). Os números do
> pitch são de outro código (r4 de 2026-10-16, `1154df4aceffbf20…`).
<!--/estado_exemplo-->

Os números desta página (contagem, quantidade financiada, distâncias) são os do
próprio laudo de exemplo. Os números de avaliação ficam em
[`docs/entregaveis/numeros.md`](../entregaveis/numeros.md).

## 1. O que tem aqui

| Arquivo | O que é |
|---|---|
| [`laudo_selado.html`](laudo_selado.html) | o laudo como a fiscal o assina: marca d'água, identificação da operação, método, sensoriamento remoto, itens com status e prova, ocorrências, hash raiz e assinatura |
| [`laudo_selado.json`](laudo_selado.json) | o mesmo laudo em JSON. **Este é o documento que vale como prova**: o HTML é uma renderização dele, e o selo cobre o conteúdo do JSON |
| [`laudo_selado.pdf`](laudo_selado.pdf) | o HTML impresso em PDF (Edge headless), para quem não vai abrir o HTML. É só uma visão: não entra no hash raiz. Os links relativos viram texto e o rodapé repete a marca de demonstração |
| [`DEMONSTRACAO_pacote_exibicao.zip`](DEMONSTRACAO_pacote_exibicao.zip) | o pacote de exibição BCB/Justiça da mesma fiscalização. A fiscal o gera com um clique, sem LLM, e ele só fica liberado depois do selo. Traz o `manifest.json` com o sha256 de cada arquivo, o laudo e o rascunho assinado, a gleba e as fotos em GeoJSON, as cenas do satélite, o fundamento por item, a memória de cálculo, a ciência do mutuário com prazo de contestação, a seção de reversão (IN BCB 758), o checklist "Ordem JF Rio Verde", os quadros-chave e as fotos, a cadeia de evidências e o **trace** (`trilha/trace.jsonl`) |
| [`SHA256SUMS`](SHA256SUMS) | sha256 dos quatro arquivos acima |
| [`gerado_com.json`](gerado_com.json) | versão do código, fixture, caminho do roteiro e conferência do selo na instalação |
| [`.gitattributes`](.gitattributes) | guarda os arquivos gerados byte a byte no git (o laudo sai com CRLF; sem isso o clone teria LF e não conferiria) |
| [`conferir_exemplo.py`](conferir_exemplo.py) | confere esta pasta sem a instalação (seção 4) |
| [`gerar_exemplo.sh`](gerar_exemplo.sh), [`gerar_pdf.cjs`](gerar_pdf.cjs) | geram tudo de novo (seção 6) |

## 2. Como ler o laudo: item → evidência → checagem → trace

Cada linha da seção "3. Itens financiados e prova" do laudo é **um aspecto de um item financiado**. Ela traz o
status, a regra citada (`regra_id`, com o texto da norma em `fundamento/fundamento_por_item.json` do pacote) e de
onde veio o valor ("vídeo (contagem por visão computacional)", "XML da NF-e", "foto georreferenciada",
"declaração do fiscal"…). Traz também as **evidências** (id, tipo e sha256 na cadeia de hash) e as **checagens**
(id, ferramenta e status), cada uma com o `span_id` do **trace**. O status sai do verificador determinístico, a
partir das checagens. O modelo de linguagem não define status nem número.

Exemplo, a contagem das vacas, para seguir a trilha de ponta a ponta:

1. **Item:** `item:bov1:quantidade` (Quantidade (contagem)), **divergente**, regra `OP-bovinos-contagem-tolerancia`.
   O valor apurado é `12 (12 a 17)` contra 29 financiadas. O limite é 27,55, e a contagem fica abaixo dele mesmo
   no extremo superior do intervalo.
2. **Evidências:** o vídeo do lote no corredor e os quadros-chave que a contagem marcou. O sha256 de cada um está
   na cadeia (`trilha/cadeia_de_evidencias.json` do pacote), e os quadros-chave estão em `evidencias/`.
3. **Checagem:** `contar_bovinos_video`, com `fonte_versao` `yolox_m@…+contador@…`. Em
   `calculo/memoria_de_calculo.json` do pacote estão a contagem, o intervalo, o modelo com o sha256 e a licença, a
   confiança média, a oclusão e os quadros-chave.
4. **Trace:** procure o `span_id` dessa checagem em `trilha/trace.jsonl`. O span `tool contar_bovinos_video` traz o
   hash dos argumentos, a versão, a latência e o resumo do resultado. Os spans de cada turno mostram também as
   decisões da política (`policy.decision`) e as chamadas ao LLM.
5. **Humano:** a justificativa da fiscal ("Confirmo a divergência na contagem…") fica ao lado do item. **A
   divergência continua no laudo**: a justificativa explica o achado, mas não troca o valor.

| Item / aspecto | Status no exemplo | Evidência | Checagem (ferramenta) |
|---|---|---|---|
| 29 vacas leiteiras · quantidade | divergente (com justificativa da fiscal) | vídeo + quadros-chave | `contar_bovinos_video` (YOLOX em CPU) |
| 29 vacas leiteiras · comprovante (NF-e) | verificado | XML da NF-e (no caminho de 19 passos, antes vem a foto da nota impressa, lida pelo VLM e completada pela fiscal) | `conciliar_nfe` |
| 29 vacas leiteiras · GTA | divergente (com justificativa da fiscal): GTA emitida antes da NF-e | e-GTA | `conciliar_gta` |
| Cerca de 1.200 m · integridade da foto | verificado | 2 fotos com EXIF e GPS | `integridade_foto` |
| Cerca · localização (foto na gleba) | verificado (a 1ª foto, a ~650 m da borda, saiu divergente e continua na trilha) | foto nova, de dentro da gleba | `geofence` |
| Cerca · conclusão da obra | verificado | fotos classificadas pelo VLM + declaração da fiscal | `classificar_foto`, `declaracao_conclusao` |
| Cerca · prazo do cronograma | verificado | data da fiscalização contra o cronograma | regra (sem ferramenta) |
| Laudo · método, independência da fiscal, metadados do satélite (MCR 2-7, item 4-b) | verificado | método registrado, declaração de independência, série Sentinel-2 da gleba | `planejar_metodo`, `serie_ndvi` |

Também estão no laudo:

- as **ocorrências**: a pressão "pode marcar 29", recusada (POL-07), e a instrução embutida no texto da GTA,
  tratada como dado (POL-06);
- a **identificação da operação** com o vetor da gleba em GeoJSON e as coordenadas e o horário das fotos;
- o **sensoriamento remoto** com satélite, sensor, datas, resolução, bandas e metodologia (MCR 2-7, item 4-b);
- o **hash raiz**, que é o que a fiscal assinou;
- a **assinatura humana** (`papel: fiscal`, com o hash assinado).

O agente se recusou a assinar e, depois do selo, recusou a alteração "muda a contagem para 29" (POL-04): uma
correção vira uma nova fiscalização.

## 3. O que a fiscal fez para chegar a este laudo

O roteiro da demo está em [`apps/web/ROTEIRO_DEMO.md`](../../apps/web/ROTEIRO_DEMO.md) e no `--help` de
`scripts/demo_cli.py`. Em resumo:

1. o agente diz por que a operação caiu na amostra e qual método a regra pede;
2. consulta o satélite da gleba e registra a declaração de independência da fiscal;
3. conta o lote no vídeo (divergente) e recusa a pressão para "marcar 29";
4. concilia a NF-e e a GTA. A GTA traz uma instrução embutida, que é tratada como dado;
5. **bloqueia o rascunho** enquanto há pendências, entre elas a foto da cerca tirada fora da gleba;
6. aceita a foto nova de dentro da gleba e as justificativas da fiscal para as duas divergências;
7. emite o rascunho e se recusa a assinar. A fiscal assina com o PIN sobre o hash, e o laudo é selado.

## 4. Como conferir

**Com o repositório, sem a instalação que gerou o laudo** (na raiz):

```bash
scripts/py.sh docs/exemplos/conferir_exemplo.py
```

O script recalcula o selo, confere que a assinatura é do hash raiz e recalcula o hash raiz do conteúdo assinado. Ele
também renderiza o HTML de novo a partir do JSON e compara. Depois confere a marca d'água, o `SHA256SUMS` e o
pacote: cada arquivo contra o `manifest.json` dele, com o mesmo selo e o mesmo laudo. Num clone, confere também
que o git guarda os arquivos gerados sem converter fim de linha. O código de saída é 0 quando tudo confere. Se
alguém trocar um valor no JSON, o hash raiz recalculado diverge. Se um arquivo só perdeu o CRLF (cópia feita sem o
`.gitattributes` desta pasta), o script diz isso em vez de acusar adulteração. No fim, ele avisa (sem falhar) se o
exemplo é provisório ou se não é do mesmo código dos números do pitch.

**Sem Python:** `sha256sum -c SHA256SUMS` nesta pasta. Depois abra o ZIP e compare o sha256 de cada arquivo com o
`manifest.json` (o `LEIA-ME.txt` do pacote explica).

**Na instalação que gerou o laudo:** `scripts/py.sh -m laudo.audit.selo --dados <pasta de dados> fis_demo_0001`.
Esse comando confere também a cadeia de hash das evidências, o rascunho assinado registrado nela e as aprovações
gravadas. O resultado dessa conferência, feita na geração, está em `gerado_com.json`, no campo
`conferencia_na_instalacao`.

**Limite declarado** (`src/laudo/audit/selo.py`): sem uma chave por assinante, quem tem acesso ao disco consegue
refazer laudo, rascunho, estado e selo de forma coerente. O selo de hoje fecha a cópia adulterada: quem troca um
arquivo sem refazer o conjunto inteiro é pego. A credencial por usuário, a chave por fiscal e o recibo enviado à IF
fecham o resto e ficam para depois.

## 5. Limites deste exemplo

- **Links do laudo:** os links de evidências e do trace são relativos à pasta de dados da instalação e, em geral,
  não abrem a partir desta pasta. A geração roda numa pasta irmã do repositório, e por isso os links para as
  entradas da demo começam com `../../../laudo-vivo/` (só o nome da pasta do repositório, nenhum caminho da
  máquina). No PDF eles viram texto. Neste repositório, a prova está no ZIP (`evidencias/`, `trilha/`, `geo/`,
  `satelite/`). O vídeo não vai no pacote: vão o sha256 dele e os quadros-chave.
- **PDF:** é o HTML impresso. Para caber na página, o `gerar_pdf.cjs` acrescenta só CSS de impressão (o carimbo
  "SELADO · ASSINADO" fora da faixa de demonstração, quebra de texto longo como o pseudônimo `hmac:…`, marca
  d'água menor); o texto é o do HTML selado.
- **Resumo:** o resumo do laudo é o de template ("Texto gerado por template"). Um texto do LLM só entraria se
  passasse no grounding numérico (POL-05).
- **Checklist "Ordem JF Rio Verde":** o pacote registra o status real de cada item. Meteorologia fica como "não
  aplicável", com justificativa, e o fundamento fica como "parcial", porque as regras de documentos fiscais ainda
  não têm citação literal. Nada disso é contado como "presente".
- **Template:** se o template do laudo mudar depois, a conferência acusa o HTML como "não conferível". O JSON
  continua conferível.
- **Uso:** é uma demonstração. Nenhum fiscal real usou o sistema para produzir este laudo.

## 6. Como gerar de novo (depois do fim da r4)

Sem GPU, na raiz do repositório (Git Bash), **depois que a r4 terminar** (o script recusa enquanto ela roda,
porque a etapa "custo" da r4 roda a mesma demo ao vivo, e recusa sem folga de memória):

```bash
bash docs/exemplos/gerar_exemplo.sh               # 19 passos: o roteiro do palco, com a foto do DANFE
bash docs/exemplos/gerar_exemplo.sh --passos 17   # 17 passos: só o XML da NF-e
```

O script faz o seguinte:

1. roda `scripts/demo_cli.py --ferramentas reais --llm replay --replay <fixture> --sem-cor --pacote`, com
   `--dados` numa pasta irmã do repositório (`../.tmp_exemplo_laudo`, nunca dentro dele);
2. **recusa** a geração se a demo não selou, se o número de passos não é o pedido, se o replay teve requisição
   fora da gravação, se o LLM ficou fora em algum turno, se o VLM saiu do cache, se uma ferramenta falhou ou se o
   laudo saiu sem satélite;
3. confere o selo com `laudo.audit.selo` na instalação;
4. monta o laudo e o pacote (até 2 MB) numa pasta de montagem, também fora do repositório;
5. imprime o PDF com o Edge sem GPU (`gerar_pdf.cjs`, via o `playwright-core` de
   `../../personas-ux/app/node_modules`; troque com `NODE_PATH=...`);
6. grava o `SHA256SUMS` e o `gerado_com.json` na montagem;
7. confere a montagem;
8. roda o `checar_pii` e as frases proibidas na montagem **e no conteúdo do ZIP**;
9. só então troca os arquivos desta pasta e reescreve o bloco de estado deste README;
10. confere esta pasta de novo (inclusive o `.gitattributes`) e as frases proibidas do README.

Uma falha antes do passo 9 deixa esta pasta como estava. Se só o PDF ou um passo posterior falhou, rode de novo
com `--reusar` (não roda a demo outra vez). Depois rode `scripts/py.sh scripts/checar_pii.py --parquet` no
repositório inteiro e registre no `CHANGELOG.md` o `sha256(src/)` que está no `gerado_com.json`.

As fixtures são gravadas na r4 (`docs/runbook.md`, seção 8): o de 19 passos usa
`tests/unit/dados_agente/replay_demo_real_qwen35_4b.jsonl`, e o de 17 usa
`tests/unit/dados_agente/replay_demo_real_sem_danfe_qwen35_4b.jsonl`. Se o código mudar depois da gravação, o
script recusa a geração: grave de novo antes de gerar.
