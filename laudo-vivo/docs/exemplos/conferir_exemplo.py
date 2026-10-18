"""Confere o laudo selado de exemplo desta pasta (docs/exemplos/) sem a instalação que o gerou.

Uso (na raiz do repositório):
  scripts/py.sh docs/exemplos/conferir_exemplo.py            # código 0 = tudo confere, 1 = algo não confere

O que é conferido:
1. o selo do laudo (`laudo.audit.selo.verificar_em_disco` sobre esta pasta): selo recalculado, assinatura humana
   sobre o hash raiz, conteúdo assinado (o hash raiz recalculado do bloco `conteudo_assinado`) e o HTML como
   renderização exata do JSON. A cadeia de hash e as aprovações gravadas ficam na pasta de dados da instalação;
   a conferência com elas foi feita na geração e está em `gerado_com.json` (`conferencia_na_instalacao`);
2. a marca d'água "DEMONSTRAÇÃO — dados sintéticos" no JSON e no HTML;
3. o `SHA256SUMS` (nada mudou depois da geração). Se um arquivo difere só no fim de linha (o CRLF da geração
   virou LF), o script diz isso: em geral é um clone feito sem o `.gitattributes` desta pasta;
4. o pacote de exibição: o sha256 de cada arquivo do ZIP contra o `manifest.json` dele, o mesmo selo e o mesmo
   laudo selado (byte a byte) que estão nesta pasta;
5. num clone git: que o git guarda os arquivos gerados sem converter fim de linha (`git check-attr text` dá
   `unset`, pelo `.gitattributes` desta pasta);
6. que o bloco de estado do `README.md` (entre `<!--estado_exemplo-->` e `<!--/estado_exemplo-->`) é o que o
   `gerado_com.json` diz.
No fim, avisa (sem mudar o código de saída) se o exemplo é provisório, se o `src/` de hoje não é o que gerou o
exemplo ou se os números do pitch (`docs/entregaveis/numeros.json`, `versao.sha256_src`) são de outro código.

Uso interno de `gerar_exemplo.sh` (não precisa rodar à mão):
  --pasta DIR                 confere DIR (ou registra nela) em vez desta pasta: a montagem fora do repositório
  --portao DIR_DADOS LOG      recusa uma geração incompleta (não SELADO, número de passos diferente de --passos,
                              replay com requisição fora da gravação, LLM fora em algum turno, VLM fora do
                              cache, falha de ferramenta, laudo sem sensoriamento remoto)
  --registrar ...             grava `gerado_com.json` e `SHA256SUMS` em --pasta
  --atualizar-readme          reescreve o bloco de estado do README.md de --pasta a partir do gerado_com.json dela
  --folga                     sai com 1 se a máquina não tem memória livre para gerar o exemplo
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import re
import subprocess
import sys
import textwrap
import zipfile
from datetime import datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent
REPO = AQUI.parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

FIS_ID = "fis_demo_0001"
ZIP = "DEMONSTRACAO_pacote_exibicao.zip"
# arquivos cobertos pelo SHA256SUMS (o README, os scripts e o próprio gerado_com.json ficam de fora)
ARQUIVOS = ("laudo_selado.json", "laudo_selado.html", "laudo_selado.pdf", ZIP)
NUMEROS = REPO / "docs" / "entregaveis" / "numeros.json"
BLOCO_INI, BLOCO_FIM = "<!--estado_exemplo-->", "<!--/estado_exemplo-->"
# folga para a geração (a demo da CLI com a contagem em CPU e, depois, um Edge headless)
FOLGA_COMMIT_GB, FOLGA_RAM_GB = 6.0, 3.5


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while bloco := f.read(1 << 20):
            h.update(bloco)
    return h.hexdigest()


def sha256_src(lf: bool = False) -> str:
    """sha256 de `src/` com a mesma definição de `eval/harness.py::hash_src` (a que a r4 registra). Com `lf`, o
    CRLF dos textos vira LF antes (o `hash_src_lf` da avaliação, que é o valor de um clone com LF)."""
    h = hashlib.sha256()
    for p in sorted((REPO / "src").rglob("*")):
        if p.is_file() and p.suffix in (".py", ".yaml", ".md", ".j2") and "__pycache__" not in p.parts:
            dados = p.read_bytes()
            dados = dados.replace(b"\r\n", b"\n") if lf else dados
            h.update(p.relative_to(REPO).as_posix().encode() + b"\0" + dados)
    return h.hexdigest()


def _crlf_virou_lf(dados: bytes, sha_esperado: str) -> bool:
    """O arquivo só difere do registrado porque o CRLF virou LF (ex.: git com `eol=lf` sem o .gitattributes)?"""
    if b"\r\n" in dados or b"\n" not in dados:
        return False
    return hashlib.sha256(dados.replace(b"\n", b"\r\n")).hexdigest() == sha_esperado


def _git_converte(pasta: Path) -> list[str] | None:
    """Arquivos gerados que o git converteria no commit (`text` diferente de `unset`); None = sem git/clone."""
    try:
        r = subprocess.run(["git", "-C", str(pasta), "check-attr", "text", "--", *ARQUIVOS],
                           capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None  # git ausente ou pasta fora de um repositório
    ruins = []
    for linha in r.stdout.splitlines():
        partes = linha.rsplit(": ", 2)
        if len(partes) == 3 and partes[2].strip() != "unset":
            ruins.append(f"{Path(partes[0]).name} (text: {partes[2].strip()})")
    return ruins


def _versao_numeros() -> dict:
    try:
        v = json.loads(NUMEROS.read_text(encoding="utf-8")).get("versao") or {}
    except (OSError, ValueError):
        return {}
    return {k: v[k] for k in ("data", "sufixo", "sha256_src") if k in v}


def _quando(iso: str | None) -> str:
    try:
        return datetime.fromisoformat(str(iso)).strftime("%d/%m/%Y às %H:%M")
    except ValueError:
        return str(iso)


def bloco_estado(meta: dict) -> str:
    """O texto do bloco de estado do README (sem os marcadores), só a partir do gerado_com.json."""
    fx = meta.get("fixture_replay") or {}
    conf = meta.get("conferencia_na_instalacao") or {}
    num = meta.get("versao_dos_numeros") or {}
    partes = [(
        "**Estado do exemplo** (escrito por `conferir_exemplo.py` a partir do `gerado_com.json`; não edite à "
        f"mão): gerado em {_quando(meta.get('gerado_em'))}. Caminho de {meta.get('passos_do_roteiro')} passos: "
        f"{meta.get('caminho')}. Código: `sha256(src/)` `{str(meta.get('sha256_src'))[:16]}…`. Fixture de "
        f"replay: `{Path(str(fx.get('arquivo', '-'))).name}` (`{str(fx.get('sha256'))[:16]}…`). Conferência do "
        f"selo na instalação: {'confere' if conf.get('valido') else 'NÃO confere'} ({conf.get('motivo', '-')})."
    )]
    if num:
        rot = f"{num.get('sufixo', '-')} de {num.get('data', '-')}"
        if num.get("mesmo_codigo"):
            partes.append(f"É o mesmo código dos números do pitch ({rot}).")
        else:
            partes.append(f"Os números do pitch são de outro código ({rot}, "
                          f"`{str(num.get('sha256_src'))[:16]}…`).")
    if meta.get("provisorio"):
        partes.append("**Provisório:** " + str(meta.get("nota") or "será gerado de novo depois da r4 (seção 6)."))
    linhas = textwrap.wrap(" ".join(partes), width=108, break_long_words=False, break_on_hyphens=False)
    return "\n".join("> " + ln for ln in linhas)


def _bloco_no_readme(texto: str) -> str | None:
    i, f = texto.find(BLOCO_INI), texto.find(BLOCO_FIM)
    if i < 0 or f < i or texto.count(BLOCO_INI) != 1:
        return None
    return texto[i + len(BLOCO_INI):f].strip("\n")


def conferir(pasta: Path = AQUI) -> list[str]:
    from laudo.audit.selo import verificar_em_disco
    from laudo.demonstracao import MARCA_DAGUA

    pasta = pasta.resolve()
    problemas: list[str] = []
    res = verificar_em_disco(pasta)
    print(
        f"selo: {'confere' if res.valido else 'NÃO confere'} (selo {res.selo_confere}, assinatura "
        f"{res.assinatura_confere}, conteúdo {res.conteudo_confere} via {res.origem_conteudo or '-'}, "
        f"HTML {res.html_confere})"
    )
    problemas += [f"selo: {d}" for d in res.divergencias]
    if not res.valido and not res.divergencias:
        problemas.append("selo: não confere")
    laudo = json.loads((pasta / "laudo_selado.json").read_text(encoding="utf-8"))
    html = (pasta / "laudo_selado.html").read_text(encoding="utf-8")
    if laudo.get("tipo") != "selado":
        problemas.append(f"o laudo não é o selado (tipo {laudo.get('tipo')!r})")
    if (laudo.get("demonstracao") or {}).get("marca_dagua") != MARCA_DAGUA or MARCA_DAGUA not in html:
        problemas.append("marca d'água de demonstração ausente no JSON ou no HTML")

    somas = pasta / "SHA256SUMS"
    if not somas.is_file():
        problemas.append("SHA256SUMS ausente")
    else:
        n = 0
        for linha in somas.read_text(encoding="utf-8").splitlines():
            if not linha.strip():
                continue
            n += 1
            h, nome = linha.split(maxsplit=1)
            nome = nome.lstrip("*")
            p = pasta / nome
            if not p.is_file():
                problemas.append(f"SHA256SUMS: {nome} ausente")
            elif sha256(p) != h:
                if _crlf_virou_lf(p.read_bytes(), h):
                    problemas.append(f"SHA256SUMS: {nome} só difere no fim de linha (o CRLF da geração virou LF; "
                                     "clone sem o .gitattributes desta pasta?)")
                else:
                    problemas.append(f"SHA256SUMS: {nome} mudou depois da geração")
        print(f"SHA256SUMS: {n} arquivo(s) conferido(s)")

    pz = pasta / ZIP
    if not pz.is_file():
        problemas.append(f"{ZIP} ausente")
    else:
        with zipfile.ZipFile(pz) as z:
            man = json.loads(z.read("manifest.json"))
            ruins = [
                a["caminho"]
                for a in man.get("arquivos", [])
                if hashlib.sha256(z.read(a["caminho"])).hexdigest() != a["sha256"]
            ]
            problemas += [f"pacote: {c} não confere com o manifest" for c in ruins]
            if man.get("selo") != laudo.get("selo"):
                problemas.append("pacote: o selo do manifest não é o do laudo desta pasta")
            no_zip, aqui = z.read("laudo/laudo_selado.json"), (pasta / "laudo_selado.json").read_bytes()
            if no_zip != aqui:
                if no_zip.replace(b"\r\n", b"\n") == aqui.replace(b"\r\n", b"\n"):
                    problemas.append("pacote: o laudo selado do ZIP só difere do desta pasta no fim de linha "
                                     "(clone sem o .gitattributes desta pasta?)")
                else:
                    problemas.append("pacote: o laudo selado do ZIP não é o desta pasta")
            print(f"pacote: {len(man.get('arquivos', []))} arquivo(s) no manifest, {len(ruins)} divergente(s)")

    if pasta == AQUI:  # só no repositório: a montagem fora dele não é clone
        convertidos = _git_converte(pasta)
        if convertidos is None:
            print("git: fora de um clone (ou sem git); a regra de fim de linha não foi conferida")
        elif convertidos:
            problemas += [f"git: {c} seria convertido no commit (falta o .gitattributes desta pasta)"
                          for c in convertidos]
        else:
            print(f"git: os {len(ARQUIVOS)} arquivos gerados ficam byte a byte (text: unset)")

    meta: dict = {}
    if (pasta / "gerado_com.json").is_file():
        meta = json.loads((pasta / "gerado_com.json").read_text(encoding="utf-8"))
    readme = pasta / "README.md"
    if readme.is_file() and meta:
        no_readme = _bloco_no_readme(readme.read_text(encoding="utf-8"))
        if no_readme is None:
            problemas.append(f"README.md sem o bloco de estado ({BLOCO_INI} … {BLOCO_FIM})")
        elif no_readme != bloco_estado(meta):
            problemas.append("README.md: o bloco de estado não é o do gerado_com.json "
                             "(rode conferir_exemplo.py --atualizar-readme)")
    for a in _avisos(meta):
        print("AVISO:", a)
    return problemas


def _avisos(meta: dict) -> list[str]:
    if not meta:
        return ["gerado_com.json ausente: não dá para saber de que código é o exemplo"]
    out = []
    gerou = str(meta.get("sha256_src") or "")
    if meta.get("provisorio"):
        out.append("o exemplo é PROVISÓRIO (gerado_com.json, 'provisorio': true); gere de novo depois da r4")
    atual = sha256_src()
    atual_lf = sha256_src(lf=True)
    if gerou and atual != gerou and atual_lf != str(meta.get("sha256_src_lf") or ""):
        out.append(f"o src/ de hoje ({atual[:16]}…) não é o que gerou o exemplo ({gerou[:16]}…)")
    num = _versao_numeros()
    if gerou and num.get("sha256_src") and num["sha256_src"] != gerou:
        out.append(f"os números do pitch ({num.get('sufixo')}, {str(num['sha256_src'])[:16]}…) são de outro "
                   f"código que o exemplo ({gerou[:16]}…)")
    return out


def portao(dados: Path, log: Path, passos: int | None = None) -> list[str]:
    """Recusa copiar uma geração que não mostre o caso inteiro."""
    texto = log.read_text(encoding="utf-8", errors="replace")
    erros = []
    if "Etapa final: SELADO" not in texto:
        erros.append("a demo não terminou SELADA")
    n_passos = len(re.findall(r"^\[\d{2}\] ", texto, flags=re.MULTILINE))
    if passos is not None and n_passos != passos:
        erros.append(f"o log tem {n_passos} passo(s), não {passos} (outra geração na pasta de dados?)")
    m = re.search(r"replay: (\d+) requisi", texto)
    if not m or m.group(1) != "0":
        erros.append("o replay teve requisição sem gravação exata (a fixture não casa com o código)")
    n_fora = texto.count("LLM indisponível") + texto.count("orçamento de LLM do turno esgotado")
    if n_fora:
        erros.append(f"LLM fora em {n_fora} turno(s) (fixture incompleta ou gravada com TIMEOUT)")
    n_cache = texto.count("ausente do cache")
    if n_cache:
        erros.append(f"{n_cache} resposta(s) do VLM fora do cache da demo (o cache não casa com o código)")
    n_erro = len(re.findall(r"ERRO (?:ERRO_INTERNO|TIMEOUT|INDISPONIVEL)", texto))
    if n_erro:
        erros.append(f"{n_erro} falha(s) de ferramenta no log")
    pj = dados / "laudos" / FIS_ID / "laudo_selado.json"
    if not pj.is_file():
        erros.append("laudo_selado.json não foi gerado")
    else:
        laudo = json.loads(pj.read_text(encoding="utf-8"))
        if not laudo.get("sensoriamento_remoto"):
            erros.append("o laudo saiu sem a consulta ao satélite (sensoriamento remoto vazio)")
    return erros


def registrar(a: argparse.Namespace) -> None:
    pasta = Path(a.pasta).resolve()
    laudo = json.loads((pasta / "laudo_selado.json").read_text(encoding="utf-8"))
    selo_inst = json.loads(Path(a.selo_json).read_text(encoding="utf-8"))
    log = Path(a.log).read_text(encoding="utf-8", errors="replace")
    passos = len(re.findall(r"^\[\d{2}\] ", log, flags=re.MULTILINE))
    fixture = REPO / a.fixture
    src_gerou = a.sha256_src or sha256_src()
    num = _versao_numeros()
    meta = {
        "gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
        "comando": f"bash docs/exemplos/gerar_exemplo.sh --passos {passos}",
        "passos_do_roteiro": passos,
        "caminho": "com a foto do DANFE (roteiro do palco)" if passos == 19 else "só o XML da NF-e (--sem-danfe)",
        "fixture_replay": {"arquivo": a.fixture, "sha256": sha256(fixture)},
        # --sha256-src: quando o registro é feito depois de o src/ mudar (o valor é o do código que gerou o laudo)
        "sha256_src": src_gerou,
        "sha256_src_no_registro": sha256_src(),
        "fiscalizacao_id": laudo.get("fiscalizacao_id"),
        "hash_raiz_assinado": laudo.get("hash_raiz"),
        "selo": laudo.get("selo"),
        "template_sha256": (laudo.get("template") or {}).get("sha256"),
        "conferencia_na_instalacao": {
            k: selo_inst.get(k)
            for k in (
                "valido", "selo_confere", "assinatura_confere", "conteudo_confere", "cadeia_confere",
                "html_confere", "aprovacoes_conferem", "origem_conteudo", "divergencias", "avisos", "motivo",
            )
            if k in selo_inst
        },
        "arquivos": {n: sha256(pasta / n) for n in ARQUIVOS if (pasta / n).is_file()},
    }
    if num:  # retrato, no registro, de qual código são os números do pitch (docs/entregaveis/numeros.json)
        meta["versao_dos_numeros"] = {**num, "mesmo_codigo": num.get("sha256_src") == src_gerou}
    if a.extra:  # JSON com chaves a acrescentar ou trocar (ex.: "nota"); argumento de arquivo, não de texto,
        # porque o micromamba run do Windows quebra argumento com <, >, & ou parênteses
        meta.update(json.loads(Path(a.extra).read_text(encoding="utf-8")))
    (pasta / "gerado_com.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    (pasta / "SHA256SUMS").write_text(
        "".join(f"{h}  {n}\n" for n, h in meta["arquivos"].items()), encoding="utf-8", newline="\n"
    )
    print(f"registrado em {pasta}: gerado_com.json e SHA256SUMS ({len(meta['arquivos'])} arquivo(s)); "
          f"sha256(src/) {meta['sha256_src'][:16]}…")


def atualizar_readme(pasta: Path) -> int:
    readme = pasta / "README.md"
    meta = json.loads((pasta / "gerado_com.json").read_text(encoding="utf-8"))
    texto = readme.read_text(encoding="utf-8")
    if _bloco_no_readme(texto) is None:
        print(f"README.md sem um bloco {BLOCO_INI} … {BLOCO_FIM} (exatamente um)")
        return 1
    i, f = texto.find(BLOCO_INI) + len(BLOCO_INI), texto.find(BLOCO_FIM)
    readme.write_text(texto[:i] + "\n" + bloco_estado(meta) + "\n" + texto[f:], encoding="utf-8", newline="\n")
    print(f"README.md: bloco de estado reescrito a partir do gerado_com.json ({meta.get('passos_do_roteiro')} "
          f"passos{', provisório' if meta.get('provisorio') else ''})")
    return 0


class _Mem(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def folga() -> int:
    """Memória virtual (commit) e RAM livres; não toca no Ollama nem na GPU."""
    if sys.platform == "win32":
        m = _Mem()
        m.dwLength = ctypes.sizeof(_Mem)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        commit, ram = m.ullAvailPageFile / 2**30, m.ullAvailPhys / 2**30
    else:
        info = {}
        for ln in Path("/proc/meminfo").read_text().splitlines():
            k, v = ln.split(":", 1)
            info[k] = int(v.split()[0]) / 2**20
        ram = info.get("MemAvailable", 0.0)
        commit = info.get("CommitLimit", 0.0) - info.get("Committed_AS", 0.0)
    ok = commit >= FOLGA_COMMIT_GB and ram >= FOLGA_RAM_GB
    print(f"memória: commit livre {commit:.1f} GB (mínimo {FOLGA_COMMIT_GB}); RAM livre {ram:.1f} GB "
          f"(mínimo {FOLGA_RAM_GB}) -> {'ok' if ok else 'sem folga'}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pasta", default=str(AQUI), help="pasta a conferir ou onde registrar (padrão: esta)")
    ap.add_argument("--portao", nargs=2, metavar=("DIR_DADOS", "LOG"))
    ap.add_argument("--passos", type=int, default=None, help="com --portao: número de passos esperado no log")
    ap.add_argument("--registrar", action="store_true")
    ap.add_argument("--atualizar-readme", action="store_true")
    ap.add_argument("--folga", action="store_true")
    ap.add_argument("--log")
    ap.add_argument("--fixture")
    ap.add_argument("--selo-json")
    ap.add_argument("--sha256-src", default="", help="sha256(src/) do código que gerou o laudo, se não for o atual")
    ap.add_argument("--extra", default="", help="arquivo JSON com chaves extras para gerado_com.json (ex.: nota)")
    a = ap.parse_args(argv)
    if a.folga:
        return folga()
    if a.portao:
        erros = portao(Path(a.portao[0]), Path(a.portao[1]), a.passos)
        for e in erros:
            print("RECUSADO:", e)
        return 1 if erros else 0
    if a.registrar:
        registrar(a)
        return 0
    if a.atualizar_readme:
        return atualizar_readme(Path(a.pasta).resolve())
    problemas = conferir(Path(a.pasta))
    for p in problemas:
        print("NÃO CONFERE:", p)
    print("exemplo: confere" if not problemas else f"exemplo: {len(problemas)} problema(s)")
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
