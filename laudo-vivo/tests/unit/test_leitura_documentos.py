"""Leitura de DANFE/GTA por foto (`ler_documento_foto`): o VLM só transcreve; a validação determinística decide.

Sem GPU: o VLM é trocado por um leitor falso (`configurar_leitor`) que devolve a transcrição verdadeira, uma
com erro plantado ou lixo. Imagens e PDF vêm do gerador de entradas bagunçadas (`eval/golden/gerador`).
"""

from __future__ import annotations

import json
import random
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from laudo.docs_fiscais import leitura as L
from laudo.docs_fiscais.comum import hash_documento
from laudo.tools import documentos as D
from laudo.tools import leitura_documentos as LD

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "eval" / "golden" / "gerador"))
import documentos_imagem as DI

CASO = REPO / "eval" / "golden" / "casos" / "GLD-0002"
HOJE = date(2026, 10, 8)


def _caso() -> dict[str, Any]:
    return yaml.safe_load((CASO / "caso.yaml").read_text(encoding="utf-8"))


def _xml() -> bytes:
    return (CASO / "nfe_1.xml").read_bytes()


def _gta() -> dict[str, Any]:
    return json.loads((CASO / "gta_1.json").read_text(encoding="utf-8"))


def _danfe_impresso(xml: bytes) -> dict[str, dict[str, Any]]:
    """O que um leitor perfeito transcreveria do DANFE, no esquema de cada recorte."""
    d = DI.dados_danfe(xml)
    linhas = [f"{it['codigo']} | {it['descricao']} | {it['ncm']} | 040 | {it['cfop']} | {it['unidade']} | "
              f"{DI.br_num(it['quantidade'], 0)} | {DI.br_num(it['valor_unitario'])} | {DI.br_num(it['valor_total'])}"
              for it in d["itens"]]
    num = f"{d['numero']:09d}"
    return {
        "cima": {"chave_acesso": DI.fmt_chave(d["chave"]), "numero_nfe": f"{num[:3]}.{num[3:6]}.{num[6:]}",
                 "serie": f"{d['serie']:03d}", "data_emissao": d["dh_emi"].strftime("%d/%m/%Y"),
                 "emitente_nome": d["emitente"]["nome"], "emitente_cnpj_cpf": DI.fmt_doc(d["emitente"]["doc"]),
                 "emitente_municipio": d["emitente"]["mun"], "emitente_uf": d["emitente"]["uf"],
                 "destinatario_nome": d["destinatario"]["nome"],
                 "destinatario_cnpj_cpf": DI.fmt_doc(d["destinatario"]["doc"]),
                 "destinatario_uf": d["destinatario"]["uf"], "entrada_ou_saida": d["tp_nf"]},
        "baixo": {"linhas_produtos": linhas, "v_total_produtos": DI.br_num(d["v_prod"]),
                  "valor_total_da_nota": DI.br_num(d["v_nf"]), "informacoes_complementares": d["inf_cpl"]},
    }


def _gta_impressa(g: dict[str, Any]) -> dict[str, dict[str, Any]]:
    q = {(x["sexo"], x["faixa_etaria"]): x["quantidade"] for x in g["quantidades"]}

    def col(s: str | None) -> dict[str, str]:
        out = {}
        for fx in DI.FAIXAS:
            v = q.get((s, fx), 0) if s else q.get(("M", fx), 0) + q.get(("F", fx), 0)
            out[fx] = str(v) if v else "-"
        tot = sum(v for (sx, _), v in q.items() if s is None or sx == s)
        out["TOTAL"] = str(tot)
        return out

    def local(lado: str) -> dict[str, str]:
        x = g[lado]
        return {"nome": x["nome"], "cpf_cnpj": DI.fmt_doc(x["documento"]), "estabelecimento": x["estabelecimento"],
                "codigo_estabelecimento": x["codigo_estabelecimento"], "municipio": x["municipio_nome"],
                "cod_ibge": x["municipio_ibge"], "uf": x["uf"]}

    em = g["emissao"]
    return {
        "cima": {"uf": g["uf_emissao"], "serie": g["serie"], "numero": g["numero"], "especie": g["especie"].upper(),
                 "coluna_machos": col("M"), "coluna_femeas": col("F"), "coluna_total": col(None),
                 "total_por_extenso": g["total_por_extenso"], "procedencia": local("origem")},
        "baixo": {"destino": local("destino"), "finalidade": g["finalidade"], "observacoes": g.get("observacao") or "",
                  "emitente": "PRODUTOR - EMISSAO ELETRONICA", "data_emissao": DI._data_br(em["data"]),
                  "valida_ate": DI._data_br(em["validade"]), "local_emissao": em["local_municipio"],
                  "chave_nfe": DI.fmt_chave(g["nfe_chaves"][0])},
    }


def _leitor(impresso: dict[str, dict[str, Any]], tipo: str = "danfe", mexer=None):
    """Leitor falso: escolhe o recorte pelo esquema; `mexer(recorte, dict, semente)` planta erro."""

    def ler(img_b64, prompt, esquema, temperatura, semente):
        props = esquema["properties"]
        if "tipo" in props and len(props) == 1:
            return {"tipo": tipo}
        nome = "cima" if ("chave_acesso" in props or "coluna_machos" in props) else "baixo"
        d = json.loads(json.dumps(impresso[nome]))
        return mexer(nome, d, semente) if mexer else d

    return ler


@pytest.fixture()
def foto_danfe(tmp_path) -> Path:
    foto, meta = DI.fotografar(DI.renderizar_danfe(_xml()), "leve", random.Random(1))
    arq = tmp_path / "danfe.jpg"
    arq.write_bytes(DI.jpeg_bytes(foto, meta["jpeg_q"]))
    return arq


@pytest.fixture(autouse=True)
def _sem_vlm():
    yield
    LD.configurar_leitor(None)


def _rodar(arq: Path, tipo: str = "danfe") -> dict[str, Any]:
    env = LD.ler_documento_foto(LD.EntradaLerDocumento(caminho=str(arq), tipo_documento=tipo, data_referencia=HOJE))
    assert env.ok, env.error
    return env.data


# ---------------------------------------------------------------------------
# DANFE
# ---------------------------------------------------------------------------


def test_danfe_lido_certo_valida_tudo_e_concilia_como_o_xml(foto_danfe):
    LD.configurar_leitor(_leitor(_danfe_impresso(_xml())))
    d = _rodar(foto_danfe)
    assert d["status"] == "ok" and d["k"] == 2 and d["chamadas_vlm"] == 4
    doc = d["documento"]
    assert doc["chave"] == _caso()["documentos"]["nfe"][0]["chave"]
    assert doc["itens"][0]["quantidade"] == 4 and doc["v_prod"] == 58200.0
    # conciliação: conteúdo igual ao do XML; integridade e autorização ficam pendentes (DANFE não prova)
    ent = _caso()["entradas_ferramentas"]["conciliar_nfe"]
    base = {k: v for k, v in ent.items() if k != "caminhos"}
    foto = D.conciliar_nfe(D.EntradaConciliarNFe(**base, leituras_foto=[doc])).data["campos"]
    xml = D.conciliar_nfe(D.EntradaConciliarNFe(**base, caminhos=[str(CASO / "nfe_1.xml")])).data["campos"]
    for campo in ("nfe_especie", "nfe_quantidade", "nfe_valor", "nfe_data", "nfe_partes", "nfe_operacao"):
        assert foto[f"item:bov1:{campo}"]["status"] == xml[f"item:bov1:{campo}"]["status"] == "ok", campo
    assert foto["documento:nfe:integridade"]["status"] == "indeterminado"
    assert foto["documento:nfe:autorizacao"]["status"] == "indeterminado"


def test_saida_nao_tem_cpf_cnpj_em_claro(foto_danfe):
    LD.configurar_leitor(_leitor(_danfe_impresso(_xml())))
    d = DI.dados_danfe(_xml())
    # a chave de acesso (necessária para consultar a SEFAZ) embute o CNPJ do emitente, como no caminho do XML
    texto = json.dumps(_rodar(foto_danfe), ensure_ascii=False).replace(d["chave"], "<chave>")
    for doc in (d["emitente"]["doc"], d["destinatario"]["doc"]):
        assert doc not in texto and DI.fmt_doc(doc) not in texto
    assert hash_documento(d["destinatario"]["doc"]) in texto  # a parte é conferida pelo hash


def test_um_digito_errado_na_chave_em_todas_as_leituras_nunca_e_aceito(foto_danfe):
    def mexer(nome, d, semente):
        if nome == "cima":
            ch = d["chave_acesso"].replace(" ", "")
            d["chave_acesso"] = ch[:10] + str((int(ch[10]) + 1) % 10) + ch[11:]
        return d

    LD.configurar_leitor(_leitor(_danfe_impresso(_xml()), mexer=mexer))
    d = _rodar(foto_danfe)
    assert d["status"] == "indeterminado"
    assert d["campos"]["chave"]["status"] == "indeterminado" and "DV" in d["campos"]["chave"]["motivo"]
    assert d["documento"]["chave"] is None
    assert "Refaça a foto" in d["pedido_nova_foto"]


def test_chave_com_um_erro_diferente_por_leitura_sai_certa_pelo_voto_posicional(foto_danfe):
    certa = _danfe_impresso(_xml())["cima"]["chave_acesso"].replace(" ", "")

    def mexer(nome, d, semente):
        if nome == "cima":
            i = {1000: 5, 1001: 20, 1002: 33}[semente]  # cada leitura erra num dígito diferente
            d["chave_acesso"] = certa[:i] + str((int(certa[i]) + 3) % 10) + certa[i + 1:]
        return d

    LD.configurar_leitor(_leitor(_danfe_impresso(_xml()), mexer=mexer))
    d = _rodar(foto_danfe)
    assert d["k"] == 3 and d["documento"]["chave"] == certa
    assert d["campos"]["chave"]["concordancia"].startswith("posicional")


def test_aritmetica_que_nao_fecha_barra_a_quantidade_e_a_conciliacao_nao_diverge(foto_danfe):
    def mexer(nome, d, semente):
        if nome == "baixo":  # leu 7 em vez de 4 (as duas leituras igual)
            d["linhas_produtos"] = [d["linhas_produtos"][0].replace(" | 4 | ", " | 7 | ")]
        return d

    LD.configurar_leitor(_leitor(_danfe_impresso(_xml()), mexer=mexer))
    d = _rodar(foto_danfe)
    assert d["campos"]["item1.quantidade"]["status"] == "indeterminado"
    assert "valor total" in d["campos"]["item1.quantidade"]["motivo"]
    ent = {k: v for k, v in _caso()["entradas_ferramentas"]["conciliar_nfe"].items() if k != "caminhos"}
    campos = D.conciliar_nfe(D.EntradaConciliarNFe(**ent, leituras_foto=[d["documento"]])).data["campos"]
    assert campos["item:bov1:nfe_quantidade"]["status"] == "indeterminado"  # nunca "divergente" por leitura


def test_ncm_ilegivel_nao_vira_especie_divergente():
    doc = L.validar_danfe({**_bruto_certo(), "itens": [{**_bruto_certo()["itens"][0], "ncm": "0102"}]}, HOJE).documento
    assert doc["itens"][0]["ncm"] is None
    ent = {k: v for k, v in _caso()["entradas_ferramentas"]["conciliar_nfe"].items() if k != "caminhos"}
    campos = D.conciliar_nfe(D.EntradaConciliarNFe(**ent, leituras_foto=[doc])).data["campos"]
    assert campos["item:bov1:nfe_especie"]["status"] == "indeterminado"


def _bruto_certo() -> dict[str, Any]:
    p = _danfe_impresso(_xml())
    return LD.montar_bruto("danfe", p)


def test_campos_decompostos_da_chave_e_do_cfop():
    b = _bruto_certo()
    b.update(emitente_doc="", serie="", numero="", emitente_uf="", destinatario_uf="", tp_nf="")
    r = L.validar_danfe(b, HOJE)
    for nome in ("emitente_doc", "serie", "numero", "emitente_uf"):
        assert r.campos[nome].status == "ok" and r.campos[nome].origem == "derivado:chave", nome
    assert r.campos["destinatario_uf"].origem == r.campos["tp_nf"].origem == "derivado:cfop"


def test_chave_valida_mas_incoerente_com_o_cnpj_lido():
    b = _bruto_certo()
    b["emitente_doc"] = "99999999000191"  # CNPJ sintético com DV válido, mas de outra empresa
    r = L.validar_danfe(b, HOJE)
    assert r.campos["chave"].status == "indeterminado" and "emitente_doc" in r.campos["chave"].motivo
    assert r.campos["emitente_doc"].status == "indeterminado"


def test_data_futura_e_uf_x_cfop_incoerentes():
    b = _bruto_certo()
    b["data_emissao"], b["destinatario_uf"] = "01/12/2026", "MT"
    r = L.validar_danfe(b, HOJE)
    assert r.campos["data_emissao"].status == "indeterminado"
    assert r.campos["destinatario_uf"].status == "indeterminado" and "CFOP" in r.campos["destinatario_uf"].motivo


def test_vlm_que_devolve_lixo_nao_inventa_nada(foto_danfe):
    LD.configurar_leitor(lambda *a: {"chave_acesso": "ola", "linhas_produtos": ["nada"]})
    d = _rodar(foto_danfe)
    assert d["status"] == "indeterminado" and d["campos_aceitos"] == 0
    assert all(v in (None, [], {}) or k in ("tipo", "emitente", "destinatario", "ilegiveis", "modelo", "proveniencia")
               for k, v in d["documento"].items())


def test_danfe_e_xml_da_mesma_nota_nao_viram_nota_duplicada():
    doc = L.validar_danfe(_bruto_certo(), HOJE).documento
    ent = _caso()["entradas_ferramentas"]["conciliar_nfe"]
    base = {**ent, "caminhos": [str(CASO / "nfe_1.xml")]}
    data = D.conciliar_nfe(D.EntradaConciliarNFe(**base, leituras_foto=[doc])).data
    assert data["status"] == "ok" and data["danfe_fotos"] == {"novas": 0, "conferidas_com_xml": 1}
    doc_errado = json.loads(json.dumps(doc))
    doc_errado["itens"][0]["quantidade"] = 5.0  # papel diferente do XML autorizado
    data = D.conciliar_nfe(D.EntradaConciliarNFe(**base, leituras_foto=[doc_errado])).data
    assert data["campos"]["documento:nfe:integridade"]["status"] == "indeterminado"
    assert data["status"] != "divergente"


# ---------------------------------------------------------------------------
# GTA (foto e PDF de scan)
# ---------------------------------------------------------------------------


@pytest.fixture()
def pdf_gta(tmp_path) -> Path:
    arq = tmp_path / "gta.pdf"
    arq.write_bytes(DI.pdf_bytes(DI.renderizar_gta(_gta())))
    return arq


def test_gta_em_pdf_de_scan_lida_e_conciliada_como_o_json(pdf_gta):
    LD.configurar_leitor(_leitor(_gta_impressa(_gta()), "gta"))
    d = _rodar(pdf_gta, "auto")
    assert d["tipo_documento"] == "gta" and d["status"] == "ok"
    doc = d["documento"]
    assert doc["total"] == 4 and doc["destino"]["municipio_ibge"] == "5216403"
    ent = _caso()["entradas_ferramentas"]["conciliar_gta"]
    base = {**{k: v for k, v in ent.items() if k not in ("caminhos", "nfe_caminhos")},
            "nfe_caminhos": [str(CASO / "nfe_1.xml")]}
    foto = D.conciliar_gta(D.EntradaConciliarGTA(**base, leituras_foto=[doc])).data
    js = D.conciliar_gta(D.EntradaConciliarGTA(**base, caminhos=[str(CASO / "gta_1.json")])).data
    assert {k: v["status"] for k, v in foto["campos"].items()} == {k: v["status"] for k, v in js["campos"].items()}


def test_grade_que_nao_soma_nao_vira_zero_cabecas(pdf_gta):
    def mexer(nome, d, semente):
        if nome == "cima":
            d["total_por_extenso"] = "CINCO BOVINOS"  # o extenso não confere com a linha TOTAL
        return d

    LD.configurar_leitor(_leitor(_gta_impressa(_gta()), "gta", mexer))
    d = _rodar(pdf_gta, "gta")
    assert d["campos"]["total"]["status"] == "indeterminado" and d["documento"]["total"] is None
    ent = _caso()["entradas_ferramentas"]["conciliar_gta"]
    base = {k: v for k, v in ent.items() if k not in ("caminhos", "nfe_caminhos")}
    campos = D.conciliar_gta(D.EntradaConciliarGTA(**base, leituras_foto=[d["documento"]])).data["campos"]
    assert campos["item:bov1:gta_quantidade"]["status"] == "indeterminado"
    assert campos["item:bov1:gta_especie"]["status"] == "indeterminado"


def test_celula_vazia_e_ilegivel_nao_zero():
    assert L.inteiro_celula("-") == 0 and L.inteiro_celula("") is None and L.inteiro_celula("17") == 17


def test_ibge_dv_e_nome_do_municipio():
    assert L.ibge_dv_ok("5216403") and not L.ibge_dv_ok("5216404")
    c: dict[str, L.CampoLido] = {}
    L._local(c, "destino", {"ibge": "5216403", "municipio": "PARAUNA", "uf": "GO", "doc": "", "nome": "",
                            "codigo_estabelecimento": "TESTE-5216403-0002"})
    assert c["destino.municipio"].status == c["destino.ibge"].status == "ok"
    L._local(c, "destino", {"ibge": "5216403", "municipio": "CRIXAS", "uf": "GO"})
    assert c["destino.municipio"].status == c["destino.ibge"].status == "indeterminado"


def test_extenso_e_numeros_brasileiros():
    assert L.extenso_para_int("VINTE E NOVE BOVINOS") == 29 and L.extenso_para_int("QUARENTA BOVINOS") == 40
    assert L.extenso_para_int("duzentas cabeças") == 200
    assert L.valor_br("14.550,00") == 14550.0 and L.valor_br("4") == 4.0 and L.valor_br("14.55") is None


def test_consenso_exige_duas_leituras_iguais():
    a = {"chave": "1" * 44, "numero": "1", "itens": [{"quantidade": "4"}]}
    b = {"chave": "1" * 44, "numero": "2", "itens": [{"quantidade": "4,0000"}]}
    cons, conc = L.consenso([a, b])
    assert conc["chave"] == "2/2" and conc["numero"] == "discordante" and cons["numero"] == ""
    assert cons["itens"][0]["quantidade"] == "4,0000" and conc["itens.0.quantidade"] == "2/2"


def test_pdf_sem_imagem_e_entrada_invalida(tmp_path):
    arq = tmp_path / "texto.pdf"
    arq.write_bytes(b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << >>\n%%EOF")
    env = LD.ler_documento_foto(LD.EntradaLerDocumento(caminho=str(arq), tipo_documento="gta"))
    assert not env.ok and env.error.code == "ENTRADA_INVALIDA"


def test_vlm_fora_do_ar_vira_erro_sem_valor(foto_danfe):
    import httpx

    def cai(*a):
        raise httpx.ConnectError("recusado")

    LD.configurar_leitor(cai)
    env = LD.ler_documento_foto(LD.EntradaLerDocumento(caminho=str(foto_danfe), tipo_documento="danfe"))
    assert not env.ok and env.data is None


# ---------------------------------------------------------------------------
# Integração com o condutor (plano mínimo) e a FSM
# ---------------------------------------------------------------------------


def test_llm_nao_recebe_as_ferramentas_do_plano():
    from laudo.agent import fsm

    nomes = fsm.nomes_permitidos("CHECAGEM", ["ler_documento_foto", "conciliar_alegacoes", "conciliar_nfe"])
    assert "conciliar_nfe" in nomes and "ler_documento_foto" not in nomes and "conciliar_alegacoes" not in nomes
    assert "ler_documento_foto" in fsm.acoes_permitidas("CHECAGEM")  # a política permite (plano)


def test_upload_de_foto_do_danfe_le_e_concilia_no_plano_minimo(tmp_path, foto_danfe):
    from laudo.agent import estado as est
    from laudo.agent.condutor import Condutor, Evento, NovaEvidencia
    from laudo.contracts import REGISTRO, Operacao
    from laudo.tools import carregar_todas

    carregar_todas()
    LD.configurar_leitor(_leitor(_danfe_impresso(_xml())))
    caso = _caso()
    reg = {k: REGISTRO[k] for k in ("ler_documento_foto", "conciliar_nfe", "conciliar_gta", "conciliar_alegacoes",
                                    "registrar_ocorrencia", "emitir_rascunho")}
    cond = Condutor(None, repo=est.RepositorioFiscalizacoes(tmp_path / "fis"), registro=reg,
                    hoje=date.fromisoformat(caso["data_fiscalizacao"]))
    op = Operacao.model_validate({**caso["operacao"], "tomador_ref": caso["tomador"]["documento_sha256"]})
    fis = cond.abrir(op, data_referencia=date.fromisoformat(caso["data_fiscalizacao"]))
    assert fis.operacao.tomador_ref.startswith("hmac:")  # o hash público não entra no estado
    ev = NovaEvidencia(tipo="documento", caminho=str(foto_danfe), item_id="bov1",
                       meta={"item_id": "bov1", "tipo_documento": "danfe"})
    r = cond.turno(fis.id, Evento(texto="Foto da nota que o produtor me deu.", evidencia=ev))
    feitas = [a.acao for a in r.acoes]
    assert feitas.index("ler_documento_foto") < feitas.index("conciliar_nfe")
    final = cond.repo.carregar(fis.id)
    chk = next(c for c in final.checagens if c.ferramenta == "conciliar_nfe")
    assert chk.resultado["campos"]["item:bov1:nfe_quantidade"]["status"] == "ok"
    assert chk.resultado["danfe_fotos"]["novas"] == 1
    assert f"hmac:{hash_documento(DI.dados_danfe(_xml())['destinatario']['doc'])}" == final.operacao.tomador_ref


def test_duas_fotos_da_mesma_nota_sao_uma_nota_so_e_se_completam():
    certo = L.validar_danfe(_bruto_certo(), HOJE).documento
    b1 = _bruto_certo()
    b1["itens"] = [{**b1["itens"][0], "quantidade": "7"}]  # 1ª foto: conta não fecha → quantidade barrada
    foto1 = L.validar_danfe(b1, HOJE).documento
    assert foto1["itens"][0]["quantidade"] is None
    (m,), alertas = L.mesclar_leituras([foto1, certo])
    assert m["itens"][0]["quantidade"] == 4 and m["chave"] == certo["chave"] and not alertas
    ent = {k: v for k, v in _caso()["entradas_ferramentas"]["conciliar_nfe"].items() if k != "caminhos"}
    data = D.conciliar_nfe(D.EntradaConciliarNFe(**ent, leituras_foto=[foto1, certo])).data
    assert data["danfe_fotos"]["novas"] == 1  # nunca "NF-e apresentada mais de uma vez"
    assert data["campos"]["item:bov1:nfe_quantidade"]["status"] == "ok"


def test_cache_do_vlm_permite_replay_sem_gpu(tmp_path, foto_danfe, monkeypatch):
    chamadas = []
    base = _leitor(_danfe_impresso(_xml()))

    def contando(*a):
        chamadas.append(1)
        return base(*a)

    monkeypatch.setattr(LD, "_ollama", lambda modelo, timeout: contando)
    monkeypatch.setenv("LAUDO_VLM_CACHE", str(tmp_path / "cache"))
    d1 = _rodar(foto_danfe)
    n = len(chamadas)
    monkeypatch.setenv("LAUDO_VLM_SO_CACHE", "1")
    d2 = _rodar(foto_danfe)
    assert n == 4 and len(chamadas) == n and d1["documento"] == d2["documento"]


def test_conciliacao_pedida_pelo_llm_sobre_foto_le_o_documento_antes(tmp_path, pdf_gta):
    """O LLM só recebe conciliar_gta; numa foto/PDF ainda não lido, o condutor roda a leitura antes."""
    from laudo.agent import estado as est
    from laudo.agent.condutor import Condutor
    from laudo.contracts import REGISTRO, Evidencia, Operacao
    from laudo.tools import carregar_todas

    carregar_todas()
    LD.configurar_leitor(_leitor(_gta_impressa(_gta()), "gta"))
    caso = _caso()
    reg = {k: REGISTRO[k] for k in ("ler_documento_foto", "conciliar_nfe", "conciliar_gta", "registrar_ocorrencia",
                                    "emitir_rascunho")}
    cond = Condutor(None, repo=est.RepositorioFiscalizacoes(tmp_path / "fis"), registro=reg,
                    hoje=date.fromisoformat(caso["data_fiscalizacao"]))
    op = Operacao.model_validate({**caso["operacao"], "tomador_ref": caso["tomador"]["documento_sha256"]})
    fis = cond.abrir(op, data_referencia=date.fromisoformat(caso["data_fiscalizacao"]))
    ev = Evidencia(tipo="documento", caminho=str(pdf_gta), sha256="0" * 64, meta={"item_id": "bov1"})
    fis.evidencias.append(ev)
    fis.estado_fsm = "CHECAGEM"
    acao = cond.executar_acao(fis, "conciliar_gta", {"evidencia_id": ev.id}, origem="llm")
    assert acao.ok and acao.dados["status"] == "ok"
    assert [c.ferramenta for c in fis.checagens][-2:] == ["ler_documento_foto", "conciliar_gta"]
