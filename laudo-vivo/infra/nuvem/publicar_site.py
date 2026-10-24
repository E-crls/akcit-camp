"""Publica o link curto no Firebase Hosting (site criado pelo Terraform em curto.tf).

- /site/ (a página do produto), as fontes e o ícone são servidos direto no domínio curto, como arquivos estáticos;
- qualquer outro caminho redireciona (302) para a demo no Cloud Run, com o caminho, onde ficam a sessão e a senha.

Uso: python publicar_site.py   (de infra/nuvem; lê o projeto do terraform.tfvars e a URL do serviço pelo terraform)
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
WEB = Path(os.environ.get("LAUDO_WEB_DIR") or AQUI.parents[1] / "apps" / "web")  # outra pasta: ex. cópia de um commit
API = "https://firebasehosting.googleapis.com/v1beta1"


def saida(*cmd: str) -> str:
    return subprocess.run(list(cmd), capture_output=True, text=True, check=True, shell=os.name == "nt").stdout.strip()


def pedir(metodo: str, url: str, corpo: bytes | dict | None = None, tipo: str = "application/json") -> dict:
    dados = json.dumps(corpo).encode() if isinstance(corpo, dict) else corpo
    req = urllib.request.Request(url, data=dados, method=metodo, headers={
        "Authorization": f"Bearer {TOKEN}", "x-goog-user-project": PROJETO, "Content-Type": tipo})
    with urllib.request.urlopen(req, timeout=120) as r:
        texto = r.read().decode() or "{}"
    return json.loads(texto)


def arquivos() -> dict[str, Path]:
    out = {f"/site/{p.relative_to(WEB / 'site').as_posix()}": p for p in (WEB / "site").rglob("*") if p.is_file()}
    out |= {f"/vendor/fonts/{p.name}": p for p in (WEB / "vendor" / "fonts").glob("*.woff2")}
    out["/icone.svg"] = WEB / "icone.svg"
    return out


def main() -> int:
    site = saida("terraform", "output", "-raw", "url_curta").removeprefix("https://").split(".")[0]
    destino = saida("terraform", "output", "-raw", "url").rstrip("/")
    if not site or not destino:
        print("sem site curto ou sem serviço no terraform output", file=sys.stderr)
        return 2
    # No Hosting, o redirecionamento vem ANTES do arquivo estático: só os caminhos da demo redirecionam (a raiz,
    # que é o QR, a entrada, a API e os arquivos do app); /site/, as fontes e o ícone ficam aqui
    demo = r"entrar\.html|api/.*|js/.*|css/.*|fis/.*|vendor/leaflet[^/]*/.*|vendor/icones/.*|\.well-known/.*"
    config = {
        "redirects": [
            {"regex": "^/$", "statusCode": 302, "location": f"{destino}/"},
            {"regex": f"^/({demo})$", "statusCode": 302, "location": f"{destino}/:1"},
        ],
        "headers": [{"glob": "/site/**", "headers": {"Cache-Control": "public, max-age=300"}}],
    }
    versao = pedir("POST", f"{API}/sites/{site}/versions", {"config": config})["name"]
    mapa, gz = {}, {}
    for caminho, p in arquivos().items():
        z = gzip.compress(p.read_bytes(), mtime=0)
        h = hashlib.sha256(z).hexdigest()
        mapa[caminho], gz[h] = h, z
    r = pedir("POST", f"{API}/{versao}:populateFiles", {"files": mapa})
    for h in r.get("uploadRequiredHashes", []):
        pedir("POST", f"{r['uploadUrl']}/{h}", gz[h], "application/octet-stream")
    pedir("PATCH", f"{API}/{versao}?update_mask=status", {"status": "FINALIZED"})
    pedir("POST", f"{API}/sites/{site}/releases?versionName={versao}", {"message": "página do produto + link curto"})
    print(f"publicado: https://{site}.web.app/site/ ({len(mapa)} arquivos; {len(r.get('uploadRequiredHashes', []))} enviados);"
          f" o resto redireciona para {destino}")
    return 0


if __name__ == "__main__":
    PROJETO = next(ln.split("=", 1)[1].strip().strip('"') for ln in (AQUI / "terraform.tfvars").read_text().splitlines()
                   if ln.strip().startswith("projeto"))
    TOKEN = os.environ.get("GOOGLE_OAUTH_ACCESS_TOKEN") or saida("gcloud", "auth", "print-access-token")
    sys.exit(main())
