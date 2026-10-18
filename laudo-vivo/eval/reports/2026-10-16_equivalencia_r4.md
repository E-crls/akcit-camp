# Equivalência do código atual com a rodada r4 (16/10/2026 23:01)

- Referência: relatórios `2026-10-16_*_r4`, `sha256(src/)=1154df4aceffbf20…`
- Código atual: `sha256(src/)=52be6b825037b28f…`, `sha256(eval/)=1b0c120f7d3a1ab8…`; manifesto do golden `19850e2d56708619…` (ok)
- O que mudou: r4.1 (versao final, depois da revisao do P1): equivalencia apos correcoes de declaracao e PIN motivadas pelo red-team cego v3 e pela revisao; a rodada completa com o LLM fica para a r5 (o congelamento citado na conclusao padrao do script foi a r4)
- Gerado por `scripts/py.sh eval/conferir_equivalencia.py`.

| Conferência | Resultado | Diferenças |
|---|---|---|
| golden set sem LLM (todas as métricas por split) | **igual** | — |
| red-team sem LLM (resumo) | **igual** | — |
| A/B v2 (leituras e alegações gravadas; tudo menos config) | **igual** | — |
| replay da demo na CLI, 19 passos com a foto do DANFE (gravado no código novo) | **igual** | — |
| replay da demo na CLI, só o XML, 17 passos (gravado em 08/10, antes das mudanças) | **igual** | — |
| contingência da interface, 19 passos pela API (gravada no código novo) | **igual** | — |

**Conclusão:** métricas sem LLM idênticas e o contexto do LLM inalterado nas gravações: os números da referência continuam valendo para o código atual; a rodada completa com o LLM fica para o congelamento.
