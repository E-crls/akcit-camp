# A/B de centralidade v2 — papel e fala do mundo real (2026-10-16)

- Split **test**, 24 casos (todos os do test com as fotos lidas); leituras REAIS do qwen3.5:4b (`leitura_v2_test.jsonl`) e extração de alegações real (`narracoes_test_r4.jsonl`); erro de digitação e tempo por parâmetros citados (abaixo). Gerado por `scripts/py.sh eval/ab_centralidade_v2/run_ab_v2.py`.
- Os braços usam as MESMAS ferramentas de conciliação e o MESMO validador determinístico; o formulário também pede redigitação do que não valida. O oráculo é o papel lido sem erro.
- **Agente + residual** usa a implementação REAL (`laudo.docs_fiscais.residual` / ferramenta `completar_leitura_documento`, a mesma do condutor): o sistema pede só os campos críticos que não validaram, a fiscal lê no papel (voz; CPF/CNPJ digitados) com erro humano por caractere e o sistema revalida (até 3 tentativas). A última coluna é a simulação da rodada 2 (digitação de todos os campos do formulário que ficaram vazios), mantida para registrar a diferença. `sha256(src/)=1154df4aceffbf20…`.

| Medida (réplica 0; IC 95% de Wilson) | Formulário (sem LLM) | Agente (só fotos) | Agente + residual (real) | Agente + residual simulado (rodada 2) |
|---|---|---|---|---|
| Campos do papel corretos ao final | 99% [98–99%] (910/920) | 93% [92–95%] (859/920) | 99% [98–99%] (908/920) | 100% [99–100%] (916/920) |
| Campos aceitos com valor ERRADO | 1% [0–2%] (8/920) | 0% [0–1%] (3/920) | 0% [0–1%] (3/920) | 0% [0–1%] (3/920) |
| Conciliação igual à do oráculo (por caso) | 88% [69–96%] (21/24) | 29% [15–49%] (7/24) | 88% [69–96%] (21/24) | 92% [74–98%] (22/24) |
| Divergências documentais detectadas | 100% [61–100%] (6/6) | 100% [61–100%] (6/6) | 100% [61–100%] (6/6) | 100% [61–100%] (6/6) |
| Divergências falsas (campos) | 1 | 0 | 0 | 0 |
| Campos pendentes a mais que o oráculo | 2 | 40 | 3 | 2 |
| Alegações da fala com status certo | 78% [64–88%] (36/46) | 87% [74–94%] (40/46) | 87% [74–94%] (40/46) | 87% [74–94%] (40/46) |
| Alegações espúrias nocivas (viraram divergência/pendência) | 0 | 1 | 1 | 1 |
| **Conteúdo conciliado igual à referência (papel e fala)** | 58% [39–76%] (14/24) | 29% [15–49%] (7/24) | 71% [51–85%] (17/24) | 71% [51–85%] (17/24) |
| Idem, sem a menção a item não financiado (o formulário não tem campo para ela) | 88% [69–96%] (21/24) | 29% [15–49%] (7/24) | 79% [60–91%] (19/24) | 79% [60–91%] (19/24) |
| Tempo da fiscal por fiscalização, mediana (s) | 215,2 | 23,1 | 34,5 | 34,4 |
| Tempo de máquina (VLM/LLM) por fiscalização, mediana (s) | 0,0 | 53,4 | 48,0 | 54,5 |
| Interações por fiscalização (campos, fotos, falas) | 38,6 | 5,7 | 7,7 | 7,6 |
| Toques na tela por fiscalização | 304 | 0 | 12 | 23 |
| Fotos por fiscalização | 0,0 | 3,8 | 3,7 | 3,9 |

Pareado (completa): agente × formulário — só o agente 3, só o formulário 10, McNemar exato p = 0,0923; agente + residual × formulário — 6 × 3, p = 0,5078. Sem as menções a item não financiado: agente × formulário 0 × 14 (p = 0,0001); agente + residual × formulário 2 × 4 (p = 0,6875). Residual simulado (rodada 2) × formulário: 6 × 3 (p = 0,5078).

**Residual real:** 32 documento(s) com pedido; completos (todos os críticos validados) depois da fala da fiscal: 97% [84–99%] (31/32); tentativas por documento (média): 1,09. **Diferença para a simulação da rodada 2:** o pedido real vem do validador (só campos críticos indeterminados, agrupados: a linha de produtos inteira, a linha TOTAL da GTA, o município com o código IBGE), a chave de acesso é pedida em grupos de 4 dígitos (os 3 últimos grupos sempre, porque o VLM erra igual nas leituras; o resto vem dos campos validados), a fiscal fala em vez de digitar (só CPF/CNPJ e código do estabelecimento são digitados), a resposta é revalidada junto com o que a foto já validou (a chave tem de fechar com UF, data, série, número e CNPJ) e a tabela de produtos ilegível não tem residual (só nova foto ou o XML). A simulação digitava todos os campos do formulário que ficaram vazios e aceitava o que o formulário validava isoladamente.

## Leitura de documento por foto (todas as fotos do test, 3 níveis de degradação)

Validação determinística: dos 3336 campos lidos, a 1ª leitura crua do VLM errou 225 (e deixou 578 vazios). Desses erros, o pipeline (consenso + validação) **barrou 193**, corrigiu 26 pelo consenso e **aceitou 6** errados. Custo da rigidez: 201 campos que a 1ª leitura acertou ficaram indeterminados. Só com 1 leitura + validação (sem autoconsistência): 64 aceitos errados.

No total: 3336 campos; **aceitos e certos 76% [74–77%] (2533/3336)**; aceitos errados 0% [0–0%] (8/3336); barrados (indeterminado, pedem nova foto) 24% [22–25%] (795/3336). Precisão dos campos aceitos (certos ÷ aceitos): 100% [99–100%] (2533/2541).

| Documento:nível | campos | aceitos e certos | aceitos errados | barrados | precisão dos aceitos |
|---|---|---|---|---|---|
| danfe:leve | 408 | 93% [91–95%] (381/408) | 1 | 26 | 100% [99–100%] (381/382) |
| danfe:media | 408 | 88% [84–91%] (358/408) | 2 | 48 | 99% [98–100%] (358/360) |
| danfe:pesada | 408 | 38% [33–42%] (153/408) | 3 | 252 | 98% [94–99%] (153/156) |
| gta:media | 704 | 84% [82–87%] (594/704) | 0 | 110 | 100% [99–100%] (594/594) |
| gta:pesada | 704 | 62% [58–65%] (434/704) | 2 | 268 | 100% [98–100%] (434/436) |
| gta:scan | 704 | 87% [84–89%] (613/704) | 0 | 91 | 100% [99–100%] (613/613) |

| Documento:nível | n | todos os campos críticos certos | algum campo crítico aceito errado |
|---|---|---|---|
| danfe:leve | 24 | 46% [28–65%] (11/24) | 0% [0–14%] (0/24) |
| danfe:media | 24 | 21% [9–40%] (5/24) | 8% [2–26%] (2/24) |
| danfe:pesada | 24 | 0% [0–14%] (0/24) | 8% [2–26%] (2/24) |
| gta:media | 32 | 6% [2–20%] (2/32) | 0% [0–11%] (0/32) |
| gta:pesada | 32 | 0% [0–11%] (0/32) | 3% [1–16%] (1/32) |
| gta:scan | 32 | 44% [28–61%] (14/32) | 0% [0–11%] (0/32) |

| Campo | n | certo | aceito errado | barrado (indeterminado) |
|---|---|---|---|---|
| danfe:cfop | 72 | 75% [64–84%] (54/72) | 0 | 18 |
| danfe:chave | 72 | 56% [44–66%] (40/72) | 0 | 32 |
| danfe:data_emissao | 72 | 89% [80–94%] (64/72) | 0 | 8 |
| danfe:destinatario_doc | 72 | 35% [25–46%] (25/72) | 0 | 47 |
| danfe:destinatario_uf | 72 | 82% [72–89%] (59/72) | 0 | 13 |
| danfe:emitente_doc | 72 | 61% [50–72%] (44/72) | 0 | 28 |
| danfe:emitente_municipio | 72 | 35% [25–46%] (25/72) | 2 | 45 |
| danfe:emitente_uf | 72 | 96% [88–99%] (69/72) | 0 | 3 |
| danfe:ncm | 72 | 61% [50–72%] (44/72) | 3 | 25 |
| danfe:numero | 72 | 96% [88–99%] (69/72) | 0 | 3 |
| danfe:quantidade | 72 | 69% [58–79%] (50/72) | 0 | 22 |
| danfe:serie | 72 | 100% [95–100%] (72/72) | 0 | 0 |
| danfe:tp_nf | 72 | 88% [78–93%] (63/72) | 0 | 9 |
| danfe:unidade | 72 | 75% [64–84%] (54/72) | 0 | 18 |
| danfe:v_prod | 72 | 83% [73–90%] (60/72) | 1 | 11 |
| danfe:valor_total | 72 | 69% [58–79%] (50/72) | 0 | 22 |
| danfe:valor_unitario | 72 | 69% [58–79%] (50/72) | 0 | 22 |
| gta:chave_nfe | 96 | 52% [42–62%] (50/96) | 0 | 46 |
| gta:data_emissao | 96 | 83% [75–89%] (80/96) | 1 | 15 |
| gta:destino.codigo_estabelecimento | 96 | 59% [49–69%] (57/96) | 0 | 39 |
| gta:destino.doc | 96 | 75% [65–83%] (72/96) | 0 | 24 |
| gta:destino.ibge | 96 | 84% [76–90%] (81/96) | 0 | 15 |
| gta:destino.municipio | 96 | 88% [79–93%] (84/96) | 0 | 12 |
| gta:destino.uf | 96 | 93% [86–96%] (89/96) | 0 | 7 |
| gta:especie | 96 | 100% [96–100%] (96/96) | 0 | 0 |
| gta:finalidade | 96 | 92% [84–96%] (88/96) | 0 | 8 |
| gta:numero | 96 | 100% [96–100%] (96/96) | 0 | 0 |
| gta:origem.codigo_estabelecimento | 96 | 49% [39–59%] (47/96) | 0 | 49 |
| gta:origem.doc | 96 | 67% [57–75%] (64/96) | 0 | 32 |
| gta:origem.ibge | 96 | 89% [81–93%] (85/96) | 0 | 11 |
| gta:origem.municipio | 96 | 71% [61–79%] (68/96) | 0 | 28 |
| gta:origem.uf | 96 | 93% [86–96%] (89/96) | 0 | 7 |
| gta:quantidades_por_faixa | 96 | 38% [28–47%] (36/96) | 1 | 59 |
| gta:serie | 96 | 83% [75–89%] (80/96) | 0 | 16 |
| gta:total | 96 | 70% [60–78%] (67/96) | 0 | 29 |
| gta:total_femeas | 96 | 70% [60–78%] (67/96) | 0 | 29 |
| gta:total_machos | 96 | 70% [60–78%] (67/96) | 0 | 29 |
| gta:uf_emissao | 96 | 100% [96–100%] (96/96) | 0 | 0 |
| gta:validade | 96 | 85% [77–91%] (82/96) | 0 | 14 |

Classificação automática DANFE × GTA: 168/168. Latência da leitura (k = 2 a 3 leituras × 2 recortes): danfe p50 12,5 s / p95 26,7 s (n = 72); gta p50 15,5 s / p95 41,5 s (n = 96)

## Fala livre → alegações (isolada, com a evidência verdadeira do caso)

| Extrator | alegações com status certo | divergências/pendências certas | narrações inteiras certas | espúrias nocivas | latência p50 (s) |
|---|---|---|---|---|---|
| LLM + extrator determinístico, fala normalizada (como na API de voz) | 87% [74–94%] (40/46) | 100% [76–100%] (12/12) | 75% [55–88%] (18/24) | 1 | 1,5 |
| só o extrator determinístico (condutor sem LLM), fala normalizada | 70% [55–81%] (32/46) | 75% [47–91%] (9/12) | 46% [28–65%] (11/24) | 0 | 0,0 |
| LLM + determinístico, texto sem normalizar números | 83% [69–91%] (38/46) | 92% [65–99%] (11/12) | 71% [51–85%] (17/24) | 0 | 1,5 |
| só determinístico, texto sem normalizar | 46% [32–60%] (21/46) | 42% [19–68%] (5/12) | 12% [4–31%] (3/24) | 0 | 0,0 |
| condutor antes da rodada 2 (número por extenso descartado), sem normalizar | 54% [40–68%] (25/46) | 42% [19–68%] (5/12) | 29% [15–49%] (7/24) | 0 | 1,2 |

## Estabilidade e sensibilidade

Média sobre 49 réplicas (sorteio da qualidade da foto e dos erros de digitação): formulario: completas 49,0% (sem registro 78,8%), campos certos 98,9%, tempo 230,1 s; agente: completas 24,9% (sem registro 27,5%), campos certos 93,1%, tempo 23,8 s; agente_residual: completas 69,4% (sem registro 77,6%), campos certos 98,6%, tempo 46,3 s; agente_residual_simulado: completas 70,7% (sem registro 79,1%), campos certos 99,6%, tempo 42,3 s.

| Cenário | Formulário: completas (sem registro) / campos / tempo (s) | Agente | Agente + residual (real) | Agente + residual simulado |
|---|---|---|---|---|
| p_erro=0.0029 | 58,3% (95,8%) / 99,7% / 224,4 | 29,2% (29,2%) / 93,4% / 24,1 | 70,8% (79,2%) / 98,7% / 41,3 | 70,8% (79,2%) / 99,6% / 41,0 |
| p_erro=0.0054 | 58,3% (87,5%) / 98,9% / 230,5 | 29,2% (29,2%) / 93,4% / 24,1 | 70,8% (79,2%) / 98,7% / 41,3 | 70,8% (79,2%) / 99,6% / 41,0 |
| p_erro=0.0234 | 16,7% (25,0%) / 93,8% / 277,5 | 29,2% (29,2%) / 93,4% / 24,1 | 70,8% (79,2%) / 98,6% / 48,4 | 70,8% (79,2%) / 99,3% / 42,7 |
| foto_boa | 58,3% (87,5%) / 98,9% / 230,5 | 20,8% (20,8%) / 91,4% / 20,9 | 66,7% (75,0%) / 98,7% / 36,7 | 70,8% (79,2%) / 99,8% / 40,0 |
| foto_ruim | 58,3% (87,5%) / 98,9% / 230,5 | 8,3% (8,3%) / 89,6% / 26,1 | 70,8% (79,2%) / 98,2% / 76,1 | 70,8% (79,2%) / 99,3% / 60,9 |

Sanidade: o oráculo (papel lido sem erro) reproduz 300/312 rótulos de conteúdo do golden; as diferenças são esperadas (DANFE não prova integridade nem autorização: XML adulterado ou com DV errado só aparece no XML) — GLD-0016 (D11_NFE_CHAVE_DV_ERRADO) item:bov1:nfe_especie: oráculo ok, golden pendente; GLD-0016 (D11_NFE_CHAVE_DV_ERRADO) item:bov1:nfe_quantidade: oráculo ok, golden pendente; GLD-0016 (D11_NFE_CHAVE_DV_ERRADO) item:bov1:nfe_valor: oráculo ok, golden pendente; GLD-0016 (D11_NFE_CHAVE_DV_ERRADO) item:bov1:nfe_data: oráculo ok, golden pendente; GLD-0016 (D11_NFE_CHAVE_DV_ERRADO) item:bov1:nfe_partes: oráculo ok, golden pendente; GLD-0016 (D11_NFE_CHAVE_DV_ERRADO) item:bov1:nfe_operacao: oráculo ok, golden pendente; GLD-0044 (D10_NFE_DIGEST_INVALIDO) item:bov1:nfe_especie: oráculo ok, golden pendente; GLD-0044 (D10_NFE_DIGEST_INVALIDO) item:bov1:nfe_quantidade: oráculo ok, golden pendente

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
