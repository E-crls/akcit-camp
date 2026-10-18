"""Entradas "bagunçadas" do golden set: o que a fiscal recebe no campo, não o que o sistema gostaria.

Para cada caso de `eval/golden/casos/` (split intacto) gera:
- **DANFE em foto**: o DANFE renderizado a partir do XML da NF-e e "fotografado" em 3 níveis (leve, média,
  pesada: rotação, perspectiva, sombra, dobra, desfoque, ruído, baixa resolução e JPEG), com o fundo da mesa;
- **GTA em papel**: formulário renderizado do JSON da e-GTA, como PDF de scan (nível "scan") e em foto (média
  e pesada). A quantidade é redistribuída em 1 a 3 faixas etárias do mesmo sexo (o total e o sexo não mudam,
  então os rótulos de conciliação do caso continuam valendo); o golden original tem sempre uma faixa só;
- **narração livre da fiscal** (texto como sai do ASR): contagem "no olho", metragem da cerca, item não
  financiado, informação não pedida, números por extenso, erros de ASR e muleta de fala.

Rótulos: valores esperados por campo de cada documento (do XML/JSON) e, por narração, as alegações esperadas
com o status que `conciliar_alegacoes` deve dar com a evidência verdadeira do caso.

Imagens e PDFs vão para `dados_locais/golden_baguncado/<ID>/` (fora do git; ~60 MB); o manifesto com
rótulos, narrações e sha256 de cada arquivo vai para `eval/golden/baguncados/MANIFESTO.yaml`.

Uso (na raiz do repositório):
    scripts/py.sh eval/golden/gerador/gerar_baguncados.py            # todos os casos (semente fixa)
    scripts/py.sh eval/golden/gerador/gerar_baguncados.py --casos GLD-0002 --saida /tmp/x
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
REPO = AQUI.parents[2]

import documentos_imagem as DI

from laudo.docs_fiscais.leitura import sem_acento
from laudo.docs_fiscais.sintetico import por_extenso
from laudo.vision.contagem import ParametrosContagem

VERSAO = "baguncados@0.1.0"
SEMENTE = 20261008
NIVEIS_DANFE = ("leve", "media", "pesada")
NIVEIS_GTA = ("scan", "media", "pesada")
DIR_CASOS = REPO / "eval" / "golden" / "casos"
DIR_SAIDA_ARQ = REPO / "dados_locais" / "golden_baguncado"
MANIFESTO = REPO / "eval" / "golden" / "baguncados" / "MANIFESTO.yaml"
_DATA_PDF = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone(timedelta(hours=-3)))


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _gravar(arq: Path, b: bytes) -> None:
    """Só regrava se o conteúdo mudou (outra avaliação pode estar lendo o arquivo)."""
    if not (arq.is_file() and arq.read_bytes() == b):
        arq.write_bytes(b)


# ---------------------------------------------------------------------------
# Rótulos por campo
# ---------------------------------------------------------------------------


def rotulos_danfe(xml: bytes) -> dict[str, Any]:
    d = DI.dados_danfe(xml)
    r: dict[str, Any] = {
        "chave": d["chave"], "numero": d["numero"], "serie": d["serie"],
        "data_emissao": d["dh_emi"].date().isoformat(), "tp_nf": d["tp_nf"],
        "emitente_doc": d["emitente"]["doc"], "destinatario_doc": d["destinatario"]["doc"],
        "emitente_uf": d["emitente"]["uf"], "destinatario_uf": d["destinatario"]["uf"], "v_prod": d["v_prod"],
        "emitente_municipio": sem_acento(d["emitente"]["mun"]),
    }
    for i, it in enumerate(d["itens"], 1):
        r.update({f"item{i}.ncm": it["ncm"], f"item{i}.cfop": it["cfop"], f"item{i}.unidade": it["unidade"].upper(),
                  f"item{i}.quantidade": it["quantidade"], f"item{i}.valor_unitario": round(it["valor_unitario"], 2),
                  f"item{i}.valor_total": it["valor_total"]})
    return r


def rotulos_gta(g: dict[str, Any]) -> dict[str, Any]:
    q = g["quantidades"]
    r: dict[str, Any] = {
        "uf_emissao": g["uf_emissao"], "numero": g["numero"], "serie": g["serie"],
        "especie": "bubalina" if sem_acento(g["especie"]).startswith(("BUBAL", "BUFAL")) else "bovina",
        "total": sum(x["quantidade"] for x in q),
        "total_machos": sum(x["quantidade"] for x in q if x["sexo"] == "M"),
        "total_femeas": sum(x["quantidade"] for x in q if x["sexo"] == "F"),
        "quantidades_por_faixa": {fx: [sum(x["quantidade"] for x in q if x["faixa_etaria"] == fx and x["sexo"] == s)
                                       for s in ("M", "F")] for fx in DI.FAIXAS
                                  if any(x["faixa_etaria"] == fx for x in q)},
        "finalidade": sem_acento(g["finalidade"]).replace(" ", "_"),
        "data_emissao": g["emissao"]["data"], "validade": g["emissao"]["validade"],
        "chave_nfe": (g.get("nfe_chaves") or [None])[0],
        "observacao": g.get("observacao"),
    }
    for lado in ("origem", "destino"):
        loc = g[lado]
        r.update({f"{lado}.doc": loc["documento"], f"{lado}.uf": loc["uf"], f"{lado}.ibge": loc["municipio_ibge"],
                  f"{lado}.municipio": sem_acento(loc["municipio_nome"]),
                  f"{lado}.codigo_estabelecimento": loc["codigo_estabelecimento"]})
    return r


def redistribuir_faixas(g: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """Mesma espécie, sexo e total; distribuição realista em 1 a 3 faixas etárias contíguas."""
    g = json.loads(json.dumps(g))
    novas = []
    for q in g["quantidades"]:
        n = q["quantidade"]
        k = 1 if n < 3 else rng.choice((1, 2, 2, 3, 3))
        i0 = max(0, min(DI.FAIXAS.index(q["faixa_etaria"]) - rng.randint(0, k - 1), len(DI.FAIXAS) - k))
        faixas = DI.FAIXAS[i0:i0 + k]
        cortes = sorted(rng.sample(range(1, n), k - 1)) if k > 1 else []
        partes = [b - a for a, b in zip([0, *cortes], [*cortes, n], strict=True)]
        novas += [{"sexo": q["sexo"], "faixa_etaria": fx, "quantidade": p} for fx, p in zip(faixas, partes,
                                                                                             strict=True) if p]
    g["quantidades"] = novas
    return g


# ---------------------------------------------------------------------------
# Narração livre
# ---------------------------------------------------------------------------

_FEM = {"vaca", "vaca leiteira", "novilha"}


def extenso(n: int, feminino: bool = False) -> str:
    t = por_extenso(n).lower()
    if feminino:
        t = (t.replace("duzentos", "duzentas").replace("trezentos", "trezentas").replace("quatrocentos", "quatrocentas")
             .replace("quinhentos", "quinhentas"))
        t = " ".join("uma" if w == "um" else "duas" if w == "dois" else w for w in t.split())
    return t.replace("tres", "três")


def _num(n: int, rng: random.Random, feminino: bool = False, p_extenso: float = 0.5) -> str:
    if n < 1000 and rng.random() < p_extenso:
        t = extenso(n, feminino)
        if " e " in t and rng.random() < 0.25:  # ASR engole o "e"
            t = t.replace(" e ", " ", 1)
        return t
    return f"{n:,}".replace(",", ".") if n >= 1000 and rng.random() < 0.5 else str(n)


def narracao(caso: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    itens = caso["operacao"]["itens"]
    bov = next(i for i in itens if i["tipo"] == "bovinos")
    benf = next(i for i in itens if i["tipo"] != "bovinos")
    q_fin = int(bov["quantidade"])
    v = caso["video"]["saida_simulada_contador"]
    real = int(caso["video"]["contagem_real"])
    cat = (bov.get("categoria_animal") or "").lower()
    fem = cat in _FEM
    palavra = {"vaca": "vacas", "vaca leiteira": "vacas", "novilha": "novilhas", "touro": "touros"}.get(cat, "cabeças")
    singular = {"vacas": "vaca", "novilhas": "novilha", "touros": "touro", "cabeças": "cabeça"}
    frases: list[str] = []
    esperadas: list[dict[str, Any]] = []
    sorteio = rng.random()
    if sorteio < 0.5:
        n, origem = real, "contagem_real"
    elif sorteio < 0.75:
        n, origem = q_fin, "ancora_no_financiado"
    else:
        n, origem = max(1, real + rng.choice((-2, -1, 1, 2))), "erro_no_olho"
    abert = rng.choice(["bom dia", "é... bom dia", "então", "ó"])
    if rng.random() < 0.6:
        frases.append(rng.choice([f"{abert} cheguei aqui às {_num(8, rng)} e meia",
                                  (f"{abert} a estrada até a sede tem uns {_num(rng.choice((18, 25, 32)), rng)} km "
                                  "de chão"),
                                  f"{abert} o produtor tem {_num(3, rng)} filhos e todos ajudam no manejo"]))
    else:
        frases.append(abert)
    pal = palavra if rng.random() < 0.7 else "cabeças"
    f_ = pal in ("vacas", "novilhas", "cabeças")
    if n == 1:
        pal = singular[pal]
    nn = _num(n, rng, f_)
    modelos = [f"contei no olho {nn} {pal} no curral né",  # número antes do substantivo
               f"no curral tinha {nn} {pal} contando no olho",
               f"passei o lote no corredor e deu {nn} {pal}",
               f"{pal} no curral, contei {nn}",  # substantivo antes do número
               f"contei {nn} no corredor, tudo {pal}"]
    if n != q_fin:  # dois números na frase: só o segundo é a contagem
        modelos.append(f"das {_num(q_fin, rng, f_)} que ele comprou eu achei {nn} no curral")
    frases.append(rng.choice(modelos))
    pc = ParametrosContagem()  # os mesmos limiares de abstenção do contador (e do simulador do harness)
    conf_ok = (v["confianca"] >= pc.limiar_conf_media and v.get("oclusao_frac", 0) <= pc.max_oclusao
               and not (v["estimativa"] > 0 and (v["ic80"][1] - v["ic80"][0]) / 2
                        > max(1.0, pc.max_meia_largura_rel * v["estimativa"])))
    if conf_ok:
        st = "confere" if v["ic80"][0] <= n <= v["ic80"][1] else "divergente"
        ev = f"vídeo {v['estimativa']} [{v['ic80'][0]}–{v['ic80'][1]}]"
    else:  # contagem abstida: a referência passa a ser a NF-e
        cab_nf = caso.get("_cabecas_nf")
        st = "sem_evidencia" if cab_nf is None else ("confere" if cab_nf == n else "divergente")
        ev = f"contagem abstida; NF {cab_nf}"
    esperadas.append({"grandeza": "quantidade", "valor": n, "item_id": bov["id"], "status": st, "origem": origem,
                      "evidencia": ev})
    if benf["tipo"] == "cerca":
        L = int(benf["quantidade"])
        s2 = rng.random()
        if s2 < 0.55:
            frases.append(rng.choice([f"a cerca tá pronta, uns {_num(L, rng)} metros de arame",
                                      f"cerca nova com {_num(L, rng)} metros, tudo esticado"]))
            esperadas.append({"grandeza": "comprimento", "valor": L, "item_id": benf["id"], "status": "confere"})
        elif s2 < 0.85:
            m = int(round(L * rng.uniform(0.55, 0.85) / 50) * 50)
            frases.append(rng.choice([f"a cerca fizeram só uns {_num(m, rng)} metros, o resto não saiu",
                                      f"da cerca só tem {_num(m, rng)} metro feito"]))
            esperadas.append({"grandeza": "comprimento", "valor": m, "item_id": benf["id"], "status": "pendente"})
        else:
            frases.append("a cerca eu passei de longe")
    else:
        frases.append(rng.choice(["o curral tá pronto, com brete e tronco", "curral novo, tronco e porteira"]))
    if rng.random() < 0.5:
        alvo = rng.choice(["galpao", "bezerros", "garrotes" if fem else "bezerros"])
        if alvo == "galpao":
            a = rng.choice((150, 200, 300))
            frases.append(f"ele fez também um galpão de {_num(a, rng)} metros quadrados com dinheiro dele")
            esperadas.append({"grandeza": "area", "valor": a, "item_id": None, "status": "registro"})
        elif alvo == "bezerros":
            b = rng.choice((4, 6, 9))
            frases.append(f"tem também uns {_num(b, rng)} bezerros que nasceram aqui")
            esperadas.append({"grandeza": "quantidade", "valor": b, "item_id": None, "status": "registro"})
        else:
            gq = rng.choice((10, 15, 22))
            frases.append(f"o produtor disse que comprou {_num(gq, rng)} garrotes por fora com dinheiro próprio")
            esperadas.append({"grandeza": "quantidade", "valor": gq, "item_id": None, "status": "registro"})
    if rng.random() < 0.4:
        frases.append(rng.choice(["o pasto tá seco mas tem água", "a nota fiscal ficou com o gerente", "tá calor"]))
    sep = rng.choice([". ", ", ", " "])
    texto = sep.join(frases)
    return {"texto": texto, "alegacoes_esperadas": esperadas, "crenca_fiscal": {"contagem": n},
            "palavras": len(texto.split())}


# ---------------------------------------------------------------------------
# Geração
# ---------------------------------------------------------------------------


def gerar_caso(cid: str, info: dict[str, Any], saida_arq: Path) -> dict[str, Any]:
    d = DIR_CASOS / cid
    caso = yaml.safe_load((d / "caso.yaml").read_text(encoding="utf-8"))
    rng = random.Random(f"{SEMENTE}:{cid}:baguncado")
    destino = saida_arq / cid
    destino.mkdir(parents=True, exist_ok=True)
    arquivos: list[dict[str, Any]] = []
    rot_nfe = []
    for k, nf in enumerate(caso["documentos"]["nfe"], 1):
        xml = (d / nf["arquivo"]).read_bytes()
        rot = rotulos_danfe(xml)
        rot_nfe.append(rot)
        img = DI.renderizar_danfe(xml)
        for nivel in NIVEIS_DANFE:
            foto, meta = DI.fotografar(img, nivel, random.Random(f"{SEMENTE}:{cid}:danfe{k}:{nivel}"))
            b = DI.jpeg_bytes(foto, meta["jpeg_q"])
            nome = f"danfe_{k}_{nivel}.jpg"
            _gravar(destino / nome, b)
            arquivos.append({"arquivo": nome, "tipo": "danfe", "doc": k, "fonte": nf["arquivo"], "nivel": nivel,
                             "formato": "jpg", "sha256": _sha(b), "meta": meta})
    unid = [(r[kk], r[kk.replace("quantidade", "unidade")]) for r in rot_nfe for kk in r if kk.endswith(".quantidade")]
    caso["_cabecas_nf"] = (int(sum(q for q, _ in unid)) if unid and all(u in ("CB", "CAB", "UN", "CABECA")
                                                                       for _, u in unid) else None)
    rot_gta = []
    gtas_json = []
    for k, g in enumerate(caso["documentos"]["gta"], 1):
        bruto = json.loads((d / g["arquivo_json"]).read_text(encoding="utf-8"))
        gv = redistribuir_faixas(bruto, random.Random(f"{SEMENTE}:{cid}:gta{k}:faixas"))
        gtas_json.append(gv)
        rot_gta.append(rotulos_gta(gv))
        img = DI.renderizar_gta(gv)
        for nivel in NIVEIS_GTA:
            r2 = random.Random(f"{SEMENTE}:{cid}:gta{k}:{nivel}")
            if nivel == "scan":  # scanner de mesa: plano, leve desfoque, 150 dpi, PDF
                from PIL import ImageFilter

                b = DI.pdf_bytes(img.filter(ImageFilter.GaussianBlur(0.5)), data=_DATA_PDF)
                nome, meta = f"gta_{k}_scan.pdf", {"nivel": "scan", "tamanho": list(img.size)}
            else:
                foto, meta = DI.fotografar(img, nivel, r2)
                b = DI.jpeg_bytes(foto, meta["jpeg_q"])
                nome = f"gta_{k}_{nivel}.jpg"
            _gravar(destino / nome, b)
            arquivos.append({"arquivo": nome, "tipo": "gta", "doc": k, "fonte": g["arquivo_json"], "nivel": nivel,
                             "formato": nome.rsplit(".", 1)[1], "sha256": _sha(b), "meta": meta})
    nar = narracao(caso, rng)
    caso.pop("_cabecas_nf", None)
    return {"id": cid, "split": info["split"], "classe": info["classe"], "codigo": info["codigo"],
            "arquivos": arquivos, "rotulos": {"danfe": rot_nfe, "gta": rot_gta},
            "gtas_variante": gtas_json, "narracao": nar}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--casos", nargs="*")
    ap.add_argument("--saida", default=None, help="diretório dos arquivos (padrão dados_locais/golden_baguncado)")
    ap.add_argument("--manifesto", default=str(MANIFESTO))
    a = ap.parse_args(argv)
    split = yaml.safe_load((DIR_CASOS / "SPLIT.yaml").read_text(encoding="utf-8"))
    infos = {c["id"]: c for c in split["casos"]}
    ids = a.casos or [c["id"] for c in split["casos"]]
    saida = Path(a.saida) if a.saida else DIR_SAIDA_ARQ
    casos = []
    for cid in ids:
        casos.append(gerar_caso(cid, infos[cid], saida))
        print(cid, len(casos[-1]["arquivos"]), "arquivos", flush=True)
    sha_cont = {}
    for parte in ("dev", "test"):
        linhas = "".join(f"{c['id']}:" + _sha(json.dumps(c, sort_keys=True, ensure_ascii=False, default=str)
                                               .encode()) + "\n" for c in casos if c["split"] == parte)
        sha_cont[parte] = _sha(linhas.encode())
    meta = {"versao": VERSAO, "semente": SEMENTE, "gerado_em": "2026-10-08",
            "split_origem": {"sha256_split": split["sha256_split"], "sha256_conteudo": split["sha256_conteudo"]},
            "fontes": {k: Path(v).name for k, v in DI.fontes_usadas().items()},
            "niveis": {"danfe": list(NIVEIS_DANFE), "gta": list(NIVEIS_GTA), "parametros": DI.NIVEIS},
            "sha256_conteudo": sha_cont, "n_casos": len(casos),
            "n_arquivos": sum(len(c["arquivos"]) for c in casos), "casos": casos}
    m = Path(a.manifesto)
    m.parent.mkdir(parents=True, exist_ok=True)
    m.write_bytes(yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=110).encode("utf-8"))
    print("manifesto:", m, "sha256_conteudo:", sha_cont)
    return 0


if __name__ == "__main__":
    sys.exit(main())
