"""Aceitação do pacote de exibição BCB/Justiça (`laudo.tools.pacote`, item 4 da seção 5A do memorando).

O pacote só sai de fiscalização SELADA (ação humana, sem LLM) e o teste falha se faltar qualquer item:
manifest sha256 de cada arquivo, laudo selado, GeoJSON da gleba, coordenadas e horário das fotos, IDs de cena
com sensor, resolução e bandas (MCR 2-7-4-b), fundamento literal por item, memória de cálculo (contagem,
conciliações, lotação), ciência do mutuário com prazo de contestação, reversão (IN BCB 758), checklist "Ordem
JF Rio Verde" com status real por item (meteorologia "não aplicável" com justificativa), "por que caiu na
amostra", PII mascarada e marca d'água da demonstração.

Caminho rápido: API com ferramentas falsas no DEMO-0001 (operação fictícia) e uma série de NDVI determinística
com IDs de cena (sem rede). Caminho lento (LAUDO_LENTO=1): o replay da demo real (ferramentas reais, mesma
gravação do LLM, que não pode mudar) até SELADO e o pacote em cima dele.
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import BaseModel

from laudo import demonstracao
from laudo.agent import estado as est
from laudo.agent.roteiro_demo import chamar
from laudo.api import casos as casos_mod
from laudo.api.main import criar_app
from laudo.api.servico import PIN_DEMO, Config
from laudo.contracts import Envelope, Ferramenta, sha256_bytes
from laudo.tools import laudo as ferr_laudo
from laudo.tools import pacote

PASTA_DEMO = casos_mod.localizar_caso("DEMO-0001")
pytestmark = pytest.mark.skipif(PASTA_DEMO is None, reason="DEMO-0001 ausente")
DATAS = ("2026-08-01", "2026-08-21", "2026-09-05")


# ---------------------------------------------------------------------------
# Funções puras
# ---------------------------------------------------------------------------


def test_trecho_literal_vem_de_docs_normas():
    t = pacote.trecho_literal("MCR 2-7-2-a-I")
    assert t.startswith("2 - O monitoramento e a fiscalização") and "I - a adequação da condução" in t
    assert "satélite imageador e sensor utilizado" in pacote.trecho_literal("MCR 2-7-4-b-I")
    assert pacote.trecho_literal("MCR 2-5-10-b").startswith("10 - Comprova-se o uso adequado")
    assert pacote.trecho_literal("MCR 2-7-23").startswith("23 - As instituições financeiras devem manter")
    assert (
        pacote.trecho_literal("MCR 9-9-9") is None and pacote.trecho_literal("MCR 2-7-1-c e 2-7-1-d") is None
    )


def test_fundamento_norma_parametro_e_sem_citacao():
    norma = pacote.fundamento("MCR-2-7-item16-benfeitorias-conclusao")
    assert norma["status"] == "literal" and norma["citacao_literal"] and pacote.tem_literal(norma)
    op = pacote.fundamento("OP-bovinos-contagem-tolerancia")
    assert op["status"] == "literal_na_base" and op["justificativa"] and op["citacao_literal"] is None
    assert all(b["citacao_literal"] for b in op["base_normativa"]) and "não é norma" in op["aviso"]
    doc = pacote.fundamento("AJ-SINIEF-07-2005-cl3")
    assert doc["status"] == "resumo" and not pacote.tem_literal(doc)
    assert pacote.fundamento("PROVISORIO/MCR-2-7")["status"] == "sem_citacao"


def test_por_que_na_amostra_abre_os_motivos_da_triagem():
    tri = {
        "prioridade_verificacao": 5,
        "prioridade_nivel": "alta",
        "motivos": [
            "lotação implícita de 3,3 UA/ha na compra de matrizes/reprodutores (acima de 3) (+2)",
            "gleba sobreposta em 100% (29,9 ha) com 1 outra(s) operação(ões) da mesma safra (+3)",
        ],
        "motivos_codigos": ["LOTACAO_ALTA", "SOBREPOSICAO_GLEBAS"],
        "observacoes": ["sem polígono público"],
    }
    a = pacote.por_que_na_amostra(tri)
    assert a["tem_triagem"] and a["nivel_rotulo"] == "alta" and a["pontos"] == 5
    assert [m["codigo"] for m in a["motivos"]] == ["LOTACAO_ALTA", "SOBREPOSICAO_GLEBAS"]
    assert [m["pontos"] for m in a["motivos"]] == [2, 3] and "acima de 5 +3" in a["motivos"][0]["criterio"]
    assert "(+" not in a["motivos"][0]["texto"] and a["observacoes"] == ["sem polígono público"]
    assert "não é indício de irregularidade" in a["aviso"] and all(
        f["citacao_literal"] for f in a["fundamento"]
    )
    # sem códigos (caso de demonstração): o código vem da forma do texto, a regra de laudo.geo.triagem
    demo = pacote.por_que_na_amostra(
        {
            "prioridade_nivel": "media",
            "prioridade_verificacao": 3,
            "motivos": [
                "lotação implícita de 6,0 cab/ha na compra de matrizes/reprodutores (acima de 5) (+3)"
            ],
        }
    )
    assert demo["motivos"][0]["codigo"] == "LOTACAO_ALTA" and demo["resumo"].startswith("prioridade média")
    assert pacote.por_que_na_amostra({})["tem_triagem"] is False
    assert pacote.por_que_na_amostra(tri, compacto=True)["fundamento"] == []


def test_mascara_nao_corrompe_hash_nem_versao():
    from laudo.docs_fiscais.sintetico import cpf_sintetico

    digitos = "".join(c for c in cpf_sintetico(7) if c.isdigit())
    cpf = f"{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}"
    hexa = "ab" + digitos + "cdef0123456789"  # 11 dígitos com DV de CPF no meio de um hash
    out = pacote.mascarar_obj(
        {
            "sha256": hexa,
            "texto": f"CPF {cpf}; hash {hexa}",
            "fonte_versao": "laudo-vivo@0.1.0",
            "motivo": f"vendedor {cpf}",
        }
    )
    assert out["sha256"] == hexa and hexa in out["texto"] and cpf not in out["texto"]
    assert out["fonte_versao"] == "laudo-vivo@0.1.0" and cpf not in out["motivo"]
    assert pacote.pii_no_texto(f"documento {cpf}") and not pacote.pii_no_texto(
        f"{hexa} pacote-exibicao@0.1.0"
    )


# ---------------------------------------------------------------------------
# DEMO-0001 pela API (ferramentas falsas + NDVI determinístico com IDs de cena)
# ---------------------------------------------------------------------------


class _EntradaNdvi(BaseModel):
    poligono_wkt: str | None = None
    inicio: str | None = None
    fim: str | None = None


def _ndvi(_a: _EntradaNdvi) -> Envelope:
    serie = [
        {
            "data": d,
            "item_id": f"S2B_T22LFH_{d.replace('-', '')}T133546_L2A",
            "tile": "22LFH",
            "plataforma": "sentinel-2b",
            "nuvem_cena": 4.0,
            "frac_limpa": 0.97,
            "ndvi_p50": 0.41,
            "limpa": True,
        }
        for d in DATAS
    ]
    meta = {
        "satelite": ["sentinel-2b"],
        "sensor": "MSI (MultiSpectral Instrument)",
        "produto": "Sentinel-2 L2A, coleção sentinel-2-c1-l2a (Earth Search / Element 84, COG)",
        "bandas": {"B04": "vermelho, 665 nm, 10 m", "B08": "infravermelho próximo, 842 nm, 10 m"},
        "resolucao_m": 10,
        "resolucao_radiometrica_bits": 12,
        "datas": list(DATAS),
        "metodologia": "NDVI=(B08-B04)/(B08+B04) (teste)",
        "uso_na_fiscalizacao": "pastagem (teste)",
    }
    return Envelope.sucesso(
        "serie_ndvi",
        {
            "status": "ok",
            "serie": serie,
            "n_obs_limpas": 3,
            "n_datas_lidas": 3,
            "n_cenas_stac": 3,
            "metadados_laudo": meta,
        },
        fonte_versao="teste@1",
    )


def _cliente(dados: Path) -> TestClient:
    app = criar_app(Config(dados=dados, caso="DEMO-0001", asr="desligado"))
    srv = app.state.servico
    srv.registro["serie_ndvi"] = Ferramenta(
        nome="serie_ndvi", descricao="NDVI de teste", entrada=_EntradaNdvi, funcao=_ndvi
    )
    caso = srv.caso("DEMO-0001")
    caso.roteiro[1].passos_llm = [chamar("serie_ndvi", args={"poligono_wkt": caso.operacao.glebas_wkt[0]})]
    return TestClient(app)


def _ate_selar(c: TestClient, fis: str) -> None:
    while True:
        r = c.post(f"/api/fiscalizacoes/{fis}/roteiro/proximo")
        if r.status_code == 409:
            return
        assert r.status_code == 200, r.text
        j = r.json()
        if j.get("acao_humana") == "assinar":
            h = j["estado"]["laudo"]["hash_raiz"]
            assert (
                c.post(
                    f"/api/fiscalizacoes/{fis}/assinar", json={"pin": PIN_DEMO, "hash_confirmado": h}
                ).json()["estado"]["etapa"]
                == "SELADO"
            )


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    dados = tmp_path_factory.mktemp("pacote") / "api"
    c = _cliente(dados)
    fis = c.post("/api/fiscalizacoes", json={"caso": "DEMO-0001"}).json()["id"]
    antes = c.post(f"/api/fiscalizacoes/{fis}/pacote")
    _ate_selar(c, fis)
    yield {"c": c, "fis": fis, "dados": dados, "antes": antes}
    est.ids_deterministicos(None)
    ferr_laudo.configurar(None, None)


@pytest.fixture(scope="module")
def gerado(demo):
    c, fis, dados = demo["c"], demo["fis"], demo["dados"]
    estado_antes = (dados / "fiscalizacoes" / f"{fis}.json").read_bytes()
    r = c.post(f"/api/fiscalizacoes/{fis}/pacote")
    assert r.status_code == 200, r.text
    z = c.get(f"/api/fiscalizacoes/{fis}/pacote.zip")
    assert z.status_code == 200 and z.headers["content-type"] == "application/zip"
    caminho = dados / "baixado.zip"
    caminho.write_bytes(z.content)
    return {"resp": r.json(), "zip": caminho, "bytes": z.content, "estado_antes": estado_antes}


def _ler(zip_bytes: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        return {n: z.read(n) for n in z.namelist()}


def test_pacote_negado_antes_de_selado(demo):
    r = demo["antes"]
    assert r.status_code == 409 and "SELADO" in r.json()["erro"]
    trace = (demo["dados"] / "traces" / f"{demo['fis']}.jsonl").read_text(encoding="utf-8")
    negado = [json.loads(x) for x in trace.splitlines() if '"gerar_pacote_exibicao"' in x and '"negar"' in x]
    assert negado and negado[0]["attributes"]["policy.rule_id"] == "POL-03"


def test_pacote_completo_e_valido(demo, gerado):
    r = gerado["resp"]
    assert r["ok"] and r["faltas"] == [] and pacote.validar_pacote(gerado["zip"]) == []
    assert r["url"].endswith("/pacote.zip") and "arquivo" not in r  # caminho local não vai para a tela
    assert r["sha256_zip"] == sha256_bytes(gerado["bytes"])
    arqs = _ler(gerado["bytes"])
    assert set(pacote.ARQUIVOS_OBRIGATORIOS) <= set(arqs)
    man = json.loads(arqs["manifest.json"])
    assert {a["caminho"] for a in man["arquivos"]} == set(arqs) - {"manifest.json"}
    for a in man["arquivos"]:
        assert a["sha256"] == sha256_bytes(arqs[a["caminho"]]) and a["bytes"] == len(arqs[a["caminho"]])
    # o laudo vai como foi selado (byte a byte) e o selo confere
    disco = demo["dados"] / "laudos" / demo["fis"] / "laudo_selado.json"
    assert arqs[pacote.ARQ["laudo_json"]] == disco.read_bytes()
    assert man["selo"] == json.loads(disco.read_bytes())["selo"]
    # nada mudou no estado selado (POL-04)
    assert (demo["dados"] / "fiscalizacoes" / f"{demo['fis']}.json").read_bytes() == gerado["estado_antes"]


def test_vetor_fotos_e_cenas(demo, gerado):
    arqs = _ler(gerado["bytes"])
    caso = yaml.safe_load((PASTA_DEMO / "caso.yaml").read_text(encoding="utf-8"))
    gl = json.loads(arqs[pacote.ARQ["gleba"]])
    assert gl["type"] == "FeatureCollection" and len(gl["features"]) == 1
    geom = gl["features"][0]["geometry"]
    assert geom["type"] == "Polygon" and geom["coordinates"][0][0] == pytest.approx(
        [-49.4085452, -16.1134634]
    )
    laudo = json.loads(arqs[pacote.ARQ["laudo_json"]])
    assert laudo["operacao"]["glebas_geojson"]["features"][0]["geometry"] == geom  # o vetor foi assinado
    fotos = json.loads(arqs[pacote.ARQ["fotos"]])["features"]
    esperadas = {
        (f["gps_app"]["lon"], f["gps_app"]["lat"]) for f in caso["fotos"] if f["item_id"] == "cerca1"
    }
    assert {tuple(f["geometry"]["coordinates"]) for f in fotos} == esperadas
    assert all(f["properties"]["capturada_em"] and f["properties"]["recebida_em"] for f in fotos)
    assert all(f["properties"]["arquivo_no_pacote"] in arqs for f in fotos)  # foto de campo vai inteira
    cenas = json.loads(arqs[pacote.ARQ["cenas"]])
    assert cenas["aplicavel"] and [c["data"] for c in cenas["cenas"]] == list(DATAS)
    for c in cenas["cenas"]:
        assert c["id_cena"].startswith("S2B_") and c["sensor"].startswith("MSI")
        assert c["resolucao_espacial_m"] == 10 and c["bandas"] == ["B04", "B08"]
        assert c["stac_url"].endswith(c["id_cena"])


def test_fundamento_memoria_ciencia_reversao(demo, gerado):
    arqs = _ler(gerado["bytes"])
    laudo = json.loads(arqs[pacote.ARQ["laudo_json"]])
    fund = json.loads(arqs[pacote.ARQ["fundamento"]])["itens"]
    assert {f["campo"] for f in fund} == {
        i["campo"] for i in laudo["itens"] if i["regra_id"] != "OP-agregacao-item"
    }
    assert all(f["fundamento"]["status"] for f in fund)
    mem = json.loads(arqs[pacote.ARQ["memoria"]])
    cont = mem["contagem"][0]
    assert cont["contagem"] == 12 and cont["intervalo"] == [12, 17] and cont["quantidade_financiada"] == 29
    assert cont["limite"] == pytest.approx(29 * (1 - cont["tolerancia_pct"] / 100), abs=0.01)
    assert {c["ferramenta"] for c in mem["conciliacoes"]} == {"conciliar_nfe", "conciliar_gta"}
    assert mem["lotacao"]["lotacao_cab_ha"] == pytest.approx(29 / 4.86, abs=1e-3)
    assert mem["lotacao"]["pontos_triagem"] == 3  # mesma regra de laudo.geo.triagem (acima de 5 cab/ha)
    ci = json.loads(arqs[pacote.ARQ["ciencia"]])
    assert ci["prazo_contestacao_dias"] == pacote.PRAZO_CONTESTACAO_DIAS and ci["contestaveis"]
    assert any(b["item"] == "MCR 2-8-3" and "60 (sessenta) dias" in b["citacao_literal"] for b in ci["base"])
    html = arqs[pacote.ARQ["ciencia_html"]].decode("utf-8")
    assert "contestação" in html and f"{pacote.PRAZO_CONTESTACAO_DIAS} dias corridos" in html
    rv = json.loads(arqs[pacote.ARQ["reversao"]])
    lit = pacote.in758_literal()  # citação conferida por sha256 em docs/normas (laudo.rulebooks.normas)
    assert (
        "IN BCB nº 758" in rv["norma"]
        and rv["citacao_conferida"] is bool(lit)
        and (rv["citacao_literal"] is None) is (lit is None)
        and rv["documentacao_desta_operacao"]
    )
    html_pac = arqs[pacote.ARQ["indice_html"]].decode("utf-8")
    if lit:  # a máscara de PII não pode alterar a citação, e a seção 8 do pacote.html a mostra
        assert rv["citacao_literal"] == lit["citacao_literal"] and rv["localizador"] == lit["localizador"]
        assert "Campo 60-B, Nota" in html_pac and "ainda não está em docs/normas" not in html_pac
    assert {x["campo"] for x in rv["itens_que_nao_sustentam"]} >= {"item:bov1:quantidade"}
    am = json.loads(arqs[pacote.ARQ["amostra"]])
    assert am["motivos"][0]["codigo"] == "LOTACAO_ALTA" and "não é indício" in am["aviso"]


def test_checklist_ordem_jf_com_status_real(gerado):
    arqs = _ler(gerado["bytes"])
    ck = json.loads(arqs[pacote.ARQ["checklist"]])
    st = {i["id"]: i for i in ck["itens"]}
    assert list(st) == list(pacote.ITENS_ORDEM_JF)
    assert st["vetor_poligono"]["status"] == "presente" and st["coordenadas"]["status"] == "presente"
    assert st["imagens_datadas"]["status"] == "presente"
    met = st["meteorologia"]
    assert met["status"] == "nao_aplicavel" and "animais" in met["justificativa"]
    fund = json.loads(arqs[pacote.ARQ["fundamento"]])["itens"]
    real = (
        "presente"
        if all(f["literal"] for f in fund)
        else ("ausente" if not any(f["literal"] for f in fund) else "parcial")
    )
    assert st["fundamento"]["status"] == real  # status real: as ferramentas falsas citam regra provisória
    assert ck["contagem"]["nao_aplicavel"] == 1 and "não conta como presente" in ck["nota"]
    assert gerado["resp"]["checklist_ordem_jf"]["resumo"] == ck["resumo"]


def test_pii_mascarada_e_marca_dagua(gerado):
    arqs = _ler(gerado["bytes"])
    caso = yaml.safe_load((PASTA_DEMO / "caso.yaml").read_text(encoding="utf-8"))
    chave = caso["documentos"]["nfe"][0]["chave"]
    doc = caso["tomador"]["documento_sintetico"]
    for n, b in arqs.items():
        if n.startswith("evidencias/"):
            continue
        t = b.decode("utf-8")
        assert chave not in t and doc not in t, n
        assert not pacote.pii_no_texto(t), (n, pacote.pii_no_texto(t))
        if n.endswith((".html", ".txt")):
            assert demonstracao.MARCA_DAGUA in t, n
    # documento fiscal e vídeo: só hash
    assert not any(n.endswith((".xml", ".mp4")) or "danfe" in n for n in arqs)
    assert gerado["resp"]["demonstracao"]["marca_dagua"] == demonstracao.MARCA_DAGUA
    incluidas = json.loads(arqs["pacote.json"])["evidencias_incluidas"]
    assert len(incluidas) == 2 and all(v in arqs for v in incluidas.values())  # as 2 fotos da cerca


def test_estado_da_tela_mostra_pacote_e_amostra(demo, gerado):
    e = demo["c"].get(f"/api/fiscalizacoes/{demo['fis']}").json()
    assert e["pacote"]["liberado"] and e["pacote"]["gerado"] and e["pacote"]["url"].endswith("pacote.zip")
    assert e["amostra"]["tem_triagem"] and e["amostra"]["motivos"][0]["codigo"] == "LOTACAO_ALTA"


# ---------------------------------------------------------------------------
# O validador falha se faltar qualquer item
# ---------------------------------------------------------------------------


def _fmt_cpf(d: str) -> str:
    d = "".join(c for c in d if c.isdigit())
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


def _reempacotar(arqs: dict[str, bytes], destino: Path) -> Path:
    """Reescreve o ZIP com o manifest refeito (a única falta é a provocada pelo teste)."""
    man = json.loads(arqs["manifest.json"])
    man["arquivos"] = [
        {"caminho": n, "sha256": sha256_bytes(b), "bytes": len(b)}
        for n, b in sorted(arqs.items())
        if n != "manifest.json"
    ]
    with zipfile.ZipFile(destino, "w") as z:
        for n, b in arqs.items():
            z.writestr(n, json.dumps(man).encode() if n == "manifest.json" else b)
    return destino


def _json_mut(arqs: dict[str, bytes], nome: str, f) -> None:
    d = json.loads(arqs[nome])
    f(d)
    arqs[nome] = json.dumps(d, ensure_ascii=False).encode("utf-8")


def _sem_justificativa(d):
    next(i for i in d["itens"] if i["id"] == "meteorologia").pop("justificativa")


MUTACOES = {
    "meteorologia sem justificativa": (pacote.ARQ["checklist"], _sem_justificativa, "sem justificativa"),
    "item do checklist faltando": (pacote.ARQ["checklist"], lambda d: d["itens"].pop(0), "vetor_poligono"),
    "cena sem id": (pacote.ARQ["cenas"], lambda d: d["cenas"][0].pop("id_cena"), "sem id_cena"),
    "cena sem bandas": (pacote.ARQ["cenas"], lambda d: d["cenas"][0].update(bandas=[]), "sem bandas"),
    "sem prazo de contestação": (
        pacote.ARQ["ciencia"],
        lambda d: d.update(prazo_contestacao_dias=0),
        "prazo",
    ),
    "fundamento faltando": (pacote.ARQ["fundamento"], lambda d: d["itens"].pop(), "fundamento: falta"),
    "memória sem lotação": (pacote.ARQ["memoria"], lambda d: d.pop("lotacao"), "lotacao"),
    "reversão sem IN 758": (pacote.ARQ["reversao"], lambda d: d.update(norma="outra"), "758"),
    "reversão conferida sem citação": (
        pacote.ARQ["reversao"],
        lambda d: d.update(citacao_conferida=True, citacao_literal=None),
        "'conferida' sem citação",
    ),
    "reversão: resumo como citação": (
        pacote.ARQ["reversao"],
        lambda d: d.update(citacao_conferida=False, citacao_literal="Fora do recorte (resumo)"),
        "sem conferência",
    ),
    "foto sem horário": (
        pacote.ARQ["fotos"],
        lambda d: d["features"][0]["properties"].pop("capturada_em"),
        "horário",
    ),
    "amostra sem motivos": (pacote.ARQ["amostra"], lambda d: d.pop("motivos"), "amostra"),
    # conteúdo mínimo (onda 3): recebimento das fotos, resolução radiométrica (MCR 2-7-4-b), citações da
    # ciência
    "foto sem recebimento": (
        pacote.ARQ["fotos"],
        lambda d: d["features"][0]["properties"].update(recebida_em=None),
        "recebida_em",
    ),
    "cena sem resolução radiométrica": (
        pacote.ARQ["cenas"],
        lambda d: d["cenas"][0].pop("resolucao_radiometrica_bits"),
        "resolucao_radiometrica_bits",
    ),
    "cena sem atribuição Copernicus": (pacote.ARQ["cenas"], lambda d: d.update(atribuicoes=[]), "Copernicus"),
    "ciência sem citação": (
        pacote.ARQ["ciencia"],
        lambda d: d["base"][0].update(citacao_literal=None),
        "citação literal",
    ),
    "laudo adulterado": (
        pacote.ARQ["laudo_json"],
        lambda d: d["itens"][0].update(motivo="adulterado no ZIP"),
        "laudo: não confere",
    ),
    "rascunho trocado": (
        pacote.ARQ["rascunho"],
        lambda d: d["itens"][0].update(motivo="adulterado no ZIP"),
        "laudo: não confere",
    ),
}


@pytest.mark.parametrize("arquivo", pacote.ARQUIVOS_OBRIGATORIOS)
def test_validador_acusa_arquivo_faltando(gerado, tmp_path, arquivo):
    arqs = _ler(gerado["bytes"])
    if arquivo == "manifest.json":
        with zipfile.ZipFile(tmp_path / "x.zip", "w") as z:
            for n, b in arqs.items():
                if n != arquivo:
                    z.writestr(n, b)
    else:
        arqs.pop(arquivo)
        _reempacotar(arqs, tmp_path / "x.zip")
    faltas = pacote.validar_pacote(tmp_path / "x.zip")
    assert any(arquivo in f for f in faltas), faltas


@pytest.mark.parametrize("caso", sorted(MUTACOES))
def test_validador_acusa_conteudo_faltando(gerado, tmp_path, caso):
    nome, mut, trecho = MUTACOES[caso]
    arqs = _ler(gerado["bytes"])
    _json_mut(arqs, nome, mut)
    faltas = pacote.validar_pacote(_reempacotar(arqs, tmp_path / "x.zip"))
    assert any(trecho in f for f in faltas), faltas


def test_validador_acusa_hash_pii_e_marca_dagua(gerado, tmp_path):
    from laudo.docs_fiscais.sintetico import cpf_sintetico

    arqs = _ler(gerado["bytes"])
    arqs[pacote.ARQ["trace"]] += b"\n"  # conteúdo mudou e o manifest antigo não confere
    with zipfile.ZipFile(tmp_path / "a.zip", "w") as z:
        for n, b in arqs.items():
            z.writestr(n, b)
    assert any("não confere" in f for f in pacote.validar_pacote(tmp_path / "a.zip"))
    arqs = _ler(gerado["bytes"])
    arqs[pacote.ARQ["indice_html"]] = (
        arqs[pacote.ARQ["indice_html"]].replace(demonstracao.MARCA_DAGUA.encode("utf-8"), b"x")
        + f"documento {_fmt_cpf(cpf_sintetico(3))}".encode()
    )
    faltas = pacote.validar_pacote(_reempacotar(arqs, tmp_path / "b.zip"))
    assert any("marca d'água" in f for f in faltas) and any(f.startswith("PII: pacote.html") for f in faltas)


def test_zip_traz_o_rascunho_assinado_e_a_verificacao_do_conteudo(demo, gerado):
    """L87a: o pacote leva o rascunho assinado e diz que o conteúdo do selado confere com ele; a conferência
    refeita só com o ZIP (`validar_pacote`) passa."""
    arqs = _ler(gerado["bytes"])
    from laudo.audit import selo

    laudo = json.loads(arqs[pacote.ARQ["laudo_json"]])
    rasc = json.loads(arqs[pacote.ARQ["rascunho"]])
    assert rasc["hash_raiz"] == laudo["hash_raiz"] and rasc["tipo"] == "rascunho"
    assert laudo["conteudo_assinado"]["tipo"] == "rascunho" and laudo["template"]["sha256"]
    r = selo.verificar_laudo(laudo, rascunho=rasc, html=arqs[pacote.ARQ["laudo_html"]])
    assert r.valido and r.conteudo_confere, r.motivo
    integ = json.loads(arqs["pacote.json"])["integridade"]
    assert integ["valido"] and integ["conteudo_confere"] and integ["cadeia_confere"] and integ["html_confere"]
    assert "laudo selado confere" in arqs["LEIA-ME.txt"].decode("utf-8")


def test_pacote_nao_sai_se_o_laudo_selado_nao_confere(demo, tmp_path):
    """Valor trocado numa cópia do laudo selado (o selo continua batendo: a fórmula não vê o conteúdo): o
    pacote não é gerado e a decisão negada vai para o trace."""
    import shutil

    origem = demo["dados"] / "laudos" / demo["fis"]
    copia = tmp_path / "laudos"
    shutil.copytree(origem, copia, ignore=shutil.ignore_patterns("pacote"))
    j = json.loads((copia / "laudo_selado.json").read_text(encoding="utf-8"))
    i = next(n for n, it in enumerate(j["itens"]) if it.get("valor") is not None)
    j["itens"][i].update(valor=29, valor_fmt="29", status="verificado")
    (copia / "laudo_selado.json").write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
    fis = est.RepositorioFiscalizacoes(demo["dados"]).carregar(demo["fis"])
    env = pacote.executar(fis, copia)
    assert not env.ok and env.error.code == "ENTRADA_INVALIDA" and "não confere" in env.error.msg, env
    assert "pacote não gerado" in env.error.msg and not (copia / "pacote").exists()


def test_chave_de_acesso_sem_espaco_e_mascarada_e_detectada():
    """A chave de 44 dígitos sem espaço passava como "hash" (só dígitos casam [0-9a-f]{16,}) pela máscara e
    pelo detector do pacote."""
    caso = yaml.safe_load((PASTA_DEMO / "caso.yaml").read_text(encoding="utf-8"))
    chave = caso["documentos"]["nfe"][0]["chave"]
    assert len(chave) == 44 and chave.isdigit()
    assert pacote.pii_no_texto(f"nota {chave} recebida")
    out = pacote.mascarar_obj({"motivo": f"nota {chave} conferida", "trecho": chave})
    assert chave not in json.dumps(out) and not pacote.pii_no_texto(json.dumps(out, ensure_ascii=False))
    h = "0123456789abcdef" * 4  # hash de verdade continua intocado
    assert pacote.mascarar_obj({"texto": f"hash {h}"})["texto"] == f"hash {h}" and not pacote.pii_no_texto(h)


def test_fundamento_das_regras_de_documentos_fiscais_e_resumo_nao_literal():
    """O fundamento das regras dos critérios de NF-e e GTA entra no pacote; o do catálogo vai como resumo e o
    checklist não diz "N de N com citação literal" (nem "presente") quando há resumo."""
    from laudo.contracts import Checagem, Fiscalizacao, Operacao

    op = Operacao.model_validate(
        yaml.safe_load((PASTA_DEMO / "caso.yaml").read_text(encoding="utf-8"))["operacao"]
    )
    chk = Checagem(
        ferramenta="conciliar_nfe",
        entrada_hash="x",
        status="ok",
        item_id="bov1",
        resultado={
            "criterios": [
                {"campo": "documento:nfe:integridade", "status": "ok", "regra_id": "AJ-SINIEF-07-2005-cl3"},
                {"campo": "item:bov1:nfe_quantidade", "status": "ok", "regra_id": "MCR-2-7-item2b"},
            ]
        },
    )
    fis = Fiscalizacao(operacao=op, checagens=[chk])
    docs = pacote.fundamento_documentos_fiscais(fis)
    por = {d["regra_id"]: d for d in docs}
    assert por["AJ-SINIEF-07-2005-cl3"]["status"] == "resumo" and not por["AJ-SINIEF-07-2005-cl3"]["literal"]
    assert por["AJ-SINIEF-07-2005-cl3"]["fundamento"]["resumo"]
    campos = [{"campo": "item:bov1:quantidade", "literal": True}]
    gl = {"features": [{"geometry": {"type": "Polygon"}}]}
    ck = pacote.checklist_ordem_jf(fis, {"itens": []}, gl, {"features": []}, {"cenas": []}, campos, docs)
    f = next(i for i in ck["itens"] if i["id"] == "fundamento")
    assert f["status"] == "parcial" and "só em resumo, não literal: AJ-SINIEF-07-2005-cl3" in f["motivo"]
    assert "1 de 1 campo(s)" in f["motivo"] and f["contagem"]["total"] == 1 + len(docs)
    assert "noticiada em 07/10/2026" in ck["referencia"] and "liminar" not in ck["referencia"]


def test_in758_literal_vem_da_citacao_conferida_de_normas():
    """A citação da IN BCB 758 é a de `laudo.rulebooks.normas.citacao_reversao()` (nota do Campo 60-B
    conferida por sha256), com o localizador, a URL oficial e a data do acesso (16/10/2026, não a data da
    IN)."""
    from laudo.rulebooks import normas

    ref = normas.citacao_reversao()
    lit = pacote.in758_literal()
    if ref is None:  # arquivo ausente ou alterado: o pacote não cita
        assert lit is None
        return
    assert lit["citacao_literal"] == ref["citacao_literal"] and lit["localizador"] == ref["localizador"]
    assert (
        lit["url"] == ref["url"]
        and lit["acesso"] == "2026-10-16"
        and lit["arquivo"] == ref["texto_normativo"]
    )
    rv = pacote.reversao_in758({}, {}, [])
    assert (
        rv["citacao_conferida"] is True
        and "A reversão da desclassificação poderá ser realizada" in (rv["citacao_literal"])
    )
    assert (
        "Fora do recorte" not in rv["citacao_literal"]
        and "nova redação do item 18" not in rv["citacao_literal"]
    )
    assert "acesso em 16/10/2026" in rv["aviso"] and "08/07/2026" not in rv["aviso"]
    assert "ainda não está" not in rv["aviso"] and rv["fonte_literal"]["url"].startswith(
        "https://www.bcb.gov.br/"
    )


def test_in758_sem_texto_conferido_nao_cita(monkeypatch):
    """Arquivo ausente ou editado depois da conferência: nada de citação e o aviso diz "não conferido"."""
    from laudo.rulebooks import normas

    monkeypatch.setattr(normas, "citacao_reversao", lambda: None)
    assert pacote.in758_literal() is None
    rv = pacote.reversao_in758({}, {}, [])
    assert rv["citacao_conferida"] is False and rv["citacao_literal"] is None and rv["fonte_literal"] is None
    assert "não está conferido" in rv["aviso"]


def test_acao_humana_fora_do_registro_do_agente():
    from laudo.contracts import REGISTRO
    from laudo.tools import carregar_todas

    assert pacote.ACAO not in carregar_todas() and pacote.ACAO not in REGISTRO
    assert pacote.ACAO in pacote.ACOES_HUMANAS


# ---------------------------------------------------------------------------
# Lento: replay da demo real (ferramentas reais; a gravação do LLM não muda)
# ---------------------------------------------------------------------------

FIXTURE_REAL = Path(__file__).parent / "dados_agente" / "replay_demo_real_qwen35_4b.jsonl"


@pytest.mark.lento
def test_pacote_da_demo_real_selada(tmp_path, monkeypatch):
    if not os.environ.get("LAUDO_LENTO") and "lento" not in (os.environ.get("PYTEST_ADDOPTS") or ""):
        pytest.skip("teste lento: rode com LAUDO_LENTO=1")
    from laudo.agent import roteiro_demo as rd
    from laudo.agent.condutor import Condutor
    from laudo.audit import otel
    from laudo.llm.provider import ReplayProvider
    from laudo.tools import carregar_todas
    from laudo.vision.modelos import MODELOS

    caso = rd.carregar_caso_real()
    faltam = [n for n, ev in caso.evidencias.items() if ev.caminho and not Path(ev.caminho).is_file()]
    if faltam or not MODELOS["yolox_m"].caminho.is_file():
        pytest.skip(f"dados locais ausentes: {faltam or 'modelo yolox_m'}")
    monkeypatch.setenv("LAUDO_VLM_CACHE", str(Path(__file__).parent / "dados_agente" / "vlm_cache_demo"))
    monkeypatch.setenv("LAUDO_VLM_SO_CACHE", "1")
    otel.configurar(tmp_path / "traces")
    est.ids_deterministicos(rd.SEMENTE_IDS_REAL)
    try:
        prov = ReplayProvider(FIXTURE_REAL, sequencial_se_ausente=True)
        cond = Condutor(
            prov,
            repo=est.RepositorioFiscalizacoes(tmp_path),
            registro=dict(carregar_todas()),
            hoje=caso.data_referencia,
        )
        rd.executar_real(cond, caso, com_danfe=True)
        assert prov.substituicoes == 0  # o pacote não mexe no que o LLM recebe
        fis = cond.repo.carregar(rd.FIS_ID_REAL)
        assert fis.estado_fsm == "SELADO"
        env = pacote.executar(fis, tmp_path / "laudos" / fis.id, otel.arquivo_trace(fis.id))
    finally:
        est.ids_deterministicos(None)
        ferr_laudo.configurar(None, None)
    assert env.ok and env.data["faltas"] == [], env.data
    zp = Path(env.data["arquivo"])
    assert pacote.validar_pacote(zp) == []
    arqs = _ler(zp.read_bytes())
    st = {i["id"]: i["status"] for i in json.loads(arqs[pacote.ARQ["checklist"]])["itens"]}
    fu = json.loads(arqs[pacote.ARQ["fundamento"]])
    fund, docs = fu["itens"], fu["documentos_fiscais"]
    assert fund and all(f["literal"] for f in fund)  # fundamento literal por campo (rulebook + docs/normas)
    # as regras de NF-e/GTA do catálogo vão como resumo: o checklist não diz "presente" se alguma não é
    # literal
    assert docs and all(d["status"] for d in docs)
    assert all(not d["literal"] for d in docs if d["status"] == "resumo")
    fund_esperado = "presente" if all(d["literal"] for d in docs) else "parcial"
    assert st == {
        "vetor_poligono": "presente",
        "coordenadas": "presente",
        "imagens_datadas": "presente",
        "meteorologia": "nao_aplicavel",
        "fundamento": fund_esperado,
    }
    cenas = json.loads(arqs[pacote.ARQ["cenas"]])["cenas"]
    assert cenas and all(c["id_cena"].startswith(("S2A_", "S2B_", "S2C_")) for c in cenas)
    assert all(c["sensor"] and c["resolucao_espacial_m"] == 10 and "B08" in c["bandas"] for c in cenas)
    mem = json.loads(arqs[pacote.ARQ["memoria"]])
    assert mem["contagem"][0]["status_campo"] == "divergente" and mem["contagem"][0]["justificativa_humana"]
    crit = [k for c in mem["conciliacoes"] for k in c["criterios"]]
    assert crit and all(k["regra_id"] for k in crit)
