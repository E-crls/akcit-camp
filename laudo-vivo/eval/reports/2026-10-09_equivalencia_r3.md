# Equivalência do código atual com a rodada r3 (09/10/2026 05:08)

- Referência: relatórios `2026-10-09_*_r3`, `sha256(src/)=c297955f9b44ad37…`
- Código atual: `sha256(src/)=a88445406cdd09a3…`
- O que mudou: sal da instalacao movido para dados_locais/config (sem efeito em metricas)
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
