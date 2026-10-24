# Bibliotecas de terceiros da interface web

Arquivos estáticos, sem build e sem npm. Baixados em 08/10/2026.

| Biblioteca | Versão | Licença | Origem | Arquivos | sha256 |
|---|---|---|---|---|---|
| Leaflet | 1.9.4 | BSD-2-Clause (`leaflet-1.9.4/LICENSE`) | https://unpkg.com/leaflet@1.9.4/dist/ | `leaflet.js`, `leaflet.css`, `images/*.png` | `leaflet.js` db49d009c841f5ca34a888c96511ae936fd9f5533e90d8b2c4d57596f4e5641a · `leaflet.css` a7837102824184820dfa198d1ebcd109ff6d0ff9a2672a074b9a1b4d147d04c6 |

## Fonte e ícones (identidade "Esquadro", baixados em 23/10/2026)

| Item | Licença | Origem | Arquivos |
|---|---|---|---|
| Barlow, Barlow Semi Condensed e Barlow Condensed (The Barlow Project Authors) | SIL OFL 1.1 (`fonts/OFL.txt`) | Google Fonts, `fonts.gstatic.com`, subconjunto latino | `fonts/*.woff2` (7 arquivos, sem modificação) |
| Phosphor Icons 2.1.1, pesos Bold e Fill | MIT (`icones/LICENSE-phosphor.txt`) | https://unpkg.com/@phosphor-icons/core@2.1.1/assets/ | `icones/phosphor-bold/*.svg` (45), `icones/phosphor-fill/*.svg` (3) |
| Lucide 0.460.0, só o `satellite` | ISC (`icones/LICENSE-lucide.txt`) | lucide-static 0.460.0 | `icones/lucide/satellite.svg` (traço de 2,25 px no sprite) |
| Cerca, área financiada, esquadro, quadrado de "Falta", marca graduada, piquete da demonstração e favicon | licença do projeto (desenho próprio) | — | `icones/proprios/*.svg`, `../icone.svg` |

O sprite inline de `index.html` é montado por `scripts/montar_sprite_web.py` a partir desses arquivos.

sha256 das fontes: `Barlow-500` cd759df8…07a8 · `Barlow-600` 4b52ddd4…0cc3 · `Barlow-700` 2d797dd8…3289 ·
`BarlowSemiCondensed-600` f158417e…998d · `BarlowSemiCondensed-700` fb958c8c…a5cb · `BarlowCondensed-700`
3787a5a4…e2b8 · `BarlowCondensed-800` 2515494e…2b52 (completos: `sha256sum apps/web/vendor/fonts/*.woff2`).

## Dados do mapa (não vendorizados)

- **Tiles do OpenStreetMap** (`https://tile.openstreetmap.org/`), só quando há internet, com a atribuição
  "© OpenStreetMap" visível no mapa. Dados ODbL; uso leve de demonstração dentro da
  [política de tiles](https://operations.osmfoundation.org/policies/tiles/). Sem internet o mapa fica sem fundo.
- **Contorno de Goiás**: gerado pela API a partir da malha municipal do IBGE
  (`dados_locais/ibge/municipios_go.parquet`), simplificado. "Fonte: IBGE — Malha Municipal".
- **Glebas e operações**: Sicor/BCB via `bench/fiscal_go/` ("Fonte: Banco Central do Brasil — Sicor").

## Voz

- Resposta falada: Web Speech API do navegador (`speechSynthesis`), voz pt-BR do sistema. Nada é instalado.
- Reconhecimento: faster-whisper com `Systran/faster-whisper-large-v3` (MIT), do cache local, no servidor.
