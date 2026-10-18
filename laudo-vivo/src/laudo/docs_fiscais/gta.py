"""GTA (Guia de Trânsito Animal) de bovinos e bubalinos: modelo, conciliação e renderização.

Não há XML público da e-GTA (em GO é emitida no SIDAGO/Agrodefesa). O modelo JSON abaixo segue:
- IN MAPA 09/2021, art. 3º (conteúdo mínimo da e-GTA) e art. 9º (UF + 6 dígitos + 1-2 letras de série);
- Manual SDA de trânsito de bovinos e bubalinos v2.0 (itens 01, 02, 10 a 21 do formulário);
- IN Agrodefesa 05/2013 (e-GTA em GO, código de barras verificável) e a integração NF-e/GTA de GO
  (IN Intersecretarial 01/2021; desde 31/03/2025 a chave da NF-e é exigida no SIDAGO).
Faixas etárias (0-12, 13-24, 25-36 e >36 meses) são as usadas nas GTAs de bovídeos e nas análises de
movimentação dos OESA (ex.: IDAF-ES 2020); conferir a tela atual do SIDAGO antes do piloto.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal

from jinja2 import Environment, select_autoescape
from pydantic import BaseModel, Field

from laudo.contracts import ItemFinanciado
from laudo.docs_fiscais.comum import (
    Criterio,
    NaoVerificado,
    agregar_campos,
    hash_documento,
    mascarar_documento,
    mascarar_nome,
    normalizar,
    pior,
    sha256_texto,
    sinais_injecao,
    so_alnum,
    tipo_documento,
)
from laudo.docs_fiscais.nfe import NFe, classe_esperada, itens_relevantes

FAIXAS_ETARIAS = ("0-12", "13-24", "25-36", ">36")
FINALIDADES_OK = {"ENGORDA", "REPRODUCAO", "RECRIA", "CRIA"}
FINALIDADES_DIVERGENTES = {"ABATE", "EXPORTACAO", "DESTRUICAO", "SACRIFICIO_SANITARIO", "QUARENTENA", "PESQUISA",
                           "PRODUCAO_INSUMOS_BIOLOGICOS"}
_SEXO_F = ("novilha", "vaca", "matriz", "bezerra", "femea", "fêmea")
_SEXO_M = ("touro", "tourinho", "reprodutor", "garrote", "boi", "bezerro", "macho")
_RE_NUMERO = re.compile(r"^\d{6}$")
_RE_SERIE = re.compile(r"^[A-Z]{1,2}$")
_RE_CARGA = re.compile(r"CARGA\s*(\d+)\s*(?:DE|/)\s*(\d+)")


# ---------------------------------------------------------------------------
# Modelo
# ---------------------------------------------------------------------------


class QuantidadeGTA(BaseModel):
    sexo: Literal["M", "F"]
    # "nao_lida": foto da GTA em que só os totais por sexo validaram (ver `leitura.validar_gta`)
    faixa_etaria: Literal["0-12", "13-24", "25-36", ">36", "nao_lida"]
    quantidade: int = Field(ge=0)


class LocalGTA(BaseModel):
    """Itens 11 (procedência) e 12 (destino) do formulário; art. 3º, II e III, da IN 09/2021."""

    documento: str | None = None  # CPF/CNPJ do produtor responsável pela exploração
    documento_sha256: str | None = None  # quando só o hash é conhecido (GTA lida de foto)
    nome: str | None = None
    estabelecimento: str | None = None
    codigo_estabelecimento: str | None = None
    codigo_exploracao: str | None = None
    municipio_nome: str | None = None
    municipio_ibge: str | None = None
    uf: str | None = None


class EmissaoGTA(BaseModel):
    """Item 20: local, data, hora e validade."""

    local_municipio: str | None = None
    data: date | None = None
    hora: str | None = None
    validade: date | None = None


class EmitenteGTA(BaseModel):
    """Item 19 (tipo do emitente) e item 18 (unidade expedidora)."""

    tipo: str | None = None  # MV_FEDERAL | MV_ESTADUAL | FUNCIONARIO_AUTORIZADO | MV_HABILITADO | PRODUTOR
    identificacao: str | None = None
    unidade_expedidora: str | None = None


class GTA(BaseModel):
    modelo: str = "e-GTA"
    uf_emissao: str | None = None
    numero: str | None = None
    serie: str | None = None
    especie: str | None = None  # item 01: "bovina" | "bubalina"
    quantidades: list[QuantidadeGTA] = Field(default_factory=list)  # item 01
    total: int | None = None  # soma do item 01
    total_por_extenso: str | None = None  # item 10
    marca_rebanho: str | None = None  # item 02
    origem: LocalGTA = Field(default_factory=LocalGTA)  # item 11
    destino: LocalGTA = Field(default_factory=LocalGTA)  # item 12
    finalidade: str | None = None  # item 13
    meio_transporte: dict[str, Any] | None = None  # item 14
    vacinacoes: list[dict[str, Any]] = Field(default_factory=list)  # item 15
    exames: list[dict[str, Any]] = Field(default_factory=list)  # item 16
    observacao: str | None = None  # item 17
    emitente: EmitenteGTA | None = None  # itens 18, 19 e 21
    emissao: EmissaoGTA = Field(default_factory=EmissaoGTA)  # item 20
    nfe_chaves: list[str] = Field(default_factory=list)  # GO: chave(s) de NF-e informada(s) no SIDAGO
    codigo_barras: str | None = None
    sintetico: bool = False
    fonte: str = "json"  # json | foto (campos lidos de foto/scan e validados em `leitura.py`)
    ilegiveis: list[str] = Field(default_factory=list)  # campos da foto que não validaram

    @property
    def especie_normalizada(self) -> str | None:
        e = normalizar(self.especie)
        if e.startswith("BOVIN"):
            return "bovina"
        if e.startswith(("BUBALIN", "BUFAL")):
            return "bubalina"
        return e.lower() or None

    @property
    def soma_quantidades(self) -> int:
        return sum(q.quantidade for q in self.quantidades)

    @property
    def identificador(self) -> str:
        return f"{self.uf_emissao or '??'}-{self.serie or '?'}-{self.numero or '??????'}"

    def resumo(self) -> dict[str, Any]:
        """Resumo sem PII: documentos viram máscara + hash; nomes de pessoa física viram iniciais."""
        d = self.model_dump(mode="json", exclude={"origem", "destino", "observacao"})
        for lado in ("origem", "destino"):
            loc: LocalGTA = getattr(self, lado)
            t = tipo_documento(loc.documento)
            d[lado] = {**loc.model_dump(mode="json", exclude={"documento", "nome"}),
                       "doc_mascarado": mascarar_documento(loc.documento),
                       "doc_sha256": hash_documento(loc.documento) or loc.documento_sha256,
                       "nome": mascarar_nome(loc.nome, t)}
        d["observacao_sha256"] = sha256_texto(self.observacao) if self.observacao else None
        d["soma_quantidades"] = self.soma_quantidades
        return d


def _distancia(a: str, b: str) -> int:
    """Distância de edição (Levenshtein) entre dois códigos curtos."""
    ant = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(ant[j] + 1, cur[j - 1] + 1, ant[j - 1] + (ca != cb)))
        ant = cur
    return ant[-1]


def sexo_esperado(item: ItemFinanciado) -> str | None:
    t = (item.categoria_animal or "").lower()
    if any(p in t for p in _SEXO_F):
        return "F"
    if any(p in t for p in _SEXO_M):
        return "M"
    return None


# ---------------------------------------------------------------------------
# Conciliação GTA x NF-e x item
# ---------------------------------------------------------------------------


class ParametrosGTA(BaseModel):
    tolerancia_quantidade: int = Field(0, ge=0, description="cabeças a menos admitidas na GTA")
    tolerancia_data_dias: int = Field(0, ge=0, description="dias antes da contratação admitidos")
    tolerancia_ordem_dias: int = Field(1, ge=0, description="GTA até N dias antes da NF: pendente")
    janela_transporte_dias: int = Field(30, ge=0, description="GTA mais de N dias após a NF: pendente")


def conciliar(gtas: list[GTA], item: ItemFinanciado, ctx: Any, nfes: list[NFe] | None = None,
              params: ParametrosGTA | None = None) -> dict[str, Any]:
    """Concilia GTA(s) com a(s) NF-e (quando houver) e com o item. `ctx` é `nfe.ContextoOperacao`.

    O conteúdo da NF-e é usado como declarado; a integridade dela é avaliada por `conciliar_nfe`.
    """
    p = params or ParametrosGTA()
    nfes = nfes or []
    pref = f"item:{item.id}"
    crit = [_formato(gtas), _especie(pref, gtas, item, nfes), _quantidade(pref, gtas, item, nfes, p),
            _destino(pref, gtas, ctx), _origem(pref, gtas, ctx, nfes), _finalidade(pref, gtas),
            _data(pref, gtas, ctx, nfes, p)]
    # NT 2024.003: só quando a NF-e traz o grupo ZF (ausência é neutra)
    if (zf := guia_nfe(gtas, nfes)) is not None:
        crit.append(zf)
    alertas = [
        NaoVerificado(id="gta.autenticidade", regra_id="IN-AGRODEFESA-05-2013",
                      motivo="autenticidade da e-GTA na BDU/SIDAGO (código de barras/QR) não verificada offline"),
        NaoVerificado(id="gta.baixa_cancelamento", regra_id="IN-MAPA-09-2021-art6",
                      motivo="baixa no destino e eventual cancelamento não verificáveis offline"),
    ]
    if not ctx.codigo_estabelecimento_destino:
        alertas.append(NaoVerificado(id="gta.codigo_estabelecimento", regra_id="MAPA-SDA-BOV-item12",
                                     motivo="código do estabelecimento da operação não informado; "
                                            "destino conferido só por município e UF"))
    ocorrencias = []
    for k, g in enumerate(gtas, 1):
        for campo, texto in (("observacao", g.observacao), ("marca_rebanho", g.marca_rebanho)):
            if texto and (pad := sinais_injecao(texto)):
                ocorrencias.append({"tipo": "injecao", "regra_id": "POL-06", "fonte": f"gta{k}.{campo}",
                                    "padroes": pad, "texto_sha256": sha256_texto(texto)})
    return {
        "gtas": [g.resumo() for g in gtas],
        "criterios": [c.saida() for c in crit],
        "campos": agregar_campos(crit),
        "nao_verificado_offline": [a.model_dump() for a in alertas],
        "ocorrencias_sugeridas": ocorrencias,
        "totais": {"gtas": len(gtas), "cabecas": sum(g.soma_quantidades for g in gtas)},
    }


def _formato(gtas: list[GTA]) -> Criterio:
    base = {"id": "gta.formato", "campo": "documento:gta:formato", "regra_id": "IN-MAPA-09-2021-art3"}
    if not gtas:
        return Criterio(status="indeterminado", motivo="nenhuma GTA apresentada", **base)
    problemas: list[tuple[str, str, str]] = []
    vistos: set[str] = set()
    for g in gtas:
        gid = g.identificador
        if gid in vistos:
            problemas.append(("divergente", "IN-MAPA-09-2021-art3", f"GTA {gid} apresentada mais de uma vez"))
        vistos.add(gid)
        if not (g.numero and _RE_NUMERO.match(g.numero)) or not (g.serie and _RE_SERIE.match(g.serie)):
            problemas.append(("indeterminado", "IN-MAPA-09-2021-art9",
                              f"GTA {gid}: número/série fora do padrão (6 dígitos + 1-2 letras)"))
        faltam = [nome for nome, v in (
            ("espécie", g.especie), ("quantidades", g.quantidades), ("finalidade", g.finalidade),
            ("origem.código", g.origem.codigo_estabelecimento), ("origem.município", g.origem.municipio_nome
                                                                 or g.origem.municipio_ibge),
            ("destino.código", g.destino.codigo_estabelecimento), ("destino.município", g.destino.municipio_nome
                                                                   or g.destino.municipio_ibge),
            ("emissão.data", g.emissao.data), ("emissão.validade", g.emissao.validade), ("emitente", g.emitente),
        ) if not v]
        if faltam:
            problemas.append(("indeterminado", "IN-MAPA-09-2021-art3", f"GTA {gid}: faltam {', '.join(faltam)}"))
        if g.total is not None and g.total != g.soma_quantidades:
            problemas.append(("divergente", "MAPA-SDA-BOV-item01",
                              f"GTA {gid}: total {g.total} difere da soma por sexo/faixa ({g.soma_quantidades})"))
        if g.emissao.data and g.emissao.validade and g.emissao.validade < g.emissao.data:
            problemas.append(("divergente", "MAPA-SDA-BOV-item20", f"GTA {gid}: validade anterior à emissão"))
    if not problemas:
        return Criterio(status="ok", motivo="campos mínimos presentes, número/série no padrão e totais coerentes",
                        **base)
    st = pior(*(s for s, _, _ in problemas))
    base["regra_id"] = next(r for s, r, _ in problemas if s == st)
    return Criterio(status=st, motivo="; ".join(m for _, _, m in problemas), **base)


def _especie(pref: str, gtas: list[GTA], item: ItemFinanciado, nfes: list[NFe]) -> Criterio:
    base = {"id": "gta.especie", "campo": f"{pref}:gta_especie", "regra_id": "MAPA-SDA-BOV-item01"}
    esperada = "bubalina" if classe_esperada(item) == "bubalino" else "bovina"
    especies = sorted({g.especie_normalizada or "?" for g in gtas})
    val: dict[str, Any] = {"especies_gta": especies, "esperada": esperada}
    if not gtas or "?" in especies:
        return Criterio(status="indeterminado", motivo="GTA sem espécie", valores=val, **base)
    if any(e != esperada for e in especies):
        return Criterio(status="divergente", valores=val,
                        motivo=f"GTA de espécie {', '.join(especies)}; item financiado é {esperada}", **base)
    classes_nf = {it.ncm_classe for _, it in itens_relevantes(nfes)[0]} if nfes else set()
    oposta = "bubalino" if esperada == "bovina" else "bovino_domestico"
    if oposta in classes_nf:
        return Criterio(status="divergente", valores=val,
                        motivo=f"GTA de espécie {esperada}, mas a NF-e descreve {oposta}", **base)
    sexo = sexo_esperado(item)
    if sexo and any(g.fonte == "foto" and g.total is None for g in gtas):
        return Criterio(status="indeterminado", valores=val,
                        motivo="quantidades por sexo ilegíveis na foto da GTA; refaça a foto", **base)
    if sexo:
        n_sexo = sum(q.quantidade for g in gtas for q in g.quantidades if q.sexo == sexo)
        val["cabecas_sexo_esperado"] = n_sexo
        if n_sexo == 0:
            return Criterio(status="divergente", valores=val,
                            motivo=f"item de {item.categoria_animal} ({sexo}), mas a GTA não traz animais desse sexo",
                            **base)
    return Criterio(status="ok", valores=val, motivo=f"GTA de espécie {esperada}"
                    + (f" com animais do sexo {sexo}" if sexo else ""), **base)


def _quantidade(pref: str, gtas: list[GTA], item: ItemFinanciado, nfes: list[NFe], p: ParametrosGTA) -> Criterio:
    base = {"id": "gta.quantidade", "campo": f"{pref}:gta_quantidade", "regra_id": "MCR-2-7-item2b"}
    total = sum(g.soma_quantidades for g in gtas)
    ref, origem_ref = None, ""
    if nfes:
        cab = [it.cabecas for _, it in itens_relevantes(nfes)[0]]
        if cab and None not in cab:
            ref, origem_ref = sum(c for c in cab if c is not None), "NF-e"
    if ref is None and item.quantidade is not None:
        ref, origem_ref = int(item.quantidade), "item financiado"
    val = {"cabecas_gta": total, "referencia": ref, "referencia_fonte": origem_ref,
           "tolerancia": p.tolerancia_quantidade}
    if not gtas or ref is None:
        return Criterio(status="indeterminado", valores=val, motivo="sem GTA ou sem quantidade de referência", **base)
    if any(g.fonte == "foto" and g.total is None for g in gtas):  # quantidade ilegível nunca vira "0 cabeças"
        return Criterio(status="indeterminado", valores=val,
                        motivo="quantidade ilegível na foto da GTA; refaça a foto", **base)
    if total >= ref - p.tolerancia_quantidade:
        return Criterio(status="ok", valores=val, motivo=f"GTA cobre {total} cabeças para {ref} da {origem_ref}",
                        **base)
    cargas = [_RE_CARGA.search(normalizar(g.observacao)) for g in gtas]
    declaradas = max((int(m.group(2)) for m in cargas if m), default=0)
    if declaradas > len(gtas):
        return Criterio(status="indeterminado", valores={**val, "cargas_declaradas": declaradas},
                        motivo=f"GTA indica carga parcial ({len(gtas)} de {declaradas} veículos); "
                               "apresente a(s) GTA(s) complementar(es)", **base)
    return Criterio(status="divergente", valores=val,
                    motivo=f"GTA cobre {total} cabeças; {origem_ref} tem {ref} (faltam {ref - total} com trânsito "
                           "documentado; se houve outro veículo, apresente a GTA complementar)", **base)


def _mesmo_municipio(loc: Any, ibge: str | None, nome: str | None) -> bool | None:
    if loc.municipio_ibge and ibge:
        return loc.municipio_ibge == ibge
    if loc.municipio_nome and nome:
        return normalizar(loc.municipio_nome) == normalizar(nome)
    return None


def _destino(pref: str, gtas: list[GTA], ctx: Any) -> Criterio:
    base = {"id": "gta.destino", "campo": f"{pref}:gta_destino", "regra_id": "MAPA-SDA-BOV-item12"}
    if not gtas:
        return Criterio(status="indeterminado", motivo="nenhuma GTA apresentada", **base)
    problemas: list[tuple[str, str]] = []
    for g in gtas:
        d = g.destino
        if d.uf and d.uf != ctx.uf:
            problemas.append(("divergente", f"GTA {g.identificador}: destino em {d.uf}, operação em {ctx.uf}"))
        mesmo = _mesmo_municipio(d, ctx.municipio_ibge, ctx.municipio_nome)
        if mesmo is False:
            problemas.append(("divergente", (f"GTA {g.identificador}: destino em {d.municipio_nome or d.municipio_ibge}, "
                                            f"operação em {ctx.municipio_nome or ctx.municipio_ibge}")))
        elif mesmo is None:
            problemas.append(("indeterminado", f"GTA {g.identificador}: município de destino não comparável"))
        if ctx.codigo_estabelecimento_destino and d.codigo_estabelecimento is None and g.fonte == "foto":
            problemas.append(("indeterminado", (f"GTA {g.identificador}: código do estabelecimento de destino "
                                                "ilegível na foto")))
        elif (ctx.codigo_estabelecimento_destino and g.fonte == "foto" and d.codigo_estabelecimento
              and 0 < _distancia(d.codigo_estabelecimento, ctx.codigo_estabelecimento_destino) <= 2):
            problemas.append(("indeterminado", (f"GTA {g.identificador}: código do estabelecimento de destino lido na "
                                                "foto difere em 1-2 caracteres do da operação; confira o papel")))
        elif ctx.codigo_estabelecimento_destino and d.codigo_estabelecimento != ctx.codigo_estabelecimento_destino:
            problemas.append(("divergente", (f"GTA {g.identificador}: estabelecimento de destino "
                                            f"{d.codigo_estabelecimento} não é o da operação")))
        dh = hash_documento(d.documento) or d.documento_sha256
        if ctx.tomador_doc_sha256 and dh and dh != ctx.tomador_doc_sha256:
            problemas.append(("indeterminado", (f"GTA {g.identificador}: produtor de destino não é o tomador "
                                               "(arrendamento/parceria?)")))
    if not problemas:
        return Criterio(status="ok", motivo="destino no estabelecimento/município da operação", **base)
    return Criterio(status=pior(*(s for s, _ in problemas)), motivo="; ".join(m for _, m in problemas), **base)


def _origem(pref: str, gtas: list[GTA], ctx: Any, nfes: list[NFe]) -> Criterio:
    base = {"id": "gta.origem", "campo": f"{pref}:gta_origem"}
    if not gtas:
        return Criterio(status="indeterminado", regra_id="MAPA-SDA-BOV-item11", motivo="nenhuma GTA", **base)
    problemas: list[tuple[str, str, str]] = []
    vendedores = {v.doc_sha256 for n in nfes for v in [n.partes_operacao()[0]] if v and v.doc_sha256}
    mun_vendedores = {v.c_mun for n in nfes for v in [n.partes_operacao()[0]] if v and v.c_mun}
    chaves_nf = {n.chave for n in nfes if n.chave}
    for g in gtas:
        o, gid = g.origem, g.identificador
        oh = hash_documento(o.documento) or o.documento_sha256
        if ctx.tomador_doc_sha256 and oh == ctx.tomador_doc_sha256:
            problemas.append(("divergente", "MCR-2-7-item6", (f"GTA {gid}: origem é o próprio tomador "
                                                              "(indício de recuperação de capital investido)")))
        if o.codigo_estabelecimento and o.codigo_estabelecimento == g.destino.codigo_estabelecimento:
            problemas.append(("divergente", "MAPA-SDA-BOV-item11", (f"GTA {gid}: origem e destino no mesmo "
                                                                    "estabelecimento")))
        if vendedores and oh and oh not in vendedores:
            problemas.append(("indeterminado", "MAPA-SDA-BOV-item11", (f"GTA {gid}: produtor de origem não é o "
                                                                      "vendedor da NF-e (leilão/intermediário?)")))
        nomes_vend = {normalizar(v.x_mun) for n in nfes for v in [n.partes_operacao()[0]] if v and v.x_mun}
        if not mun_vendedores and nomes_vend and o.municipio_nome and normalizar(o.municipio_nome) not in nomes_vend:
            problemas.append(("indeterminado", "MAPA-SDA-BOV-item11", (f"GTA {gid}: município de origem difere do "
                                                                      "endereço do vendedor no DANFE")))
        if mun_vendedores and o.municipio_ibge and o.municipio_ibge not in mun_vendedores:
            problemas.append(("indeterminado", "MAPA-SDA-BOV-item11", (f"GTA {gid}: município de origem difere do "
                                                                      "endereço do vendedor na NF-e")))
        if g.nfe_chaves and chaves_nf and not set(g.nfe_chaves) & chaves_nf:
            problemas.append(("indeterminado", "GO-INC-ECONOMIA-AGRODEFESA-01-2021",
                              f"GTA {gid}: vinculada no SIDAGO a NF-e não apresentada"))
    if not problemas:
        motivo = "origem coerente com o vendedor da NF-e" if nfes else "origem distinta do tomador e do destino"
        return Criterio(status="ok", regra_id="MAPA-SDA-BOV-item11", motivo=motivo, **base)
    st = pior(*(s for s, _, _ in problemas))
    return Criterio(status=st, regra_id=next(r for s, r, _ in problemas if s == st),
                    motivo="; ".join(m for _, _, m in problemas), **base)


# Grupo ZF da NF-e, NT 2024.003 v1.03 (fev/2025) e v1.10 (mai/2026, mesmo leiaute; UFGuia passa a 1-1),
# leiaute e regras de validação:
# - ZF01 agropecuario (filho de infNFe, ocorrência 0-1) contém OU o ZF02 defensivo OU o ZF04 guiaTransito, e o
#   ZF04 ocorre no máximo 1 vez: **cada NF-e cita no máximo uma guia**. Uma compra em várias cargas (uma GTA
#   por veículo) pode vir numa NF-e só, que cita uma das GTAs: as demais não aparecem em grupo nenhum;
# - ZF05 tpGuia (N, 1 posição): 1 GTA, 2 TTA, 3 DTA (as três contam como "Guia de Trânsito Animal" na regra
#   ZF05-10), 4 ATV, 5 PTV, 6 GTV, 7 guia florestal. Só a GTA (1) tem o leiaute da e-GTA comparado aqui;
# - ZF06 UFGuia (C 2, 0-1), ZF07 serieGuia (C 1-9, 0-1: alfanumérica, "informar sempre que houver a série"),
#   ZF08 nGuia (N 1-9, 1-1);
# - regra ZF05-10 (rejeição 836, "não informada Guia de Trânsito Animal"): facultativa por UF, ativa para NCM
#   0102 (gado bovino) em BA, GO, MA e MT (tabela 4.1: 01/10/2025; pelo cronograma da v1.10, as regras de
#   validação da NT entraram em produção em 01/03/2026). Em GO, a NF-e real de compra de gado traz o grupo
#   com UMA guia.
TP_GUIA_GTA = 1


def _so_digitos(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


def _num_guia(s: str | None) -> int | None:
    """nGuia (N 1-9) e número da GTA (6 dígitos) comparados como inteiros (zeros à esquerda não contam)."""
    d = _so_digitos(s)
    return int(d) if d else None


def _serie_compativel(serie_nfe: str | None, serie_gta: str | None) -> bool | None:
    """True/False quando as duas séries são comparáveis; None quando não dá para comparar.

    O ZF07 (serieGuia) é alfanumérico (C 1-9) e opcional; a série da e-GTA (IN MAPA 09/2021, art. 9º) tem
    1-2 letras. Série ausente, ou só numérica de um lado e com letra do outro, não é comparável (não muda o
    status).
    """
    a, b = so_alnum(serie_nfe), so_alnum(serie_gta)
    if not a or not b or a.isdigit() != b.isdigit():
        return None
    return (int(a) == int(b)) if a.isdigit() else a == b


def _tp_guia(g: dict[str, Any]) -> int | None:
    d = _so_digitos(g.get("tp_guia"))
    return int(d) if d else None


def guias_gta_da_nfe(nfes: list[NFe]) -> list[tuple[NFe, dict[str, Any]]]:
    """Guias do tipo GTA declaradas no grupo ZF de cada NF-e (tpGuia ausente conta como GTA)."""
    return [(n, g) for n in nfes for g in n.guia_transito if _tp_guia(g) in (None, TP_GUIA_GTA)]


def _rotulo_guia(g: dict[str, Any]) -> str:
    return f"{g.get('uf') or '??'}-{g.get('serie') or '?'}-{g.get('numero') or '?'}"


def _mesma_uf(g: dict[str, Any], a: GTA) -> bool:
    return not g.get("uf") or not a.uf_emissao or g["uf"].upper() == a.uf_emissao.upper()


def _guia_casa(g: dict[str, Any], a: GTA) -> bool:
    num = _num_guia(g.get("numero"))
    return (num is not None and _num_guia(a.numero) == num and _mesma_uf(g, a)
            and _serie_compativel(g.get("serie"), a.serie) is not False)


def guia_nfe(gtas: list[GTA], nfes: list[NFe]) -> Criterio | None:
    """NF-e (grupo ZF, NT 2024.003) × GTA apresentada: a guia que cada nota cita está entre as apresentadas?

    Devolve None (nenhum critério) quando nenhuma NF-e cita GTA no grupo ou não há GTA: a validação é
    facultativa por UF/NCM, então a ausência do grupo é neutra. Com o grupo, **por NF-e** (cada nota cita no
    máximo uma guia, ZF04 1-1):
    - ok: a GTA citada (nGuia, UF e série, quando comparável) está entre as apresentadas;
    - indeterminado: a GTA citada não foi apresentada (o fiscal pode só não ter enviado; sem ela a GTA
      apresentada não se liga a esta nota), a apresentada com o mesmo número tem outra UF ou série, ou o
      número da GTA lida de foto é ilegível. Nunca divergente: o grupo ZF sozinho não prova que a GTA é de
      outra venda.
    GTA apresentada que nenhuma nota cita não muda o status (as outras cargas de uma nota não cabem no grupo);
    aparece em `valores.gtas_sem_citacao`."""
    citadas = guias_gta_da_nfe(nfes)
    if not citadas or not gtas:
        return None
    base = {"id": "gta.nfe_guia", "campo": "documento:gta:nfe_guia", "regra_id": "NT-2024.003-ZF"}
    por_nota: dict[int, tuple[NFe, list[dict[str, Any]]]] = {}
    for n, g in citadas:
        por_nota.setdefault(id(n), (n, []))[1].append(g)
    casadas: set[int] = set()  # índices das GTAs apresentadas que alguma nota cita
    problemas: list[tuple[str, str]] = []
    for n, guias in por_nota.values():
        achou = {k for k, a in enumerate(gtas) for g in guias if _guia_casa(g, a)}
        if achou:
            casadas |= achou
            continue
        rot = " ou ".join(_rotulo_guia(g) for g in guias)
        nums = {_num_guia(g.get("numero")) for g in guias} - {None}
        mesmo = next((a for a in gtas if _num_guia(a.numero) in nums), None)
        cita = f"NF-e {n.chave_mascarada} cita a GTA {rot} no grupo ZF"
        if mesmo is not None:
            msg = (f"{cita}; a apresentada com o mesmo número é {mesmo.identificador} (UF ou série diferente)"
                   + ("; confira o papel" if mesmo.fonte == "foto" else "; apresente a GTA citada na nota"))
        elif any(a.fonte == "foto" and _num_guia(a.numero) is None for a in gtas):
            msg = f"{cita}; número da GTA ilegível na foto: refaça a foto para comparar"
        else:
            apresentadas = ", ".join(a.identificador for a in gtas)
            msg = (f"{cita}, que não está entre as apresentadas ({apresentadas}): "
                   "apresente a GTA citada na nota")
        problemas.append(("indeterminado", msg))
    val: dict[str, Any] = {
        "guias_nfe": [_rotulo_guia(g) for _, g in citadas],
        "gtas": [a.identificador for a in gtas],
        "gtas_sem_citacao": [a.identificador for k, a in enumerate(gtas) if k not in casadas],
    }
    if fora := [n.chave_mascarada for n in nfes if len(n.guia_transito) > 1]:
        val["fora_do_leiaute"] = fora  # mais de uma guia na mesma NF-e (ZF01 0-1, ZF04 1-1)
    if not problemas:
        motivo = ("a GTA citada no grupo ZF de cada NF-e está entre as apresentadas (nGuia, UF e série "
                  "conferem)")
        return Criterio(status="ok", valores=val, motivo=motivo, **base)
    return Criterio(status=pior(*(s for s, _ in problemas)), valores=val,
                    motivo="; ".join(m for _, m in problemas), **base)


def _finalidade(pref: str, gtas: list[GTA]) -> Criterio:
    base = {"id": "gta.finalidade", "campo": f"{pref}:gta_finalidade", "regra_id": "MAPA-SDA-BOV-item13"}
    fins = sorted({normalizar(g.finalidade).replace(" ", "_") or "?" for g in gtas})
    if not gtas or "?" in fins:
        return Criterio(status="indeterminado", motivo="GTA sem finalidade", **base)
    if any(f in FINALIDADES_DIVERGENTES for f in fins):
        return Criterio(status="divergente", valores={"finalidades": fins},
                        motivo=f"finalidade {', '.join(fins)} incompatível com animais de investimento na fazenda",
                        **base)
    if all(f in FINALIDADES_OK for f in fins):
        return Criterio(status="ok", valores={"finalidades": fins}, motivo=f"finalidade {', '.join(fins)}", **base)
    return Criterio(status="indeterminado", valores={"finalidades": fins},
                    motivo=f"finalidade {', '.join(fins)} (evento/aglomeração?): confirme o trânsito até a fazenda",
                    **base)


def _data(pref: str, gtas: list[GTA], ctx: Any, nfes: list[NFe], p: ParametrosGTA) -> Criterio:
    base = {"id": "gta.data", "campo": f"{pref}:gta_data"}
    if not gtas or any(g.emissao.data is None for g in gtas):
        return Criterio(status="indeterminado", regra_id="MAPA-SDA-BOV-item20", motivo="GTA sem data de emissão",
                        **base)
    problemas: list[tuple[str, str, str]] = []
    datas_nf = {n.chave: n.data_emissao for n in nfes if n.data_emissao}
    for g in gtas:
        d, gid = g.emissao.data, g.identificador
        assert d is not None
        if ctx.data_contratacao and d.toordinal() < ctx.data_contratacao.toordinal() - p.tolerancia_data_dias:
            problemas.append(("divergente", "MCR-2-7-item6", (f"GTA {gid} emitida em {d.isoformat()}, antes da "
                                                              f"contratação ({ctx.data_contratacao.isoformat()})")))
        if ctx.data_fiscalizacao and d > ctx.data_fiscalizacao:
            problemas.append(("divergente", "MCR-2-7-item3", f"GTA {gid} posterior à fiscalização"))
        if not datas_nf:
            continue
        vinculadas = [datas_nf[c] for c in g.nfe_chaves if c in datas_nf]
        d_nf = min(vinculadas) if vinculadas else min(datas_nf.values())
        delta = (d - d_nf).days
        if delta < -p.tolerancia_ordem_dias:
            if (g.uf_emissao or "").upper() == "GO":
                problemas.append(("divergente", "GO-INC-ECONOMIA-AGRODEFESA-01-2021",
                                  (f"GTA {gid} emitida {-delta} dias antes da NF-e; em GO a chave da NF-e é exigida "
                                  "no SIDAGO para autorizar a GTA (desde 31/03/2025)")))
            else:
                problemas.append(("indeterminado", "NT-2024.003-ZF",
                                  f"GTA {gid} emitida {-delta} dias antes da NF-e; ordem não fixada nacionalmente"))
        elif delta < 0:
            problemas.append(("indeterminado", "NT-2024.003-ZF",
                              (f"GTA {gid} emitida {-delta} dia(s) antes da NF-e: a ordem NF/GTA não é fixa "
                              "nacionalmente (NT 2024.003 pode exigir a GTA na NF-e; GO exige a NF-e na GTA)")))
        elif delta > p.janela_transporte_dias:
            problemas.append(("indeterminado", "MAPA-SDA-BOV-item20",
                              f"GTA {gid} emitida {delta} dias após a NF-e: confirme que se refere a esta venda"))
    if not problemas:
        return Criterio(status="ok", regra_id="GO-INC-ECONOMIA-AGRODEFESA-01-2021",
                        motivo="emissão após a contratação e coerente com a data da NF-e", **base)
    st = pior(*(s for s, _, _ in problemas))
    return Criterio(status=st, regra_id=next(r for s, r, _ in problemas if s == st),
                    motivo="; ".join(m for _, _, m in problemas), **base)


# ---------------------------------------------------------------------------
# Renderização (HTML e PDF sintéticos para a demo)
# ---------------------------------------------------------------------------

_HTML = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<title>GTA {{ g.identificador }}{% if g.sintetico %} (sintética){% endif %}</title>
<style>
 body{font-family:Arial,Helvetica,sans-serif;font-size:12px;color:#111;background:#fff;margin:24px;position:relative}
 h1{font-size:16px;margin:0 0 4px} .sub{color:#555;margin-bottom:12px}
 table{border-collapse:collapse;width:100%;margin-bottom:8px} td,th{border:1px solid #444;padding:4px;vertical-align:top}
 th{background:#eee;text-align:left;width:22%} .item{font-weight:bold;background:#f6f6f6}
 .marca{position:fixed;top:40%;left:5%;font-size:40px;color:rgba(200,0,0,.18);transform:rotate(-25deg);
  pointer-events:none;font-weight:bold}
</style></head><body>
{% if g.sintetico %}<div class="marca">DOCUMENTO SINTÉTICO — SEM VALOR LEGAL</div>{% endif %}
<h1>Guia de Trânsito Animal — {{ g.modelo }} {{ g.uf_emissao }} série {{ g.serie }} nº {{ g.numero }}</h1>
<div class="sub">Modelo de dados inspirado na IN MAPA 09/2021 (art. 3º) e no Manual SDA de trânsito de bovinos e
bubalinos. {% if g.sintetico %}Gerado para testes do Laudo Vivo; não é documento oficial.{% endif %}</div>
<table>
<tr><td class="item" colspan="4">01 — Bovídeos: {{ g.especie }}</td></tr>
<tr><th>Sexo</th><th>Faixa etária (meses)</th><th colspan="2">Quantidade</th></tr>
{% for q in g.quantidades %}<tr><td>{{ q.sexo }}</td><td>{{ q.faixa_etaria }}</td><td colspan="2">{{ q.quantidade }}</td>
</tr>{% endfor %}
<tr><th>Total</th><td colspan="3">{{ g.total if g.total is not none else g.soma_quantidades }}</td></tr>
<tr><th>02 — Marca do rebanho</th><td colspan="3">{{ g.marca_rebanho or "" }}</td></tr>
<tr><th>10 — Total por extenso</th><td colspan="3">{{ g.total_por_extenso or "" }}</td></tr>
</table>
{% for titulo, loc in (("11 — Procedência", g.origem), ("12 — Destino", g.destino)) %}
<table><tr><td class="item" colspan="4">{{ titulo }}</td></tr>
<tr><th>CPF/CNPJ</th><td>{{ loc.documento or "" }}</td><th>Nome</th><td>{{ loc.nome or "" }}</td></tr>
<tr><th>Estabelecimento</th><td>{{ loc.estabelecimento or "" }}</td><th>Código</th>
<td>{{ loc.codigo_estabelecimento or "" }}</td></tr>
<tr><th>Município</th><td>{{ loc.municipio_nome or "" }} ({{ loc.municipio_ibge or "" }})</td><th>UF</th>
<td>{{ loc.uf or "" }}</td></tr></table>
{% endfor %}
<table>
<tr><th>13 — Finalidade</th><td>{{ g.finalidade or "" }}</td></tr>
<tr><th>14 — Meio de transporte</th><td>{{ (g.meio_transporte or {}).get("tipo", "") }}
 {{ (g.meio_transporte or {}).get("placa", "") }}</td></tr>
<tr><th>15 — Vacinações</th><td>{% for v in g.vacinacoes %}{{ v.get("doenca") }} {{ v.get("data") }}; {% endfor %}</td></tr>
<tr><th>16 — Atestados de exames</th><td>{% for e in g.exames %}{{ e.get("doenca") }} {{ e.get("resultado") }};
{% endfor %}</td></tr>
<tr><th>17 — Observação</th><td>{{ g.observacao or "" }}</td></tr>
<tr><th>18 — Unidade expedidora</th><td>{{ g.emitente.unidade_expedidora if g.emitente else "" }}</td></tr>
<tr><th>19 — Emitente</th><td>{{ g.emitente.tipo if g.emitente else "" }} —
 {{ g.emitente.identificacao if g.emitente else "" }}</td></tr>
<tr><th>20 — Emissão</th><td>{{ g.emissao.local_municipio or "" }}, {{ g.emissao.data }} {{ g.emissao.hora or "" }};
 validade {{ g.emissao.validade }}</td></tr>
<tr><th>NF-e vinculada (GO)</th><td>{{ g.nfe_chaves | join(", ") }}</td></tr>
<tr><th>Código de barras</th><td>{{ g.codigo_barras or "" }}</td></tr>
</table></body></html>
"""

_ENV = Environment(autoescape=select_autoescape(default=True, default_for_string=True))


def renderizar_html(g: GTA) -> str:
    return _ENV.from_string(_HTML).render(g=g)


_FONTES_TTF = ("DejaVuSans.ttf", "arial.ttf", "Arial.ttf", "LiberationSans-Regular.ttf", "segoeui.ttf")


def _fonte(tamanho: int) -> tuple[Any, bool]:
    """Fonte TrueType com acentos, se houver no sistema; senão a padrão do Pillow (sem acentos)."""
    from PIL import ImageFont

    for nome in _FONTES_TTF:
        try:
            return ImageFont.truetype(nome, tamanho), True
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=tamanho), False
    except TypeError:  # Pillow sem FreeType
        return ImageFont.load_default(), False


def _sem_acento(t: str) -> str:
    import unicodedata

    t = t.replace("—", "-").replace("–", "-")
    return "".join(ch for ch in unicodedata.normalize("NFKD", t) if not unicodedata.combining(ch))


def renderizar_imagem(g: GTA) -> Any:
    """Imagem A4 (150 dpi) com os campos da GTA, como uma guia digitalizada. Usa só Pillow."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (1240, 1754), "white")
    dr = ImageDraw.Draw(img)
    fonte, acentos = _fonte(22)
    titulo, _ = _fonte(30)

    def txt(s: str) -> str:
        return s if acentos else _sem_acento(s)

    y = 60
    dr.text((60, y), txt(f"GUIA DE TRÂNSITO ANIMAL — {g.modelo} {g.uf_emissao} série {g.serie} nº {g.numero}"),
            font=titulo, fill="black")
    y += 60
    linhas = [
        f"01 Espécie: {g.especie}   Total: {g.soma_quantidades}   ({g.total_por_extenso or ''})",
        *[f"     {q.sexo}  {q.faixa_etaria} meses: {q.quantidade}" for q in g.quantidades],
        f"02 Marca: {g.marca_rebanho or ''}",
        f"11 Procedência: {g.origem.nome or ''} — {g.origem.estabelecimento or ''}",
        f"     Código {g.origem.codigo_estabelecimento or ''} — {g.origem.municipio_nome or ''}/{g.origem.uf or ''}",
        f"12 Destino: {g.destino.nome or ''} — {g.destino.estabelecimento or ''}",
        f"     Código {g.destino.codigo_estabelecimento or ''} — {g.destino.municipio_nome or ''}/{g.destino.uf or ''}",
        f"13 Finalidade: {g.finalidade or ''}",
        f"14 Transporte: {(g.meio_transporte or {}).get('tipo', '')} {(g.meio_transporte or {}).get('placa', '')}",
        f"17 Observação: {g.observacao or ''}",
        f"19 Emitente: {g.emitente.tipo if g.emitente else ''} — {g.emitente.identificacao if g.emitente else ''}",
        (f"20 Emissão: {g.emissao.local_municipio or ''} {g.emissao.data} {g.emissao.hora or ''}"
        f"   Validade: {g.emissao.validade}"),
        f"NF-e vinculada: {', '.join(g.nfe_chaves)}",
    ]
    for linha in linhas:
        dr.text((60, y), txt(linha)[:100], font=fonte, fill="black")
        y += 40
    if g.sintetico:
        aviso = txt("DOCUMENTO SINTÉTICO — SEM VALOR LEGAL")
        caixa = dr.textbbox((0, 0), aviso, font=titulo)
        marca = Image.new("RGBA", (caixa[2] + 20, caixa[3] + 20), (255, 255, 255, 0))
        ImageDraw.Draw(marca).text((10, 10), aviso, font=titulo, fill=(200, 0, 0, 120))
        marca = marca.resize((marca.width * 3 // 2, marca.height * 3 // 2)).rotate(25, expand=True)
        img.paste(marca, ((img.width - marca.width) // 2, (img.height - marca.height) // 2), marca)
    return img


def renderizar_pdf(g: GTA) -> bytes:
    """PDF de uma página (imagem) com os campos da GTA."""
    import io

    buf = io.BytesIO()
    renderizar_imagem(g).save(buf, "PDF", resolution=150.0)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# GTA a partir da leitura (validada) de uma foto/scan
# ---------------------------------------------------------------------------


def de_leitura(doc: dict[str, Any]) -> GTA:
    """Monta uma `GTA` a partir de `leitura.validar_gta(...).documento` (só campos aceitos; CPF/CNPJ só como
    hash). Campo ilegível fica `None` e as regras o tratam como indeterminado, nunca como divergência."""

    def local(d: dict[str, Any] | None) -> LocalGTA:
        d = d or {}
        return LocalGTA(documento_sha256=d.get("documento_sha256"), nome=d.get("nome"),
                        estabelecimento=d.get("estabelecimento"), codigo_estabelecimento=d.get("codigo_estabelecimento"),
                        municipio_nome=d.get("municipio_nome"), municipio_ibge=d.get("municipio_ibge"), uf=d.get("uf"))

    em = doc.get("emissao") or {}
    return GTA(modelo="foto", uf_emissao=doc.get("uf_emissao"), numero=doc.get("numero"), serie=doc.get("serie"),
               especie=doc.get("especie"),
               quantidades=[QuantidadeGTA(**q) for q in doc.get("quantidades") or []],
               total=doc.get("total"), total_por_extenso=doc.get("total_por_extenso"),
               origem=local(doc.get("origem")), destino=local(doc.get("destino")), finalidade=doc.get("finalidade"),
               emitente=EmitenteGTA(identificacao=doc["emitente"]) if doc.get("emitente") else None,
               emissao=EmissaoGTA(data=em.get("data"), validade=em.get("validade"),
                                  local_municipio=em.get("local_municipio")),
               nfe_chaves=list(doc.get("nfe_chaves") or []), fonte="foto", ilegiveis=list(doc.get("ilegiveis") or []),
               observacao=doc.get("observacao"))
