"""RSA/X.509 em Python puro e XMLDSig da NF-e: digest válido vs. adulterado."""

from __future__ import annotations

import random
from datetime import UTC, datetime

import docs_apoio as A
from lxml import etree

from laudo.docs_fiscais import xmldsig
from laudo.docs_fiscais.cripto import (
    gerar_certificado,
    gerar_chave_rsa,
    ler_certificado,
    rsa_assinar,
    rsa_verificar,
)
from laudo.docs_fiscais.nfe import NS, ler_nfe


def test_rsa_pkcs1v15_ida_e_volta():
    chave = gerar_chave_rsa(random.Random(1), bits=1024)
    for alg in ("sha1", "sha256"):
        sig = rsa_assinar(chave, b"mensagem", alg)
        assert rsa_verificar(chave.n, chave.e, sig, b"mensagem", alg)
        assert not rsa_verificar(chave.n, chave.e, sig, b"mensagem alterada", alg)


def test_geracao_de_chave_e_deterministica():
    assert gerar_chave_rsa(random.Random("x"), 512) == gerar_chave_rsa(random.Random("x"), 512)


def test_certificado_sintetico_le_campos():
    rng = random.Random(2)
    ac, suj = gerar_chave_rsa(rng, 1024), gerar_chave_rsa(rng, 1024)
    der = gerar_certificado("VENDEDOR TESTE:99999999000191", suj, "AC TESTE", ac, 42,
                            datetime(2025, 1, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC))
    c = ler_certificado(der)
    assert c["sujeito"]["CN"] == "VENDEDOR TESTE:99999999000191"
    assert c["emissor"]["CN"] == "AC TESTE"
    assert (c["n"], c["e"], c["serial"]) == (suj.n, suj.e, 42)
    assert c["nao_antes"].year == 2025 and c["nao_depois"].year == 2027


def _verificar(xml: bytes) -> dict:
    raiz = etree.fromstring(xml)
    nfe = raiz.find(f"{{{NS}}}NFe") if raiz.tag.endswith("nfeProc") else raiz
    inf = nfe.find(f"{{{NS}}}infNFe")
    return xmldsig.verificar(raiz, inf, nfe.find(f"{{{xmldsig.NS_DS}}}Signature"))


def test_digest_e_assinatura_validos():
    r = _verificar(A.nfe_xml())
    assert r["presente"] and r["referencia_ok"] and r["transforms_ok"]
    assert r["digest_ok"] is True and r["rsa_ok"] is True
    assert r["digest_calculado"] == r["digest_informado"]


def test_digest_invalido_quando_xml_adulterado():
    def adulterar(inf):
        inf.find(f".//{{{NS}}}qCom").text = "50.0000"

    r = _verificar(A.nfe_xml(adulterar=adulterar))
    assert r["digest_ok"] is False
    assert r["rsa_ok"] is True  # o SignedInfo continua íntegro: só o conteúdo referenciado mudou
    assert any("DigestValue" in m for m in r["motivos"])


def test_signature_value_adulterado_falha_rsa():
    xml = A.nfe_xml()
    raiz = etree.fromstring(xml)
    sv = raiz.find(f".//{{{xmldsig.NS_DS}}}SignatureValue")
    sv.text = ("A" if sv.text[0] != "A" else "B") + sv.text[1:]
    r = _verificar(etree.tostring(raiz))
    assert r["digest_ok"] is True and r["rsa_ok"] is False


def test_referencia_para_outro_id():
    raiz = etree.fromstring(A.nfe_xml())
    raiz.find(f".//{{{xmldsig.NS_DS}}}Reference").set("URI", "#NFeOUTRA")
    assert _verificar(etree.tostring(raiz))["referencia_ok"] is False


def test_xml_reindentado_depois_da_assinatura_ainda_confere():
    """Visualizadores reindentam o XML; espaços entre tags não são conteúdo da NF-e."""
    raiz = etree.fromstring(A.nfe_xml())
    etree.indent(raiz, space="  ")
    bonito = etree.tostring(raiz, xml_declaration=True, encoding="UTF-8")
    assert _verificar(bonito)["digest_ok"] is False  # como veio, o digest não bate
    n = ler_nfe(bonito)
    assert n.assinatura["digest_ok"] is True and n.xml_reformatado
    assert n.status_integridade() == "ok"


def test_canonicalizacao_inclui_namespaces_herdados_sem_xmlns_vazio():
    xml = (b'<a xmlns="urn:x" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><b Id="1" z="2"><c>1</c></b>'
           b'</a>')
    b = etree.fromstring(xml)[0]
    c14n = xmldsig.canonicalizar(b)
    assert c14n.startswith(b'<b xmlns="urn:x" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" Id="1" z="2">')
    assert b'xmlns=""' not in c14n


def test_enveloped_remove_assinatura_descendente():
    xml = b'<r xmlns="urn:x"><d Id="d"><v>1</v><S xmlns="urn:s"><k/></S>\n</d></r>'
    d = etree.fromstring(xml)[0]
    sem = xmldsig.canonicalizar(d, remover=d[1])
    assert b"<S" not in sem and sem.endswith(b"<v>1</v>\n</d>")
