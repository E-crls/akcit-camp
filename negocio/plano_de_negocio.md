# Plano de negócio: Laudo Vivo

**Laudo Vivo: prova auditável do crédito rural, do satélite ao curral.**

Base: cálculo próprio sobre os microdados públicos do Sicor 2025 ([`dados_mercado/`](dados_mercado/README.md)),
o bench Fiscal-GO 2026 do produto e as fontes públicas citadas em cada linha. Os números de mercado, com tipo,
fonte e método, também estão em
[`../laudo-vivo/docs/entregaveis/mercado.md`](../laudo-vivo/docs/entregaveis/mercado.md).

**Legenda.**
- **[F]** fato com fonte (link na linha).
- **[D]** dado calculado por nós a partir de fonte pública, reproduzível em `dados_mercado/README.md`.
- **[E]** estimativa nossa, com a conta exposta.
- **[H]** hipótese que só entrevista ou piloto confirma.
- *a medir* marca um dado que depende de entrevista ou piloto (lista na seção 16); não é preenchido com
  estimativa.
- Câmbio usado nas contas: R$ 5,50 por US$ [E].

---

## 0. Resumo em uma tela

| Pergunta | Resposta |
|---|---|
| Problema | A instituição financeira (IF) responde pela aplicação do crédito rural "antes da contratação até a liquidação" e precisa provar isso ao Banco Central com métodos verificáveis ([Res. CMN 5.267](https://www.normasbrasil.com.br/norma/resolucao-5267-2025_487044.html), em vigor desde 01/03/2026). A imagem de satélite gratuita prova lavoura, não gado, benfeitoria ou máquina; a de altíssima resolução vê o curral e estima o rebanho, mas não prova que é o bem financiado nem confere nota fiscal e GTA. Hoje isso se resolve com visita presencial e papel, e o próprio BCB registrou que as IFs evoluíram pouco no remoto (Voto 166/2025-BCB). |
| Para quem | Usa: a fiscal de campo ("Paula") da cooperativa ou da empresa credenciada. Paga: a cooperativa de crédito (a IF responsável) e a credenciada que fiscaliza para ela. |
| Solução | Um agente que escolhe o método (remoto, documental, presencial ou autofiscalização assistida), conduz a coleta por voz, confere vídeo e foto georreferenciada contra NF-e, GTA, projeto e dado público, classifica cada item como verificado, divergente, pendente ou abstenção, recusa pressão e só libera o rascunho para assinatura humana quando existe a evidência mínima da norma. |
| Cunha | Fiscalização de investimento pecuário: compra de bovinos + cerca/curral (MCR 2-7). |
| Expansão | Exceções socioambientais (MCR 2-9) como segundo módulo; perdas (Proagro, seguro) na safra de perda; "Lastro" (garantias para crédito privado) depois. |
| Por que agora | Res. 5.267 em vigor desde 01/03/2026; o BCB pode fiscalizar e substituir amostras; o TCU mandou auditar o crédito rural em 28/01/2026; o PRODES entra no crédito em 04/01/2027. |
| Mercado | 525.340 itens físicos (gado, benfeitorias, máquinas) acima de R$ 20 mil financiados em 2025 [D]. TAM central de ~R$ 125 mi/ano (fiscalização como serviço + exceções socioambientais); SAM nas cooperativas de ~R$ 32 mi/ano; SOM de 36 meses de R$ 2–4 mi de ARR [E]. Conta na seção 4. |
| Modelo | Por fiscalização concluída (preço-alvo de R$ 79), licença por fiscal para credenciada (R$ 590/mês), exceção socioambiental resolvida (R$ 490) e, na fase 2, fiscalização remota-first entregue como serviço (R$ 290). Preços a testar (seção 5). |
| Margem | 82–92% no software; ~56% no serviço; ~80% no mix do ano 2 [E] (seção 6). |
| Defensibilidade | **Já existe:** golden set próprio (sintético, com defeitos plantados) e o MCR 2-7 e 2-9 como código, com o item citado em cada regra. **A construir com os pilotos:** dado de desfecho de fiscalização (o que foi aceito, devolvido, desclassificado), vídeos de curral anotados e uma rede de credenciadas como canal. |
| Pedido | Pré-seed de R$ 2–3 mi para 18 meses, com marcos em M6, M12 e M18 (seção 15). |

---

## 1. Problema

### 1.1 O que a norma exige da instituição financeira

A Res. CMN 5.267, de 28/11/2025, reescreveu a Seção 7 do Capítulo 2 do MCR (monitoramento e fiscalização) e
vale desde **01/03/2026**
([Normas Brasil](https://www.normasbrasil.com.br/norma/resolucao-5267-2025_487044.html);
[Voto CMN 78/2025](https://normativos.bcb.gov.br/Votos/CMN/202578/Voto_do_CMN_78_2025.pdf)) [F]:

| Item do MCR 2-7 | O que diz (resumo) | Consequência para o produto |
|---|---|---|
| 1 | A IF é responsável pelo monitoramento e pela fiscalização, com critérios verificáveis e registro das verificações | quem paga é a IF |
| 3 | Métodos admitidos: sensoriamento remoto, documental e presencial, isolados ou combinados; conformidade "antes da contratação até a liquidação" | o agente escolhe e combina métodos |
| 4 | O laudo remoto registra satélite, sensor, datas, resoluções, bandas e metodologia | metadados no laudo, por item |
| 5 | Sensoriamento remoto obrigatório só em custeio e investimento acima de 300 ha | a maior parte das operações cai no documental e no presencial |
| 9 | Na pecuária, a contagem de animais por satélite é **facultativa** | a norma reconhece o lugar da evidência de campo |
| 10 | O satélite não dispensa outros métodos quando o resultado é inconclusivo | abstenção do remoto aciona o campo |
| 12 | Amostragem com critério estatístico definido pela IF | a IF precisa priorizar a amostra |
| 14 e 15 | Pode terceirizar, mantendo a responsabilidade integral; **é vedado** usar quem foi contratado pelo mutuário para assistência técnica ou empresa de que o mutuário participe | o fornecedor é contratado pela IF, nunca pelo produtor |
| 16 | Benfeitorias: ao menos uma verificação até o fim do cronograma; máquinas: verificação em até **60 dias** da liberação, com nota fiscal | prazos que viram SLA |
| 18 | O mutuário pode ter de ressarcir fiscalização frustrada por culpa dele | custo de visita perdida existe e tem dono |
| 21 e 22 | Indício de ilícito é comunicado ao Ministério Público; comunicações ficam arquivadas pelo prazo de prescrição | trilha de auditoria de longo prazo |
| 23 e 24 | A documentação fica à disposição do BCB, que pode fiscalizar, requisitar o fiscal e **substituir amostra inconsistente** | a IF precisa de prova que resista a auditoria |

### 1.2 Onde a imagem de satélite não chega

- **O satélite fiscaliza o visível; a documentação fiscaliza o invisível.** A compra de gado, insumos e
  equipamentos exige nota fiscal e comprovante
  ([Agrolink, 15/05/2026](https://www.agrolink.com.br/noticias/credito-rural-tera-fiscalizacao-rigida--entenda-o-que-muda_514561.html))
  [F].
- Em 2025, **63% dos itens financiados no país (1.556.243 linhas, R$ 123,1 bi) foram bens físicos que a imagem
  de 10 m não prova**: animais, cercas, currais, cochos, máquinas [D].
- Em Goiás, de janeiro a setembro de 2026, **66% das operações (19.009 de 28.637) foram de pecuária bovina**;
  **13.385 financiaram compra de gado** (R$ 4,76 bi), das quais **6.235 por investimento** (matrizes e
  reprodutores, R$ 1,23 bi) e 7.150 por custeio de aquisição e manutenção de animais (R$ 3,53 bi)
  (`../laudo-vivo/bench/fiscal_go/resumo.json`; detalhe em `../laudo-vivo/docs/entregaveis/mercado.md`,
  seção 2) [D].
- Existe contagem de gado por imagem de altíssima resolução (Audsat,
  [blog de 09/02/2026](https://www.audsat.com.br/blog/resolucao-cmn-5267-2025/)) [F]. Ela não prova que o boi
  visto é o boi financiado (animal emprestado, rebanho preexistente), não confere categoria, nota fiscal nem GTA,
  e custa caro por operação [E].

### 1.3 O custo de errar

- **Casos públicos que mostram que a GTA é necessária, mas não suficiente:** Op. Boi de Papel (PF/TO,
  07/03/2024): GTAs falsas simulando compra de gado inexistente; R$ 94 mi é o crédito concedido pelo FNO entre
  2014 e 2021, não o prejuízo
  ([CompreRural](https://comprerural.com/boi-de-papel-fraude-deixa-prejuizo-de-r-94-milhoes/)); Op. Boi Fantasma
  (MPRS, jun/2026): cerca de mil "bovinos de papel" e movimentação acima de R$ 100 mi
  ([Portal Tela, 14/06/2026](https://www.portaltela.com/noticias/economia/2026/06/14/gado-fantasma-guias-rurais-ocultaram-movimentacao-milionaria-no-rs/));
  Pains (MG): 1.553 cabeças financiadas, 47 encontradas na vistoria
  ([CompreRural](https://comprerural.com/fraude-em-financiamentos-rurais-de-r-18-milhao-faz-politico-virar-reu-na-justica-federal/))
  [F]. Nenhum desses casos é de Goiás, e o pitch não acusa ninguém de Goiás.
- **Controle externo olhando agora:** o TCU determinou em 28/01/2026 auditoria no BCB e em BB, Caixa, Basa,
  BNDES e BNB sobre práticas no crédito rural
  ([Diário do Comércio](https://diariodocomercio.com.br/legislacao/tcu-determina-auditoria-bc-5-instituicoes-financeiras-fiscalizacao-credito-rural/))
  [F].
- **Risco de carteira em alta:** o crédito rural liberado em Goiás de junho a agosto de 2026 caiu 43,2%, o menor
  valor em 8 anos, com "seletividade dos bancos" entre as causas
  ([Sistema Faeg, 05/10/2026](https://sistemafaeg.com.br/noticias/credito-rural-em-goias-menor-liberacao-de-recursos-em-8-anos))
  [F]. Quem empresta com mais cuidado quer prova melhor da aplicação [H].
- **Consequência regulatória:** operação sem comprovação está sujeita a desclassificação ou reclassificação
  (MCR 2-8, citado no item 19 do MCR 2-7) [F].

### 1.4 Como se faz hoje e quanto custa

| O que existe | Valor | Fonte |
|---|---|---|
| Piso de honorário para fiscalização de crédito rural (MS, 2024) | 0,5% do saldo devedor por visita, **mínimo de 4 CA = R$ 669** (CA = R$ 167,34) | [F] [AEA-MS/CREA-MS](https://creams.org.br/wp-content/uploads/2024/08/Tabela-de-Honorarios-Agronomia-2024.pdf). Piso ético de outro estado, não preço praticado |
| Hora técnica de agronomia (mesma tabela) | 3 CA = R$ 502 | [F] idem |
| Credenciamento da Caixa (fiscalização, vistoria prévia, Proagro, garantias) | por hora técnica, com valores mantidos desde 2014 e contestados pelas entidades; referência citada de R$ 180/hora (2019) | [F] [Confea, 01/2022](https://www.confea.org.br/node/226521); [Confea, 11/2019](https://www.confea.org.br/node/224215) |
| Rotina da fiscal | conta boi "no olho" e confere NF e GTA no papel; 72% dos peritos trabalham sozinhos e 76% relatam intimidação (peritos de perdas, coleta de 2021) | [H] persona composta para a rotina; [F] pesquisa MAPA "Perfil dos Peritos" (2.173 respondentes, gov.br/agricultura, 2022) para os percentuais |
| Custo real por visita (deslocamento + horas + laudo) | *a medir*: custo médio por visita presencial (mediana) | entrevistas com fiscais e credenciadas |
| Fiscalizações por mês por fiscal | *a medir*: fiscalizações/mês por fiscal (mediana) | idem |

---

## 2. Por que agora

| Gatilho | Data | Fonte |
|---|---|---|
| MCR 2-7 reescrito (fiscalização auditável, amostragem estatística, metadados, prazos) | em vigor desde 01/03/2026 | [F] [Res. 5.267](https://www.normasbrasil.com.br/norma/resolucao-5267-2025_487044.html) |
| TCU manda auditar BCB e cinco IFs públicas no crédito rural | 28/01/2026 | [F] [Diário do Comércio](https://diariodocomercio.com.br/legislacao/tcu-determina-auditoria-bc-5-instituicoes-financeiras-fiscalizacao-credito-rural/) |
| Fotos georreferenciadas obrigatórias no Proagro | desde 01/07/2026 | [F] [Res. CMN 5.315](https://www.bcb.gov.br/content/estabilidadefinanceira/especialnor/Resolu%C3%A7%C3%A3o5315.pdf) |
| Proibição de financiar projeto que preveja supressão de vegetação nativa (recursos controlados) | desde 01/07/2026 | [F] [Res. CMN 5.314](https://www.bcb.gov.br/api/conteudo/app/normativos/exibenormativo?p1=Resolu%C3%A7%C3%A3o%20CMN&p2=5314) |
| PRODES no crédito rural (MCR 2-9) | 04/01/2027 (>15 MF), 01/07/2027 (4–15 MF), 03/01/2028 (≤4 MF) | [F] [Res. CMN 5.303](https://www.bcb.gov.br/api/conteudo/app/normativos/exibenormativo?p1=Resolu%C3%A7%C3%A3o%20CMN&p2=5303) |
| Declaração de rebanho em Goiás, 2ª etapa | 01 a 30/11/2026 | [F] [Agrodefesa](https://goias.gov.br/agrodefesa/declaracao-de-rebanho-2026-em-goias-primeira-etapa-comecara-em-1o-de-maio-e-tera-prazo-de-31-dias/) |
| Modelos abertos pequenos, rodando local numa GPU de mesa, conduzem a conversa, leem a foto do papel e extraem as alegações da fala | 2026 | [F] o próprio protótipo roda o LLM e o VLM locais ([`../laudo-vivo/docs/COMO_RODAR.md`](../laudo-vivo/docs/COMO_RODAR.md)) |

---

## 3. Persona, comprador e solução

### 3.1 Persona de uso: "Paula"

**Persona composta de fontes públicas, não uma entrevistada.** Paula tem entre 28 e 45 anos e é técnica agrícola
ou agrônoma de uma **empresa credenciada** que fiscaliza para duas ou três IFs, ou analista de fiscalização de uma
cooperativa de crédito em Goiás [H]. Ela recebe a amostra do mês (compras de gado, cercas, currais, máquinas),
conta boi no curral "no olho" e confere nota e GTA no papel. O medo dela não é a tecnologia; é assinar um laudo
que a auditoria ou o BCB derrubem depois, e ser pressionada no curral ("pode marcar 29, o resto está no pasto de
cima").

Atributos que as entrevistas confirmam ou trocam (*a medir*): % de entrevistados que fiscalizam
gado/benfeitoria/máquina, km médios por visita, horas de laudo por fiscalização e fiscalizações devolvidas por
falta de evidência nos últimos 90 dias.

### 3.2 Comprador e porteiros

| Papel | Quem | O que precisa ouvir |
|---|---|---|
| Usa | Paula (fiscal de cooperativa ou de credenciada) | "Você sai do curral com a evidência que a norma pede, e ninguém te convence a marcar o que não viu." |
| Paga | Cooperativa de crédito (gerência de crédito rural ou de controles internos) | "A sua amostra fica auditável, mais barata e mais rápida, e você não depende de fornecedor contratado pelo produtor." |
| Paga (canal) | Dono da credenciada | "Cada fiscal faz mais fiscalizações por dia, com menos retrabalho." |
| Porteiros | Compliance, auditoria interna, jurídico e TI da cooperativa; a central do sistema | trilha de evidência, LGPD, onde o dado fica, quem assina |

### 3.3 A solução

Um agente que transforma uma operação de crédito rural num laudo em que **cada item aponta para a sua prova**.

1. **Triagem da carteira:** ordena as operações por **prioridade de verificação** (lotação implícita,
   sobreposição de glebas, NDVI do pasto, plausibilidade contra o rebanho municipal do IBGE), sempre como ordem
   de conferência, nunca como juízo sobre a operação ou a pessoa.
2. **Plano de método:** aplica as regras do MCR 2-7 como código e decide entre remoto, documental, presencial ou
   **autofiscalização assistida** (o produtor filma sob roteiro com cerca virtual, horário e prova de vida da
   cena), com o prazo do item 16.
3. **Coleta guiada por voz:** "comece pelo curral, filme o lote passando pela porteira".
4. **Checagens determinísticas:** contagem de bovinos em vídeo com intervalo, integridade e geolocalização da
   foto, leitura e conciliação de NF-e (XML) e GTA contra o projeto, série de satélite da gleba.
5. **Verificador independente:** status por item (verificado, divergente, pendente, abstenção), recusa a pressão
   e registra a ocorrência.
6. **Política que bloqueia por padrão:** sem evidência mínima, o rascunho não sai.
7. **Humano assina:** a fiscal ou o agrônomo revisa e assina; o laudo sai em HTML/JSON com hash e os metadados
   do item 4.

A arquitetura e os contratos estão em [`../laudo-vivo/docs/arquitetura.md`](../laudo-vivo/docs/arquitetura.md).
**O LLM não calcula número nem define status:** as ferramentas calculam, a política decide, o verificador
atribui o status e o humano assina.

### 3.4 O que o produto não faz (de propósito)

- Não assina laudo, não tem ART e não substitui o profissional.
- Não acusa ninguém; sinaliza divergência e prioridade de verificação, e o indício de ilícito é comunicado pela
  IF (MCR 2-7, item 21).
- Não trabalha para o produtor contra a IF na mesma operação (item 15 do MCR 2-7).
- Não lê brinco a distância nem conta gado por satélite.

---

## 4. Mercado (TAM, SAM, SOM)

### 4.1 Unidades: quantos itens físicos existem para provar

Cálculo próprio sobre o Sicor 2025 (`dados_mercado/README.md`) [D]:

| Recorte | Itens/ano | Valor financiado |
|---|---|---|
| Todas as operações | 1.830.128 operações (2.456.396 itens) | R$ 361,2 bi |
| Itens físicos (gado, benfeitorias, máquinas), todas as faixas | 1.556.243 | R$ 123,1 bi |
| ... dos quais abaixo de R$ 20 mil (microcrédito, sobretudo BNB/Pronaf B) | 1.030.903 | R$ 7,3 bi |
| **Itens físicos ≥ R$ 20 mil** | **525.340** | **R$ 115,8 bi** |
| ... no Banco do Brasil | 221.197 (42%) | — |
| ... nos sistemas cooperativos (Sicoob, Sicredi, Cresol) | 159.630 (30%) | — |
| ... em Goiás | 34.890 (BB 77%; cooperativas 10,7%) | — |

**Atenção:** 55% das linhas do Sicor 2025 são do BNB, quase todas microcrédito. Por isso "1,8 milhão de
operações" **não** é o nosso mercado; a base útil é a de 525 mil itens físicos acima de R$ 20 mil.

### 4.2 Hipóteses que movem a conta

| Hipótese | Valor usado | Tipo | Como validar |
|---|---|---|---|
| Fração dos itens físicos que a IF fiscaliza por ano (amostragem do item 12 + 100% dos grandes) | 20% / **50%** / 100% | [H] | entrevista com cooperativas: "qual a sua taxa de amostragem em investimento pecuário?" (*a medir*) |
| 1 item ≈ 1 fiscalização | 1,0 | [E] nas cooperativas, linhas = operações (Sicredi: 237.387 = 237.387) [D] | — |
| Preço do software por fiscalização concluída | R$ 79 (preço-alvo) | [E] seção 5 | pergunta de preço na entrevista |
| Preço da fiscalização remota-first entregue como serviço | R$ 290 | [E] seção 5 | piloto |
| Exceções socioambientais por ano (coordenada, CAR, embargo, PRODES) | 60–100 mil | [E] | lista MMA + entrevistas |
| Preço por exceção resolvida | R$ 300–800 | [E] | entrevista |

### 4.3 A conta

**TAM (Brasil).**

| Camada | Conta | 20% fiscalizados | **50%** | 100% |
|---|---|---|---|---|
| Fiscalização assistida (software) | 525.340 × taxa × R$ 79 (preço-alvo) | R$ 8,3 mi | **R$ 20,8 mi** | R$ 41,5 mi |
| Fiscalização como serviço (remota-first, fase 2) | 525.340 × taxa × R$ 290 | R$ 30,5 mi | **R$ 76,2 mi** | R$ 152,3 mi |
| Exceções socioambientais (MCR 2-9) | 60–100 mil × R$ 300–800 | — | **R$ 18–80 mi** (ponto médio ~R$ 48 mi) | — |

- **TAM central [E]: ~R$ 125 mi/ano** = serviço a 50% (R$ 76 mi) + exceções no ponto médio (R$ 48 mi). Na versão
  só-software, ~R$ 69 mi.
- Fora da conta (potencial, não prometido): microcrédito com autofiscalização em escala (1,03 milhão de itens
  abaixo de R$ 20 mil); triagem de carteira por operação; perdas (Proagro e seguro); "Lastro" (garantias de CPR,
  barter e penhor de gado), que não tem dado público de volume (*a medir*: volume de garantias de gado/CPR
  monitoráveis).

**SAM (cooperativas de crédito no Brasil, onde a venda começa).**

| Camada | Conta | Valor/ano [E] |
|---|---|---|
| Fiscalização (serviço, taxa 50%) | 159.630 × 50% × R$ 290 | R$ 23,1 mi |
| Fiscalização (só software, taxa 50%) | 159.630 × 50% × R$ 79 (preço-alvo) | R$ 6,3 mi |
| Exceções socioambientais da carteira cooperativa | ~18% das exceções (participação de Sicoob + Sicredi no valor de 2025 [D]) × R$ 48 mi | ~R$ 8,6 mi |
| **SAM central** | serviço + exceções | **~R$ 32 mi** (só software + exceções: ~R$ 15 mi) |

**SOM (36 meses).**

| Fonte de receita | Conta | ARR [E] |
|---|---|---|
| 25 cooperativas do perfil ideal (≥ 300 itens físicos/ano; média de 966 itens [D]) | 25 × 966 × 50% × mix de R$ 150 (metade software, metade serviço) | R$ 1,8 mi |
| Triagem de carteira nessas 25 | 25 × ~2.740 operações [D: as 109 singulares do perfil somam 299.119 operações] × R$ 8 | R$ 0,5 mi |
| 15 credenciadas × 6 fiscais | 90 licenças × R$ 590 × 12 | R$ 0,6 mi |
| Exceções socioambientais | 25 cooperativas × exceções/ano por cooperativa (*a medir*) × R$ 490 | não somado |
| **SOM** | | **~R$ 2,9 mi de ARR** (faixa R$ 2–4 mi) |

**Onde está a tese.** Só com fiscalização em software, o mercado é de R$ 20–40 mi/ano. A tese de crescimento
vem de (1) capturar o valor do serviço (entregar a fiscalização remota-first, não só a ferramenta), (2) somar as
exceções socioambientais da mesma IF e (3) levar o mesmo verificador ao credor privado ("Lastro").

### 4.4 Goiás é mercado de piloto, não de negócio

Em 2025 houve 34.890 itens físicos acima de R$ 20 mil em Goiás, 77% no BB e 3.743 nas cooperativas [D]. A 50% de
taxa e com o preço-alvo de R$ 79, as cooperativas de Goiás valem ~R$ 150 mil/ano em software. Goiás serve para
validar, filmar, rotular e conseguir as primeiras LOIs; o negócio é nacional desde o início.

---

## 5. Modelo de receita e preço

### 5.1 Tabela de preços a testar

| Produto | Unidade | Preço-alvo (a testar) | Preço de piloto | Quem paga |
|---|---|---|---|---|
| **Fiscalização assistida** (triagem, plano de método, coleta guiada ou autofiscalização assistida, contagem, conciliação NF-e/GTA, laudo selado com metadados) | fiscalização concluída | **R$ 79** (preço-alvo; R$ 59 acima de 500/ano) | R$ 39 | cooperativa |
| **Licença de credenciada** | fiscal/mês, com 15 fiscalizações incluídas; excedente R$ 35 | **R$ 590** | R$ 290 nos 3 primeiros meses | credenciada |
| **Triagem de carteira pecuária** (prioridade de verificação para a amostra do item 12) | operação ativa/ano | R$ 8 | incluída no piloto | cooperativa |
| **Exceção socioambiental resolvida** (MCR 2-9) | exceção | **R$ 490**, com garantia de aceitação (refazemos sem custo se o compliance devolver por falha do dossiê) | R$ 290 | cooperativa |
| **Fiscalização remota-first como serviço** (fase 2: autofiscalização + revisão e assinatura por agrônomo da rede contratada pela IF; visita presencial só na exceção) | fiscalização entregue | **R$ 290**; visita presencial de exceção cobrada à parte | — | cooperativa |
| **Piloto Fundador** | 90 dias, até 150 fiscalizações, triagem da carteira, treinamento | **R$ 5.900** | — | cooperativa |

### 5.2 Âncoras que justificam cada preço

| Preço | Âncora | Leitura [E] |
|---|---|---|
| R$ 79 por fiscalização (preço-alvo) | piso de R$ 669 por visita presencial (AEA-MS, 4 CA) [F]; hora técnica de R$ 502 (AEA-MS) ou R$ 180 (referência de 2019 citada pelo Confea) [F]; compra de gado por investimento em GO com média de ~R$ 197 mil por operação (R$ 1,23 bi / 6.235, jan–set/2026, `../laudo-vivo/bench/fiscal_go/resumo.json`) [D] | menos de 12% do piso de uma visita, menos de uma hora técnica e cerca de 0,04% do crédito fiscalizado |
| R$ 590 por fiscal/mês | assistente de IA de crédito agro da Tarken a ~R$ 200–800 por usuário/mês ([AgFeed](https://agfeed.com.br/agtech/com-novo-estrategista-no-time-tarken-tenta-ganhar-mais-espaco-no-credito-do-agro)) [F] | paga-se se o fiscal fizer mais fiscalizações por mês com o agente (*a medir*); a referência é o preço que a credenciada recebe por fiscalização (*a medir*) |
| R$ 490 por exceção | faixa de R$ 300–800 por exceção tratada para a IF [E]; laudo agronômico com ART de R$ 1.000–3.500 ([Freela sem Crise](https://www.freelasemcrise.com.br/quanto-cobrar/assistencia-tecnica-agronomia)) [F] | ~1/3 do laudo particular |
| R$ 290 por fiscalização entregue | piso de R$ 669 por visita presencial [F] | menos da metade do piso, porque a visita vira exceção |
| R$ 5.900 pelo piloto | faixa de R$ 5–15 mil por 3 meses para o primeiro pagamento de uma cooperativa [E] | abaixo de qualquer alçada de compra relevante de cooperativa (*a medir*: alçada de compra sem licitação interna) |

### 5.3 Regras comerciais

- **Um lado por operação:** só vendemos para quem fiscaliza (a IF ou a credenciada que ela contratou). Nunca para
  o mutuário da mesma operação (MCR 2-7, item 15).
- **Garantia de aceitação** nas exceções e no piloto: se a auditoria ou o compliance devolver um laudo por falta
  de evidência que o agente deveria ter exigido, refazemos sem custo.
- Preço publicado e por unidade, num mercado em que as soluções de fiscalização para IF costumam ser vendidas sob
  consulta.

---

## 6. Unit economics

### 6.1 Custo de tecnologia por fiscalização

Medido no trace da demo (19 passos; resultados em
[`../laudo-vivo/eval/SLIDE.md`](../laudo-vivo/eval/SLIDE.md)):
<!--n:custo.tokens_entrada.valor-->135.349<!--/n--> tokens de entrada e <!--n:custo.tokens_saida.valor-->1.038<!--/n-->
de saída por fiscalização; energia local <!--n:custo.local_rs.valor-->R$ 0,0035<!--/n-->; os mesmos tokens em
nuvem, <!--n:custo.nuvem_min_rs.valor-->R$ 0,04<!--/n--> a <!--n:custo.nuvem_max_rs.valor-->R$ 0,28<!--/n-->. A
demo é uma fiscalização curta. Para uma fiscalização real, as premissas de consumo [E] são: ~30 turnos de
condução; ~940 mil tokens de entrada acumulados, dos quais ~85% em cache; ~30 mil tokens de saída (incluindo
raciocínio); ~15 min de áudio; 1 vídeo de curral de 40–60 s e ~20 fotos.

| Item | Local (GPU própria, padrão do produto) | Nuvem |
|---|---|---|
| LLM | energia ~R$ 0,05 + amortização da máquina R$ 0,20 a R$ 1,40 (R$ 15–20 mil em 36 meses; 400 a 2.000 fiscalizações/mês) [E] | LLM comercial via API, porte pequeno: ~US$ 0,04 ≈ **R$ 0,20**; porte médio: ~US$ 0,66 ≈ **R$ 3,60**; porte grande: ~US$ 1,32 ≈ R$ 7,30 [E, preços públicos de tabela de um provedor comercial de LLM, consultados em out/2026: pequeno US$ 0,10 / 0,50 por 1M, cache US$ 0,01; médio US$ 2 / 10, cache US$ 0,10; grande US$ 4 / 20, cache US$ 0,20] |
| Transcrição de voz | R$ 0 (faster-whisper local) | Amazon Transcribe US$ 0,006/min × 15 min ≈ R$ 0,50 ([AWS](https://aws.amazon.com/transcribe/pricing/)) |
| Visão (contagem e fotos) | centavos (CPU) [E] | R$ 0,10–0,50 [E] |
| Satélite, Sicor, IBGE | R$ 0 (dados públicos; Sentinel-2 aberto no AWS Open Data) [F] | R$ 0 |
| Armazenamento da evidência pelo prazo de guarda (~150 MB por 5 anos) | R$ 0,25–1,50 [E, conferir na calculadora AWS da região sa-east-1] | idem |
| **Total de tecnologia** | **~R$ 0,50–3** | **~R$ 1–6** |

A inferência é **menos de 5% do preço** em qualquer cenário. O custo que decide a margem é humano.

### 6.2 Margem por produto

| Produto | Preço | Custo variável [E] | Margem bruta [E] |
|---|---|---|---|
| Fiscalização assistida (a fiscal da IF ou da credenciada assina) | R$ 79 (preço-alvo) | tecnologia R$ 1–6 + QA amostral nosso (10% dos casos × 10 min × R$ 125/h ≈ R$ 2) + suporte R$ 3–6 = **R$ 6–14** | **82–92%** |
| Licença de credenciada (15 fiscalizações) | R$ 590/mês | 15 × R$ 1–6 + suporte R$ 40 = R$ 55–130 | **78–91%** |
| Exceção socioambiental | R$ 490 | inferência R$ 3–7 + processamento R$ 1 + revisão amostral R$ 5 + suporte = **R$ 15–30** | **94–97%** |
| Fiscalização como serviço | R$ 290 | revisão e assinatura por agrônomo da rede (20 min × R$ 125/h ≈ R$ 42) + coordenação R$ 10 + tecnologia R$ 5 + visita presencial em 15% dos casos × R$ 450 [H] ≈ R$ 68 + ART por contrato com a IF, rateada ([ART 2026](https://www.confea.org.br/node/231967)), ~R$ 2 = **~R$ 127** | **~56%** |
| **Mix do ano 2** (60% software e licença, 25% serviço, 15% exceções) | | | **~80%** [E] |

Depois da margem bruta entram impostos sobre faturamento (Simples Nacional) e taxa de meio de pagamento. A margem
de contribuição é recalculada com o regime tributário escolhido (*a medir*: alíquota efetiva).

### 6.3 Quanto o cliente economiza (a conta que a cooperativa faz)

Por fiscalização, com hipóteses explícitas [H]:
- Se o agente permite trocar a visita presencial por autofiscalização assistida numa fração dos casos
  (*a medir* no piloto), cada visita evitada poupa o custo médio de uma visita presencial (*a medir*).
- Exemplo ilustrativo, **não é medição**: 40% de visitas evitadas × R$ 400 por visita = R$ 160 poupados por
  fiscalização, contra o preço-alvo de R$ 79 (retorno de ~2x).
- Benefícios que não entram na conta: menos devolução pela auditoria, menos amostra substituída pelo BCB, prazo
  de 60 dias para máquinas cumprido, trilha pronta para o TCU.

### 6.4 CAC, payback e valor do cliente

| Canal | CAC [E] | ARR por cliente [E] | Payback [E] |
|---|---|---|---|
| Cooperativa do perfil ideal (≥ 300 itens físicos/ano) | R$ 15–30 mil (venda consultiva, 3–6 reuniões, piloto subsidiado) | ~R$ 38 mil em software (966 itens × 50% × R$ 79 de preço-alvo) + triagem de ~2.700 operações × R$ 8 ≈ **R$ 60 mil** | 4–7 meses com margem de 85% |
| Cooperativa mediana (156 itens físicos/ano [D]) | R$ 10–20 mil | ~R$ 6 mil + R$ 2,4 mil ≈ R$ 8 mil | longo demais: **não é público-alvo inicial** |
| Credenciada com 6 fiscais | R$ 2–5 mil (indicação, CREA-GO, eventos) | 6 × R$ 590 × 12 ≈ R$ 42 mil | 1–2 meses |

O dado decisivo de foco: **109 singulares concentram 82% dos itens físicos acima de R$ 20 mil das cooperativas
singulares** [D]. O perfil ideal de cliente é esse grupo, não as 742 cooperativas do país.

---

## 7. Go-to-market

### 7.1 Sequência

Meses contados a partir da captação do pré-seed (os mesmos M6, M12 e M18 da seção 10.2).

| Fase | Quando | Quem | Como entra |
|---|---|---|---|
| 1. Cooperativas de Goiás | M0 a M6 | as 16 singulares com mais de 100 itens em GO em 2025 [D], começando por Sicoob Credi-Rural (Rio Verde), Cresol Goiás (Orizona), Sicredi Planalto Central (Cristalina), Sicredi Cerrado GO, Sicoob Centro-Sul, Sicoob Agrorural, Sicoob Cerrado, Sicoob Secovicred, Sicoob do Vale e Sicoob Unicentro BR (lista em `dados_mercado/README.md`) | teste retroativo com 20 a 50 operações já fiscalizadas, depois Piloto Fundador pago |
| 2. Credenciadas como canal | em paralelo, desde M0 | empresas que fiscalizam para cooperativas, Caixa e BB em Goiás | licença por fiscal; dá acesso indireto ao volume do BB (77% dos itens físicos de GO) sem vender ao BB |
| 3. Cooperativas do perfil ideal no Brasil | a partir de M6 | as 109 singulares com ≥ 300 itens físicos/ano [D] (Centro-Oeste, MT, MS, PR, MG, RO) | indicação entre cooperativas, eventos do sistema, casos de Goiás |
| 4. Centrais e bancos de sistema | M9 a M18 | centrais Sicoob, Sicredi e Cresol | API e laudo em marca branca; homologação na central |
| 5. Bancos | depois de M18 | bancos médios, Bradesco, depois BB e Caixa | depois de casos e certificações de segurança; via credenciadas antes disso |

### 7.2 Por que cooperativa primeiro

- Decide localmente, com ciclo de 1 a 3 meses para piloto, contra 6 a 12 meses de banco [E].
- Os sistemas cooperativos têm 30% dos itens físicos acima de R$ 20 mil do país [D] e 742 singulares,
  R$ 1,036 tri de ativos e 21,2 milhões de cooperados
  ([BCB, Panorama do SNCC 2025](https://www.bcb.gov.br/content/estabilidadefinanceira/coopcredpanorama/panorama_cooperativas_sncc_anobase_dez_2025_FINAL.pdf);
  [Agência Brasil, 02/07/2026](https://agenciabrasil.ebc.com.br/economia/noticia/2026-07/cooperativas-de-credito-superam-r-1-trilhao-em-ativos))
  [F].
- O banco grande (BB) já tem processo próprio e concentra 86,5% das compras de gado por investimento de GO em
  2026 [D] (6.235 operações; `../laudo-vivo/docs/entregaveis/mercado.md`, seção 2): é alvo de canal
  (credenciadas), não de venda direta no primeiro ano.

### 7.3 Ferramentas de venda

- Um laudo de exemplo clicável
  ([`../laudo-vivo/docs/exemplos/laudo_selado.html`](../laudo-vivo/docs/exemplos/laudo_selado.html)).
- Os resultados da avaliação com intervalos de confiança
  ([`../laudo-vivo/eval/SLIDE.md`](../laudo-vivo/eval/SLIDE.md)).
- A política de dados (LGPD) ([`../laudo-vivo/docs/privacidade.md`](../laudo-vivo/docs/privacidade.md)).
- Para a validação comercial: roteiro de entrevista de 30 minutos, modelo de LOI e a oferta do Piloto Fundador.

---

## 8. Concorrência e diferencial

| Quem | O que faz (com fonte) | O que não faz [E] | Como convivemos |
|---|---|---|---|
| **Audsat** | fiscalização remota para a Res. 5.267; "estimativa e contagem precisa do número de cabeças de gado" e validação de "galpões, currais, confinamentos e bebedouros" com imagem de altíssima resolução; relatório de pré-formalização em PDF ([Audsat, 09/02/2026](https://www.audsat.com.br/blog/resolucao-cmn-5267-2025/)); mais de 30 mi ha e 850 mil operações monitoradas/ano ([Audsat](https://audsat.com.br/)) [F] | não prova que o animal visto é o financiado; não confere NF-e, GTA, categoria, nem conduz coleta de campo; imagem de altíssima resolução custa por operação | consumir o alerta remoto deles e fechar a prova no chão |
| **Softfocus Zoom** | validação automática de NF na Receita, validações socioambientais, sensoriamento remoto, comprovação financeira; clientes Banrisul, Caixa, Cresol, Sicredi, Sicoob e outros ([Softfocus Zoom](https://softfocus.com.br/zoom/)) [F] | a página não mostra app de campo, contagem de animais, conciliação com GTA nem laudo item a item | integrar como etapa de campo; é também o comprador estratégico mais provável |
| **Agrotools** | inteligência territorial para Itaú, Bradesco, Sicoob, Cresol e Rabobank ([Folha Agrícola, 01/06/2026](https://folhaagricola.com.br/2026/06/01/novas-regras-do-credito-rural-aumentam-exigencias-por-solucoes-com-inteligencia-territorial-nos-bancos/)) [F] | lavoura e território, não animal nem benfeitoria no chão | — |
| **Serasa Experian** | "Mapa da Soja" (25/08/2026) cruza Sicor, Proagro, Sentinel-2 e ZARC em escala e sugere que bancos priorizem checagens ([Serasa](https://www.serasaexperian.com.br/sala-de-imprensa/agronegocios/mapa-da-soja-cerca-de-83-por-cento-das-operacoes-analisadas-indicam-o-uso-adequado-do-credito-rural-para-o-cultivo-financiado-mostra-estudo-da-serasa-experian/)) [F] | lavoura de soja; não vai a campo nem produz o laudo | comprador estratégico (comprou Agrosatélite e idwall) |
| Vega, Inplan/SensorSat | monitoramento remoto; desafio Sicredi ([AgTech Garage](https://www.agtechgarage.news/sicredi-seleciona-startup-para-desenvolver-solucao-de-monitoramento-e-fiscalizacao-do-credito-rural/)) [F] | idem | — |
| AgRisk (AgenticRisk) | agente de IA conversacional para analista de crédito agro, lançado em 25/09/2026 ([Let's Money](https://www.letsmoney.com.br/credito/agrisk-agente-ia-analise-credito-agro/)) [F] | análise de crédito, não fiscalização de aplicação | — |
| Picsel, Vistoria BB, apps de Proagro | captura de foto com GPS e IA para perito ([Picsel](https://picsel.com.br/gestao-de-sinistros/)) [F] | sinistro, não fiscalização de investimento | — |
| Credenciada com prancheta | o processo atual | — | **é o cliente-canal, não o concorrente** |

**Diferencial em uma frase:** os outros apontam o que o satélite vê; nós fechamos a prova do que ele não vê, item a
item, conciliando o físico (vídeo, foto georreferenciada) com o documento (NF-e, GTA, projeto) e com a regra
(MCR 2-7), com abstenção quando a evidência não basta e recusa quando alguém pressiona.

Diferença em relação ao "Já Estava" (vencedor do AI Glasses Brasil,
[TI Inside](https://tiinside.com.br/25/09/2026/projeto-goiano-para-vistorias-de-imoveis-vence-ai-glasses-brasil/)):
a referência deles é o laudo anterior; a nossa é externa e pública (Sicor, NF-e, GTA, MCR), a saída é numérica com
intervalo e abstenção, e o domínio é regulado e auditado (BCB, TCU).

---

## 9. Defensibilidade

| Camada | O que é | Por que é difícil de copiar |
|---|---|---|
| **Dado de desfecho** | cada fiscalização gera o par evidência → status → decisão da IF (aceito, devolvido, desclassificado, substituído pelo BCB) | só existe com uso; incumbente de satélite não tem a evidência de campo |
| **Fiscal-GO 2026** | operações de crédito rural de Goiás com polígono, lotação implícita, sobreposição, rebanho municipal e NDVI de pasto, publicado como "prioridade de verificação" | reprodutível, mas o rótulo de desfecho vem do piloto |
| **Golden set de fiscalizações** | <!--n:golden.n_total.valor-->60<!--/n--> casos com divergências plantadas e rotuladas (split de teste congelado); benchmark de leitura de papel por foto com <!--n:ab2.leitura_campos.valor-->5.025<!--/n--> campos | benchmark é ativo próprio; a próxima versão soma defeitos escritos por fiscais de fora da equipe |
| **MCR 2-7 e 2-9 como código** | rulebooks versionados, cada regra cita o item, com o golden set que os testa | aberto de propósito: vira padrão e traz desenvolvedores; o valor está no conteúdo (norma como código e golden), no dado e na operação. O servidor MCP mínimo é a porta de acesso, não a defesa |
| **Vídeos de curral anotados** | contagem de referência em Nelore, em Goiás (*a medir*: nº de vídeos e animais anotados) | coleta física, com consentimento |
| **Rede de credenciadas** | canal que já está dentro das IFs | relacionamento local |
| **Neutralidade** | contratado pela IF, nunca pelo mutuário (item 15) | posicionamento que fornecedor de produtor não pode ocupar |

O que o incumbente faria [E]: a Softfocus pode pôr um app de campo no Zoom em 1 a 2 trimestres; a Audsat pode
somar conciliação documental. A resposta é velocidade de acumulação de dado de desfecho, foco nas cooperativas do
perfil ideal e ser comprável (Serasa comprou Agrosatélite e idwall; a Aliare comprou a Agrometrika).

---

## 10. Roadmap

### 10.1 O que o protótipo já mostra

Números da avaliação final. A página completa, com dev e teste lado a lado, está em
[`../laudo-vivo/eval/SLIDE.md`](../laudo-vivo/eval/SLIDE.md).

| Entrega | Número |
|---|---|
| Um fluxo ponta a ponta: compra de bovinos + cerca/curral | demo de 19 passos em replay, da coleta ao laudo selado ([`../laudo-vivo/`](../laudo-vivo/README.md)) |
| Recusa de pressão ("pode marcar 29") e bloqueio de emissão sem evidência mínima | na demo e no trace |
| Golden set (<!--n:golden.n_total.valor-->60<!--/n--> casos sintéticos, split de teste congelado, IC95) | teste: recall <!--n:recall_teste.fmt-->1,00 [0,70–1,00] (9/9)<!--/n-->, over-blocking <!--n:overblocking_teste.fmt-->0% [0–28%] (0/10)<!--/n-->, abstenção correta <!--n:abstencao_teste.fmt-->1,00 [0,57–1,00] (5/5)<!--/n-->; dev: recall 1,00 [0,80–1,00] (15/15), over-blocking 0% [0–22%] (0/14), abstenção correta 1,00 [0,65–1,00] (7/7) |
| Red-team: ataque bem-sucedido e over-blocking em pedido legítimo | conjuntos da equipe: ataque <!--n:redteam.ataques.fmt-->0% [0–5%] (0/80)<!--/n-->, over-blocking <!--n:redteam.overblocking.fmt-->0% [0–12%] (0/27)<!--/n-->; conjunto cego: ataque <!--n:redteam.cego_ataques.fmt-->20% [10–37%] (6/30)<!--/n-->, over-blocking <!--n:redteam.cego_overblocking.fmt-->0% [0–28%] (0/10)<!--/n--> |
| A/B agente × checklist fixo (fiscal simulado) | entrada estruturada (v1): <!--n:ab1.agente.kn-->42/42<!--/n--> × <!--n:ab1.checklist.kn-->42/42<!--/n-->. Papel fotografado e fala livre, sintéticos (v2), conciliação igual à referência, agente com pedido residual × formulário: teste <!--n:ab2_teste.residual.kn-->17/24<!--/n--> × <!--n:ab2_teste.formulario.kn-->14/24<!--/n--> (<!--n:ab2_teste.mcnemar.curto-->p = 0,51<!--/n-->), sem a menção a item não financiado <!--n:ab2_teste.residual_sem_registro.kn-->19/24<!--/n--> × <!--n:ab2_teste.formulario_sem_registro.kn-->21/24<!--/n--> (<!--n:ab2_teste.mcnemar_sem_registro.curto-->p = 0,69<!--/n-->); no dev, <!--n:ab2.residual.valor-->97%<!--/n--> × <!--n:ab2.formulario.valor-->42%<!--/n--> e, sem a menção, <!--n:ab2.residual_sem_registro.valor-->97%<!--/n--> × <!--n:ab2.formulario_sem_registro.valor-->78%<!--/n-->; toques de digitação no teste, <!--n:ab2_teste.toques_residual.valor-->12<!--/n--> × <!--n:ab2_teste.toques_formulario.valor-->304<!--/n--> |
| Contagem de bovinos em vídeo | MAE 1,6 animal (12,4%) em 5 vídeos semissintéticos de corredor (conjunto pequeno, sem split dev/teste) |
| Custo e latência | <!--n:custo.tokens_entrada_mil.valor-->135 mil<!--/n--> tokens de entrada na demo; <!--n:custo.local_rs.valor-->R$ 0,0035<!--/n--> de energia local; latência por turno no teste: p50 <!--n:agente.latencia_p50.valor-->2,0 s<!--/n-->, p95 <!--n:agente.latencia_p95.valor-->2,8 s<!--/n--> |
| Fiscal-GO 2026 (triagem) | 28.637 operações de GO (jan–set/2026), 7.499 com polígono (`../laudo-vivo/bench/fiscal_go/resumo.json`) |

### 10.2 Próxima fase e dezoito meses

| Entrega | Por que importa |
|---|---|
| Exceções socioambientais (coordenada, embargo, PRODES; MCR 2-9) como segundo fluxo completo | evolução sem troca de tema; segunda fonte de receita na mesma IF |
| Validação: ≥ 8 entrevistas registradas por papel, 2 LOIs e agrônomo com ART como parceiro | dor, preço e quem assina, com registro |
| Teste retroativo com uma cooperativa (20 a 50 operações já fiscalizadas) | tração com dado real, sem sigilo violado (análise no ambiente dela, se preciso) |
| 2 ou mais LOIs com preço; 1 Piloto Fundador pago ou pré-pago | "dor que já é paga" |
| Métricas antes e depois no mesmo golden set ampliado | evolução medida, não declarada |
| Expansão "Lastro" | mostra o caminho do centro de custo regulatório para a perda evitada |
| Unit economics medido no trace | substitui as estimativas da seção 6 |

Marcos dos 18 meses do pré-seed (meses contados a partir da captação):

| Quando | Marco |
|---|---|
| M6 | 3 cooperativas pagando e 3 credenciadas com licença; 1.500 fiscalizações seladas; aceitação na 1ª revisão ≥ 90%; módulo de exceções em uso desde a primeira onda do PRODES no crédito (04/01/2027) |
| M12 | 10 cooperativas e 8 credenciadas; 8.000 fiscalizações acumuladas; MRR de R$ 80–120 mil; serviço remota-first em 1 cooperativa; onda de 01/07/2027 do PRODES (4–15 MF) atendida |
| M18 | ARR de R$ 1,5–2 mi; 1 central ou banco médio em piloto; 1 piloto do "Lastro" com credor privado; pronto para seed |

---

## 11. Métrica norte e métricas de guarda

**Métrica norte:** **R$ de crédito rural com aplicação provada por mês**, ou seja, a soma do valor das operações
cujo laudo foi selado e aceito pela IF sem retrabalho.

| Métrica de guarda | Meta | Por quê |
|---|---|---|
| Aceitação na 1ª revisão (compliance/auditoria) | ≥ 90% | o produto é a prova que passa |
| Falso "verificado" no conjunto canário | 0 (alarme acima de 3%) | o erro mais caro |
| Abstenção | 10–25% | se abstém quando deve, sem travar tudo |
| Over-blocking (válido marcado como divergente) | ≤ 10% | não atrapalhar o produtor honesto |
| Visitas presenciais evitadas | meta definida no piloto | é a economia do cliente |
| Tempo da operação até o laudo selado | *a medir*: tempo atual × tempo com agente | prazo de 60 dias para máquinas |
| Custo por fiscalização (tecnologia + revisão) | ≤ 15% do preço | margem |

---

## 12. Riscos e mitigação

| Risco | Probab. [E] | Mitigação | Critério de morte ou de alerta |
|---|---|---|---|
| "O satélite já resolve o gado" (Audsat) | média | posicionar como conciliação física e documental que complementa o remoto e consome o alerta dele | se 3 de 5 fiscais ouvidos na validação disserem que o satélite resolve |
| Disposição a pagar baixa (fiscalização é centro de custo) | média-alta | vender à credenciada como produtividade; à cooperativa como visita evitada e auditoria tranquila | custo atual por visita abaixo de R$ 150, ou preço aceito abaixo de R$ 30 |
| Concentração no BB em Goiás (77% dos itens físicos) | alta | cooperativas + credenciadas como canal; tese nacional | nenhuma cooperativa ou credenciada de GO aceita conversar sobre piloto |
| Compliance não aceita evidência capturada pelo produtor | média | começar pela ferramenta da fiscal; autofiscalização na fase 2, com prova de vida da cena | compliance vetar até o modo "fiscal" |
| Contagem ruim no curral (oclusão, Nelore homogêneo) | média | filmar no corredor ou na porteira; abstenção acima do limiar | erro médio acima de 5% no conjunto próprio de vídeos de curral |
| GTA falsa (o "Boi de Papel" usou GTAs falsas) | alta | conferir coerência (datas, quantidades, origem e destino contra NF-e e projeto); autenticidade só com integração à Agrodefesa | — |
| LGPD (vídeo do produtor e de funcionários; NF-e e GTA com CPF) | média | inferência local por padrão; minimização e mascaramento; TCLE; contrato de operador com a IF; retenção pelo prazo do item 23 do MCR 2-7 | incidente com dado pessoal |
| Viés contra o pequeno produtor | média | "prioridade de verificação", nunca rótulo sobre a pessoa; over-blocking medido, com recorte por porte no piloto; direito de resposta antes de qualquer divergência virar decisão | over-blocking maior em operações pequenas |
| Cópia por incumbente (Softfocus, Audsat) | média | dado de desfecho e rede de credenciadas (construídos com os pilotos), preço publicado, ser comprável | — |
| Mudança regulatória | baixa no MCR 2-7; média no 2-9 (o CMN já adiou duas vezes; ADPF da CNA no STF, sem liminar em out/2026) | começar pelo 2-7, que não está em disputa | — |
| Responsabilidade técnica pelo laudo errado | média | quem assina é humano com registro profissional; trilha de evidência; seguro de responsabilidade civil profissional no uso dos recursos | — |
| Equipe sem domínio de crédito rural | alta | agrônomo com ART como parceiro; conselheiro ex-gerente de cooperativa | sem agrônomo parceiro, não há quem assine a rotulagem e responda pela leitura da norma |

---

## 13. Equipe necessária

| Papel | Por que |
|---|---|
| Líder de negócio e vendas (cooperativas) | o ciclo de venda é consultivo e local |
| Líder técnico (agente, avaliação, LLMOps) | agente, avaliação com IC e operação do modelo |
| Engenharia de dados, geo e visão (Sicor, Sentinel-2, contagem em vídeo) | ativo próprio e checagens |
| **Agrônomo com ART** (parceiro ou conselheiro; ideal, sócio) | assina a rotulagem do golden set, valida o rulebook, responde "quem assina?" e, na fase 2, coordena a rede de revisores |
| Conselheiro de crédito rural (ex-gerente de cooperativa ou de credenciada) | porta de entrada e leitura do processo de compra |
| Jurídico (LGPD e bancário), por demanda | contrato de operador, leitura do item 15, termos de piloto |

Contratações do pré-seed: 3 engenheiros, 1 pessoa de vendas e sucesso do cliente agro, e a rede de agrônomos
revisores remunerada por fiscalização.

---

## 14. Impacto e aderência ao programa

- **Crédito melhor alocado:** prova barata da aplicação reduz o custo de fiscalizar o pequeno e médio produtor
  honesto e concentra a visita onde há divergência [E].
- **Integridade do crédito sem acusar ninguém:** o agente registra divergência e pressão, e a decisão continua
  humana.
- **Código aberto:** rulebooks MCR 2-7 e 2-9 e servidor MCP publicados com licença aberta; benchmark com *data
  card*.
- **Multimodal por necessidade:** voz porque as mãos estão ocupadas no curral; vídeo e foto porque são a prova;
  satélite porque é a referência independente.

---

## 15. Plano de captação

### 15.1 A rodada

**Pré-seed de R$ 2–3 mi, a R$ 12–18 mi pós-money** (diluição de 15–20%), para 18 meses de pista, com queima de
R$ 130–160 mil/mês [E]. Âncoras: Picsel com seed de R$ 5 mi já com receita
([AgFeed, 06/02/2026](https://agfeed.com.br/agtech/enquanto-o-seguro-rural-patina-picsel-investe-em-tecnologia-para-crescer));
Produzindo Certo com primeira rodada de R$ 20,7 mi
([The AgriBiz](https://www.theagribiz.com/agtechs/venture-capital/na-era-da-regeneracao-produzindo-certo-capta-r-20-milhoes-com-arar-sp-ventures-e-slc/));
Nagro com Série B de R$ 50 mi com Itaú Ventures
([AgFeed](https://agfeed.com.br/agtech/nagro-capta-r-50-milhoes-com-itau-e-rabobank-para-avancar-em-credito-e-gestao-de-riscos))
[F]. Não há dado agregado confiável de valuation de pré-seed no Brasil em 2025–26; a faixa é estimativa nossa.

### 15.2 Uso dos recursos

| Destino | % | O que compra |
|---|---|---|
| Produto e engenharia | 55% | 3 engenheiros por 18 meses; GPU de inferência; segurança da informação |
| Go-to-market | 20% | 1 pessoa de vendas e sucesso do cliente agro; viagens às cooperativas; eventos do sistema cooperativo |
| Operação de campo e rede técnica | 12% | pilotos subsidiados; rede de agrônomos revisores; ART; seguro de responsabilidade civil profissional |
| Dados, avaliação e conformidade | 8% | rotulagem do golden set; LGPD (RIPD, contrato de operador); auditoria de segurança |
| Jurídico e contábil | 5% | estrutura societária, contratos, regime tributário |

### 15.3 Marcos que destravam o seed

Os de M6, M12 e M18 da seção 10.2, com destaque para: aceitação na 1ª revisão ≥ 90% em produção, MRR de
R$ 80–120 mil em M12 e ARR de R$ 1,5–2 mi em M18.

### 15.4 Quem procurar

- Pré-seed e seed agro: **Arar Capital** (Picsel, Produzindo Certo) e **SP Ventures** (AgVentures III,
  US$ 50 mi) ([The AgriBiz](https://www.theagribiz.com/agtechs/venture-capital/sp-ventures-chega-a-us-50-milhoes-em-seu-novo-fundo/))
  [F].
- Estratégico: **Itaú Ventures** (Nagro) [F]; corporate de cooperativas (a verificar).
- Seed e Série A em IA vertical: Canary, Kaszek, Astella, ONEVC.
- Não dilutivo: créditos AWS do prêmio, AKCIT/EMBRAPII e editais de subvenção (a levantar).

### 15.5 Gatilhos de tração, em ordem

1. Métricas próprias com IC e Fiscal-GO 2026 publicados (seção 10.1).
2. ≥ 12 entrevistas por papel; parecer de um jurídico de cooperativa sobre o item 15 e a autofiscalização.
3. ≥ 2 LOIs de cooperativa ou credenciada com preço; teste retroativo com 20 a 50 operações já fiscalizadas.
4. Primeiro pagamento (Piloto Fundador ou pré-pagamento de licenças); unit economics medido.

---

## 16. Hipóteses a medir

Os dados marcados *a medir* ao longo do plano, e como cada um se mede:

| Dado | Como se mede |
|---|---|
| Custo médio por visita presencial e fiscalizações por mês por fiscal | entrevistas com fiscais e credenciadas (mediana, com o n) |
| Taxa de amostragem em investimento pecuário | entrevistas com cooperativas |
| Preço aceito por fiscalização e alçada de compra sem licitação interna | entrevistas e LOIs |
| Preço que a credenciada recebe por fiscalização e fiscalizações extras por mês com o agente | entrevistas com credenciadas e piloto |
| Fração de visitas presenciais evitáveis | piloto |
| Tempo da operação até o laudo selado (atual × com agente) | piloto |
| Exceções socioambientais por ano por cooperativa | piloto e lista pública do MMA |
| Volume de garantias de gado e CPR monitoráveis ("Lastro") | levantamento com credores privados |
| Vídeos de curral e animais anotados | coleta própria, com consentimento |
| Alíquota efetiva do regime tributário | contador, com o regime escolhido |
