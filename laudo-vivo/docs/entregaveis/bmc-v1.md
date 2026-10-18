# Business Model Canvas: Laudo Vivo (v1, regional)

**Laudo Vivo: prova auditável do crédito rural, do satélite ao curral.** Versão 1 de 08/10/2026, para o regional de 24/10/2026. A v0 é a tese da inscrição; a v2 sai para a final (28/11) com o módulo socioambiental e os números de piloto, se houver piloto. Números de mercado, fontes e contas em [`mercado.md`](mercado.md); a decisão de produto em [`docs/decisao.md`](../decisao.md).

**Fonte canônica:** este arquivo, `bmc-v1.html` (o mesmo conteúdo, para imprimir) e `bmc-v1.pdf` (1 página A4 paisagem, gerado do HTML por `node scripts/gerar_pdf_bmc.cjs`), no repositório; `negocio/` só aponta para cá. Os números medidos vêm de `numeros.md` (entre marcadores `<!--n:…-->`, conferidos por `scripts/gerar_numeros.py --verificar`); os de mercado e da avaliação do contador, que não mudam com a r4, ficam entre marcadores `<!--f:…-->`, conferidos contra `mercado.md` e `eval/golden/visao/RESULTADOS.md` por `scripts/py.sh scripts/checar_numeros_fixos.py`. O PDF é para o GitHub e para imprimir (A4, corpo de 8 pt): não projete o BMC; no palco, o modelo de negócio aparece no S4 do deck. Depois da r4: `gerar_numeros.py --aplicar` (a r4 já roda) e o PDF gerado de novo.

Sem marcadores a preencher: o que depende da equipe e ainda não existe (entrevistas, preço testado, filmagem em curral, agrônomo parceiro, piloto) está escrito como "ainda não", com a data. Até 16/10/2026 não há entrevista registrada, carta de intenção, piloto nem cliente. Revisado em 09/10/2026 contra o código (o servidor MCP, o custo medido no trace, o expurgo por chave e a leitura do papel por foto existem no repositório) e em 16/10/2026 contra a decisão do dia (`docs/decisao.md`: cunha "operações com animais" e pacote de exibição).

---

## 1. Segmentos de clientes

- **Pagador principal:** cooperativas de crédito singulares com carteira rural pecuária (cunha desde 16/10/2026: fiscalização de **operações com animais**, isto é, compra de gado por investimento, custeio de aquisição e manutenção de animais, cerca e curral; MCR 2-7, Res. CMN 5.267). Perfil ideal: as <!--f:mercado.singulares_perfil-->109<!--/f--> singulares com 300 ou mais itens físicos (gado, benfeitorias, máquinas) acima de R$ 20 mil por ano, que somam <!--f:mercado.pct_itens_perfil-->82%<!--/f--> desses itens nas singulares (Sicor 2025).
- **Pagador-canal:** empresas credenciadas que fiscalizam crédito rural para cooperativas, Caixa e bancos.
- **Usuária:** "Paula", a fiscal de campo (técnica agrícola ou agrônoma) da cooperativa ou da credenciada (persona composta de fontes públicas, não uma entrevistada).
- **Depois:** centrais de cooperativas e bancos médios; credor privado do agro (FIDC, Fiagro, revendas com barter) no módulo "Lastro".
- **Mercado de piloto:** Goiás (<!--f:mercado.itens_go-->34.890<!--/f--> itens físicos acima de R$ 20 mil em 2025; <!--f:mercado.singulares_go_100-->16<!--/f--> singulares com mais de 100 itens no estado).

## 2. Proposta de valor

- **Para a cooperativa:** cada item da fiscalização aponta para a sua prova (vídeo, foto georreferenciada, NF-e, GTA, satélite, regra do MCR 2-7), pronta para a auditoria interna, o BCB e o TCU; depois do selo, o **pacote de exibição** que o BCB e a Justiça pedem (arquivos com sha256, gleba, fotos, cenas de satélite, fundamento por item e o status real de cada exigência) sai em um clique, por ação humana. Visita presencial só onde há divergência.
- **Para a fiscal:** sai do curral com a evidência mínima que a norma pede, conduzida por voz; **não digita o papel**: fotografa a nota e a GTA, a IA lê, as regras conferem e o agente pede só o que faltou (no teste congelado com fiscal simulado, a IA não conciliou mais que o formulário digitado, <!--n:ab2_teste.residual.kn-->17/24<!--/n--> contra <!--n:ab2_teste.formulario.kn-->14/24<!--/n--> (<!--n:ab2_teste.mcnemar.curto-->p = 0,51<!--/n-->); o ganho é poupar a digitação, <!--n:ab2_teste.toques_residual.valor-->12<!--/n--> toques contra <!--n:ab2_teste.toques_formulario.valor-->304<!--/n-->; no dev, onde o A/B foi desenvolvido, <!--n:ab2.residual.valor-->97%<!--/n--> contra <!--n:ab2.formulario.valor-->42%<!--/n-->, que não se repetiu); o laudo sai pronto para ela revisar e assinar; o agente recusa pressão ("pode marcar 29") e registra a ocorrência.
- **Para a credenciada:** mais fiscalizações por fiscal por dia, menos retrabalho. É hipótese: nenhum fiscal foi cronometrado até 16/10/2026; no teste com fiscal simulado, o tempo da fiscal, modelado com parâmetros publicados, foi de <!--n:ab2_teste.tempo_residual.uma_casa-->34,5 s<!--/n--> contra <!--n:ab2_teste.tempo_formulario.valor-->215 s<!--/n--> digitando, mais cerca de <!--n:ab2_teste.tempo_maquina_residual.valor-->48 s<!--/n--> de máquina.
- **O que nos diferencia:** os outros apontam o que o satélite vê; nós fechamos a prova do que ele não vê, item a item, com abstenção quando a evidência não basta.

## 3. Canais

- Venda direta consultiva a cooperativas de Goiás (teste retroativo → Piloto Fundador → contrato).
- Credenciadas como canal de licença (acesso indireto ao volume de BB e Caixa).
- Indicação entre cooperativas, eventos do sistema cooperativo, CREA-GO e entidades de agronomia.
- Repositório aberto (Apache-2.0: rulebooks MCR 2-7/2-9 e servidor MCP mínimo com as ferramentas do agente) como vitrine técnica.
- Depois: centrais de cooperativas (marca branca e API).

## 4. Relacionamento com clientes

- Piloto Fundador de 90 dias com garantia de aceitação (refazemos sem custo se a auditoria devolver por falta de evidência que o agente deveria ter exigido).
- Sucesso do cliente dedicado por cooperativa; treinamento das fiscais em campo.
- Relatório mensal de qualidade: aceitação na 1ª revisão, abstenção, divergências, visitas evitadas.
- Comunidade de fiscais (grupo de usuários) para melhorar roteiros de coleta.

## 5. Fontes de receita

| Produto | Preço-alvo (a testar) |
|---|---|
| Fiscalização assistida, por fiscalização concluída | <!--f:mercado.preco_fiscalizacao-->R$ 79<!--/f--> (preço-alvo; <!--f:mercado.preco_volume-->R$ 59<!--/f--> acima de 500/ano) |
| Licença de credenciada, por fiscal/mês (15 fiscalizações incluídas) | <!--f:mercado.preco_licenca-->R$ 590<!--/f--> |
| Triagem de carteira pecuária, por operação ativa/ano | <!--f:mercado.preco_triagem-->R$ 8<!--/f--> |
| Exceção socioambiental resolvida (a partir da final) | <!--f:mercado.preco_excecao-->R$ 490<!--/f--> |
| Fiscalização remota-first entregue como serviço (fase 2) | <!--f:mercado.preco_servico-->R$ 290<!--/f--> |
| Piloto Fundador (90 dias, até 150 fiscalizações) | <!--f:mercado.preco_piloto-->R$ 5.900<!--/f--> |

Âncora: piso de <!--f:mercado.piso_visita-->R$ 669<!--/f--> por visita presencial de fiscalização (tabela de honorários da AEA-MS 2024; piso de outro estado, não preço praticado em GO). Os preços acima são preço-alvo: nenhum foi perguntado a cliente até 16/10/2026, e o Piloto Fundador é o teste. Quando houver entrevista registrada (`negocio/kit_validacao/registro_entrevistas.csv`, nenhuma até hoje), a mediana do preço aceito entra aqui com o n.

## 6. Recursos-chave

- **Fiscal-GO 2026:** operações de crédito rural de Goiás com polígono, lotação implícita, sobreposição e NDVI, publicado como "prioridade de verificação".
- **Pacote de exibição BCB/Justiça** (primeira versão no código em 16/10/2026, liberado só depois do selo).
- **Golden set de fiscalizações** com divergências plantadas e rotuladas: <!--n:golden.n_total.valor-->60<!--/n--> casos sintéticos (<!--n:golden.n_teste.valor-->24<!--/n--> no split de teste, congelado em 16/10/2026); defeitos de perito externo ainda por vir. Benchmark de leitura de papel por foto: <!--n:ab2.leitura_campos.valor-->5.025<!--/n--> campos de DANFE e GTA.
- **MCR 2-7 e 2-9 como código** (rulebooks versionados com citação de item) e servidor MCP mínimo (stdio) com as ferramentas do agente.
- **Vídeos de curral anotados** em Goiás: **ainda nenhum** (16/10/2026). A contagem foi avaliada em <!--f:visao.videos_reais-->5<!--/f--> vídeos reais do Wikimedia e <!--f:visao.videos_semissinteticos-->5<!--/f--> semissintéticos (`eval/golden/visao/RESULTADOS.md`); filmar lotes em curral goiano, com termo de consentimento (`docs/tcle_modelo.md`), é a próxima etapa.
- Agente com política que bloqueia por padrão, verificador independente e trilha com hash.
- Agrônomo com ART como parceiro (a buscar: nenhum até 16/10/2026); equipe de IA, dados e vendas.

## 7. Atividades-chave

- Conduzir, verificar e selar fiscalizações e emitir o pacote de exibição; manter os rulebooks atualizados a cada resolução do CMN.
- Avaliar o agente continuamente (golden set com split de teste congelado em 16/10/2026, red team, métrica de degradação).
- Vender e implantar em cooperativas; formar a rede de credenciadas.
- Rotular desfechos (aceito, devolvido, desclassificado) para melhorar a triagem e a verificação.
- Segurança e LGPD (minimização, mascaramento, chave da NF-e e CPF só como máscara e hash com sal da instalação, guarda pelo item 23 do MCR 2-7, expurgo dos brutos por chave por fiscalização; `docs/privacidade.md`).

## 8. Parcerias-chave

Nenhuma parceria está firmada até 16/10/2026: a lista é de quem o modelo precisa, não de quem já está com a gente.

- Credenciadas e agrônomos revisores (rede técnica, a formar).
- Cooperativas-piloto e suas centrais (nenhum piloto até hoje).
- Fontes públicas: BCB (Sicor), INPE/AWS Open Data (Sentinel-2), IBGE (PPM), MMA (lista MCR), Agrodefesa (GTA, integração a buscar).
- CEIA-UFG/AKCIT e Escola de Agronomia da UFG (avaliação, fazenda para filmagem).
- AWS (créditos do prêmio) para a camada de nuvem opcional.
- Possíveis parceiros de integração: fornecedores de monitoramento remoto (consumir o alerta deles).

## 9. Estrutura de custos

- **Pessoas** (maior custo): engenharia, vendas e sucesso do cliente, agrônomos revisores.
- **Tecnologia por fiscalização:** LLM medido no trace da demo (<!--n:custo.tokens_entrada_mil.valor-->135 mil<!--/n--> tokens): <!--n:custo.local_rs.valor-->R$ 0,0035<!--/n--> de energia local, <!--n:custo.nuvem_min_rs.valor-->R$ 0,04<!--/n-->–<!--n:custo.nuvem_max_rs.valor-->R$ 0,28<!--/n--> se fosse em nuvem; com transcrição, visão e armazenamento por 5 anos, <!--f:mercado.tec_local-->~R$ 0,50–3<!--/f--> local e <!--f:mercado.tec_nuvem-->~R$ 1–6<!--/f--> em nuvem (estimado); a inferência é menos de <!--f:mercado.inferencia_pct-->5%<!--/f--> do preço.
- **Revisão humana:** QA amostral (<!--f:mercado.revisao_amostral-->~R$ 2<!--/f--> por fiscalização no software); revisão e assinatura (<!--f:mercado.revisao_servico-->~R$ 42<!--/f-->) e visita de exceção no serviço.
- **Campo:** deslocamento para pilotos e filmagens; ART por contrato; seguro de responsabilidade civil profissional.
- **Comercial:** CAC estimado de <!--f:mercado.cac_cooperativa-->R$ 15–30 mil<!--/f--> por cooperativa e <!--f:mercado.cac_credenciada-->R$ 2–5 mil<!--/f--> por credenciada.
- Margem bruta estimada: <!--f:mercado.margem_software-->82–92%<!--/f--> no software, <!--f:mercado.margem_servico-->~56%<!--/f--> no serviço, <!--f:mercado.margem_mix-->~80%<!--/f--> no mix do ano 2.
