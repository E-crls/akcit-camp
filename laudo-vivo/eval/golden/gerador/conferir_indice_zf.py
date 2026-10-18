"""Golden DEV no modo determinístico: índice de documentos ligado e NF-e com o grupo ZF realista (de GO).

Uso (na raiz do repositório):
    scripts/py.sh eval/golden/gerador/conferir_indice_zf.py                 # 36 casos do dev, dois modos
    scripts/py.sh eval/golden/gerador/conferir_indice_zf.py --casos GLD-0023 GLD-0055 --saida <dir>

Roda os casos do DEV (o TESTE congelado não é tocado) duas vezes, com o condutor real sem LLM, a integração
`app` e os contornos de `eval/harness.py` (os mesmos de `eval/run_eval.py --modo deterministico`):

- `base`: como está no produto hoje, numa instalação sem laudo selado (o executor consulta o índice do
  diretório de dados do caso, que está vazio; nada é registrado);
- `indice_zf`: (a) `conciliar_nfe`/`conciliar_gta` consultam um índice de documentos COMPARTILHADO pelos casos
  (`indice_documentos` fixado no índice compartilhado + `operacao_ref` = ref. Bacen); (b) no fim de cada caso
  o laudo é "selado" e os documentos que comprovaram o item vão para o índice
  (`indice.registrar_fiscalizacao`: a mesma seleção de `laudo.agent.indice.registrar_na_selagem`, sem a
  etapa SELADO), na ordem do split; (c) cada NF-e passa a trazer o grupo ZF com UMA guia
  (NT 2024.003; ZF05-10 ativa em GO para NCM 0102, regras em produção desde 01/03/2026): a GTA vinculada à
  nota no SIDAGO
  (`nfe_chaves`), senão a k-ésima GTA para a k-ésima nota, senão a 1ª. Só `conciliar_gta` lê a cópia com o
  grupo (a assinatura da cópia não confere; `conciliar_nfe` segue com o XML original).

Mede, por modo: over-blocking nos válidos (algum grupo do laudo diferente de verificado: a métrica
`campos_rotulados` de `eval/metrics.py`), rascunho bloqueado nos válidos, divergências campo × rótulo (grupo
do laudo contra o rótulo do golden), reusos acusados e campos `documento:gta:nfe_guia` não ok. Grava
`<saida>/relatorio.json` e sai 1 se o modo `indice_zf` mudar algum status do laudo, acusar reuso ou deixar
`nfe_guia` não ok.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

_AQUI = Path(__file__).resolve().parent
_REPO = _AQUI.parents[2]
for p in (_AQUI, _REPO / "eval", _REPO / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import casos_publicos as CP
import harness as H
from lxml import etree

from laudo.docs_fiscais import indice as I

NS = "http://www.portalfiscal.inf.br/nfe"
_RE_CHAVE = re.compile(rb'Id="NFe(\w{44})"')


def _com_grupo_zf(xml: bytes, g: dict[str, Any]) -> bytes:
    raiz = etree.fromstring(xml)
    inf = raiz.find(f".//{{{NS}}}infNFe")
    gt = etree.SubElement(etree.SubElement(inf, f"{{{NS}}}agropecuario"), f"{{{NS}}}guiaTransito")
    for k, v in (("tpGuia", "1"), ("UFGuia", g.get("uf_emissao")), ("serieGuia", g.get("serie")),
                 ("nGuia", g.get("numero"))):
        if v:
            etree.SubElement(gt, f"{{{NS}}}{k}").text = str(v)
    return etree.tostring(raiz, xml_declaration=True, encoding="UTF-8")


def notas_com_zf(caso: dict[str, Any], dcaso: Path, destino: Path) -> dict[str, str]:
    """Cópias das NF-e do caso com o grupo ZF (uma guia por nota): caminho original → caminho da cópia."""
    gtas = [json.loads((dcaso / g["arquivo_json"]).read_text(encoding="utf-8"))
            for g in caso["documentos"]["gta"]]
    if not gtas:
        return {}
    destino.mkdir(parents=True, exist_ok=True)
    mapa = {}
    for k, nf in enumerate(caso["documentos"]["nfe"]):
        orig = dcaso / nf["arquivo"]
        xml = orig.read_bytes()
        m = _RE_CHAVE.search(xml)
        chave = m.group(1).decode() if m else None
        g = next((g for g in gtas if chave and chave in (g.get("nfe_chaves") or [])), None)
        g = g or (gtas[k] if k < len(gtas) else gtas[0])
        copia = destino / f"{caso['id']}_{nf['arquivo']}"
        copia.write_bytes(_com_grupo_zf(xml, g))
        mapa[str(orig)] = str(copia)
    return mapa


def _com_nfes_trocadas(ferr, mapa: dict[str, str]):
    from laudo.contracts import Ferramenta

    def funcao(args):
        d = args.model_dump(mode="json")
        d["nfe_caminhos"] = [mapa.get(p, p) for p in d.get("nfe_caminhos") or []]
        return ferr.funcao(ferr.entrada.model_validate(d))

    return Ferramenta(nome=ferr.nome, descricao=ferr.descricao, entrada=ferr.entrada, funcao=funcao,
                      deterministica=ferr.deterministica, timeout_s=ferr.timeout_s)


def rodar_caso(caso: dict[str, Any], amb: Any, modo: str, indice: Path) -> dict[str, Any]:
    dcaso = H.DIR_CASOS / caso["id"]
    reg = H.montar_registro(caso, dcaso, "app", H.saidas_video_do_caso(caso))
    if modo == "indice_zf":
        mapa = notas_com_zf(caso, dcaso, amb.dir / "nfe_com_zf")
        reg["conciliar_gta"] = _com_nfes_trocadas(reg["conciliar_gta"], mapa)
        extras = {"indice_documentos": str(indice), "operacao_ref": caso["operacao"]["ref_bacen"]}
        for nome in ("conciliar_nfe", "conciliar_gta"):
            reg[nome] = H.ferramenta_com_contexto(reg[nome], extras)
    cond, fis, dcaso, dtrab = H.preparar_condutor(caso, amb, None, "app", registro=reg)
    for t in H.roteiro_caso(caso, dcaso, dtrab):
        H.executar_turno(cond, fis.id, t)
    fim = H.estado_final(cond, fis.id)
    grupos = {g: {"esperado": e,
                  "sistema": (fim["campos"].get(H.campo_sistema(caso, g)) or {}).get("status", "ausente")}
              for g, e in H.esperado_por_grupo(caso).items()}
    selados = I.registrar_fiscalizacao(indice, fim["fis"]) if modo == "indice_zf" else 0
    return {"id": caso["id"], "classe": caso["classe"], "grupos": grupos,
            "finos": CP.campos_finos(fim["fis"]), "emissao_permitida": fim["emissao_permitida"],
            "selados": selados}


def resumir(rs: list[dict[str, Any]]) -> dict[str, Any]:
    validos = [r for r in rs if r["classe"] == "valido"]
    ob = [r["id"] for r in validos if any(v["sistema"] != "verificado" for v in r["grupos"].values())]
    bloq = [r["id"] for r in validos if not r["emissao_permitida"]]
    div = [f"{r['id']}:{g} ({v['esperado']}→{v['sistema']})" for r in rs for g, v in r["grupos"].items()
           if v["esperado"] != v["sistema"]]
    reuso = [f"{r['id']}:{c}={s}" for r in rs for c, s in r["finos"].items() if c.endswith(":reuso")
             and s != "verificado"]
    zf = [f"{r['id']}={r['finos'][c]}" for r in rs for c in r["finos"] if c == "documento:gta:nfe_guia"]
    zf_nao_ok = [x for x in zf if not x.endswith("=verificado")]
    return {"casos": len(rs), "validos": len(validos), "over_blocking": ob, "rascunho_bloqueado": bloq,
            "divergencias_campo_rotulo": div, "reusos_acusados": reuso, "nfe_guia": len(zf),
            "nfe_guia_nao_ok": zf_nao_ok, "selados_no_indice": sum(r["selados"] for r in rs)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--casos", nargs="*", default=None, help="ids do DEV (padrão: todos os 36)")
    ap.add_argument("--saida", type=Path, default=_REPO / "dados_locais" / "eval" / "indice_zf")
    a = ap.parse_args(argv)
    split = H.carregar_split()
    ids = a.casos or list(split["dev"])
    fora = [c for c in ids if c not in split["dev"]]
    if fora:
        print(f"só casos do DEV (o TESTE está congelado): {fora}")
        return 2
    rel: dict[str, Any] = {"casos": ids, "split_sha256": split["sha256_split"]}
    por_modo: dict[str, list[dict[str, Any]]] = {}
    for modo in ("base", "indice_zf"):
        amb = H.Ambiente(base=a.saida, rotulo=modo)
        indice = amb.dir / "indices" / "documentos.jsonl"
        por_modo[modo] = [rodar_caso(H.carregar_caso(cid), amb, modo, indice) for cid in ids]
        rel[modo] = resumir(por_modo[modo])
    mudou = [f"{b['id']}:{g} ({b['grupos'][g]['sistema']}→{i['grupos'][g]['sistema']})"
             for b, i in zip(por_modo["base"], por_modo["indice_zf"], strict=True)
             for g in b["grupos"] if b["grupos"][g]["sistema"] != i["grupos"][g]["sistema"]]
    rel["status_do_laudo_mudou"] = mudou
    texto = json.dumps(rel, ensure_ascii=False, indent=1)
    rel["sha256_relatorio"] = hashlib.sha256(texto.encode()).hexdigest()
    a.saida.mkdir(parents=True, exist_ok=True)
    (a.saida / "relatorio.json").write_text(json.dumps(rel, ensure_ascii=False, indent=1), encoding="utf-8")
    for modo in ("base", "indice_zf"):
        r = rel[modo]
        print(f"{modo}: {r['casos']} casos do dev | over-blocking {len(r['over_blocking'])}/{r['validos']} "
              f"válidos | rascunho bloqueado {len(r['rascunho_bloqueado'])}/{r['validos']} | campo×rótulo "
              f"{len(r['divergencias_campo_rotulo'])} | reusos {len(r['reusos_acusados'])} | nfe_guia "
              f"{r['nfe_guia']} campos, {len(r['nfe_guia_nao_ok'])} não ok | selados "
              f"{r['selados_no_indice']}")
    detalhe = f" ({'; '.join(mudou)})" if mudou else ""
    print(f"status do laudo que mudou entre os modos: {len(mudou)}{detalhe}")
    ruim = mudou or rel["indice_zf"]["reusos_acusados"] or rel["indice_zf"]["nfe_guia_nao_ok"]
    return 1 if ruim else 0


if __name__ == "__main__":
    raise SystemExit(main())
