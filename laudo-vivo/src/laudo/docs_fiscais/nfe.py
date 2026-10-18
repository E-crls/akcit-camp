"""NF-e (modelo 55, leiaute 4.00): leitura, integridade offline e conciliação com o item financiado.

Integridade (verificável offline): chave de acesso (formato, DV módulo 11, coerência com ide/emit),
assinatura XMLDSig (referência, DigestValue recalculado com C14N, SignatureValue contra o certificado
embutido) e protocolo de autorização (`protNFe`, cStat 100/150, chNFe e digVal).

Não verificável offline (vira alerta, nunca divergência): cadeia ICP-Brasil do certificado, situação
atual na SEFAZ (cancelamento, cláusula 12ª do Ajuste SINIEF 07/2005) e assinatura do protocolo.

Conciliação com o item (bovinos): espécie (NCM 01.02), quantidade de cabeças, valor, data entre a
contratação e a fiscalização, partes (vendedor ≠ tomador; comprador = tomador) e operação (UF/CFOP).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from lxml import etree
from pydantic import BaseModel, Field

from laudo.contracts import ItemFinanciado
from laudo.docs_fiscais import xmldsig
from laudo.docs_fiscais.comum import (
    Criterio,
    NaoVerificado,
    agregar_campos,
    brl,
    cnpj_valido,
    cpf_valido,
    decompor_chave,
    hash_documento,
    mascarar_documento,
    mascarar_nome,
    pior,
    sha256_texto,
    sinais_injecao,
    so_alnum,
    tipo_documento,
    validar_chave,
)
from laudo.docs_fiscais.fontes import classificar_ncm

NS = "http://www.portalfiscal.inf.br/nfe"
TAMANHO_MAXIMO_XML = 5 * 1024 * 1024

UNIDADES_CABECA = {"CB", "CAB", "CABECA", "CABECAS", "CBC", "CABS", "UN", "UND", "UNID", "UNIDADE", "U"}
UNIDADES_PESO = {"KG", "KGS", "@", "ARROBA", "ARROBAS", "ARR", "T", "TON", "TONELADA"}
# Sufixos de CFOP de venda (x.101 produção própria, x.102 revenda, x.105/x.106 sem trânsito pelo
# estabelecimento, comum em leilão, x.117-x.123 vendas à ordem/entrega futura/consignação).
SUFIXOS_CFOP_VENDA = {"101", "102", "105", "106", "117", "118", "119", "120", "122", "123"}
CSTAT_AUTORIZADO = {"100", "150"}


class ErroLeituraNFe(ValueError):
    """XML ilegível ou que não é uma NF-e."""


def _q(nome: str) -> str:
    return f"{{{NS}}}{nome}"


def _txt(el: etree._Element | None, caminho: str) -> str | None:
    if el is None:
        return None
    partes = "/".join(_q(p) for p in caminho.split("/"))
    v = el.findtext(partes)
    return v.strip() if v is not None and v.strip() else None


def _num(s: str | None) -> float | None:
    try:
        return float(s) if s is not None else None
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Modelos (saídas sempre mascaradas)
# ---------------------------------------------------------------------------


class ParteNFe(BaseModel):
    tipo_doc: str | None = None
    doc_mascarado: str | None = None
    doc_sha256: str | None = None
    doc_valido: bool | None = None
    nome: str | None = None  # iniciais quando pessoa física
    uf: str | None = None
    c_mun: str | None = None
    x_mun: str | None = None


class ItemNFe(BaseModel):
    n_item: int
    c_prod: str | None = None
    x_prod: str | None = None
    ncm: str | None = None
    ncm_classe: str
    ncm_descricao: str
    cfop: str | None = None
    u_com: str | None = None
    q_com: float | None = None
    v_un_com: float | None = None
    v_prod: float | None = None
    u_trib: str | None = None
    q_trib: float | None = None
    cabecas: int | None = None
    unidade_tipo: str = "desconhecida"  # cabeca | peso | desconhecida


class ProtocoloNFe(BaseModel):
    tp_amb: str | None = None
    ch_nfe: str | None = None
    dh_recbto: str | None = None
    n_prot: str | None = None
    dig_val: str | None = None
    c_stat: str | None = None
    x_motivo: str | None = None


class SubChecagem(BaseModel):
    id: str
    status: str  # ok | divergente | indeterminado
    motivo: str


class NFe(BaseModel):
    origem: str
    fonte: str = "xml"  # xml | danfe_foto (campos lidos de foto do DANFE e validados em `leitura.py`)
    chave: str | None = None
    versao: str | None = None
    c_uf: str | None = None
    c_nf: str | None = None
    nat_op: str | None = None
    modelo: str | None = None
    serie: str | None = None
    n_nf: str | None = None
    dh_emi: datetime | None = None
    tp_nf: str | None = None
    id_dest: str | None = None
    c_mun_fg: str | None = None
    tp_emis: str | None = None
    c_dv: str | None = None
    tp_amb: str | None = None
    fin_nfe: str | None = None
    emitente: ParteNFe
    destinatario: ParteNFe | None = None
    itens: list[ItemNFe] = Field(default_factory=list)
    v_nf: float | None = None
    v_prod: float | None = None
    protocolo: ProtocoloNFe | None = None
    assinatura: dict[str, Any] = Field(default_factory=dict)
    xml_reformatado: bool = False
    guia_transito: list[dict[str, Any]] = Field(default_factory=list)
    sinais_injecao: list[dict[str, Any]] = Field(default_factory=list)
    integridade: list[SubChecagem] = Field(default_factory=list)
    alertas: list[NaoVerificado] = Field(default_factory=list)

    @property
    def data_emissao(self) -> date | None:
        return self.dh_emi.date() if self.dh_emi else None

    @property
    def chave_mascarada(self) -> str:
        c = self.chave or "?" * 44
        return f"{c[:6]}…{c[-8:]}"

    def status_integridade(self) -> str:
        return pior(*(s.status for s in self.integridade))

    def partes_operacao(self) -> tuple[ParteNFe | None, ParteNFe | None]:
        """(vendedor, comprador): em NF de saída (tpNF=1) o emitente vende; em NF de entrada, compra."""
        if self.tp_nf == "0":
            return self.destinatario, self.emitente
        return self.emitente, self.destinatario

    def resumo(self) -> dict[str, Any]:
        d = self.model_dump(mode="json", exclude={"assinatura", "alertas"})
        a = {k: v for k, v in self.assinatura.items() if not k.startswith("_")}
        d["assinatura"] = a
        return d


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------


def _parser(remove_blank_text: bool) -> etree.XMLParser:
    return etree.XMLParser(remove_blank_text=remove_blank_text, resolve_entities=False, no_network=True,
                           huge_tree=False, load_dtd=False)


def _localizar(raiz: etree._Element) -> tuple[etree._Element, etree._Element, etree._Element | None]:
    if raiz.tag == _q("NFe"):
        nfe, prot = raiz, None
    elif raiz.tag == _q("nfeProc"):
        nfe, prot = raiz.find(_q("NFe")), raiz.find(_q("protNFe"))
    else:
        raise ErroLeituraNFe(f"elemento raiz {raiz.tag!r} não é NFe nem nfeProc (namespace {NS})")
    if nfe is None or nfe.find(_q("infNFe")) is None:
        raise ErroLeituraNFe("XML sem NFe/infNFe")
    return nfe, nfe.find(_q("infNFe")), prot


def _parte(el: etree._Element | None, ender: str) -> ParteNFe | None:
    if el is None:
        return None
    doc = _txt(el, "CNPJ") or _txt(el, "CPF")
    t = tipo_documento(doc)
    valido = (cnpj_valido(doc) if t == "cnpj" else cpf_valido(doc)) if t else None
    return ParteNFe(tipo_doc=t, doc_mascarado=mascarar_documento(doc), doc_sha256=hash_documento(doc),
                    doc_valido=valido, nome=mascarar_nome(_txt(el, "xNome"), t), uf=_txt(el, f"{ender}/UF"),
                    c_mun=_txt(el, f"{ender}/cMun"), x_mun=_txt(el, f"{ender}/xMun"))


def _item(det: etree._Element) -> ItemNFe:
    prod = det.find(_q("prod"))
    ncm = _txt(prod, "NCM")
    classe, desc = classificar_ncm(ncm)
    u_com, u_trib = _txt(prod, "uCom"), _txt(prod, "uTrib")
    q_com, q_trib = _num(_txt(prod, "qCom")), _num(_txt(prod, "qTrib"))
    cabecas, tipo = None, "desconhecida"
    for u, q in ((u_com, q_com), (u_trib, q_trib)):
        un = so_alnum(u) if u and u.strip() != "@" else "@" if u else ""
        if un in UNIDADES_CABECA and q is not None and float(q).is_integer():
            cabecas, tipo = int(q), "cabeca"
            break
        if un in UNIDADES_PESO and tipo == "desconhecida":
            tipo = "peso"
    return ItemNFe(n_item=int(det.get("nItem") or 0), c_prod=_txt(prod, "cProd"), x_prod=_txt(prod, "xProd"),
                   ncm=ncm, ncm_classe=classe, ncm_descricao=desc, cfop=_txt(prod, "CFOP"), u_com=u_com,
                   q_com=q_com, v_un_com=_num(_txt(prod, "vUnCom")), v_prod=_num(_txt(prod, "vProd")),
                   u_trib=u_trib, q_trib=q_trib, cabecas=cabecas, unidade_tipo=tipo)


def _verificar_assinatura(xml: bytes) -> tuple[dict[str, Any], bool]:
    """Verifica no XML como veio; se o digest falhar, tenta sem espaços entre tags (reformatação)."""
    resultado: dict[str, Any] = {}
    for reformatado in (False, True):
        raiz = etree.fromstring(xml, _parser(remove_blank_text=reformatado))
        nfe, inf, _ = _localizar(raiz)
        resultado = xmldsig.verificar(raiz, inf, nfe.find(f"{{{xmldsig.NS_DS}}}Signature"))
        if resultado.get("digest_ok") is not False:
            return resultado, reformatado
    return resultado, False


def ler_nfe(xml: bytes | str, origem: str = "xml") -> NFe:
    """Lê e verifica uma NF-e. Levanta `ErroLeituraNFe` se o XML for ilegível ou não for NF-e."""
    b = xml.encode("utf-8") if isinstance(xml, str) else xml
    if len(b) > TAMANHO_MAXIMO_XML:
        raise ErroLeituraNFe(f"XML com {len(b)} bytes excede o limite de {TAMANHO_MAXIMO_XML}")
    try:
        raiz = etree.fromstring(b, _parser(remove_blank_text=False))
    except etree.XMLSyntaxError as e:
        raise ErroLeituraNFe(f"XML malformado: {e}") from e
    _nfe_el, inf, prot = _localizar(raiz)
    ide = inf.find(_q("ide"))
    id_attr = inf.get("Id") or ""
    chave = id_attr[3:] if id_attr.startswith("NFe") else None
    dh = _txt(ide, "dhEmi") or _txt(ide, "dEmi")
    try:
        dh_emi = datetime.fromisoformat(dh) if dh else None
    except ValueError:
        dh_emi = None
    emit = inf.find(_q("emit"))
    n = NFe(
        origem=origem, chave=chave, versao=inf.get("versao"), c_uf=_txt(ide, "cUF"), c_nf=_txt(ide, "cNF"),
        nat_op=_txt(ide, "natOp"), modelo=_txt(ide, "mod"), serie=_txt(ide, "serie"), n_nf=_txt(ide, "nNF"),
        dh_emi=dh_emi, tp_nf=_txt(ide, "tpNF"), id_dest=_txt(ide, "idDest"), c_mun_fg=_txt(ide, "cMunFG"),
        tp_emis=_txt(ide, "tpEmis"), c_dv=_txt(ide, "cDV"), tp_amb=_txt(ide, "tpAmb"), fin_nfe=_txt(ide, "finNFe"),
        emitente=_parte(emit, "enderEmit") or ParteNFe(), destinatario=_parte(inf.find(_q("dest")), "enderDest"),
        itens=[_item(d) for d in inf.findall(_q("det"))],
        v_nf=_num(_txt(inf, "total/ICMSTot/vNF")), v_prod=_num(_txt(inf, "total/ICMSTot/vProd")),
    )
    if prot is not None:
        ip = prot.find(_q("infProt"))
        n.protocolo = ProtocoloNFe(tp_amb=_txt(ip, "tpAmb"), ch_nfe=_txt(ip, "chNFe"), dh_recbto=_txt(ip, "dhRecbto"),
                                   n_prot=_txt(ip, "nProt"), dig_val=_txt(ip, "digVal"), c_stat=_txt(ip, "cStat"),
                                   x_motivo=_txt(ip, "xMotivo"))
    for g in inf.findall(f"{_q('agropecuario')}/{_q('guiaTransito')}"):
        n.guia_transito.append({"tp_guia": _txt(g, "tpGuia"), "uf": _txt(g, "UFGuia"),
                                "serie": _txt(g, "serieGuia"), "numero": _txt(g, "nGuia")})
    _coletar_textos(inf, n)
    n.assinatura, n.xml_reformatado = _verificar_assinatura(b)
    _checar_integridade(n, emit)
    return n


def _coletar_textos(inf: etree._Element, n: NFe) -> None:
    textos = {"infAdic/infCpl": _txt(inf, "infAdic/infCpl"), "infAdic/infAdFisco": _txt(inf, "infAdic/infAdFisco")}
    for i, obs in enumerate(inf.findall(f"{_q('infAdic')}/{_q('obsCont')}")):
        textos[f"infAdic/obsCont[{i}]"] = _txt(obs, "xTexto")
    for it in n.itens:
        textos[f"det[{it.n_item}]/xProd"] = it.x_prod
    for campo, texto in textos.items():
        if texto and (padroes := sinais_injecao(texto)):
            n.sinais_injecao.append({"campo": campo, "padroes": padroes, "texto_sha256": sha256_texto(texto)})


def _checar_integridade(n: NFe, emit: etree._Element | None) -> None:
    sub = n.integridade
    ok, motivo = validar_chave(n.chave)
    sub.append(SubChecagem(id="chave_dv", status="ok" if ok else "divergente", motivo=motivo))
    if ok and n.chave:
        k = decompor_chave(n.chave)
        doc_emit = so_alnum(_txt(emit, "CNPJ") or _txt(emit, "CPF"))
        esperado = {
            "cUF": (k["c_uf"], n.c_uf), "AAMM": (k["aamm"], n.dh_emi.strftime("%y%m") if n.dh_emi else None),
            "CNPJ/CPF do emitente": (k["doc_emitente"], doc_emit.zfill(14) if doc_emit else None),
            "modelo": (k["modelo"], n.modelo), "série": (k["serie"], int(n.serie) if n.serie else None),
            "nNF": (k["numero"], int(n.n_nf) if n.n_nf else None), "tpEmis": (k["tp_emis"], n.tp_emis),
            "cNF": (k["c_nf"], n.c_nf), "cDV": (str(k["dv"]), n.c_dv),
        }
        difs = [nome for nome, (a, b) in esperado.items() if b is not None and str(a) != str(b)]
        sub.append(SubChecagem(id="chave_coerente", status="divergente" if difs else "ok",
                               motivo=f"chave não confere com {', '.join(difs)}" if difs
                               else "chave coerente com ide/emit"))
    if n.modelo and n.modelo != "55":
        sub.append(SubChecagem(id="modelo", status="indeterminado",
                               motivo=f"modelo {n.modelo} não é NF-e modelo 55"))
    a = n.assinatura
    if not a.get("presente"):
        sub.append(SubChecagem(id="assinatura_presente", status="indeterminado",
                               motivo="XML sem assinatura: peça o XML autorizado (procNFe) ao vendedor"))
    else:
        if a.get("referencia_ok") is False:
            sub.append(SubChecagem(id="referencia", status="divergente",
                                   motivo="a assinatura não referencia o infNFe desta nota"))
        if a.get("transforms_ok") is False:
            sub.append(SubChecagem(id="transforms", status="indeterminado",
                                   motivo="transform de assinatura não suportado"))
        d = a.get("digest_ok")
        sub.append(SubChecagem(
            id="digest", status={True: "ok", False: "divergente"}.get(d, "indeterminado"),
            motivo={True: "DigestValue recalculado (C14N) confere"
                    + (" após remover a indentação aplicada depois da assinatura" if n.xml_reformatado else ""),
                    False: "DigestValue não confere: conteúdo alterado depois da assinatura"}.get(
                d, "DigestValue não pôde ser recalculado")))
        r = a.get("rsa_ok")
        sub.append(SubChecagem(
            id="assinatura_rsa", status={True: "ok", False: "divergente"}.get(r, "indeterminado"),
            motivo={True: "SignatureValue confere com o certificado embutido",
                    False: "SignatureValue não confere com o certificado embutido"}.get(
                r, "SignatureValue não verificável (sem certificado embutido)")))
    n.alertas.append(NaoVerificado(
        id="nfe.cadeia_icp_brasil", regra_id="AJ-SINIEF-07-2005-cl3",
        motivo="cadeia do certificado até a AC raiz ICP-Brasil e revogação (LCR/OCSP) não verificadas offline"))
    cert = a.get("_cert")
    if cert:
        cn = cert["sujeito"].get("CN") or ""
        doc_emit = so_alnum(_txt(emit, "CNPJ") or _txt(emit, "CPF"))
        if doc_emit and doc_emit not in so_alnum(cn):
            n.alertas.append(NaoVerificado(id="nfe.certificado_emitente", regra_id="AJ-SINIEF-07-2005-cl3",
                                           motivo="o CN do certificado não traz o CNPJ/CPF do emitente"))
        if n.dh_emi and n.dh_emi.tzinfo and not (cert["nao_antes"] <= n.dh_emi <= cert["nao_depois"]):
            n.alertas.append(NaoVerificado(id="nfe.certificado_validade", regra_id="AJ-SINIEF-07-2005-cl3",
                                           motivo="data de emissão fora da validade do certificado embutido"))


# ---------------------------------------------------------------------------
# Conciliação
# ---------------------------------------------------------------------------


class ContextoOperacao(BaseModel):
    """Dados da operação necessários à conciliação (sem PII: o tomador entra só como hash)."""

    uf: str = "GO"
    municipio_ibge: str | None = None
    municipio_nome: str | None = None
    data_contratacao: date | None = None
    data_fiscalizacao: date | None = None
    tomador_doc_sha256: str | None = None
    codigo_estabelecimento_destino: str | None = None


class ParametrosNFe(BaseModel):
    """Tolerâncias (o rulebook define os valores; os defaults são conservadores)."""

    tolerancia_quantidade: int = Field(0, ge=0, description="cabeças a menos admitidas na NF")
    tolerancia_valor_pct: float = Field(0.05, ge=0, le=1, description="fração do valor do item")
    tolerancia_data_dias: int = Field(0, ge=0, description="dias antes da contratação admitidos")
    aceitar_homologacao: bool = Field(False, description="aceita tpAmb=2 (só golden set/testes)")


def classe_esperada(item: ItemFinanciado) -> str:
    texto = f"{item.categoria_animal or ''} {item.descricao}".lower()
    return "bubalino" if "bubal" in texto or "búfal" in texto or "bufal" in texto else "bovino_domestico"


def itens_relevantes(nfes: list[NFe]) -> tuple[list[tuple[NFe, ItemNFe]], bool]:
    """Itens de bovídeo vivo (posição 01.02); se não houver nenhum, todos os itens (fallback)."""
    todos = [(n, it) for n in nfes for it in n.itens]
    rel = [(n, it) for n, it in todos if it.ncm_classe != "nao_bovideo_vivo"]
    return (rel, False) if rel else (todos, True)


def conciliar(nfes: list[NFe], item: ItemFinanciado, ctx: ContextoOperacao,
              params: ParametrosNFe | None = None) -> dict[str, Any]:
    """Concilia uma ou mais NF-e com o item financiado. Função pura; não levanta exceção."""
    p = params or ParametrosNFe()
    crit: list[Criterio] = []
    pref = f"item:{item.id}"
    alertas: list[NaoVerificado] = []

    # --- integridade e autorização, por nota
    for k, n in enumerate(nfes, 1):
        st = n.status_integridade()
        motivos = [s.motivo for s in n.integridade if s.status != "ok"] or ["chave, assinatura e digest conferem"]
        crit.append(Criterio(id=f"nfe{k}.integridade", campo="documento:nfe:integridade", status=st,
                             regra_id="AJ-SINIEF-07-2005-cl3", motivo=f"NF-e {n.chave_mascarada}: " + "; ".join(motivos),
                             valores={"subchecagens": [s.model_dump() for s in n.integridade],
                                      "xml_reformatado": n.xml_reformatado}))
        crit.append(_autorizacao(k, n, p))
        alertas.extend(n.alertas)
        alertas.append(NaoVerificado(
            id=f"nfe{k}.situacao_sefaz", regra_id="AJ-SINIEF-07-2005-cl12",
            motivo="cancelamento/denegação posterior não verificável offline (exige NfeConsultaProtocolo "
                   "com certificado ou consulta no portal com CAPTCHA)"))
        if n.protocolo:
            alertas.append(NaoVerificado(id=f"nfe{k}.assinatura_protocolo", regra_id="AJ-SINIEF-07-2005-cl4",
                                         motivo="assinatura da SEFAZ no protocolo não verificada"))
    # notas repetidas
    chaves = [n.chave for n in nfes if n.chave]
    if len(set(chaves)) < len(chaves):
        crit.append(Criterio(id="nfe.duplicada", campo="documento:nfe:integridade", status="divergente",
                             regra_id="MCR-2-7-item6", motivo="a mesma NF-e foi apresentada mais de uma vez"))

    rel, fallback = itens_relevantes(nfes)
    crit.append(_especie(pref, item, rel, fallback))
    crit.append(_quantidade(pref, item, rel, p))
    crit.append(_valor(pref, item, rel, p))
    crit.append(_data(pref, nfes, ctx, p))
    crit.append(_partes(pref, nfes, ctx))
    crit.append(_operacao(pref, nfes, ctx, rel))

    # NF sem integridade: o conteúdo deixa de servir como prova (ok -> indeterminado)
    sem_integridade = [n for n in nfes if n.status_integridade() == "divergente"]
    if sem_integridade:
        aviso = (f"conteúdo não confiável: NF-e {', '.join(n.chave_mascarada for n in sem_integridade)} "
                 "falhou na integridade")
        for c in crit:
            if c.status == "ok" and c.campo != "documento:nfe:integridade":
                c.status = "indeterminado"
                c.motivo = f"{c.motivo} ({aviso})"

    ocorrencias = [{"tipo": "injecao", "regra_id": "POL-06", "fonte": f"nfe{k}.{s['campo']}",
                    "padroes": s["padroes"], "texto_sha256": s["texto_sha256"]}
                   for k, n in enumerate(nfes, 1) for s in n.sinais_injecao]
    cabecas = [it.cabecas for _, it in rel]
    return {
        "notas": [n.resumo() for n in nfes],
        "criterios": [c.saida() for c in crit],
        "campos": agregar_campos(crit),
        "nao_verificado_offline": [a.model_dump() for a in alertas],
        "ocorrencias_sugeridas": ocorrencias,
        "totais": {"notas": len(nfes),
                   "cabecas": sum(cabecas) if cabecas and None not in cabecas else None,
                   "valor_bovinos_rs": round(sum(it.v_prod or 0 for _, it in rel), 2),
                   "itens_fallback_sem_ncm_0102": fallback},
    }


def _autorizacao(k: int, n: NFe, p: ParametrosNFe) -> Criterio:
    campo, regra = "documento:nfe:autorizacao", "AJ-SINIEF-07-2005-cl4"
    pr = n.protocolo
    nome = f"NF-e {n.chave_mascarada}"
    if n.fonte == "danfe_foto":
        return Criterio(id=f"nfe{k}.autorizacao", campo=campo, status="indeterminado", regra_id=regra,
                        motivo=f"{nome}: DANFE fotografado não prova a autorização de uso; peça o XML (procNFe) "
                               "ou consulte a chave na SEFAZ")
    if pr is None:
        return Criterio(id=f"nfe{k}.autorizacao", campo=campo, status="indeterminado", regra_id=regra,
                        motivo=f"{nome}: XML sem protocolo de autorização (protNFe); peça o procNFe")
    problemas: list[tuple[str, str]] = []
    if pr.ch_nfe != n.chave:
        problemas.append(("divergente", "chNFe do protocolo difere da chave da nota"))
    if pr.c_stat not in CSTAT_AUTORIZADO:
        problemas.append(("divergente", f"cStat {pr.c_stat} ({pr.x_motivo}) não é uso autorizado"))
    dig = n.assinatura.get("digest_informado")
    if not dig:
        problemas.append(("indeterminado", "sem DigestValue para comparar com o digVal do protocolo"))
    elif pr.dig_val != dig:
        problemas.append(("divergente", "digVal do protocolo difere do DigestValue da assinatura"))
    if pr.tp_amb and n.tp_amb and pr.tp_amb != n.tp_amb:
        problemas.append(("divergente", "ambiente do protocolo difere do ambiente da nota"))
    if (n.tp_amb == "2" or pr.tp_amb == "2") and not p.aceitar_homologacao:
        problemas.append(("divergente", "NF-e de homologação (tpAmb=2), sem valor fiscal"))
    if not problemas:
        return Criterio(id=f"nfe{k}.autorizacao", campo=campo, status="ok", regra_id=regra,
                        motivo=f"{nome}: protocolo {pr.n_prot} com cStat {pr.c_stat} e digVal conferem",
                        valores={"c_stat": pr.c_stat, "n_prot": pr.n_prot, "tp_amb": n.tp_amb})
    return Criterio(id=f"nfe{k}.autorizacao", campo=campo, status=pior(*(s for s, _ in problemas)),
                    regra_id=regra, motivo=f"{nome}: " + "; ".join(m for _, m in problemas),
                    valores={"c_stat": pr.c_stat, "tp_amb": n.tp_amb})


def _especie(pref: str, item: ItemFinanciado, rel: list[tuple[NFe, ItemNFe]], fallback: bool) -> Criterio:
    esperada = classe_esperada(item)
    classes = sorted({it.ncm_classe for _, it in rel})
    ncms = sorted({it.ncm or "?" for _, it in rel})
    val = {"ncm": ncms, "classes": classes, "esperada": esperada}
    base = {"id": "nfe.especie", "campo": f"{pref}:nfe_especie", "regra_id": "MCR-2-7-item2b", "valores": val}
    if not rel:
        return Criterio(status="indeterminado", motivo="NF-e sem itens", **base)
    if "ncm_ilegivel" in classes:  # NCM não validado na leitura da foto: nunca vira divergência
        return Criterio(status="indeterminado", motivo="NCM ilegível na foto do DANFE; refaça a foto", **base)
    if fallback or any(c not in (esperada, "bovideo_desconhecido") for c in classes):
        return Criterio(status="divergente", motivo=f"NCM {', '.join(ncms)} não corresponde a {esperada} vivo "
                        "(posição 01.02 da NCM/TEC)", **base)
    if "bovideo_desconhecido" in classes:
        return Criterio(status="indeterminado", motivo=f"NCM {', '.join(ncms)} na posição 01.02 com subitem "
                        "desconhecido", **base)
    return Criterio(status="ok", motivo=f"NCM {', '.join(ncms)} é {esperada} vivo (posição 01.02)", **base)


def _quantidade(pref: str, item: ItemFinanciado, rel: list[tuple[NFe, ItemNFe]], p: ParametrosNFe) -> Criterio:
    base = {"id": "nfe.quantidade", "campo": f"{pref}:nfe_quantidade", "regra_id": "MCR-2-7-item2b"}
    if item.quantidade is None:
        return Criterio(status="indeterminado", motivo="item sem quantidade financiada", **base)
    cab = [it.cabecas for _, it in rel]
    if not rel or None in cab:
        unidades = sorted({it.u_com or "?" for _, it in rel})
        return Criterio(status="indeterminado", valores={"unidades": unidades},
                        motivo=f"quantidade de cabeças não determinável pela NF (unidade {', '.join(unidades)}); "
                               "confira pela GTA e pela contagem", **base)
    total, alvo = sum(c for c in cab if c is not None), int(item.quantidade)
    val = {"cabecas_nf": total, "cabecas_item": alvo, "tolerancia": p.tolerancia_quantidade}
    if total < alvo - p.tolerancia_quantidade:
        return Criterio(status="divergente", valores=val,
                        motivo=f"NF comprova {total} cabeças; financiadas {alvo} (faltam {alvo - total})", **base)
    extra = f"; {total - alvo} além do financiado (recursos próprios)" if total > alvo else ""
    return Criterio(status="ok", valores=val, motivo=f"NF comprova {total} cabeças para {alvo} financiadas{extra}",
                    **base)


def _valor(pref: str, item: ItemFinanciado, rel: list[tuple[NFe, ItemNFe]], p: ParametrosNFe) -> Criterio:
    base = {"id": "nfe.valor", "campo": f"{pref}:nfe_valor", "regra_id": "MCR-2-7-item2b"}
    if item.valor_rs is None:
        return Criterio(status="indeterminado", motivo="item sem valor financiado", **base)
    if not rel or any(it.v_prod is None for _, it in rel):
        return Criterio(status="indeterminado", motivo="NF sem vProd nos itens", **base)
    v = round(sum(it.v_prod or 0 for _, it in rel), 2)
    minimo = round(item.valor_rs * (1 - p.tolerancia_valor_pct), 2)
    val = {"valor_nf_rs": v, "valor_item_rs": item.valor_rs, "minimo_rs": minimo,
           "tolerancia_pct": p.tolerancia_valor_pct}
    if v < minimo:
        return Criterio(status="divergente", valores=val,
                        motivo=f"NF soma {brl(v)}; item financiado {brl(item.valor_rs)} "
                               f"(mínimo aceito {brl(minimo)})", **base)
    return Criterio(status="ok", valores=val, motivo=f"NF soma {brl(v)} para item de {brl(item.valor_rs)}",
                    **base)


def _data(pref: str, nfes: list[NFe], ctx: ContextoOperacao, p: ParametrosNFe) -> Criterio:
    base = {"id": "nfe.data", "campo": f"{pref}:nfe_data"}
    datas = [n.data_emissao for n in nfes]
    val = {"emissoes": [d.isoformat() if d else None for d in datas],
           "contratacao": ctx.data_contratacao.isoformat() if ctx.data_contratacao else None,
           "fiscalizacao": ctx.data_fiscalizacao.isoformat() if ctx.data_fiscalizacao else None}
    if None in datas or ctx.data_contratacao is None:
        return Criterio(status="indeterminado", regra_id="MCR-2-7-item6", valores=val,
                        motivo="sem data de emissão ou sem data de contratação", **base)
    inicio = ctx.data_contratacao.toordinal() - p.tolerancia_data_dias
    antes = [d for d in datas if d is not None and d.toordinal() < inicio]
    if antes:
        return Criterio(status="divergente", regra_id="MCR-2-7-item6", valores=val,
                        motivo=f"NF emitida em {min(antes).isoformat()}, antes da contratação "
                               f"({ctx.data_contratacao.isoformat()}): indício de recuperação de capital", **base)
    if ctx.data_fiscalizacao and any(d is not None and d > ctx.data_fiscalizacao for d in datas):
        return Criterio(status="divergente", regra_id="MCR-2-7-item3", valores=val,
                        motivo="NF com data posterior à fiscalização", **base)
    return Criterio(status="ok", regra_id="MCR-2-7-item6", valores=val,
                    motivo="emissão entre a contratação e a fiscalização", **base)


def _partes(pref: str, nfes: list[NFe], ctx: ContextoOperacao) -> Criterio:
    base = {"id": "nfe.partes", "campo": f"{pref}:nfe_partes"}
    if not ctx.tomador_doc_sha256:
        return Criterio(status="indeterminado", regra_id="MCR-2-7-item6",
                        motivo="hash do documento do tomador não informado", **base)
    problemas: list[tuple[str, str, str]] = []
    for n in nfes:
        vendedor, comprador = n.partes_operacao()
        if vendedor and vendedor.doc_sha256 == ctx.tomador_doc_sha256:
            problemas.append(("divergente", "MCR-2-7-item6",
                              (f"NF-e {n.chave_mascarada}: vendedor é o próprio tomador "
                              "(indício de recuperação de capital investido)")))
        if comprador is None or comprador.doc_sha256 is None:
            problemas.append(("indeterminado", "MCR-2-7-item2b", f"NF-e {n.chave_mascarada}: sem documento do comprador"))
        elif comprador.doc_sha256 != ctx.tomador_doc_sha256:
            problemas.append(("divergente", "MCR-2-7-item2b",
                              f"NF-e {n.chave_mascarada}: comprador ({comprador.doc_mascarado}) não é o tomador"))
    if not problemas:
        return Criterio(status="ok", regra_id="MCR-2-7-item6",
                        motivo="vendedor diferente do tomador e comprador igual ao tomador", **base)
    st = pior(*(s for s, _, _ in problemas))
    regra = next(r for s, r, _ in problemas if s == st)
    return Criterio(status=st, regra_id=regra, motivo="; ".join(m for _, _, m in problemas), **base)


def _operacao(pref: str, nfes: list[NFe], ctx: ContextoOperacao, rel: list[tuple[NFe, ItemNFe]]) -> Criterio:
    base = {"id": "nfe.operacao", "campo": f"{pref}:nfe_operacao", "regra_id": "MCR-2-7-item2b"}
    problemas: list[tuple[str, str]] = []
    for n in nfes:
        _, comprador = n.partes_operacao()
        uf_emit = n.emitente.uf
        uf_dest = n.destinatario.uf if n.destinatario else None
        if comprador is not None and comprador.uf and comprador.uf != ctx.uf:
            problemas.append(("indeterminado", (f"NF-e {n.chave_mascarada}: endereço do comprador em {comprador.uf}, "
                                               f"operação em {ctx.uf}")))
        if n.fin_nfe and n.fin_nfe != "1":
            problemas.append(("indeterminado", f"NF-e {n.chave_mascarada}: finalidade {n.fin_nfe} não é NF normal"))
        for nn, it in rel:
            if nn is not n or not it.cfop:
                continue
            if it.cfop[1:] not in SUFIXOS_CFOP_VENDA:
                problemas.append(("indeterminado", (f"CFOP {it.cfop} não é de venda (transferência, remessa, "
                                                   "doação?)")))
            if uf_emit and uf_dest and it.cfop[0] in "56":
                esperado = "5" if uf_emit == uf_dest else "6"
                if it.cfop[0] != esperado:
                    problemas.append(("divergente", f"CFOP {it.cfop} incoerente com UF {uf_emit}->{uf_dest}"))
    if not problemas:
        return Criterio(status="ok", motivo=f"operação de venda com destino em {ctx.uf}", **base)
    return Criterio(status=pior(*(s for s, _ in problemas)), motivo="; ".join(sorted({m for _, m in problemas})),
                    **base)


# ---------------------------------------------------------------------------
# NF-e a partir da leitura (validada) de uma foto do DANFE
# ---------------------------------------------------------------------------


def de_leitura_danfe(doc: dict[str, Any], origem: str = "danfe_foto") -> NFe:
    """Monta uma `NFe` a partir de `leitura.validar_danfe(...).documento` (só campos aceitos; documentos já
    como hash). O DANFE é representação gráfica: assinatura e protocolo não existem na foto, então a
    integridade fica `indeterminado` (pedir o XML ou consultar a chave), e a autorização também."""

    def parte(p: dict[str, Any] | None) -> ParteNFe:
        p = p or {}
        return ParteNFe(tipo_doc=p.get("tipo_doc"), doc_mascarado=p.get("doc_mascarado"),
                        doc_sha256=p.get("doc_sha256"), doc_valido=True if p.get("doc_sha256") else None,
                        nome=p.get("nome"), uf=p.get("uf"), x_mun=p.get("municipio"))

    itens = []
    for i, it in enumerate(doc.get("itens") or [], 1):
        ncm = it.get("ncm")
        classe, desc = classificar_ncm(ncm) if ncm else ("ncm_ilegivel", "NCM ilegível na foto")
        un = so_alnum(it.get("unidade")) if it.get("unidade") not in (None, "@") else it.get("unidade")
        q = it.get("quantidade")
        cab = int(q) if un in UNIDADES_CABECA and q is not None and float(q).is_integer() else None
        tipo = "cabeca" if cab is not None else "peso" if un in UNIDADES_PESO else "desconhecida"
        itens.append(ItemNFe(n_item=i, x_prod=it.get("descricao"), ncm=ncm, ncm_classe=classe, ncm_descricao=desc,
                             cfop=it.get("cfop"), u_com=it.get("unidade"), q_com=q,
                             v_un_com=it.get("valor_unitario"), v_prod=it.get("valor_total"), cabecas=cab,
                             unidade_tipo=tipo))
    data = doc.get("data_emissao")
    chave = doc.get("chave")
    n = NFe(origem=origem, fonte="danfe_foto", chave=chave, c_uf=doc.get("c_uf"), modelo=doc.get("modelo"),
            serie=str(doc["serie"]) if doc.get("serie") is not None else None,
            n_nf=str(doc["numero"]) if doc.get("numero") is not None else None,
            dh_emi=datetime.fromisoformat(data) if data else None, tp_nf=doc.get("tp_nf"),
            emitente=parte(doc.get("emitente")), destinatario=parte(doc.get("destinatario")), itens=itens,
            v_nf=doc.get("v_nf"), v_prod=doc.get("v_prod"))
    ok, motivo = validar_chave(chave) if chave else (False, "chave de acesso ilegível na foto")
    n.integridade.append(SubChecagem(id="chave_dv", status="ok" if ok else "indeterminado", motivo=motivo))
    n.integridade.append(SubChecagem(
        id="danfe_foto", status="indeterminado",
        motivo="DANFE fotografado: assinatura e protocolo só no XML; peça o procNFe ou consulte a chave na SEFAZ"))
    n.alertas.append(NaoVerificado(id="nfe.danfe_foto", regra_id="AJ-SINIEF-07-2005-cl3",
                                   motivo="campos lidos de foto do DANFE (VLM + validação determinística); a "
                                          "NF-e só vale com o XML autorizado"))
    return n
