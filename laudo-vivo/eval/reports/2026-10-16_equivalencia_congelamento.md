# Equivalência com a rodada r3 depois do congelamento do split (16/10/2026 01:47)

- Referência: relatórios `2026-10-09_*_r3`, `sha256(src/)=c297955f9b44ad37…`
- Código conferido: `sha256(src/)=52b82f0bf2168d4f…` (o `src/` das frentes da madrugada de 16/10, ainda em andamento: o hash final da r4 precisa de outra conferência)
- O que mudou: congelamento do split de teste em 16/10/2026; codigo das frentes da madrugada de 16/10
- Como: Executado com uma cópia de eval/conferir_equivalencia.py que grava fora do repositório, para não sobrescrever eval/reports/2026-10-09_equivalencia_r3.*, que scripts/gerar_numeros.py cita.

| Conferência | Resultado | Diferenças |
|---|---|---|
| golden set sem LLM (todas as métricas por split) | **igual** | — |
| red-team sem LLM (resumo) | **igual** | — |
| A/B v2 (leituras e alegações gravadas; tudo menos config) | **igual** | — |
| replay da demo na CLI, 19 passos com a foto do DANFE (gravado no código novo) | **igual** | — |
| replay da demo na CLI, só o XML, 17 passos (gravado em 08/10, antes das mudanças) | **igual** | — |
| contingência da interface, 19 passos pela API (gravada no código novo) | **igual** | — |

**Conclusão:** métricas sem LLM idênticas e o contexto do LLM inalterado nas gravações: os números da referência continuam valendo para o código atual; a rodada completa com o LLM fica para o congelamento.

## Histórico

- 16/10/2026 01:02, `sha256(src/)=48f0d4f925370649…`: 5 de 6 iguais; diferente: contingência da interface, 19 passos pela API (gravada no código novo). Causa: relógio: a API carimbava Evidencia.recebida_em com a hora da máquina; as fotos da cerca do DEMO-0001 têm EXIF de 08/10/2026 e passaram de 72 h, o rascunho não saía e o passo 18 (assinatura) quebrava. Corrigido por outra frente em src/laudo/api/casos.py (16/10, 01:24): o recebimento vem do caso (recebida_em do caso.yaml), como na CLI.
