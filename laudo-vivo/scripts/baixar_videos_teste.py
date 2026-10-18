"""Baixa os vídeos de teste do contador de bovinos (Wikimedia Commons, licenças livres).

Uso (raiz do repositório):
    scripts/py.sh scripts/baixar_videos_teste.py --contato "<seu e-mail>"
    scripts/py.sh scripts/baixar_videos_teste.py --contato "https://github.com/sua-equipe" --extras

A política de User-Agent do Wikimedia (https://w.wiki/4wJS) exige contato de quem roda o robô; sem ele o
servidor de arquivos responde 429. O contato é de quem roda o script: não há valor padrão.

Baixa a versão transcodificada 480p VP9 (≤ 30 MB, suficiente para o detector com entrada 640 px) para
`dados_locais/videos/` e confere o sha256 dos 5 vídeos de referência. `--extras` baixa candidatos
adicionais (sem contagem de referência) para `dados_locais/videos/extras/`.
"""

from __future__ import annotations

import argparse
import hashlib
import time
from pathlib import Path

import httpx
import yaml

RAIZ = Path(__file__).resolve().parents[1]
API = "https://commons.wikimedia.org/w/api.php"
REF = RAIZ / "eval" / "golden" / "visao" / "contagens_referencia.yaml"

VIDEOS = {
    "v01_estrada_oregon": "File:Cattle drive on southern Oregon road (41211547371).webm",
    "v02_mata_burro_noite": "File:Cow crosses cattle grid.webm",
    "v03_zebuinos_estabulo": "File:Cows at Dharmasthala (2025) 01.webm",
    "v04_manejo_a_cavalo": "File:Herding the cows video.webm",
    "v05_bufalas_ordenha": "File:Cows at Dharmasthala (2025) 02.webm",
}
# Candidatos extras (licença livre, ≤ 30 MB em 480p), sem contagem de referência.
EXTRAS = {
    "x01_tocando_vacas_verao": "File:Moving cows to the summer range (42877666722).webm",  # domínio público
    "x02_vale_jequitinhonha": "File:Lida com o gado no Vale do Jequitinhonha - MG.webm",  # CC BY 3.0
    "x03_saskatchewan": "File:Cows in Saskatchewan.webm",  # CC BY 2.0
    "x04_garni": "File:Paŝtisto kun bovoj apud la urbo Garni.webm",  # CC BY-SA 4.0
    "x05_feno_cc0": "File:Herd of cows enjoying hay.webm",  # CC0
    "x06_cattle_sep26": "File:Video Cattle Sep26.webm",  # CC0
    "x07_dharmasthala_03": "File:Cows at Dharmasthala (2025) 03.webm",  # CC BY-SA 4.0
    "x08_drone_tamale": "File:(Drone Aerial) Herd Of Cows In Rural Tamale.webm",  # CC BY-SA 4.0
}


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while b := f.read(1 << 20):
            h.update(b)
    return h.hexdigest()


def _get(cliente: httpx.Client, url: str, **kw) -> httpx.Response:
    for tentativa in range(5):
        r = cliente.get(url, **kw)
        if r.status_code != 429:
            r.raise_for_status()
            return r
        espera = max(int(r.headers.get("retry-after", "0") or 0), 30 * (tentativa + 1))
        print(f"429 (limite do servidor); esperando {espera} s")
        time.sleep(espera)
    raise SystemExit("o servidor continua recusando (429); tente mais tarde")


def baixar(cliente: httpx.Client, titulo: str, destino: Path) -> dict:
    r = _get(cliente, API, params={"action": "query", "titles": titulo, "prop": "videoinfo",
                                   "viprop": "url|size|extmetadata|derivatives", "format": "json"})
    pagina = next(iter(r.json()["query"]["pages"].values()))
    vi = pagina["videoinfo"][0]
    meta = vi.get("extmetadata", {})
    url = next((d["src"] for d in vi.get("derivatives", []) if d.get("transcodekey") == "480p.vp9.webm"),
               vi["url"])
    if not destino.exists():
        destino.parent.mkdir(parents=True, exist_ok=True)
        tmp = destino.with_suffix(".part")
        tmp.write_bytes(_get(cliente, url, follow_redirects=True, timeout=120).content)
        tmp.replace(destino)
        time.sleep(5)
    return {"arquivo": destino.name, "titulo": titulo, "pagina": vi.get("descriptionurl"),
            "licenca": (meta.get("LicenseShortName") or {}).get("value"),
            "autor": (meta.get("Artist") or {}).get("value"), "sha256": _sha256(destino)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--contato", required=True, help="e-mail ou URL de quem roda (política do Wikimedia)")
    ap.add_argument("--extras", action="store_true", help="baixa também os candidatos sem referência")
    a = ap.parse_args(argv)
    ua = f"LaudoVivo-AKCIT/0.1 ({a.contato}) httpx/{httpx.__version__}"
    esperados = {v["id"]: v["sha256"] for v in yaml.safe_load(REF.read_text(encoding="utf-8"))["videos"]}
    with httpx.Client(headers={"User-Agent": ua}, timeout=60) as c:
        for nome, titulo in VIDEOS.items():
            info = baixar(c, titulo, RAIZ / "dados_locais" / "videos" / f"{nome}.webm")
            ok = "confere" if info["sha256"] == esperados.get(nome) else "SHA256 DIFERENTE da referência"
            print(nome, info["licenca"], ok)
        if a.extras:
            for nome, titulo in EXTRAS.items():
                info = baixar(c, titulo, RAIZ / "dados_locais" / "videos" / "extras" / f"{nome}.webm")
                print(nome, info["licenca"], info["autor"], info["pagina"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
