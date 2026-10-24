"""Agente Auditor: revisa o rascunho antes da assinatura e aponta riscos e lacunas por item.

Avaliador independente, com a verdade no verificador determinístico: o Auditor **não muda nenhum status** e não
grava nada na fiscalização. Ele lê o que o verificador decidiu (status de cada item citando o MCR 2-7), as
pendências, as divergências, as checagens com abstenção e o texto do rascunho, e devolve um parecer estruturado
(`ParecerAuditor`) que a fiscal lê antes de assinar. Quem decide é o verificador; quem assina é a fiscal.

- O LLM é o mesmo do condutor, com saída estruturada (`laudo.llm.provider.pedir_json`). Provedor externo
  (`externo=True`): a entrada vai com a PII mascarada (`laudo.agent.pii.mascarar_obj`).
- A saída do LLM é conferida: item ou evidência que não existe sai; com pendência ou divergência sem justificativa
  no verificador, a recomendação é sempre "revisar_antes".
- LLM indisponível ou saída inválida: parecer determinístico, montado das pendências e divergências do
  verificador (`origem="regras"`).

Novo na arquitetura v2 e **não avaliado** no golden set: a tela o mostra como "revisão antes de assinar".
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from laudo.agent.pii import mascarar, mascarar_obj

Risco = Literal["alto", "medio", "baixo"]
Recomendacao = Literal["pode_assinar", "revisar_antes"]
NOTA = "O Auditor não muda nenhum status; quem decide é o verificador, citando o MCR. A assinatura é sua."
MAX_ITENS = 40


class ItemAuditoria(BaseModel):
    item_id: str = Field(max_length=120)
    risco: Risco
    motivo: str = Field(max_length=400)
    evidencias: list[str] = Field(default_factory=list, max_length=12)
    pergunta_para_a_fiscal: str = Field("", max_length=300)


class ParecerAuditor(BaseModel):
    resumo: str = Field(max_length=400)
    itens: list[ItemAuditoria] = Field(default_factory=list, max_length=20)
    recomendacao: Recomendacao


SISTEMA = (
    "Você é o Agente Auditor do Laudo Vivo, um revisor independente de laudos de fiscalização do crédito rural "
    "(MCR 2-7). Você NÃO decide status: o status de cada item já foi dado pelo verificador determinístico, "
    "citando o MCR. Seu trabalho é ler o rascunho, as provas e o resultado do verificador e apontar, antes da "
    "assinatura, o que a fiscal deve revisar: itens com pendência, divergência sem justificativa, abstenção de "
    "uma checagem, evidência fraca ou um texto do rascunho que diz mais do que as provas mostram. "
    "Para cada item em risco, cite o item_id exato da entrada, as evidências pelos ids da entrada (ids de "
    "evidência ou de checagem), o motivo em uma frase e uma pergunta curta e objetiva para a fiscal. "
    "Não invente item nem evidência. Recomende \"revisar_antes\" se houver qualquer pendência ou divergência "
    "sem justificativa; senão, \"pode_assinar\". Escreva em português do Brasil, sem dados pessoais. "
    "Responda apenas com o JSON do schema."
)


# ---------------------------------------------------------------------------- entrada
def montar_entrada(estado: dict[str, Any], texto_rascunho: str | None = None) -> dict[str, Any]:
    """A entrada do Auditor a partir do estado da fiscalização (`Servico.estado`): os itens do laudo com o status
    do verificador, as pendências, as divergências, as checagens com abstenção e o texto do rascunho."""
    linhas = list(estado.get("matriz") or [])[:MAX_ITENS]
    itens = [
        {
            "item_id": ln.get("campo"),
            "item": ln.get("item_descricao"),
            "aspecto": ln.get("aspecto"),
            "status_do_verificador": ln.get("status"),
            "regra": ln.get("regra_id"),
            "valor": ln.get("valor_fmt"),
            "motivo": (ln.get("motivo") or "")[:240],
            "justificativa_da_fiscal": (ln.get("justificativa") or "")[:240] or None,
            "evidencias": list(ln.get("evidencias") or []) + list(ln.get("checagens") or []),
            "agregado": bool(ln.get("agregado")),
        }
        for ln in linhas
        if ln.get("campo")
    ]
    # o resultado agregado do item repete o status dos aspectos (a justificativa fica no aspecto): conta só o aspecto
    pend = [i for i in itens if i["status_do_verificador"] in ("pendente", "abstencao") and not i["agregado"]]
    div = [i for i in itens if i["status_do_verificador"] == "divergente" and not i["agregado"]]
    chks = [
        {"id": c.get("id"), "ferramenta": c.get("ferramenta"), "status": c.get("status"), "item_id": c.get("item_id"),
         "resumo": (c.get("resumo") or "")[:200]}
        for c in estado.get("checagens") or []
        if str(c.get("status") or "").lower() in ("abstencao", "abstenção", "inconclusivo", "indeterminado")
    ]
    return {
        "etapa": estado.get("etapa"),
        "metodo": estado.get("metodo_rotulo") or estado.get("metodo"),
        "itens": itens,
        "pendencias": [{"item_id": i["item_id"], "status": i["status_do_verificador"], "motivo": i["motivo"]}
                       for i in pend],
        "divergencias": [{"item_id": i["item_id"], "motivo": i["motivo"],
                          "justificada": bool(i["justificativa_da_fiscal"])} for i in div],
        "checagens_com_abstencao": chks,
        "rascunho": (texto_rascunho or "")[:2000] or None,
    }


def ids_validos(estado: dict[str, Any]) -> tuple[set[str], set[str]]:
    """Itens (campos do laudo e itens da operação) e evidências (evidências, falas e checagens) que existem."""
    itens = {str(ln.get("campo")) for ln in estado.get("matriz") or [] if ln.get("campo")}
    itens |= {str(ln.get("item_id")) for ln in estado.get("matriz") or [] if ln.get("item_id")}
    evs = {str(e.get("id")) for chave in ("evidencias", "falas") for e in estado.get(chave) or [] if e.get("id")}
    evs |= {str(c.get("id")) for c in estado.get("checagens") or [] if c.get("id")}
    for ln in estado.get("matriz") or []:
        evs |= {str(x) for x in (ln.get("evidencias") or []) + (ln.get("checagens") or [])}
    return itens, evs


def bloqueios_do_verificador(entrada: dict[str, Any]) -> list[str]:
    """Pendência ou divergência sem justificativa: com qualquer uma delas, a fiscal revisa antes de assinar."""
    out = [f"pendência em {p['item_id']}" for p in entrada.get("pendencias") or []]
    out += [f"divergência sem justificativa em {d['item_id']}" for d in entrada.get("divergencias") or []
            if not d.get("justificada")]
    return out


# ---------------------------------------------------------------------------- parecer
def parecer_por_regras(entrada: dict[str, Any]) -> ParecerAuditor:
    """Parecer determinístico, só com o que o verificador decidiu (sem LLM)."""
    por_item = {i["item_id"]: i for i in entrada.get("itens") or []}
    itens: list[ItemAuditoria] = []

    def ev(iid: str) -> list[str]:
        return list(dict.fromkeys(por_item.get(iid, {}).get("evidencias") or []))[:12]

    for d in entrada.get("divergencias") or []:
        just = d.get("justificada")
        itens.append(ItemAuditoria(
            item_id=d["item_id"], risco="medio" if just else "alto",
            motivo=(("Divergência justificada pela fiscal: " if just else "Divergência sem justificativa: ")
                    + (d.get("motivo") or "o verificador encontrou diferença"))[:400],
            evidencias=ev(d["item_id"]),
            pergunta_para_a_fiscal=("A justificativa diz o que você viu em campo?" if just
                                    else "O que você viu em campo explica a diferença? Registre a justificativa."),
        ))
    for p in entrada.get("pendencias") or []:
        abst = p.get("status") == "abstencao"
        itens.append(ItemAuditoria(
            item_id=p["item_id"], risco="alto",
            motivo=(("Checagem se absteve: " if abst else "Sem prova: ") + (p.get("motivo") or "aguardando evidência"))[:400],
            evidencias=ev(p["item_id"]),
            pergunta_para_a_fiscal="Consegue enviar a prova que falta ou registrar por que não há?",
        ))
    for c in entrada.get("checagens_com_abstencao") or []:
        iid = c.get("item_id")
        if not iid or any(i.item_id == iid for i in itens):
            continue
        alvo = next((k for k in por_item if por_item[k].get("evidencias") and c.get("id") in por_item[k]["evidencias"]), None)
        if alvo is None:
            continue
        itens.append(ItemAuditoria(
            item_id=alvo, risco="baixo",
            motivo=f"Uma checagem ({c.get('ferramenta')}) se absteve; o status veio de outra prova.",
            evidencias=[str(c.get("id"))],
            pergunta_para_a_fiscal="A outra prova basta para este item?",
        ))
    bloq = bloqueios_do_verificador(entrada)
    n_pend = len(entrada.get("pendencias") or [])
    n_div = sum(1 for d in entrada.get("divergencias") or [] if not d.get("justificada"))
    n_just = sum(1 for d in entrada.get("divergencias") or [] if d.get("justificada"))
    if bloq:
        resumo = (f"Pelo verificador: {n_pend} pendência(s) e {n_div} divergência(s) sem justificativa. "
                  "Revise esses itens antes de assinar.")
    elif n_just:
        resumo = (f"Pelo verificador, nada pendente. {n_just} divergência(s) justificada(s) pela fiscal: confira se "
                  "a justificativa diz o que viu em campo.")
    else:
        resumo = "Pelo verificador, nada pendente e nenhuma divergência. Confira o resumo e assine se concordar."
    return ParecerAuditor(resumo=resumo[:400], itens=itens[:20], recomendacao="revisar_antes" if bloq else "pode_assinar")


def validar(parecer: ParecerAuditor, entrada: dict[str, Any], itens_ok: set[str], evs_ok: set[str]
            ) -> tuple[ParecerAuditor, list[str]]:
    """Tira item e evidência que não existem e força "revisar_antes" quando o verificador tem bloqueio."""
    avisos: list[str] = []
    itens: list[ItemAuditoria] = []
    for it in parecer.itens:
        if it.item_id not in itens_ok:
            avisos.append(f"item inexistente removido: {mascarar(it.item_id)[:60]}")
            continue
        boas = [e for e in it.evidencias if e in evs_ok]
        if len(boas) != len(it.evidencias):
            avisos.append(f"{len(it.evidencias) - len(boas)} evidência(s) inexistente(s) removida(s) de {it.item_id}")
        itens.append(it.model_copy(update={"evidencias": boas}))
    rec = parecer.recomendacao
    bloq = bloqueios_do_verificador(entrada)
    if bloq and rec != "revisar_antes":
        rec = "revisar_antes"
        avisos.append("recomendação ajustada para revisar antes: " + "; ".join(bloq[:3]))
    return parecer.model_copy(update={"itens": itens, "recomendacao": rec}), avisos


def auditar(estado: dict[str, Any], provedor: Any | None, texto_rascunho: str | None = None) -> dict[str, Any]:
    """Parecer do Auditor: `{parecer, origem: "llm" | "regras", modelo, avisos, nota}`. Não muda nada."""
    from laudo.llm.provider import pedir_json

    entrada = montar_entrada(estado, texto_rascunho)
    itens_ok, evs_ok = ids_validos(estado)
    avisos: list[str] = []
    if provedor is not None:
        enviada = mascarar_obj(entrada) if getattr(provedor, "externo", False) else entrada
        msgs = [
            {"role": "system", "content": SISTEMA},
            {"role": "user", "content": "Revise este rascunho antes da assinatura.\n"
             + json.dumps(enviada, ensure_ascii=False)},
        ]
        res = pedir_json(provedor, msgs, ParecerAuditor, reparos=1, metadados={"laudo.agente": "auditor"})
        if res.valido and isinstance(res.objeto, ParecerAuditor):
            parecer, avisos = validar(res.objeto, entrada, itens_ok, evs_ok)
            modelo = next((r.modelo for r in reversed(res.respostas) if r.modelo), "") or getattr(provedor, "modelo", "")
            return {"parecer": parecer.model_dump(), "origem": "llm", "modelo": modelo, "avisos": avisos, "nota": NOTA,
                    "latencia_ms": res.latencia_ms}
        avisos.append("LLM sem parecer válido" + (f" ({res.codigo_erro})" if res.codigo_erro else "")
                      + ": parecer pelas regras do verificador")
    else:
        avisos.append("sem LLM ao vivo neste modo: parecer pelas regras do verificador")
    return {"parecer": parecer_por_regras(entrada).model_dump(), "origem": "regras", "modelo": "regras",
            "avisos": avisos, "nota": NOTA, "latencia_ms": 0}
