# Avaliação no golden set — modo agente (2026-10-16)

- Integração: `app` · LLM: qwen3.5:4b · casos: test=24 · tempo total: 517 s
- Split: `sha256_split=9e51b91272fcc1b3…`, congelado=True; hashes conferidos: ok
- Gerado por `scripts/py.sh eval/run_eval.py --modo agente --split test --final --motivo L60 repeticao do agente no teste r4 --sufixo _r4_rep --manter-modelo`; intervalos de 95% de Wilson.
- Versão avaliada: `sha256(src/)=1154df4aceffbf20…` (o repositório ainda não tem commits).
- Reprodutibilidade: `sha256(eval/)=82d544fe6b051410…`, manifesto `19850e2d56708619…` (confere); LLM: `qwen3.5:4b` digest `2a654d98e6fba55d452`, Ollama 0.32.4, opções `{"temperature": 0, "seed": 42, "num_ctx": 16384}`, think=False.
- Uso do split de teste registrado (`--final`, execução `b6bd560cd850` em `eval/golden/casos/registro_teste.jsonl`): L60 repeticao do agente no teste r4.
- Status por campo: verificador + `avaliar_regras` + política sobre as checagens das ferramentas reais. Contagem de vídeo dos casos sintéticos: saída simulada do caso (ver eval/README.md, contorno 2).

## Repetição de `2026-10-16_agente_r4.json` (L60)

- `test` (n=24): casos com algum campo do laudo diferente 0% [0–14%] (0/24); emissão diferente 0% [0–14%] (0/24); turnos com ações diferentes 0% [0–1%] (0/273); turnos com fala diferente 4% [2–7%] (10/273).
  Leitura: os status e as decisões de emissão foram os mesmos; mudaram só falas ou ações intermediárias, o que não muda nenhum número do slide (o status vem do verificador, não do LLM).

## Split `test` (n=24: {'valido': 10, 'ambiguo': 5, 'defeito': 9})

| Métrica | Valor [IC 95%] (k/n) | Meta |
|---|---|---|
| **Recall de defeito** (caso: algum campo afetado divergente/pendente) | 1,00 [0,70–1,00] (9/9) | ≥ 0,95 |
| Recall de defeito contando abstenção como detecção | 1,00 [0,70–1,00] (9/9) | — |
| Recall de defeito por campo afetado | 1,00 [0,74–1,00] (11/11) | — |
| **Falso "verificado"** (campo com rótulo não verificado) | 0% [0–19%] (0/16) | 0 |
| Casos com algum falso "verificado" | 0% [0–22%] (0/14) | 0 |
| **Over-blocking** (a) válidos com campo rotulado não verificado | 0% [0–28%] (0/10) | ≤ 10% |
| Over-blocking (b) válidos com rascunho bloqueado (qualquer pendência) | 0% [0–28%] (0/10) | ≤ 10% |
| Over-blocking (b') idem, sem contar cronograma e conclusão (exigências fora do golden) | 0% [0–28%] (0/10) | ≤ 10% |
| Válidos com "divergente" falso | 0% [0–28%] (0/10) | 0 |
| **Abstenção correta** (ambíguos: campo ambíguo pendente/abstenção) | 1,00 [0,57–1,00] (5/5) | ≥ 0,8 |
| Abstenção correta com status exato | 0,60 [0,23–0,88] (3/5) | — |
| Abstenção indevida (campos claros) | 0% [0–3%] (0/114) | ≤ 10% |
| Abstenção indevida (cenários claros) | 0% [0–17%] (0/19) | ≤ 10% |
| Acurácia seletiva (quando se compromete) | 1,00 [0,97–1,00] (114/114) | ≥ 0,9 |
| Cobertura (campos comprometidos) | 0,95 [0,90–0,98] (114/120) | — |
| Acerto exato do status (todos os campos) | 0,98 [0,94–1,00] (118/120) | — |
| Ferramentas de documento, critério fino: acerto exato | 0,98 [0,96–0,99] (352/360) | — |
| Ferramentas de documento, critério fino: falso verificado | 0% [0–13%] (0/25) | 0 |
| Ocorrência de pressão registrada (casos D12) | 1,00 [0,21–1,00] (1/1) | 1,00 |
| Ocorrência de injeção registrada (casos D13) | n/d (n=0) | 1,00 |
| **Grounding**: números sem lastro (falas entregues + laudo) | 0 (falas: 273, laudos: 24) | 0 |
| Grounding, oráculo independente do harness: falas com número sem lastro | 0% [0–1%] (0/273) | 0 |

**Agente (LLM)**

| Métrica | Valor | Meta |
|---|---|---|
| Tool call válida na 1ª tentativa (limite inferior) | 100% [90–100%] (35/35) | ≥ 95% |
| Tool call válida após reparo | 100% [90–100%] (35/35) | ≥ 99% |
| Ação correta por turno | 0,42 [0,36–0,48] (103/248) | — |
| Turnos em que o plano mínimo teve de cobrir o LLM | 148 | — |
| Ações do LLM negadas pela política (POL-01..03) | 0 | — |
| Falas do LLM entregues / descartadas por grounding (POL-05) | 216 / 0 | — |
| Latência por turno p50 / p95 (s, n=273) | 1,98 / 2,92 | p95 ≤ 6 s |
| Latência por chamada ao LLM p50 / p95 (s, n=248) | 0,90 / 1,29 | — |

Ação correta por tipo de turno: abertura 1,00 [0,86–1,00] (24/24), declaracao 1,00 [0,93–1,00] (48/48), upload 0,05 [0,02–0,09] (7/152), fala 1,00 [0,86–1,00] (24/24)

**Acerto por campo do laudo** (cobertura = comprometidos; acurácia quando se compromete)

| Campo | Cobertura | Acurácia seletiva | Acerto exato |
|---|---|---|---|
| comprovante_nfe | 0,96 [0,80–0,99] (23/24) | 1,00 [0,86–1,00] (23/23) | 1,00 [0,86–1,00] (24/24) |
| gta | 0,92 [0,74–0,98] (22/24) | 1,00 [0,85–1,00] (22/22) | 1,00 [0,86–1,00] (24/24) |
| integridade_foto | 1,00 [0,86–1,00] (24/24) | 1,00 [0,86–1,00] (24/24) | 1,00 [0,86–1,00] (24/24) |
| localizacao | 0,92 [0,74–0,98] (22/24) | 1,00 [0,85–1,00] (22/22) | 0,96 [0,80–0,99] (23/24) |
| quantidade | 0,96 [0,80–0,99] (23/24) | 1,00 [0,86–1,00] (23/23) | 0,96 [0,80–0,99] (23/24) |

Matriz rótulo→sistema (pares caso×campo): `abstencao→pendente` 1, `divergente→divergente` 10, `pendente→abstencao` 1, `pendente→pendente` 4, `verificado→verificado` 104

Curva risco-cobertura (comprometidos ordenados pela confiança): cob 57% → risco 0.0% (conf ≥ 1.00); cob 63% → risco 0.0% (conf ≥ 0.98); cob 72% → risco 0.0% (conf ≥ 0.97); cob 79% → risco 0.0% (conf ≥ 0.95); cob 85% → risco 0.0% (conf ≥ 0.93); cob 95% → risco 0.0% (conf ≥ 0.90)

