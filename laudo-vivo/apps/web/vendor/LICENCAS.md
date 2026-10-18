# Bibliotecas de terceiros da interface web

Arquivos estáticos, sem build e sem npm. Baixados em 08/10/2026.

| Biblioteca | Versão | Licença | Origem | Arquivos | sha256 |
|---|---|---|---|---|---|
| Leaflet | 1.9.4 | BSD-2-Clause (`leaflet-1.9.4/LICENSE`) | https://unpkg.com/leaflet@1.9.4/dist/ | `leaflet.js`, `leaflet.css`, `images/*.png` | `leaflet.js` db49d009c841f5ca34a888c96511ae936fd9f5533e90d8b2c4d57596f4e5641a · `leaflet.css` a7837102824184820dfa198d1ebcd109ff6d0ff9a2672a074b9a1b4d147d04c6 |

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
