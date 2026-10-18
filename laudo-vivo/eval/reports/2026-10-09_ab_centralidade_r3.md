# A/B de centralidade — checklist sem LLM × agente (2026-10-09)

- 14 casos válidos do split dev × perfis P1, P2, P3 = 42 pares; LLM do agente: qwen3.5:4b; tempo total 1083 s; `sha256(src/)=c297955f9b44ad37…`.
- Gerado por `scripts/py.sh eval/ab_centralidade/run_ab.py --sufixo _r3 --manter-modelo`. Fiscal simulado: `eval/ab_centralidade/fiscal_simulado.py` (perfis: P1 foto fora da gleba; P2 + esquece a GTA; P3 + vídeo ruim).

| Medida | Checklist (sem LLM) | Agente |
|---|---|---|
| **Saiu da fazenda com evidência suficiente** | 100% [92–100%] (42/42) | 100% [92–100%] (42/42) |
| Saiu com pendência (precisaria voltar) | 0% [0–8%] (0/42) | 0% [0–8%] (0/42) |
| Pendências nunca pedidas ao fiscal | 0 | 0 |
| Pedido de correção logo após erro do fiscal | 100% [96–100%] (84/84) | 99% [94–100%] (83/84) |
| Turnos até ficar suficiente (mediana) | 8,0 | 9,0 |
| Turnos por episódio (média) | 10,4 | 10,9 |
| Turnos ociosos — fiscal sem saber o que fazer (média) | 1,0 | 1,1 |
| Tempo de máquina por episódio, mediana (s) | 0,2 | 25,1 |
| Latência por turno p95 (s) | 0,03 | 3,50 |
| Campos que ficaram faltando | {} | {} |

Suficiência por perfil: checklist: P1 1,00 [0,78–1,00] (14/14), P2 1,00 [0,78–1,00] (14/14), P3 1,00 [0,78–1,00] (14/14); agente: P1 1,00 [0,78–1,00] (14/14), P2 1,00 [0,78–1,00] (14/14), P3 1,00 [0,78–1,00] (14/14)

Pareado (mesmo caso e perfil): só o agente suficiente em 0, só o checklist em 0; McNemar exato p = n/d.

