# Ativos da demo com ferramentas reais

A demo do caso `DEMO-0001` (linha de comando com 19 passos e interface web em replay) usa o vídeo do lote e
a série do satélite da gleba. Os dois ficam em `dados_locais/`, que é local e fica fora do git. Esta pasta
guarda uma cópia versionada deles, para que um clone novo rode a demo sem rede:

```bash
python scripts/preparar_demo.py            # copia para dados_locais/ e baixa o detector YOLOX (sha256)
python scripts/preparar_demo.py --conferir # só confere
```

O `scripts/instalar.sh` (ou `scripts/instalar.ps1`) e a imagem Docker já rodam o preparo. Cada arquivo tem o
sha256 e o destino em [`manifesto.json`](manifesto.json); o `.gitattributes` desta pasta guarda tudo byte a
byte. Aqui os nomes são curtos, porque um clone no Windows tem limite de 260 caracteres no caminho.

| Arquivo (em `demo/`) | Vai para | O que é | Licença e atribuição |
|---|---|---|---|
| `video/s03_fila_colada.mp4` (1,2 MB) | `dados_locais/videos/sinteticos/s03_fila_colada.mp4` | vídeo semissintético de corredor do curral: 15 bovinos em fila, 17,3 s; o sha256 é o que o `caso.yaml` do `DEMO-0001` registra | **CC BY-SA 4.0**, obra derivada de "Cows at Dharmasthala (2025) 01.webm" (Gpkp, CC BY-SA 4.0) e "Herding the cows video.webm" (Marie Nouvellon, CC BY 2.0), do Wikimedia Commons |
| `ndvi/stac_dda9cb9b2585de90.json` e `ndvi/AAAA-MM-DD.json` (13 arquivos, 66 kB) | `dados_locais/ndvi_cache/stac/` e `dados_locais/ndvi_cache/22LFH/AAAA-MM-DD/`, com o nome que a ferramenta de NDVI procura | lista de cenas do catálogo STAC e estatísticas de NDVI por data (p10, p50 e p90, fração limpa) da gleba da demo, de 16/03 a 08/10/2026 | Sentinel Data Legal Notice (acesso livre e aberto). "Contém dados Copernicus Sentinel modificados (2026)" |
| `contagem/<chave>/` (envelope e 4 quadros-chave, 390 kB) | `dados_locais/cache_contagem/<chave>/` | resultado da contagem do YOLOX para o vídeo da demo, o mesmo da gravação do replay: a demo pública lê daqui, porque o YOLOX em outra CPU pode contar diferente e tirar os passos seguintes da gravação | CC BY-SA 4.0, como o vídeo |

O que **não** está aqui: o detector `yolox_m.onnx` (~100 MB, Apache-2.0). Ele é baixado da release oficial do
YOLOX no GitHub e conferido pelo sha256 de `src/laudo/vision/modelos.py`.

Como os ativos foram gerados (para refazer, na máquina com os vídeos do Commons e rede):

- vídeo: `eval/golden/visao/gerar_semissintetico.py` (semente 20261008), depois de
  `scripts/baixar_videos_teste.py --contato <seu e-mail>`; detalhes em `eval/golden/visao/RESULTADOS.md`;
- satélite: a ferramenta `serie_ndvi` grava o cache na primeira execução com rede (~40 MB de COGs lidos por
  janela, ~40 s). Com o cache, a série sai igual à do laudo de exemplo e a demo roda sem rede. Para consultar
  o catálogo de novo, apague a pasta ou use `LAUDO_STAC_SEM_CACHE=1`.

Para refazer esta pasta a partir do `dados_locais/` de uma máquina que já rodou a demo com rede:
`python scripts/preparar_demo.py --gerar-manifesto` (copia os arquivos com os nomes curtos e regrava o
manifesto).
