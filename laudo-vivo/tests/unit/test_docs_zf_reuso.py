"""NF-e grupo ZF (NT 2024.003) × GTA apresentada e índice de documentos de laudos selados (análogo ao
ZF04-20).

Tabelas de casos; cada linha cita a regra. Dados sintéticos (`docs_apoio`: CNPJ 99.999.999, CPF 000.000).
Leiaute conferido nos PDFs da NT 2024.003 v1.03 e v1.10: ZF01 agropecuario 0-1, ZF04 guiaTransito 1-1 (uma
guia por NF-e), ZF07 serieGuia C 1-9; tabela 4.1: ZF05-10 ativa para NCM 0102 em GO (01/10/2025; regras de
validação em produção desde 01/03/2026).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import docs_apoio as A
import pytest
import yaml
from lxml import etree

from laudo import privacidade
from laudo.agent.condutor import schema_para_llm
from laudo.contracts import REGISTRO, Checagem, Evidencia, Fiscalizacao, Operacao
from laudo.docs_fiscais import gta as G
from laudo.docs_fiscais import indice as I
from laudo.docs_fiscais import nfe as N
from laudo.docs_fiscais.gta import QuantidadeGTA
from laudo.tools import documentos as T

REPO = Path(__file__).resolve().parents[2]
CAMPO_ZF = "documento:gta:nfe_guia"
NS = "http://www.portalfiscal.inf.br/nfe"


def _guia(
    numero: str = "123456", uf: str = "GO", serie: str | None = None, tp: str | None = "1"
) -> dict[str, str]:
    g = {"UFGuia": uf, "nGuia": numero}
    if tp is not None:
        g["tpGuia"] = tp
    if serie is not None:
        g["serieGuia"] = serie
    return g


def _nfe(guia: dict[str, str] | None, **kw) -> N.NFe:
    return N.ler_nfe(A.nfe_xml(guia_transito=guia, **kw))


def _conciliar(gtas, notas):
    """`notas`: lista de guias (uma por NF-e; None = NF-e sem o grupo)."""
    nfes = [_nfe(g, n_nf=1234 + k, c_nf=f"{12345678 + k:08d}") for k, g in enumerate(notas)]
    return G.conciliar(gtas if isinstance(gtas, list) else [gtas], A.item(), A.contexto(), nfes)


def _gta_foto(**kw):
    g = A.gta(**kw)
    g.fonte = "foto"
    return g


def _duas_cargas():
    return [
        A.gta(quantidade=20, numero="100001", observacao="CARGA 1 DE 2"),
        A.gta(quantidade=20, numero="100002", observacao="CARGA 2 DE 2"),
    ]


# ============================================================ grupo ZF × GTA (NT 2024.003, ZF05-ZF08)
CASOS_ZF = [
    # (descrição com a regra, GTAs apresentadas, guia de cada NF-e, status sugerido | None = sem critério)
    (
        "NT-2024.003-ZF: NF-e sem o grupo agropecuário é neutra (validação facultativa por UF)",
        lambda: [A.gta()],
        [None],
        None,
    ),
    (
        "NT-2024.003-ZF: guia de outro tipo (PTV, tpGuia 5) não é GTA: neutra",
        lambda: [A.gta()],
        [_guia("999", tp="5")],
        None,
    ),
    (
        "NT-2024.003-ZF: TTA (tpGuia 2) é guia animal, mas não é e-GTA: neutra",
        lambda: [A.gta()],
        [_guia("123456", tp="2")],
        None,
    ),
    (
        "NT-2024.003-ZF: nGuia e UF conferem (serieGuia omitida) → verificado",
        lambda: [A.gta()],
        [_guia()],
        "verificado",
    ),
    ("NT-2024.003-ZF: tpGuia ausente conta como GTA", lambda: [A.gta()], [_guia(tp=None)], "verificado"),
    ("NT-2024.003-ZF: tpGuia '01' é GTA", lambda: [A.gta()], [_guia(tp="01")], "verificado"),
    (
        "NT-2024.003-ZF: nGuia com zeros à esquerda (N 1-9) confere com a GTA de 6 dígitos",
        lambda: [A.gta(numero="004321")],
        [_guia("000004321")],
        "verificado",
    ),
    (
        "NT-2024.003-ZF: serieGuia (C 1-9) só numérica × série com letra da e-GTA não é comparável",
        lambda: [A.gta(serie="A")],
        [_guia(serie="1")],
        "verificado",
    ),
    (
        "NT-2024.003-ZF: série alfabética igual → verificado",
        lambda: [A.gta(serie="AB")],
        [_guia(serie="AB")],
        "verificado",
    ),
    (
        "NT-2024.003-ZF: uma NF-e e duas cargas, a nota cita a GTA da carga 1 (ZF04 1-1) → verificado",
        _duas_cargas,
        [_guia("100001")],
        "verificado",
    ),
    (
        "NT-2024.003-ZF: uma NF-e e duas cargas, a nota cita a GTA da carga 2 → verificado",
        _duas_cargas,
        [_guia("100002")],
        "verificado",
    ),
    (
        "NT-2024.003-ZF: uma NF-e por carga, cada uma cita a sua GTA → verificado",
        _duas_cargas,
        [_guia("100001"), _guia("100002")],
        "verificado",
    ),
    (
        "NT-2024.003-ZF: duas NF-e citam a mesma GTA → verificado",
        _duas_cargas,
        [_guia("100001"), _guia("100001")],
        "verificado",
    ),
    (
        "NT-2024.003-ZF: uma nota com o grupo e outra sem → só a que traz o grupo é cobrada",
        _duas_cargas,
        [_guia("100001"), None],
        "verificado",
    ),
    (
        "NT-2024.003-ZF: mesmo número, série diferente → pendente (apresente a GTA citada), nunca divergente",
        lambda: [A.gta(serie="AB")],
        [_guia(serie="AC")],
        "pendente",
    ),
    (
        "NT-2024.003-ZF: mesmo número, UF diferente → pendente",
        lambda: [A.gta()],
        [_guia(uf="MT")],
        "pendente",
    ),
    (
        "NT-2024.003-ZF: nenhuma GTA apresentada é a citada (boi de papel ou GTA não enviada) → pendente",
        lambda: [A.gta()],
        [_guia("654321")],
        "pendente",
    ),
    (
        "NT-2024.003-ZF: uma NF-e por carga e a GTA citada pela 2ª nota não veio → pendente",
        lambda: [A.gta(quantidade=20, numero="100001")],
        [_guia("100001"), _guia("100002")],
        "pendente",
    ),
    (
        "NT-2024.003-ZF: foto da GTA com número ilegível não vira divergência → pendente",
        lambda: [_gta_foto(numero=None)],
        [_guia()],
        "pendente",
    ),
    (
        "NT-2024.003-ZF: foto da GTA com série lida diferente → pendente (confira o papel)",
        lambda: [_gta_foto(serie="B")],
        [_guia(serie="AB")],
        "pendente",
    ),
]


@pytest.mark.parametrize("regra,gtas,notas,esperado", CASOS_ZF, ids=[c[0] for c in CASOS_ZF])
def test_grupo_zf_cruzado_com_a_gta(regra, gtas, notas, esperado):
    r = _conciliar(gtas(), notas)
    if esperado is None:
        assert CAMPO_ZF not in r["campos"] and not any(c["id"] == "gta.nfe_guia" for c in r["criterios"])
        return
    campo = r["campos"][CAMPO_ZF]
    assert campo["status_campo_sugerido"] == esperado, campo["motivos"]
    assert campo["regra_id"] == "NT-2024.003-ZF"
    assert campo["status"] != "divergente"  # o grupo ZF sozinho nunca acusa


def test_gta_sem_citacao_fica_so_no_valor():
    """Uma NF-e cita no máximo uma guia: as outras cargas ficam em `gtas_sem_citacao`, sem mudar o status."""
    r = _conciliar(_duas_cargas(), [_guia("100001")])
    crit = next(c for c in r["criterios"] if c["id"] == "gta.nfe_guia")
    assert crit["valores"]["gtas_sem_citacao"] == ["GO-A-100002"] and crit["status"] == "ok"


def test_nfe_fora_do_leiaute_com_duas_guias_e_marcada():
    """XML com dois grupos de guia (o leiaute admite um): a comparação usa qualquer um e o valor avisa."""

    def segunda_guia(inf):
        gt = etree.SubElement(etree.SubElement(inf, f"{{{NS}}}agropecuario"), f"{{{NS}}}guiaTransito")
        for k, v in (("tpGuia", "1"), ("UFGuia", "GO"), ("nGuia", "100002")):
            etree.SubElement(gt, f"{{{NS}}}{k}").text = v

    nota = N.ler_nfe(A.nfe_xml(guia_transito=_guia("100001"), adulterar=segunda_guia))
    assert len(nota.guia_transito) == 2
    r = G.conciliar(_duas_cargas(), A.item(), A.contexto(), [nota])
    crit = next(c for c in r["criterios"] if c["id"] == "gta.nfe_guia")
    assert crit["status"] == "ok" and crit["valores"]["fora_do_leiaute"] == [nota.chave_mascarada]


def test_gerador_sintetico_aceita_uma_guia_so():
    with pytest.raises(TypeError, match="uma guia por NF-e"):
        A.nfe_xml(guia_transito=[_guia(), _guia("2")])
    assert A.nfe_xml(guia_transito=_guia()).count(b"<guiaTransito>") == 1


def test_ausencia_do_grupo_nao_muda_nenhum_outro_campo():
    """A ausência do grupo é neutra: o resultado é o mesmo da conciliação sem o critério ZF."""
    com = _conciliar([A.gta()], [_guia()])
    sem = _conciliar([A.gta()], [None])
    assert {k: v for k, v in com["campos"].items() if k != CAMPO_ZF} == sem["campos"]
    assert set(com["campos"]) - set(sem["campos"]) == {CAMPO_ZF}


def test_ferramenta_conciliar_gta_le_o_grupo_do_xml():
    xml = A.nfe_xml(guia_transito=_guia("654321")).decode()
    env = T.conciliar_gta(
        T.EntradaConciliarGTA(gtas=[A.gta().model_dump(mode="json")], nfe_xmls=[xml], **_ctx_args())
    )
    assert env.ok and env.data["status"] == "indeterminado"
    assert env.data["campos"][CAMPO_ZF]["status"] == "indeterminado"
    assert "GO-?-654321" in env.data["motivo"] and "apresente a GTA citada" in env.data["motivo"]


# ============================================================ índice de documentos de laudos selados
def _ctx_args(**kw):
    base = {
        "item": A.item().model_dump(mode="json"),
        "municipio_ibge": A.NOVA_CRIXAS[0],
        "municipio_nome": A.NOVA_CRIXAS[1],
        "data_contratacao": "2026-07-01",
        "data_fiscalizacao": "2026-09-20",
        "tomador_doc_sha256": A.TOMADOR_REF,
        "codigo_estabelecimento_destino": A.COD_ESTAB,
        "parametros": {"aceitar_homologacao": True},
    }
    base.update(kw)
    return base


def _conciliar_com_indice(indice: Path, operacao: str, item_id: str = "bov1", xml: bytes | None = None):
    """Concilia NF-e e GTA consultando o índice; devolve os campos de reuso e as saídas (para selar)."""
    args = _ctx_args(indice_documentos=str(indice), operacao_ref=operacao)
    args["item"] = dict(args["item"], id=item_id)
    x = (xml or A.nfe_xml()).decode()
    gtas = [A.gta().model_dump(mode="json")]
    env_g = T.conciliar_gta(T.EntradaConciliarGTA(gtas=gtas, nfe_xmls=[x], **args))
    env_n = T.conciliar_nfe(T.EntradaConciliarNFe(xmls=[x], **args))
    assert env_g.ok and env_n.ok
    return (
        env_g.data["campos"]["documento:gta:reuso"],
        env_n.data["campos"]["documento:nfe:reuso"],
        [("conciliar_gta", env_g.data), ("conciliar_nfe", env_n.data)],
    )


def _selar(indice: Path, saidas, operacao: str, fis: str, item_id: str = "bov1") -> int:
    docs = [d for nome, data in saidas for d in I.documentos_do_resultado(nome, data, item_id)]
    return I.IndiceDocumentos(indice).registrar_documentos(docs, operacao, fis)


# (descrição, laudos selados antes: (operação, item), consulta: (operação, item), status sugerido)
CASOS_REUSO = [
    ("índice vazio: primeira apresentação → verificado", [], ("op_a", "bov1"), "verificado"),
    (
        "refiscalização da mesma operação e item (MCR 2-7: nova visita) → verificado, não é reuso",
        [("op_a", "bov1")],
        ("op_a", "bov1"),
        "verificado",
    ),
    (
        "política de duplicata: mesma operação, outro item → pendente (não comprova dois itens)",
        [("op_a", "bov1")],
        ("op_a", "bov2"),
        "pendente",
    ),
    (
        "MCR 2-7-6-b e 7-d / ZF04-20: documento já em laudo selado de outra operação → divergente",
        [("op_a", "bov1")],
        ("op_b", "bov1"),
        "divergente",
    ),
    (
        "MCR 2-7-6-b / ZF04-20: outra operação prevalece sobre outro item da mesma",
        [("op_a", "bov2"), ("op_b", "bov2")],
        ("op_b", "bov1"),
        "divergente",
    ),
    (
        "refiscalização: NF-e e GTA aceitas em dois itens no laudo selado → verificado no 1º item",
        [("op_a", "bov1"), ("op_a", "bov2")],
        ("op_a", "bov1"),
        "verificado",
    ),
    (
        "refiscalização: NF-e e GTA aceitas em dois itens no laudo selado → verificado no 2º item",
        [("op_a", "bov1"), ("op_a", "bov2")],
        ("op_a", "bov2"),
        "verificado",
    ),
    (
        "documento de dois itens da op_a apresentado num 3º item que ele nunca comprovou → pendente",
        [("op_a", "bov1"), ("op_a", "bov2")],
        ("op_a", "bov3"),
        "pendente",
    ),
    (
        "documento de dois itens da op_a apresentado em outra operação → divergente",
        [("op_a", "bov1"), ("op_a", "bov2")],
        ("op_b", "bov1"),
        "divergente",
    ),
]


@pytest.mark.parametrize("regra,selados,consulta,esperado", CASOS_REUSO, ids=[c[0] for c in CASOS_REUSO])
def test_indice_de_documentos_reutilizados(tmp_path, regra, selados, consulta, esperado):
    indice = tmp_path / "documentos.jsonl"
    for k, (op, item_id) in enumerate(selados):
        *_, saidas = _conciliar_com_indice(indice, op, item_id)
        assert _selar(indice, saidas, op, f"fis_{k}", item_id) == 2
    c_gta, c_nfe, _ = _conciliar_com_indice(indice, *consulta)
    for campo in (c_gta, c_nfe):
        assert campo["status_campo_sugerido"] == esperado, campo["motivos"]
        assert campo["regra_id"] == "MCR-2-7-item6"


def test_refiscalizacao_de_documento_de_dois_itens_nao_vira_pendencia(tmp_path):
    """Revisão da onda 3: a guia que o laudo selado aceitou em dois itens (bov1 e bov2) não acusa "um
    documento não comprova dois itens" na refiscalização da mesma operação (o fiscal que assinou já decidiu);
    num item que ela nunca comprovou, acusa; em outra operação, diverge."""
    indice = I.IndiceDocumentos(tmp_path / "documentos.jsonl")
    h = I.hash_gta("GO", "A", "123456")
    doc = [("GO-A-123456", h)]
    assert indice.registrar_documentos([("gta", h, "bov1"), ("gta", h, "bov2")], "SINT-A", "fis_1") == 2
    for item_id in ("bov1", "bov2"):
        c = I.conferir_reuso(indice, "gta", doc, "SINT-A", item_id)
        assert c.status == "ok" and c.valores["refiscalizacao"] == 1, c.motivo
        assert "refiscalização" in c.motivo and "dois itens" not in c.motivo
    c3 = I.conferir_reuso(indice, "gta", doc, "SINT-A", "bov3")
    assert c3.status == "indeterminado" and "bov1, bov2" in c3.motivo
    assert I.conferir_reuso(indice, "gta", doc, "SINT-B", "bov1").status == "divergente"
    vazio = I.conferir_reuso(I.IndiceDocumentos(tmp_path / "outro.jsonl"), "gta", doc, "SINT-A", "bov1")
    assert vazio.status == "ok" and "refiscalizacao" not in vazio.valores  # índice vazio: saída de antes


def test_conciliacao_so_le_o_indice(tmp_path):
    """A conciliação roda a cada envio (estados intermediários, documento trocado): nunca grava. O servidor
    MCP somente leitura expõe conciliar_nfe/conciliar_gta sem efeito colateral."""
    indice = tmp_path / "sub" / "documentos.jsonl"
    _conciliar_com_indice(indice, "op_a")
    assert not indice.exists() and not indice.parent.exists()
    *_, saidas = _conciliar_com_indice(indice, "op_a")
    _selar(indice, saidas, "op_a", "fis_1")
    antes = indice.read_bytes()
    for op in ("op_a", "op_b", "op_c"):
        _conciliar_com_indice(indice, op)
    assert indice.read_bytes() == antes


def test_documento_enviado_por_engano_nao_fica_no_indice(tmp_path):
    """Só a selagem registra: a GTA conciliada e depois trocada (nunca selada) não acusa outra operação."""
    indice = tmp_path / "documentos.jsonl"
    _conciliar_com_indice(indice, "op_a")  # GTA enviada na op_a, laudo não selado com ela
    c_gta, c_nfe, _ = _conciliar_com_indice(indice, "op_b")
    assert c_gta["status"] == "ok" and c_nfe["status"] == "ok"


def test_indice_guarda_so_hmac_nunca_o_valor(tmp_path):
    indice = tmp_path / "documentos.jsonl"
    xml = A.nfe_xml()
    *_, saidas = _conciliar_com_indice(indice, "SINT-2026-000777", xml=xml)
    assert _selar(indice, saidas, "SINT-2026-000777", "fis_a") == 2
    chave = N.ler_nfe(xml).chave
    bruto = indice.read_text(encoding="utf-8")
    assert chave not in bruto and chave[6:20] not in bruto  # nem a chave nem o CNPJ/CPF do emitente
    assert "123456" not in bruto and "GO-A" not in bruto  # nem o número da GTA
    assert "SINT-2026-000777" not in bruto  # nem a referência da operação
    linhas = [json.loads(x) for x in bruto.splitlines()]
    assert {e["tipo"] for e in linhas} == {"gta", "nfe"} and len(linhas) == 2
    assert all(len(e["hash"]) == 64 and e["instalacao"] == privacidade.id_instalacao() for e in linhas)
    assert {e["operacao"] for e in linhas} == {I.hash_operacao("SINT-2026-000777")}
    assert {e["hash"] for e in linhas if e["tipo"] == "nfe"} == {privacidade.hash_chave(chave)}
    assert _selar(indice, saidas, "SINT-2026-000777", "fis_b") == 0  # selar de novo não duplica
    assert len(indice.read_text(encoding="utf-8").splitlines()) == 2


def test_registro_a_partir_do_estado_protegido(tmp_path):
    """A selagem lê as checagens do estado (chave mascarada + `chave_hash`): os hashes são os mesmos."""
    *_, saidas = _conciliar_com_indice(tmp_path / "x.jsonl", "op_a")
    claro = [d for nome, data in saidas for d in I.documentos_do_resultado(nome, data, "bov1")]
    estado = [d for nome, data in saidas
              for d in I.documentos_do_resultado(nome, privacidade.proteger_resultado(data), "bov1")]
    assert sorted(claro) == sorted(estado) and len(claro) == 2
    chks = [Checagem(id=f"chk_{k}", ferramenta=nome, entrada_hash="t", status="ok", item_id="bov1",
                     evidencias=["ev_doc"], resultado=privacidade.proteger_resultado(data))
            for k, (nome, data) in enumerate(saidas)]
    outra_gta = {"gtas": [{"uf_emissao": "GO", "serie": "Z", "numero": "999999"}], "substitui": []}
    chks.append(Checagem(id="chk_9", ferramenta="conciliar_gta", entrada_hash="t", status="ok",
                         item_id="bov1", evidencias=["ev_doc"], resultado=outra_gta))
    chks[1].resultado["substitui"] = ["chk_0"]  # a GTA anterior foi substituída pela reconciliação
    op = Operacao(ref_bacen="SINT-2026-000778", tomador_ref="anon-teste", itens=[A.item()], fonte="sintetico")
    ev = Evidencia(id="ev_doc", tipo="gta", sha256="0" * 64)
    fis = Fiscalizacao(id="fis_sel", operacao=op, checagens=chks, evidencias=[ev])
    indice = tmp_path / "documentos.jsonl"
    assert I.registrar_fiscalizacao(indice, fis) == 2  # NF-e + GTA Z (a GTA de chk_0 foi substituída)
    assert I.registrar_fiscalizacao(indice, fis) == 0


# (descrição, mudança na checagem final da GTA Z, a GTA Z entra no índice?)
CASOS_SELAVEIS = [
    ("conciliação ok, com evidência e item da operação → entra", {}, True),
    ("divergente (ex.: GTA de outro lote enviada por engano) → não entra", {"status": "divergente"}, False),
    ("indeterminado (outro item, leitura não validada) → não entra", {"status": "indeterminado"}, False),
    ("L24: checagem sem evidência da fiscalização → não entra", {"evidencias": ["ev_inexistente"]}, False),
    ("item que não é da operação → não entra", {"item_id": "bov9"}, False),
]


@pytest.mark.parametrize("regra,mudanca,entra", CASOS_SELAVEIS, ids=[c[0] for c in CASOS_SELAVEIS])
def test_documentos_selaveis_so_o_que_comprovou_o_item(regra, mudanca, entra):
    gta_z = {"gtas": [{"uf_emissao": "GO", "serie": "Z", "numero": "999999"}]}
    chk = Checagem(id="chk_z", ferramenta="conciliar_gta", entrada_hash="t", status="ok", item_id="bov1",
                   evidencias=["ev_doc"], resultado=gta_z).model_copy(update=mudanca)
    op = Operacao(ref_bacen="SINT-2026-000779", tomador_ref="anon-teste", itens=[A.item()], fonte="sintetico")
    fis = Fiscalizacao(id="fis_z", operacao=op, checagens=[chk],
                       evidencias=[Evidencia(id="ev_doc", tipo="gta", sha256="0" * 64)])
    docs = I.documentos_selaveis(fis)
    assert (docs == [("gta", I.hash_gta("GO", "Z", "999999"), chk.item_id)]) is entra, regra
    assert entra or docs == []


def test_hash_da_gta_usa_o_sal_e_normaliza_o_numero():
    assert I.hash_gta("go", "a", "000123456") == I.hash_gta("GO", "A", "123456")
    assert I.hash_gta("GO", "A", "123456") != I.hash_gta("GO", "B", "123456")
    assert I.hash_gta("GO", None, "123456") is None and I.hash_gta(None, "A", "1") is None
    publico = privacidade.salgar(I.DOMINIO_GTA, "GO-A-123456", sal_explicito="outra-instalacao")
    assert I.hash_gta("GO", "A", "123456") != publico  # instalações diferentes não se comparam
    assert I.hash_nfe("1" * 44) is None  # DV inválido não entra no índice
    assert I.hash_operacao(" ") is None and I.hash_operacao("A") != I.hash_operacao("B")


def test_indice_desligado_nao_acrescenta_campo():
    """Sem `indice_documentos` + `operacao_ref` (servidor MCP, chamada direta; o executor do produto liga os
    dois a partir do diretório de dados) a saída é a de antes."""
    env = T.conciliar_gta(
        T.EntradaConciliarGTA(
            gtas=[A.gta().model_dump(mode="json")], nfe_xmls=[A.nfe_xml().decode()], **_ctx_args()
        )
    )
    assert "documento:gta:reuso" not in env.data["campos"]
    env = T.conciliar_nfe(
        T.EntradaConciliarNFe(xmls=[A.nfe_xml().decode()], **_ctx_args(indice_documentos="x.jsonl"))
    )
    assert "documento:nfe:reuso" not in env.data["campos"]


def test_indice_ilegivel_vira_pendencia_nunca_excecao(tmp_path):
    pasta = tmp_path / "pasta"
    pasta.mkdir()
    env = T.conciliar_nfe(
        T.EntradaConciliarNFe(
            xmls=[A.nfe_xml().decode()], **_ctx_args(indice_documentos=str(pasta), operacao_ref="op")
        )
    )
    assert env.ok and env.data["campos"]["documento:nfe:reuso"]["status"] == "indeterminado"


def test_campos_novos_ficam_fora_do_esquema_que_o_llm_ve():
    """O replay casa pelo hash do esquema das ferramentas: os campos do índice ficam fora do esquema."""
    from laudo.tools import carregar_todas

    carregar_todas()
    for nome in ("conciliar_nfe", "conciliar_gta"):
        props = schema_para_llm(REGISTRO[nome])["function"]["parameters"]["properties"]
        assert set(props) == {"evidencia_id", "item_id"}, props


def test_mcp_somente_leitura_continua_sem_ferramenta_que_grava(tmp_path):
    """No MCP somente leitura, conciliar_* seguem anunciadas como readOnlyHint: e de fato só leem."""
    from laudo.mcp_server import MUTAVEIS, ServidorMCP

    srv = ServidorMCP(somente_leitura=True)
    assert {"conciliar_nfe", "conciliar_gta"} <= set(srv.ferramentas)
    assert not {"conciliar_nfe", "conciliar_gta"} & MUTAVEIS
    alvo = tmp_path / "qualquer" / "arquivo.jsonl"
    _conciliar_com_indice(alvo, "op_a")
    assert not alvo.exists()


# ============================================================ golden: invariantes sem rótulo (60 casos)
def _golden() -> list[tuple[str, Path, dict, str]]:
    """(id, diretório, entradas das ferramentas, ref. Bacen). Os testes abaixo não leem rótulos (`esperado`):
    são invariantes de "nada muda" e podem rodar nos 60 casos sem tocar a avaliação do teste congelado."""
    dcasos = REPO / "eval" / "golden" / "casos"
    split = yaml.safe_load((dcasos / "SPLIT.yaml").read_text(encoding="utf-8"))
    out = []
    for c in split["casos"]:
        d = dcasos / c["id"]
        caso = yaml.safe_load((d / "caso.yaml").read_text(encoding="utf-8"))
        out.append((c["id"], d, caso["entradas_ferramentas"], caso["operacao"]["ref_bacen"]))
    return out


def _resolver(d: Path, ent: dict) -> dict:
    e = dict(ent)
    for k in ("caminhos", "nfe_caminhos"):
        if k in e:
            e[k] = [str(d / x) for x in e[k]]
    return e


def _com_grupo_zf(xml: bytes, g: dict) -> str:
    """NF-e com o grupo ZF citando a GTA `g` (a assinatura deixa de conferir; conciliar_gta não a usa)."""
    raiz = etree.fromstring(xml)
    inf = raiz.find(f".//{{{NS}}}infNFe")
    gt = etree.SubElement(etree.SubElement(inf, f"{{{NS}}}agropecuario"), f"{{{NS}}}guiaTransito")
    for k, v in (("tpGuia", "1"), ("UFGuia", g.get("uf_emissao")), ("serieGuia", g.get("serie")),
                 ("nGuia", g.get("numero"))):
        if v:
            etree.SubElement(gt, f"{{{NS}}}{k}").text = str(v)
    return etree.tostring(raiz, xml_declaration=True, encoding="UTF-8").decode("utf-8")


@pytest.mark.parametrize("modo", ["so_a_primeira_gta", "uma_gta_por_nota"])
def test_golden_com_grupo_zf_realista_nao_muda_status(modo):
    """NF-e de GO de gado traz o grupo ZF com UMA guia (ZF05-10, tabela 4.1). Nos 60 casos do
    golden, cada nota passa a citar uma das GTAs apresentadas (a 1ª, ou a k-ésima para a k-ésima nota): nenhum
    campo muda e `documento:gta:nfe_guia` fica ok. Inclui GLD-0019, 0023, 0055 e 0059 (duas notas, duas GTAs),
    que a regra anterior ("GTA não citada → pendente") bloqueava."""
    com_zf = 0
    for cid, d, ent, _ in _golden():
        base = _resolver(d, ent["conciliar_gta"])
        if not base.get("nfe_caminhos"):
            continue
        gtas = [json.loads(Path(p).read_text(encoding="utf-8")) for p in base["caminhos"]]
        sem = T.conciliar_gta(T.EntradaConciliarGTA.model_validate(base)).data
        xmls = []
        for k, p in enumerate(base["nfe_caminhos"]):
            g = gtas[0] if modo == "so_a_primeira_gta" else gtas[k % len(gtas)]
            xmls.append(_com_grupo_zf(Path(p).read_bytes(), g))
        com = T.conciliar_gta(T.EntradaConciliarGTA.model_validate(
            {**base, "nfe_caminhos": [], "nfe_xmls": xmls})).data
        assert {k: v["status"] for k, v in com["campos"].items() if k != CAMPO_ZF} == {
            k: v["status"] for k, v in sem["campos"].items()
        }, cid
        assert com["campos"][CAMPO_ZF]["status"] == "ok", (cid, com["campos"][CAMPO_ZF]["motivos"])
        assert com["status"] == sem["status"], cid
        com_zf += 1
    assert com_zf >= 40


def test_golden_sem_falso_reuso_com_indice_compartilhado(tmp_path):
    """Os 60 casos como 60 operações seladas em sequência num índice só: nenhum documento colide (zero falso
    reuso) e nenhum campo muda de status."""
    indice = tmp_path / "documentos.jsonl"
    t0 = time.perf_counter()
    mudou, reuso, selados = [], [], 0
    for cid, d, ent, ref in _golden():
        saidas = []
        for nome, modelo, ferr in (
            ("conciliar_nfe", T.EntradaConciliarNFe, T.conciliar_nfe),
            ("conciliar_gta", T.EntradaConciliarGTA, T.conciliar_gta),
        ):
            base = _resolver(d, ent[nome])
            sem = ferr(modelo.model_validate(base)).data
            ligado = {**base, "indice_documentos": str(indice), "operacao_ref": ref}
            com = ferr(modelo.model_validate(ligado)).data
            novos = {k: v for k, v in com["campos"].items() if k not in sem["campos"]}
            # nota com DV inválido (defeito plantado) não tem identificador: não entra no índice
            assert set(novos) <= {f"documento:{nome.split('_')[1]}:reuso"} and CAMPO_ZF not in com["campos"]
            if any(v["status"] != "ok" for v in novos.values()):
                reuso.append((cid, nome))
            if {k: v["status"] for k, v in com["campos"].items() if k in sem["campos"]} != {
                k: v["status"] for k, v in sem["campos"].items()
            } or com["status"] != sem["status"]:
                mudou.append((cid, nome))
            saidas.append((nome, com))
        docs = [x for nome, data in saidas
                for x in I.documentos_do_resultado(nome, data, ent[nome]["item"]["id"])]
        selados += I.IndiceDocumentos(indice).registrar_documentos(docs, ref, f"fis:{cid}")
    assert reuso == [] and mudou == []
    assert selados > 100  # NF-e e GTAs dos 60 casos (as notas com DV inválido ficam de fora)
    assert time.perf_counter() - t0 < 120


def test_quantidade_por_sexo_continua_lida_com_o_grupo():
    """O grupo ZF não interfere nas outras regras da GTA (ex.: sexo do item)."""
    g = A.gta(quantidades=[QuantidadeGTA(sexo="M", faixa_etaria="13-24", quantidade=40)])
    r = _conciliar([g], [_guia()])
    assert r["campos"][CAMPO_ZF]["status_campo_sugerido"] == "verificado"
    assert A.status(r, ":gta_especie") == "divergente"  # item de novilhas, GTA só de machos
