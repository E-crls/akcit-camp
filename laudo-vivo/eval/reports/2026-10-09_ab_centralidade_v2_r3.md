# A/B de centralidade v2 — papel e fala do mundo real (2026-10-09)

- Split **dev**, 36 casos (todos os do dev com as fotos lidas); leituras REAIS do qwen3.5:4b (`leitura_v2_dev.jsonl`) e extração de alegações real (`narracoes_dev_r3.jsonl`); erro de digitação e tempo por parâmetros citados (abaixo). Gerado por `scripts/py.sh eval/ab_centralidade_v2/run_ab_v2.py`.
- Os braços usam as MESMAS ferramentas de conciliação e o MESMO validador determinístico; o formulário também pede redigitação do que não valida. O oráculo é o papel lido sem erro.
- **Agente + residual** usa a implementação REAL (`laudo.docs_fiscais.residual` / ferramenta `completar_leitura_documento`, a mesma do condutor): o sistema pede só os campos críticos que não validaram, a fiscal lê no papel (voz; CPF/CNPJ digitados) com erro humano por caractere e o sistema revalida (até 3 tentativas). A última coluna é a simulação da rodada 2 (digitação de todos os campos do formulário que ficaram vazios), mantida para registrar a diferença. `sha256(src/)=c297955f9b44ad37…`.

| Medida (réplica 0; IC 95% de Wilson) | Formulário (sem LLM) | Agente (só fotos) | Agente + residual (real) | Agente + residual simulado (rodada 2) |
|---|---|---|---|---|
| Campos do papel corretos ao final | 99% [98–99%] (1380/1399) | 95% [94–96%] (1335/1399) | 99% [98–99%] (1383/1399) | 100% [99–100%] (1397/1399) |
| Campos aceitos com valor ERRADO | 1% [1–2%] (13/1399) | 0% [0–0%] (0/1399) | 0% [0–0%] (0/1399) | 0% [0–0%] (0/1399) |
| Conciliação igual à do oráculo (por caso) | 81% [65–90%] (29/36) | 44% [30–60%] (16/36) | 100% [90–100%] (36/36) | 100% [90–100%] (36/36) |
| Divergências documentais detectadas | 100% [72–100%] (10/10) | 100% [72–100%] (10/10) | 100% [72–100%] (10/10) | 100% [72–100%] (10/10) |
| Divergências falsas (campos) | 1 | 0 | 0 | 0 |
| Campos pendentes a mais que o oráculo | 7 | 36 | 0 | 0 |
| Alegações da fala com status certo | 74% [62–82%] (53/72) | 99% [93–100%] (71/72) | 99% [93–100%] (71/72) | 99% [93–100%] (71/72) |
| Alegações espúrias nocivas (viraram divergência/pendência) | 0 | 0 | 0 | 0 |
| **Fiscalizações completas com evidência suficiente** | 42% [27–58%] (15/36) | 44% [30–60%] (16/36) | 97% [86–100%] (35/36) | 97% [86–100%] (35/36) |
| Completas sem contar menção a item não financiado | 78% [62–88%] (28/36) | 44% [30–60%] (16/36) | 97% [86–100%] (35/36) | 97% [86–100%] (35/36) |
| Tempo da fiscal por fiscalização, mediana (s) | 216,2 | 23,5 | 37,2 | 32,0 |
| Tempo de máquina (VLM/LLM) por fiscalização, mediana (s) | 0,0 | 60,9 | 58,8 | 60,3 |
| Interações por fiscalização (campos, fotos, falas) | 39,7 | 5,5 | 7,1 | 7,1 |
| Toques na tela por fiscalização | 314 | 0 | 19 | 17 |
| Fotos por fiscalização | 0,0 | 3,5 | 3,5 | 3,5 |

Pareado (completa): agente × formulário — só o agente 9, só o formulário 8, McNemar exato p = 1,0000; agente + residual × formulário — 21 × 1, p = 0,0000. Sem as menções a item não financiado: agente × formulário 2 × 14 (p = 0,0042); agente + residual × formulário 8 × 1 (p = 0,0391). Residual simulado (rodada 2) × formulário: 21 × 1 (p = 0,0000).

**Residual real:** 41 documento(s) com pedido; completos (todos os críticos validados) depois da fala da fiscal: 93% [81–97%] (38/41); tentativas por documento (média): 1,15. **Diferença para a simulação da rodada 2:** o pedido real vem do validador (só campos críticos indeterminados, agrupados: a linha de produtos inteira, a linha TOTAL da GTA, o município com o código IBGE), a chave de acesso é pedida em grupos de 4 dígitos (os 3 últimos grupos sempre, porque o VLM erra igual nas leituras; o resto vem dos campos validados), a fiscal fala em vez de digitar (só CPF/CNPJ e código do estabelecimento são digitados), a resposta é revalidada junto com o que a foto já validou (a chave tem de fechar com UF, data, série, número e CNPJ) e a tabela de produtos ilegível não tem residual (só nova foto ou o XML). A simulação digitava todos os campos do formulário que ficaram vazios e aceitava o que o formulário validava isoladamente.

## Leitura de documento por foto (todas as fotos do dev, 3 níveis de degradação)

Validação determinística: dos 5025 campos lidos, a 1ª leitura crua do VLM errou 340 (e deixou 798 vazios). Desses erros, o pipeline (consenso + validação) **barrou 278**, corrigiu 55 pelo consenso e **aceitou 7** errados. Custo da rigidez: 280 campos que a 1ª leitura acertou ficaram indeterminados. Só com 1 leitura + validação (sem autoconsistência): 92 aceitos errados.

No total: 5025 campos; **aceitos e certos 78% [77–79%] (3904/5025)**; aceitos errados 0% [0–0%] (12/5025); barrados (indeterminado, pedem nova foto) 22% [21–23%] (1109/5025). Precisão dos campos aceitos (certos ÷ aceitos): 100% [99–100%] (3904/3916).

| Documento:nível | campos | aceitos e certos | aceitos errados | barrados | precisão dos aceitos |
|---|---|---|---|---|---|
| danfe:leve | 663 | 94% [91–95%] (620/663) | 0 | 43 | 100% [99–100%] (620/620) |
| danfe:media | 663 | 88% [86–90%] (585/663) | 3 | 75 | 99% [99–100%] (585/588) |
| danfe:pesada | 663 | 38% [35–42%] (254/663) | 4 | 405 | 98% [96–99%] (254/258) |
| gta:media | 1012 | 90% [88–92%] (911/1012) | 0 | 101 | 100% [100–100%] (911/911) |
| gta:pesada | 1012 | 63% [60–66%] (641/1012) | 5 | 366 | 99% [98–100%] (641/646) |
| gta:scan | 1012 | 88% [86–90%] (893/1012) | 0 | 119 | 100% [100–100%] (893/893) |

| Documento:nível | n | todos os campos críticos certos | algum campo crítico aceito errado |
|---|---|---|---|
| danfe:leve | 39 | 54% [39–68%] (21/39) | 0% [0–9%] (0/39) |
| danfe:media | 39 | 28% [17–44%] (11/39) | 5% [1–17%] (2/39) |
| danfe:pesada | 39 | 0% [0–9%] (0/39) | 5% [1–17%] (2/39) |
| gta:media | 46 | 35% [23–49%] (16/46) | 0% [0–8%] (0/46) |
| gta:pesada | 46 | 0% [0–8%] (0/46) | 7% [2–18%] (3/46) |
| gta:scan | 46 | 52% [38–66%] (24/46) | 0% [0–8%] (0/46) |

| Campo | n | certo | aceito errado | barrado (indeterminado) |
|---|---|---|---|---|
| danfe:cfop | 117 | 74% [65–81%] (86/117) | 1 | 30 |
| danfe:chave | 117 | 57% [48–66%] (67/117) | 0 | 50 |
| danfe:data_emissao | 117 | 89% [82–93%] (104/117) | 0 | 13 |
| danfe:destinatario_doc | 117 | 38% [29–47%] (44/117) | 0 | 73 |
| danfe:destinatario_uf | 117 | 74% [65–81%] (86/117) | 0 | 31 |
| danfe:emitente_doc | 117 | 60% [51–68%] (70/117) | 0 | 47 |
| danfe:emitente_municipio | 117 | 37% [29–46%] (43/117) | 3 | 71 |
| danfe:emitente_uf | 117 | 98% [94–100%] (115/117) | 0 | 2 |
| danfe:ncm | 117 | 62% [53–71%] (73/117) | 2 | 42 |
| danfe:numero | 117 | 95% [89–98%] (111/117) | 1 | 5 |
| danfe:quantidade | 117 | 70% [61–78%] (82/117) | 0 | 35 |
| danfe:serie | 117 | 99% [95–100%] (116/117) | 0 | 1 |
| danfe:tp_nf | 117 | 87% [80–92%] (102/117) | 0 | 15 |
| danfe:unidade | 117 | 78% [69–84%] (91/117) | 0 | 26 |
| danfe:v_prod | 117 | 90% [83–94%] (105/117) | 0 | 12 |
| danfe:valor_total | 117 | 70% [61–78%] (82/117) | 0 | 35 |
| danfe:valor_unitario | 117 | 70% [61–78%] (82/117) | 0 | 35 |
| gta:chave_nfe | 138 | 51% [43–60%] (71/138) | 0 | 67 |
| gta:data_emissao | 138 | 86% [79–90%] (118/138) | 1 | 19 |
| gta:destino.codigo_estabelecimento | 138 | 64% [56–72%] (89/138) | 1 | 48 |
| gta:destino.doc | 138 | 78% [70–84%] (107/138) | 0 | 31 |
| gta:destino.ibge | 138 | 86% [79–91%] (119/138) | 0 | 19 |
| gta:destino.municipio | 138 | 86% [79–91%] (119/138) | 0 | 19 |
| gta:destino.uf | 138 | 90% [84–94%] (124/138) | 0 | 14 |
| gta:especie | 138 | 100% [97–100%] (138/138) | 0 | 0 |
| gta:finalidade | 138 | 97% [93–99%] (134/138) | 0 | 4 |
| gta:numero | 138 | 100% [97–100%] (138/138) | 0 | 0 |
| gta:origem.codigo_estabelecimento | 138 | 54% [45–62%] (74/138) | 0 | 64 |
| gta:origem.doc | 138 | 71% [63–78%] (98/138) | 0 | 40 |
| gta:origem.ibge | 138 | 87% [80–92%] (120/138) | 0 | 18 |
| gta:origem.municipio | 138 | 80% [72–86%] (110/138) | 0 | 28 |
| gta:origem.uf | 138 | 95% [90–98%] (131/138) | 0 | 7 |
| gta:quantidades_por_faixa | 138 | 41% [33–50%] (57/138) | 2 | 79 |
| gta:serie | 138 | 86% [79–90%] (118/138) | 0 | 20 |
| gta:total | 138 | 78% [71–84%] (108/138) | 0 | 30 |
| gta:total_femeas | 138 | 78% [71–84%] (108/138) | 0 | 30 |
| gta:total_machos | 138 | 78% [71–84%] (108/138) | 0 | 30 |
| gta:uf_emissao | 138 | 100% [97–100%] (138/138) | 0 | 0 |
| gta:validade | 138 | 86% [79–90%] (118/138) | 1 | 19 |

Classificação automática DANFE × GTA: 255/255. Latência da leitura (k = 2 a 3 leituras × 2 recortes): danfe p50 15,8 s / p95 25,1 s (n = 117); gta p50 19,5 s / p95 28,0 s (n = 138)

## Fala livre → alegações (isolada, com a evidência verdadeira do caso)

| Extrator | alegações com status certo | divergências/pendências certas | narrações inteiras certas | espúrias nocivas | latência p50 (s) |
|---|---|---|---|---|---|
| LLM + extrator determinístico, fala normalizada (como na API de voz) | 99% [93–100%] (71/72) | 94% [74–99%] (17/18) | 97% [86–100%] (35/36) | 0 | 0,9 |
| só o extrator determinístico (condutor sem LLM), fala normalizada | 72% [61–81%] (52/72) | 67% [44–84%] (12/18) | 44% [30–60%] (16/36) | 0 | 0,0 |
| LLM + determinístico, texto sem normalizar números | 86% [76–92%] (62/72) | 89% [67–97%] (16/18) | 72% [56–84%] (26/36) | 0 | 0,8 |
| só determinístico, texto sem normalizar | 46% [35–57%] (33/72) | 50% [29–71%] (9/18) | 11% [4–25%] (4/36) | 0 | 0,0 |
| condutor antes da rodada 2 (número por extenso descartado), sem normalizar | 58% [47–69%] (42/72) | 56% [34–75%] (10/18) | 33% [20–50%] (12/36) | 0 | 0,8 |

## Estabilidade e sensibilidade

Média sobre 49 réplicas (sorteio da qualidade da foto e dos erros de digitação): formulario: completas 37,6% (sem registro 77,6%), campos certos 98,6%, tempo 237,5 s; agente: completas 41,2% (sem registro 41,2%), campos certos 94,6%, tempo 23,9 s; agente_residual: completas 91,3% (sem registro 91,3%), campos certos 98,5%, tempo 42,1 s; agente_residual_simulado: completas 94,6% (sem registro 94,6%), campos certos 99,7%, tempo 39,7 s.

| Cenário | Formulário: completas (sem registro) / campos / tempo (s) | Agente | Agente + residual (real) | Agente + residual simulado |
|---|---|---|---|---|
| p_erro=0.0029 | 47,2% (91,7%) / 99,4% / 229,2 | 44,4% (44,4%) / 95,4% / 23,9 | 97,2% (97,2%) / 98,9% / 42,0 | 97,2% (97,2%) / 99,9% / 36,0 |
| p_erro=0.0054 | 41,7% (77,8%) / 98,6% / 239,0 | 44,4% (44,4%) / 95,4% / 23,9 | 97,2% (97,2%) / 98,9% / 43,3 | 97,2% (97,2%) / 99,9% / 36,0 |
| p_erro=0.0234 | 25,0% (44,4%) / 93,9% / 291,0 | 44,4% (44,4%) / 95,4% / 23,9 | 94,4% (94,4%) / 98,8% / 45,0 | 97,2% (97,2%) / 99,8% / 36,9 |
| foto_boa | 41,7% (77,8%) / 98,6% / 239,0 | 38,9% (38,9%) / 92,6% / 21,3 | 94,4% (94,4%) / 98,4% / 37,4 | 97,2% (97,2%) / 99,9% / 41,3 |
| foto_ruim | 41,7% (77,8%) / 98,6% / 239,0 | 13,9% (13,9%) / 92,1% / 26,5 | 80,6% (80,6%) / 98,3% / 66,9 | 83,3% (83,3%) / 99,1% / 55,1 |

Sanidade: o oráculo (papel lido sem erro) reproduz 456/468 rótulos de conteúdo do golden; as diferenças são esperadas (DANFE não prova integridade nem autorização: XML adulterado ou com DV errado só aparece no XML) — GLD-0018 (D11_NFE_CHAVE_DV_ERRADO) item:bov1:nfe_especie: oráculo ok, golden pendente; GLD-0018 (D11_NFE_CHAVE_DV_ERRADO) item:bov1:nfe_quantidade: oráculo ok, golden pendente; GLD-0018 (D11_NFE_CHAVE_DV_ERRADO) item:bov1:nfe_valor: oráculo ok, golden pendente; GLD-0018 (D11_NFE_CHAVE_DV_ERRADO) item:bov1:nfe_data: oráculo ok, golden pendente; GLD-0018 (D11_NFE_CHAVE_DV_ERRADO) item:bov1:nfe_partes: oráculo ok, golden pendente; GLD-0018 (D11_NFE_CHAVE_DV_ERRADO) item:bov1:nfe_operacao: oráculo ok, golden pendente; GLD-0029 (D10_NFE_DIGEST_INVALIDO) item:bov1:nfe_especie: oráculo ok, golden pendente; GLD-0029 (D10_NFE_DIGEST_INVALIDO) item:bov1:nfe_quantidade: oráculo ok, golden pendente

## Parâmetros e fontes

- `p_erro_caractere` = 0.0054
- `p_erro_sensibilidade` = [0.0029, 0.0054, 0.0234]
- `tipos_erro` = {'substituicao': 0.79, 'transposicao': 0.102, 'omissao': 0.054, 'insercao': 0.054}
- `t_K` = 0.39
- `t_K_letra` = 0.33
- `t_M` = 1.35
- `t_S_macro` = 0.36
- `bloco_leitura` = 4
- `t_selecao` = 2.13
- `t_foto` = 2.23
- `fala_palavras_s` = 2.1681666666666666
- `t_confirmacao` = 2.35
- `max_tentativas_campo` = 3
- `max_fotos` = 2
- `dist_foto_danfe` = {'leve': 0.5, 'media': 0.35, 'pesada': 0.15}
- `dist_foto_gta` = {'scan': 0.3, 'media': 0.5, 'pesada': 0.2}
- `melhor_nivel` = {'pesada': 'media', 'media': 'leve', 'leve': None, 'scan': None}
- `melhor_nivel_gta` = {'pesada': 'media', 'media': 'scan', 'scan': None}
- `replicacoes` = 50
- `p_erro_voz_caractere` = 0.0054
- `t_preparo_campo_residual` = 1.35

- [WCC2011] Wiseman S, Cairns P, Cox A (2011). A Taxonomy of Number Entry Error. Proc. HCI 2011, BCS eWiC. doi:10.14236/ewic/hci2011.46
- [G2025] Garza MY et al. (2025). Error rates of data processing methods in clinical research: systematic review and meta-analysis. Int J Med Inform 195:105749, Tabela 2. doi:10.1016/j.ijmedinf.2024.105749
- [P2019] Palin K, Feit AM, Kim S, Kristensson PO, Oulasvirta A (2019). How do People Type on Mobile Devices? MobileHCI '19, Tabela 3. doi:10.1145/3338286.3340120
- [V1969] Verhoeff J (1969). Error Detecting Decimal Codes. Mathematical Centre Tracts 29, seções 0.5–0.6
- [H2007] Holleis P, Otto F, Hussmann H, Schmidt A (2007). Keystroke-level model for advanced mobile phone interaction. CHI '07, Tabela 1. doi:10.1145/1240624.1240851
- [CMN1980] Card SK, Moran TP, Newell A (1980). The keystroke-level model for user performance time with interactive systems. CACM 23(7):396–410, Fig. 1. doi:10.1145/358886.358895
- [S2019] Santos LP et al. (2019). Velocidade da fala de adultos pessoenses sem transtornos da fluência. Rev. Bras. Ciências da Saúde 23(2)
