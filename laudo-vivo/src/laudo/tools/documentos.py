"""Ferramentas de documentos fiscais: `conciliar_nfe` e `conciliar_gta`.

Determinísticas e offline. Calculam critérios por campo (ok/divergente/indeterminado, com regra e
motivo) e listam o que não é verificável offline (alertas). Quem atribui o status do laudo é o
verificador; o LLM nunca define status a partir destas saídas sem passar por ele.

Com docs_fiscais 0.2.0, `conciliar_gta` cruza a GTA com o grupo ZF da NF-e (`documento:gta:nfe_guia`,
só quando a nota traz o grupo; uma guia por NF-e) e as duas ferramentas consultam, só lendo, o índice de
documentos de laudos selados (`documento:gta:reuso`, `documento:nfe:reuso`) quando recebem
`indice_documentos` e `operacao_ref` (no produto, o executor os preenche a partir do diretório de dados e da
ref. Bacen). Nenhuma das duas grava nada: o registro no índice é da selagem
(`laudo.agent.indice.registrar_na_selagem`, que usa `docs_fiscais.indice.documentos_selaveis`).

**Descrições para o LLM.** As duas descrições de `@registrar` citam o grupo ZF da NF-e (só `conciliar_gta`)
e a consulta de reuso ao índice de laudos selados. A descrição entra no esquema que o LLM recebe, e o hash do
esquema entra na chave do replay (`llm.provider.chave_requisicao`): mudar a descrição faz as gravações com
ferramentas reais (`tests/unit/dados_agente/replay_demo_real*_qwen35_4b.jsonl` e
`eval/golden/demo/DEMO-0001/replay_qwen35_4b.jsonl`) deixarem de casar, e elas precisam ser regravadas. As
gravações com ferramentas falsas (`replay_demo_qwen35_4b.jsonl`) não dependem dela: as falsas têm descrição
própria.
"""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from laudo.contracts import CodigoErro, Envelope, ItemFinanciado, registrar
from laudo.docs_fiscais import FONTE_VERSAO
from laudo.docs_fiscais import gta as gta_mod
from laudo.docs_fiscais import indice as indice_mod
from laudo.docs_fiscais import leitura as leitura_mod
from laudo.docs_fiscais import nfe as nfe_mod
from laudo.docs_fiscais.comum import Criterio, agregar_campos, pior
from laudo.privacidade import hash_referencia

_FONTE = f"{FONTE_VERSAO};ncm=TEC-Res.Gecex-272/2021;nfe=MOC-4.00;gta=IN-MAPA-09-2021"
_TAMANHO_MAXIMO_JSON = 1024 * 1024


class _Contexto(BaseModel):
    item: ItemFinanciado = Field(description="Item financiado a comprovar (tipo 'bovinos')")
    uf_operacao: str = Field("GO", description="UF da operação")
    municipio_ibge: str | None = Field(None, description="Código IBGE do município da operação")
    municipio_nome: str | None = None
    data_contratacao: date | None = None
    data_fiscalizacao: date | None = None
    tomador_doc_sha256: str | None = Field(None, description="CPF/CNPJ do tomador como hash, nunca em claro: "
                                                             "o hash público (comum.hash_documento_publico, "
                                                             "`<hex>` ou `sha256:<hex>`, convertido aqui) ou "
                                                             "`hmac:<hex>` (hash desta instalação)")
    codigo_estabelecimento_destino: str | None = Field(None, description="Código do estabelecimento (OESA) "
                                                                         "da propriedade da operação")
    # Índice de documentos reutilizados (docs_fiscais/indice.py): só roda com os dois campos e só LÊ (o
    # registro é da selagem do laudo, fora das ferramentas). O LLM não os preenche (parâmetros técnicos ficam
    # fora do esquema que ele vê); quem liga é o executor ou o harness.
    indice_documentos: str | None = Field(None, description="Índice local (JSONL) de GTA e NF-e de laudos "
                                                            "selados, só com HMAC (consulta, nunca grava)")
    operacao_ref: str | None = Field(None, description="Referência da operação (ref. Bacen; vira HMAC): "
                                                       "separa refiscalização da mesma operação de reuso")

    def contexto(self) -> nfe_mod.ContextoOperacao:
        return nfe_mod.ContextoOperacao(
            uf=self.uf_operacao, municipio_ibge=self.municipio_ibge, municipio_nome=self.municipio_nome,
            data_contratacao=self.data_contratacao, data_fiscalizacao=self.data_fiscalizacao,
            tomador_doc_sha256=hash_referencia(self.tomador_doc_sha256),
            codigo_estabelecimento_destino=self.codigo_estabelecimento_destino)


class EntradaConciliarNFe(_Contexto):
    xmls: list[str] = Field(default_factory=list, description="Conteúdo XML de cada NF-e (procNFe ou NFe)")
    caminhos: list[str] = Field(default_factory=list, description="Caminhos locais de arquivos XML de NF-e")
    leituras_foto: list[dict[str, Any]] = Field(
        default_factory=list, description="DANFE lido de foto por `ler_documento_foto` (campo `documento`, só "
                                          "campos validados); preenchido pelo condutor")
    parametros: nfe_mod.ParametrosNFe = Field(default_factory=nfe_mod.ParametrosNFe)


class EntradaConciliarGTA(_Contexto):
    gtas: list[dict[str, Any]] = Field(default_factory=list, description="e-GTA em JSON (modelo GTA)")
    caminhos: list[str] = Field(default_factory=list, description="Caminhos locais de e-GTA em JSON")
    nfe_xmls: list[str] = Field(default_factory=list, description="NF-e da mesma compra (opcional)")
    nfe_caminhos: list[str] = Field(default_factory=list)
    leituras_foto: list[dict[str, Any]] = Field(
        default_factory=list, description="GTA lida de foto/PDF por `ler_documento_foto` (campo `documento`)")
    nfe_leituras_foto: list[dict[str, Any]] = Field(default_factory=list, description="DANFE lido de foto")
    parametros: gta_mod.ParametrosGTA = Field(default_factory=gta_mod.ParametrosGTA)


def _ler_arquivo(caminho: str, limite: int) -> bytes:
    p = Path(caminho)
    if not p.is_file():
        raise FileNotFoundError(f"arquivo não encontrado: {caminho}")
    if p.stat().st_size > limite:
        raise ValueError(f"arquivo {p.name} excede {limite} bytes")
    return p.read_bytes()


def _ler_nfes(xmls: list[str], caminhos: list[str]) -> list[nfe_mod.NFe]:
    fontes: list[tuple[str, bytes]] = [(f"xml[{i}]", x.encode("utf-8")) for i, x in enumerate(xmls)]
    fontes += [(Path(c).name, _ler_arquivo(c, nfe_mod.TAMANHO_MAXIMO_XML)) for c in caminhos]
    return [nfe_mod.ler_nfe(b, origem=o) for o, b in fontes]


def _nfes_de_fotos(leituras: list[dict[str, Any]], nfes_xml: list[nfe_mod.NFe]) -> tuple[list[nfe_mod.NFe],
                                                                                       list[dict[str, Any]]]:
    """NF-e montadas das leituras de DANFE. DANFE cuja chave já veio em XML não vira nota nova (seria
    "duplicada"): é conferido contra o XML (o papel bate com o documento autorizado?)."""
    por_chave = {n.chave: n for n in nfes_xml if n.chave}
    novas, conferencias = [], []
    # a mesma nota fotografada de novo (pedido de nova foto) é uma nota só: mescla campo a campo
    leituras, _ = leitura_mod.mesclar_leituras([d for d in leituras if d.get("tipo") in (None, "danfe")])
    for i, doc in enumerate(leituras, 1):
        xml = por_chave.get(doc.get("chave"))
        if xml is None:
            novas.append(nfe_mod.de_leitura_danfe(doc, origem=f"danfe_foto[{i}]"))
            continue
        difs = []
        if doc.get("data_emissao") and xml.data_emissao and doc["data_emissao"] != xml.data_emissao.isoformat():
            difs.append("data de emissão")
        if doc.get("v_prod") is not None and xml.v_prod is not None and abs(doc["v_prod"] - xml.v_prod) > 0.011:
            difs.append("valor total dos produtos")
        q_foto = [it.get("quantidade") for it in doc.get("itens") or []]
        q_xml = [it.q_com for it in xml.itens]
        if None not in q_foto and q_foto and len(q_foto) == len(q_xml) and any(
                abs((a or 0) - (b or 0)) > 1e-6 for a, b in zip(q_foto, q_xml, strict=True)):
            difs.append("quantidade")
        conferencias.append({"chave": xml.chave_mascarada, "difere_em": difs})
    return novas, conferencias


def _com_status(data: dict[str, Any], item_id: str) -> dict[str, Any]:
    """Acrescenta `status` (vocabulário `StatusChecagem`: o pior dos campos) e `motivo` (campos não ok).

    O verificador e o rulebook leem o status da checagem; sem ele, uma GTA divergente viraria "ok".
    """
    campos = data.get("campos") or {}
    st = pior(*(c["status"] for c in campos.values())) if campos else "indeterminado"
    nao_ok = [f"{nome}: {c['status']} ({'; '.join(c.get('motivos') or [])})"
              for nome, c in campos.items() if c["status"] != "ok"]
    data["status"] = st
    data["motivo"] = " | ".join(nao_ok)[:600] if nao_ok else "todos os critérios conferem"
    data["item_id"] = item_id
    return data


def _anexar(data: dict[str, Any], criterios: list[Criterio]) -> None:
    """Acrescenta critérios calculados fora da conciliação pura (índice de reuso) a `criterios` e `campos`."""
    for crit in criterios:
        data["criterios"].append(crit.saida())
        novo = agregar_campos([crit])[crit.campo]
        atual = data["campos"].get(crit.campo)
        if atual is None:
            data["campos"][crit.campo] = novo
            continue
        atual["criterios"] += novo["criterios"]
        atual["motivos"] += novo["motivos"]
        if pior(atual["status"], crit.status) != atual["status"]:
            atual.update(status=crit.status, status_campo_sugerido=novo["status_campo_sugerido"],
                         regra_id=crit.regra_id)


def _reuso(args: _Contexto, tipo: str, documentos: list[tuple[str, str | None]]) -> list[Criterio]:
    """Consulta (só leitura) ao índice de documentos de laudos selados (GTA, chave de NF-e), quando ligado
    (`indice_documentos` + `operacao_ref`). Erro de E/S no índice vira critério indeterminado, nunca
    exceção."""
    if not args.indice_documentos or not args.operacao_ref:
        return []
    try:
        indice = indice_mod.IndiceDocumentos(args.indice_documentos)
        crit = indice_mod.conferir_reuso(indice, tipo, documentos, args.operacao_ref, args.item.id)
    except (OSError, UnicodeDecodeError) as e:
        crit = Criterio(id=f"{tipo}.reuso", campo=indice_mod.CAMPO[tipo], status="indeterminado",
                        regra_id=indice_mod.REGRA,
                        motivo=f"índice de documentos indisponível ({type(e).__name__})")
    return [crit] if crit is not None else []


def _checar_item(item: ItemFinanciado) -> str | None:
    if item.tipo != "bovinos":
        return f"item {item.id} é do tipo {item.tipo}; conciliação fiscal implementada só para bovinos"
    return None


@registrar(
    "conciliar_nfe",
    "Lê NF-e XML (leiaute 4.00), verifica offline chave/DV, assinatura (DigestValue C14N e certificado "
    "embutido) e protocolo, e concilia com o item de bovinos: NCM 01.02, quantidade, valor, data entre "
    "contratação e fiscalização, vendedor ≠ tomador, comprador = tomador, UF/CFOP. Também confere, só lendo, se "
    "a chave da nota já comprovou OUTRA operação num laudo selado desta instalação (reuso de documento, indício "
    "de duplicidade de crédito, MCR 2-7-7-d: divergente; refiscalização da mesma operação não é reuso). "
    "Devolve critérios por campo.",
    EntradaConciliarNFe,
)
def conciliar_nfe(args: EntradaConciliarNFe) -> Envelope:
    t0 = time.perf_counter()
    nome = "conciliar_nfe"
    if msg := _checar_item(args.item):
        return Envelope.falha(nome, CodigoErro.FORA_DO_ESCOPO, msg, t0=t0)
    if not args.xmls and not args.caminhos and not args.leituras_foto:
        return Envelope.falha(nome, CodigoErro.ENTRADA_INVALIDA, "nenhuma NF-e informada (xmls ou caminhos)", t0=t0)
    try:
        nfes = _ler_nfes(args.xmls, args.caminhos)
    except (nfe_mod.ErroLeituraNFe, FileNotFoundError, ValueError) as e:
        return Envelope.falha(nome, CodigoErro.ENTRADA_INVALIDA, f"NF-e ilegível: {e}", t0=t0)
    fotos, conferencias = _nfes_de_fotos(args.leituras_foto, nfes)
    try:
        data = nfe_mod.conciliar(nfes + fotos, args.item, args.contexto(), args.parametros)
        for c in conferencias:  # papel × XML: diferença pede nova foto ou o papel original (nunca diverge)
            st = "indeterminado" if c["difere_em"] else "ok"
            crit = {"id": "nfe.danfe_confere_xml", "campo": "documento:nfe:integridade", "status": st,
                    "regra_id": "AJ-SINIEF-07-2005-cl3", "status_campo_sugerido": "pendente" if st != "ok" else
                    "verificado", "valores": c,
                    "motivo": (f"DANFE fotografado difere do XML {c['chave']} em {', '.join(c['difere_em'])}: "
                               "confira o papel e refaça a foto") if c["difere_em"] else
                    f"DANFE fotografado confere com o XML {c['chave']}"}
            data["criterios"].append(crit)
            campo = data["campos"]["documento:nfe:integridade"]
            campo["criterios"].append(crit["id"])
            campo["motivos"].append(crit["motivo"])
            if st != "ok" and campo["status"] == "ok":
                campo.update(status=st, status_campo_sugerido="pendente", regra_id=crit["regra_id"])
        if fotos or conferencias:
            data["danfe_fotos"] = {"novas": len(fotos), "conferidas_com_xml": len(conferencias)}
        docs = [(n.chave_mascarada, indice_mod.hash_nfe(n.chave)) for n in nfes + fotos]
        _anexar(data, _reuso(args, "nfe", docs))
        data = _com_status(data, args.item.id)
    except Exception as e:  # noqa: BLE001 - erro interno vira Envelope, nunca valor inventado
        return Envelope.falha(nome, CodigoErro.ERRO_INTERNO, f"{type(e).__name__}: {e}", t0=t0)
    return Envelope.sucesso(nome, data, fonte_versao=_FONTE, t0=t0)


@registrar(
    "conciliar_gta",
    "Confere e-GTA (JSON) de bovinos/bubalinos contra a NF-e e o item: formato (IN MAPA 09/2021), espécie e "
    "sexo, quantidade (GTA ≥ NF), destino = município/estabelecimento da operação, origem ≠ tomador, "
    "finalidade e coerência temporal com a contratação e com a NF-e. Cruza a GTA com o grupo ZF da NF-e "
    "(NT 2024.003: a guia citada na nota deve estar entre as apresentadas, senão pendente; nota sem o grupo é "
    "neutra) e confere, só lendo, se a GTA já comprovou OUTRA operação num laudo selado desta instalação "
    "(reuso, análogo à rejeição 838 'Guia de Trânsito já utilizada': divergente). Devolve critérios por campo.",
    EntradaConciliarGTA,
)
def conciliar_gta(args: EntradaConciliarGTA) -> Envelope:
    t0 = time.perf_counter()
    nome = "conciliar_gta"
    if msg := _checar_item(args.item):
        return Envelope.falha(nome, CodigoErro.FORA_DO_ESCOPO, msg, t0=t0)
    brutos: list[dict[str, Any]] = list(args.gtas)
    try:
        for c in args.caminhos:
            brutos.append(json.loads(_ler_arquivo(c, _TAMANHO_MAXIMO_JSON).decode("utf-8")))
    except (FileNotFoundError, ValueError) as e:
        return Envelope.falha(nome, CodigoErro.ENTRADA_INVALIDA, f"GTA ilegível: {e}", t0=t0)
    if not brutos and not args.leituras_foto:
        return Envelope.falha(nome, CodigoErro.ENTRADA_INVALIDA, "nenhuma GTA informada (gtas ou caminhos)", t0=t0)
    try:
        gtas = [gta_mod.GTA.model_validate(b) for b in brutos]
        fotos_gta, _ = leitura_mod.mesclar_leituras([d for d in args.leituras_foto if d.get("tipo") in (None, "gta")])
        gtas += [gta_mod.de_leitura(d) for d in fotos_gta]
    except ValidationError as e:
        return Envelope.falha(nome, CodigoErro.ENTRADA_INVALIDA, f"GTA ilegível: {e.error_count()} erro(s) de "
                              f"validação; primeiro: {e.errors()[0]['loc']} {e.errors()[0]['msg']}", t0=t0)
    try:
        nfes = _ler_nfes(args.nfe_xmls, args.nfe_caminhos)
        nfes += _nfes_de_fotos(args.nfe_leituras_foto, nfes)[0]
    except (nfe_mod.ErroLeituraNFe, FileNotFoundError, ValueError) as e:
        return Envelope.falha(nome, CodigoErro.ENTRADA_INVALIDA, f"NF-e ilegível: {e}", t0=t0)
    try:
        data = gta_mod.conciliar(gtas, args.item, args.contexto(), nfes, args.parametros)
        docs = [(g.identificador, indice_mod.hash_gta(g.uf_emissao, g.serie, g.numero)) for g in gtas]
        _anexar(data, _reuso(args, "gta", docs))
        data = _com_status(data, args.item.id)
    except Exception as e:  # noqa: BLE001
        return Envelope.falha(nome, CodigoErro.ERRO_INTERNO, f"{type(e).__name__}: {e}", t0=t0)
    return Envelope.sucesso(nome, data, fonte_versao=_FONTE, t0=t0)
