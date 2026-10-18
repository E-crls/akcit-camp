"""Gerador de entradas bagunçadas (DANFE/GTA em foto e narração livre): rótulos coerentes com o golden."""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1].parent
sys.path.insert(0, str(REPO / "eval" / "golden" / "gerador"))
import documentos_imagem as DI
import gerar_baguncados as GB

CASOS = REPO / "eval" / "golden" / "casos"


def _caso(cid: str) -> dict:
    return yaml.safe_load((CASOS / cid / "caso.yaml").read_text(encoding="utf-8"))


def test_redistribuir_faixas_mantem_total_e_sexo():
    g = json.loads((CASOS / "GLD-0035" / "gta_1.json").read_text(encoding="utf-8"))
    for semente in range(20):
        v = GB.redistribuir_faixas(g, random.Random(semente))
        assert sum(q["quantidade"] for q in v["quantidades"]) == g["total"]
        assert {q["sexo"] for q in v["quantidades"]} == {q["sexo"] for q in g["quantidades"]}
        assert len({q["faixa_etaria"] for q in v["quantidades"]}) == len(v["quantidades"]) <= 3


def test_rotulos_do_danfe_batem_com_o_caso():
    caso = _caso("GLD-0002")
    r = GB.rotulos_danfe((CASOS / "GLD-0002" / "nfe_1.xml").read_bytes())
    assert r["chave"] == caso["documentos"]["nfe"][0]["chave"]
    assert r["item1.quantidade"] == caso["operacao"]["itens"][0]["quantidade"]


def test_narracao_e_deterministica_e_rotula_as_alegacoes():
    caso = _caso("GLD-0011")
    a = GB.narracao(caso, random.Random("x"))
    b = GB.narracao(caso, random.Random("x"))
    assert a == b and a["alegacoes_esperadas"][0]["item_id"] == "bov1"
    assert {e["status"] for e in a["alegacoes_esperadas"]} <= {"confere", "divergente", "pendente", "registro",
                                                               "sem_evidencia"}


def test_extenso_feminino_e_imagem_da_gta():
    assert GB.extenso(22, feminino=True) == "vinte e duas" and GB.extenso(200, feminino=True) == "duzentas"
    img = DI.renderizar_gta(json.loads((CASOS / "GLD-0002" / "gta_1.json").read_text(encoding="utf-8")))
    foto, meta = DI.fotografar(img, "pesada", random.Random(1))
    assert max(foto.size) <= 950 and meta["nivel"] == "pesada"


def test_manifesto_respeita_o_split_congelado():
    man = yaml.safe_load((REPO / "eval" / "golden" / "baguncados" / "MANIFESTO.yaml").read_text(encoding="utf-8"))
    split = yaml.safe_load((CASOS / "SPLIT.yaml").read_text(encoding="utf-8"))
    assert man["split_origem"]["sha256_split"] == split["sha256_split"]
    assert {c["id"]: c["split"] for c in man["casos"]} == {c["id"]: c["split"] for c in split["casos"]}
