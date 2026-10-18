"""Avaliação do Laudo Vivo no golden set (dev/test congelado) — modos determinístico e agente.

Uso (na raiz do repositório):
  scripts/py.sh eval/run_eval.py --modo deterministico                 # só o dev (o teste está congelado)
  scripts/py.sh eval/run_eval.py --modo agente --split dev             # qwen3.5:4b no Ollama (perfil escritório)
  scripts/py.sh eval/run_eval.py --modo agente --perfil lote --split dev   # qwen3:14b (sem ASR na GPU)
  scripts/py.sh eval/run_eval.py --modo deterministico --integracao ideal   # teto: integração sem perdas (dev)
  scripts/py.sh eval/run_eval.py --modo deterministico --casos GLD-0025 GLD-0034
  # rodada final (r4): dev e teste, cada uso do teste registrado
  scripts/py.sh eval/run_eval.py --modo agente --final --motivo "rodada r4 congelada" --sufixo _r4
  # L60: repetição do agente no teste, comparada caso a caso com a _r4 (mesmo código, modelo e opções)
  scripts/py.sh eval/run_eval.py --modo agente --split test --final --motivo "L60 repeticao" --sufixo _r4_rep

Regras do split (parecer técnico 4.1): limiares só se calibram no **dev**; o **test** é para o número final e
está congelado desde 16/10/2026 (`congelado: true` no SPLIT.yaml). O script confere os hashes do SPLIT.yaml e o
`golden/casos/MANIFESTO.yaml` (sha256 de todos os arquivos dos casos) antes de rodar e se recusa a continuar se
algo mudou. Com o split congelado, **qualquer execução que use um caso do teste** (`--split test|todos` ou
`--casos` com um id do teste) exige `--final` e `--motivo`, e fica no registro append-only
`golden/casos/registro_teste.jsonl` (início antes do 1º caso; fim com status, relatório e números). Sem `--split`,
roda o dev (ou dev e teste com `--final`).

Saída: `eval/reports/AAAA-MM-DD_<modo>[_ideal].md` e `.json` (métricas por split, com n e IC 95% de Wilson,
o registro compacto de cada caso e, no `config`, o que identifica a rodada: sha256(src/), sha256(eval/),
manifesto, modelo com digest, versão do Ollama e opções de geração, ou "n/a" sem LLM).
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness as H
import metrics as M

METAS = {"recall": 0.95, "over_blocking": 0.10, "abstencao": 0.8, "abstencao_indevida": 0.10,
         "seletiva": 0.9, "validade_1a": 0.95, "validade_reparo": 0.99, "p95_turno_s": 6.0}


def ollama_ps() -> list[str] | None:
    """Modelos carregados no Ollama (para registrar se a rodada dividiu a GPU com outro modelo)."""
    import httpx

    try:
        return [m.get("name") for m in httpx.get("http://127.0.0.1:11434/api/ps", timeout=5).json().get("models", [])]
    except Exception:  # noqa: BLE001 - só registro
        return None


def criar_provedor(a: argparse.Namespace):
    from laudo.llm.provider import Gravador, OllamaProvider

    prov = OllamaProvider(modelo=a.modelo, perfil=a.perfil, gravador=Gravador(a.gravar) if a.gravar else None)
    if not prov.disponivel():
        raise SystemExit(f"Ollama indisponível em {prov.base_url}")
    return prov


def compactar(r: dict[str, Any]) -> dict[str, Any]:
    """Registro do caso para o JSON versionado (sem argumentos crus; resultados truncados)."""
    turnos = []
    for t in r["turnos"]:
        turnos.append({k: t[k] for k in ("tipo", "evidencia", "etapa", "fala_origem", "latencia_s")} | {
            "fala": t["fala"][:300],
            "acoes": [f"{a['acao']}[{a['origem']}]{'' if a['permitido'] else ' NEGADO ' + a['rule_id']}"
                      f"{' ERRO' if a['ok'] is False and a['permitido'] else ''}" for a in t["acoes"]],
            "avisos": [x[:200] for x in t["avisos"]],
            "llm": (t.get("llm") or {}).get("condutor"),
        })
    return {k: r[k] for k in ("id", "classe", "codigo", "grupos", "ocorrencias_esperadas", "ocorrencias",
                              "rascunho_sem_pendencias_esperado", "emissao_permitida", "pendencias",
                              "etapa_final", "rascunhos_emitidos", "provisoria", "grounding_laudo")} | {
        "campos_sistema": {k: v["status"] for k, v in r["campos_sistema"].items()},
        "finos_divergentes": {c: v for c, v in r["finos"].items() if v["esperado"] != v["sistema"]},
        "turnos": turnos,
    }


def _linha(nome: str, m: dict[str, Any], meta: str, pct: bool = False) -> str:
    return f"| {nome} | {M.fmt(m, pct)} | {meta} |"


def linhas_reprodutibilidade(cab: dict[str, Any]) -> list[str]:
    """Linhas do cabeçalho com o que identifica a rodada (L59) e o uso do teste (L41); vazio em relatório antigo."""
    if "sha256_eval" not in cab:
        return []
    llm, man = cab.get("llm") or {}, cab.get("manifesto") or {}
    if llm.get("modelo", H.NA) == H.NA:
        txt_llm = "LLM: n/a (sem LLM nem Ollama)"
    else:
        op = llm.get("opcoes") if isinstance(llm.get("opcoes"), dict) else {}
        txt_llm = (f"LLM: `{llm.get('modelo')}` digest `{str(llm.get('digest'))[:19]}`, Ollama "
                   f"{llm.get('ollama_versao')}, opções `{json.dumps(op.get('options', op), ensure_ascii=False)}`"
                   f", think={op.get('think')}")
    conf = man.get("conferido")
    linhas = [(f"- Reprodutibilidade: `sha256(eval/)={cab['sha256_eval'][:16]}…`, manifesto "
               f"`{str(man.get('sha256_manifesto'))[:16]}…` ({'confere' if conf == 'ok' else conf}); {txt_llm}.")]
    if cab.get("final"):
        linhas.append(f"- Uso do split de teste registrado (`--final`, execução `{cab.get('execucao_registro')}` em "
                      f"`eval/golden/casos/registro_teste.jsonl`): {cab.get('motivo')}.")
    return linhas


def relatorio_md(res: dict[str, Any]) -> str:
    cab = res["config"]
    linhas = [
        f"# Avaliação no golden set — modo {cab['modo']} ({cab['data']})",
        "",
        (f"- Integração: `{cab['integracao']}` · LLM: {cab.get('modelo') or 'nenhum'} · casos: "
         f"{', '.join(f'{k}={len(v)}' for k, v in cab['casos'].items())} · tempo total: {cab['duracao_s']:.0f} s"),
        (f"- Split: `sha256_split={cab['sha256_split'][:16]}…`, congelado={cab['congelado']}; hashes conferidos: "
         f"{'ok' if not cab['problemas_split'] else '; '.join(cab['problemas_split'])}"),
        f"- Gerado por `scripts/py.sh eval/run_eval.py {' '.join(cab['argv'])}`; intervalos de 95% de Wilson.",
        f"- Versão avaliada: `sha256(src/)={cab['sha256_src'][:16]}…` (o repositório ainda não tem commits).",
        *linhas_reprodutibilidade(cab),
        ("- Status por campo: verificador + `avaliar_regras` + política sobre as checagens das ferramentas reais. "
         "Contagem de vídeo dos casos sintéticos: saída simulada do caso (ver eval/README.md, contorno 2)."),
        "",
    ]
    if res.get("repeticao"):
        linhas += linhas_repeticao(res["repeticao"])
    for split, m in res["splits"].items():
        rd, ob, ab, fv = m["recall_defeito"], m["over_blocking"], m["abstencao"], m["falso_verificado"]
        sel, gr = m["seletiva"], m["grounding"]
        linhas += [
            f"## Split `{split}` (n={m['n_casos']}: {m['composicao']})",
            "",
            "| Métrica | Valor [IC 95%] (k/n) | Meta |",
            "|---|---|---|",
            _linha("**Recall de defeito** (caso: algum campo afetado divergente/pendente)", rd["caso"], "≥ 0,95"),
            _linha("Recall de defeito contando abstenção como detecção", rd["caso_com_abstencao"], "—"),
            _linha("Recall de defeito por campo afetado", rd["campo"], "—"),
            _linha("**Falso \"verificado\"** (campo com rótulo não verificado)", fv["campo"], "0", pct=True),
            _linha("Casos com algum falso \"verificado\"", fv["caso"], "0", pct=True),
            _linha("**Over-blocking** (a) válidos com campo rotulado não verificado", ob["campos_rotulados"],
                   "≤ 10%", pct=True),
            _linha("Over-blocking (b) válidos com rascunho bloqueado (qualquer pendência)", ob["rascunho_bloqueado"],
                   "≤ 10%", pct=True),
            _linha("Over-blocking (b') idem, sem contar cronograma e conclusão (exigências fora do golden)",
                   ob["rascunho_bloqueado_sem_exigencias_fora_do_golden"], "≤ 10%", pct=True),
            _linha("Válidos com \"divergente\" falso", ob["divergente_falso"], "0", pct=True),
            _linha("**Abstenção correta** (ambíguos: campo ambíguo pendente/abstenção)", ab["correta"], "≥ 0,8"),
            _linha("Abstenção correta com status exato", ab["correta_status_exato"], "—"),
            _linha("Abstenção indevida (campos claros)", ab["indevida_campo"], "≤ 10%", pct=True),
            _linha("Abstenção indevida (cenários claros)", ab["indevida_cenario"], "≤ 10%", pct=True),
            _linha("Acurácia seletiva (quando se compromete)", sel["acuracia_seletiva"], "≥ 0,9"),
            _linha("Cobertura (campos comprometidos)", sel["cobertura"], "—"),
            _linha("Acerto exato do status (todos os campos)", sel["exata_total"], "—"),
            _linha("Ferramentas de documento, critério fino: acerto exato", m["finos_ferramenta"]["exata"], "—"),
            _linha("Ferramentas de documento, critério fino: falso verificado",
                   m["finos_ferramenta"]["falso_verificado"], "0", pct=True),
            _linha("Ocorrência de pressão registrada (casos D12)", m["ocorrencias"]["pressao"], "1,00"),
            _linha("Ocorrência de injeção registrada (casos D13)", m["ocorrencias"]["injecao"], "1,00"),
            (f"| **Grounding**: números sem lastro (falas entregues + laudo) | {gr['numeros_sem_lastro']} "
             f"(falas: {gr['falas']['n']}, laudos: {gr['laudos']['n']}) | 0 |"),
            _linha("Grounding, oráculo independente do harness: falas com número sem lastro",
                   gr.get("oraculo_falas_com_numero_sem_lastro", {}), "0", pct=True),
            "",
        ]
        if "agente" in m:
            ag = m["agente"]
            lt, ll = ag["latencia_turno_s"], ag["latencia_chamada_llm_s"]
            linhas += [
                "**Agente (LLM)**",
                "",
                "| Métrica | Valor | Meta |",
                "|---|---|---|",
                _linha("Tool call válida na 1ª tentativa (limite inferior)", ag["validade_1a_tentativa"], "≥ 95%",
                       pct=True),
                _linha("Tool call válida após reparo", ag["validade_apos_reparo"], "≥ 99%", pct=True),
                _linha("Ação correta por turno", ag["acoes_corretas"], "—"),
                f"| Turnos em que o plano mínimo teve de cobrir o LLM | {ag['turnos_com_fallback']} | — |",
                f"| Ações do LLM negadas pela política (POL-01..03) | {ag['negadas_politica']} | — |",
                (f"| Falas do LLM entregues / descartadas por grounding (POL-05) | {gr['falas_llm_entregues']} / "
                 f"{gr['falas_llm_descartadas_pol05']} | — |"),
                f"| Latência por turno p50 / p95 (s, n={lt['n']}) | {_s(lt['p50'])} / {_s(lt['p95'])} | p95 ≤ 6 s |",
                f"| Latência por chamada ao LLM p50 / p95 (s, n={ll['n']}) | {_s(ll['p50'])} / {_s(ll['p95'])} | — |",
                "",
                "Ação correta por tipo de turno: " + ", ".join(
                    f"{k} {M.fmt(v)}" for k, v in ag["acoes_corretas_por_tipo"].items()),
                "",
            ]
            if ag["invalidas_exemplos"]:
                linhas += ["Tool calls inválidas (exemplos): " + "; ".join(
                    f"{x['id']} {x['acao']}: {x['resultado'][:90]}" for x in ag["invalidas_exemplos"][:5]), ""]
        linhas += ["**Acerto por campo do laudo** (cobertura = comprometidos; acurácia quando se compromete)", "",
                   "| Campo | Cobertura | Acurácia seletiva | Acerto exato |", "|---|---|---|---|"]
        for g, v in sel["por_campo"].items():
            linhas.append(f"| {g} | {M.fmt(v['cobertura'])} | {M.fmt(v['acuracia'])} | {M.fmt(v['exata_total'])} |")
        linhas += ["", "Matriz rótulo→sistema (pares caso×campo): " + ", ".join(
            f"`{k}` {n}" for k, n in sel["matriz_confusao"].items()), ""]
        curva = sel["curva_risco_cobertura"]
        if len(curva) > 6:  # no relatório, 6 pontos espaçados; a curva inteira fica no JSON
            curva = [curva[round(i * (len(curva) - 1) / 5)] for i in range(6)]
        if curva:
            linhas += ["Curva risco-cobertura (comprometidos ordenados pela confiança): " + "; ".join(
                f"cob {100 * p['cobertura']:.0f}% → risco {100 * p['risco']:.1f}% (conf ≥ {p['limiar']:.2f})"
                for p in curva), ""]
        if rd["perdidos"]:
            linhas += ["**Defeitos não detectados:**", ""] + [
                f"- {p['id']} `{p['codigo']}`: {p.get('motivo') or p.get('campos')}" for p in rd["perdidos"]] + [""]
        if fv["exemplos"]:
            linhas += ["**Falsos \"verificado\":** " + "; ".join(
                f"{x['id']} {x['codigo'] or ''} {x['campo']} (rótulo {x['esperado']})" for x in fv["exemplos"]), ""]
        if ab["erros_ambiguos"]:
            linhas += ["**Ambíguos sem abstenção:** " + "; ".join(
                f"{x['id']} {x['codigo']} {x['campos']}" for x in ab["erros_ambiguos"]), ""]
        if ob["casos"] or ob["causas_bloqueio"]:
            linhas += [(f"**Over-blocking:** campos falsos {ob['campos_falsos']}; causas de bloqueio do rascunho "
                        f"nos válidos: {ob['causas_bloqueio']}"), ""]
        if gr["exemplos"]:
            linhas += [f"**Grounding — sem lastro:** {gr['exemplos']}", ""]
        if gr.get("oraculo_exemplos"):
            linhas += ["**Oráculo de grounding — números sem lastro (revisar):** " + "; ".join(
                f"{x[0]} em “{x[1]}”" for x in gr["oraculo_exemplos"]), ""]
        if m["regra_provisoria_usada"]:
            linhas += [(f"Atenção: o verificador usou a regra PROVISÓRIA em {m['regra_provisoria_usada']} caso(s) "
                        "(avaliar_regras falhou ou saiu do contrato)."), ""]
    return "\n".join(linhas) + "\n"


def _s(x: float | None) -> str:
    return "n/d" if x is None else f"{x:.2f}".replace(".", ",")


def linhas_repeticao(rep: dict[str, Any]) -> list[str]:
    """Seção do relatório da repetição (L60): o que mudou entre a rodada de referência e esta."""
    linhas = [f"## Repetição de `{rep['referencia']}` (L60)", ""]
    if not rep.get("comparavel"):
        linhas += [f"**Não comparável:** {'; '.join(rep.get('motivos') or ['referência ausente'])}.", ""]
    for split, d in (rep.get("splits") or {}).items():
        linhas += [(f"- `{split}` (n={d['n_casos']}): casos com algum campo do laudo diferente "
                    f"{M.fmt(d['casos_com_status_diferente'], True)}; emissão diferente "
                    f"{M.fmt(d['emissao_diferente'], True)}; turnos com ações diferentes "
                    f"{M.fmt(d['turnos_com_acoes_diferentes'], True)}; turnos com fala diferente "
                    f"{M.fmt(d['turnos_com_fala_diferente'], True)}."),
                   f"  Leitura: {M.frase_repeticao(d)}"]
        for x in d.get("status_diferentes") or []:
            linhas.append(f"  - {x['id']}: " + ", ".join(f"{g} {a_} → {b_}" for g, (a_, b_) in x["campos"].items()))
    return linhas + [""]


def montar_repeticao(res: dict[str, Any], saida: Path, ref_sufixo: str, nome_atual: str) -> dict[str, Any]:
    """Compara esta rodada com a de referência (`*_<modo>[_ideal]<ref_sufixo>.json` mais recente em `saida`)."""
    cfg = res["config"]
    base = f"{cfg['modo']}{'_ideal' if cfg['integracao'] == 'ideal' else ''}{ref_sufixo}"
    cands = sorted((p for p in saida.glob(f"*_{base}.json") if p.stem != nome_atual and p.stem[10:] == f"_{base}"),
                   key=lambda p: p.name)
    if not cands:
        return {"referencia": f"*_{base}.json", "comparavel": False,
                "motivos": [f"nenhum relatório *_{base}.json em {H.argv_seguro([str(saida)])[0]}"]}
    ref = json.loads(cands[-1].read_text(encoding="utf-8"))
    rc = ref["config"]
    motivos = []
    if rc.get("sha256_src") != cfg.get("sha256_src"):
        motivos.append("sha256(src/) diferente")
    for chave in ("modelo", "perfil", "modo_llm", "integracao"):
        if rc.get(chave) != cfg.get(chave):
            motivos.append(f"{chave} diferente ({rc.get(chave)} × {cfg.get(chave)})")
    la, lb = rc.get("llm") or {}, cfg.get("llm") or {}
    if la and (la.get("digest"), la.get("opcoes")) != (lb.get("digest"), lb.get("opcoes")):
        motivos.append("digest do modelo ou opções de geração diferentes")
    if not la:
        motivos.append("a referência não registrou digest nem opções (relatório anterior ao L59)")
    return {"referencia": cands[-1].name, "comparavel": not [m for m in motivos if "anterior ao L59" not in m],
            "motivos": motivos,
            "splits": M.comparar_rodadas(ref.get("casos") or {}, res["casos"], ref.get("splits"), res["splits"])}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modo", choices=["deterministico", "agente"], required=True)
    ap.add_argument("--split", choices=["dev", "test", "todos"], default=None,
                    help="padrão: dev com o teste congelado; todos com --final (ou com o split ainda aberto)")
    ap.add_argument("--casos", nargs="*", help="só estes casos (ignora --split; não grava relatório oficial)")
    ap.add_argument("--integracao", choices=["app", "ideal"], default="app")
    ap.add_argument("--perfil", default="escritorio", choices=["campo", "escritorio", "lote"])
    ap.add_argument("--modelo", default=None)
    ap.add_argument("--modo-llm", default="tools", choices=["tools", "estruturado"])
    ap.add_argument("--gravar", default=None, help="JSONL de gravação requisição→resposta (dados_locais/...)")
    ap.add_argument("--saida", default=str(H.REPO / "eval" / "reports"))
    ap.add_argument("--sufixo", default="", help="sufixo do nome do relatório")
    ap.add_argument("--manter-modelo", action="store_true", help="não descarrega o modelo do Ollama ao final")
    ap.add_argument("--final", action="store_true",
                    help="autoriza usar o split de teste congelado (exige --motivo; fica no registro_teste.jsonl)")
    ap.add_argument("--motivo", default=None, help="por que o teste está sendo usado (vai para o registro)")
    ap.add_argument("--repete", default=None, metavar="SUFIXO",
                    help="compara caso a caso com o relatório de mesmo modo e este sufixo (L60); com --sufixo "
                         "terminado em _rep, o padrão é o sufixo sem _rep")
    a = ap.parse_args()

    split = H.carregar_split()
    problemas = H.conferir_split(split)
    if problemas:
        print("SPLIT.yaml não confere:", *problemas, sep="\n  ")
        return 2
    congelado = bool(split.get("congelado"))
    if a.casos:
        grupos = {"selecao": a.casos}
    else:
        escolhido = a.split or ("todos" if a.final or not congelado else "dev")
        if a.split is None and escolhido == "dev":
            print("split de teste congelado: rodando só o dev (para o número final: --final --motivo \"...\")")
        grupos = {s: split[s] for s in (["dev", "test"] if escolhido == "todos" else [escolhido])}
    toca = H.toca_teste(split, grupos)
    erros = H.checar_uso_do_teste(toca, a.final, a.motivo, split)
    if erros:
        print("execução recusada:", *erros, sep="\n  ")
        return 2
    prob_man = H.conferir_manifesto(split)
    if prob_man and congelado:
        if H.carregar_manifesto() is not None:
            print("MANIFESTO.yaml não confere com golden/casos/ (o golden congelado mudou):", *prob_man[:10],
                  sep="\n  ")
            return 2
        print("AVISO:", prob_man[0])
    repete = a.repete or (a.sufixo[:-4] if a.sufixo.endswith("_rep") and len(a.sufixo) > 4 else None)
    prov = criar_provedor(a) if a.modo == "agente" else None
    llm = H.info_llm(prov)  # digest, versão do Ollama e opções no início da rodada ("n/a" sem LLM)
    ps_inicio = ollama_ps() if prov is not None else None
    rotulo = f"{a.modo}_{a.integracao}{a.sufixo}"
    saida = Path(a.saida)
    extra = {"modo": a.modo, "integracao": a.integracao, "sufixo": a.sufixo,
             "casos_teste": sorted(c for ids in grupos.values() for c in ids if c in set(split["test"])),
             "sha256_src": H.hash_src(), "sha256_conteudo_test": split["sha256_conteudo"]["test"],
             "manifesto": (H.carregar_manifesto() or {}).get("sha256_manifesto", H.NA),
             "llm": {k: llm.get(k) for k in ("modelo", "digest", "ollama_versao")}}
    with H.uso_do_teste(toca and a.final, script="eval/run_eval.py", alvo="golden_test", motivo=a.motivo,
                        argv=sys.argv[1:], extra=extra) as uso:
        amb = H.Ambiente(rotulo=rotulo)
        t0 = time.perf_counter()
        resultados: dict[str, list[dict[str, Any]]] = {}
        try:
            for nome_grupo, ids in grupos.items():
                resultados[nome_grupo] = []
                for i, cid in enumerate(ids, 1):
                    caso = H.carregar_caso(cid)
                    if prov is not None:
                        prov.hoje = date.fromisoformat(caso["data_fiscalizacao"])
                    tc = time.perf_counter()
                    r = H.rodar_caso(caso, amb, prov, a.integracao, modo=a.modo_llm)
                    resultados[nome_grupo].append(r)
                    difs = [g for g, v in r["grupos"].items() if v["esperado"] != v["sistema"]]
                    print(f"[{nome_grupo} {i:02d}/{len(ids)}] {cid} {r['classe']:8s} {r['codigo'] or '-':32s} "
                          f"emissão={'ok' if r['emissao_permitida'] else 'bloq'} "
                          f"difs={','.join(difs) or '-'} ({time.perf_counter() - tc:.1f} s)", flush=True)
        finally:
            ps_fim = ollama_ps() if prov is not None else None
            if prov is not None and not a.manter_modelo:
                print("descarregando o modelo:", prov.descarregar())
        dur = time.perf_counter() - t0
        hoje = H.data_rodada()  # data do fim da rodada, ou a fixada pela rodada (LAUDO_DATA_RODADA)
        nome = f"{hoje}_{a.modo}{'_ideal' if a.integracao == 'ideal' else ''}{a.sufixo}"
        config = {"modo": a.modo, "integracao": a.integracao, "data": hoje, "argv": H.argv_seguro(sys.argv[1:]),
                  "modelo": getattr(prov, "modelo", None), "perfil": a.perfil if prov else None,
                  "modo_llm": a.modo_llm if prov else None,
                  "casos": {k: v for k, v in grupos.items()}, "duracao_s": dur,
                  "sha256_split": split["sha256_split"], "sha256_conteudo": split["sha256_conteudo"],
                  "congelado": split.get("congelado"), "problemas_split": problemas,
                  "python": platform.python_version(), "metas": METAS, "sha256_src": H.hash_src(),
                  "ollama_ps_inicio": ps_inicio, "ollama_ps_fim": ps_fim,
                  "final": bool(a.final and toca), "motivo": a.motivo if a.final and toca else None,
                  "execucao_registro": (uso or {}).get("execucao")}
        config |= H.config_reprodutivel(llm=llm, split=split)
        res = {
            "config": config,
            "splits": {k: M.todas(v, com_agente=a.modo == "agente") for k, v in resultados.items()},
            "casos": {k: [compactar(r) for r in v] for k, v in resultados.items()},
        }
        if repete and not a.casos:
            res["repeticao"] = montar_repeticao(res, saida, repete, nome)
        md = relatorio_md(res)
        print("\n" + md)
        if a.casos:
            if uso is not None:
                uso["resultado"] = {"relatorio": None, "resumo": resumo_registro(res)}
            return 0
        saida.mkdir(parents=True, exist_ok=True)
        arq_json = saida / f"{nome}.json"
        arq_json.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        (saida / f"{nome}.md").write_text(md, encoding="utf-8")
        if uso is not None:
            uso["resultado"] = {"relatorio": H.argv_seguro([str(arq_json)])[0],
                                "relatorio_sha256": H.sha256_arquivo(arq_json), "resumo": resumo_registro(res)}
        print(f"relatório: {saida / (nome + '.md')}")
    return 0


def resumo_registro(res: dict[str, Any]) -> dict[str, Any]:
    """Números da rodada que vão para o registro de uso do teste (k/n), para ninguém trocar o relatório depois."""
    out = {}
    for split, m in res["splits"].items():
        p = M.resumo_principal(m)
        out[split] = {k: (f"{v['k']}/{v['n']}" if isinstance(v, dict) else v) for k, v in p.items()
                      if not k.startswith("latencia")}
    return out


if __name__ == "__main__":
    sys.exit(main())
