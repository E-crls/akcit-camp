"""XMLDSig enveloped (como na NF-e): canonicalização, DigestValue e assinatura RSA.

O que é verificável offline (e é verificado aqui):
- presença e estrutura da `Signature`; a `Reference` aponta para o `Id` do elemento assinado;
- transforms esperados (enveloped-signature + C14N) e algoritmos conhecidos;
- `DigestValue` recalculado sobre o elemento referenciado canonicalizado (C14N 1.0 inclusivo);
- `SignatureValue` confere com a chave pública do certificado embutido (`X509Certificate`).

O que NÃO é verificável offline (fica como alerta, nunca como divergência):
- cadeia até uma AC raiz ICP-Brasil, revogação (LCR/OCSP) e política de certificação.

Nota técnica: `lxml.etree.tostring(subelemento, method="c14n")` emite `xmlns=""` espúrio nos filhos
de um subelemento com namespace padrão herdado. Por isso o subconjunto é copiado para um documento
próprio, declarando no ápice todos os namespaces em escopo, que é o resultado do C14N inclusivo.
"""

from __future__ import annotations

import base64
import binascii
import copy
import hashlib
from typing import Any

from lxml import etree

from laudo.docs_fiscais.cripto import ChaveRSA, ErroDER, ler_certificado, rsa_assinar, rsa_verificar

NS_DS = "http://www.w3.org/2000/09/xmldsig#"
C14N = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
C14N_COMENTARIOS = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315#WithComments"
C14N_EXCLUSIVO = "http://www.w3.org/2001/10/xml-exc-c14n#"
ENVELOPED = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"
DIGESTS = {"http://www.w3.org/2000/09/xmldsig#sha1": "sha1", "http://www.w3.org/2001/04/xmlenc#sha256": "sha256"}
ASSINATURAS = {"http://www.w3.org/2000/09/xmldsig#rsa-sha1": "sha1",
               "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256": "sha256"}
_C14N_SUPORTADOS = {C14N, C14N_COMENTARIOS, C14N_EXCLUSIVO}


def mascarar_cn(cn: str | None) -> str | None:
    """CN de certificado ICP-Brasil ("NOME:CPF" ou "RAZÃO SOCIAL:CNPJ") com o documento mascarado e, se for
    pessoa física, o nome em iniciais."""
    if not cn:
        return cn
    from laudo.docs_fiscais.comum import mascarar_documento, mascarar_nome, so_alnum, tipo_documento

    nome, sep, doc = cn.rpartition(":")
    t = tipo_documento(so_alnum(doc)) if sep else None
    if t is None:
        return cn
    return f"{mascarar_nome(nome, t)}:{mascarar_documento(doc)}"


def _q(nome: str) -> str:
    return f"{{{NS_DS}}}{nome}"


def canonicalizar(el: etree._Element, metodo: str = C14N, remover: etree._Element | None = None) -> bytes:
    """C14N 1.0 do subconjunto `el` (com seus descendentes), opcionalmente sem o nó `remover`.

    `remover` (transform enveloped-signature) precisa ser descendente de `el`; o texto que o segue
    (tail) é preservado, como no modelo de dados XPath.
    """
    novo = etree.Element(el.tag, attrib=dict(el.attrib), nsmap=el.nsmap)
    novo.text = el.text
    for filho in el:
        c = copy.deepcopy(filho)
        c.tail = filho.tail
        novo.append(c)
    caminho = _caminho(el, remover) if remover is not None else None
    if caminho:
        no = novo
        for i in caminho:
            no = no[i]
        _remover_preservando_tail(no)
    if metodo == C14N_EXCLUSIVO:
        return etree.tostring(novo, method="c14n", exclusive=True)
    return etree.tostring(novo, method="c14n", with_comments=metodo == C14N_COMENTARIOS)


def _caminho(raiz: etree._Element, no: etree._Element) -> list[int] | None:
    """Índices de filhos de `raiz` até `no` (None se `no` não descende de `raiz`)."""
    idx: list[int] = []
    atual = no
    while atual is not None and atual is not raiz:
        pai = atual.getparent()
        if pai is None:
            return None
        idx.append(pai.index(atual))
        atual = pai
    return list(reversed(idx)) if atual is raiz else None


def _remover_preservando_tail(no: etree._Element) -> None:
    pai = no.getparent()
    if no.tail:
        anterior = no.getprevious()
        if anterior is not None:
            anterior.tail = (anterior.tail or "") + no.tail
        else:
            pai.text = (pai.text or "") + no.tail
    pai.remove(no)


def _b64(texto: str | None) -> bytes | None:
    if not texto:
        return None
    try:
        return base64.b64decode("".join(texto.split()), validate=True)
    except (binascii.Error, ValueError):
        return None


def verificar(raiz: etree._Element, alvo: etree._Element, assinatura: etree._Element | None) -> dict[str, Any]:
    """Verifica a assinatura enveloped de `alvo` (ex.: infNFe). Não levanta exceção.

    Devolve dicionário com `presente`, `referencia_ok`, `transforms_ok`, `digest_ok`, `rsa_ok`
    (True/False/None quando não dá para avaliar), `certificado` e `motivos`.
    """
    r: dict[str, Any] = {"presente": assinatura is not None, "referencia_ok": None, "transforms_ok": None,
                         "digest_ok": None, "rsa_ok": None, "digest_informado": None, "digest_calculado": None,
                         "algoritmo_digest": None, "algoritmo_assinatura": None, "certificado": None,
                         "motivos": []}
    if assinatura is None:
        r["motivos"].append("XML sem elemento Signature")
        return r
    si = assinatura.find(_q("SignedInfo"))
    ref = si.find(_q("Reference")) if si is not None else None
    if si is None or ref is None:
        r["motivos"].append("Signature sem SignedInfo/Reference")
        r["referencia_ok"] = False
        return r

    # Referência
    uri = ref.get("URI") or ""
    id_alvo = alvo.get("Id") or ""
    r["referencia_uri"] = uri
    r["referencia_ok"] = bool(id_alvo) and uri == f"#{id_alvo}"
    if not r["referencia_ok"]:
        r["motivos"].append(f"Reference URI '{uri}' não aponta para o Id do elemento assinado '{id_alvo}'")

    # Transforms e algoritmos
    transforms = [t.get("Algorithm") for t in ref.findall(f"{_q('Transforms')}/{_q('Transform')}")]
    r["transforms"] = transforms
    desconhecidos = [t for t in transforms if t != ENVELOPED and t not in _C14N_SUPORTADOS]
    r["transforms_ok"] = not desconhecidos
    if desconhecidos:
        r["motivos"].append(f"transform não suportado: {desconhecidos}")
    metodo_ref = next((t for t in transforms if t in _C14N_SUPORTADOS), C14N)
    dm = ref.find(_q("DigestMethod"))
    alg_dig = DIGESTS.get(dm.get("Algorithm") if dm is not None else "")
    r["algoritmo_digest"] = alg_dig
    cm = si.find(_q("CanonicalizationMethod"))
    metodo_si = cm.get("Algorithm") if cm is not None else C14N
    sm = si.find(_q("SignatureMethod"))
    alg_sig = ASSINATURAS.get(sm.get("Algorithm") if sm is not None else "")
    r["algoritmo_assinatura"] = alg_sig

    # Digest do elemento referenciado
    dv = ref.find(_q("DigestValue"))
    r["digest_informado"] = dv.text.strip() if dv is not None and dv.text else None
    if alg_dig is None:
        r["motivos"].append("algoritmo de digest desconhecido")
    elif r["transforms_ok"]:
        remover = assinatura if ENVELOPED in transforms else None  # só tem efeito se for descendente
        calc = base64.b64encode(hashlib.new(alg_dig, canonicalizar(alvo, metodo_ref, remover)).digest()).decode()
        r["digest_calculado"] = calc
        r["digest_ok"] = calc == r["digest_informado"]
        if not r["digest_ok"]:
            r["motivos"].append("DigestValue não confere: o conteúdo assinado foi alterado depois da assinatura")

    # Certificado e SignatureValue
    cert_txt = assinatura.findtext(f"{_q('KeyInfo')}/{_q('X509Data')}/{_q('X509Certificate')}")
    cert_der = _b64(cert_txt)
    sig = _b64(assinatura.findtext(_q("SignatureValue")))
    cert = None
    if cert_der:
        try:
            cert = ler_certificado(cert_der)
        except (ErroDER, ValueError, IndexError) as e:
            r["motivos"].append(f"certificado embutido ilegível: {e}")
    if cert is not None:
        r["certificado"] = {
            # o CN do e-CPF/e-CNPJ é "NOME:DOCUMENTO": vai para a trilha mascarado (POL-08); a conferência com o
            # emitente usa o certificado em memória (`_cert`)
            "sujeito_cn": mascarar_cn(cert["sujeito"].get("CN")), "emissor_cn": cert["emissor"].get("CN"),
            "nao_antes": cert["nao_antes"].isoformat(), "nao_depois": cert["nao_depois"].isoformat(),
            "bits": cert["n"].bit_length(), "serial": str(cert["serial"]),
        }
        if sig is None or alg_sig is None or metodo_si not in _C14N_SUPORTADOS:
            r["motivos"].append("SignatureValue ausente ou algoritmo de assinatura não suportado")
        else:
            r["rsa_ok"] = rsa_verificar(cert["n"], cert["e"], sig, canonicalizar(si, metodo_si), alg_sig)
            if not r["rsa_ok"]:
                r["motivos"].append("SignatureValue não confere com a chave pública do certificado embutido")
        r["_cert"] = cert
    elif not cert_der:
        r["motivos"].append("assinatura sem X509Certificate: não dá para conferir o SignatureValue")
    return r


def assinar(pai: etree._Element, alvo: etree._Element, chave: ChaveRSA, cert_der: bytes,
            alg_digest: str = "sha1") -> etree._Element:
    """Assina `alvo` (enveloped, C14N, RSA-SHA1 como no MOC da NF-e) e anexa a Signature em `pai`."""
    uri_dig = {v: k for k, v in DIGESTS.items()}[alg_digest]
    uri_sig = {v: k for k, v in ASSINATURAS.items()}[alg_digest]
    digest = base64.b64encode(hashlib.new(alg_digest, canonicalizar(alvo, C14N)).digest()).decode()
    sig = etree.SubElement(pai, _q("Signature"), nsmap={None: NS_DS})
    si = etree.SubElement(sig, _q("SignedInfo"))
    etree.SubElement(si, _q("CanonicalizationMethod"), Algorithm=C14N)
    etree.SubElement(si, _q("SignatureMethod"), Algorithm=uri_sig)
    ref = etree.SubElement(si, _q("Reference"), URI="#" + alvo.get("Id"))
    tr = etree.SubElement(ref, _q("Transforms"))
    etree.SubElement(tr, _q("Transform"), Algorithm=ENVELOPED)
    etree.SubElement(tr, _q("Transform"), Algorithm=C14N)
    etree.SubElement(ref, _q("DigestMethod"), Algorithm=uri_dig)
    etree.SubElement(ref, _q("DigestValue")).text = digest
    valor = rsa_assinar(chave, canonicalizar(si, C14N), alg_digest)
    etree.SubElement(sig, _q("SignatureValue")).text = base64.b64encode(valor).decode()
    ki = etree.SubElement(sig, _q("KeyInfo"))
    x5 = etree.SubElement(ki, _q("X509Data"))
    etree.SubElement(x5, _q("X509Certificate")).text = base64.b64encode(cert_der).decode()
    return sig
