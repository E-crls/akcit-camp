# Casos de dev do perfil custeio (4) — rodada r4 (2026-10-16)

- Comando: `scripts/py.sh eval/golden/gerador/casos_publicos.py --rodar --custeio` (gerado por `eval/rodada_r4.py`, etapa `casos_publicos_custeio`)
- Versão avaliada: `sha256(src/)=1154df4aceffbf20…`; código de saída 0

```
CUS-0001: confere | bov1=verificado, comprovante_nfe=verificado, gta=verificado, lotacao=verificado, metodo_if=verificado, quantidade=verificado
CUS-0002: confere | bov1=divergente, comprovante_nfe=verificado, gta=verificado, lotacao=verificado, metodo_if=verificado, quantidade=divergente
CUS-0003: confere | bov1=divergente, comprovante_nfe=verificado, gta=divergente, lotacao=verificado, metodo_if=verificado, quantidade=verificado
CUS-0004: confere | bov1=verificado, lotacao=pendente, metodo_if=verificado, quantidade=verificado
```
