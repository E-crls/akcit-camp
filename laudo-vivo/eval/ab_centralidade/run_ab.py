"""A/B de centralidade (P1): o mesmo app SEM LLM (checklist fixo do rulebook + as mesmas ferramentas acionadas
por botão, em ordem fixa) contra o agente, com um fiscal roteirizado (`fiscal_simulado.py`).

Uso (na raiz do repositório):
  scripts/py.sh eval/ab_centralidade/run_ab.py                 # casos válidos do dev × perfis P1–P3 × 2 braços
  scripts/py.sh eval/ab_centralidade/run_ab.py --casos GLD-0002 --perfis P3

Braços:
- `checklist` (baseline): o fiscal vê na tela a lista fixa dos requisitos do rulebook (de `planejar_metodo`), na
  ordem do rulebook, com o status e o texto de pedido estático dos que faltam; cada envio é um botão que roda as
  mesmas ferramentas (condutor sem LLM). Não há fala.
- `agente`: o fiscal fala e ouve o agente (condutor com LLM local); só a fala do agente orienta o fiscal.

Medidas por episódio: evidência suficiente ao sair da fazenda (os 5 campos rotulados + declaração de
independência verificados), turnos até ficar suficiente, turnos totais, turnos ociosos, pendências com que o
fiscal foi embora, pendências nunca pedidas, pedido de correção logo depois de um erro do fiscal, e tempo.
Só usa casos VÁLIDOS do split dev (o teste fica para o número final do golden set).

Relatório reprodutível (L59, desde a onda 3): o `config` traz, além do sha256(src/), o sha256(eval/), o manifesto
do golden, o modelo com digest, a versão do Ollama e as opções de geração ("n/a" no braço sem LLM), os modelos
carregados no início e no fim, os casos, perfis e braços, o sha256 do fiscal simulado e as bibliotecas
(`montar_config`). Na r4: `--sufixo _r4` (`eval/rodada_r4.py`).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))
sys.path.insert(0, str(AQUI))

import fiscal_simulado as FS
import harness as H
import metrics as M

GRUPOS = ["quantidade", "comprovante_nfe", "gta", "integridade_foto", "localizacao"]
TIPO_DO_GRUPO = {"quantidade": "video", "comprovante_nfe": "nfe", "gta": "gta", "integridade_foto": "foto",
                 "localizacao": "foto", "independencia_fiscal": "declaracao"}
MAX_TURNOS = 22


def campos_suficiencia(caso: dict[str, Any]) -> dict[str, str]:
    out = {g: H.campo_sistema(caso, g) for g in GRUPOS}
    out["independencia_fiscal"] = "laudo:independencia_fiscal"
    return out


def mensagem_checklist(cond, fis_id: str) -> str:
    """Tela do baseline: requisitos bloqueantes do rulebook, na ordem fixa, só os que não estão verificados."""
    fis = cond.repo.carregar(fis_id)
    res = cond.verificador.recalcular(fis)
    linhas = []
    for r in res.requisitos or fis.requisitos:
        if not r.get("obrigatorio", r.get("bloqueante", True)):
            continue
        c = res.campos.get(r.get("campo", ""))
        st = c.status if c else "pendente"
        if st == "verificado":
            continue
        linhas.append(f"Falta — {r.get('descricao', '')} ({st}): {r.get('pedido', '')}.")  # uma frase por item
    return "\n".join(linhas)


def estado(cond, fis_id: str, caso: dict[str, Any]) -> dict[str, str]:
    fis = cond.repo.carregar(fis_id)
    res = cond.verificador.recalcular(fis)
    return {k: (res.campos.get(n).status if res.campos.get(n) else "ausente")
            for k, n in campos_suficiencia(caso).items()}


def episodio(caso: dict[str, Any], perfil: str, braco: str, amb: H.Ambiente, prov) -> dict[str, Any]:
    sufixo = f"_{perfil}_{braco}"
    dcaso = H.DIR_CASOS / caso["id"]
    dtrab = amb.dir_caso(caso["id"] + sufixo)
    fiscal = FS.Fiscal(caso, dcaso, dtrab, perfil)
    reg = H.montar_registro(caso, dcaso, "app", fiscal.saidas_video())
    provedor = prov if braco == "agente" else None
    if provedor is not None:
        provedor.hoje = date.fromisoformat(caso["data_fiscalizacao"])
    cond, fis, _, _ = H.preparar_condutor(caso, amb, provedor, registro=reg, sufixo=sufixo)
    t0 = time.perf_counter()
    falas_fiscal: list[str] = []
    msgs: list[str] = []
    lat: list[float] = []

    def turno(texto: str, evidencia: dict[str, Any] | None, agora: datetime) -> str:
        t = H.Turno("ab", texto, evidencia=evidencia, agora=agora)
        reg_t = H.executar_turno(cond, fis.id, t)
        lat.append(reg_t["latencia_s"])
        if braco == "agente":
            return reg_t["fala"]
        return mensagem_checklist(cond, fis.id)

    msg = turno("Bom dia, cheguei na fazenda para a fiscalização." if braco == "agente" else "", None,
                fiscal.avancar_relogio(0))
    msgs.append(msg)
    n_turnos = ociosos = 0
    suficiente_em = None
    erros_pendentes: list[str] = []  # erro do fiscal à espera de correção na próxima mensagem
    acompanhamento = {"certo": 0, "n": 0}
    while n_turnos < MAX_TURNOS:
        acao, item = fiscal.responder(msg)
        n_turnos += 1
        if acao == "fim":
            falas_fiscal.append(item.texto)
            break
        if acao in ("ocioso", "recusa"):
            ociosos += acao == "ocioso"
            falas_fiscal.append(item.texto)
            if acao == "recusa":
                erros_pendentes.append("gta")
            if braco == "agente":
                msg = turno(item.texto, None, fiscal.avancar_relogio(2))
                msgs.append(msg)
            # no checklist a tela não muda: o fiscal volta a olhar a mesma lista
        else:
            agora = fiscal.avancar_relogio(4)
            cap = (item.evidencia or {}).get("capturada_em")
            if cap and agora < cap + timedelta(minutes=3):
                agora = cap + timedelta(minutes=3)
                fiscal.relogio = agora
            falas_fiscal.append(item.texto)
            # no checklist não há fala; a declaração de conclusão vai no campo de texto do formulário
            texto = item.texto if braco == "agente" or item.evidencia is None else ""
            msg = turno(texto, item.evidencia, agora)
            msgs.append(msg)
            if item.erro:
                erros_pendentes.append(item.tipo)
        for tipo in list(erros_pendentes):  # a mensagem logo depois do erro pede a correção específica?
            if acao in ("ocioso", "recusa") and braco == "checklist" and tipo != "gta":
                continue
            acompanhamento["n"] += 1
            pediu = tipo in {t for _, t in FS.tipos_pedidos(msg)}
            acompanhamento["certo"] += pediu
            erros_pendentes.remove(tipo)
        if suficiente_em is None and all(v == "verificado" for v in estado(cond, fis.id, caso).values()):
            suficiente_em = n_turnos
    final = estado(cond, fis.id, caso)
    faltando = [k for k, v in final.items() if v != "verificado"]
    nunca = sorted({TIPO_DO_GRUPO[k] for k in faltando if not fiscal.pedidos_vistos.get(TIPO_DO_GRUPO[k])})
    return {
        "caso": caso["id"], "perfil": perfil, "braco": braco, "suficiente": not faltando,
        "turnos_ate_suficiente": suficiente_em, "turnos": n_turnos, "ociosos": ociosos,
        "faltando": faltando, "nunca_pedidas": nunca, "entregas": fiscal.entregas,
        "acompanhamento": acompanhamento, "tempo_s": round(time.perf_counter() - t0, 2),
        "latencia_turno_s": lat, "final": final,
        "dialogo": [{"sistema": m[:400], "fiscal": f} for m, f in zip(msgs, falas_fiscal + [""], strict=False)],
    }


def resumo(eps: list[dict[str, Any]]) -> dict[str, Any]:
    out = {}
    for braco in ("checklist", "agente"):
        e = [x for x in eps if x["braco"] == braco]
        if not e:
            continue
        suf = [x for x in e if x["suficiente"]]
        ac = {"certo": sum(x["acompanhamento"]["certo"] for x in e), "n": sum(x["acompanhamento"]["n"] for x in e)}
        lat = [v for x in e for v in x["latencia_turno_s"]]
        out[braco] = {
            "n": len(e), "suficiente": M.proporcao(len(suf), len(e)),
            "turnos_ate_suficiente_mediana": M.percentil([x["turnos_ate_suficiente"] for x in suf], 0.5),
            "turnos_media": sum(x["turnos"] for x in e) / len(e),
            "ociosos_media": sum(x["ociosos"] for x in e) / len(e),
            "saiu_com_pendencia": M.proporcao(len(e) - len(suf), len(e)),
            "pendencias_nunca_pedidas": sum(len(x["nunca_pedidas"]) for x in e),
            "faltando": dict(Counter(f for x in e for f in x["faltando"])),
            "acompanhamento_correto": M.proporcao(ac["certo"], ac["n"]),
            "tempo_episodio_s_mediana": M.percentil([x["tempo_s"] for x in e], 0.5),
            "latencia_turno_p95_s": M.percentil(lat, 0.95),
            "por_perfil": {p: M.proporcao(sum(x["suficiente"] for x in e if x["perfil"] == p),
                                          sum(1 for x in e if x["perfil"] == p))
                           for p in sorted({x["perfil"] for x in e})},
        }
    # pareado: mesmo caso e perfil nos dois braços
    pares = {}
    for x in eps:
        pares.setdefault((x["caso"], x["perfil"]), {})[x["braco"]] = x["suficiente"]
    so_ag = sum(1 for v in pares.values() if v.get("agente") and not v.get("checklist"))
    so_ck = sum(1 for v in pares.values() if v.get("checklist") and not v.get("agente"))
    out["pareado"] = {"n_pares": len(pares), "so_agente_suficiente": so_ag, "so_checklist_suficiente": so_ck,
                      "mcnemar_p_exato": _mcnemar(so_ag, so_ck)}
    return out


def _mcnemar(b: int, c: int) -> float | None:
    """p bicaudal exato de McNemar (binomial com p=0,5 nos pares discordantes)."""
    from math import comb

    n = b + c
    if n == 0:
        return None
    k = min(b, c)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)


def relatorio_md(res: dict[str, Any]) -> str:
    cfg, s = res["config"], res["resumo"]
    ck, ag = s.get("checklist", {}), s.get("agente", {})

    def lin(nome: str, a: Any, b: Any) -> str:
        return f"| {nome} | {a} | {b} |"

    def num(x: Any, casas: int = 1) -> str:
        return "n/d" if x is None else f"{x:.{casas}f}".replace(".", ",")

    p = s["pareado"]
    linhas = [
        f"# A/B de centralidade — checklist sem LLM × agente ({cfg['data']})", "",
        (f"- {cfg['n_casos']} casos válidos do split dev × perfis {', '.join(cfg['perfis'])} = {p['n_pares']} pares; "
         f"LLM do agente: {cfg.get('modelo')}; tempo total {cfg['duracao_s']:.0f} s; "
         f"`sha256(src/)={cfg['sha256_src'][:16]}…`."),
        (f"- Gerado por `scripts/py.sh eval/ab_centralidade/run_ab.py {' '.join(cfg['argv'])}`. Fiscal simulado: "
         "`eval/ab_centralidade/fiscal_simulado.py` (perfis: P1 foto fora da gleba; P2 + esquece a GTA; P3 + vídeo "
         "ruim)."), *H.linha_reprodutibilidade(cfg), "",
        "| Medida | Checklist (sem LLM) | Agente |", "|---|---|---|",
        lin("**Saiu da fazenda com evidência suficiente**", M.fmt(ck.get("suficiente"), True),
            M.fmt(ag.get("suficiente"), True)),
        lin("Saiu com pendência (precisaria voltar)", M.fmt(ck.get("saiu_com_pendencia"), True),
            M.fmt(ag.get("saiu_com_pendencia"), True)),
        lin("Pendências nunca pedidas ao fiscal", ck.get("pendencias_nunca_pedidas"), ag.get("pendencias_nunca_pedidas")),
        lin("Pedido de correção logo após erro do fiscal", M.fmt(ck.get("acompanhamento_correto"), True),
            M.fmt(ag.get("acompanhamento_correto"), True)),
        lin("Turnos até ficar suficiente (mediana)", num(ck.get("turnos_ate_suficiente_mediana")),
            num(ag.get("turnos_ate_suficiente_mediana"))),
        lin("Turnos por episódio (média)", num(ck.get("turnos_media")), num(ag.get("turnos_media"))),
        lin("Turnos ociosos — fiscal sem saber o que fazer (média)", num(ck.get("ociosos_media")),
            num(ag.get("ociosos_media"))),
        lin("Tempo de máquina por episódio, mediana (s)", num(ck.get("tempo_episodio_s_mediana")),
            num(ag.get("tempo_episodio_s_mediana"))),
        lin("Latência por turno p95 (s)", num(ck.get("latencia_turno_p95_s"), 2), num(ag.get("latencia_turno_p95_s"), 2)),
        lin("Campos que ficaram faltando", ck.get("faltando"), ag.get("faltando")), "",
        "Suficiência por perfil: " + "; ".join(
            f"{b}: " + ", ".join(f"{k} {M.fmt(v)}" for k, v in s[b]["por_perfil"].items())
            for b in ("checklist", "agente") if b in s), "",
        (f"Pareado (mesmo caso e perfil): só o agente suficiente em {p['so_agente_suficiente']}, só o checklist em "
         f"{p['so_checklist_suficiente']}; McNemar exato p = {num(p['mcnemar_p_exato'], 3)}."), "",
    ]
    return "\n".join(linhas) + "\n"


def montar_config(a: argparse.Namespace, ids: list[str], split: dict[str, Any], prov, llm: dict[str, Any],
                  duracao_s: float, ps_inicio: list[str] | None, ps_fim: list[str] | None) -> dict[str, Any]:
    """`config` do relatório (L59): além do sha256(src/), o que torna a rodada reprodutível — argumentos, casos,
    perfis e braços, split, versão do fiscal simulado, modelos carregados no Ollama no início e no fim e, via
    `harness.config_reprodutivel`, sha256(eval/), manifesto do golden, modelo com digest, versão do Ollama,
    opções de geração e bibliotecas ("n/a" sem LLM)."""
    config = {"data": H.data_rodada(), "argv": H.argv_seguro(sys.argv[1:]),
              "modelo": getattr(prov, "modelo", None), "perfil_llm": a.perfil_llm if prov else None,
              "n_casos": len(ids), "casos": ids, "perfis": a.perfis, "bracos": a.bracos,
              "duracao_s": duracao_s, "sha256_src": H.hash_src(),
              "sha256_split": split["sha256_split"], "sha256_conteudo_dev": split["sha256_conteudo"]["dev"],
              "congelado": split.get("congelado"), "ollama_ps_inicio": ps_inicio, "ollama_ps_fim": ps_fim,
              "fiscal_simulado_sha256": H.sha256_arquivo(AQUI / "fiscal_simulado.py")}
    return config | H.config_reprodutivel(llm=llm, split=split)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--casos", nargs="*")
    ap.add_argument("--perfis", nargs="*", default=["P1", "P2", "P3"])
    ap.add_argument("--bracos", nargs="*", default=["checklist", "agente"])
    ap.add_argument("--perfil-llm", default="escritorio")
    ap.add_argument("--modelo", default=None)
    ap.add_argument("--saida", default=str(H.REPO / "eval" / "reports"))
    ap.add_argument("--manter-modelo", action="store_true")
    ap.add_argument("--sufixo", default="", help="sufixo do nome do relatório (não sobrescreve o do mesmo dia)")
    a = ap.parse_args()
    split = H.carregar_split()
    if H.conferir_split(split):
        raise SystemExit("SPLIT.yaml não confere")
    validos = [c["id"] for c in split["casos"] if c["split"] == "dev" and c["classe"] == "valido"]
    ids = a.casos or validos
    if set(ids) - set(split["dev"]):
        raise SystemExit("o A/B só usa casos do dev")
    prov = None
    if "agente" in a.bracos:
        from laudo.llm.provider import OllamaProvider

        prov = OllamaProvider(modelo=a.modelo, perfil=a.perfil_llm)
        if not prov.disponivel():
            raise SystemExit("Ollama indisponível")
    llm = H.info_llm(prov)  # L59: digest, versão do Ollama e opções no início da rodada ("n/a" sem LLM)
    ps_inicio = H.ollama_ps() if prov is not None else None
    amb = H.Ambiente(rotulo="ab_centralidade")
    t0 = time.perf_counter()
    eps = []
    ps_fim = None
    try:
        for cid in ids:
            caso = H.carregar_caso(cid)
            for perfil in a.perfis:
                for braco in a.bracos:
                    e = episodio(caso, perfil, braco, amb, prov)
                    eps.append(e)
                    print(f"{cid} {perfil} {braco:9s} suficiente={e['suficiente']!s:5s} turnos={e['turnos']:2d} "
                          f"ociosos={e['ociosos']} faltando={e['faltando']} entregas={e['entregas']}", flush=True)
    finally:
        ps_fim = H.ollama_ps() if prov is not None else None
        if prov is not None and not a.manter_modelo:
            print("descarregando o modelo:", prov.descarregar())
    config = montar_config(a, ids, split, prov, llm, time.perf_counter() - t0, ps_inicio, ps_fim)
    res = {"config": config, "resumo": resumo(eps), "episodios": eps}
    md = relatorio_md(res)
    print("\n" + md)
    if a.casos:
        return 0
    out = Path(a.saida)
    out.mkdir(parents=True, exist_ok=True)
    nome = f"{res['config']['data']}_ab_centralidade{a.sufixo}"
    (out / f"{nome}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / f"{nome}.md").write_text(md, encoding="utf-8")
    print(f"relatório: {out / (nome + '.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
