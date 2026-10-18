"""Torna fictícia a operação do caso da demo (eval/golden/demo/DEMO-0001) sem perder o realismo.

O gerador (`eval/golden/gerador/gerar_casos.py --so-demo`) monta o DEMO-0001 a partir de uma operação
pública do Fiscal-GO 2026 (Sicor/BCB) e planta divergências, pressão e injeção. Uma operação real e
identificável não pode aparecer com defeitos plantados: este script reescreve o caso para que ele não
aponte para nenhuma operação, propriedade ou produtor reais:

- REF_BACEN → `000000001` (não existe no Sicor) e instituição → cooperativa fictícia;
- data de contratação −4 dias, valor do lote +R$ 1.000 e área +0,04 ha (quebra a busca exata no bench público,
  que está no repositório; a lotação continua em 6,0 cab/ha e a triagem, em prioridade média);
- gleba espelhada, girada 35° e deslocada ~4,2 km (dentro do mesmo município, longe de qualquer gleba
  do bench) e o GPS das fotos (EXIF e app) pela mesma transformação rígida: as distâncias à borda (~650 m
  e de dentro) não mudam;
- textos de origem e aviso trocados, bloco `demonstracao:` com a marca d'água.

Mantidos: município (densidade bovina do IBGE), finalidade, empreendimento, 29 vacas leiteiras, a cerca de
1.200 m do projeto sintético, NF-e e GTA sintéticas (não citam REF, IF, data de contratação nem a gleba).

Uso (depois de regerar o caso; idempotente: recusa caso já mascarado):
    scripts/py.sh eval/golden/gerador/gerar_casos.py --so-demo
    scripts/py.sh scripts/mascarar_demo.py
    scripts/py.sh scripts/mascarar_demo.py --verificar      # só confere (sai com 1 se o caso for o real)
"""

from __future__ import annotations

import argparse
import hashlib
import io
import struct
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import shapely
import yaml
from PIL import Image
from pyproj import Transformer
from shapely import affinity, wkt
from shapely.geometry import Point, Polygon

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

CASO = REPO / "eval" / "golden" / "demo" / "DEMO-0001"
REF_DEMO = "000000001"
IF_DEMO = "COOPERATIVA DE CRÉDITO DEMONSTRAÇÃO (fictícia)"
FONTE_DEMO = "sintetico+sicor_derivado"
DIAS_CONTRATACAO = -4
DELTA_VALOR_LOTE = 1000.0
DELTA_AREA_HA = 0.04
ESPELHO, ROTACAO_GRAUS, DESLOC_M = True, 35.0, (3000.0, -3000.0)  # em UTM 22S (SIRGAS 2000)
EPSG_UTM = 31982
VERSAO = 1

NOTA_GEOMETRIA = (
    "Geometria derivada de uma gleba pública do Sicor/BCB, espelhada, girada e deslocada ~4 km (não coincide "
    "com nenhuma gleba financiada do Fiscal-GO 2026); dados de campo e documentos sintéticos."
)


def transform(fn, g):
    """Reprojeta a geometria com uma função (x, y) -> (x, y) vetorizada (pyproj)."""
    return shapely.transform(g, lambda c: np.column_stack(fn(c[:, 0], c[:, 1])))


def _transformacao(centro_utm: Point):
    para_utm = Transformer.from_crs(4326, EPSG_UTM, always_xy=True).transform
    para_ll = Transformer.from_crs(EPSG_UTM, 4326, always_xy=True).transform

    def aplicar(g):
        g = transform(para_utm, g)
        if ESPELHO:
            g = affinity.scale(g, xfact=-1, yfact=1, origin=centro_utm)
        g = affinity.rotate(g, ROTACAO_GRAUS, origin=centro_utm)
        g = affinity.translate(g, *DESLOC_M)
        return transform(para_ll, g)

    return aplicar


def _gms(valor: float) -> tuple[float, float, float]:
    v = abs(valor)
    g = int(v)
    m = int((v - g) * 60)
    s = round((v - g - m / 60) * 3600, 2)
    return float(g), float(m), s


def _trocar_gps_exif(caminho: Path, lat: float, lon: float) -> None:
    """Reescreve só o segmento APP1 (EXIF) com o GPS novo: os pixels do JPEG não são recodificados."""
    bruto = caminho.read_bytes()
    img = Image.open(io.BytesIO(bruto))
    ex = img.getexif()
    g = ex.get_ifd(0x8825)
    g[1] = "S" if lat < 0 else "N"
    g[2] = _gms(lat)
    g[3] = "W" if lon < 0 else "E"
    g[4] = _gms(lon)
    novo_app1 = ex.tobytes()
    if not novo_app1.startswith(b"Exif\x00\x00"):
        novo_app1 = b"Exif\x00\x00" + novo_app1
    assert bruto[:2] == b"\xff\xd8", "não é JPEG"
    i, saida = 2, bytearray(b"\xff\xd8")
    trocado = False
    while i < len(bruto):
        if bruto[i] != 0xFF:
            raise ValueError(f"{caminho.name}: marcador JPEG inesperado em {i}")
        marcador = bruto[i + 1]
        if marcador == 0xDA:  # início dos dados da imagem: copia o resto como está
            saida += bruto[i:]
            break
        tam = struct.unpack(">H", bruto[i + 2 : i + 4])[0]
        seg = bruto[i : i + 2 + tam]
        if marcador == 0xE1 and seg[4:10] == b"Exif\x00\x00" and not trocado:
            seg = b"\xff\xe1" + struct.pack(">H", len(novo_app1) + 2) + novo_app1
            trocado = True
        saida += seg
        i += 2 + tam
    if not trocado:
        raise ValueError(f"{caminho.name}: sem segmento EXIF")
    caminho.write_bytes(bytes(saida))


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verificar(dados: dict) -> list[str]:
    """Problemas que ainda ligam o caso a uma operação real (lista vazia = ok)."""
    problemas = []
    op = dados.get("operacao") or {}
    if op.get("ref_bacen") != REF_DEMO:
        problemas.append(f"REF_BACEN {op.get('ref_bacen')!r} não é o fictício {REF_DEMO}")
    if "BRASIL" in str(op.get("instituicao") or "").upper() or "fictícia" not in str(
        op.get("instituicao") or ""
    ):
        problemas.append(f"instituição {op.get('instituicao')!r} não é fictícia")
    if not dados.get("demonstracao"):
        problemas.append("falta o bloco `demonstracao:` (marca d'água)")
    texto = yaml.safe_dump(dados, allow_unicode=True)
    from laudo.geo import bench

    try:
        ops = bench.operacoes()
        gl = bench.glebas()
    except bench.BenchAusente:
        return problemas
    if op.get("ref_bacen") in set(ops["ref_bacen"]):
        problemas.append("REF_BACEN existe no bench público")
    for ref in ops["ref_bacen"]:
        if str(ref) in texto:
            problemas.append(f"o caso cita o REF real {ref}")
            break
    if op.get("glebas_wkt"):
        poly = wkt.loads(op["glebas_wkt"][0])
        from shapely.strtree import STRtree

        geoms = [wkt.loads(w) for w in gl["wkt"] if w and not str(w).endswith("EMPTY")]
        perto = STRtree(geoms).query(poly.buffer(0.002))
        if len(perto):
            problemas.append(f"a gleba fictícia encosta em {len(perto)} gleba(s) do bench público")
    mesmo = ops[
        (ops["municipio_ibge"].astype(str) == str(op.get("municipio_ibge")))
        & (ops["valor_rs"].round(2) == round(float(op.get("valor_rs") or 0), 2))
    ]
    if len(mesmo):
        problemas.append("valor + município ainda casam com operação do bench")
    return problemas


def mascarar(pasta: Path = CASO) -> dict:
    arq = pasta / "caso.yaml"
    dados = yaml.safe_load(arq.read_text(encoding="utf-8"))
    if (dados.get("demonstracao") or {}).get("mascarado_versao"):
        raise SystemExit(f"{arq} já está mascarado (versão {dados['demonstracao']['mascarado_versao']})")
    op = dados["operacao"]
    poly = wkt.loads(op["glebas_wkt"][0])
    para_utm = Transformer.from_crs(4326, EPSG_UTM, always_xy=True).transform
    centro = transform(para_utm, poly).centroid
    tf = _transformacao(centro)
    nova = tf(poly)
    assert isinstance(nova, Polygon)
    coords = ", ".join(f"{x:.7f} {y:.7f}" for x, y in nova.exterior.coords)
    op["glebas_wkt"] = [f"POLYGON (({coords}))"]

    # quase-identificadores do Sicor
    contratacao = date.fromisoformat(str(op["data_contratacao"])) + timedelta(days=DIAS_CONTRATACAO)
    op["ref_bacen"] = REF_DEMO
    op["instituicao"] = IF_DEMO
    op["data_contratacao"] = contratacao.isoformat()
    op["fonte"] = FONTE_DEMO
    bov = next(i for i in op["itens"] if i["tipo"] == "bovinos")
    bov["valor_rs"] = round(float(bov["valor_rs"]) + DELTA_VALOR_LOTE, 2)
    op["valor_rs"] = round(sum(float(i["valor_rs"] or 0) for i in op["itens"]), 2)
    for k in ("area_financiada_ha", "area_informada_ha"):
        if op.get(k):
            op[k] = round(float(op[k]) + DELTA_AREA_HA, 2)
    lot = round(float(bov["quantidade"]) / float(op["area_financiada_ha"]), 2)
    proj = dados.get("projeto") or {}
    proj["lotacao_implicita_cab_ha"] = lot
    for o in proj.get("orcamento") or []:
        if o.get("item_id") == bov["id"]:
            o["valor_unitario_rs"] = round(bov["valor_rs"] / float(o["quantidade"]), 2)
            o["valor_total_rs"] = round(o["valor_unitario_rs"] * float(o["quantidade"]), 2)
    tri = dados.get("triagem") or {}
    tri["lotacao_implicita_cab_ha"] = lot
    tri["fonte_versao"] = f"{tri.get('fonte_versao', '')};demo-mascarado@{VERSAO}".lstrip(";")
    for ent in (dados.get("entradas_ferramentas") or {}).values():
        if isinstance(ent, dict):
            ent["data_contratacao"] = contratacao.isoformat()
            if isinstance(ent.get("item"), dict):
                ent["item"]["valor_rs"] = bov["valor_rs"]

    # fotos: mesma transformação rígida no GPS do app e no EXIF
    for f in dados.get("fotos") or []:
        for chave in ("gps_app",):
            g = f.get(chave)
            if g:
                p = tf(Point(g["lon"], g["lat"]))
                g["lat"], g["lon"] = round(p.y, 7), round(p.x, 7)
        ex = (f.get("exif") or {}).get("gps")
        if ex:
            p = tf(Point(ex["lon"], ex["lat"]))
            ex["lat"], ex["lon"] = round(p.y, 7), round(p.x, 7)
            _trocar_gps_exif(pasta / f["arquivo"], ex["lat"], ex["lon"])
        f["sha256"] = _sha256(pasta / f["arquivo"])

    # textos
    dfc = dados.get("defeito") or {}
    dfc["titulo"] = "Demo do regional (operação fictícia + defeitos plantados)"
    dfc["descricao"] = (
        "Operação fictícia derivada de um registro público do Sicor/BCB (REF, IF, data, valores, área e "
        "geometria alterados); D15 (GTA antes da NF-e) + D12 (contagem 12 [12-17] de 29 e pressão) + D13 "
        "(injeção na GTA) "
        "+ foto da cerca fora da gleba corrigida"
    )
    dados["sintetico"] = "derivado"
    dados["aviso"] = (
        "Caso de DEMONSTRAÇÃO com operação FICTÍCIA. REF 000000001 (não existe no Sicor), cooperativa "
        "fictícia; "
        "data, valores, área e geometria alterados a partir de um registro público do Sicor/BCB. Projeto, "
        "tomador, vendedor, NF-e, GTA, vídeo, fotos, falas e TODOS os defeitos são sintéticos e plantados. "
        "Não "
        "descreve nenhuma operação, propriedade ou produtor real. Prioridade de verificação não é indício de "
        "irregularidade."
    )
    dados["origem_dados"] = {
        "operacao": (
            "fictícia, derivada de um registro público do Fiscal-GO 2026 (Sicor/BCB) por "
            "scripts/mascarar_demo.py: mantidos município, finalidade, empreendimento, quantidade de "
            "animais e ordem de grandeza de valor e área; trocados REF, instituição, data de contratação, "
            "valores, área e geometria"
        ),
        "geometria": NOTA_GEOMETRIA,
        "sintetico": [
            "REF e instituição",
            "projeto (cerca de 1.200 m, cronograma)",
            "tomador e vendedor",
            "NF-e",
            "GTA",
            "fotos (desenho com EXIF)",
            "vídeo semissintético",
            "falas",
            "defeitos plantados",
        ],
    }
    from laudo.demonstracao import MARCA_DAGUA

    dados["demonstracao"] = {
        "marca_dagua": MARCA_DAGUA,
        "nota_geometria": NOTA_GEOMETRIA,
        "mascarado_versao": VERSAO,
        "script": "scripts/mascarar_demo.py",
    }
    arq.write_text(yaml.safe_dump(dados, sort_keys=False, allow_unicode=True, width=110), encoding="utf-8")
    return dados


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pasta", type=Path, default=CASO)
    ap.add_argument(
        "--verificar", action="store_true", help="só confere; sai com 1 se ainda for identificável"
    )
    a = ap.parse_args()
    if not a.verificar:
        mascarar(a.pasta)
        print(f"caso mascarado: {a.pasta / 'caso.yaml'}")
    dados = yaml.safe_load((a.pasta / "caso.yaml").read_text(encoding="utf-8"))
    problemas = verificar(dados)
    for p in problemas:
        print(f"PROBLEMA: {p}")
    if not problemas:
        print("ok: o caso não aponta para operação, gleba ou instituição reais do bench")
    return 1 if problemas else 0


if __name__ == "__main__":
    raise SystemExit(main())
