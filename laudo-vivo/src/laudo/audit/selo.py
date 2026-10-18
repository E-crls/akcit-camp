"""Verificação do laudo selado que cobre o **conteúdo**, a partir da cadeia de hash
(`audit.hashchain`).

O selo (`tools/laudo.py::selar`) é `sha256(canônico({hash_raiz, aprovacoes}))`: conferir só essa
fórmula deixaria passar uma cópia do laudo selado com um valor trocado (o `hash_raiz` e as assinaturas continuam
os mesmos). O que o humano assinou é o `hash_raiz` do **rascunho**:
`sha256(raiz_da_cadeia_na_emissão | canônico(conteúdo))` (`hashchain.hash_raiz_laudo`). O laudo selado repete
o conteúdo do rascunho e só muda `tipo`, `gerado_em`, `assinaturas` e `cadeia` (mais `selo`). A verificação:

1. recalcula o selo (`selo_v1`) e confere que cada assinatura é do `hash_raiz` do laudo;
2. **reconstrói o conteúdo assinado** = o laudo selado com os 4 campos do momento da emissão (do bloco
   `conteudo_assinado` do próprio laudo, gravado por `selar`, ou do rascunho que está na cadeia)
   e **recalcula o `hash_raiz`**: qualquer valor alterado no JSON selado (ou no rascunho) faz divergir;
3. com a cadeia (evidências do estado): confere que ela está íntegra, que o rascunho é a evidência
   `documento` com `meta.laudo` e esse `hash_raiz`, com o sha256 do arquivo registrado nela, emitido sobre a
   raiz que o laudo declara, e que a raiz do selado é um elo da cadeia;
4. com o HTML: renderiza de novo o laudo verificado e compara (o HTML é uma visão do JSON; se diverge, ou o
   HTML foi editado ou o template mudou depois do selo, e nos dois casos o HTML não é prova). Se o laudo
   declarar o sha256 do template com que foi gerado (`template.sha256`, gravado por `montar_laudo`) e ele
   não for o atual, o HTML fica "não conferível" (aviso) em vez de "não confere": um laudo arquivado não
   passa a ser inválido porque o template mudou;
5. com as aprovações do estado: as assinaturas do laudo são as gravadas na fiscalização.

`Condutor.assinar` roda esta verificação ao selar e devolve o motivo quando o selado não confere.

Escopo: a verificação fecha a cópia adulterada. Sem chave de quem assina, quem tem acesso ao disco consegue
refazer laudo, rascunho, estado e selo de forma coerente; isso fica para a credencial por usuário, a chave
por fiscal e o recibo enviado à IF.

Uso: `scripts/py.sh -m laudo.audit.selo --dados <dir de dados> <fis_id>` (código 0 = válido, 1 = não confere).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from laudo.audit import hashchain
from laudo.contracts import Evidencia

TEMPLATE_LAUDO = Path(__file__).resolve().parents[1] / "agent" / "templates" / "laudo.html.j2"
# Campos que mudam do rascunho assinado para o laudo selado; todo o resto é conteúdo assinado.
CAMPOS_DO_SELO = ("tipo", "gerado_em", "assinaturas", "cadeia")
# Campos que não fazem parte do conteúdo hasheado (o hash, o selo e o bloco que guarda os campos da emissão).
FORA_DO_CONTEUDO = ("hash_raiz", "selo", "conteudo_assinado")


class ResultadoSelo(BaseModel):
    valido: bool
    selo_confere: bool = False
    assinatura_confere: bool = False
    conteudo_confere: bool | None = None  # None: não deu para conferir (sem rascunho nem `conteudo_assinado`)
    cadeia_confere: bool | None = None  # None: sem as evidências do estado
    html_confere: bool | None = None  # None: sem HTML
    aprovacoes_conferem: bool | None = None  # None: sem as aprovações do estado
    hash_raiz: str = ""
    hash_raiz_recalculado: str = ""
    origem_conteudo: str = ""  # conteudo_assinado | rascunho
    divergencias: list[str] = Field(default_factory=list)
    avisos: list[str] = Field(default_factory=list)  # o que não deu para conferir, sem invalidar

    @property
    def motivo(self) -> str:
        if self.divergencias:
            return "; ".join(self.divergencias)
        return "laudo selado confere" + (f" ({'; '.join(self.avisos)})" if self.avisos else "")


def selo_v1(laudo: dict[str, Any]) -> str:
    """Selo como `tools/laudo.py::selar` calcula (sozinho, não cobre o conteúdo; ver o módulo)."""
    return hashchain.sha256_hex(
        hashchain.canonico({"hash_raiz": laudo.get("hash_raiz"), "aprovacoes": laudo.get("assinaturas")})
    )


def _corpo(laudo: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in laudo.items() if k not in FORA_DO_CONTEUDO}


def hash_do_conteudo(conteudo: dict[str, Any]) -> str:
    """`hash_raiz` de um conteúdo de laudo (sem `hash_raiz`/`selo`), sobre a raiz que ele mesmo declara."""
    raiz = str((conteudo.get("cadeia") or {}).get("raiz") or "")
    return hashchain.hash_raiz_laudo(raiz, conteudo)


def conteudo_assinado(laudo: dict[str, Any], rascunho: dict[str, Any] | None = None
                      ) -> tuple[dict[str, Any], str] | None:
    """O conteúdo que o humano assinou, reconstruído a partir do laudo selado: os campos do momento da
    emissão vêm do bloco `conteudo_assinado` do laudo (formato proposto para `selar`) ou do rascunho. None se
    não há de onde."""
    if isinstance(laudo.get("conteudo_assinado"), dict):
        emissao, origem = laudo["conteudo_assinado"], "conteudo_assinado"
    elif rascunho is not None:
        emissao, origem = rascunho, "rascunho"
    else:
        return None
    faltam = [k for k in CAMPOS_DO_SELO if k not in emissao]
    if faltam:
        return None
    return {**_corpo(laudo), **{k: emissao[k] for k in CAMPOS_DO_SELO}}, origem


def diferencas_de_conteudo(laudo: dict[str, Any], rascunho: dict[str, Any]) -> list[str]:
    """Campos de conteúdo em que dois laudos diferem (fora os do selo), com o índice quando é lista: diz o
    que foi alterado no selado em relação ao rascunho assinado."""
    a, b = _corpo(laudo), _corpo(rascunho)
    chaves = sorted((set(a) | set(b)) - set(CAMPOS_DO_SELO))
    saida = []
    for k in chaves:
        if hashchain.canonico(a.get(k)) == hashchain.canonico(b.get(k)):
            continue
        if isinstance(a.get(k), list) and isinstance(b.get(k), list) and len(a[k]) == len(b[k]):
            idx = [i for i, (x, y) in enumerate(zip(a[k], b[k]))
                   if hashchain.canonico(x) != hashchain.canonico(y)]
            saida.append(f"{k}[{', '.join(map(str, idx[:5]))}]")
        else:
            saida.append(k)
    return saida


def _evidencia_do_rascunho(evidencias: list[Evidencia], hash_raiz: str) -> tuple[int, Evidencia] | None:
    for i, e in enumerate(evidencias):
        if e.tipo == "documento" and e.meta.get("laudo") and e.meta.get("hash_raiz") == hash_raiz:
            return i, e
    return None


def ler_laudo(caminho: str | Path | None) -> dict[str, Any] | None:
    """JSON de um laudo (rascunho ou selado) no disco; None se ausente ou ilegível."""
    lido = _ler_json(caminho)
    return lido[0] if lido is not None else None


def _ler_json(caminho: str | Path | None) -> tuple[dict[str, Any], bytes] | None:
    if not caminho or not Path(caminho).is_file():
        return None
    b = Path(caminho).read_bytes()
    try:
        return json.loads(b.decode("utf-8")), b
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _sem_cr(x: str | bytes) -> bytes:
    b = x.encode("utf-8") if isinstance(x, str) else x
    return b.replace(b"\r\n", b"\n")  # o laudo é gravado com write_text: no Windows, CRLF


def sha256_template_laudo() -> str | None:
    """sha256 do template HTML atual do laudo (sem CR), para comparar com o `template.sha256` do laudo."""
    if not TEMPLATE_LAUDO.is_file():
        return None
    return hashlib.sha256(_sem_cr(TEMPLATE_LAUDO.read_bytes())).hexdigest()


def verificar_laudo(
    laudo: dict[str, Any],
    *,
    evidencias: Iterable[Evidencia] | None = None,
    rascunho: dict[str, Any] | None = None,
    rascunho_bytes: bytes | None = None,
    aprovacoes: list[dict[str, Any]] | None = None,
    html: str | bytes | None = None,
    renderizar: Callable[[dict[str, Any]], str] | None = None,
) -> ResultadoSelo:
    """Confere o laudo selado: selo, assinatura, conteúdo (recalculando o `hash_raiz`), cadeia, HTML e
    aprovações.

    `evidencias`: as do estado (a cadeia); sem `rascunho`, o rascunho é lido do arquivo da evidência dela.
    `renderizar`: laudo → HTML (padrão: `tools.laudo.renderizar_html`, importado só quando há HTML)."""
    hash_raiz = str(laudo.get("hash_raiz") or "")
    r = ResultadoSelo(valido=False, hash_raiz=hash_raiz)
    div = r.divergencias
    if laudo.get("tipo") != "selado":
        div.append(f"o laudo não é o selado (tipo {laudo.get('tipo')!r})")
    r.selo_confere = bool(laudo.get("selo")) and selo_v1(laudo) == laudo.get("selo")
    if not r.selo_confere:
        div.append("selo não confere com {hash_raiz, assinaturas}")
    assinaturas = laudo.get("assinaturas") or []
    r.assinatura_confere = bool(assinaturas) and all(
        isinstance(a, dict) and a.get("hash_assinado") == hash_raiz for a in assinaturas
    )
    if not r.assinatura_confere:
        div.append("sem assinatura humana do hash raiz do laudo")

    # rascunho assinado: da cadeia (arquivo com o sha256 registrado nela) ou passado pelo chamador
    evs = list(evidencias) if evidencias is not None else None
    elo = _evidencia_do_rascunho(evs, hash_raiz) if evs is not None else None
    if evs is not None:
        cad = hashchain.verificar_cadeia(evs)
        problemas = [] if cad.integra else [f"cadeia de hash quebrada ({cad.motivo})"]
        if elo is None:
            problemas.append("a cadeia não tem o rascunho com este hash raiz")
        if rascunho is None and elo is not None:
            lido = _ler_json(elo[1].caminho)
            if lido is None:
                problemas.append("arquivo do rascunho assinado ausente ou ilegível")
            else:
                rascunho, rascunho_bytes = lido
        if elo is not None and rascunho_bytes is not None \
                and hashlib.sha256(rascunho_bytes).hexdigest() != elo[1].sha256:
            problemas.append("o arquivo do rascunho não é o registrado na cadeia (sha256 diverge)")
        if elo is not None and rascunho is not None \
                and (rascunho.get("cadeia") or {}).get("raiz") != elo[1].hash_anterior:
            problemas.append("o rascunho declara uma raiz de cadeia que não é a da emissão")
        sel = laudo.get("cadeia") or {}
        n = sel.get("n")
        elo_ok = (isinstance(n, int) and 0 < n <= len(evs)
                  and hashchain.hash_elo(evs[n - 1]) == sel.get("raiz"))
        if not elo_ok:
            problemas.append("a raiz da cadeia no laudo selado não é um elo da cadeia")
        r.cadeia_confere = not problemas
        div += problemas

    # conteúdo: recalcula o hash raiz do que o humano assinou
    rec = conteudo_assinado(laudo, rascunho)
    if rec is None:
        r.conteudo_confere = None
        div.append("conteúdo não conferível: falta o rascunho assinado (cadeia) ou o bloco conteudo_assinado")
    else:
        conteudo, r.origem_conteudo = rec
        r.hash_raiz_recalculado = hash_do_conteudo(conteudo)
        selado_ok = r.hash_raiz_recalculado == hash_raiz
        rascunho_ok = rascunho is None or hash_do_conteudo(_corpo(rascunho)) == hash_raiz
        r.conteudo_confere = selado_ok and rascunho_ok
        if not rascunho_ok:
            div.append("o rascunho assinado foi alterado (o hash raiz recalculado dele diverge do assinado)")
        if not selado_ok:
            alterados = diferencas_de_conteudo(laudo, rascunho) if rascunho is not None else []
            div.append("conteúdo do laudo selado diverge do assinado (hash raiz recalculado "
                       f"{r.hash_raiz_recalculado[:12]} ≠ {hash_raiz[:12]})"
                       + (f": {', '.join(alterados)}" if alterados else ""))

    if aprovacoes is not None:
        r.aprovacoes_conferem = hashchain.canonico(aprovacoes) == hashchain.canonico(assinaturas)
        if not r.aprovacoes_conferem:
            div.append("as assinaturas do laudo não são as aprovações gravadas na fiscalização")

    if html is not None:
        if renderizar is None:
            from laudo.tools.laudo import renderizar_html as renderizar  # visão do JSON (template do laudo)
        r.html_confere = _sem_cr(html) == _sem_cr(renderizar(laudo))
        tpl = laudo.get("template") if isinstance(laudo.get("template"), dict) else {}
        if not r.html_confere and tpl.get("sha256") and tpl["sha256"] != sha256_template_laudo():
            r.html_confere = None
            r.avisos.append("HTML não conferível: o template do laudo mudou depois do selo (vale o JSON)")
        elif not r.html_confere:
            div.append("o HTML não é a renderização do laudo selado (editado, ou o template mudou depois do "
                       "selo)")

    r.valido = (not div and r.selo_confere and r.assinatura_confere and bool(r.conteudo_confere)
                and r.cadeia_confere is not False and r.html_confere is not False
                and r.aprovacoes_conferem is not False)
    return r


def verificar_em_disco(dir_laudos: str | Path, fis: Any | None = None,
                       renderizar: Callable[[dict[str, Any]], str] | None = None) -> ResultadoSelo:
    """`laudo_selado.json` e `.html` de `dir_laudos`, com a cadeia e as aprovações de `fis` (Fiscalizacao) se
    houver; sem `fis`, o rascunho é procurado pelo nome (`rascunho_<hash12>.json`)."""
    d = Path(dir_laudos)
    lido = _ler_json(d / "laudo_selado.json")
    if lido is None:
        return ResultadoSelo(valido=False, divergencias=["laudo_selado.json ausente ou ilegível"])
    laudo, _ = lido
    ph = d / "laudo_selado.html"
    html = ph.read_bytes() if ph.is_file() else None
    kw: dict[str, Any] = {}
    if fis is not None:
        kw["evidencias"] = fis.evidencias
        kw["aprovacoes"] = [a.model_dump(mode="json") for a in fis.aprovacoes]
    else:
        r = _ler_json(d / f"rascunho_{str(laudo.get('hash_raiz') or '')[:12]}.json")
        if r is not None:
            kw["rascunho"], kw["rascunho_bytes"] = r
    res = verificar_laudo(laudo, html=html, renderizar=renderizar, **kw)
    if html is None:
        res.divergencias.append("laudo_selado.html ausente")
        res.valido = False
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Confere o laudo selado (selo, conteúdo, cadeia, HTML).")
    ap.add_argument("--dados", type=Path, default=None, help="diretório de dados (padrão: LAUDO_DADOS_DIR)")
    ap.add_argument("fis_id")
    a = ap.parse_args(argv)
    from laudo.agent import estado as est

    dados = a.dados or est.diretorio_dados()
    fis = est.RepositorioFiscalizacoes(dados).carregar(a.fis_id)
    res = verificar_em_disco(dados / "laudos" / a.fis_id, fis)
    print(json.dumps({**res.model_dump(), "motivo": res.motivo}, ensure_ascii=False, indent=1))
    return 0 if res.valido else 1


if __name__ == "__main__":
    sys.exit(main())
