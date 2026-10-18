# A/B de centralidade — checklist sem LLM × agente (2026-10-16)

- 14 casos válidos do split dev × perfis P1, P2, P3 = 42 pares; LLM do agente: qwen3.5:4b; tempo total 966 s; `sha256(src/)=1154df4aceffbf20…`.
- Gerado por `scripts/py.sh eval/ab_centralidade/run_ab.py --sufixo _r4 --manter-modelo`. Fiscal simulado: `eval/ab_centralidade/fiscal_simulado.py` (perfis: P1 foto fora da gleba; P2 + esquece a GTA; P3 + vídeo ruim).
- Reprodutibilidade: `sha256(eval/)=82d544fe6b051410…`, manifesto do golden `19850e2d56708619…` (confere); LLM: `qwen3.5:4b` digest `2a654d98e6fba55d452`, Ollama 0.32.4, opções `{"temperature": 0, "seed": 42, "num_ctx": 16384}`, think=False.

| Medida | Checklist (sem LLM) | Agente |
|---|---|---|
| **Saiu da fazenda com evidência suficiente** | 100% [92–100%] (42/42) | 100% [92–100%] (42/42) |
| Saiu com pendência (precisaria voltar) | 0% [0–8%] (0/42) | 0% [0–8%] (0/42) |
| Pendências nunca pedidas ao fiscal | 0 | 0 |
| Pedido de correção logo após erro do fiscal | 100% [96–100%] (84/84) | 100% [96–100%] (84/84) |
| Turnos até ficar suficiente (mediana) | 8,0 | 9,0 |
| Turnos por episódio (média) | 10,4 | 10,9 |
| Turnos ociosos — fiscal sem saber o que fazer (média) | 1,0 | 1,0 |
| Tempo de máquina por episódio, mediana (s) | 0,2 | 23,0 |
| Latência por turno p95 (s) | 0,03 | 3,03 |
| Campos que ficaram faltando | {} | {} |

Suficiência por perfil: checklist: P1 1,00 [0,78–1,00] (14/14), P2 1,00 [0,78–1,00] (14/14), P3 1,00 [0,78–1,00] (14/14); agente: P1 1,00 [0,78–1,00] (14/14), P2 1,00 [0,78–1,00] (14/14), P3 1,00 [0,78–1,00] (14/14)

Pareado (mesmo caso e perfil): só o agente suficiente em 0, só o checklist em 0; McNemar exato p = n/d.

