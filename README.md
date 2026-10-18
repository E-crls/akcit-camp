# AKCIT Camp 2026 — Laudo Vivo

Workspace da equipe no AKCIT Camp 2026 (regional Centro-Oeste, Goiânia).

- **[`laudo-vivo/`](laudo-vivo/)** — o produto: agente de fiscalização auditável do crédito rural (MCR 2-7), com
  avaliação (`eval/`), entregáveis do regional (`docs/entregaveis/`) e documentação do fluxo do agente.
  Comece pelo [`laudo-vivo/README.md`](laudo-vivo/README.md), que abre com "Como avaliar em 10 minutos".
- [`negocio/`](negocio/) — plano de negócio, textos de inscrição, relatórios quinzenais e o [passo a passo da equipe](negocio/PASSO_A_PASSO_EQUIPE.md).
- [`DECISAO.md`](DECISAO.md) — decisão de produto.

## Rodar o produto

Tudo roda de dentro de `laudo-vivo/`, sem GPU e sem conta em serviço nenhum:

```bash
cd laudo-vivo
docker compose up --build demo     # interface web em replay: http://127.0.0.1:8000
docker compose run --rm cli        # a demo de 19 passos no terminal, até o laudo selado
```

Sem Docker, use `bash scripts/instalar.sh` (no Windows, `powershell -ExecutionPolicy Bypass -File
scripts\instalar.ps1`) e depois `make replay` e `make demo-web`. Requisitos, sistemas, modo ao vivo com o LLM
local e problemas comuns estão em [`laudo-vivo/docs/COMO_RODAR.md`](laudo-vivo/docs/COMO_RODAR.md).

Fora do git: `dados/` (dados públicos brutos, re-baixáveis), `.ferramentas/` (ambiente local) e
`dados_locais/` (leituras, logs e gravações locais). O que a demo precisa e não cabe no git (o detector YOLOX)
é baixado pelo instalador e pela imagem, com sha256 conferido.
