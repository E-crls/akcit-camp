# MCR 2-7: Monitoramento e Fiscalização (texto literal)

Base normativa dos rulebooks `src/laudo/rulebooks/mcr_2_7.yaml` (fluxo do regional) e, em parte,
`mcr_2_9.yaml`. Texto normativo é público; aqui ele é reproduzido literalmente para que cada `citacao` dos
rulebooks possa ser conferida por teste automático (`tests/unit/test_regras_rulebook.py`).

## Fontes e data de acesso

| Fonte | URL | Acesso | Observação |
|---|---|---|---|
| Resolução CMN nº 5.267, de 28/11/2025 (DOU 01/12/2025, Seção 1, p. 120/121), oficial | https://www.bcb.gov.br/estabilidadefinanceira/exibenormativo?tipo=Resolu%C3%A7%C3%A3o%20CMN&numero=5267 (API usada: `https://www.bcb.gov.br/api/conteudo/app/normativos/exibenormativo?p1=Resolu%C3%A7%C3%A3o%20CMN&p2=5267`) | 08/10/2026 | Art. 1º: a Seção 7 do Capítulo 2 do MCR "passa a vigorar na forma do anexo". Art. 2º: "Esta Resolução entra em vigor em 1º de março de 2026." Não revogada, não cancelada. |
| MCR vigente, Sistema de Gestão de Manuais do BCB (SGM) | https://manuais.bcb.gov.br/app/manual/mcr/publico (01 - MCR Normas › 02 - Condições Básicas › 7 - Monitoramento e Fiscalização) | 08/10/2026 | PDF da seção com cabeçalho "Resolução CMN nº 5.267, de 28 de novembro de 2025". Texto idêntico ao anexo da resolução. |
| Seções correlatas do MCR vigente (2-2, 2-5, 2-8, 3-3) | mesmo SGM | 08/10/2026 | Cabeçalhos: 2-2 "Atualização MCR nº 730, de 12/07/2024"; 2-5 e 3-3 "Atualização MCR nº 745, de 16/07/2025"; 2-8 "Resolução CMN nº 4.895, de 26/02/2021". |

Verificação de alterações posteriores: varri as Resoluções CMN nº 5.269 a 5.343 (até 24/09/2026) na API de
normativos do BCB. Nenhuma altera o MCR 2-7. A busca textual por "MCR 2-7" também devolve a 5.267 como a mais
recente. O endereço antigo `www3.bcb.gov.br/mcr` hoje redireciona para a página inicial do BCB. O MCR passou
a ser publicado no SGM (link acima).

Numeração usada nos rulebooks: `MCR 2-7-16-b-II` = Capítulo 2, Seção 7, item 16, alínea "b", inciso II.

---

## Texto literal da Seção 2-7 (Res. CMN 5.267/2025, vigente desde 01/03/2026)

TÍTULO : CRÉDITO RURAL
CAPÍTULO : Condições Básicas - 2
SEÇÃO : Monitoramento e Fiscalização - 7

1 - A instituição financeira é responsável pelo monitoramento e pela fiscalização das operações de crédito rural, cabendo-lhe definir os procedimentos aplicados, observados:
a) as exigências estabelecidas nesta Seção;
b) a efetividade do procedimento adotado em vista das características do empreendimento financiado;
c) a aplicação de critérios e métodos consistentes, verificáveis e passíveis de avaliação pelo Banco Central do Brasil; e
d) o necessário registro das verificações realizadas.

2 - O monitoramento e a fiscalização das operações de crédito rural têm por finalidade:
a) avaliar, em vista do que dispõem a regulamentação aplicável ao crédito rural e o contrato de financiamento:
I - a adequação da condução do empreendimento pelo mutuário;
II - a situação das garantias vinculadas à operação de crédito rural;
III - a compatibilidade do empreendimento ou do mutuário com o programa ou a linha de crédito objeto do financiamento;
b) identificar operações com indícios de irregularidades e prevenir possíveis desvios de finalidade na contratação e na condução dos empreendimentos financiados, conforme definido na regulamentação aplicável ao crédito rural, por meio de práticas como:
I - mapeamento da composição da carteira de crédito rural;
II - cruzamento de informações e uso de indicadores de risco, inclusive provenientes de base de dados publicamente disponíveis;
III - geração de alertas de risco de irregularidades, desde a análise de crédito;
IV - proposição de amostras dirigidas à equipe de fiscalização da instituição financeira;
c) recomendar mudanças nos processos internos da instituição financeira, inclusive nos controles na contratação e nas ações de fiscalização.

3 - Para atendimento ao disposto no item 2, é admitido o uso dos seguintes métodos de análise, de forma individual ou combinada em uma mesma operação, observada a necessidade de assegurar a sua conformidade antes da contratação até a liquidação do financiamento:
a) sensoriamento remoto, por meio da aquisição e da análise de dados de sistemas fotográficos, óptico-eletrônicos ou de radar, capazes de detectar e registrar, sob a forma de imagens, o fluxo de radiação eletromagnética refletida ou emitida por objetos distantes;
b) documental, que consiste na análise de documentação comprobatória;
c) presencial, que consiste no exame do empreendimento no local onde se desenvolve a atividade financiada ou onde se encontra o bem ou o produto financiado.

4 - Na aplicação do método de sensoriamento remoto, de que trata a alínea “a” do item 3, devem ser observadas as seguintes condições específicas:
a) as imagens utilizadas devem ter qualidade suficiente, determinada por parâmetros de resolução espacial, temporal, espectral e radiométrica, para extrair informações relativas à condução do empreendimento pelo mutuário, tais como:
I - aplicação do crédito em área plantada;
II - cultura desenvolvida; e
III - desenvolvimento vegetativo do cultivo;
b) a documentação referente ao processo de monitoramento ou fiscalização deve conter o registro das seguintes informações:
I - satélite imageador e sensor utilizado, data das imagens, resolução espacial, resolução radiométrica e bandas utilizadas;
II - metodologia utilizada para realizar o pré-processamento e o processamento da imagem;
III - explicações acerca do modo como as imagens foram utilizadas para monitorar e fiscalizar as operações;
c) a captura das imagens deve ser efetuada conforme a finalidade das operações.

5 - Ficam sujeitos à obrigatoriedade de monitoramento e fiscalização pelo método de sensoriamento remoto, de que trata alínea “a” do item 3, os empreendimentos de custeio e investimento que, cumulativamente:
a) forem financiados em operações contratadas a partir de 1º de março de 2026; e
b) tenham área total superior a trezentos hectares.

6 - Na hipótese de que trata o item 5, previamente à formalização da operação, a instituição financeira deve adotar o método de sensoriamento remoto para fazer, no mínimo, as verificações quanto aos seguintes aspectos:
a) a aptidão da área do empreendimento para a execução da atividade financiada, por meio de verificações como área agricultável, declividade do terreno, nível de degradação do solo, entre outros;
b) se há elementos que caracterizem a duplicidade de crédito ou a recuperação de capital investido, por meio da análise da área do empreendimento, observado o disposto no MCR 2-5-2;
c) se há vegetação nativa na área do empreendimento, para fins de observância ao disposto no MCR 2-9-16.

7 - Na hipótese de que trata o item 5, ao longo do curso da operação, a instituição financeira deve adotar o método de sensoriamento remoto para fazer, no mínimo, as verificações quanto aos seguintes aspectos, observado o disposto na alínea “c” do item 4, conforme as características de cada empreendimento:
a) a compatibilidade entre a atividade financiada e a exploração efetivamente realizada em toda a área do empreendimento;
b) se foram observados os períodos para plantio e colheita, conforme informados na contratação, com base nas respectivas datas indicadas pelo sensoriamento remoto;
c) a coincidência entre a área do empreendimento financiado e a área emergida, inclusive para orientar o produtor sobre eventual necessidade de alteração da área informada no Sistema de Operações do Crédito Rural e do Proagro – Sicor, observado o disposto no MCR 2-1-3;
d) se há elementos que caracterizem a duplicidade de crédito ou a recuperação de capital investido, observado o disposto no MCR 2-5-2;
e) se há indícios de condução inadequada do empreendimento ou de não aplicação dos recursos do financiamento;
f) se a exploração da área do empreendimento e da área contínua a ele se deu por meio de sobreposição com área vedada pelas disposições dos MCR 2-9-5 a 15, observadas as regras e exceções previstas nesses itens;
g) se houve manutenção da vegetação nativa na área do empreendimento e na área contínua a ele, para fins de observância ao disposto no MCR 2-9-16.

8 - Relativamente ao disposto nas alíneas “f” e “g” do item 7, considera-se área contínua ao empreendimento qualquer área adjacente à informada no Sicor que tenha sido utilizada, no curso da operação, para exploração da mesma atividade objeto do financiamento, observado que:
a) as verificações de que trata o MCR 2-9 relativas a Unidades de Conservação, a terras ocupadas por indígenas, a terras ocupadas e tituladas por remanescentes das comunidades de quilombos e a Florestas Públicas Tipo B devem considerar qualquer área contínua ao empreendimento, inclusive área contínua que extrapole a área do imóvel rural;
b) as verificações de que trata o MCR 2-9 relativas a embargos ambientais e à manutenção de vegetação nativa devem considerar apenas a área contínua pertencente à área do imóvel rural do empreendimento;
c) para definição da área do imóvel rural de que tratam as alíneas “a” e “b”, devem ser consideradas as informações registradas no Sistema Nacional de Cadastro Ambiental Rural – Sicar para o imóvel em que situado o empreendimento.

9 - As verificações de que tratam os itens 6 e 7 são aplicáveis, no que couber, aos empreendimentos de pecuária, devendo ser apurada a existência de pastagem e de instalações compatíveis com o empreendimento, conforme o caso, facultada a contagem de animais por sensoriamento remoto.

10 - As exigências de que tratam os itens 5 a 9 não dispensam a instituição financeira de adotar os demais métodos de que trata o item 3, em vista de informações inconclusivas levantadas pelo sensoriamento remoto ou de exigência normativa específica, e sempre que necessário para assegurar a efetividade do monitoramento e da fiscalização.

11 - A estrutura responsável pelas atividades indicadas no item 2 deve dispor de:
a) políticas e estratégias para o monitoramento e fiscalização das operações de crédito rural claramente documentadas;
b) metodologia para as ações de monitoramento e fiscalização;
c) gestão das fiscalizações, com reporte adequado das ações realizadas e avaliação contínua da efetividade das estratégias de mitigação de riscos utilizadas;
d) controle sistemático das contratações do crédito, mediante a implantação de rotinas e procedimentos capazes de identificar operações com indícios de irregularidades e o estabelecimento de indicadores de desvio de crédito.

12 - Nas ações de monitoramento e fiscalização que envolverem a realização de amostras, o processo de amostragem deve observar critérios estatísticos, de acordo com sistemática estabelecida pela própria instituição financeira ou baseada em normas técnicas ou recomendações de órgãos de controle federais.

13 - Em seus trabalhos de monitoramento e fiscalização, a instituição financeira pode utilizar, de forma complementar, outras fontes externas de informação disponíveis.

14 - Sem prejuízo da integral responsabilidade pelo cumprimento das disposições de que trata esta Seção e demais regulamentações do crédito rural, a instituição financeira pode contratar pessoas especializadas para a execução de seus trabalhos de monitoramento e fiscalização.

15 - É vedado o exercício de atividades de monitoramento e fiscalização:
a) por pessoa física ou jurídica contratada diretamente pelo mutuário para a prestação de assistência técnica ao empreendimento;
b) por empresa da qual o mutuário participe direta ou indiretamente.

16 - Devem ser adotados os seguintes procedimentos nas ações de monitoramento e fiscalização aos financiamentos destinados a:
a) construções, reformas ou ampliações de benfeitorias: as ações de monitoramento e fiscalização devem ocorrer pelo menos uma vez até o término do cronograma de execução previsto no projeto, para verificar a completa conclusão das obras e instalações;
b) aquisição de máquinas, equipamentos, implementos, veículos, tratores, colheitadeiras, embarcações, aeronaves e equipamentos empregados na medição de lavouras:
I - os itens devem ser identificados por numeração de fábrica, quando couber;
II - as ações de monitoramento e fiscalização devem ocorrer até sessenta dias da liberação do crédito, devendo ser apresentada pelo mutuário a nota fiscal de aquisição com a discriminação do bem financiado e do comprador, com a identificação da instituição financeira;
c) atendimento a cooperados, na modalidade de fornecimento de insumos: as ações de monitoramento e fiscalização devem ocorrer após o registro da relação de cooperados no Sicor e até sessenta dias antes do vencimento da operação.

17 - A instituição financeira deve avaliar, com base nas conclusões e recomendações dos relatórios de monitoramento e fiscalização, as providências adicionais necessárias para a adequação do empreendimento em face do crédito contratado.

18 - O mutuário poderá ser responsabilizado pelo ressarcimento de despesas realizadas no caso de fiscalização:
a) frustrada por sua culpa;
b) extraordinária, realizada em virtude de irregularidade de sua conduta.

19 - A instituição financeira deve realizar a desclassificação ou a reclassificação de operações, conforme disposições do MCR 2-8.

20 - O Banco Central do Brasil, em suas atividades de monitoramento e supervisão das instituições financeiras, pode determinar a desclassificação e/ou a reclassificação de operações de crédito rural.

21 - Na hipótese de constatação de ilícitos penais ou fraudes fiscais, deve a instituição financeira comunicar os fatos ao Ministério Público ou às autoridades tributárias, encaminhando, sempre que possível, os documentos comprobatórios das irregularidades verificadas, sem prejuízo da observância da Lei Complementar nº 105, de 10 de janeiro de 2001, quando aplicável.

22 - Na hipótese descrita no item 21, a instituição financeira deve manter arquivadas e à disposição do Banco Central do Brasil as comunicações efetuadas pelo prazo correspondente à prescrição da pretensão punitiva.

23 - As instituições financeiras devem manter a documentação gerada no processo de fiscalização e monitoramento à disposição do Banco Central do Brasil, observadas as normas legais e regulamentares relativas à guarda e à conservação de documentos referentes às operações de crédito rural.

24 - É facultado ao Banco Central do Brasil:
a) fiscalizar as operações de crédito rural realizadas pelas instituições financeiras, inclusive junto aos mutuários, devendo o instrumento de crédito conter cláusula explícita nesse sentido;
b) determinar que as instituições financeiras realizem fiscalizações em quaisquer operações de crédito rural, sem ônus para a Autarquia;
c) requisitar a designação de fiscal da instituição financeira para realizar vistorias no imóvel rural, em conjunto com prepostos da Autarquia e sem ônus para esta; e
d) determinar a substituição da amostra de fiscalização por outra que considere adequada, quando verificada a inconsistência do método empregado para amostragem.

---

## Itens correlatos de outras seções do MCR (usados pelo fluxo de fiscalização)

Texto literal do MCR vigente no SGM (acesso em 08/10/2026). Entre parênteses, a norma de origem indicada no
próprio MCR.

### MCR 2-2 (Orçamento, Plano e Projeto)

2 - O orçamento de aplicação dos recursos deve discriminar a espécie, o valor e a época de todas as despesas e inversões programadas. (Res CMN nº 4.883 art 1º)

11 - A instituição financeira pode exigir avaliação, vistoria prévia, medição de lavoura ou pastagem, exame de escrita, estudo de viabilidade, plano ou projeto sempre que julgar necessário. (Res CMN nº 4.883 art 1º)

### MCR 2-5 (Utilização)

10 - Comprova-se o uso adequado de recursos pela verificação de que o empreendimento foi correta e tempestivamente executado, devendo o produtor: (Res CMN 4.883 art 1º)
a) reter os comprovantes de aplicação na aquisição de insumos e no pagamento de mão de obra, para apresentá-los ao financiador, quando solicitados;
b) entregar ao financiador, no prazo de 30 (trinta) dias a contar da liberação, os documentos comprobatórios da aquisição de veículos, máquinas, equipamentos e animais.

12 - A aplicação irregular ou o desvio de parcelas do crédito sujeitam o mutuário à sua reposição, com as sanções pecuniárias pactuadas, contadas desde a data de sua liberação, sem prejuízo de demais sanções previstas neste Manual e na legislação aplicável. (Res CMN 4.883 art 1º)

### MCR 2-8 (Desclassificação e Reclassificação)

2 - Deve ser desclassificada, total ou parcialmente, a operação na qual for constatada irregularidade que caracterize desvio nos objetivos do crédito rural, representada por uma ou mais das seguintes ocorrências:
[...]
i) aplicação não comprovada de recursos;

3 - A desclassificação da operação consiste na adoção das seguintes medidas pela instituição financeira, em até 60 (sessenta) dias a contar da data em que ficou ciente do fato passível de ser caracterizado como irregularidade, sem prejuízo da observância das demais providências previstas na legislação em vigor:
[...]

### MCR 3-3 (Créditos de Investimento)

2 - São financiáveis os seguintes investimentos fixos: (Res CMN 4.883 art 1º; Res CMN 5.021 art 2º; Res CMN 5.149 art 5º)
a) construção, reforma ou ampliação de benfeitorias e instalações permanentes; (Res CMN 4.883 art 1º)
[...]

3 - São financiáveis os seguintes investimentos semifixos: (Res CMN 4.883 art 1º; Res CMN 5.021 art 2º; Res CMN 5.078 art 4º; Res CMN 5.149 art 5º)
a) aquisição de animais para reprodução ou cria; (Res CMN 4.883 art 1º)
[...]

10 - O beneficiário de crédito para investimento relativo à pecuária deve: (Res CMN 4.883 art 1º)
a) adotar medidas profiláticas e sanitárias em defesa dos rebanhos;
b) efetuar a marcação dos animais, com observância das normas legais.

---

## Lacunas do texto normativo para o fluxo do regional (bovinos + cerca/curral)

1. **Contagem de animais.** O MCR 2-7 não fixa critério de contagem nem tolerância. Só diz que a contagem
   por sensoriamento remoto é facultada (item 9) e que os critérios devem ser "consistentes, verificáveis"
   (item 1-c). A tolerância de 5% e a regra do intervalo de confiança são **parâmetros operacionais nossos**.
2. **Prazo de fiscalização de animais.** O item 16 fixa prazos para benfeitorias (cronograma), máquinas
   (60 dias) e insumos a cooperados. **Não há prazo específico para aquisição de animais** no 2-7. O prazo
   normativo mais próximo é o do MCR 2-5-10-b: o mutuário entrega os comprovantes de aquisição de animais em
   30 dias da liberação.
3. **GTA.** A Guia de Trânsito Animal **não aparece no MCR**. Ela vem da legislação de defesa sanitária animal:
   normas federais do MAPA sobre a GTA (o módulo de documentos fiscais cita a IN MAPA nº 09/2021 para a
   e-GTA; a IN MAPA nº 18/2006 aprovou o modelo anterior) e normas estaduais da Agrodefesa em Goiás. **Não
   conferi o texto dessas normas nesta sessão; é fonte secundária.** No rulebook, a exigência de GTA é
   parâmetro operacional (`OP-bovinos-gta`), com justificativa.
4. **"Área total" (item 5-b).** O MCR não define se é a área do empreendimento financiado ou a do imóvel.
   O Sicor público traz a área financiada. Quando só ela é conhecida, `planejar_metodo` usa a área financiada
   como aproximação e avisa.
5. **Autofiscalização assistida.** O nome não aparece na norma. Os métodos admitidos são remoto, documental
   e presencial (item 3). Enquadramos a captura guiada pelo próprio produtor como **documental**, isto é,
   análise de documentação comprobatória: foto/vídeo com integridade e georreferência. É interpretação nossa
   e precisa de revisão de compliance. O item 15 veda que a fiscalização seja feita pelo técnico contratado
   pelo mutuário. A análise e a conclusão continuam com a IF ou com a credenciada.
6. **Foto georreferenciada.** O MCR 2-7 não exige fotos nem georreferência para benfeitorias. Essa exigência
   existe no Proagro (MCR 12-4-16-e, Res. CMN 5.315/2026). No 2-7, a distância máxima da foto à gleba e a
   integridade da foto são **parâmetros operacionais**.
