"""Prepara os ativos da demo com ferramentas reais (caso DEMO-0001) e confere o sha256 de cada um.

A demo da linha de comando (19 passos) e a interface web em replay usam três coisas que não vêm prontas no
`dados_locais/` de um clone novo (a pasta é local e fica fora do git):

1. o vídeo semissintético do corredor do curral (`s03_fila_colada.mp4`, 1,2 MB) e
2. a série Sentinel-2 da gleba da demo já calculada (cache de NDVI, 13 arquivos JSON, 66 kB),
   ambos versionados em `ativos/demo/` e copiados para `dados_locais/`;
3. o detector YOLOX `yolox_m.onnx` (~100 MB, Apache-2.0), baixado da release oficial no GitHub.

Tudo é conferido contra o sha256 registrado (`ativos/manifesto.json` e `src/laudo/vision/modelos.py`). Arquivo
que já está no lugar e confere não é copiado de novo; arquivo diferente no destino é mantido (é cache local de
outra execução) e aparece como aviso, a não ser com `--forcar`.

Uso (na raiz do repositório, com o ambiente ativado; não precisa de PYTHONPATH):
  python scripts/preparar_demo.py               # copia os ativos e baixa o detector
  python scripts/preparar_demo.py --conferir    # só confere (código 1 se faltar algo); não copia nem baixa
  python scripts/preparar_demo.py --sem-modelo  # copia os ativos e não baixa o detector
  python scripts/preparar_demo.py --ao-vivo     # confere também o Ollama e o qwen3.5:4b (modo ao vivo)
  python scripts/preparar_demo.py --ajustar-openmp   # Windows + conda + faster-whisper: correção da ADR 002
  python scripts/preparar_demo.py --gerar-manifesto   # (manutenção) refaz ativos/ a partir de dados_locais/

Sem rede, o vídeo e o satélite continuam funcionando (vêm do repositório); só o detector precisa de download.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
ATIVOS = RAIZ / "ativos"
MANIFESTO = ATIVOS / "manifesto.json"
ORIGEM = ATIVOS / "demo"
DESTINO = RAIZ / "dados_locais"
CASO_DEMO = RAIZ / "eval" / "golden" / "demo" / "DEMO-0001" / "caso.yaml"
MODELO_DEMO = "yolox_m"
MODELO_LLM = "qwen3.5:4b"

sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Origem, licença e atribuição de cada grupo de ativos (copiadas para o manifesto em --gerar-manifesto).
# Em ativos/demo/ os nomes são curtos (o caminho de um clone no Windows tem limite de 260 caracteres); o
# manifesto diz para onde cada arquivo vai em dados_locais/, com o nome que o código procura.
GRUPOS = [
    {
        "prefixo": "video/",
        "o_que_e": "vídeo semissintético de corredor do curral (15 bovinos, 17,3 s) do caso DEMO-0001",
        "origem": "eval/golden/visao/gerar_semissintetico.py (semente 20261008) sobre recortes dos vídeos "
        "'Cows at Dharmasthala (2025) 01.webm' (Gpkp, CC BY-SA 4.0) e 'Herding the cows video.webm' "
        "(Marie Nouvellon, CC BY 2.0), do Wikimedia Commons",
        "licenca": "CC BY-SA 4.0 (obra derivada; ver THIRD_PARTY.md)",
        "atribuicao": "Gpkp (CC BY-SA 4.0) e Marie Nouvellon (CC BY 2.0), via Wikimedia Commons",
    },
    {
        "prefixo": "ndvi/",
        "o_que_e": "busca STAC e estatísticas de NDVI por data da gleba do DEMO-0001 (hash da geometria "
        "dda9cb9b2585de90, período 2026-03-16 a 2026-10-08)",
        "origem": "laudo.geo.ndvi.serie_ndvi sobre Sentinel-2 L2A (coleção sentinel-2-c1-l2a do Earth "
        "Search, Element 84, AWS Open Data)",
        "licenca": "Sentinel Data Legal Notice (Copernicus): uso livre, completo e aberto",
        "atribuicao": "Contém dados Copernicus Sentinel modificados (2026)",
    },
    {
        "prefixo": "contagem/",
        "o_que_e": "resultado da contagem do YOLOX para o vídeo do DEMO-0001 (envelope e quadros-chave), o mesmo da "
        "gravação do replay; a demo pública (laudo.api.publica) lê daqui em vez de contar de novo, porque o YOLOX "
        "em outra CPU (a do Cloud Build) contou diferente e os passos seguintes saíram da gravação",
        "origem": "python -m laudo.api.publica --preparar, na máquina em que a contagem confere com a gravação",
        "licenca": "CC BY-SA 4.0 (quadros do vídeo semissintético; ver THIRD_PARTY.md)",
        "atribuicao": "Gpkp (CC BY-SA 4.0) e Marie Nouvellon (CC BY 2.0), via Wikimedia Commons",
    },
]
VIDEO_DEMO = "videos/sinteticos/s03_fila_colada.mp4"  # relativo a dados_locais/ (caso.yaml do DEMO-0001)


def sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        while bloco := f.read(1 << 20):
            h.update(bloco)
    return h.hexdigest()


def hash_gleba_demo() -> str:
    """Hash da geometria da gleba do DEMO-0001, o mesmo que nomeia o cache de NDVI (laudo.geo.ndvi)."""
    import yaml
    from shapely import wkt
    from shapely.ops import unary_union

    from laudo.geo.ndvi import hash_geom

    caso = yaml.safe_load(CASO_DEMO.read_text(encoding="utf-8"))
    return hash_geom(unary_union([wkt.loads(w) for w in caso["operacao"]["glebas_wkt"]]))


def gerar_manifesto() -> int:
    """(Manutenção) Copia de dados_locais/ para ativos/demo/ o vídeo, o cache de NDVI e o da contagem da demo, com nomes
    curtos, e reescreve o manifesto. Roda na máquina que tem esses arquivos (depois de uma demo com rede)."""
    gh = hash_gleba_demo()
    pares: list[tuple[Path, str]] = [(DESTINO / VIDEO_DEMO, "video/" + Path(VIDEO_DEMO).name)]
    for p in sorted((DESTINO / "ndvi_cache").rglob(f"*{gh}*")):
        curto = f"ndvi/stac_{gh}.json" if p.parent.name == "stac" else f"ndvi/{p.parent.name}.json"
        pares.append((p, curto))
    for p in sorted((DESTINO / "cache_contagem").glob("*/*")):  # cache da demo pública (só vídeos do caso)
        pares.append((p, f"contagem/{p.parent.name}/{p.name}"))
    faltam = [str(o) for o, _ in pares if not o.is_file()]
    if faltam or len(pares) < 3:
        print(f"faltam arquivos em dados_locais/ para gerar os ativos: {faltam or 'cache de NDVI'}",
              file=sys.stderr)
        return 2
    if len({c for _, c in pares}) != len(pares):
        print("dois arquivos com o mesmo nome curto em ativos/demo/", file=sys.stderr)
        return 2
    shutil.rmtree(ORIGEM, ignore_errors=True)
    arquivos = []
    for origem, curto in pares:
        alvo = ORIGEM / curto
        alvo.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origem, alvo)
        grupo = next(g["prefixo"] for g in GRUPOS if curto.startswith(g["prefixo"]))
        arquivos.append({"caminho": curto, "destino": origem.relative_to(RAIZ).as_posix(),
                         "sha256": sha256(alvo), "bytes": alvo.stat().st_size, "grupo": grupo})
    dados = {
        "descricao": "Ativos da demo com ferramentas reais (DEMO-0001), copiados de ativos/demo/ para "
        "dados_locais/ por scripts/preparar_demo.py. Nada aqui é dado pessoal.",
        "grupos": GRUPOS,
        "arquivos": arquivos,
    }
    texto = json.dumps(dados, ensure_ascii=False, indent=1) + "\n"
    MANIFESTO.write_text(texto, encoding="utf-8", newline="\n")
    print(f"{MANIFESTO.relative_to(RAIZ).as_posix()}: {len(arquivos)} arquivo(s) em ativos/demo/")
    return 0


def sha_do_video_no_caso() -> str | None:
    """sha256 que o caso da demo registra para o vídeo (o mesmo que a ferramenta de integridade confere)."""
    try:
        import yaml

        caso = yaml.safe_load(CASO_DEMO.read_text(encoding="utf-8"))
        return (caso.get("video") or {}).get("sha256")
    except Exception:  # noqa: BLE001 — só um reforço da conferência; o manifesto já tem o hash
        return None


def preparar_ativos(conferir: bool, forcar: bool) -> tuple[int, int]:
    """Copia (ou só confere) os ativos versionados. Devolve (problemas, avisos)."""
    if not MANIFESTO.is_file():
        print(f"falta {MANIFESTO.relative_to(RAIZ).as_posix()} (o clone está incompleto?)")
        return 1, 0
    man = json.loads(MANIFESTO.read_text(encoding="utf-8"))
    problemas = avisos = copiados = iguais = 0
    sha_video = sha_do_video_no_caso()
    for a in man["arquivos"]:
        origem = ORIGEM / a["caminho"]
        destino = RAIZ / a["destino"]
        if a["caminho"].endswith(".mp4") and sha_video and sha_video != a["sha256"]:
            print(f"ERRO {a['caminho']}: o caso DEMO-0001 espera sha256 {sha_video[:12]}…, o manifesto diz "
                  f"{a['sha256'][:12]}…")
            problemas += 1
            continue
        if destino.is_file() and sha256(destino) == a["sha256"]:
            iguais += 1
            continue
        if conferir:
            estado = "difere do registrado" if destino.is_file() else "ausente"
            print(f"falta  {a['destino']} ({estado})")
            problemas += 1
            continue
        if not origem.is_file() or sha256(origem) != a["sha256"]:
            print(f"ERRO {a['caminho']}: arquivo de ativos/ ausente ou com sha256 diferente do manifesto")
            problemas += 1
            continue
        if destino.is_file() and not forcar:
            print(f"aviso  {a['destino']}: já existe com outro conteúdo (cache local); mantido "
                  "(--forcar troca)")
            avisos += 1
            continue
        destino.parent.mkdir(parents=True, exist_ok=True)
        tmp = destino.with_name(destino.name + ".part")
        shutil.copyfile(origem, tmp)
        tmp.replace(destino)
        copiados += 1
    total = len(man["arquivos"])
    verbo = "conferidos" if conferir else "prontos"
    print(f"ativos da demo: {iguais + copiados}/{total} {verbo} em dados_locais/ "
          f"({copiados} copiado(s), {iguais} já estavam iguais)")
    return problemas, avisos


def preparar_modelo(conferir: bool) -> int:
    from laudo.vision.modelos import MODELOS

    info = MODELOS[MODELO_DEMO]
    if info.caminho.is_file() and sha256(info.caminho) == info.sha256:
        print(f"detector {MODELO_DEMO}: confere ({info.sha256[:12]}…) em {info.caminho}")
        return 0
    if conferir:
        print(f"falta  detector {MODELO_DEMO} em {info.caminho} (rode sem --conferir para baixar ~100 MB)")
        return 1
    import baixar_modelos

    print(f"detector {MODELO_DEMO}: baixando ~100 MB de {info.url}")
    try:
        baixar_modelos.baixar(MODELO_DEMO)
    except SystemExit as e:  # sha256 diferente: baixar() já apagou o arquivo parcial
        print(f"ERRO detector {MODELO_DEMO}: {e}")
        return 1
    except Exception as e:  # noqa: BLE001 — rede fora, proxy, disco: vira mensagem com o que fazer
        print(f"ERRO detector {MODELO_DEMO}: {type(e).__name__}: {e}")
        print(f"  Baixe à mão {info.url} e salve como {info.caminho} (sha256 {info.sha256}).")
        return 1
    return 0


def conferir_ollama() -> int:
    import httpx

    base = (os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
    if not base.startswith("http"):
        base = "http://" + base
    try:
        r = httpx.get(f"{base}/api/tags", timeout=5)
        r.raise_for_status()
        nomes = {m.get("name") for m in r.json().get("models", [])}
    except Exception as e:  # noqa: BLE001
        print(f"aviso  Ollama fora do ar em {base} ({type(e).__name__}); o modo ao vivo precisa dele. "
              "O replay não precisa.")
        return 1
    if MODELO_LLM in nomes:
        print(f"Ollama em {base} com {MODELO_LLM}: pronto para o modo ao vivo")
        return 0
    print(f"aviso  Ollama em {base} sem o {MODELO_LLM}: rode `ollama pull {MODELO_LLM}` (~3,4 GB)")
    return 1


SITECUSTOMIZE = '''"""sitecustomize do ambiente conda do Laudo Vivo.

Escrito por scripts/preparar_demo.py --ajustar-openmp.

Ver docs/adr/002-ambiente.md: desliga as caixas modais de erro do Windows (a falha de DLL vira exceção em vez
de travar o processo esperando um clique) e pré-carrega a libiomp5md.dll da Intel que vem com o ctranslate2,
para que o shim de mesmo nome do conda-forge (sem o símbolo _vcomp_barrier) não seja usado.
"""

import os
import sys

if sys.platform == "win32":
    try:
        import ctypes

        # SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX
        ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    except Exception:
        pass
    # dois runtimes OpenMP no mesmo processo (Intel libiomp5md + LLVM libomp)
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    try:
        import ctypes

        _dll = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ctranslate2", "libiomp5md.dll")
        if os.path.exists(_dll):
            ctypes.WinDLL(_dll)
    except Exception:
        pass
'''
MARCA_SITECUSTOMIZE = "scripts/preparar_demo.py --ajustar-openmp"


def ajustar_openmp() -> int:
    """Windows + ambiente conda + faster-whisper do PyPI: aplica a correção da ADR 002 ao ambiente deste
    Python (sys.prefix). Sem ela, o primeiro import do ctranslate2 depois do shim libiomp5md.dll do
    conda-forge abre uma caixa modal ("_vcomp_barrier não encontrado") e o processo fica parado. Idempotente;
    fora do Windows, fora de um ambiente conda ou sem o ctranslate2, não faz nada."""
    if sys.platform != "win32":
        print("openmp: nada a ajustar (só no Windows)")
        return 0
    prefixo = Path(sys.prefix)
    sp = prefixo / "Lib" / "site-packages"
    intel = sp / "ctranslate2" / "libiomp5md.dll"
    shim = prefixo / "Library" / "bin" / "libiomp5md.dll"
    if not intel.is_file() or not shim.is_file() or not (prefixo / "conda-meta").is_dir():
        print("openmp: nada a ajustar (sem ctranslate2 ou fora de um ambiente conda)")
        return 0
    feito = []
    if sha256(shim) != sha256(intel):
        bak = shim.with_name("libiomp5md.dll.llvm-shim.bak")
        if not bak.exists():
            shutil.copyfile(shim, bak)
        shutil.copyfile(intel, shim)
        feito.append("Library/bin/libiomp5md.dll trocada pela da Intel (o shim fica em "
                     "libiomp5md.dll.llvm-shim.bak)")
    ativ = prefixo / "etc" / "conda" / "activate.d"
    ativ.mkdir(parents=True, exist_ok=True)
    for nome, texto in (("laudo-omp_activate.bat", '@SET "KMP_DUPLICATE_LIB_OK=TRUE"\n'),
                        ("laudo-omp_activate.ps1", '$Env:KMP_DUPLICATE_LIB_OK = "TRUE"\n'),
                        ("laudo-omp_activate.sh", "export KMP_DUPLICATE_LIB_OK=TRUE\n")):
        if not (ativ / nome).exists():
            (ativ / nome).write_text(texto, encoding="utf-8")
            feito.append(f"etc/conda/activate.d/{nome}")
    sc = sp / "sitecustomize.py"
    if not sc.exists() or MARCA_SITECUSTOMIZE in sc.read_text(encoding="utf-8", errors="ignore"):
        if not sc.exists() or sc.read_text(encoding="utf-8") != SITECUSTOMIZE:
            sc.write_text(SITECUSTOMIZE, encoding="utf-8")
            feito.append("site-packages/sitecustomize.py")
    else:
        print(f"openmp: aviso: {sc} já existe e não é deste script; não foi trocado")
    print("openmp: " + ("; ".join(feito) if feito else "já estava ajustado") + " (docs/adr/002-ambiente.md)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--conferir", action="store_true", help="só confere; não copia nem baixa")
    ap.add_argument("--sem-modelo", action="store_true", help="não baixa nem confere o detector YOLOX")
    ap.add_argument("--forcar", action="store_true",
                    help="troca arquivos de destino que diferem do registrado")
    ap.add_argument("--ao-vivo", action="store_true", help="confere também o Ollama e o qwen3.5:4b")
    ap.add_argument("--ajustar-openmp", action="store_true",
                    help="(Windows, ambiente conda com faster-whisper) só aplica a correção da ADR 002")
    ap.add_argument("--gerar-manifesto", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.gerar_manifesto:
        return gerar_manifesto()
    if a.ajustar_openmp:
        return ajustar_openmp()
    problemas, _avisos = preparar_ativos(a.conferir, a.forcar)
    if not a.sem_modelo:
        problemas += preparar_modelo(a.conferir)
    if a.ao_vivo:
        conferir_ollama()  # só informa: o replay e os testes não dependem do Ollama
    if problemas:
        print(f"{problemas} problema(s): a demo com ferramentas reais ainda não roda "
              "(veja docs/COMO_RODAR.md)")
        return 1
    print("pronto: a demo com ferramentas reais (CLI e interface web em replay) roda sem GPU e sem rede")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
