"""Construtores de documentos sintéticos (golden set, testes e demo).

Marcadores de dado sintético, para que nada se passe por documento real:
- NF-e em ambiente de homologação (tpAmb=2), destinatário com o texto exigido pelo MOC para
  homologação e `infCpl` com aviso de documento sintético;
- CNPJs com raiz 99.999.999 e CPFs com prefixo 000.000 (DV calculado); nomes "... TESTE NN";
- certificados emitidos por "AC TESTE SINTETICA LAUDO VIVO" com O="DOCUMENTO SINTETICO - SEM VALOR LEGAL".
"""

from __future__ import annotations

import base64
import hashlib
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from lxml import etree

from laudo.docs_fiscais import xmldsig
from laudo.docs_fiscais.comum import dv_cnpj, dv_cpf, montar_chave, so_alnum
from laudo.docs_fiscais.cripto import ChaveRSA, gerar_certificado, gerar_chave_rsa
from laudo.docs_fiscais.nfe import NS

MARCA_SINTETICO = "DOCUMENTO SINTETICO GERADO PARA TESTES (LAUDO VIVO) - SEM VALOR FISCAL"
NOME_HOMOLOGACAO = "NF-E EMITIDA EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL"
AC_TESTE = "AC TESTE SINTETICA LAUDO VIVO"
CODIGO_UF = {"GO": "52", "MT": "51", "MS": "50", "MG": "31", "SP": "35", "TO": "17", "BA": "29", "DF": "53",
             "PA": "15", "RO": "11"}


def cnpj_sintetico(ordem: int) -> str:
    """CNPJ com raiz 99.999.999 (claramente fictícia) e DV calculado."""
    base = f"99999999{ordem:04d}"
    return base + dv_cnpj(base)


def cpf_sintetico(n: int) -> str:
    """CPF com prefixo 000.000 e DV calculado (faixa claramente fictícia)."""
    base = f"000000{n:03d}"
    return base + dv_cpf(base)


_UNIDADES = ["", "UM", "DOIS", "TRES", "QUATRO", "CINCO", "SEIS", "SETE", "OITO", "NOVE", "DEZ", "ONZE", "DOZE",
             "TREZE", "QUATORZE", "QUINZE", "DEZESSEIS", "DEZESSETE", "DEZOITO", "DEZENOVE"]
_DEZENAS = ["", "", "VINTE", "TRINTA", "QUARENTA", "CINQUENTA", "SESSENTA", "SETENTA", "OITENTA", "NOVENTA"]
_CENTENAS = ["", "CENTO", "DUZENTOS", "TREZENTOS", "QUATROCENTOS", "QUINHENTOS", "SEISCENTOS", "SETECENTOS",
             "OITOCENTOS", "NOVECENTOS"]


def por_extenso(n: int) -> str:
    """Número inteiro de 0 a 999 por extenso (sem acento, como em formulário)."""
    if n == 0:
        return "ZERO"
    if n == 100:
        return "CEM"
    partes = []
    c, resto = divmod(n, 100)
    if c:
        partes.append(_CENTENAS[c])
    if resto >= 20:
        d, u = divmod(resto, 10)
        partes.append(_DEZENAS[d] + (f" E {_UNIDADES[u]}" if u else ""))
    elif resto:
        partes.append(_UNIDADES[resto])
    return " E ".join(partes)


# ---------------------------------------------------------------------------
# Chaves e certificados sintéticos
# ---------------------------------------------------------------------------


class PoolChaves:
    """Chaves RSA determinísticas por semente: uma 'AC TESTE' e N chaves de emitente."""

    def __init__(self, semente: int | str, n_emitentes: int = 4, bits: int = 2048):
        rng = random.Random(f"laudo-vivo/chaves/{semente}")
        self.ac = gerar_chave_rsa(rng, bits)
        self.emitentes = [gerar_chave_rsa(rng, bits) for _ in range(n_emitentes)]
        self._cache: dict[str, tuple[ChaveRSA, bytes]] = {}

    def para(self, documento: str, nome: str) -> tuple[ChaveRSA, bytes]:
        doc = so_alnum(documento)
        if doc not in self._cache:
            idx = int(hashlib.sha256(doc.encode()).hexdigest(), 16)
            chave = self.emitentes[idx % len(self.emitentes)]
            cert = gerar_certificado(f"{nome}:{doc}", chave, AC_TESTE, self.ac, serial=idx % (1 << 63),
                                     inicio=datetime(2025, 1, 1, tzinfo=UTC),
                                     fim=datetime(2027, 12, 31, tzinfo=UTC))
            self._cache[doc] = (chave, cert)
        return self._cache[doc]


# ---------------------------------------------------------------------------
# NF-e sintética
# ---------------------------------------------------------------------------


@dataclass
class ParteSintetica:
    documento: str
    nome: str
    uf: str
    c_mun: str
    x_mun: str
    ie: str | None = None
    logradouro: str = "RODOVIA TESTE KM 0"
    cep: str = "75000000"


@dataclass
class ItemSintetico:
    c_prod: str
    x_prod: str
    ncm: str
    cfop: str
    u_com: str
    q_com: float
    v_un_com: float
    u_trib: str | None = None
    q_trib: float | None = None

    @property
    def v_prod(self) -> float:
        return round(self.q_com * self.v_un_com, 2)


@dataclass
class NFeSintetica:
    emitente: ParteSintetica
    destinatario: ParteSintetica
    itens: list[ItemSintetico]
    dh_emi: datetime
    serie: int
    n_nf: int
    c_nf: str
    nat_op: str = "VENDA DE PRODUCAO DO ESTABELECIMENTO"
    tp_amb: int = 2
    tp_nf: int = 1
    fin_nfe: int = 1
    tp_emis: int = 1
    inf_cpl: str | None = MARCA_SINTETICO
    assinar: bool = True
    com_protocolo: bool = True
    c_stat: str = "100"
    x_motivo: str = "Autorizado o uso da NF-e"
    dv_errado: bool = False
    # grupo ZF (NT 2024.003): ZF01 agropecuario 0-1 com ZF04 guiaTransito 1-1, ou seja, no máximo UMA guia por
    # NF-e: {"tpGuia", "UFGuia", "serieGuia", "nGuia"} (chave ausente fica fora do XML)
    guia_transito: dict[str, str] | None = None

    @property
    def chave(self) -> str:
        doc = so_alnum(self.emitente.documento)
        c = montar_chave(CODIGO_UF[self.emitente.uf], self.dh_emi.strftime("%y%m"), doc, "55", self.serie,
                         self.n_nf, self.tp_emis, self.c_nf)
        return c[:43] + str((int(c[43]) + 1) % 10) if self.dv_errado else c


def _sub(pai: etree._Element, nome: str, texto: Any = None, **attrs: str) -> etree._Element:
    el = etree.SubElement(pai, f"{{{NS}}}{nome}", **attrs)
    if texto is not None:
        el.text = str(texto)
    return el


def _parte(pai: etree._Element, tag: str, ender: str, p: ParteSintetica, nome: str) -> None:
    el = _sub(pai, tag)
    doc = so_alnum(p.documento)
    _sub(el, "CPF" if len(doc) == 11 else "CNPJ", doc)
    _sub(el, "xNome", nome)
    en = _sub(el, ender)
    for k, v in (("xLgr", p.logradouro), ("nro", "SN"), ("xBairro", "ZONA RURAL"), ("cMun", p.c_mun),
                 ("xMun", p.x_mun), ("UF", p.uf), ("CEP", p.cep), ("cPais", "1058"), ("xPais", "BRASIL")):
        _sub(en, k, v)
    if tag == "dest":
        _sub(el, "indIEDest", "1" if p.ie else "9")
    if p.ie:
        _sub(el, "IE", p.ie)
    if tag == "emit":
        _sub(el, "CRT", "3")


def gerar_nfe_xml(spec: NFeSintetica, pool: PoolChaves | None,
                  adulterar: Callable[[etree._Element], None] | None = None) -> bytes:
    """XML procNFe (ou NFe sem protocolo) no leiaute 4.00, compacto, assinado com chave sintética.

    `adulterar(infNFe)` roda depois da assinatura (simula edição do XML assinado).
    """
    chave = spec.chave
    proc = etree.Element(f"{{{NS}}}nfeProc", nsmap={None: NS}, versao="4.00") if spec.com_protocolo else None
    nfe = (etree.SubElement(proc, f"{{{NS}}}NFe") if proc is not None
           else etree.Element(f"{{{NS}}}NFe", nsmap={None: NS}))
    inf = _sub(nfe, "infNFe", Id=f"NFe{chave}", versao="4.00")
    ide = _sub(inf, "ide")
    mesma_uf = spec.emitente.uf == spec.destinatario.uf
    for k, v in (("cUF", CODIGO_UF[spec.emitente.uf]), ("cNF", spec.c_nf), ("natOp", spec.nat_op), ("mod", "55"),
                 ("serie", spec.serie), ("nNF", spec.n_nf), ("dhEmi", spec.dh_emi.isoformat()),
                 ("dhSaiEnt", spec.dh_emi.isoformat()), ("tpNF", spec.tp_nf), ("idDest", "1" if mesma_uf else "2"),
                 ("cMunFG", spec.emitente.c_mun), ("tpImp", "1"), ("tpEmis", spec.tp_emis), ("cDV", chave[43]),
                 ("tpAmb", spec.tp_amb), ("finNFe", spec.fin_nfe), ("indFinal", "0"), ("indPres", "1"),
                 ("procEmi", "0"), ("verProc", "GERADOR-LAUDO-VIVO-0.1")):
        _sub(ide, k, v)
    _parte(inf, "emit", "enderEmit", spec.emitente, spec.emitente.nome)
    nome_dest = NOME_HOMOLOGACAO if spec.tp_amb == 2 else spec.destinatario.nome
    _parte(inf, "dest", "enderDest", spec.destinatario, nome_dest)
    total = 0.0
    for i, it in enumerate(spec.itens, 1):
        det = _sub(inf, "det", nItem=str(i))
        prod = _sub(det, "prod")
        for k, v in (("cProd", it.c_prod), ("cEAN", "SEM GTIN"), ("xProd", it.x_prod), ("NCM", it.ncm),
                     ("CFOP", it.cfop), ("uCom", it.u_com), ("qCom", f"{it.q_com:.4f}"),
                     ("vUnCom", f"{it.v_un_com:.10f}"), ("vProd", f"{it.v_prod:.2f}"), ("cEANTrib", "SEM GTIN"),
                     ("uTrib", it.u_trib or it.u_com), ("qTrib", f"{(it.q_trib or it.q_com):.4f}"),
                     ("vUnTrib", f"{it.v_prod / (it.q_trib or it.q_com):.10f}"), ("indTot", "1")):
            _sub(prod, k, v)
        imp = _sub(det, "imposto")
        icms = _sub(_sub(imp, "ICMS"), "ICMS40")
        _sub(icms, "orig", "0")
        _sub(icms, "CST", "40")
        _sub(_sub(_sub(imp, "PIS"), "PISNT"), "CST", "07")
        _sub(_sub(_sub(imp, "COFINS"), "COFINSNT"), "CST", "07")
        total += it.v_prod
    tot = _sub(_sub(inf, "total"), "ICMSTot")
    for k in ("vBC", "vICMS", "vICMSDeson", "vFCP", "vBCST", "vST", "vFCPST", "vFCPSTRet"):
        _sub(tot, k, "0.00")
    _sub(tot, "vProd", f"{total:.2f}")
    for k in ("vFrete", "vSeg", "vDesc", "vII", "vIPI", "vIPIDevol", "vPIS", "vCOFINS", "vOutro"):
        _sub(tot, k, "0.00")
    _sub(tot, "vNF", f"{total:.2f}")
    _sub(_sub(inf, "transp"), "modFrete", "9")
    det_pag = _sub(_sub(inf, "pag"), "detPag")
    _sub(det_pag, "tPag", "15")
    _sub(det_pag, "vPag", f"{total:.2f}")
    if spec.inf_cpl:
        _sub(_sub(inf, "infAdic"), "infCpl", spec.inf_cpl)
    if spec.guia_transito is not None:
        if not isinstance(spec.guia_transito, dict):
            raise TypeError("guia_transito: uma guia por NF-e (NT 2024.003, ZF04 1-1), não uma lista")
        gt = _sub(_sub(inf, "agropecuario"), "guiaTransito")
        for k in ("tpGuia", "UFGuia", "serieGuia", "nGuia"):
            if spec.guia_transito.get(k):
                _sub(gt, k, spec.guia_transito[k])

    digest = base64.b64encode(hashlib.sha1(xmldsig.canonicalizar(inf)).digest()).decode()
    if spec.assinar:
        if pool is None:
            raise ValueError("assinar=True exige PoolChaves")
        chave_rsa, cert = pool.para(spec.emitente.documento, spec.emitente.nome)
        xmldsig.assinar(nfe, inf, chave_rsa, cert)
    if adulterar is not None:
        adulterar(inf)
    if proc is not None:
        prot = etree.SubElement(proc, f"{{{NS}}}protNFe", versao="4.00")
        n_prot = f"1{CODIGO_UF[spec.emitente.uf]}{spec.dh_emi:%y}{int(chave[25:34]) % 10**10:010d}"
        ip = etree.SubElement(prot, f"{{{NS}}}infProt", Id=f"ID{n_prot}")
        for k, v in (("tpAmb", spec.tp_amb), ("verAplic", "SEFAZ-TESTE-SINTETICA"), ("chNFe", chave),
                     ("dhRecbto", spec.dh_emi.replace(second=min(spec.dh_emi.second + 7, 59)).isoformat()),
                     ("nProt", n_prot), ("digVal", digest), ("cStat", spec.c_stat), ("xMotivo", spec.x_motivo)):
            _sub(ip, k, v)
    raiz = proc if proc is not None else nfe
    return etree.tostring(raiz, xml_declaration=True, encoding="UTF-8")
