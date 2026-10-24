"""Contorno de Goiás do mapa da carteira: com a malha do IBGE ou, sem ela (imagem Docker), o versionado em ativos/."""

import json

from laudo.api import mapa


def test_sem_malha_do_ibge_usa_o_contorno_versionado(tmp_path, monkeypatch):
    monkeypatch.setattr(mapa, "REPO", tmp_path)
    assert mapa.contorno_go(None) is None  # nem malha nem contorno pronto
    pronto = tmp_path / "dados_locais" / "mapa" / "contorno_go.json"
    pronto.parent.mkdir(parents=True)
    pronto.write_text(json.dumps({"nome": "Goiás", "aneis": [[[-16.0, -49.0], [-16.1, -49.1], [-16.0, -49.0]]]}),
                      encoding="utf-8")
    c = mapa.contorno_go(None)
    assert c["nome"] == "Goiás" and c["aneis"]


def test_contorno_versionado_nos_ativos():
    m = json.loads((mapa.REPO / "ativos" / "manifesto.json").read_text(encoding="utf-8"))
    a = next(x for x in m["arquivos"] if x["caminho"] == "mapa/contorno_go.json")
    assert a["destino"] == "dados_locais/mapa/contorno_go.json"
    c = json.loads((mapa.REPO / "ativos" / "demo" / "mapa" / "contorno_go.json").read_text(encoding="utf-8"))
    assert c["aneis"] and len(c["aneis"][0]) > 100
