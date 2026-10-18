"""Gerador de casos sintéticos: determinismo, composição, split, ausência de PII e coerência dos rótulos."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "eval" / "golden" / "gerador"))

import gerar_casos as GC
from taxonomia_defeitos import CAMPOS_DOCUMENTOS, TIPOS

from laudo.docs_fiscais.comum import cnpj_valido, cpf_valido
from laudo.tools import documentos as T

N = 40  # 16 válidos, 16 com defeito (todos os 16 tipos) e 8 ambíguos (todos os 8 tipos)


@pytest.fixture(scope="module")
def conjunto(tmp_path_factory):
    d = tmp_path_factory.mktemp("golden")
    meta = GC.gerar_conjunto(semente=123, n=N, saida=d, demo=False, bits=1024)
    return d, meta


def _casos(d: Path) -> list[tuple[Path, dict]]:
    return [(p, yaml.safe_load((p / "caso.yaml").read_text(encoding="utf-8"))) for p in sorted(d.glob("GLD-*"))]


def test_deterministico_pela_semente(conjunto, tmp_path):
    d, meta = conjunto
    meta2 = GC.gerar_conjunto(semente=123, n=N, saida=tmp_path, demo=False, bits=1024)
    assert meta2["sha256_split"] == meta["sha256_split"]
    assert meta2["sha256_conteudo"] == meta["sha256_conteudo"]
    for arq in sorted(d.glob("GLD-000[1-5]/**/*.*")):
        assert arq.read_bytes() == (tmp_path / arq.relative_to(d)).read_bytes(), arq


def test_semente_diferente_gera_outro_conjunto(tmp_path):
    a = GC.gerar_conjunto(semente=1, n=5, saida=tmp_path / "a", demo=False, bits=1024)
    b = GC.gerar_conjunto(semente=2, n=5, saida=tmp_path / "b", demo=False, bits=1024)
    assert a["sha256_conteudo"] != b["sha256_conteudo"]


def test_composicao_e_cobertura_da_taxonomia(conjunto):
    d, meta = conjunto
    assert meta["composicao"] == {"valido": 16, "defeito": 16, "ambiguo": 8}
    codigos = {c["defeito"]["codigo"] for _, c in _casos(d) if c["defeito"]}
    assert codigos == {t.codigo for t in TIPOS}


def test_planejar_respeita_proporcoes():
    plano = GC.planejar(60, 7)
    classes = [c for c, _ in plano]
    assert (classes.count("valido"), classes.count("defeito"), classes.count("ambiguo")) == (24, 24, 12)
    exigidos = {t.codigo for t in TIPOS if t.exigido}
    assert exigidos <= {c for _, c in plano}


def test_split_estratificado_e_hash(conjunto):
    d, meta = conjunto
    dev, test = set(meta["dev"]), set(meta["test"])
    assert not dev & test and len(dev | test) == N and len(test) == round(N * 0.4)
    for classe, e in meta["estratos"].items():
        total = e["dev"] + e["test"]
        assert abs(e["test"] - total * 0.4) <= 1, classe
    split = {"dev": meta["dev"], "test": meta["test"]}
    assert hashlib.sha256(json.dumps(split, sort_keys=True).encode()).hexdigest() == meta["sha256_split"]
    gravado = yaml.safe_load((d / "SPLIT.yaml").read_text(encoding="utf-8"))
    assert gravado["sha256_split"] == meta["sha256_split"]


def test_split_congelado_nao_e_sobrescrito(tmp_path):
    GC.gerar_conjunto(semente=1, n=3, saida=tmp_path, demo=False, bits=1024)
    arq = tmp_path / "SPLIT.yaml"
    meta = yaml.safe_load(arq.read_text(encoding="utf-8"))
    meta["congelado"] = True
    arq.write_text(yaml.safe_dump(meta), encoding="utf-8")
    with pytest.raises(SystemExit):
        GC.gerar_conjunto(semente=1, n=3, saida=tmp_path, demo=False, bits=1024)


def test_identificadores_claramente_sinteticos(conjunto):
    d, _ = conjunto
    for p, caso in _casos(d):
        assert caso["sintetico"] is True and caso["operacao"]["fonte"] == "sintetico"
        assert caso["operacao"]["ref_bacen"].startswith("SINT-")
        assert "TESTE" in caso["tomador"]["nome"]
        for arq in [*p.glob("nfe_*.xml"), *p.glob("gta_*.json")]:
            texto = arq.read_text(encoding="utf-8")
            for doc in re.findall(r"<(?:CNPJ|CPF)>(\w+)</|\"documento\": \"(\w+)\"", texto):
                v = doc[0] or doc[1]
                assert (v.startswith("99999999") and cnpj_valido(v)) or (v.startswith("000000") and cpf_valido(v))
            assert "TESTE" in texto


def _resolver(d: Path, ent: dict) -> dict:
    out = dict(ent)
    for chave in ("caminhos", "nfe_caminhos"):
        if chave in out:
            out[chave] = [str(d / x) for x in out[chave]]
    return out


def test_ferramentas_reproduzem_rotulos_documentais(conjunto):
    d, _ = conjunto
    for p, caso in _casos(d):
        ent = caso["entradas_ferramentas"]
        r_nfe = T.conciliar_nfe(T.EntradaConciliarNFe.model_validate(_resolver(p, ent["conciliar_nfe"])))
        r_gta = T.conciliar_gta(T.EntradaConciliarGTA.model_validate(_resolver(p, ent["conciliar_gta"])))
        assert r_nfe.ok and r_gta.ok, (p.name, r_nfe.error, r_gta.error)
        obtidos = {**r_nfe.data["campos"], **r_gta.data["campos"]}
        subs = {"bov": "bov1", "benf": caso["operacao"]["itens"][1]["id"]}
        for modelo in CAMPOS_DOCUMENTOS:
            campo = modelo.format(**subs)
            esp, obt = caso["esperado"]["campos"][campo], obtidos[campo]
            assert obt["status_campo_sugerido"] == esp["status_esperado"], (p.name, campo, obt["motivos"])
            if esp["status_esperado"] != "verificado":
                assert obt["regra_id"] == esp["regra_id"], (p.name, campo)
        ocorr = {o["tipo"] for o in r_nfe.data["ocorrencias_sugeridas"] + r_gta.data["ocorrencias_sugeridas"]}
        assert ("injecao" in ocorr) == ("injecao" in caso["esperado"]["ocorrencias"]), p.name


def test_rotulos_fisicos_coerentes_com_metadados(conjunto):
    d, _ = conjunto
    for p, caso in _casos(d):
        esp = caso["esperado"]["campos"]
        benf = caso["operacao"]["itens"][1]["id"]
        fotos = [f for f in caso["fotos"] if f["item_id"] == benf]
        dentro = any(f["esperado"]["geofence"] == "dentro" for f in fotos)
        assert (esp[f"item:{benf}:localizacao"]["status_esperado"] == "verificado") == dentro, p.name
        shas = [f["sha256"] for f in fotos]
        assert (len(set(shas)) < len(shas)) == any(f["duplicata_de"] for f in fotos), p.name
        for f in fotos:
            assert (p / f["arquivo"]).is_file()


def test_casos_versionados_conferem_com_split():
    """Protege o conjunto versionado: cada caso.yaml precisa bater com o hash registrado no SPLIT.yaml."""
    base = REPO / "eval" / "golden" / "casos"
    arq = base / "SPLIT.yaml"
    if not arq.exists():
        pytest.skip("conjunto ainda não gerado")
    meta = yaml.safe_load(arq.read_text(encoding="utf-8"))
    for c in meta["casos"]:
        texto = (base / c["id"] / "caso.yaml").read_bytes()
        assert hashlib.sha256(texto).hexdigest() == c["sha256_caso"], c["id"]
    split = {"dev": meta["dev"], "test": meta["test"]}
    assert hashlib.sha256(json.dumps(split, sort_keys=True).encode()).hexdigest() == meta["sha256_split"]
