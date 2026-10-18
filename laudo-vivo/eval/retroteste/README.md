# Retro-teste pré-registrado da triagem

Pergunta: a priorização de `src/laudo/geo/triagem.py`, sem retoque e só com campos de originação, põe no top 10%
de cada carteira mais operações que depois tiveram desclassificação registrada pelo BCB do que a amostra
aleatória do MCR 2-7, item 12? (memorando de 16/10/2026, seção 5A, item 6; seção 3, linha 12)

| Arquivo | O que é |
|---|---|
| [`PROTOCOLO.md`](PROTOCOLO.md) | protocolo da versão 1, escrito e com hash gravado **antes** de rodar |
| `PROTOCOLO.sha256`, `registro_protocolo.json` | sha256 (`e48cf6edbecc2656…`) e hora do registro (16/10/2026 01:06) |
| [`RELATORIO.md`](RELATORIO.md), `resultado.json` | relatório da rodada oficial (B = 1000), publicado com o resultado que deu |
| `rodar.py`, `metricas.py` | execução (confere o hash do protocolo e do software congelado) e métricas vetorizadas |

## Resultado (versão 1 do protocolo)

**Não passou no limiar de palco.** Análise primária (BR, insumos de cadastro, qualquer motivo, coortes
2022–2024, top 10% dentro de cada IF): lift@10% <!--n:retro.lift.valor_ic-->1,33 [1,23–1,43]<!--/n-->, AUC
<!--n:retro.auc.valor_ic-->0,56 [0,55–0,57]<!--/n-->, em <!--n:retro.n_operacoes-->1.241.271<!--/n--> operações
com <!--n:retro.n_positivos-->2.926<!--/n--> desclassificadas. O limiar era IC95 inferior > 1,5.

Leitura [F = do relatório; I = inferência]:

1. [F] As regras de cadastro (lotação implícita e valor por cabeça) acham **mais** desclassificações do que o
   acaso dentro de cada IF (o IC95 inteiro fica acima de 1), mas pouco: cerca de 1,3 vez a amostra aleatória.
2. [F] A linha de base "só valor" (maior valor financiado primeiro) vai melhor: lift
   <!--n:retro.lift_so_valor.valor_ic-->2,03 [1,90–2,18]<!--/n-->; diferença pareada regras − valor
   <!--n:retro.diferenca_regras_valor.valor_ic-->-0,70 [-0,85–-0,54]<!--/n-->.
3. [I] O "só valor" provavelmente mede o desenho da fiscalização, não a irregularidade: o rótulo só existe se a
   IF fiscalizou, e operações maiores tendem a ser mais fiscalizadas. É o viés de fiscalização previsto no
   protocolo; por isso o resultado não autoriza dizer que "valor prevê desclassificação".
4. [F] Em GO, nenhuma versão das regras (com ou sem glebas) se separa do acaso (lift dentro de IF de 1,06 a
   1,16, IC95 cruzando 1). A amostra é pequena (171 operações desclassificadas em 3 coortes).
5. [F] Secundárias que passariam de 1,5 (rótulo 001/013; estratificação só por coorte) não substituem a primária:
   o protocolo proíbe escolher a melhor de N, e a estratificação só por coorte mistura IFs com taxas de
   desclassificação de 0,1 a 39 por mil.

**No palco: nada do retro-teste.** No Q&A: "fizemos um retro-teste pré-registrado; não passou no limiar que
fixamos; o relatório está publicado". Para a final (memorando, seção 5B), uma versão 2 com protocolo novo pode
testar modelo contra regra e controlar o esforço de fiscalização; esta versão 1 continua publicada.

## Como reproduzir

```bash
# da raiz do repositório; o recorte vai para uma pasta fora do repositório (apague ao fim)
scripts/py.sh -I bench/desclassificacao/build.py --trabalho <pasta>   # ~8 min, ~1 GB em streaming
scripts/py.sh -I eval/retroteste/rodar.py --dados <pasta>             # ~13 min de preparo + ~5 min de bootstrap
scripts/py.sh -m pytest tests/unit/test_retroteste_metricas.py -q
```

O preparo (variáveis e pontuação) fica em cache na pasta `--dados`, sem rótulo, e só é reaproveitado com o mesmo
software congelado. Pico de RAM medido: cerca de 1,4 GB.
