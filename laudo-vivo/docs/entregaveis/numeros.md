# Números do Laudo Vivo (fonte única)

*Gerado por `scripts/py.sh scripts/gerar_numeros.py` a partir de `eval/reports/2026-10-16_*_r4*.json` (todos com `sha256(src/)=1154df4aceffbf20…`, ou `02d050f4267708c9…` com LF, como o git guarda) e do custo medido no trace da demo. Não edite à mão: os textos citam estes números entre marcadores `<!--n:chave-->…<!--/n-->`, e `--verificar` falha se algum divergir.*

**Par obrigatório** (`--verificar`; no mesmo parágrafo ou, numa tabela, na mesma linha): `ab2.residual*` e `ab2.formulario*` (dev) exigem um `ab2_teste.*`; `redteam.ataques` (equipe) exige `redteam.cego_ataques`; `r41.v3_regressao_*` (não cega) exige `redteam.cego_ataques`.

Split de teste (`sha256_conteudo=f47e444648b4…`): **congelado** quando esta rodada foi medida.

## Código depois da avaliação

O código mudou depois desta rodada (r4.1 (versao final, depois da revisao do P1): equivalencia apos correcoes de declaracao e PIN motivadas pelo red-team cego v3 e pela revisao; a rodada completa com o LLM fica para a r5 (o congelamento citado na conclusao padrao do script foi a r4)). Conferência de equivalência em 16/10/2026 23:01, no código `sha256(src/)=52be6b825037b28f…`: golden set sem LLM (todas as métricas por split): **igual**; red-team sem LLM (resumo): **igual**; A/B v2 (leituras e alegações gravadas; tudo menos config): **igual**; replay da demo na CLI, 19 passos com a foto do DANFE (gravado no código novo): **igual**; replay da demo na CLI, só o XML, 17 passos (gravado em 08/10, antes das mudanças): **igual**; contingência da interface, 19 passos pela API (gravada no código novo): **igual**. Métricas sem LLM idênticas e o contexto do LLM inalterado nas gravações: os números da referência continuam valendo para o código atual; a rodada completa com o LLM fica para o congelamento.

Regressão sem LLM do conjunto cego v3 no código novo (`eval/reports/2026-10-16_redteam_deterministico_r4.1_v3regressao.json`): **não cega**, porque as correções foram motivadas por estes casos. As chaves dela (`*.v3_regressao_*`) só valem ao lado do resultado cego (`redteam.cego_*`), que não muda; os números com LLM continuam os medidos no código da rodada.

| Chave | Valor | Falado |
|---|---|---|
| `golden.n_total` | 60 |  |
| `golden.n_dev` | 36 |  |
| `golden.n_teste` | 24 |  |
| `golden.teste_validos` | 10 |  |
| `golden.teste_defeito` | 9 |  |
| `golden.teste_ambiguos` | 5 |  |
| `recall_teste` | 1,00 [0,70–1,00] (9/9) | 9 de 9 |
| `overblocking_teste` | 0% [0–28%] (0/10) | 0 de 10 |
| `abstencao_teste` | 1,00 [0,57–1,00] (5/5) | 5 de 5 |
| `falso_verificado_teste` | 0% [0–19%] (0/16) | 0 de 16 |
| `grounding.sem_lastro` | 0 |  |
| `grounding.falas` | 273 |  |
| `grounding.laudos` | 24 |  |
| `sem_llm.recall_teste` | 1,00 [0,70–1,00] (9/9) | 9 de 9 |
| `sem_llm.overblocking_teste` | 0% [0–28%] (0/10) | 0 de 10 |
| `sem_llm.abstencao_teste` | 1,00 [0,57–1,00] (5/5) | 5 de 5 |
| `agente.tool_call_valida` | 100% [90–100%] (35/35) | 35 de 35 |
| `agente.turnos_plano_teste` | 148 |  |
| `agente.acao_llm_correta_teste` | 42% [36–48%] (103/248) | 103 de 248 |
| `agente.acao_llm_correta_dev` | 42% [37–47%] (156/372) | 156 de 372 |
| `agente.acao_llm_correta_upload_dev` | 5% [3–9%] (12/228) | 12 de 228 |
| `agente.latencia_p50` | 2,0 s |  |
| `agente.latencia_p95` | 2,8 s |  |
| `agente_rep.casos_status_diferente` | 0% [0–14%] (0/24) | 0 de 24 |
| `agente_rep.emissao_diferente` | 0% [0–14%] (0/24) | 0 de 24 |
| `agente_rep.turnos_fala_diferente` | 4% [2–7%] (10/273) | 10 de 273 |
| `agente_rep.turnos_acoes_diferentes` | 0% [0–1%] (0/273) | 0 de 273 |
| `agente_rep.numeros_iguais` | sim |  |
| `agente_rep.recall_teste` | 1,00 [0,70–1,00] (9/9) | 9 de 9 |
| `agente_rep.overblocking_teste` | 0% [0–28%] (0/10) | 0 de 10 |
| `redteam.n_casos` | 107 |  |
| `redteam.n_ataques` | 80 |  |
| `redteam.ataques` | 0% [0–5%] (0/80) | 0 de 80 |
| `redteam.overblocking` | 0% [0–12%] (0/27) | 0 de 27 |
| `redteam.sem_llm_ataques` | 0% [0–5%] (0/80) | 0 de 80 |
| `redteam.original_ataques` | 0% [0–7%] (0/49) | 0 de 49 |
| `redteam.original_overblocking` | 0% [0–26%] (0/11) | 0 de 11 |
| `redteam.v2_ataques` | 0% [0–11%] (0/31) | 0 de 31 |
| `redteam.v2_overblocking` | 0% [0–19%] (0/16) | 0 de 16 |
| `redteam.cat_argumentos_llm` | 0% [0–43%] (0/5) | 0 de 5 |
| `redteam.cat_assinatura` | 0% [0–28%] (0/10) | 0 de 10 |
| `redteam.defesa_assinatura` | 100% [44–100%] (3/3) | 3 de 3 |
| `redteam.cat_falha_ferramenta` | 0% [0–32%] (0/8) | 0 de 8 |
| `redteam.cat_fora_de_escopo` | 0% [0–43%] (0/5) | 0 de 5 |
| `redteam.cat_injecao_documento` | 0% [0–32%] (0/8) | 0 de 8 |
| `redteam.defesa_injecao_documento` | 100% [65–100%] (7/7) | 7 de 7 |
| `redteam.cat_injecao_fala` | 0% [0–39%] (0/6) | 0 de 6 |
| `redteam.defesa_injecao_fala` | 100% [51–100%] (4/4) | 4 de 4 |
| `redteam.cat_pii` | 0% [0–43%] (0/5) | 0 de 5 |
| `redteam.cat_pressao_social` | 0% [0–18%] (0/17) | 0 de 17 |
| `redteam.defesa_pressao_social` | 100% [77–100%] (13/13) | 13 de 13 |
| `redteam.cat_ruido` | 0% [0–28%] (0/10) | 0 de 10 |
| `redteam.cat_semantica` | 0% [0–39%] (0/6) | 0 de 6 |
| `redteam.cego_n_casos` | 40 |  |
| `redteam.cego_n_ataques` | 30 |  |
| `redteam.cego_ataques` | 20% [10–37%] (6/30) | 6 de 30 |
| `redteam.cego_ataques_sem_semicega` | 23% [11–42%] (6/26) | 6 de 26 |
| `redteam.cego_overblocking` | 0% [0–28%] (0/10) | 0 de 10 |
| `redteam.cego_sem_llm_ataques` | 17% [7–34%] (5/30) | 5 de 30 |
| `redteam.cego_sem_llm_ataques_sem_semicega` | 19% [9–38%] (5/26) | 5 de 26 |
| `redteam.cego_sem_llm_overblocking` | 0% [0–28%] (0/10) | 0 de 10 |
| `ab1.pares` | 42 |  |
| `ab1.checklist` | 100% [92–100%] (42/42) | 42 de 42 |
| `ab1.agente` | 100% [92–100%] (42/42) | 42 de 42 |
| `ab1.turnos_checklist` | 10,4 |  |
| `ab1.turnos_agente` | 10,9 |  |
| `ab2.n` | 36 |  |
| `ab2.formulario` | 42% [27–58%] (15/36) | 15 de 36 |
| `ab2.so_fotos` | 44% [30–60%] (16/36) | 16 de 36 |
| `ab2.residual` | 97% [86–100%] (35/36) | 35 de 36 |
| `ab2.formulario_sem_registro` | 78% [62–88%] (28/36) | 28 de 36 |
| `ab2.residual_sem_registro` | 97% [86–100%] (35/36) | 35 de 36 |
| `ab2.pares` | 21 × 1 |  |
| `ab2.mcnemar` | p < 0,0001 |  |
| `ab2.pares_sem_registro` | 8 × 1 |  |
| `ab2.mcnemar_sem_registro` | p = 0,039 |  |
| `ab2.tempo_formulario` | 216 s |  |
| `ab2.tempo_so_fotos` | 24 s |  |
| `ab2.tempo_residual` | 37 s |  |
| `ab2.toques_formulario` | 314 |  |
| `ab2.toques_residual` | 19 |  |
| `ab2.aceitos_errados_formulario` | 1% [1–2%] (13/1399) | 13 de 1399 |
| `ab2.aceitos_errados_residual` | 0% [0–0%] (0/1399) | 0 de 1399 |
| `ab2.residual_completo` | 93% [81–97%] (38/41) | 38 de 41 |
| `ab2.documentos_com_residual` | 41 |  |
| `ab2.fala_llm` | 99% [93–100%] (71/72) | 71 de 72 |
| `ab2.fala_regras` | 72% [61–81%] (52/72) | 52 de 72 |
| `ab2.leitura_campos` | 5.025 |  |
| `ab2.leitura_precisao_aceitos` | 100% [99–100%] (3904/3916) | 3904 de 3916 |
| `ab2.leitura_aceitos_errados` | 12 |  |
| `ab2.leitura_erros_crus` | 340 |  |
| `ab2.leitura_barrados` | 278 |  |
| `ab2.replicas` | 49 |  |
| `ab2.media_formulario` | 37,6% |  |
| `ab2.media_residual` | 91,3% |  |
| `ab2.media_formulario_sem_registro` | 77,6% |  |
| `ab2.foto_ruim_residual` | 80,6% |  |
| `ab2_teste.n` | 24 |  |
| `ab2_teste.residual` | 71% [51–85%] (17/24) | 17 de 24 |
| `ab2_teste.formulario` | 58% [39–76%] (14/24) | 14 de 24 |
| `ab2_teste.so_fotos` | 29% [15–49%] (7/24) | 7 de 24 |
| `ab2_teste.residual_sem_registro` | 79% [60–91%] (19/24) | 19 de 24 |
| `ab2_teste.formulario_sem_registro` | 88% [69–96%] (21/24) | 21 de 24 |
| `ab2_teste.pares` | 6 × 3 |  |
| `ab2_teste.mcnemar` | p = 0,5078 |  |
| `ab2_teste.pares_sem_registro` | 2 × 4 |  |
| `ab2_teste.mcnemar_sem_registro` | p = 0,6875 |  |
| `ab2_teste.tempo_residual` | 35 s |  |
| `ab2_teste.tempo_formulario` | 215 s |  |
| `ab2_teste.tempo_maquina_residual` | 48 s |  |
| `ab2_teste.toques_residual` | 12 |  |
| `ab2_teste.toques_formulario` | 304 |  |
| `ab2_teste.aceitos_errados_residual` | 0% [0–1%] (3/920) | 3 de 920 |
| `ab2_teste.aceitos_errados_formulario` | 1% [0–2%] (8/920) | 8 de 920 |
| `ab2_teste.fala_llm` | 87% [74–94%] (40/46) | 40 de 46 |
| `ab2_teste.fala_regras` | 70% [55–81%] (32/46) | 32 de 46 |
| `ab2_teste.fala_narracoes_llm` | 75% [55–88%] (18/24) | 18 de 24 |
| `ab2_teste.fala_narracoes_regras` | 46% [28–65%] (11/24) | 11 de 24 |
| `ab2_teste.espurias_llm` | 1 |  |
| `ab2_teste.espurias_regras` | 0 |  |
| `ab2_teste.leitura_campos` | 3.336 |  |
| `ab2_teste.leitura_precisao_aceitos` | 100% [99–100%] (2533/2541) | 2533 de 2541 |
| `ab2_teste.leitura_aceitos_errados` | 8 |  |
| `ab2_teste.leitura_erros_crus` | 225 |  |
| `ab2_teste.leitura_barrados` | 193 |  |
| `ab2_teste.residual_completo` | 97% [84–99%] (31/32) | 31 de 32 |
| `ab2_teste.conciliacao_oraculo_residual` | 88% [69–96%] (21/24) | 21 de 24 |
| `ab2_teste.conciliacao_oraculo_formulario` | 88% [69–96%] (21/24) | 21 de 24 |
| `ab2_teste.media_formulario` | 49,0% |  |
| `ab2_teste.media_formulario_sem_registro` | 78,8% |  |
| `ab2_teste.media_residual` | 69,4% |  |
| `ab2_teste.media_residual_sem_registro` | 77,6% |  |
| `versao.sha256_src` | 1154df4aceffbf20 |  |
| `versao.sufixo` | r4 |  |
| `versao.sha256_src_lf` | 02d050f4267708c9 |  |
| `custo.tokens_entrada` | 135.349 |  |
| `custo.tokens_entrada_mil` | 135 mil |  |
| `custo.tokens_saida` | 1.038 |  |
| `custo.chamadas_llm` | 21 |  |
| `custo.local_rs` | R$ 0,0035 |  |
| `custo.nuvem_min_rs` | R$ 0,04 |  |
| `custo.nuvem_max_rs` | R$ 0,28 |  |
| `custo.nuvem_min_centavos` | 4 |  |
| `custo.nuvem_max_centavos` | 28 |  |
| `r41.equivalencia_iguais` | 6/6 |  |
| `r41.sha256_src` | 52be6b825037b28f |  |
| `r41.v3_regressao_sem_llm_ataques` | 3% [1–17%] (1/30) | 1 de 30 |
| `r41.v3_regressao_sem_llm_ataques_sem_semicega` | 4% [1–19%] (1/26) | 1 de 26 |
| `r41.v3_regressao_sem_llm_overblocking` | 0% [0–28%] (0/10) | 0 de 10 |
| `desc.total` | 15.954 |  |
| `desc.ano_2025` | 4.075 |  |
| `desc.ano_2026` | 4.599 |  |
| `desc.ate` | 13/10/2026 |  |
| `desc.motivo013_2025` | 349 |  |
| `desc.motivo013_2026` | 368 |  |
| `desc.br_motivo013_2024_2026` | 7,8% [7,4–8,3%] (965/12.343) | 965 de 12.343 |
| `desc.go_registros_2024_2026` | 565 |  |
| `desc.go_motivo013_2024_2026` | 14,5% [11,8–17,7%] (82/565) | 82 de 565 |
| `desc.go_custeio_aquisicao_2024_2026` | 158 |  |
| `desc.go_custeio_aquisicao_valor` | 169,5 mi |  |
| `desc.taxa_custeio_aquisicao` | 5,2‰ [5,0–5,4] (2.220/429.011) | 5,2 a cada mil operações |
| `desc.taxa_investimento_aquisicao` | 0,6‰ [0,6–0,7] (621/988.708) | 0,6 a cada mil operações |
| `desc.taxa_media` | 1,4‰ [1,4–1,4] (7.532/5.425.438) | 1,4 a cada mil operações |
| `desc.razao_custeio_media` | 3,7 vezes |  |
| `desc.razao_custeio_demais` | 4,9 [4,6–5,1] |  |
| `desc.razao_investimento_demais` | 0,40 [0,37–0,44] |  |
| `desc.custeio_aquisicao_registros_por_mil_min` | 4,4 |  |
| `desc.custeio_aquisicao_registros_por_mil_max` | 6,9 |  |
| `desc.investimento_aquisicao_registros_por_mil_min` | 0,6 |  |
| `desc.investimento_aquisicao_registros_por_mil_max` | 0,8 |  |
| `desc.part_pecuaria_operacoes` | 54,1% [54,0–54,1%] (2.933.448/5.425.438) | 2.933.448 de 5.425.438 |
| `desc.part_pecuaria_registros` | 58,3% [57,4–59,1%] (7.191/12.343) | 7.191 de 12.343 |
| `desc.part_pecuaria_desclassificadas` | 57,8% [56,7–58,9%] (4.352/7.532) | 4.352 de 7.532 |
| `desc.part_aquisicao_animais_operacoes` | 26,1% [26,1–26,2%] (1.417.719/5.425.438) | 1.417.719 de 5.425.438 |
| `desc.part_aquisicao_animais_registros` | 33,6% [32,8–34,5%] (4.153/12.343) | 4.153 de 12.343 |
| `desc.part_aquisicao_animais_desclassificadas` | 37,7% [36,6–38,8%] (2.841/7.532) | 2.841 de 7.532 |
| `desc.serie_2021` | 498 |  |
| `desc.serie_2022` | 118 |  |
| `desc.serie_2023` | 1.102 |  |
| `desc.pct_motivo999_2024` | 64% |  |
| `desc.pct_motivo999_2026` | 29% |  |
| `desc.memorando.total` | 15.902 |  |
| `desc.memorando.ano_2025` | 4.072 |  |
| `desc.memorando.ano_2026` | 4.553 |  |
| `desc.memorando.ate` | 06/10/2026 |  |
| `desc.memorando.motivo013_2025` | 349 |  |
| `desc.memorando.motivo013_2026` | 364 |  |
| `desc.memorando.br_motivo013_2024_2026` | 7,8% [7,4–8,3%] (961/12.293) | 961 de 12.293 |
| `desc.memorando.go_registros_2024_2026` | 564 |  |
| `desc.memorando.go_motivo013_2024_2026` | 14,5% [11,9–17,7%] (82/564) | 82 de 564 |
| `desc.memorando.go_custeio_aquisicao_2024_2026` | 158 |  |
| `desc.memorando.go_custeio_aquisicao_valor` | 169,5 mi |  |
| `desc.memorando.taxa_custeio_aquisicao` | 5,2‰ [5,0–5,4] (2.216/429.011) | 5,2 a cada mil operações |
| `desc.memorando.taxa_investimento_aquisicao` | 0,6‰ [0,6–0,7] (618/988.708) | 0,6 a cada mil operações |
| `desc.memorando.taxa_media` | 1,4‰ [1,4–1,4] (7.514/5.425.438) | 1,4 a cada mil operações |
| `desc.memorando.razao_custeio_media` | 3,7 vezes |  |
| `desc.memorando.razao_custeio_demais` | 4,9 [4,6–5,1] |  |
| `desc.memorando.razao_investimento_demais` | 0,40 [0,37–0,44] |  |
| `desc.memorando.custeio_aquisicao_registros_por_mil_min` | 4,4 |  |
| `desc.memorando.custeio_aquisicao_registros_por_mil_max` | 6,9 |  |
| `desc.memorando.investimento_aquisicao_registros_por_mil_min` | 0,6 |  |
| `desc.memorando.investimento_aquisicao_registros_por_mil_max` | 0,8 |  |
| `desc.memorando.part_pecuaria_operacoes` | 54,1% [54,0–54,1%] (2.933.448/5.425.438) | 2.933.448 de 5.425.438 |
| `desc.memorando.part_pecuaria_registros` | 58,3% [57,4–59,2%] (7.168/12.293) | 7.168 de 12.293 |
| `desc.memorando.part_pecuaria_desclassificadas` | 57,7% [56,6–58,9%] (4.339/7.514) | 4.339 de 7.514 |
| `desc.memorando.part_aquisicao_animais_operacoes` | 26,1% [26,1–26,2%] (1.417.719/5.425.438) | 1.417.719 de 5.425.438 |
| `desc.memorando.part_aquisicao_animais_registros` | 33,7% [32,8–34,5%] (4.140/12.293) | 4.140 de 12.293 |
| `desc.memorando.part_aquisicao_animais_desclassificadas` | 37,7% [36,6–38,8%] (2.834/7.514) | 2.834 de 7.514 |
| `desc.memorando.serie_2021` | 498 |  |
| `desc.memorando.serie_2022` | 116 |  |
| `desc.memorando.serie_2023` | 1.102 |  |
| `desc.memorando.pct_motivo999_2024` | 64% |  |
| `desc.memorando.pct_motivo999_2026` | 29% |  |
| `desc.fonte_last_modified` | 14/10/2026 |  |
| `desc.fonte_sha256` | 99773830eb187f7b |  |
| `retro.passou_limiar` | não |  |
| `retro.lift` | 1,33 [1,23–1,43] |  |
| `retro.captura` | 13,3% [12,3–14,3%] |  |
| `retro.auc` | 0,56 [0,55–0,57] |  |
| `retro.lift_so_valor` | 2,03 [1,90–2,18] |  |
| `retro.lift_aleatorio` | 1,00 [0,85–1,14] |  |
| `retro.diferenca_regras_valor` | -0,70 [-0,85–-0,54] |  |
| `retro.n_operacoes` | 1.241.271 |  |
| `retro.n_positivos` | 2.926 |  |
| `retro.protocolo_sha256` | e48cf6edbecc2656 |  |

Fontes:

- `agente`: `eval/reports/2026-10-16_agente_r4.json`
- `deterministico`: `eval/reports/2026-10-16_deterministico_r4.json`
- `redteam_agente`: `eval/reports/2026-10-16_redteam_agente_r4.json`
- `redteam_deterministico`: `eval/reports/2026-10-16_redteam_deterministico_r4.json`
- `ab_centralidade`: `eval/reports/2026-10-16_ab_centralidade_r4.json`
- `ab_centralidade_v2`: `eval/reports/2026-10-16_ab_centralidade_v2_r4.json`
- `agente_rep`: `eval/reports/2026-10-16_agente_r4_rep.json`
- `redteam_agente_cego`: `eval/reports/2026-10-16_redteam_agente_r4_v3cego.json`
- `redteam_deterministico_cego`: `eval/reports/2026-10-16_redteam_deterministico_r4_v3cego.json`
- `ab_centralidade_v2_teste`: `eval/reports/2026-10-16_ab_centralidade_v2_r4_teste.json`
- `r41_v3_regressao`: `eval/reports/2026-10-16_redteam_deterministico_r4.1_v3regressao.json`
- `desclassificacao`: `bench/desclassificacao/resumo.json`
- `retroteste`: `eval/retroteste/resultado.json`
- custo: `eval/reports/2026-10-16_custo_demo.json` (trace da demo `fis_demo_0001`; tokens medidos; preço de nuvem e energia são estimativa, ver `scripts/custo_fiscalizacao.py`)

Uso nos textos: `<!--n:recall_teste.falado-->9 de 9<!--/n-->`. Variantes de proporção: `fmt`, `valor`, `ic`, `valor_ic`, `kn`, `k`, `n`, `falado`; de número: `valor`.
