"""Ferramentas de regras do MCR: `planejar_metodo`, `avaliar_regras` e `explicar_regra`.

Tudo aqui é determinístico e puro: o mesmo estado e a mesma data de referência dão sempre o mesmo resultado.
Nenhuma função lê o relógio, exceto os invólucros registrados quando a data de referência não vem na entrada
(nesse caso, com aviso).

- `planejar(...)`: método recomendado, obrigatoriedades, prazos com datas e requisitos de evidência por item.
- `avaliar(...)`: aplica o rulebook às `checagens` e `evidencias` da fiscalização e devolve um `CampoLaudo`
  por exigência e os bloqueios (regra_id e o que falta).
- `explicar(...)`: citação literal, fonte e justificativa de uma regra ou parâmetro.

As regras vêm de `src/laudo/rulebooks/*.yaml`. Este módulo só implementa os avaliadores nomeados ali
(ver docs/regras.md).
"""

from __future__ import annotations

import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, ValidationError

from laudo.contracts import (
    Bloqueio,
    CampoLaudo,
    Checagem,
    CodigoErro,
    Envelope,
    Fiscalizacao,
    ItemFinanciado,
    Operacao,
    registrar,
)
from laudo.formatacao import fmt_br
from laudo.rulebooks import Fluxo, Regra, Rulebook, avaliar_condicao, buscar_regra, carregar, todos

Prioridade = Literal["alta", "media", "baixa", "desconhecida"]
FonteRecursos = Literal["controlados", "direcionados", "livres", "nao_controlados"]
# "justificavel" (rulebook 0.3.0): medição precisa que não basta para verificar nem é inconclusiva (foto fora da
# gleba na faixa intermediária de distância): o campo fica pendente, pede nova captura ou justificativa do fiscal,
# e NÃO conta para a abstenção (abstenção é para medição imprecisa/indeterminada).
Veredito = Literal["verificado", "divergente", "inconclusivo", "incompleto", "justificavel", "erro"]

ID_27 = "mcr-2-7"
ID_29 = "mcr-2-9"
R_REMOTO = "MCR-2-7-item5-remoto-obrigatorio-300ha"
R_PECUARIA = "MCR-2-7-item9-pecuaria-pastagem-instalacoes"
R_INCONCLUSIVO = "MCR-2-7-item10-inconclusivo-outros-metodos"
R_ESCOLHA = "OP-metodo-escolha-por-item"
R_ENQUADRAMENTO = "OP-metodo-autofiscalizacao-enquadramento"
R_ESCOPO = "OP-escopo-itens-regional"
R_AGREGACAO = "OP-agregacao-item"
R_COMPROVANTES_30D = "MCR-2-5-item10-comprovantes-30d"
R_PRODES_INICIO = "MCR-2-9-item17-prodes-inicio"
R_PRODES_COLETIVO = "MCR-2-9-item17A-uso-coletivo"
R_PRODES_DOCS = "MCR-2-9-item18-documentos-regularizacao"
PAR_TENTATIVAS = "PAR-tentativas-inconclusivas-max"
# 0.5.0: marca do campo pendente de regra não bloqueante (ver `_marcar_nao_bloqueantes`)
RESSALVA_NAO_BLOQUEANTE = ("não bloqueante: ponto de atenção; não impede o rascunho nem entra no status do "
                           "item")

TIPOS_PECUARIA = {"bovinos", "cerca", "curral", "galpao"}
FUSO = ZoneInfo("America/Sao_Paulo")  # prazos do MCR contam em dias civis locais
TIPOS_EVIDENCIA_CAMPO = {"foto", "video", "audio"}  # captura no local (documento tem data de emissão)


# ---------------------------------------------------------------------------
# Entradas e saídas
# ---------------------------------------------------------------------------


class ContextoRegras(BaseModel):
    """Dados que as regras precisam e que ainda não existem em `contracts.Operacao`/`ItemFinanciado`.

    Proposta de migração para `contracts.py` no relatório do construtor de regras.
    """

    data_liberacao: date | None = None
    data_fiscalizacao: date | None = None  # se omitida: a primeira captura de campo (foto/vídeo/áudio)
    area_total_ha: float | None = None  # "área total" do MCR 2-7-5-b (Sicor público só tem a financiada)
    prioridade_verificacao: Prioridade = "desconhecida"  # vem de triar_carteira
    cronograma_fim: dict[str, date] = Field(default_factory=dict)  # item_id -> término do cronograma
    itens_sem_numero_serie: list[str] = Field(default_factory=list)  # máquinas sem numeração de fábrica
    modulos_fiscais: float | None = None  # tamanho do imóvel (CAR/Incra), para o MCR 2-9-17
    uso_coletivo: bool = False  # MCR 2-9-17-A
    fonte_recursos: FonteRecursos | None = None  # MCR 2-9-18
    rulebooks: list[str] = Field(default_factory=lambda: [ID_27])


def completar_contexto(contexto: ContextoRegras, op: Operacao, fisc: Fiscalizacao | None = None) -> ContextoRegras:
    """Completa o contexto com os campos que já existem nos contratos (`Operacao`, `ItemFinanciado`,
    `Fiscalizacao`). O que veio explícito no contexto prevalece; nada é inventado."""
    dados = contexto.model_dump()
    dado = contexto.model_fields_set

    def por(campo: str, valor: Any) -> None:
        if campo not in dado and valor not in (None, {}, []):
            dados[campo] = valor

    por("data_liberacao", op.data_liberacao)
    por("area_total_ha", op.area_total_ha)
    por("modulos_fiscais", op.modulos_fiscais)
    por("fonte_recursos", op.fonte_recursos)
    por("cronograma_fim", {it.id: it.cronograma_fim for it in op.itens if it.cronograma_fim})
    por("itens_sem_numero_serie", [it.id for it in op.itens if it.tipo == "maquina" and not it.exige_numero_serie])
    if fisc is not None:
        por("data_fiscalizacao", fisc.data_fiscalizacao)
        ids = [r.split("@")[0].replace("_", "-") for r in fisc.rulebooks]
        por("rulebooks", [i for i in ids if i in (ID_27, ID_29)])
    return ContextoRegras.model_validate(dados)


class PlanejarMetodoEntrada(BaseModel):
    operacao: Operacao
    contexto: ContextoRegras = Field(default_factory=ContextoRegras)
    data_referencia: date | None = None  # passe sempre a data de hoje


class AvaliarRegrasEntrada(BaseModel):
    fiscalizacao: Fiscalizacao
    contexto: ContextoRegras = Field(default_factory=ContextoRegras)
    data_referencia: date | None = None


class ExplicarRegraEntrada(BaseModel):
    regra_id: str = Field(description="ID de regra (ex.: MCR-2-7-item16-maquinas-60d) ou de parâmetro (PAR-...)")


class ResultadoAvaliacao(BaseModel):
    campos: dict[str, CampoLaudo]
    bloqueios: list[Bloqueio]
    alertas: list[str] = Field(default_factory=list)
    avisos: list[str] = Field(default_factory=list)
    nao_aplicaveis: list[dict[str, Any]] = Field(default_factory=list)
    resumo: dict[str, int] = Field(default_factory=dict)
    data_fiscalizacao: date | None = None
    fonte_versao: str = ""
    # 0.5.0: campos de regra não bloqueante que não ficaram verificados (ponto de atenção; não impedem o
    # rascunho nem entram no status do item). Ficam fora de `bloqueios`; o `resumo` continua contando o status.
    nao_bloqueantes: list[str] = Field(default_factory=list)

    @property
    def pode_emitir(self) -> bool:
        return not self.bloqueios


# ---------------------------------------------------------------------------
# Contexto para condições declarativas
# ---------------------------------------------------------------------------


def _ctx_operacao(op: Operacao, contexto: ContextoRegras, rb: Rulebook) -> tuple[dict[str, Any], list[str]]:
    """Monta o dicionário plano lido pelas condições do YAML e devolve avisos de aproximação."""
    avisos: list[str] = []
    area = contexto.area_total_ha
    if area is None and op.area_financiada_ha is not None:
        if op.area_financiada_ha > 300:
            area = op.area_financiada_ha  # área total ≥ financiada > 300: obrigatoriedade certa
            avisos.append("área total desconhecida; área financiada > 300 ha basta para o MCR 2-7-5-b")
        elif rb.param("PAR-area-total-usa-financiada"):
            area = op.area_financiada_ha
            avisos.append(
                f"área total desconhecida: usando a área financiada ({fmt_br(op.area_financiada_ha)} ha) como aproximação "
                "(PAR-area-total-usa-financiada); se a área total do empreendimento passar de 300 ha, o "
                "sensoriamento remoto é obrigatório (MCR 2-7-5-b)")
    ctx = {
        "operacao.finalidade": op.finalidade,
        "operacao.data_contratacao": op.data_contratacao,
        "operacao.area_total_ha": area,
        "operacao.fonte_recursos": contexto.fonte_recursos,
        "imovel.modulos_fiscais": contexto.modulos_fiscais,
        "imovel.uso_coletivo": contexto.uso_coletivo,
    }
    return ctx, avisos


def _citacao(regra: Regra) -> str:
    return regra.citacao or ""


def _dias(d: date | None, ref: date | None) -> int | None:
    return (d - ref).days if (d is not None and ref is not None) else None


def _situacao_prazo(limite: date | None, ref: date) -> str:
    if limite is None:
        return "indeterminado"
    return "no_prazo" if ref <= limite else "vencido"


# ---------------------------------------------------------------------------
# Regras de data puras (reaproveitadas por planejar, avaliar e testes)
# ---------------------------------------------------------------------------


def limite_dias_apos(ancora: date | None, dias: int) -> date | None:
    """"Até N dias da liberação": o dia N conta (liberação + N dias, inclusive)."""
    return ancora + timedelta(days=dias) if ancora is not None else None


def remoto_obrigatorio(op: Operacao, contexto: ContextoRegras) -> tuple[bool | None, list[str]]:
    """MCR 2-7-5: True (obrigatório), False (não) ou None (indeterminado por falta de dado)."""
    rb = carregar(ID_27)
    ctx, avisos = _ctx_operacao(op, contexto, rb)
    return avaliar_condicao(rb.regra(R_REMOTO).condicao, ctx, rb), avisos


def prodes_inicio(modulos_fiscais: float | None, uso_coletivo: bool = False) -> tuple[date | None, str, str]:
    """MCR 2-9-17/17-A: data de início da verificação Prodes conforme o tamanho do imóvel.

    Devolve (data_inicio, alinea, regra_id). Sem módulos fiscais (e sem uso coletivo): (None, "", regra).
    """
    rb = carregar(ID_29)
    if uso_coletivo:
        r = rb.regra(R_PRODES_COLETIVO)
        return r.efeito["inicio"], "17-A", r.id
    r = rb.regra(R_PRODES_INICIO)
    ctx = {"imovel.modulos_fiscais": modulos_fiscais}
    for faixa in r.efeito["faixas"]:
        if avaliar_condicao(faixa["condicao"], ctx, rb) is True:
            return faixa["inicio"], str(faixa["alinea"]), r.id
    return None, "", r.id


def documento_18_aceito(tipo: str, data_emissao: date | None) -> tuple[str, str]:
    """MCR 2-9-18: devolve ("aceito" | "recusado" | "validacao_humana" | "desconhecido", motivo)."""
    regra = carregar(ID_29).regra(R_PRODES_DOCS)
    spec = regra.efeito["documentos"].get(tipo)
    if spec is None:
        return "desconhecido", f"tipo de documento {tipo!r} não está no MCR 2-9-18"
    alinea = spec["alinea"]
    corte = spec.get("aceito_se_emitido_antes")
    if corte is None:
        return "aceito", f"{tipo} aceito (MCR 2-9-18-{alinea})"
    if data_emissao is None:
        return "validacao_humana", f"{tipo} sem data de emissão: validar (MCR 2-9-18-{alinea})"
    if data_emissao < corte:
        return "aceito", f"{tipo} emitido em {data_emissao.isoformat()}, antes de {corte.isoformat()} (MCR 2-9-18-a)"
    senao = spec.get("senao", "recusado")
    if senao == "validacao_humana":
        return "validacao_humana", (
            f"{tipo} emitida em {data_emissao.isoformat()}: aceitável só se conforme a Res. Conama 510/2025; "
            "conformidade exige validação humana (MCR 2-9-18-a)")
    return "recusado", (
        f"{tipo} emitido em {data_emissao.isoformat()}: só são aceitos os expedidos antes de "
        f"{corte.isoformat()} (MCR 2-9-18-a-I)")


# ---------------------------------------------------------------------------
# Planejamento
# ---------------------------------------------------------------------------


def planejar(op: Operacao, contexto: ContextoRegras, data_referencia: date) -> dict[str, Any]:
    """Recomenda método, lista obrigatoriedades, prazos (com datas) e requisitos de evidência por item."""
    contexto = completar_contexto(contexto, op)
    rb = carregar(ID_27)
    ctx, avisos = _ctx_operacao(op, contexto, rb)
    r5 = rb.regra(R_REMOTO)
    obrig_sr = avaliar_condicao(r5.condicao, ctx, rb)
    obrigatoriedades: list[dict[str, Any]] = [{
        "regra_id": r5.id, "item": r5.item, "descricao": r5.titulo, "aplica": obrig_sr,
        "motivo": _motivo_remoto(ctx, obrig_sr), "citacao": _citacao(r5),
    }]
    pecuaria = any(it.tipo in TIPOS_PECUARIA for it in op.itens)
    if pecuaria and obrig_sr is not False:
        r9 = rb.regra(R_PECUARIA)
        obrigatoriedades.append({
            "regra_id": r9.id, "item": r9.item, "descricao": r9.titulo, "aplica": obrig_sr,
            "motivo": "operação pecuária sujeita ao item 5: sensoriamento deve apurar pastagem e instalações; "
                      "contagem de animais por satélite é facultativa",
            "citacao": _citacao(r9),
        })

    escolha = rb.regra(R_ESCOLHA).efeito
    enquadramento = rb.regra(R_ENQUADRAMENTO).efeito["enquadramento"]
    metodos_por_item: list[dict[str, Any]] = []
    requisitos: list[dict[str, Any]] = []
    prazos: list[dict[str, Any]] = []
    fora_escopo: list[dict[str, Any]] = []
    em_fluxos = _regras_em_fluxos(rb)
    for it in op.itens:
        achado = fluxo_do_item(rb, it, op)
        if achado is None:
            fora_escopo.append({"item_id": it.id, "tipo": it.tipo, "regra_id": R_ESCOPO,
                                "motivo": rb.regra(R_ESCOPO).pedido})
            continue
        nome, fluxo, perfil = achado
        metodo = escolha["por_fluxo"][nome][contexto.prioridade_verificacao]
        m_item = {
            "item_id": it.id, "tipo": it.tipo, "fluxo": nome, "metodo": metodo,
            "enquadramento_normativo": enquadramento[metodo], "regra_id": R_ESCOLHA,
            "prioridade": contexto.prioridade_verificacao,
            "escalonamento": escolha["escalonamento"],
        }
        if perfil is not None:  # 0.4.0: método documentado pela IF para o perfil (MCR 2-7-1-c)
            m_item["perfil"] = _metodo_do_perfil_no_plano(rb, perfil, it, op, contexto)
        metodos_por_item.append(m_item)
        item_ctx = _ctx_item(it, contexto, op)
        for c in fluxo.campos:
            if avaliar_condicao(c.condicao, item_ctx, rb) is False:
                continue
            regra = rb.regra(c.regra)
            requisitos.append(_requisito(f"item:{it.id}:{c.campo}", it.id, regra))
        for regra in rb.regras:  # recomendações não bloqueantes (ex.: marcação dos animais)
            if (not regra.bloqueante and it.tipo in regra.aplica_a and "planejar_metodo" in regra.usado_por
                    and regra.id not in em_fluxos
                    and avaliar_condicao(regra.condicao, item_ctx, rb) is not False):
                requisitos.append(_requisito(f"item:{it.id}:{regra.id}", it.id, regra))
        prazos.extend(_prazos_item(rb, it, contexto, data_referencia))

    for c in rb.campos_laudo:
        regra = rb.regra(c.regra)
        if c.campo == "laudo:sensoriamento_remoto" and obrig_sr is False:
            continue
        if c.campo == "laudo:metadados_sensoriamento" and obrig_sr is False:
            continue
        requisitos.append(_requisito(c.campo, None, regra))

    ordem = escolha["ordem_rigor"]
    if metodos_por_item:
        principal = min((m["metodo"] for m in metodos_por_item), key=ordem.index)
    else:
        principal = "remoto" if obrig_sr else "documental"
        avisos.append("operação sem itens financiados no escopo: método definido só pela obrigatoriedade")
    complementares = ["remoto"] if obrig_sr is True and principal != "remoto" else []
    if obrig_sr is None:
        avisos.append("obrigatoriedade do sensoriamento remoto indeterminada (MCR 2-7-5): informe finalidade, "
                      "data de contratação e área total")

    fontes = [rb.fonte_versao]
    prodes = None
    if ID_29 in contexto.rulebooks or contexto.modulos_fiscais is not None or contexto.uso_coletivo:
        rb29 = carregar(ID_29)
        fontes.append(rb29.fonte_versao)
        prodes = _planejar_prodes(op, contexto, data_referencia)
        obrigatoriedades.append(prodes["obrigatoriedade"])
        if prodes["prazo"]:
            prazos.append(prodes["prazo"])

    return {
        "metodo": principal,  # chave lida pelo condutor (agent/condutor.py::_aplicar_plano)
        "metodo_recomendado": principal,
        "enquadramento_normativo": enquadramento[principal],
        "metodos_complementares": complementares,
        "metodos_por_item": metodos_por_item,
        "obrigatoriedades": obrigatoriedades,
        "prazos": prazos,
        "requisitos": requisitos,
        "fora_do_escopo": fora_escopo,
        "avisos": avisos,
        "data_referencia": data_referencia.isoformat(),
        "rulebooks": fontes,
    }


def _motivo_remoto(ctx: dict[str, Any], obrig: bool | None) -> str:
    fin, dt, area = ctx["operacao.finalidade"], ctx["operacao.data_contratacao"], ctx["operacao.area_total_ha"]
    partes = [f"finalidade={fin or '?'}", f"contratação={dt.isoformat() if dt else '?'}",
              f"área total={'?' if area is None else f'{fmt_br(area)} ha'}"]
    txt = "; ".join(partes)
    if obrig is True:
        return f"obrigatório: {txt} (custeio/investimento, a partir de 01/03/2026 e > 300 ha)"
    if obrig is False:
        return f"não obrigatório: {txt}"
    return f"indeterminado (dado ausente): {txt}"


def normalizar_texto(texto: str | None) -> str:
    """Maiúsculas e sem acento (para ler a descrição do item)."""
    t = unicodedata.normalize("NFKD", texto or "")
    return "".join(ch for ch in t if not unicodedata.combining(ch)).upper()


def eh_aquisicao(it: ItemFinanciado) -> bool | None:
    """Item de aquisição de animais? True ("aquisição"/"compra" na descrição), False (só "manutenção") ou None
    (não dá para dizer: a condição do fluxo fica indeterminada e o campo é mantido, nunca dispensado)."""
    t = normalizar_texto(it.descricao)
    if "AQUISI" in t or "COMPRA" in t:
        return True
    if "MANUTEN" in t:
        return False
    return None


def _ctx_item(it: ItemFinanciado, contexto: ContextoRegras, op: Operacao | None = None) -> dict[str, Any]:
    return {"item.tipo": it.tipo, "item.exige_numero_serie": it.id not in contexto.itens_sem_numero_serie,
            "item.aquisicao": eh_aquisicao(it),
            "operacao.finalidade": op.finalidade if op is not None else None}


def fluxo_do_item(rb: Rulebook, it: ItemFinanciado, op: Operacao) -> tuple[str, Fluxo, Regra | None] | None:
    """Fluxo do item: o de um perfil (regra com `efeito.fluxo`, rulebook 0.4.0) cuja condição for verdadeira
    para a operação e o item; senão, o fluxo do tipo de item que nenhum perfil reserva. Condição de perfil
    indeterminada (ex.: finalidade desconhecida) não escolhe o perfil: vale o fluxo padrão do tipo de
    item. Devolve (nome, fluxo, regra do perfil ou None)."""
    perfis = [r for r in rb.regras if r.efeito.get("fluxo") in rb.fluxos and it.tipo in r.aplica_a]
    ctx = {"operacao.finalidade": op.finalidade, "item.tipo": it.tipo}
    for r in perfis:
        if avaliar_condicao(r.condicao, ctx, rb) is True:
            nome = str(r.efeito["fluxo"])
            return nome, rb.fluxos[nome], r
    reservados = {r.efeito["fluxo"] for r in rb.regras if r.efeito.get("fluxo")}
    for nome, f in rb.fluxos.items():
        if nome not in reservados and it.tipo in f.tipos_item:
            return nome, f, None
    return None


def _regras_em_fluxos(rb: Rulebook) -> set[str]:
    return {c.regra for f in rb.fluxos.values() for c in f.campos}


def _requisito(rid: str, item_id: str | None, regra: Regra) -> dict[str, Any]:
    """Requisito no formato de `Fiscalizacao.requisitos` (chaves também lidas por agent/verificador.py)."""
    return {
        "id": rid, "campo": rid, "item_id": item_id, "regra_id": regra.id, "item_norma": regra.item,
        "tipo": regra.tipo, "origem": regra.origem, "descricao": regra.titulo,
        "evidencias": regra.evidencias, "tipos_evidencia": regra.evidencias,
        "ferramentas": regra.ferramentas, "ferramenta": regra.ferramentas[0] if regra.ferramentas else None,
        "pedido": regra.pedido, "bloqueante": regra.bloqueante, "obrigatorio": regra.bloqueante,
    }


def _prazos_item(rb: Rulebook, it: ItemFinanciado, contexto: ContextoRegras, ref: date) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for regra in rb.regras:
        if regra.tipo != "prazo" or it.tipo not in regra.aplica_a or "planejar_metodo" not in regra.usado_por:
            continue
        if "dias" in regra.efeito:
            inicio = contexto.data_liberacao
            limite = limite_dias_apos(inicio, int(regra.efeito["dias"]))
            desc = f"{regra.titulo} ({regra.efeito['dias']} dias após a liberação, inclusive)"
        else:
            inicio = None
            limite = contexto.cronograma_fim.get(it.id)
            desc = regra.titulo
        out.append({
            "regra_id": regra.id, "item_norma": regra.item, "item_id": it.id, "descricao": desc,
            "data_inicio": inicio.isoformat() if inicio else None,
            "data_limite": limite.isoformat() if limite else None,
            "dias_restantes": _dias(limite, ref), "situacao": _situacao_prazo(limite, ref),
            "responsavel": "mutuario" if regra.id == R_COMPROVANTES_30D else "instituicao_financeira",
            "falta": "" if limite else regra.pedido or "data-base desconhecida",
            "citacao": _citacao(regra),
        })
    return out


def _planejar_prodes(op: Operacao, contexto: ContextoRegras, ref: date) -> dict[str, Any]:
    inicio, alinea, rid = prodes_inicio(contexto.modulos_fiscais, contexto.uso_coletivo)
    regra = carregar(ID_29).regra(rid)
    if inicio is None:
        aplica, motivo = None, "módulos fiscais do imóvel desconhecidos (informe pelo CAR/Incra)"
    elif op.data_contratacao is None:
        aplica, motivo = None, f"exigência a partir de {inicio.isoformat()}; data de contratação desconhecida"
    else:
        aplica = op.data_contratacao >= inicio
        motivo = (f"imóvel na alínea {alinea}: exigência a partir de {inicio.isoformat()}; operação contratada em "
                  f"{op.data_contratacao.isoformat()}")
    obrig = {"regra_id": rid, "item": regra.item, "descricao": regra.titulo, "aplica": aplica, "motivo": motivo,
             "citacao": _citacao(regra)}
    prazo = None
    if inicio is not None:
        prazo = {"regra_id": rid, "item_norma": regra.item, "item_id": None,
                 "descricao": "início da verificação Prodes para a faixa do imóvel", "data_inicio": None,
                 "data_limite": inicio.isoformat(), "dias_restantes": _dias(inicio, ref),
                 "situacao": "vigente" if ref >= inicio else "futuro", "responsavel": "instituicao_financeira",
                 "falta": "", "citacao": _citacao(regra)}
    return {"obrigatoriedade": obrig, "prazo": prazo}


# ---------------------------------------------------------------------------
# Avaliação: vereditos por checagem e agregação em status de campo
# ---------------------------------------------------------------------------

_MAPA_STATUS: dict[str, Veredito] = {"ok": "verificado", "divergente": "divergente",
                                     "indeterminado": "inconclusivo", "erro": "erro"}


@dataclass(frozen=True)
class _Ctx:
    """Tudo que um avaliador pode ler (interno)."""

    rb: Rulebook
    fisc: Fiscalizacao
    contexto: ContextoRegras
    data_fiscalizacao: date | None
    ctx_operacao: dict[str, Any]
    data_referencia: date


def _checagens(fisc: Fiscalizacao, regra: Regra, item_id: str | None, qualquer_item: bool = False,
               rb: Rulebook | None = None) -> list[Checagem]:
    """Checagens que alimentam a regra: mesma ferramenta e mesmo item (ou qualquer item, no nível do laudo).

    Se a checagem aponta explicitamente (`regra_id`) para outra regra conhecida do mesmo rulebook, ela não é
    usada aqui. No nível do laudo (`qualquer_item`), a mesma checagem pode servir a várias regras.
    """
    conhecidas = {r.id for r in rb.regras} if rb is not None else set()
    # Checagem refeita com mais documentos (ex.: 2ª NF-e da mesma compra) lista em `resultado.substitui` as que
    # ela substitui; as substituídas não contam (não são recontagem conflitante, são conciliação parcial).
    substituidas = {s for ch in fisc.checagens for s in (ch.resultado.get("substitui") or [])}
    out = []
    for ch in fisc.checagens:
        if ch.ferramenta not in regra.ferramentas or ch.id in substituidas:
            continue
        if not qualquer_item:
            if ch.item_id != item_id:
                continue
            if ch.regra_id and ch.regra_id != regra.id and ch.regra_id in conhecidas:
                continue
        out.append(ch)
    return out


def _motivo_resultado(ch: Checagem, padrao: str = "") -> str:
    """Motivo legível de uma checagem: `motivo`, ou `motivos` (lista de str/dict), ou `pedidos_recaptura`."""
    r = ch.resultado
    if r.get("motivo"):
        return str(r["motivo"])
    partes = []
    for m in r.get("motivos") or []:
        partes.append(str(m.get("msg") or m.get("codigo") or m) if isinstance(m, dict) else str(m))
    partes += [str(p) for p in r.get("pedidos_recaptura") or []]
    return "; ".join(partes) or padrao or f"{ch.ferramenta}: {ch.status}"


def _veredito_status(ch: Checagem, regra: Regra) -> tuple[Veredito, str]:
    v = _MAPA_STATUS.get(ch.status, "erro")
    exigidos = regra.efeito.get("requisitos") or []
    ausentes = [r for r in (ch.resultado.get("requisitos_ausentes") or []) if not exigidos or r in exigidos]
    motivo = _motivo_resultado(ch)
    if v == "verificado" and ausentes:
        return "incompleto", f"{ch.ferramenta}: faltam requisitos da norma: {', '.join(ausentes)}"
    if v == "inconclusivo" and ausentes:
        return "incompleto", f"{ch.ferramenta}: faltam requisitos: {', '.join(ausentes)}"
    return v, motivo


def _agregar(vereditos: list[tuple[Veredito, str, Checagem]], regra: Regra, rb: Rulebook
             ) -> tuple[str, str, list[Checagem]]:
    """Converte vereditos de checagens em (status do campo, motivo, checagens usadas)."""
    if not vereditos:
        return "pendente", f"evidência ausente: {regra.pedido or regra.titulo}", []
    divergentes = [v for v in vereditos if v[0] == "divergente"]
    verificados = [v for v in vereditos if v[0] == "verificado"]
    if regra.agregacao == "qualquer_divergente":
        if divergentes:
            return "divergente", "; ".join(v[1] for v in divergentes), [v[2] for v in divergentes]
        # rulebook 0.2.0: uma captura inconclusiva (foto duplicada na mesma fiscalização, sem EXIF, GPS impreciso)
        # só é superada por uma captura verificada POSTERIOR; a foto boa anterior não "absolve" a ruim seguinte
        ultima_ok = max((i for i, v in enumerate(vereditos) if v[0] == "verificado"), default=-1)
        abertas = [v for i, v in enumerate(vereditos)
                   if i > ultima_ok and v[0] in ("inconclusivo", "incompleto", "justificavel")]
        if verificados and not abertas:
            return "verificado", "; ".join(v[1] for v in verificados), [v[2] for v in verificados]
        if verificados:
            vereditos = abertas  # só as capturas ainda não superadas contam para pendência e abstenção
    else:
        if divergentes and verificados:
            motivo = (f"checagens conclusivas conflitantes ({len(verificados)} ok, {len(divergentes)} "
                      "divergentes): revisão humana; recontar até passar não resolve")
            return "pendente", motivo, [v[2] for v in divergentes + verificados]
        if divergentes:
            return "divergente", "; ".join(v[1] for v in divergentes), [v[2] for v in divergentes]
        if verificados:
            return "verificado", "; ".join(v[1] for v in verificados), [v[2] for v in verificados]
    incompletos = [v for v in vereditos if v[0] == "incompleto"]
    if incompletos:
        return "pendente", "; ".join(v[1] for v in incompletos) + f" — {regra.pedido}", [v[2] for v in incompletos]
    justificaveis = [v for v in vereditos if v[0] == "justificavel"]
    if justificaveis:  # 0.3.0: medição precisa fora da faixa aceita: pendente (nova captura ou justificativa)
        return "pendente", "; ".join(v[1] for v in justificaveis), [v[2] for v in justificaveis]
    inconclusivos = [v for v in vereditos if v[0] == "inconclusivo"]
    maximo = int(rb.param(PAR_TENTATIVAS)) if PAR_TENTATIVAS in {p.id for p in rb.parametros} else 2
    if len(inconclusivos) >= maximo:
        motivo = (f"{len(inconclusivos)} checagens inconclusivas (máximo {maximo}): o sistema se abstém; "
                  f"decisão humana — último motivo: {inconclusivos[-1][1]}")
        return "abstencao", motivo, [v[2] for v in inconclusivos]
    if inconclusivos:
        motivo = (f"checagem inconclusiva ({len(inconclusivos)}/{maximo}): {inconclusivos[-1][1]} — nova "
                  f"coleta: {regra.pedido}")
        return "pendente", motivo, [v[2] for v in inconclusivos]
    erros = [v for v in vereditos if v[0] == "erro"]
    return ("pendente", f"falha de ferramenta, repetir: {erros[-1][1]}", [v[2] for v in erros])


def aceita_justificativa(campo: CampoLaudo) -> bool:
    """Campo pendente que a justificativa do fiscal resolve (rulebook 0.3.0: foto fora da gleba na faixa entre
    PAR-geofence-perto-m e PAR-geofence-longe-m, com posição medida)."""
    return campo.status == "pendente" and isinstance(campo.valor, dict) and bool(campo.valor.get("aceita_justificativa"))


def _campo(nome: str, regra: Regra, status: str, motivo: str, usados: list[Checagem],
           valor: Any = None, evidencias: list[str] | None = None) -> CampoLaudo:
    evs = list(evidencias or [])
    for ch in usados:
        for e in ch.evidencias:
            if e not in evs:
                evs.append(e)
    return CampoLaudo(campo=nome, valor=valor, status=status, regra_id=regra.id, evidencias=evs,
                      checagens=[ch.id for ch in usados], motivo=motivo)


# -- avaliadores nomeados no YAML ---------------------------------------------
# Assinatura: (nome_campo, regra, item | None, ctx) -> CampoLaudo | None (None = não aplicável)

Avaliador = Callable[[str, Regra, ItemFinanciado | None, _Ctx], CampoLaudo | None]


def _veredito_classe_foto(ch: Checagem, item: ItemFinanciado | None) -> tuple[Veredito, str] | None:
    """MCR-2-7-item16-benfeitorias-conclusao (rulebook 0.3.0): a classificação da foto pelo VLM só prova a
    estrutura se a classe for a do item (cerca para cerca, curral para curral). Outra classe, ou abstenção do VLM,
    é inconclusiva; o VLM nunca dá divergência (não sabe se a obra está inacabada)."""
    if ch.ferramenta != "classificar_foto" or item is None or ch.status == "erro":
        return None
    r = ch.resultado
    if "classe" not in r and "classe_majoritaria" not in r:
        return None
    classe = r.get("classe")
    if classe == item.tipo and ch.status == "ok":
        return "verificado", f"a foto mostra {item.tipo} (VLM, concordância {fmt_br(r.get('concordancia'))})"
    vista = classe or r.get("classe_majoritaria") or "indeterminado"
    return "inconclusivo", (f"a foto não mostra a estrutura do item ({item.tipo}): VLM viu {vista}"
                            f"{' (abstenção)' if r.get('abstencao') else ''}; foto da estrutura inteira")


def _av_status_checagem(nome: str, regra: Regra, item: ItemFinanciado | None, c: _Ctx) -> CampoLaudo:
    chs = _checagens(c.fisc, regra, item.id if item else None, rb=c.rb)
    vereditos = [(*(_veredito_classe_foto(ch, item) or _veredito_status(ch, regra)), ch) for ch in chs]
    status, motivo, usados = _agregar(vereditos, regra, c.rb)
    return _campo(nome, regra, status, motivo, usados)


def _av_contagem_intervalo(nome: str, regra: Regra, item: ItemFinanciado | None, c: _Ctx) -> CampoLaudo:
    assert item is not None
    if item.quantidade is None or item.quantidade <= 0:
        return _campo(nome, regra, "pendente", "quantidade financiada desconhecida no projeto/Sicor", [])
    tol_pct = Decimal(str(c.rb.param("PAR-contagem-tolerancia-pct")))
    q = Decimal(str(item.quantidade))
    limite = q * (Decimal(100) - tol_pct) / Decimal(100)
    vereditos: list[tuple[Veredito, str, Checagem]] = []
    ultimo: dict[str, Any] = {}
    for ch in _checagens(c.fisc, regra, item.id, rb=c.rb):
        if ch.status == "erro":
            vereditos.append(("erro", _motivo_resultado(ch, "erro na contagem"), ch))
            continue
        if ch.status == "indeterminado" or ch.resultado.get("status") == "indeterminado":
            motivo = _motivo_resultado(ch, "contagem abstida pela ferramenta")
            vereditos.append(("inconclusivo", f"contagem abstida: {motivo}", ch))
            continue
        n = ch.resultado.get("contagem")
        intervalo = ch.resultado.get("intervalo")
        if n is None and not intervalo:
            vereditos.append(("erro", "resultado da contagem sem 'contagem' nem 'intervalo'", ch))
            continue
        lo, hi = (intervalo if intervalo else (n, n))
        lo_d, hi_d = Decimal(str(lo)), Decimal(str(hi))
        ultimo = {"contagem": n, "intervalo": [lo, hi]}
        faixa = (f"contagem {fmt_br(n)} [{fmt_br(lo)}, {fmt_br(hi)}] vs financiado {fmt_br(item.quantidade)} "
                 f"(limite {fmt_br(float(limite))})")
        if lo_d >= limite:
            vereditos.append(("verificado", f"{faixa}: dentro da tolerância", ch))
        elif hi_d < limite:
            vereditos.append(("divergente", f"{faixa}: abaixo do limite mesmo no extremo superior", ch))
        else:
            vereditos.append(("inconclusivo", f"{faixa}: intervalo cruza o limite", ch))
    status, motivo, usados = _agregar(vereditos, regra, c.rb)
    valor = {"financiado": item.quantidade, "limite_inferior": float(limite), "tolerancia_pct": float(tol_pct),
             **ultimo}
    return _campo(nome, regra, status, motivo, usados, valor=valor)


def _posicao_geofence(ch: Checagem) -> str:
    """Posição do ponto: `resultado.posicao` (geofence ≥ 0.1.1); `resultado.status` legado (dentro/fora);
    senão, deduzida do status comum da checagem (ok → dentro, divergente → fora)."""
    r = ch.resultado
    for chave in ("posicao", "status"):
        if r.get(chave) in ("dentro", "fora", "indeterminado"):
            return str(r[chave])
    return {"ok": "dentro", "divergente": "fora"}.get(ch.status, "indeterminado")


def _av_geofence(nome: str, regra: Regra, item: ItemFinanciado | None, c: _Ctx) -> CampoLaudo:
    assert item is not None
    perto = float(c.rb.param("PAR-geofence-perto-m"))
    longe = float(c.rb.param("PAR-geofence-longe-m"))
    vereditos: list[tuple[Veredito, str, Checagem]] = []
    for ch in _checagens(c.fisc, regra, item.id, rb=c.rb):
        if ch.status == "erro":
            vereditos.append(("erro", _motivo_resultado(ch, "erro no geofence"), ch))
            continue
        gs = _posicao_geofence(ch)
        d = ch.resultado.get("distancia_borda_m")
        if gs == "dentro":
            vereditos.append(("verificado", "foto dentro da gleba", ch))
        elif gs == "fora" and d is not None:
            d = float(d)
            if d <= perto:
                vereditos.append(("verificado", f"foto a {fmt_br(d)} m da borda (≤ {perto:g} m)", ch))
            elif d <= longe:
                # 0.3.0: posição medida (não é GPS impreciso): duas capturas assim não viram abstenção
                motivo = (f"foto fora da gleba, a {fmt_br(d)} m da borda (entre {perto:g} e {longe:g} m): "
                          "refaça a foto de dentro da gleba ou registre a justificativa do fiscal (ex.: curral na "
                          "sede)")
                vereditos.append(("justificavel", motivo, ch))
            else:
                vereditos.append(("divergente", f"foto a {fmt_br(d)} m da borda (> {longe:g} m)", ch))
        else:
            motivo = ch.resultado.get("motivo") or "localização indeterminada (precisão do GPS)"
            vereditos.append(("inconclusivo", str(motivo), ch))
    status, motivo, usados = _agregar(vereditos, regra, c.rb)
    valor = None
    if status == "pendente" and usados and all(v[0] == "justificavel" for v in vereditos if v[2] in usados):
        valor = {"faixa": "intermediaria", "aceita_justificativa": True,
                 "distancias_m": [round(float(ch.resultado.get("distancia_borda_m") or 0), 1) for ch in usados]}
    return _campo(nome, regra, status, motivo, usados, valor=valor)


def _data_item(c: _Ctx, item: ItemFinanciado | None) -> tuple[date | None, str]:
    """Data da ação de fiscalização para o item: a informada no contexto ou a primeira captura de campo
    (foto/vídeo/áudio) ligada às checagens do item. Documentos não contam (a data deles é de emissão)."""
    if c.contexto.data_fiscalizacao is not None:
        return c.contexto.data_fiscalizacao, "informada"
    if item is None:
        return c.data_fiscalizacao, "primeira captura de campo"
    ids = {e for ch in c.fisc.checagens if ch.item_id == item.id for e in ch.evidencias}
    datas = [_data_local(e.capturada_em) for e in c.fisc.evidencias
             if e.id in ids and e.tipo in TIPOS_EVIDENCIA_CAMPO and e.capturada_em is not None]
    return (min(datas), "primeira captura de campo do item") if datas else (None, "")


def _prazo(nome: str, regra: Regra, item: ItemFinanciado | None, c: _Ctx, limite: date,
           valor: dict[str, Any], descricao_limite: str) -> CampoLaudo:
    df, origem = _data_item(c, item)
    valor = {**valor, "data_limite": limite.isoformat(), "data_fiscalizacao": df.isoformat() if df else None,
             "origem_data_fiscalizacao": origem or None}
    if df is None:
        if c.data_referencia > limite:
            return _campo(nome, regra, "pendente",
                          f"prazo ({descricao_limite}) vencido em {limite.isoformat()} sem fiscalização registrada "
                          "do item — registrar a data da ação ou justificar", [], valor=valor)
        return _campo(nome, regra, "pendente",
                      f"sem fiscalização registrada do item; prazo até {limite.isoformat()} ({descricao_limite})", [],
                      valor=valor)
    if df <= limite:
        return _campo(nome, regra, "verificado",
                      f"fiscalização em {df.isoformat()}, dentro do prazo ({descricao_limite})", [], valor=valor)
    return _campo(nome, regra, "divergente",
                  f"fiscalização em {df.isoformat()}, depois do prazo de {limite.isoformat()} ({descricao_limite}; "
                  f"{regra.item}) — exige justificativa humana", [], valor=valor)


def _av_prazo_dias_apos(nome: str, regra: Regra, item: ItemFinanciado | None, c: _Ctx) -> CampoLaudo:
    dias = int(regra.efeito["dias"])
    ancora = c.contexto.data_liberacao
    if ancora is None:
        return _campo(nome, regra, "pendente", f"data de liberação desconhecida — {regra.pedido}", [])
    limite = limite_dias_apos(ancora, dias)
    assert limite is not None
    return _prazo(nome, regra, item, c, limite, {"data_liberacao": ancora.isoformat(), "dias": dias},
                  f"até {dias} dias da liberação em {ancora.isoformat()}")


def _av_prazo_ate_data(nome: str, regra: Regra, item: ItemFinanciado | None, c: _Ctx) -> CampoLaudo:
    assert item is not None
    limite = c.contexto.cronograma_fim.get(item.id)
    if limite is None:
        return _campo(nome, regra, "pendente", f"término do cronograma desconhecido — {regra.pedido}", [])
    return _prazo(nome, regra, item, c, limite, {"cronograma_fim": limite.isoformat()},
                  "até o término do cronograma do projeto")


def _av_metodo_registrado(nome: str, regra: Regra, item: ItemFinanciado | None, c: _Ctx) -> CampoLaudo:
    m = c.fisc.metodo
    if not m:
        return _campo(nome, regra, "pendente", regra.pedido, [])
    enq = c.rb.regra(R_ENQUADRAMENTO).efeito["enquadramento"]
    return _campo(nome, regra, "verificado", f"método registrado: {m}", [],
                  valor={"metodo": m, "enquadramento_normativo": enq.get(m, m)})


def _av_declaracao_independencia(nome: str, regra: Regra, item: ItemFinanciado | None, c: _Ctx) -> CampoLaudo:
    assunto = regra.efeito.get("assunto", "independencia_fiscal")
    decl = [e for e in c.fisc.evidencias if e.tipo == "declaracao" and e.meta.get("assunto") == assunto]
    if not decl:
        return _campo(nome, regra, "pendente", regra.pedido, [])
    ids = [e.id for e in decl]
    if any(e.meta.get("conflito") is True for e in decl):
        return _campo(nome, regra, "divergente", "declaração registra conflito: fiscal vedado (MCR 2-7-15)", [],
                      evidencias=ids)
    return _campo(nome, regra, "verificado", "declaração de independência registrada", [], evidencias=ids)


def _av_sensoriamento_obrigatorio(nome: str, regra: Regra, item: ItemFinanciado | None, c: _Ctx
                                  ) -> CampoLaudo | None:
    obrig = avaliar_condicao(regra.condicao, c.ctx_operacao, c.rb)
    if obrig is False:
        return None
    if obrig is None:
        return _campo(nome, regra, "pendente",
                      "obrigatoriedade do sensoriamento remoto indeterminada: informe finalidade, data de "
                      "contratação e área total (MCR 2-7-5)", [])
    chs = _checagens(c.fisc, regra, None, qualquer_item=True)
    vereditos = [(*_veredito_status(ch, regra), ch) for ch in chs]
    status, motivo, usados = _agregar(vereditos, regra, c.rb)
    if status in ("pendente", "abstencao") and any(v[0] == "inconclusivo" for v in vereditos):
        motivo += " — sensoriamento inconclusivo: complementar com método documental ou presencial (MCR 2-7-10)"
    return _campo(nome, regra, status, motivo, usados, valor={"obrigatorio": True})


def _metadados_de(ch: Checagem, blocos: list[str]) -> dict[str, Any]:
    """Junta os blocos de metadados conhecidos (ex.: `metadados_laudo` do serie_ndvi) ao nível de cima."""
    md = dict(ch.resultado)
    for b in blocos:
        if isinstance(ch.resultado.get(b), dict):
            md.update(ch.resultado[b])
    return md


def _av_metadados_sensoriamento(nome: str, regra: Regra, item: ItemFinanciado | None, c: _Ctx
                                ) -> CampoLaudo | None:
    chs = [ch for ch in _checagens(c.fisc, regra, None, qualquer_item=True) if ch.status != "erro"]
    if not chs:
        return None  # sem sensoriamento usado no laudo: item 4-b não se aplica
    exigidos: dict[str, dict[str, Any]] = regra.efeito["campos_exigidos"]
    blocos = list(regra.efeito.get("blocos_metadados") or [])
    faltas = []
    for ch in chs:
        md = _metadados_de(ch, blocos)
        ausentes = [k for k, spec in exigidos.items()
                    if all(md.get(a) in (None, "", [], {}) for a in spec.get("aceita", [k]))]
        if ausentes:
            faltas.append(f"{ch.ferramenta} {ch.id}: "
                          + ", ".join(f"{k} (MCR 2-7-{exigidos[k]['inciso']})" for k in ausentes))
    if faltas:
        return _campo(nome, regra, "pendente", "metadados do MCR 2-7-4-b ausentes — " + "; ".join(faltas), chs)
    return _campo(nome, regra, "verificado", f"{len(chs)} checagem(ns) de sensoriamento com os metadados do item 4-b",
                  chs)


def _av_escopo(nome: str, regra: Regra, item: ItemFinanciado | None, c: _Ctx) -> CampoLaudo:
    tipo = item.tipo if item else "?"
    return _campo(nome, regra, "pendente", f"item do tipo {tipo!r} sem fluxo no rulebook — {regra.pedido}", [])


def _av_prodes_status(nome: str, regra: Regra, item: ItemFinanciado | None, c: _Ctx) -> CampoLaudo | None:
    op = c.fisc.operacao
    inicio, alinea, rid = prodes_inicio(c.contexto.modulos_fiscais, c.contexto.uso_coletivo)
    if inicio is None:
        return _campo(nome, regra, "pendente",
                      "módulos fiscais do imóvel desconhecidos: não dá para saber se o MCR 2-9-17 já vale", [])
    if op.data_contratacao is None:
        return _campo(nome, regra, "pendente", "data de contratação desconhecida (MCR 2-9-17)", [])
    if op.data_contratacao < inicio:
        return None
    chs = _checagens(c.fisc, regra, None, qualquer_item=True)
    vereditos = [(*_veredito_status(ch, regra), ch) for ch in chs]
    status, motivo, usados = _agregar(vereditos, regra, c.rb)
    valor: dict[str, Any] = {"inicio_exigencia": inicio.isoformat(), "alinea": alinea, "regra_inicio": rid}
    if status != "divergente":
        return _campo(nome, regra, status, motivo, usados, valor=valor)
    # Supressão constatada: o MCR 2-9-18 condiciona a concessão a um documento de regularização.
    rb29 = carregar(ID_29)
    fonte = c.contexto.fonte_recursos
    if fonte in ("livres", "nao_controlados"):
        return _campo(nome, regra, "verificado",
                      f"supressão constatada; recursos {fonte}: o MCR 2-9-18 não condiciona a concessão", usados,
                      valor=valor)
    docs = [e for e in c.fisc.evidencias if e.tipo == "documento" and e.meta.get("tipo_documento")]
    res = []
    for e in docs:
        dt = e.meta.get("data_emissao")
        dte = date.fromisoformat(dt) if isinstance(dt, str) else dt
        res.append((*documento_18_aceito(str(e.meta["tipo_documento"]), dte), e.id))
    valor["documentos"] = [{"evidencia": r[2], "situacao": r[0], "motivo": r[1]} for r in res]
    regra18 = rb29.regra(R_PRODES_DOCS)
    for situacao, novo_status in (("aceito", "verificado"), ("validacao_humana", "pendente"),
                                  ("recusado", "divergente")):
        achados = [r for r in res if r[0] == situacao]
        if achados:
            return _campo(nome, regra, novo_status, f"supressão constatada; {achados[0][1]}", usados, valor=valor,
                          evidencias=[r[2] for r in achados])
    return _campo(nome, regra, "pendente", f"supressão constatada sem documento — {regra18.pedido}", usados,
                  valor=valor)


def _area_lotacao(op: Operacao) -> tuple[float | None, str]:
    """Área que recebe o lote: a informada; senão a financiada (proporcional ao crédito, não é o pasto);
    senão a total do empreendimento."""
    areas = (("area_informada_ha", op.area_informada_ha), ("area_financiada_ha", op.area_financiada_ha),
             ("area_total_ha", op.area_total_ha))
    for nome, v in areas:
        if v is not None and v > 0:
            return float(v), nome
    return None, ""


def _av_lotacao_sinal(nome: str, regra: Regra, item: ItemFinanciado | None, c: _Ctx) -> CampoLaudo:
    """OP-custeio-lotacao (0.4.0): cabeças do lote ÷ área contra o parâmetro. Usa a última `checar_lotacao`
    ok da operação (ou do item); sem ela, calcula com a quantidade dos itens de bovinos e a área da operação.
    Nunca diverge: acima do parâmetro, ou sem área, o campo fica pendente (a regra não é bloqueante)."""
    assert item is not None
    pid = regra.parametros[0]
    limite = float(c.rb.param(pid))
    op = c.fisc.operacao
    chs = [ch for ch in _checagens(c.fisc, regra, None, qualquer_item=True)
           if ch.status == "ok" and ch.item_id in (None, item.id)
           and ch.resultado.get("lotacao_cab_ha") is not None]
    usados: list[Checagem] = []
    if chs:
        r = chs[-1].resultado
        usados = [chs[-1]]
        if r.get("classe") == "nao_aplicavel_confinamento":
            motivo = "engorda em confinamento: lotação por área não se aplica"
            return _campo(nome, regra, "verificado", motivo, usados,
                          valor={"fonte": "checar_lotacao", "limite_cab_ha": limite})
        lot, fonte = float(r["lotacao_cab_ha"]), "checar_lotacao"
        cab, area, campo_area = r.get("cabecas"), r.get("area_ha"), "checar_lotacao"
    else:
        cab = sum(float(i.quantidade) for i in op.itens if i.tipo == "bovinos" and i.quantidade)
        area, campo_area = _area_lotacao(op)
        if not cab or area is None:
            return _campo(nome, regra, "pendente",
                          f"lotação indeterminada (sem quantidade ou sem área) — {regra.pedido}", [],
                          valor={"limite_cab_ha": limite, "fonte": "operacao"})
        lot, fonte = cab / area, f"operacao.{campo_area}"
    valor = {"lotacao_cab_ha": round(lot, 2), "limite_cab_ha": limite, "cabecas": cab, "area_ha": area,
             "fonte": fonte, "parametro": pid}
    aviso = ""
    if campo_area == "area_financiada_ha":
        aviso = " (área financiada: proporcional ao crédito, não é o pasto)"
    faixa = f"lotação de {fmt_br(round(lot, 2))} cab/ha"
    if lot > limite:
        return _campo(nome, regra, "pendente",
                      f"{faixa} acima de {fmt_br(limite)} ({pid}){aviso}: ponto de atenção, não "
                      f"divergência — {regra.pedido}", usados, valor=valor)
    return _campo(nome, regra, "verificado", f"{faixa}, até {fmt_br(limite)} ({pid}){aviso}", usados,
                  valor=valor)


def _av_metodo_documentado(nome: str, regra: Regra, item: ItemFinanciado | None, c: _Ctx) -> CampoLaudo:
    """MCR-2-7-item1-metodo-documentado-if (0.4.0): registra no laudo o método que a IF documentou para o
    perfil (perfil, versão e sha256 do rulebook, componentes). Pendente (não bloqueante) se faltar componente
    no perfil ou se a fiscalização ainda não registrou o método de campo."""
    assert item is not None
    perfil = c.rb.regra(str(regra.efeito["perfil"]))
    metodo = perfil.efeito.get("metodo") or {}
    exigidos, nao_aplicaveis = _componentes_do_item(regra, item, c)
    valor = {"perfil": perfil.id, "rulebook": c.rb.fonte_versao, "rulebook_sha256": c.rb.sha256,
             "componentes": {k: metodo.get(k) for k in exigidos}, "metodo_campo": c.fisc.metodo,
             "citacao": regra.citacao}
    nota = ""
    if nao_aplicaveis:  # ex.: item só de manutenção, sem NF-e nem GTA de compra (condição do fluxo)
        valor["nao_aplicaveis"] = nao_aplicaveis
        nota = f" ({', '.join(nao_aplicaveis)} não se aplicam ao item: condição do fluxo)"
    faltam = [k for k in exigidos if not metodo.get(k)]
    if faltam:
        return _campo(nome, regra, "pendente",
                      f"perfil {perfil.id} sem método documentado para: {', '.join(faltam)}", [], valor=valor)
    if not c.fisc.metodo:
        return _campo(nome, regra, "pendente", f"perfil {perfil.id} documentado; {regra.pedido}", [],
                      valor=valor)
    return _campo(nome, regra, "verificado",
                  f"método documentado pela IF: {perfil.id} ({c.rb.fonte_versao}), com "
                  f"{', '.join(exigidos)}{nota}; método de campo {c.fisc.metodo} ({regra.item})", [],
                  valor=valor)


def _componentes_do_item(regra: Regra, item: ItemFinanciado, c: _Ctx) -> tuple[list[str], list[str]]:
    return componentes_aplicaveis(c.rb, regra, item, c.fisc.operacao, c.contexto)


def componentes_aplicaveis(rb: Rulebook, regra: Regra, item: ItemFinanciado, op: Operacao,
                           contexto: ContextoRegras) -> tuple[list[str], list[str]]:
    """(componentes do método que se aplicam ao item, os que não se aplicam). Um componente não se aplica
    quando o campo do fluxo que o executa (`efeito.campos`) tem condição falsa para o item (ex.: item só de
    manutenção, sem NF-e nem GTA de compra). Condição indeterminada mantém o componente (nunca dispensa)."""
    exigidos = list(regra.efeito.get("componentes") or [])
    campos = regra.efeito.get("campos") or {}
    achado = fluxo_do_item(rb, item, op)
    if achado is None or not campos:
        return exigidos, []
    condicoes = {cf.campo: cf.condicao for cf in achado[1].campos}
    ctx = _ctx_item(item, contexto, op)
    fora = [k for k in exigidos if campos.get(k) in condicoes
            and avaliar_condicao(condicoes[campos[k]], ctx, rb) is False]
    return [k for k in exigidos if k not in fora], fora


def _metodo_do_perfil_no_plano(rb: Rulebook, perfil: Regra, item: ItemFinanciado, op: Operacao,
                               contexto: ContextoRegras) -> dict[str, Any]:
    """Método do perfil no plano, só com os componentes que se aplicam ao item (rulebook 0.5.0): item só de
    manutenção não lista NF-e nem GTA de compra (vem a nota `manutencao`); item de aquisição, ou que não dá para
    classificar, lista NF-e e GTA e não traz a nota de manutenção. Mesma regra do campo `metodo_if` do laudo."""
    metodo = perfil.efeito.get("metodo") or {}
    reg = next((r for r in rb.regras if r.avaliador == "metodo_documentado"
                and r.efeito.get("perfil") == perfil.id), None)
    aplicaveis, fora = (componentes_aplicaveis(rb, reg, item, op, contexto) if reg is not None
                        else ([k for k in metodo if k != "manutencao"], []))
    metodo_if = {k: metodo[k] for k in aplicaveis if k in metodo}
    if fora and "manutencao" in metodo:
        metodo_if["manutencao"] = metodo["manutencao"]
    return {"regra_id": perfil.id, "titulo": perfil.titulo, "metodo_if": metodo_if,
            "componentes": aplicaveis, "nao_aplicaveis": fora}


AVALIADORES: dict[str, Avaliador] = {
    "lotacao_sinal": _av_lotacao_sinal,
    "metodo_documentado": _av_metodo_documentado,
    "status_checagem": _av_status_checagem,
    "contagem_intervalo": _av_contagem_intervalo,
    "geofence_distancia": _av_geofence,
    "prazo_dias_apos": _av_prazo_dias_apos,
    "prazo_ate_data": _av_prazo_ate_data,
    "metodo_registrado": _av_metodo_registrado,
    "declaracao_independencia": _av_declaracao_independencia,
    "sensoriamento_obrigatorio": _av_sensoriamento_obrigatorio,
    "metadados_sensoriamento": _av_metadados_sensoriamento,
    "escopo": _av_escopo,
    "prodes_status": _av_prodes_status,
}

# Avaliadores aplicados fora do dicionário: agregação (depende dos campos do item) e início Prodes
# (função `prodes_inicio`, usada por planejar e pelo avaliador `prodes_status`).
AVALIADORES_INTERNOS = {"agregacao_item", "prodes_inicio"}

_PRECEDENCIA = ["divergente", "pendente", "abstencao", "verificado"]


def _bloqueante(regra_id: str, rb: Rulebook) -> bool:
    try:
        return rb.regra(regra_id).bloqueante
    except KeyError:
        return True


def _agregar_item(nome: str, componentes: list[CampoLaudo], rb: Rulebook) -> CampoLaudo:
    regra = rb.regra(R_AGREGACAO)
    precedencia = regra.efeito.get("precedencia", _PRECEDENCIA)
    # 0.4.0: campo de regra não bloqueante (lotação, método documentado) aparece no valor, mas não decide o
    # status do item (sinal não é achado). Os fluxos anteriores à 0.4.0 só têm campos bloqueantes.
    decisivos = [c for c in componentes if _bloqueante(c.regra_id, rb)] or componentes
    status = min((c.status for c in decisivos), key=precedencia.index)
    piores = [c.campo.rsplit(":", 1)[-1] for c in decisivos if c.status == status]
    ids_decisivos = {id(c) for c in decisivos}
    atencao = [f"{c.campo.rsplit(':', 1)[-1]} ({c.status})" for c in componentes
               if id(c) not in ids_decisivos and c.status != "verificado"]
    if status == "verificado":
        motivo = ("todas as exigências verificadas" if not atencao else
                  "exigências bloqueantes verificadas")
    else:
        motivo = f"{status}: {', '.join(piores)}"
    if atencao:  # 0.4.0: o item não fica "todo verificado" com sinal pendente, mesmo sem bloquear
        motivo += f"; ponto de atenção não bloqueante: {', '.join(atencao)}"
    evs: list[str] = []
    chs: list[str] = []
    for c in componentes:
        evs += [e for e in c.evidencias if e not in evs]
        chs += [x for x in c.checagens if x not in chs]
    return CampoLaudo(campo=nome, valor={c.campo.rsplit(":", 1)[-1]: c.status for c in componentes},
                      status=status, regra_id=regra.id, evidencias=evs, checagens=chs, motivo=motivo)


def _data_local(dt: datetime) -> date:
    """Dia civil em America/Sao_Paulo (datetime ingênuo é tratado como já local)."""
    return dt.astimezone(FUSO).date() if dt.tzinfo is not None else dt.date()


def _data_fiscalizacao(fisc: Fiscalizacao, contexto: ContextoRegras) -> date | None:
    if contexto.data_fiscalizacao is not None:
        return contexto.data_fiscalizacao
    datas = [_data_local(e.capturada_em) for e in fisc.evidencias
             if e.tipo in TIPOS_EVIDENCIA_CAMPO and e.capturada_em is not None]
    return min(datas) if datas else None


def avaliar(fisc: Fiscalizacao, contexto: ContextoRegras, data_referencia: date) -> ResultadoAvaliacao:
    """Aplica os rulebooks à fiscalização. Função pura: não altera `fisc`."""
    contexto = completar_contexto(contexto, fisc.operacao, fisc)
    rb = carregar(ID_27)
    ctx_op, avisos = _ctx_operacao(fisc.operacao, contexto, rb)
    df = _data_fiscalizacao(fisc, contexto)
    c = _Ctx(rb=rb, fisc=fisc, contexto=contexto, data_fiscalizacao=df, ctx_operacao=ctx_op,
             data_referencia=data_referencia)
    campos: dict[str, CampoLaudo] = {}
    agregados: set[str] = set()
    nao_aplicaveis: list[dict[str, Any]] = []
    alertas: list[str] = []

    for it in fisc.operacao.itens:
        achado = fluxo_do_item(rb, it, fisc.operacao)
        if achado is None:
            nome = f"item:{it.id}"
            campos[nome] = _av_escopo(nome, rb.regra(R_ESCOPO), it, c)
            continue
        _, fluxo, _perfil = achado
        item_ctx = _ctx_item(it, contexto, fisc.operacao)
        componentes = []
        for cf in fluxo.campos:
            nome = f"item:{it.id}:{cf.campo}"
            regra = rb.regra(cf.regra)
            if avaliar_condicao(cf.condicao, item_ctx, rb) is False:
                nao_aplicaveis.append({"campo": nome, "regra_id": regra.id, "motivo": "condição do fluxo não atendida"})
                continue
            campo = AVALIADORES[regra.avaliador](nome, regra, it, c) if regra.avaliador else None
            if campo is not None:
                campos[nome] = campo
                componentes.append(campo)
        if componentes:
            nome = f"item:{it.id}"
            campos[nome] = _agregar_item(nome, componentes, rb)
            agregados.add(nome)
        alertas += _alerta_comprovantes(rb, it, componentes, contexto, data_referencia)

    for cf in rb.campos_laudo:
        regra = rb.regra(cf.regra)
        campo = AVALIADORES[regra.avaliador](cf.campo, regra, None, c) if regra.avaliador else None
        if campo is None:
            nao_aplicaveis.append({"campo": cf.campo, "regra_id": regra.id, "motivo": "não se aplica a esta operação"})
        else:
            campos[cf.campo] = campo

    fontes = [rb.fonte_versao]
    if ID_29 in contexto.rulebooks:
        rb29 = carregar(ID_29)
        fontes.append(rb29.fonte_versao)
        c29 = _Ctx(rb=rb29, fisc=fisc, contexto=contexto, data_fiscalizacao=df, ctx_operacao=ctx_op,
                   data_referencia=data_referencia)
        if contexto.fonte_recursos is None and rb29.param("PAR-prodes-fonte-recursos-desconhecida-aplica"):
            avisos.append("fonte de recursos desconhecida: MCR 2-9-18 tratado como aplicável")
        for cf in rb29.campos_laudo:
            regra = rb29.regra(cf.regra)
            campo = AVALIADORES[regra.avaliador](cf.campo, regra, None, c29) if regra.avaliador else None
            if campo is None:
                nao_aplicaveis.append({"campo": cf.campo, "regra_id": regra.id,
                                       "motivo": "exigência do MCR 2-9-17 ainda não vigente para esta operação"})
            else:
                campos[cf.campo] = campo

    # Justificativa humana registrada antes sobrevive à reavaliação.
    for nome, campo in campos.items():
        anterior = fisc.campos.get(nome)
        if anterior is not None and anterior.justificativa_humana:
            campo.justificativa_humana = anterior.justificativa_humana

    bloqueios = []
    for nome, campo in campos.items():
        if nome in agregados:
            continue
        try:
            _, regra = buscar_regra(campo.regra_id)
        except KeyError:
            regra = None
        if regra is not None and not regra.bloqueante:
            continue
        if campo.status == "pendente" and aceita_justificativa(campo):
            if not campo.justificativa_humana:  # 0.3.0: nova captura OU justificativa do fiscal resolve
                bloqueios.append(Bloqueio(regra_id=campo.regra_id, campo=nome, status="pendente",
                                          falta=f"nova captura ou justificativa do fiscal ({campo.motivo})"))
        elif campo.status == "pendente":
            bloqueios.append(Bloqueio(regra_id=campo.regra_id, campo=nome, status="pendente", falta=campo.motivo))
        elif campo.status == "abstencao" and not campo.justificativa_humana:
            bloqueios.append(Bloqueio(regra_id=campo.regra_id, campo=nome, status="abstencao",
                                      falta=f"justificativa humana para a abstenção ({campo.motivo})"))

    nao_bloqueantes = _marcar_nao_bloqueantes(campos, agregados)

    resumo: dict[str, int] = {s: 0 for s in _PRECEDENCIA}
    for nome, campo in campos.items():
        if nome not in agregados:
            resumo[campo.status] += 1
    return ResultadoAvaliacao(campos=campos, bloqueios=bloqueios, alertas=alertas, avisos=avisos,
                              nao_aplicaveis=nao_aplicaveis, resumo=resumo, data_fiscalizacao=df,
                              fonte_versao="+".join(fontes), nao_bloqueantes=nao_bloqueantes)


def _marcar_nao_bloqueantes(campos: dict[str, CampoLaudo], agregados: set[str]) -> list[str]:
    """Rulebook 0.5.0: campo de regra **não bloqueante** que não ficou verificado
    (lotação acima do parâmetro, método do perfil sem o método de campo) continua `pendente` (o vocabulário é o
    do contrato e a pendência é real), mas aparece diferente do pendente que bloqueia: ressalva
    `RESSALVA_NAO_BLOQUEANTE`, motivo que termina dizendo que não bloqueia e a lista `nao_bloqueantes` do
    resultado, separada de `bloqueios`. Devolve essa lista."""
    saida = []
    for nome, campo in campos.items():
        if nome in agregados or campo.status == "verificado":
            continue
        try:
            _, regra = buscar_regra(campo.regra_id)
        except KeyError:
            continue
        if regra.bloqueante:
            continue
        saida.append(nome)
        if RESSALVA_NAO_BLOQUEANTE not in campo.ressalvas:
            campo.ressalvas.append(RESSALVA_NAO_BLOQUEANTE)
        if "não bloqueia" not in campo.motivo:
            campo.motivo = f"{campo.motivo} (não bloqueia o laudo)"
    return saida


def _alerta_comprovantes(rb: Rulebook, it: ItemFinanciado, componentes: list[CampoLaudo],
                         contexto: ContextoRegras, ref: date) -> list[str]:
    """MCR 2-5-10-b: prazo do mutuário (30 dias) vencido e comprovante ainda sem checagem."""
    regra = rb.regra(R_COMPROVANTES_30D)
    if it.tipo not in regra.aplica_a or contexto.data_liberacao is None:
        return []
    limite = limite_dias_apos(contexto.data_liberacao, int(regra.efeito["dias"]))
    sem_nfe = any(cp.campo.endswith((":comprovante_nfe", ":nfe")) and cp.status == "pendente" and not cp.checagens
                  for cp in componentes)
    if limite is not None and ref > limite and sem_nfe:
        msg = (f"item {it.id}: comprovante de aquisição não apresentado e prazo do mutuário vencido em "
               f"{limite.isoformat()} ({regra.item})")
        return [msg]
    return []


# ---------------------------------------------------------------------------
# Explicação
# ---------------------------------------------------------------------------


def explicar(regra_id: str) -> dict[str, Any] | None:
    """Citação, fonte e justificativa de uma regra (ou parâmetro). None se o id não existir."""
    for rb in todos():
        meta = {"id": rb.id, "versao": rb.versao, "sha256": rb.sha256, "norma_base": rb.norma_base,
                "texto_normativo": rb.texto_normativo, "estado_revisao": rb.revisao.estado,
                "fontes": [f.model_dump(mode="json") for f in rb.fontes]}
        for r in rb.regras:
            if r.id == regra_id:
                params = [p.model_dump(mode="json") for p in rb.parametros if p.id in r.parametros]
                return {"tipo": "regra", "regra": r.model_dump(mode="json"), "parametros": params, "rulebook": meta,
                        "executada": bool(r.avaliador) or bool(r.usado_por)}
        for p in rb.parametros:
            if p.id == regra_id:
                usado = [r.id for r in rb.regras if p.id in r.parametros]
                return {"tipo": "parametro", "parametro": p.model_dump(mode="json"), "usado_por_regras": usado,
                        "rulebook": meta}
    return None


def _ids_conhecidos() -> list[str]:
    ids: list[str] = []
    for rb in todos():
        ids += [r.id for r in rb.regras] + [p.id for p in rb.parametros]
    return ids


# ---------------------------------------------------------------------------
# Ferramentas registradas
# ---------------------------------------------------------------------------


def _entrada(modelo: type[BaseModel], args: Any) -> BaseModel:
    return args if isinstance(args, modelo) else modelo.model_validate(args)


def _data_ref(d: date | None, avisos: list[str]) -> date:
    if d is None:
        avisos.append("data_referencia não informada: usando a data do sistema (America/Sao_Paulo)")
        return datetime.now(FUSO).date()
    return d


@registrar(
    "planejar_metodo",
    "Escolhe o método de fiscalização (remoto, documental, presencial ou autofiscalização assistida) pelas "
    "regras do MCR 2-7 e lista obrigatoriedades (ex.: satélite > 300 ha), prazos com datas (ex.: máquinas "
    "em 60 dias) e as evidências exigidas por item financiado, cada uma com regra_id citável.",
    PlanejarMetodoEntrada,
)
def planejar_metodo(args: PlanejarMetodoEntrada) -> Envelope:
    t0 = time.perf_counter()
    nome = "planejar_metodo"
    try:
        e = _entrada(PlanejarMetodoEntrada, args)
    except ValidationError as ex:
        return Envelope.falha(nome, CodigoErro.ENTRADA_INVALIDA, str(ex)[:500], t0=t0)
    try:
        avisos: list[str] = []
        ref = _data_ref(e.data_referencia, avisos)
        data = planejar(e.operacao, e.contexto, ref)
        data["avisos"] = avisos + data["avisos"]
        data["status"] = "ok"  # StatusChecagem: plano calculado
        return Envelope.sucesso(nome, data, fonte_versao="+".join(data["rulebooks"]), t0=t0)
    except Exception as ex:  # noqa: BLE001 - erro vira envelope, nunca exceção solta
        return Envelope.falha(nome, CodigoErro.ERRO_INTERNO, f"{type(ex).__name__}: {ex}", t0=t0)


@registrar(
    "avaliar_regras",
    "Aplica o rulebook do MCR 2-7 (e, se pedido, do 2-9) às checagens e evidências da fiscalização e devolve "
    "um campo do laudo por exigência (verificado, divergente, pendente ou abstenção, com regra_id, evidências "
    "e checagens) e os bloqueios (regra_id e o que falta). Determinística; não usa LLM.",
    AvaliarRegrasEntrada,
)
def avaliar_regras(args: AvaliarRegrasEntrada) -> Envelope:
    t0 = time.perf_counter()
    nome = "avaliar_regras"
    try:
        e = _entrada(AvaliarRegrasEntrada, args)
    except ValidationError as ex:
        return Envelope.falha(nome, CodigoErro.ENTRADA_INVALIDA, str(ex)[:500], t0=t0)
    try:
        avisos: list[str] = []
        ref = _data_ref(e.data_referencia, avisos)
        res = avaliar(e.fiscalizacao, e.contexto, ref)
        data = res.model_dump(mode="json")
        data["avisos"] = avisos + data["avisos"]
        data["pode_emitir_rascunho"] = res.pode_emitir
        data["status"] = "ok"  # StatusChecagem: avaliação calculada (o status de cada campo está em campos)
        data["data_referencia"] = ref.isoformat()
        return Envelope.sucesso(nome, data, fonte_versao=res.fonte_versao, t0=t0)
    except Exception as ex:  # noqa: BLE001
        return Envelope.falha(nome, CodigoErro.ERRO_INTERNO, f"{type(ex).__name__}: {ex}", t0=t0)


@registrar(
    "explicar_regra",
    "Devolve a citação literal, o item da norma, a fonte (URL e data de acesso) e, para parâmetros "
    "operacionais, a justificativa de uma regra do rulebook (ex.: MCR-2-7-item16-maquinas-60d).",
    ExplicarRegraEntrada,
    timeout_s=2.0,
)
def explicar_regra(args: ExplicarRegraEntrada) -> Envelope:
    t0 = time.perf_counter()
    nome = "explicar_regra"
    try:
        e = _entrada(ExplicarRegraEntrada, args)
    except ValidationError as ex:
        return Envelope.falha(nome, CodigoErro.ENTRADA_INVALIDA, str(ex)[:500], t0=t0)
    try:
        data = explicar(e.regra_id.strip())
    except Exception as ex:  # noqa: BLE001
        return Envelope.falha(nome, CodigoErro.ERRO_INTERNO, f"{type(ex).__name__}: {ex}", t0=t0)
    if data is None:
        prefixo = e.regra_id.strip()[:9]
        sugestoes = [i for i in _ids_conhecidos() if i.startswith(prefixo)][:10]
        return Envelope.falha(nome, CodigoErro.ENTRADA_INVALIDA, f"regra desconhecida: {e.regra_id}", t0=t0,
                              data={"sugestoes": sugestoes})
    rb_meta = data["rulebook"]
    data["status"] = "ok"  # StatusChecagem: consulta respondida
    return Envelope.sucesso(nome, data, fonte_versao=f"rulebook-{rb_meta['id']}@{rb_meta['versao']}", t0=t0)
