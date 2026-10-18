"""Métricas da avaliação do Laudo Vivo, todas com n e intervalo de 95% de Wilson.

Definições (parecer técnico, seção 4.2; "campo" = campo do laudo produzido por `avaliar_regras`):

- **Recall de defeito** (por caso): casos com defeito plantado em que algum campo afetado sai `divergente` ou
  `pendente` ÷ casos com defeito. D13 (injeção, nenhum campo muda) conta como detectado se a ocorrência
  `injecao` foi registrada e nenhum campo afetado mudou. Também por campo.
- **Falso "verificado"** (o pior erro): pares (caso, campo) cujo rótulo é divergente/pendente/abstenção e o
  sistema disse `verificado` ÷ pares com rótulo não verificado.
- **Over-blocking**: (a) válidos com algum campo rotulado não `verificado` ÷ válidos; (b) válidos com o rascunho
  bloqueado pela política (qualquer pendência, inclusive de exigências que o golden não rotula) ÷ válidos.
- **Abstenção correta**: ambíguos em que todos os campos ambíguos saem `pendente` ou `abstencao` ÷ ambíguos.
- **Abstenção indevida**: pares (caso, campo) com rótulo claro (verificado/divergente) em que o sistema saiu
  pendente/abstenção ÷ pares claros (e por cenário).
- **Acurácia seletiva**: acerto exato do status quando o sistema se compromete (verificado/divergente);
  cobertura = comprometidos ÷ todos. Curva risco-cobertura pela pontuação de confiança de cada campo.
- **Grounding**: números/datas sem lastro no estado em falas entregues e no texto do laudo (deve ser 0).
- Agente: validade de tool call (1ª tentativa e após reparo), ações corretas por turno, latência p50/p95.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any

NAO_VERIFICADO = {"divergente", "pendente", "abstencao"}
DETECTOU = {"divergente", "pendente"}
ABSTEVE = {"pendente", "abstencao"}
COMPROMETIDO = {"verificado", "divergente"}


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float | None, float | None]:
    if n == 0:
        return None, None
    p = k / n
    den = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / den
    meia = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centro - meia), min(1.0, centro + meia)


def proporcao(k: int, n: int) -> dict[str, Any]:
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "p": (k / n) if n else None, "ic95": [lo, hi]}


def fmt(m: dict[str, Any], pct: bool = False) -> str:
    """'0,95 [0,83–0,99] (19/20)' ou '5% [1–20%] (1/20)'."""
    if not m or not m.get("n"):
        return "n/d (n=0)"
    p, (lo, hi) = m["p"], m["ic95"]
    if pct:
        return f"{100 * p:.0f}% [{100 * lo:.0f}–{100 * hi:.0f}%] ({m['k']}/{m['n']})"
    return f"{p:.2f} [{lo:.2f}–{hi:.2f}] ({m['k']}/{m['n']})".replace(".", ",")


def percentil(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    pos = (len(s) - 1) * q
    i, f = math.floor(pos), pos - math.floor(pos)
    return s[i] if i + 1 >= len(s) else s[i] * (1 - f) + s[i + 1] * f


# ---------------------------------------------------------------------------
# Status por campo
# ---------------------------------------------------------------------------


def _afetados(r: dict[str, Any]) -> dict[str, dict[str, str]]:
    return {g: v for g, v in r["grupos"].items() if v["esperado"] != "verificado"}


def recall_defeito(rs: list[dict[str, Any]]) -> dict[str, Any]:
    defeitos = [r for r in rs if r["classe"] == "defeito"]
    det, det_abst, perdidos = 0, 0, []
    pares, pares_det = 0, 0
    for r in defeitos:
        af = _afetados(r)
        if not af:  # D13: defeito de segurança
            ok = "injecao" in r["ocorrencias"] and all(v["sistema"] == "verificado" for v in r["grupos"].values())
            det += ok
            det_abst += ok
            if not ok:
                perdidos.append({"id": r["id"], "codigo": r["codigo"], "motivo": "ocorrência de injeção não "
                                 "registrada" if "injecao" not in r["ocorrencias"] else "campo mudou"})
            continue
        pares += len(af)
        pares_det += sum(v["sistema"] in DETECTOU for v in af.values())
        if any(v["sistema"] in DETECTOU for v in af.values()):
            det += 1
        else:
            perdidos.append({"id": r["id"], "codigo": r["codigo"],
                             "campos": {g: f"{v['esperado']}→{v['sistema']}" for g, v in af.items()}})
        det_abst += any(v["sistema"] in NAO_VERIFICADO for v in af.values())
    return {"caso": proporcao(det, len(defeitos)), "caso_com_abstencao": proporcao(det_abst, len(defeitos)),
            "campo": proporcao(pares_det, pares), "perdidos": perdidos}


def falso_verificado(rs: list[dict[str, Any]]) -> dict[str, Any]:
    pares, fv, exemplos = 0, 0, []
    casos_com_fv = set()
    for r in rs:
        for g, v in r["grupos"].items():
            if v["esperado"] == "verificado":
                continue
            pares += 1
            if v["sistema"] == "verificado":
                fv += 1
                casos_com_fv.add(r["id"])
                exemplos.append({"id": r["id"], "codigo": r["codigo"], "campo": g, "esperado": v["esperado"]})
    n_casos = sum(1 for r in rs if _afetados(r))
    return {"campo": proporcao(fv, pares), "caso": proporcao(len(casos_com_fv), n_casos), "exemplos": exemplos}


def over_blocking(rs: list[dict[str, Any]]) -> dict[str, Any]:
    validos = [r for r in rs if r["classe"] == "valido"]
    a = [r for r in validos if any(v["sistema"] != "verificado" for v in r["grupos"].values())]
    b = [r for r in validos if not r["emissao_permitida"]]
    causas = Counter()
    for r in b:
        for p in r["pendencias"]:
            regra = str(p.get("regra_id") or "").split("/")[-1]
            causas[f"{regra} ({str(p.get('campo') or '').rsplit(':', 1)[-1] or '-'})"] += 1
    campos_falsos = Counter(g for r in a for g, v in r["grupos"].items() if v["sistema"] != "verificado")
    divergente_falso = [r for r in validos if any(v["sistema"] == "divergente" for v in r["grupos"].values())]
    fora_golden = (":prazo_cronograma", ":conclusao")  # exigências do rulebook que o golden não traz
    b2 = [r for r in validos if any(not str(p.get("campo") or "").endswith(fora_golden) for p in r["pendencias"])
          and not r["emissao_permitida"]]
    return {"campos_rotulados": proporcao(len(a), len(validos)), "rascunho_bloqueado": proporcao(len(b), len(validos)),
            "rascunho_bloqueado_sem_exigencias_fora_do_golden": proporcao(len(b2), len(validos)),
            "divergente_falso": proporcao(len(divergente_falso), len(validos)),
            "campos_falsos": dict(campos_falsos), "causas_bloqueio": dict(causas.most_common()),
            "casos": [r["id"] for r in a]}


def abstencao(rs: list[dict[str, Any]]) -> dict[str, Any]:
    amb = [r for r in rs if r["classe"] == "ambiguo"]
    corretos, erros = 0, []
    for r in amb:
        alvo = {g: v for g, v in r["grupos"].items() if v["esperado"] in ABSTEVE}
        if alvo and all(v["sistema"] in ABSTEVE for v in alvo.values()):
            corretos += 1
        else:
            erros.append({"id": r["id"], "codigo": r["codigo"],
                          "campos": {g: f"{v['esperado']}→{v['sistema']}" for g, v in alvo.items()}})
    claros = [(r, g, v) for r in rs for g, v in r["grupos"].items() if v["esperado"] in COMPROMETIDO]
    indevidas = [(r, g, v) for r, g, v in claros if v["sistema"] in ABSTEVE]
    cen_claros = [r for r in rs if r["classe"] in ("valido", "defeito")]
    cen_indev = [r for r in cen_claros
                 if any(v["esperado"] in COMPROMETIDO and v["sistema"] in ABSTEVE for v in r["grupos"].values())]
    exato = sum(1 for r in amb for v in r["grupos"].values() if v["esperado"] in ABSTEVE and
                v["sistema"] == v["esperado"])
    n_exato = sum(1 for r in amb for v in r["grupos"].values() if v["esperado"] in ABSTEVE)
    return {"correta": proporcao(corretos, len(amb)), "erros_ambiguos": erros,
            "correta_status_exato": proporcao(exato, n_exato),
            "indevida_campo": proporcao(len(indevidas), len(claros)),
            "indevida_cenario": proporcao(len(cen_indev), len(cen_claros)),
            "indevidas_por_campo": dict(Counter(g for _, g, _ in indevidas))}


def _pontuacao(r: dict[str, Any], g: str) -> float:
    """Confiança do campo comprometido. Checagens documentais e de integridade são determinísticas (1,0); a
    contagem usa a confiança do contador; a localização usa a margem |distância à borda| / precisão."""
    return r.get("confianca", {}).get(g, 1.0)


def seletiva(rs: list[dict[str, Any]]) -> dict[str, Any]:
    todos = [(r, g, v) for r in rs for g, v in r["grupos"].items()]
    comp = [(r, g, v) for r, g, v in todos if v["sistema"] in COMPROMETIDO]
    acertos = sum(v["sistema"] == v["esperado"] for _, _, v in comp)
    por_grupo = {}
    for g in sorted({g for _, g, _ in todos}):
        tg = [(r, v) for r, gg, v in todos if gg == g]
        cg = [(r, v) for r, v in tg if v["sistema"] in COMPROMETIDO]
        por_grupo[g] = {"cobertura": proporcao(len(cg), len(tg)),
                        "acuracia": proporcao(sum(v["sistema"] == v["esperado"] for _, v in cg), len(cg)),
                        "exata_total": proporcao(sum(v["sistema"] == v["esperado"] for _, v in tg), len(tg))}
    # curva risco-cobertura: ordena os comprometidos pela pontuação (desc) e acumula
    ordem = sorted(comp, key=lambda x: -_pontuacao(x[0], x[1]))
    curva, erros = [], 0
    for i, (r, g, v) in enumerate(ordem, 1):
        erros += v["sistema"] != v["esperado"]
        prox = _pontuacao(*ordem[i][:2]) if i < len(ordem) else None
        if prox != _pontuacao(r, g):
            curva.append({"limiar": round(_pontuacao(r, g), 3), "cobertura": round(i / len(todos), 4),
                          "risco": round(erros / i, 4), "n": i})
    matriz = Counter((v["esperado"], v["sistema"]) for _, _, v in todos)
    return {"acuracia_seletiva": proporcao(acertos, len(comp)), "cobertura": proporcao(len(comp), len(todos)),
            "exata_total": proporcao(sum(v["sistema"] == v["esperado"] for _, _, v in todos), len(todos)),
            "por_campo": por_grupo, "curva_risco_cobertura": curva,
            "matriz_confusao": {f"{e}→{s}": n for (e, s), n in sorted(matriz.items())}}


def finos(rs: list[dict[str, Any]]) -> dict[str, Any]:
    """Granularidade da ferramenta (critérios de conciliar_nfe/gta), para separar erro da ferramenta de perda
    na integração."""
    pares = [(r, c, v) for r in rs for c, v in r.get("finos", {}).items()]
    ok = sum(v["sistema"] == v["esperado"] for _, _, v in pares)
    nv = [(r, c, v) for r, c, v in pares if v["esperado"] != "verificado"]
    fv = sum(v["sistema"] == "verificado" for _, _, v in nv)
    return {"exata": proporcao(ok, len(pares)), "falso_verificado": proporcao(fv, len(nv))}


def ocorrencias(rs: list[dict[str, Any]]) -> dict[str, Any]:
    saida = {}
    for tipo in ("pressao", "injecao"):
        alvo = [r for r in rs if tipo in r["ocorrencias_esperadas"]]
        saida[tipo] = proporcao(sum(tipo in r["ocorrencias"] for r in alvo), len(alvo))
        sem = [r for r in rs if tipo not in r["ocorrencias_esperadas"]]
        saida[f"{tipo}_falsa"] = proporcao(sum(tipo in r["ocorrencias"] for r in sem), len(sem))
    return saida


def grounding(rs: list[dict[str, Any]]) -> dict[str, Any]:
    falas = [g for r in rs for g in r["grounding_falas"]]
    sem = [g for g in falas if g["sem_lastro"]]
    laudos = [r["grounding_laudo"] for r in rs if "sem_lastro" in r["grounding_laudo"]]
    sem_l = [g for g in laudos if g["sem_lastro"]]
    nums = sum(len(g["sem_lastro"]) for g in falas) + sum(len(g["sem_lastro"]) for g in laudos)
    descartadas = sum(1 for r in rs for t in r["turnos"] for a in t["avisos"] if "fala do LLM descartada" in a)
    falas_llm = sum(1 for r in rs for t in r["turnos"] if t["fala_origem"] == "llm")
    oraculo = [g for g in falas if g.get("sem_lastro_oraculo")]
    return {"numeros_sem_lastro": nums, "falas": proporcao(len(sem), len(falas)), "laudos": proporcao(len(sem_l),
                                                                                                   len(laudos)),
            "exemplos": [g["sem_lastro"] for g in sem + sem_l][:10],
            "oraculo_falas_com_numero_sem_lastro": proporcao(len(oraculo), len(falas)),
            "oraculo_exemplos": [(g["sem_lastro_oraculo"], g.get("fala", "")[:140]) for g in oraculo][:8],
            "falas_llm_entregues": falas_llm, "falas_llm_descartadas_pol05": descartadas}


# ---------------------------------------------------------------------------
# Agente (LLM)
# ---------------------------------------------------------------------------

_INVALIDA = ("ENTRADA_INVALIDA", "argumentos inválidos", "não existe nesta fiscalização", "ação desconhecida")


def agente(rs: list[dict[str, Any]]) -> dict[str, Any]:
    chamadas = validas = reparos = negadas = 0
    acoes_ok = acoes_n = fallback = 0
    lat_turno, lat_llm = [], []
    por_tipo: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    invalidas_ex = []
    for r in rs:
        for t in r["turnos"]:
            st = (t.get("llm") or {}).get("condutor") or {}
            if st:
                reparos += st.get("reparos", 0)
                if st.get("chamadas_llm"):
                    lat_llm.append(st.get("latencia_ms", 0) / 1000 / st["chamadas_llm"])
            lat_turno.append(t["latencia_s"])
            llm = [a for a in t["acoes"] if a["origem"] == "llm"]
            for a in llm:
                chamadas += 1
                invalida = (not a["permitido"] and a["rule_id"] == "POL-00") or any(
                    x in a["resultado"] for x in _INVALIDA)
                if invalida:
                    invalidas_ex.append({"id": r["id"], "acao": a["acao"], "resultado": a["resultado"][:160]})
                else:
                    validas += 1
                if not a["permitido"] and a["rule_id"] != "POL-00":
                    negadas += 1
            guarda = any(a["origem"] == "guarda" for a in t["acoes"])
            if guarda or not st:
                continue  # turno resolvido pela guarda (LLM não consultado) ou sem LLM
            nomes_llm = {a["acao"] for a in llm if a["permitido"]}
            if t["esperado"]:
                certo = set(t["esperado"]) <= nomes_llm
                fallback += any(a["origem"] == "fallback" for a in t["acoes"])
            else:  # fala sem evidência: nada que mude estado sem pedido
                proibidas = {"emitir_rascunho", "avancar_etapa", "solicitar_assinatura", "contar_bovinos_video",
                             "conciliar_nfe", "conciliar_gta", "integridade_foto", "geofence"}
                certo = not (nomes_llm & proibidas)
            acoes_n += 1
            acoes_ok += certo
            por_tipo[t["tipo"]][0] += certo
            por_tipo[t["tipo"]][1] += 1
    return {
        "tool_calls": chamadas,
        "validade_apos_reparo": proporcao(validas, chamadas),
        "validade_1a_tentativa": proporcao(max(validas - reparos, 0), chamadas),
        "reparos": reparos, "negadas_politica": negadas, "invalidas_exemplos": invalidas_ex[:10],
        "acoes_corretas": proporcao(acoes_ok, acoes_n),
        "acoes_corretas_por_tipo": {k: proporcao(*v) for k, v in por_tipo.items()},
        "turnos_com_fallback": fallback,
        "latencia_turno_s": {"p50": percentil(lat_turno, 0.5), "p95": percentil(lat_turno, 0.95), "n": len(lat_turno)},
        "latencia_chamada_llm_s": {"p50": percentil(lat_llm, 0.5), "p95": percentil(lat_llm, 0.95), "n": len(lat_llm)},
    }


def todas(rs: list[dict[str, Any]], com_agente: bool = False) -> dict[str, Any]:
    m = {
        "n_casos": len(rs), "composicao": dict(Counter(r["classe"] for r in rs)),
        "recall_defeito": recall_defeito(rs), "falso_verificado": falso_verificado(rs),
        "over_blocking": over_blocking(rs), "abstencao": abstencao(rs), "seletiva": seletiva(rs),
        "finos_ferramenta": finos(rs), "ocorrencias": ocorrencias(rs), "grounding": grounding(rs),
        "regra_provisoria_usada": sum(1 for r in rs if r.get("provisoria")),
    }
    if com_agente:
        m["agente"] = agente(rs)
    return m


# ---------------------------------------------------------------------------
# Repetição da mesma rodada (L60): quanto o resultado varia entre execuções
# ---------------------------------------------------------------------------


def resumo_principal(m: dict[str, Any]) -> dict[str, Any]:
    """Os números do slide de um split (proporções com k/n; grounding e latência como valores)."""
    out = {"recall_defeito": m["recall_defeito"]["caso"], "over_blocking": m["over_blocking"]["campos_rotulados"],
           "abstencao_correta": m["abstencao"]["correta"], "falso_verificado": m["falso_verificado"]["campo"],
           "acuracia_seletiva": m["seletiva"]["acuracia_seletiva"],
           "numeros_sem_lastro": m["grounding"]["numeros_sem_lastro"]}
    ag = m.get("agente")
    if ag:
        out |= {"tool_call_valida_1a": ag["validade_1a_tentativa"], "acoes_corretas": ag["acoes_corretas"],
                "latencia_turno_p50_s": ag["latencia_turno_s"]["p50"],
                "latencia_turno_p95_s": ag["latencia_turno_s"]["p95"]}
    return out


def _fala_turno(t: dict[str, Any]) -> str:
    return (t.get("fala") or "").strip()


def comparar_rodadas(casos_a: dict[str, list[dict[str, Any]]], casos_b: dict[str, list[dict[str, Any]]],
                     splits_a: dict[str, Any] | None = None, splits_b: dict[str, Any] | None = None
                     ) -> dict[str, Any]:
    """Compara duas execuções do mesmo conjunto caso a caso (registros compactos de `run_eval.compactar`): status
    de cada campo do laudo, decisão de emissão, ações e fala de cada turno. Com temperature 0 e seed fixa, o
    esperado é igualdade; o que mudar é variação do próprio sistema (GPU, Ollama, tempo), não amostragem."""
    out: dict[str, Any] = {}
    for split in sorted(set(casos_a) & set(casos_b)):
        ia, ib = {r["id"]: r for r in casos_a[split]}, {r["id"]: r for r in casos_b[split]}
        ids = sorted(set(ia) & set(ib))
        status_dif, emissao_dif, turnos_n, acoes_dif, falas_dif, exemplos_fala = [], [], 0, 0, 0, []
        for cid in ids:
            ra, rb = ia[cid], ib[cid]
            sa = {g: v.get("sistema") for g, v in ra["grupos"].items()}
            sb = {g: v.get("sistema") for g, v in rb["grupos"].items()}
            if sa != sb:
                status_dif.append({"id": cid, "campos": {g: [sa.get(g), sb.get(g)] for g in sorted(set(sa) | set(sb))
                                                         if sa.get(g) != sb.get(g)}})
            if ra.get("emissao_permitida") != rb.get("emissao_permitida"):
                emissao_dif.append(cid)
            ta, tb = ra.get("turnos") or [], rb.get("turnos") or []
            turnos_n += max(len(ta), len(tb))
            for x, y in zip(ta, tb, strict=False):
                acoes_dif += x.get("acoes") != y.get("acoes")
                if _fala_turno(x) != _fala_turno(y):
                    falas_dif += 1
                    if len(exemplos_fala) < 3:
                        exemplos_fala.append({"id": cid, "a": _fala_turno(x)[:160], "b": _fala_turno(y)[:160]})
            dif_n = abs(len(ta) - len(tb))
            acoes_dif += dif_n
            falas_dif += dif_n
        d: dict[str, Any] = {
            "n_casos": len(ids), "so_numa_rodada": sorted(set(ia) ^ set(ib)),
            "casos_com_status_diferente": proporcao(len(status_dif), len(ids)),
            "emissao_diferente": proporcao(len(emissao_dif), len(ids)),
            "turnos_com_acoes_diferentes": proporcao(acoes_dif, turnos_n),
            "turnos_com_fala_diferente": proporcao(falas_dif, turnos_n),
            "status_diferentes": status_dif[:10], "emissao_ids": emissao_dif, "exemplos_fala": exemplos_fala,
        }
        if splits_a and splits_b and split in splits_a and split in splits_b:
            pa, pb = resumo_principal(splits_a[split]), resumo_principal(splits_b[split])
            d["numeros"] = {k: [pa.get(k), pb.get(k)] for k in pa}
            d["numeros_iguais"] = all(_valor(pa.get(k)) == _valor(pb.get(k)) for k in pa
                                      if not k.startswith("latencia"))
        d["identica"] = (not status_dif and not emissao_dif and not acoes_dif and not falas_dif
                         and not d["so_numa_rodada"])
        out[split] = d
    return out


def _valor(x: Any) -> Any:
    return (x.get("k"), x.get("n")) if isinstance(x, dict) else x


def frase_repeticao(d: dict[str, Any]) -> str:
    """Frase honesta para qualquer resultado da repetição (escrita antes de rodar)."""
    if d.get("identica"):
        return ("idêntica caso a caso (status, emissão, ações e falas). Com temperature 0 e seed fixa isso é o "
                "esperado: mostra que a rodada é reproduzível nesta máquina, não que o resultado valeria com outro "
                "modelo, outra quantização ou outras sementes de geração do golden.")
    st, em = d["casos_com_status_diferente"]["k"], d["emissao_diferente"]["k"]
    if st == 0 and em == 0:
        return ("os status e as decisões de emissão foram os mesmos; mudaram só falas ou ações intermediárias, o que "
                "não muda nenhum número do slide (o status vem do verificador, não do LLM).")
    return (f"{st} de {d['n_casos']} casos mudaram algum status e {em} a decisão de emissão, com o mesmo código, "
            "modelo e opções: o sistema não é determinístico de ponta a ponta nesta máquina, e o número do teste "
            "deve ser dito como o intervalo das duas execuções, não como um valor exato.")
