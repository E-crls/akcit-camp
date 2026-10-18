# Retro-teste pré-registrado da triagem: relatório

*Gerado por `eval/retroteste/rodar.py` em 2026-10-16T01:47:07-03:00. Protocolo: `eval/retroteste/PROTOCOLO.md` (sha256 `e48cf6edbecc2656…`, registrado em 2026-10-16T01:06:42-0300). Publicado qualquer que seja o resultado.*

> O rótulo é **desclassificação registrada** no Sicor, que depende de a IF ter fiscalizado e registrado. Não é previsão de ilícito, e nenhuma operação é rotulada. Os números são agregados.

## Resultado da análise primária

Escopo BR, insumos de cadastro, rótulo A (qualquer motivo), coortes 2022–2024, top 10% escolhido dentro de cada IF em cada coorte: **lift@10% = 1,33 [1,23–1,43]**, captura@10% = 13,3% [12,3%–14,3%], AUC = 0,56 [0,55–0,57]; 1.241.271 operações, 2.926 com desclassificação.

**Limiar de palco (IC95 inferior do lift > 1,5): NÃO PASSOU.** Linha de base "só valor" na mesma análise: lift 2,03 [1,90–2,18]; diferença pareada regras − valor: -0,70 [-0,85–-0,54]. Amostra aleatória: lift 1,00 [0,85–1,14].

Não passou no limiar pré-registrado: nada do retro-teste vai ao palco. No Q&A: "fizemos um retro-teste pré-registrado; não passou no limiar que fixamos; o relatório está publicado".

## Escopo BR

| Coorte | Operações | Rótulo A | Taxa A (por mil) | Rótulo B | Taxa B (por mil) |
|---|---:|---:|---|---:|---|
| 2022 | 378.696 | 1.132 | 2,99 [2,82–3,17] | 150 | 0,40 [0,34–0,46] |
| 2023 | 413.896 | 864 | 2,09 [1,95–2,23] | 258 | 0,62 [0,55–0,70] |
| 2024 (limite inferior) | 448.679 | 930 | 2,07 [1,94–2,21] | 201 | 0,45 [0,39–0,51] |

- Insumos `cadastro`: 21,0% das operações com algum ponto; distribuição {'0': 980377, '1': 120242, '2': 103513, '3': 35858, '4': 1281}; motivos {'LOTACAO_ALTA': 243135, 'VALOR_CABECA_ATIPICO': 22605}.

| Pontuação | Estratificação | Rótulo | Lift@10% [IC95] | Captura@10% [IC95] | AUC [IC95] |
|---|---|---|---|---|---|
| regras_cadastro | coorte_if | A | 1,33 [1,23–1,43] | 13,3% [12,3%–14,3%] | 0,56 [0,55–0,57] |
| regras_cadastro | coorte_if | B | 1,70 [1,47–1,94] | 17,0% [14,7%–19,4%] | 0,60 [0,57–0,63] |
| regras_cadastro | coorte | A | 1,68 [1,56–1,81] | 16,8% [15,6%–18,1%] | 0,58 [0,57–0,59] |
| regras_cadastro | coorte | B | 2,51 [2,21–2,83] | 25,1% [22,1%–28,3%] | 0,63 [0,62–0,66] |
| regras_cadastro | coorte_if_tipo | A | 1,39 [1,29–1,48] | 13,9% [12,9%–14,8%] | 0,56 [0,55–0,58] |
| regras_cadastro | coorte_if_tipo | B | 1,71 [1,50–1,94] | 17,1% [15,0%–19,4%] | 0,60 [0,57–0,63] |
| so_valor | coorte_if | A | 2,03 [1,90–2,18] | 20,3% [19,0%–21,8%] | 0,66 [0,65–0,68] |
| so_valor | coorte_if | B | 2,96 [2,65–3,34] | 29,6% [26,5%–33,4%] | 0,78 [0,75–0,81] |
| so_valor | coorte | A | 3,82 [3,66–4,00] | 38,2% [36,6%–40,0%] | 0,83 [0,82–0,83] |
| so_valor | coorte | B | 5,03 [4,60–5,42] | 50,3% [46,0%–54,2%] | 0,85 [0,83–0,86] |
| so_valor | coorte_if_tipo | A | 2,05 [1,91–2,20] | 20,5% [19,1%–22,0%] | 0,69 [0,67–0,70] |
| so_valor | coorte_if_tipo | B | 3,02 [2,69–3,37] | 30,2% [26,9%–33,7%] | 0,79 [0,76–0,82] |
| aleatorio | - | A | 1,00 [0,85–1,14] | 10,0% [8,5%–11,5%] | n/d |
| aleatorio | - | B | 1,00 [0,68–1,35] | 10,0% [6,8%–13,5%] | n/d |

Por coorte (estratificação coorte×IF, rótulo A):

| Pontuação | 2022 | 2023 | 2024 (limite inferior) |
|---|---|---|---|
| regras_cadastro | 1,22 [1,05–1,41] | 1,42 [1,22–1,60] | 1,39 [1,23–1,56] |
| so_valor | 1,79 [1,57–2,01] | 2,56 [2,28–2,85] | 1,83 [1,60–2,08] |
| aleatorio | 1,00 [0,76–1,23] | 1,00 [0,74–1,28] | 1,00 [0,73–1,30] |

Dentro de cada IF (rótulo A, IFs com pelo menos 20 positivos; anonimizadas por tamanho da população):

| IF | Segmento | Operações | Positivos | Lift regras | AUC regras | Lift só valor |
|---|---|---:|---:|---|---|---|
| IF-01 | BANCO PÚBLICO | 667.522 | 89 | 2,81 [1,95–3,69] | 0,60 [0,55–0,65] | 9,33 [8,75–9,78] |
| IF-02 | BANCO PÚBLICO | 277.800 | 1229 | 1,48 [1,30–1,64] | 0,56 [0,54–0,57] | 1,86 [1,65–2,07] |
| IF-03 | BANCO PRIVADO | 40.651 | 110 | 1,15 [0,81–1,55] | 0,50 [0,44–0,55] | 1,00 [0,50–1,63] |
| IF-04 | BANCO PÚBLICO | 26.080 | 1025 | 1,20 [1,02–1,36] | 0,52 [0,51–0,54] | 1,80 [1,56–2,01] |
| IF-05 | BANCO COOPERATIVO | 22.216 | 43 | 0,45 [0,00–1,14] | 0,47 [0,40–0,55] | 1,22 [0,35–2,25] |
| IF-07 | BANCO PÚBLICO | 10.201 | 31 | 1,17 [0,17–2,36] | 0,51 [0,45–0,58] | 2,26 [0,88–3,75] |
| IF-11 | COOPERATIVA DE CRÉDITO | 4.175 | 44 | 1,09 [0,84–1,56] | 0,51 [0,49–0,54] | 2,76 [1,54–4,27] |
| IF-15 | COOPERATIVA DE CRÉDITO | 3.254 | 31 | 0,25 [0,00–0,54] | 0,35 [0,27–0,42] | 0,32 [0,00–1,03] |
| IF-51 | COOPERATIVA DE CRÉDITO | 1.136 | 34 | 1,98 [0,86–3,17] | 0,57 [0,47–0,66] | 2,21 [0,88–3,81] |

## Escopo GO

| Coorte | Operações | Rótulo A | Taxa A (por mil) | Rótulo B | Taxa B (por mil) |
|---|---:|---:|---|---:|---|
| 2022 | 17.334 | 64 | 3,69 [2,89–4,71] | 3 | 0,17 [0,06–0,51] |
| 2023 | 18.642 | 65 | 3,49 [2,74–4,44] | 13 | 0,70 [0,41–1,19] |
| 2024 (limite inferior) | 19.776 | 42 | 2,12 [1,57–2,87] | 7 | 0,35 [0,17–0,73] |

- Insumos `cadastro`: 34,0% das operações com algum ponto; distribuição {'0': 36809, '1': 10765, '2': 7048, '3': 1091, '4': 39}; motivos {'LOTACAO_ALTA': 18113, 'VALOR_CABECA_ATIPICO': 1097}.
- Insumos `geo`: 40,6% das operações com algum ponto; distribuição {'0': 33127, '1': 10476, '2': 9532, '3': 1874, '4': 540, '5': 171, '6': 28, '7': 4}; motivos {'LOTACAO_ALTA': 18113, 'SOBREPOSICAO_GLEBAS': 4996, 'VALOR_CABECA_ATIPICO': 1097, 'AREA_DIVERGENTE': 36}.

| Pontuação | Estratificação | Rótulo | Lift@10% [IC95] | Captura@10% [IC95] | AUC [IC95] |
|---|---|---|---|---|---|
| regras_cadastro | coorte_if | A | 1,11 [0,79–1,44] | 11,1% [7,9%–14,4%] | 0,53 [0,47–0,58] |
| regras_cadastro | coorte_if | B | 0,52 [0,10–0,98] | 5,2% [1,0%–9,8%] | 0,51 [0,40–0,63] |
| regras_cadastro | coorte | A | 0,67 [0,37–1,00] | 6,7% [3,7%–10,0%] | 0,50 [0,46–0,53] |
| regras_cadastro | coorte | B | 0,60 [0,00–1,67] | 6,0% [0,0%–16,7%] | 0,48 [0,39–0,57] |
| regras_cadastro | coorte_if_tipo | A | 1,13 [0,82–1,47] | 11,3% [8,2%–14,7%] | 0,53 [0,48–0,58] |
| regras_cadastro | coorte_if_tipo | B | 0,46 [0,12–0,97] | 4,6% [1,2%–9,7%] | 0,50 [0,39–0,62] |
| regras_geo | coorte_if | A | 1,06 [0,74–1,43] | 10,6% [7,4%–14,3%] | 0,52 [0,47–0,59] |
| regras_geo | coorte_if | B | 0,72 [0,10–1,51] | 7,2% [1,0%–15,1%] | 0,46 [0,36–0,56] |
| regras_geo | coorte | A | 0,55 [0,30–0,83] | 5,5% [3,0%–8,3%] | 0,48 [0,44–0,51] |
| regras_geo | coorte | B | 0,54 [0,00–1,58] | 5,4% [0,0%–15,8%] | 0,46 [0,38–0,56] |
| regras_geo | coorte_if_tipo | A | 1,16 [0,83–1,55] | 11,6% [8,3%–15,5%] | 0,53 [0,48–0,59] |
| regras_geo | coorte_if_tipo | B | 0,66 [0,14–1,48] | 6,6% [1,4%–14,8%] | 0,46 [0,36–0,57] |
| so_valor | coorte_if | A | 2,04 [1,42–2,58] | 20,4% [14,2%–25,8%] | 0,62 [0,54–0,69] |
| so_valor | coorte_if | B | 0,78 [0,00–2,14] | 7,8% [0,0%–21,4%] | 0,45 [0,25–0,65] |
| so_valor | coorte | A | 3,86 [3,17–4,57] | 38,6% [31,7%–45,7%] | 0,73 [0,68–0,77] |
| so_valor | coorte | B | 1,30 [0,00–2,92] | 13,0% [0,0%–29,2%] | 0,53 [0,38–0,67] |
| so_valor | coorte_if_tipo | A | 2,29 [1,65–2,88] | 22,9% [16,5%–28,8%] | 0,62 [0,55–0,69] |
| so_valor | coorte_if_tipo | B | 0,61 [0,03–2,00] | 6,1% [0,3%–20,0%] | 0,45 [0,24–0,66] |
| aleatorio | - | A | 1,00 [0,45–1,67] | 10,0% [4,5%–16,6%] | n/d |
| aleatorio | - | B | 1,00 [0,00–3,13] | 10,0% [0,0%–30,8%] | n/d |

Por coorte (estratificação coorte×IF, rótulo A):

| Pontuação | 2022 | 2023 | 2024 (limite inferior) |
|---|---|---|---|
| regras_cadastro | 1,24 [0,64–1,97] | 0,95 [0,56–1,41] | 1,14 [0,62–1,62] |
| regras_geo | 1,13 [0,51–1,82] | 0,99 [0,54–1,61] | 1,07 [0,47–1,70] |
| so_valor | 1,59 [0,76–2,50] | 2,83 [1,67–3,81] | 1,48 [0,59–2,58] |
| aleatorio | 1,00 [0,15–2,14] | 1,00 [0,15–2,15] | 1,00 [0,00–2,60] |

Dentro de cada IF (rótulo A, IFs com pelo menos 20 positivos; anonimizadas por tamanho da população):

| IF | Segmento | Operações | Positivos | Lift regras | AUC regras | Lift só valor |
|---|---|---:|---:|---|---|---|
| IF-01 | BANCO PÚBLICO | 36.726 | 42 | 0,68 [0,26–1,15] | 0,53 [0,46–0,60] | 1,19 [0,26–2,35] |
| IF-03 | BANCO PÚBLICO | 3.424 | 113 | 1,19 [0,80–1,64] | 0,54 [0,49–0,58] | 2,39 [1,61–3,04] |

## Dados e software

- `operacoes_2022`: https://www.bcb.gov.br/htms/sicor/DadosBrutos/SICOR_OPERACAO_BASICA_ESTADO_2022.gz (Last-Modified Wed, 14 Oct 2026 11:50:00 GMT; sha256 `2773d6cd24715d4e…`; 60,7 MB)
- `glebas_2022`: https://www.bcb.gov.br/htms/sicor/DadosBrutos/SICOR_GLEBAS_WKT_2022.gz (Last-Modified Wed, 14 Oct 2026 11:52:34 GMT; sha256 `467ff7bde6342c51…`; 233,8 MB)
- `operacoes_2023`: https://www.bcb.gov.br/htms/sicor/DadosBrutos/SICOR_OPERACAO_BASICA_ESTADO_2023.gz (Last-Modified Wed, 14 Oct 2026 11:50:00 GMT; sha256 `0c265ca5196a28c5…`; 65,0 MB)
- `glebas_2023`: https://www.bcb.gov.br/htms/sicor/DadosBrutos/SICOR_GLEBAS_WKT_2023.gz (Last-Modified Wed, 14 Oct 2026 11:52:37 GMT; sha256 `274cac2ccd566bae…`; 271,4 MB)
- `operacoes_2024`: https://www.bcb.gov.br/htms/sicor/DadosBrutos/SICOR_OPERACAO_BASICA_ESTADO_2024.gz (Last-Modified Wed, 14 Oct 2026 11:50:01 GMT; sha256 `d3cb92b389b70b54…`; 68,2 MB)
- `glebas_2024`: https://www.bcb.gov.br/htms/sicor/DadosBrutos/SICOR_GLEBAS_WKT_2024.gz (Last-Modified Wed, 14 Oct 2026 11:52:39 GMT; sha256 `408c4e6af85a84e9…`; 281,1 MB)
- `desclassificacao`: https://www.bcb.gov.br/htms/sicor/DadosBrutos/sicor_desclassificacao.gz (Last-Modified Wed, 14 Oct 2026 11:52:23 GMT; sha256 `99773830eb187f7b…`; 0,2 MB)

- `src/laudo/geo/triagem.py`: igual ao registrado (`509d0c5e7b65207b…`)
- `bench/fiscal_go/build.py`: igual ao registrado (`ea2d4c5ae48aee59…`)
- `src/laudo/geo/geometria.py`: igual ao registrado (`f21702bb643528bc…`)

## Desvios

- Antes desta rodada houve execuções de teste do código com 3 réplicas (01:21–01:41 de 16/10/2026; a primeira foi interrompida na preparação), já com o protocolo registrado (01:06). As estimativas pontuais não dependem do bootstrap e são as mesmas; nada no protocolo, nas regras ou nos limiares mudou depois delas. As populações pontuadas foram reaproveitadas do cache da execução de teste (mesmo software congelado).

## Como reproduzir

```bash
scripts/py.sh -I bench/desclassificacao/build.py --trabalho <pasta fora do repositório>
scripts/py.sh -I eval/retroteste/rodar.py --dados <mesma pasta>
```
