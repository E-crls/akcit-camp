"""Split `casos_publicos`: 6 cenários inspirados em casos públicos, rodados no modo determinístico.

Confere: (1) os arquivos versionados são exatamente os que o gerador produz; (2) cada caso traz item
normativo e URL da fonte, com dados só sintéticos; (3) os 6 dão os status esperados com o condutor sem LLM;
(4) o índice de reuso é por operação (refiscalização não acusa) e só a selagem registra; (5) o split de TESTE
do golden principal continua com o mesmo hash (congelado em 16/10/2026).
"""

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

import casos_publicos as CP

DIR = REPO / "eval" / "golden" / "casos_publicos"
DIR_GOLDEN = REPO / "eval" / "golden" / "casos"
SHA_TESTE_CONGELADO = "f47e444648b42130268cede1a0c37803cce49035200ed8fe918b3dbb0d735dcd"
SHA_SPLIT_CONGELADO = "9e51b91272fcc1b38e669fa358c39328be35d289d25e0c42e72f4e3628c10f38"
CENARIOS = {  # id → palavra-chave do mecanismo pedido no memorando (seção 5A, item 5)
    "PUB-0001": "Pains",
    "PUB-0002": "Boi de Papel",
    "PUB-0003": "Orizona/Vianópolis",
    "PUB-0004": "ZF04-20",
    "PUB-0005": "destino",
    "PUB-0006": "abaixo da GTA",
}


def _casos() -> list[tuple[dict, Path]]:
    return CP.carregar(DIR)


def test_arquivos_versionados_sao_os_do_gerador(tmp_path):
    meta = CP.gerar(CP.PUBLICOS, tmp_path)
    versionado = yaml.safe_load((DIR / "SPLIT.yaml").read_text(encoding="utf-8"))
    assert meta["sha256_conteudo"] == versionado["sha256_conteudo"]
    for c in versionado["casos"]:
        for nome, sha in c["arquivos"].items():
            b = (DIR / c["id"] / nome).read_bytes()
            assert hashlib.sha256(b).hexdigest() == sha, (c["id"], nome)
            assert b == (tmp_path / c["id"] / nome).read_bytes(), (c["id"], nome)
    assert sorted(p.name for p in DIR.glob("PUB-*")) == sorted(CENARIOS)


def test_seis_cenarios_com_item_normativo_e_fonte():
    casos = _casos()
    assert [c["id"] for c, _ in casos] == list(CENARIOS)
    textos = {
        c["id"]: f"{c['titulo']} {c['inspiracao']['caso']} {c['inspiracao']['item_normativo']}"
        for c, _ in casos
    }
    for c, _ in casos:
        insp = c["inspiracao"]
        assert CENARIOS[c["id"]].lower() in textos[c["id"]].lower(), c["id"]
        assert insp["url"].startswith("https://") and insp["fonte"]
        if c["id"] == "PUB-0005":  # sem data de acesso registrada: não se põe a de hoje (revisão da onda 3)
            assert insp["acesso"] is None and "não registrada" in insp["acesso_nota"]
        else:
            assert insp["acesso"] == "2026-10-16"
        assert re.search(r"(MCR|NT 2024\.003|Manual SDA|OP-)", insp["item_normativo"]), c["id"]
        assert insp["o_que_prova"] and insp["o_que_nao_prova"]
        assert c["split"] == "casos_publicos" and c["sintetico"] is True


def test_dados_sinteticos_sem_nome_real():
    from laudo.docs_fiscais.comum import cnpj_valido, cpf_valido, so_alnum

    for c, d in _casos() + CP.carregar(CP.DIR_CUSTEIO):
        assert "TESTE" in c["tomador"]["nome"] and "TESTE" in c["projeto"]["propriedade"]["nome"]
        assert c["tomador"]["documento_sintetico"].startswith("000000") and cpf_valido(
            c["tomador"]["documento_sintetico"]
        )
        for arq in d.glob("gta_*.json"):
            g = json.loads(arq.read_text(encoding="utf-8"))
            assert g["sintetico"] is True
            for lado in ("origem", "destino"):
                assert "TESTE" in g[lado]["nome"] and "TESTE" in g[lado]["estabelecimento"]
                doc = so_alnum(g[lado]["documento"])
                assert doc.startswith(("000000", "99999999"))
        for arq in d.glob("nfe_*.xml"):
            x = arq.read_text(encoding="utf-8")
            assert "<tpAmb>2</tpAmb>" in x and "SEM VALOR FISCAL" in x
            cnpjs = re.findall(r"<CNPJ>(\d{14})</CNPJ>", x)
            assert cnpjs and all(n.startswith("99999999") and cnpj_valido(n) for n in cnpjs)
        # municípios das notícias não aparecem nos dados (só na citação da fonte)
        dados = yaml.safe_dump({k: v for k, v in c.items() if k != "inspiracao"}, allow_unicode=True)
        dados += "".join(p.read_text(encoding="utf-8") for p in d.iterdir() if p.suffix in (".json", ".xml"))
        assert (
            "ORIZONA" not in dados.upper()
            and "VIANÓPOLIS" not in dados.upper()
            and "PAINS" not in dados.upper()
        )


@pytest.mark.parametrize("cid", list(CENARIOS))
def test_cenario_no_modo_deterministico(cid, tmp_path):
    caso, d = next((c, x) for c, x in _casos() if c["id"] == cid)
    r = CP.rodar(caso, d, tmp_path)
    assert CP.conferir(caso, r) == [], r["campos"]
    # nenhum dos cenários fecha sem humano: divergente ou pendente sempre pede justificativa ou nova evidência
    assert not r["emissao_permitida"]


def test_reuso_so_aparece_com_laudo_selado_de_outra_operacao(tmp_path):
    """Sem o laudo selado da outra operação (índice vazio), o PUB-0004 verifica NF-e e GTA: o achado é o
    reuso."""
    caso, d = next((c, x) for c, x in _casos() if c["id"] == "PUB-0004")
    assert caso["pre_indice"]["operacao"] != caso["operacao"]["ref_bacen"]
    r = CP.rodar({**caso, "pre_indice": None}, d, tmp_path)
    assert (
        r["campos"]["item:bov1:comprovante_nfe"] == "verificado"
        and r["campos"]["item:bov1:gta"] == "verificado"
    )
    assert r["finos"]["documento:gta:reuso"] == "verificado"


def test_refiscalizacao_da_mesma_operacao_nao_e_reuso(tmp_path):
    """Laudo da operação selado (registro feito a partir do estado do condutor) e a mesma operação fiscalizada
    de novo com os mesmos documentos: reuso ok. Outra operação com os mesmos documentos: divergente."""
    caso, d = next((c, x) for c, x in _casos() if c["id"] == "PUB-0004")
    indice = tmp_path / "indice_compartilhado.jsonl"
    primeira = CP.rodar({**caso, "pre_indice": None}, d, tmp_path / "1", indice=indice, selar=True)
    assert primeira["selados_no_indice"] == 2  # a NF-e e a GTA das conciliações finais
    de_novo = CP.rodar({**caso, "pre_indice": None}, d, tmp_path / "2", indice=indice)
    assert de_novo["finos"]["documento:gta:reuso"] == "verificado"
    assert de_novo["finos"]["documento:nfe:reuso"] == "verificado"
    assert de_novo["campos"]["item:bov1:gta"] == "verificado"
    op_outra = {**caso["operacao"], "ref_bacen": "SINT-PUB-OUTRA-000004"}
    outra = {**caso, "pre_indice": None, "operacao": op_outra}
    r = CP.rodar(outra, d, tmp_path / "3", indice=indice)
    assert r["finos"]["documento:gta:reuso"] == "divergente" and r["campos"]["item:bov1:gta"] == "divergente"


def test_uma_guia_por_nfe_e_numeros_da_fonte():
    """NT 2024.003 v1.03: cada NF-e traz no máximo um grupo ZF (a GTA da carga 1). PUB-0006 cita o número da
    fonte (WLJ, 19/05/2023: 10.559 achadas)."""
    for c, d in _casos():
        for arq in d.glob("nfe_*.xml"):
            assert arq.read_text(encoding="utf-8").count("<guiaTransito>") <= 1, (c["id"], arq.name)
    pains = next(c for c, _ in _casos() if c["id"] == "PUB-0001")
    assert pains["documentos"]["nfe"][0]["grupo_zf"] == "GO-A-520201" and len(pains["documentos"]["gta"]) == 4
    eua = next(c for c, _ in _casos() if c["id"] == "PUB-0006")["inspiracao"]["caso"]
    assert "89.522" in eua and "10.559" in eua and "10.575" not in eua


def test_pub_0005_e_cenario_construido_sem_atribuir_a_noticia():
    """O mecanismo "GTA com destino em outro imóvel" não está na notícia de Pains (ela relata gado ausente nas
    propriedades vistoriadas): o caso é marcado como construído e a fonte é só a regra do destino."""
    casos = {c["id"]: c for c, _ in _casos()}
    insp = casos["PUB-0005"]["inspiracao"]
    assert insp["natureza"] == "cenario_construido" and "Manual SDA" in insp["fonte"]
    assert insp["url"] == CP._URL_MANUAL_SDA and "data_noticia" not in insp
    assert "pains" not in yaml.safe_dump(insp, allow_unicode=True).lower()
    assert all("natureza" not in c["inspiracao"] for cid, c in casos.items() if cid != "PUB-0005")


def test_papel_de_cada_split_no_manifesto():
    pub = yaml.safe_load((DIR / "SPLIT.yaml").read_text(encoding="utf-8"))
    dev = yaml.safe_load((CP.DIR_CUSTEIO / "SPLIT.yaml").read_text(encoding="utf-8"))
    assert pub["split"] == "casos_publicos" and pub["papel"].startswith("avaliacao_separada")
    assert dev["split"] == "dev_custeio" and dev["papel"].startswith("dev:") and dev["congelado"] is False
    assert pub["gerador"]["versao"] == dev["gerador"]["versao"] == CP.VERSAO


def test_estado_global_restaurado(tmp_path):
    """O runner não vaza ids determinísticos nem o diretório de traces para outros testes."""
    from laudo.agent import estado as est
    from laudo.audit import otel

    antes_ids, antes_dir = dict(est._IDS), otel._estado.get("diretorio")
    caso, d = _casos()[0]
    CP.rodar(caso, d, tmp_path)
    assert est._IDS == antes_ids and otel._estado.get("diretorio") == antes_dir


def test_split_de_teste_do_golden_inalterado():
    """O split novo não toca o golden principal: o hash do TESTE congelado continua o de 16/10/2026."""
    split = yaml.safe_load((DIR_GOLDEN / "SPLIT.yaml").read_text(encoding="utf-8"))
    assert split["congelado"] is True
    por_id = {c["id"]: c["sha256_caso"] for c in split["casos"]}
    for cid in split["dev"] + split["test"]:
        b = (DIR_GOLDEN / cid / "caso.yaml").read_bytes()
        assert hashlib.sha256(b).hexdigest() == por_id[cid], cid
    sha_test = hashlib.sha256("".join(f"{cid}:{por_id[cid]}\n" for cid in split["test"]).encode()).hexdigest()
    sha_split = hashlib.sha256(
        json.dumps({"dev": split["dev"], "test": split["test"]}, sort_keys=True).encode()
    ).hexdigest()
    assert sha_test == split["sha256_conteudo"]["test"] == SHA_TESTE_CONGELADO
    assert sha_split == split["sha256_split"] == SHA_SPLIT_CONGELADO
    assert not set(CENARIOS) & set(split["dev"] + split["test"])
