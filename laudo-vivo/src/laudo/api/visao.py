"""Visões para a interface: estado da fiscalização (matriz ao vivo, evidências, provas, governança).

Tudo aqui é **leitura**: nada chama ferramenta, verificador ou política (que gerariam spans e mudariam a
trilha). O status de cada campo é o que o verificador gravou no último turno (`fis.campos`); requisitos ainda
sem checagem aparecem como "pendente".
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from shapely import wkt as shp_wkt

from laudo.agent.pii import mascarar, mascarar_obj
from laudo.agent.verificador import normalizar_requisitos
from laudo.contracts import Checagem, Evidencia, Fiscalizacao
from laudo.formatacao import fmt_milhar, fmt_valor

ETAPAS = ["BRIEFING", "COLETA", "CHECAGEM", "CONCILIACAO", "REVISAO", "RASCUNHO", "ASSINATURA", "SELADO"]
ROTULO_ETAPA = {
    "BRIEFING": "Briefing",
    "COLETA": "Coleta",
    "CHECAGEM": "Checagem",
    "CONCILIACAO": "Conciliação",
    "REVISAO": "Revisão",
    "RASCUNHO": "Rascunho",
    "ASSINATURA": "Assinatura",
    "SELADO": "Selado",
}
ROTULO_STATUS = {
    "verificado": "Verificado",
    "divergente": "Divergente",
    "pendente": "Pendente",
    "abstencao": "Abstenção",
}
ASPECTO = {
    "quantidade": "Quantidade (contagem em vídeo)",
    "nfe": "Nota fiscal (NF-e)",
    "gta": "GTA",
    "existencia": "Existência física georreferenciada",
    "localizacao": "Localização (foto dentro da gleba)",
    "integridade_foto": "Integridade da foto",
    "ndvi": "Vigor da vegetação (NDVI)",
    "lotacao": "Lotação",
    "integridade": "Integridade do documento",
    "autorizacao": "Autorização na SEFAZ",
    "formato": "Formato",
    "nfe_especie": "NF-e: espécie (NCM)",
    "nfe_quantidade": "NF-e: quantidade",
    "nfe_valor": "NF-e: valor",
    "nfe_data": "NF-e: data",
    "nfe_partes": "NF-e: vendedor e comprador",
    "nfe_operacao": "NF-e: operação (CFOP/UF)",
    "gta_especie": "GTA: espécie",
    "gta_quantidade": "GTA: quantidade",
    "gta_destino": "GTA: destino",
    "gta_origem": "GTA: origem",
    "gta_finalidade": "GTA: finalidade",
    "gta_data": "GTA: data",
    "comprovante_nfe": "Comprovante fiscal (NF-e)",
    "conclusao": "Conclusão da obra (declaração do fiscal)",
    "prazo_cronograma": "Prazo do cronograma físico",
    "metodo": "Método da fiscalização",
    "independencia_fiscal": "Independência do fiscal",
}
TIPOS_COM_ARQUIVO = {"foto", "video", "audio", "nfe_xml", "gta", "documento", "quadro_chave", "satelite"}
_REGRA_AGREGACAO = "OP-agregacao-item"


def fmt_num(v: Any) -> str:
    """Número da tela (milhar com ponto, decimal com vírgula); a regra é a de
    `laudo.formatacao.fmt_milhar`."""
    return fmt_milhar(v)


def glebas_coords(glebas_wkt: list[str], tolerancia: float = 0.0) -> list[list[list[float]]]:
    """WKT (lon lat) → anéis externos como [[lat, lon], ...] (formato do Leaflet), simplificados."""
    saida = []
    for w in glebas_wkt:
        try:
            g = shp_wkt.loads(w)
        except Exception:  # noqa: BLE001, S112 - WKT inválido não derruba a tela (só não desenha)
            continue
        if tolerancia:
            g = g.simplify(tolerancia, preserve_topology=True)
        polys = list(getattr(g, "geoms", [g]))
        for p in polys:
            ext = getattr(p, "exterior", None)
            if ext is None:
                continue
            saida.append([[round(y, 6), round(x, 6)] for x, y in ext.coords])
    return saida


def _url_ev(fis_id: str, ev: Evidencia) -> str | None:
    if ev.tipo not in TIPOS_COM_ARQUIVO or not ev.caminho or not Path(ev.caminho).is_file():
        return None
    return f"/api/fiscalizacoes/{fis_id}/evidencias/{ev.id}/arquivo"


def evidencia_visao(fis_id: str, ev: Evidencia) -> dict[str, Any]:
    meta = ev.meta or {}
    d: dict[str, Any] = {
        "id": ev.id,
        "tipo": ev.tipo,
        "nome": Path(ev.caminho).name if ev.caminho else None,
        "url": _url_ev(fis_id, ev),
        "sha256": ev.sha256,
        "recebida_em": ev.recebida_em.isoformat(timespec="seconds") if ev.recebida_em else None,
        "capturada_em": ev.capturada_em.isoformat(timespec="seconds") if ev.capturada_em else None,
        "gps": ev.gps.model_dump(mode="json") if ev.gps else None,
        "item_id": meta.get("item_id"),
        "lote": meta.get("lote"),
        "laudo": bool(meta.get("laudo")),
    }
    if ev.tipo == "declaracao":
        d["texto"] = meta.get("texto")
        d["origem"] = meta.get("origem")
    elif ev.tipo == "ocorrencia":
        d["descricao"] = meta.get("descricao")
        d["ocorrencia_tipo"] = meta.get("tipo")
    if ev.tipo in ("nfe_xml", "gta"):
        d["trecho_url"] = f"/api/fiscalizacoes/{fis_id}/evidencias/{ev.id}/trecho"
    return d


# ---------------------------------------------------------------------------
# Provas por checagem
# ---------------------------------------------------------------------------


def _motivos(r: dict[str, Any]) -> list[str]:
    out = []
    for m in r.get("motivos") or []:
        if isinstance(m, dict):
            out.append(
                m.get("msg")
                or m.get("texto")
                or m.get("motivo")
                or m.get("codigo")
                or json.dumps(m, ensure_ascii=False)
            )
        else:
            out.append(str(m))
    if r.get("motivo") and r["motivo"] not in out:
        out.insert(0, str(r["motivo"]))
    return [mascarar(x)[:300] for x in out]


def prova_checagem(fis: Fiscalizacao, chk: Checagem) -> dict[str, Any]:
    r = chk.resultado or {}
    evs = {e.id: e for e in fis.evidencias}
    ev = evs.get(chk.evidencias[0]) if chk.evidencias else None
    base = {
        "tipo": "generico",
        "fake": bool(r.get("fake")),
        "motivos": _motivos(r),
        "erro": (r.get("erro") or {}).get("msg") if isinstance(r.get("erro"), dict) else None,
    }
    f = chk.ferramenta
    if f == "contar_bovinos_video":
        quadros = [
            {
                "url": f"/api/fiscalizacoes/{fis.id}/checagens/{chk.id}/quadros/{i}",
                "t_s": q.get("t_s"),
                "contagem_ate_aqui": q.get("contagem_ate_aqui"),
                "sha256": q.get("sha256"),
            }
            for i, q in enumerate(r.get("quadros_chave") or [])
            if isinstance(q, dict)
        ]
        return base | {
            "tipo": "contagem",
            "contagem": r.get("contagem"),
            "intervalo": r.get("intervalo"),
            "status_ferramenta": r.get("status_ferramenta") or r.get("status"),
            "abstencao": r.get("abstencao"),
            "pedidos_recaptura": r.get("pedidos_recaptura") or [],
            "quadros": quadros,
            "video_url": _url_ev(fis.id, ev) if ev else None,
            "metodo": r.get("metodo") or r.get("versao"),
            "conf_media": r.get("conf_media"),
            "lote": r.get("lote") or (ev.meta.get("lote") if ev else None),
        }
    if f in ("integridade_foto", "geofence"):
        gps = ev.gps.model_dump(mode="json") if ev is not None and ev.gps else None
        return base | {
            "tipo": "foto_mapa",
            "ferramenta": f,
            "status_ferramenta": r.get("status_ferramenta") or r.get("status"),
            "foto_url": _url_ev(fis.id, ev) if ev else None,
            "gps": gps,
            "distancia_borda_m": r.get("distancia_borda_m"),
            "precisao_m": r.get("precisao_m"),
            "glebas": glebas_coords(fis.operacao.glebas_wkt),
            "exif": {
                k: r.get(k) for k in ("exif", "gps_exif", "score_tela", "nitidez", "atraso_h") if k in r
            },
            "alertas": [mascarar(str(a))[:200] for a in (r.get("alertas") or [])][:8],
        }
    if f in ("conciliar_nfe", "conciliar_gta"):
        crits = [
            {
                "campo": c.get("campo"),
                "status": c.get("status"),
                "regra_id": c.get("regra_id"),
                "motivo": mascarar(str(c.get("motivo") or ""))[:300],
            }
            for c in (r.get("criterios") or [])
            if isinstance(c, dict)
        ]
        nao = [
            {"regra_id": a.get("regra_id"), "motivo": a.get("motivo")}
            for a in (r.get("nao_verificado_offline") or [])
            if isinstance(a, dict)
        ]
        return base | {
            "tipo": "documento",
            "ferramenta": f,
            "criterios": crits,
            "nao_verificado_offline": nao,
            "trecho_url": f"/api/fiscalizacoes/{fis.id}/evidencias/{ev.id}/trecho" if ev else None,
            "status_ferramenta": r.get("status_ferramenta") or r.get("status"),
            "resumo": {
                k: r.get(k) for k in ("quantidade", "valor", "ncm", "data_emissao", "especie") if k in r
            },
        }
    if f == "planejar_metodo":
        return base | {
            "tipo": "plano",
            "metodo": r.get("metodo"),
            "justificativa": r.get("justificativa"),
            "n_requisitos": len(r.get("requisitos") or []),
        }
    escalares = {k: v for k, v in r.items() if isinstance(v, (str, int, float, bool)) and k not in ("fake",)}
    return base | {"dados": mascarar_obj(dict(list(escalares.items())[:12]))}


def checagem_visao(fis: Fiscalizacao, chk: Checagem) -> dict[str, Any]:
    r = chk.resultado or {}
    resumo = ", ".join(
        f"{k}={fmt_num(r[k])}"
        for k in ("status", "contagem", "intervalo", "quantidade", "metodo")
        if k in r and r[k] is not None
    )
    return {
        "id": chk.id,
        "ferramenta": chk.ferramenta,
        "status": chk.status,
        "item_id": chk.item_id,
        "regra_id": chk.regra_id,
        "evidencias": chk.evidencias,
        "span_id": chk.trace_id,
        "fonte_versao": chk.fonte_versao,
        "criada_em": chk.criada_em.isoformat(timespec="seconds"),
        "resumo": mascarar(resumo)[:300],
        "prova": prova_checagem(fis, chk),
    }


# ---------------------------------------------------------------------------
# Matriz de itens
# ---------------------------------------------------------------------------


def _aspecto(campo: str) -> str:
    partes = campo.split(":")
    if partes[0] == "item" and len(partes) == 2:
        return "Resultado do item"
    suf = partes[-1]
    return ASPECTO.get(suf, suf.replace("_", " "))


def matriz(fis: Fiscalizacao) -> list[dict[str, Any]]:
    from laudo.tools.laudo import proveniencia

    itens = {i.id: i for i in fis.operacao.itens}
    ordem_item = {i.id: n for n, i in enumerate(fis.operacao.itens)}
    try:
        reqs = normalizar_requisitos(fis)
    except Exception:  # noqa: BLE001 - requisito malformado não derruba a tela
        reqs = []
    ordem_req = {r.get("campo"): n for n, r in enumerate(reqs)}
    linhas: dict[str, dict[str, Any]] = {}

    def item_de(campo: str) -> str | None:
        p = campo.split(":")
        return p[1] if p[0] == "item" and len(p) > 2 else None

    for nome, c in fis.campos.items():
        iid = item_de(nome)
        linhas[nome] = {
            "campo": nome,
            "item_id": iid,
            "item_descricao": itens[iid].descricao
            if iid in itens
            else (
                "Documento"
                if nome.startswith("documento")
                else "Laudo"
                if nome.startswith("laudo")
                else "Operação"
            ),
            "aspecto": _aspecto(nome),
            "agregado": c.regra_id == _REGRA_AGREGACAO or (nome.startswith("item:") and nome.count(":") == 1),
            "status": c.status,
            "rotulo": ROTULO_STATUS.get(c.status, c.status),
            "valor": c.valor,
            "valor_fmt": fmt_valor(c.valor),
            "regra_id": c.regra_id,
            "motivo": mascarar(c.motivo or ""),
            "ressalvas": c.ressalvas,
            "justificativa": c.justificativa_humana,
            "evidencias": c.evidencias,
            "checagens": c.checagens,
            "proveniencia": proveniencia(fis, c.evidencias, c.checagens, bool(c.justificativa_humana)),
            "sem_checagem": False,
        }
    for r in reqs:
        campo = r.get("campo")
        if not campo or campo in linhas or not r.get("obrigatorio", True):
            continue
        iid = r.get("item_id") or item_de(campo)
        linhas[campo] = {
            "campo": campo,
            "item_id": iid,
            "item_descricao": itens[iid].descricao if iid in itens else "Operação",
            "aspecto": _aspecto(campo),
            "status": "pendente",
            "rotulo": "Pendente",
            "valor": None,
            "valor_fmt": "—",
            "regra_id": r.get("regra_id"),
            "motivo": "aguardando evidência",
            "pedido": r.get("pedido") or r.get("descricao"),
            "tipos_evidencia": r.get("tipos_evidencia") or [],
            "ressalvas": [],
            "justificativa": None,
            "evidencias": [],
            "checagens": [],
            "proveniencia": [],
            "sem_checagem": True,
        }
    for nome, linha in linhas.items():
        req = next((r for r in reqs if r.get("campo") == nome), None)
        if req:
            linha.setdefault("pedido", req.get("pedido") or req.get("descricao"))
            linha.setdefault("tipos_evidencia", req.get("tipos_evidencia") or [])

    def chave(kv: tuple[str, dict[str, Any]]) -> tuple[int, int, str]:
        return (
            ordem_item.get(kv[1]["item_id"] or "", 98 if kv[0].startswith("documento") else 99),
            ordem_req.get(kv[0], 99),
            kv[0],
        )

    return [v for _, v in sorted(linhas.items(), key=chave)]


def contagem_status(linhas: list[dict[str, Any]]) -> dict[str, int]:
    """Contadores da tela: só aspectos, como o resumo do laudo; o "Resultado do item" (agregado) fica
    fora."""
    out = {s: 0 for s in ROTULO_STATUS}
    for linha in linhas:
        if linha.get("agregado"):
            continue
        out[linha["status"]] = out.get(linha["status"], 0) + 1
    return out


# ---------------------------------------------------------------------------
# Governança (decisões de política a partir do trace)
# ---------------------------------------------------------------------------


def ler_trace(caminho: Path, limite: int = 5000) -> list[dict[str, Any]]:
    if not caminho.exists():
        return []
    saida = []
    with open(caminho, encoding="utf-8") as f:
        for linha in f:
            if linha.strip():
                try:
                    saida.append(json.loads(linha))
                except json.JSONDecodeError:
                    continue
            if len(saida) >= limite:
                break
    return saida


def governanca(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Decisões que negaram, registraram ou transformaram algo (as permissões rotineiras ficam de fora)."""
    out = []
    for s in spans:
        a = s.get("attributes") or {}
        if s.get("name") == "policy.decision" and a.get("policy.resultado") != "permitir":
            out.append(
                {
                    "span_id": s.get("span_id"),
                    "rule_id": a.get("policy.rule_id"),
                    "resultado": a.get("policy.resultado"),
                    "acao": a.get("policy.acao"),
                    "motivo": a.get("policy.motivo"),
                    "em": s.get("start"),
                    "n_pendencias": a.get("policy.n_pendencias"),
                }
            )
        elif s.get("name") == "policy.decision" and str(a.get("policy.acao")) in (
            "assinar",
            "emitir_rascunho",
        ):
            out.append(
                {
                    "span_id": s.get("span_id"),
                    "rule_id": a.get("policy.rule_id"),
                    "resultado": a.get("policy.resultado"),
                    "acao": a.get("policy.acao"),
                    "motivo": a.get("policy.motivo"),
                    "em": s.get("start"),
                }
            )
    return out


def spans_relacionados(spans: list[dict[str, Any]], span_id: str) -> list[dict[str, Any]]:
    """O span pedido, seus filhos e seu pai (para abrir a "prova" da checagem no trace)."""
    alvo = next((s for s in spans if s.get("span_id") == span_id), None)
    if alvo is None:
        return []
    out = [alvo]
    out += [s for s in spans if s.get("parent_span_id") == span_id]
    pai = next((s for s in spans if s.get("span_id") == alvo.get("parent_span_id")), None)
    if pai:
        out.insert(0, pai)
    return out


# ---------------------------------------------------------------------------
# Eventos de um turno (faixas de destaque na tela)
# ---------------------------------------------------------------------------

_TITULO_GUARDA = {
    "POL-07": ("pressao", "Pressão recusada"),
    "POL-06": ("injecao", "Instrução embutida ignorada"),
    "POL-03": ("assinatura", "O agente não assina"),
    "POL-04": ("selado", "Laudo selado: nada muda"),
    "POL-02": ("justificativa", "Justificativa recusada"),
}


def eventos_turno(resp: dict[str, Any], antes: dict[str, str], depois: list[dict[str, Any]]) -> list[dict]:
    """Resposta do turno → eventos da faixa de destaque (bloqueio, abstenção, recusa, emissão)."""
    ev: list[dict[str, Any]] = []
    for a in resp.get("acoes") or []:
        rid = str(a.get("rule_id") or "")
        if a.get("acao") == "emitir_rascunho":
            if a.get("ok"):
                h = (a.get("dados") or {}).get("hash_raiz") or ""
                ev.append(
                    {
                        "tipo": "emitido",
                        "nivel": "ok",
                        "titulo": "Rascunho emitido",
                        "texto": f"Hash raiz {h[:16]}… — confira e assine (o agente não assina).",
                        "rule_id": rid,
                    }
                )
            else:
                pend = (a.get("dados") or {}).get("pendencias") or []
                ev.append(
                    {
                        "tipo": "bloqueio",
                        "nivel": "bloqueio",
                        "titulo": "Política BLOQUEOU o rascunho",
                        "texto": f"{len(pend)} pendência(s) antes da emissão (default-deny).",
                        "pendencias": pend[:8],
                        "rule_id": rid or "POL-01",
                        "span_id": a.get("span_id"),
                    }
                )
        elif a.get("acao") == "assinar":
            if a.get("ok"):
                ev.append(
                    {
                        "tipo": "selado",
                        "nivel": "ok",
                        "titulo": "Assinado e selado",
                        "texto": "Assinatura humana com PIN e hash conferido.",
                        "rule_id": rid,
                    }
                )
            else:
                ev.append(
                    {
                        "tipo": "assinatura",
                        "nivel": "bloqueio",
                        "titulo": "Assinatura recusada",
                        "texto": str(a.get("resultado") or ""),
                        "rule_id": rid,
                        "span_id": a.get("span_id"),
                    }
                )
        elif a.get("origem") == "guarda" and not a.get("permitido", True):
            chave = rid.split("/")[0]
            tipo, titulo = _TITULO_GUARDA.get(chave, ("guarda", "Guarda da política"))
            ev.append(
                {
                    "tipo": tipo,
                    "nivel": "bloqueio",
                    "titulo": titulo,
                    "texto": str(a.get("resultado") or ""),
                    "rule_id": rid,
                    "span_id": a.get("span_id"),
                }
            )
        elif not a.get("permitido", True):
            ev.append(
                {
                    "tipo": "negado",
                    "nivel": "bloqueio",
                    "titulo": f"Política negou {a.get('acao')}",
                    "texto": str(a.get("resultado") or ""),
                    "rule_id": rid,
                    "span_id": a.get("span_id"),
                }
            )
    for linha in depois:
        st_antes = antes.get(linha["campo"])
        # "Resultado do item" repete o pior aspecto do item: uma faixa por campo, sem a duplicata do agregado
        if linha["status"] == st_antes or linha.get("sem_checagem") or linha.get("agregado"):
            continue
        if linha["status"] == "abstencao":
            ev.append(
                {
                    "tipo": "abstencao",
                    "nivel": "abstencao",
                    "titulo": "O agente se ABSTEVE",
                    "texto": f"{linha['item_descricao']} — {linha['aspecto']}: {linha['motivo']}",
                    "campo": linha["campo"],
                    "pedido": linha.get("pedido"),
                }
            )
        elif linha["status"] == "divergente":
            ev.append(
                {
                    "tipo": "divergencia",
                    "nivel": "divergente",
                    "titulo": "Divergência encontrada",
                    "texto": f"{linha['item_descricao']} — {linha['aspecto']}: {linha['motivo']}",
                    "campo": linha["campo"],
                }
            )
        elif linha["status"] == "verificado" and st_antes in (None, "pendente", "abstencao", "divergente"):
            ev.append(
                {
                    "tipo": "verificado",
                    "nivel": "ok",
                    "titulo": "Item verificado",
                    "texto": f"{linha['item_descricao']} — {linha['aspecto']}",
                    "campo": linha["campo"],
                }
            )
        elif linha["status"] == "pendente" and linha.get("checagens"):
            ev.append(
                {
                    "tipo": "pendente",
                    "nivel": "pendente",
                    "titulo": "Item pendente",
                    "texto": f"{linha['item_descricao']} — {linha['aspecto']}: {linha['motivo']}",
                    "campo": linha["campo"],
                }
            )
    for o in resp.get("ocorrencias") or []:
        ev.append(
            {
                "tipo": "ocorrencia",
                "nivel": "info",
                "titulo": "Ocorrência registrada na cadeia de hash",
                "texto": str(o),
            }
        )
    return ev


_HEX_LONGO = re.compile(r"\b[0-9a-f]{12,}\b")


def fala_para_voz(texto: str, limite: int = 320) -> str:
    """Texto do agente para TTS: sem hashes nem ids técnicos (ninguém quer ouvir hexadecimal) e curto: corta
    na última frase completa antes de `limite` caracteres (o texto inteiro continua na tela)."""
    t = _HEX_LONGO.sub("", texto or "")
    t = re.sub(r"\b(?:ev|chk|oc|alg|al|fis)_[0-9a-z_]+\b", "", t)
    t = re.sub(r"\((?:item|documento|operacao|laudo)(?::[^)]*)?\)", "", t)
    t = re.sub(r"\b(?:item|laudo|documento):[\w:]+\b", "", t)
    t = re.sub(r"\s{2,}", " ", t).replace(" .", ".").replace(" ,", ",").replace("( )", "").strip()
    if len(t) > limite:
        corte = max(t.rfind(p, 0, limite) for p in (". ", "! ", "? "))
        t = t[: corte + 1] if corte > 40 else t[:limite].rsplit(" ", 1)[0] + "…"
    return t
