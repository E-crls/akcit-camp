# IN BCB nº 758, de 08/07/2026: reversão de desclassificação no Sicor (trechos literais)

Base normativa da seção "reversão de desclassificação" do pacote de exibição (`reversao_in758`) e da linha 2
da matriz de evidências (`validacao/README.md`). A Instrução Normativa altera o **MCR - Documento 1**
(Requisitos e Instruções de Preenchimento do Sicor): prazos de alteração de campos (art. 1º), notas dos campos
49, 52 e 60-B (art. 2º). O que interessa ao Laudo Vivo é a nota do **Campo 60-B**: quem pode reverter a
desclassificação, e que a documentação que a justifica é registrada **por operação** e fica à disposição do
BC. Texto normativo é público; aqui ele é reproduzido literalmente para que a citação possa ser conferida
por teste (`tests/unit/test_regras_normas_in758.py`) e lida por código (`laudo.rulebooks.normas`). Só a seção
"Texto literal" é transcrição; as outras seções são nossas (fonte, resumo, leitura), e nenhum título fora dela
leva a palavra "literal" (o pacote de exibição procura a transcrição por ela). Editar a seção "Texto literal" muda o sha256 registrado: o código deixa
de citá-la como conferida até alguém reconferir contra a fonte oficial e atualizar o hash.

## Fontes e data de acesso

Acesso ao texto oficial: 16/10/2026 (API de normativos do BCB; o texto da seção "Texto literal" foi conferido
linha a linha contra a resposta da API e o sha256 dessa seção está em `laudo.rulebooks.normas.FONTES`).

| Fonte | URL | Acesso | Observação |
|---|---|---|---|
| Instrução Normativa BCB nº 758, de 08/07/2026 (DOU 10/07/2026, Seção 1, p. 196), oficial | https://www.bcb.gov.br/estabilidadefinanceira/exibenormativo?tipo=Instru%C3%A7%C3%A3o%20Normativa%20BCB&numero=758 (API usada: `https://www.bcb.gov.br/api/conteudo/app/normativos/exibenormativo?p1=Instru%C3%A7%C3%A3o%20Normativa%20BCB&p2=758`) | 16/10/2026 | Id 52969, versão 1. Não revogada, não cancelada. Assina o Chefe do Derop. Referências: Res. BCB 340/2023 (Regimento Interno, art. 23, I, "a"); MCR 3-6-4 e 12-1-1-m; "Altera MCR - Documento 1". Art. 4º: em vigor na data da publicação (10/07/2026). |

O texto vigente do MCR - Documento 1 é indicado pela própria IN em `www3.bcb.gov.br/mcr`; esse endereço hoje
redireciona para a página inicial do BCB (ver `mcr_2_7.md`). A redação consolidada do Documento 1 no SGM não
foi conferida nesta sessão: vale o texto da IN, abaixo.

Convenções desta transcrição: as linhas pontilhadas do original (parte do campo que não muda) viram "[…]";
as aspas que abrem e fecham a nova redação de cada campo e a marca "(NR)" ficam fora das alíneas (o original
fecha cada campo com "” (NR)"). Nada mais foi alterado. Localizador usado no código:
`IN BCB 758, Campo 60-B, Nota, alínea c`.

---

## Texto literal (IN BCB nº 758/2026)

### Ementa

Altera o MCR - Documento 1 do Manual de Crédito Rural (MCR) para ajustar prazos aplicáveis à alteração de registros e para orientar as instituições financeiras sobre procedimentos aplicáveis à reversão de desclassificação, no âmbito do Sistema de Operações do Crédito Rural e do Proagro (Sicor).

### Art. 2º

Art. 2º O Conteúdo e Orientação dos Campos Estáticos de 1 a 70 do MCR - Documento 1 do MCR passa a vigorar com a seguinte alteração:

### Campo 52, Nota

O Campo 52 deve ser atualizado dentro da vigência do instrumento de crédito sempre que identificada alteração no número do CAR do imóvel do empreendimento, observadas as seguintes condições:
a) as atualizações estão sujeitas aos prazos e às condições de que trata o item 18;
b) caso a instituição financeira identifique irregularidade na alteração do CAR, deve adotar as providências previstas no MCR 2-8 e, quando couber, no MCR 2-7-21;
c) a área do empreendimento deve estar inserida na área referente ao novo número de CAR;

### Campo 60-B, Nota

A reversão da desclassificação poderá ser realizada pela instituição financeira, observados os seguintes procedimentos e condições:
a) alteração dos status SOR08 (Desclassificada Totalmente) ou SOR13 (Desclassificada Parcialmente) deve ser realizada por meio de correções via web, no Painel de Gestão do SCR, ou na forma indicada pela área gestora daquele sistema, para correção do Doc 3040;
b) as desclassificações realizadas em consequência de ações de supervisão do BC não poderão ser revertidas, salvo autorização expressa do BC;
c) os procedimentos para reversão de desclassificação serão realizados no Sicor-web pelo diretor responsável pela área de crédito rural, que deve registrar, para cada operação, a documentação comprobatória das justificativas para a reversão;
d) o Sicor identificará a operação que teve a desclassificação revertida, excluindo os dados dos respectivos campos do(s) Grupo(s) Desclassificação Parcial/Total;
e) a documentação que fundamenta a reversão de desclassificação deverá ser mantida à disposição do BC pelo prazo previsto nas normas legais e regulamentares aplicáveis à produção e à gestão de documentos relativos às operações e transações realizadas por instituições financeiras.

### Art. 4º

Art. 4º Esta Instrução Normativa BCB entra em vigor na data de sua publicação.

---

## Fora do recorte (resumo nosso, não é transcrição da norma)

- **Art. 1º:** nova redação do item 18 do MCR - Documento 1, com os prazos para alterar campos do registro no
  Sicor depois da emissão do instrumento de crédito (40, 60, 90 ou 180 dias, conforme o campo e a adesão ao
  Proagro) e os campos que não podem ser alterados (Ref Bacen, CNPJ da instituição, data de emissão,
  CNPJ/CPF do beneficiário, DAP). Não muda o fluxo de fiscalização.
- **Art. 2º, Campo 49:** orientação de preenchimento do período previsto de plantio/semeadura (lavoura).
- **Art. 3º:** endereço do MCR - Documento 1. **Nota da IN:** objetivos (evitar alterações indevidas em campos
  relevantes para a conformidade e adequar o Sicor a operações objeto de fiscalização e supervisão) e
  dispensa de AIR (Decreto 10.411/2020, art. 4º, V, "b").

## Leitura para o produto (o que prova e o que não prova)

- **Prova:** quem reverte é a IF, pelo diretor responsável pela área de crédito rural, no Sicor-web
  (Campo 60-B, "c"); a documentação que justifica a reversão é registrada **para cada operação** ("c") e fica à
  disposição do BC pelo prazo legal ("e"). Desclassificação feita por supervisão do BC não se reverte sem
  autorização expressa dele ("b").
- **Não prova:** a IN não diz que documento basta para reverter, nem cita laudo de fiscalização. O pacote de
  exibição organiza a documentação da operação; ele **não garante** reversão nenhuma, e a decisão continua
  com o diretor da IF (e, no caso "b", com o BC).
- **Liga com o MCR 2-7:** a nota do Campo 52 ("b") manda a IF que identificar irregularidade na alteração do
  CAR adotar as providências do MCR 2-8 e, quando couber, do MCR 2-7-21 (comunicação de indícios de ilícitos).
