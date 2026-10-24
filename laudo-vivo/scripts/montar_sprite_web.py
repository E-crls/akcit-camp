"""Monta o sprite de ícones e de marca da interface web (`apps/web/index.html`, entre os marcadores do sprite).

Os ícones vêm de `apps/web/vendor/icones/` e cada conjunto guarda a sua licença ao lado:

- `phosphor-bold/` e `phosphor-fill/`: Phosphor Icons 2.1.1 (MIT, `LICENSE-phosphor.txt`), de
  https://unpkg.com/@phosphor-icons/core@2.1.1/assets/
- `lucide/`: Lucide 0.460.0 (ISC, `LICENSE-lucide.txt`), só o `satellite`, com o traço ajustado ao peso Bold
  (2,25 px em 24)
- `proprios/`: cerca, área financiada, esquadro e o quadrado vazado de "Falta", desenhados para o produto
  (licença do projeto)

A marca (o esquadro na placa ipê, o selo grande, a marca do agente e o piquete da demonstração) é desenhada aqui.

Uso (na raiz do repositório): scripts/py.sh scripts/montar_sprite_web.py
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "apps" / "web"
ICONES = WEB / "vendor" / "icones"

# id no produto (`#i-<id>`) -> arquivo em vendor/icones
MAPA = {
    "camera": "phosphor-bold/camera",
    "video": "phosphor-bold/video-camera",
    "nota": "phosphor-bold/receipt",
    "gta": "phosphor-bold/truck",
    "arquivo": "phosphor-bold/file-code",
    "mais": "phosphor-bold/plus",
    "mic": "phosphor-bold/microphone",
    "enviar": "phosphor-bold/paper-plane-right",
    "check": "phosphor-bold/check",
    "check-cheio": "phosphor-fill/check-fat",
    "x": "phosphor-bold/x",
    "alerta": "phosphor-bold/warning",
    "diverge": "phosphor-bold/not-equals",
    "falta": "proprios/quadrado-falta",
    "sem-conclusao": "phosphor-bold/prohibit",
    "cadeado": "phosphor-bold/lock-simple",
    "cadeado-cheio": "phosphor-fill/lock-simple",
    "escudo": "phosphor-bold/shield-check",
    "escudo-cheio": "phosphor-fill/shield-check",
    "satelite": "lucide/satellite",
    "pino": "phosphor-bold/map-pin",
    "gps": "phosphor-bold/gps-fix",
    "vaca": "phosphor-bold/cow",
    "cerca": "proprios/cerca",
    "area": "proprios/area",
    "esquadro": "proprios/esquadro",
    "caneta": "phosphor-bold/note-pencil",
    "assinar": "phosphor-bold/signature",
    "baixar": "phosphor-bold/download-simple",
    "imprimir": "phosphor-bold/printer",
    "voltar": "phosphor-bold/arrow-left",
    "direita": "phosphor-bold/caret-right",
    "baixo": "phosphor-bold/caret-down",
    "info": "phosphor-bold/info",
    "codigo": "phosphor-bold/code",
    "play": "phosphor-bold/play",
    "pular": "phosphor-bold/skip-forward",
    "recomecar": "phosphor-bold/arrow-counter-clockwise",
    "lista": "phosphor-bold/list-checks",
    "mapa": "phosphor-bold/map-trifold",
    "galeria": "phosphor-bold/image",
    "relogio": "phosphor-bold/clock",
    "usuario": "phosphor-bold/user",
    "opcoes": "phosphor-bold/dots-three",
    "busca": "phosphor-bold/magnifying-glass",
    "balao": "phosphor-bold/chat-text",
    "copiar": "phosphor-bold/copy",
    "telao": "phosphor-bold/projector-screen",
    "ampliar": "phosphor-bold/arrows-out-simple",
    "regua": "phosphor-bold/ruler",
    "data": "phosphor-bold/calendar-check",
    "pacote": "phosphor-bold/package",
}

# Marca: a placa ipê com o esquadro graduado (o L de Laudo, com as marcas de régua) e a peça encaixada no canto.
# A graduação é o que faz do desenho um esquadro: ela vai em toda marca de 32 px ou mais (topo, folha do laudo, lacre).
# A versão lisa fica só abaixo de 20 px (favicon e rótulo do agente), onde a graduação some.
IPE, CARVAO = "#FFC414", "#15130F"
ESQ_P = '<path d="M13 11H26V40H53V53H13Z"/><rect x="30" y="24" width="12" height="12"/>'
# marcas de régua vazadas na borda de fora do esquadro: 3 de 64 de largura (1,7 px a 36 px), longas e curtas alternadas
ESQ_G = ('<path d="M12 10H25V41H54V54H12Z'
         'M12 15h6.5v3h-6.5ZM12 21h4v3h-4ZM12 27h6.5v3h-6.5ZM12 33h4v3h-4Z'
         'M30 54v-6.5h3v6.5ZM36 54v-4h3v4ZM42 54v-6.5h3v6.5ZM48 54v-4h3v4Z" fill-rule="evenodd"/>'
         '<rect x="29" y="25" width="12" height="12"/>')
MARCA = [
    # símbolo pequeno (abaixo de 20 px: favicon): sem graduação
    f'<symbol id="marca-p" viewBox="0 0 64 64"><rect width="64" height="64" rx="7" fill="{IPE}"/><g fill="{CARVAO}">{ESQ_P}</g></symbol>',
    # a marca (32 px ou mais: topo, folha do laudo, lacre SELADO): o esquadro graduado
    f'<symbol id="selo-g" viewBox="0 0 64 64"><rect width="64" height="64" rx="7" fill="{IPE}"/><g fill="{CARVAO}">{ESQ_G}</g></symbol>',
    # rótulo do agente (20 px): só o esquadro liso, sem rosto, sem placa, sem círculo (na cor do texto)
    f'<symbol id="agente" viewBox="8 6 50 52"><g fill="currentColor">{ESQ_P}</g></symbol>',
    # piquete do caso da demonstração no mapa: o quadrado ipê com contorno carvão e o esquadro (sem letra)
    (f'<symbol id="pino-demo" viewBox="0 0 30 30"><rect x="1.5" y="1.5" width="27" height="27" rx="2" fill="{IPE}" stroke="{CARVAO}" stroke-width="3"/>'
    f'<g fill="{CARVAO}"><path d="M8 7h4.5v11.5H23V23H8Z"/><rect x="14.5" y="11.5" width="4.5" height="4.5"/></g></symbol>'),
]


def simbolo(nome: str, arq: str) -> str:
    t = (ICONES / f"{arq}.svg").read_text(encoding="utf-8")
    t = re.sub(r"<!--.*?-->", "", t, flags=re.DOTALL)
    vb = re.search(r'viewBox="([^"]+)"', t).group(1)
    corpo = re.sub(r"\s+", " ", re.search(r"<svg[^>]*>(.*)</svg>", t, re.DOTALL).group(1)).strip()
    corpo = corpo.replace("> <", "><")
    if arq.startswith("lucide/") or arq == "proprios/area":
        return (f'<symbol id="i-{nome}" viewBox="{vb}" fill="none" stroke="currentColor" stroke-width="2.25" '
                f'stroke-linecap="round" stroke-linejoin="round">{corpo}</symbol>')
    return f'<symbol id="i-{nome}" viewBox="{vb}" fill="currentColor">{corpo}</symbol>'


def main() -> int:
    linhas = [simbolo(n, a) for n, a in MAPA.items()] + MARCA
    bloco = "<!-- sprite:inicio (gerado por scripts/montar_sprite_web.py) -->\n<defs>\n" + "\n".join(linhas) + "\n</defs>\n<!-- sprite:fim -->"
    idx = WEB / "index.html"
    html = idx.read_text(encoding="utf-8")
    novo, n = re.subn(r"<!-- sprite:inicio.*?<!-- sprite:fim -->", lambda _m: bloco, html, flags=re.DOTALL)
    if n != 1:
        raise SystemExit("marcadores do sprite não encontrados em apps/web/index.html")
    idx.write_text(novo, encoding="utf-8", newline="\n")
    usados = sorted({a for a in MAPA.values()})
    print(f"sprite: {len(MAPA)} ícones ({len(usados)} arquivos) + {len(MARCA)} símbolos da marca")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
