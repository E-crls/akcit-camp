"""Narração livre da fiscal → alegações (extrator do condutor) → `conciliar_alegacoes`, contra os rótulos do
conjunto bagunçado. Mede o componente de fala isolado (com a evidência verdadeira do caso).

Modos (a fala passa antes por `laudo.speech.numeros.normalizar`, como na API de voz, salvo nos modos `*_bruto`):
- `llm`: o extrator do condutor como está (saída estruturada do LLM local + extrator determinístico);
- `regex`: só o extrator determinístico (o condutor sem LLM) — o "sem IA" da fala;
- `llm_bruto` / `regex_bruto`: o mesmo, sem a normalização de números falados (texto digitado);
- sufixo `_v0`: emula o condutor antes da rodada 2 (alegação com número por extenso era descartada).

Uso (na raiz; o modo `llm` precisa do Ollama com qwen3.5:4b):
  scripts/py.sh eval/ab_centralidade_v2/avaliar_narracoes.py --split dev --modos llm regex --rotulo v0
  # L07, split de teste congelado (os mesmos 5 modos da r3 no dev; ~5 min; numa linha só):
  scripts/py.sh eval/ab_centralidade_v2/avaliar_narracoes.py --split test --rotulo r4
      --modos llm regex llm_bruto regex_bruto llm_bruto_v0 --final --motivo "L07 AB v2 no teste r4"
Saída: `dados_locais/eval/narracoes_<split>_<rotulo>.jsonl` e, ao lado, `narracoes_<split>_<rotulo>.meta.json`
(modelo, digest, versão do Ollama, opções de geração, sha256(src/) e sha256(eval/); L59). O split de teste está
congelado: `--split test|todos` (ou `--casos` com caso do teste) exige `--final` e `--motivo` e fica no
`golden/casos/registro_teste.jsonl` (L41).
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from datetime import date
from pathlib import Path
from typing import Any

import yaml

AQUI = Path(__file__).resolve().parent
REPO = AQUI.parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "eval"))

import harness as H

from laudo.agent import estado as est
from laudo.agent.condutor import Condutor, RespostaTurno
from laudo.contracts import Fiscalizacao, Operacao
from laudo.speech.numeros import normalizar as numeros_falados
from laudo.tools.alegacoes import conciliar
from laudo.vision.contagem import ParametrosContagem

MANIFESTO = REPO / "eval" / "golden" / "baguncados" / "MANIFESTO.yaml"
DIR_CASOS = REPO / "eval" / "golden" / "casos"


def checagens_verdadeiras(caso: dict[str, Any], rot_danfe: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Checagens com a evidência verdadeira do caso: contagem simulada (mesmos limiares do contador) e NF."""
    bov = next(i for i in caso["operacao"]["itens"] if i["tipo"] == "bovinos")
    v = caso["video"]["saida_simulada_contador"]
    pc = ParametrosContagem()
    abst = (v["confianca"] < pc.limiar_conf_media or v.get("oclusao_frac", 0) > pc.max_oclusao
            or (v["estimativa"] > 0 and (v["ic80"][1] - v["ic80"][0]) / 2 > max(1.0, pc.max_meia_largura_rel
                                                                                * v["estimativa"])))
    chk = [{"ferramenta": "contar_bovinos_video", "status": "indeterminado" if abst else "ok", "item_id": bov["id"],
            "resultado": {"contagem": v["estimativa"], "intervalo": v["ic80"]}}]
    unid = [(r[k], r[k.replace("quantidade", "unidade")]) for r in rot_danfe for k in r if k.endswith(".quantidade")]
    cab = int(sum(q for q, _ in unid)) if unid and all(u in ("CB", "CAB", "UN") for _, u in unid) else None
    valor = round(sum(r.get("v_prod") or 0 for r in rot_danfe), 2)
    chk.append({"ferramenta": "conciliar_nfe", "status": "ok", "item_id": bov["id"],
                "resultado": {"totais": {"cabecas": cab, "valor_bovinos_rs": valor}}})
    return chk


def pontuar(esperadas: list[dict[str, Any]], obtidas: list[dict[str, Any]]) -> dict[str, Any]:
    """Casa alegação esperada × obtida por (grandeza, valor); status vem de `conciliar_alegacoes`."""
    usadas: set[int] = set()
    por_esp = []
    for e in esperadas:
        j = next((i for i, o in enumerate(obtidas) if i not in usadas
                  and (o["grandeza"] == e["grandeza"] or e["status"] == "registro")
                  and abs(float(o["valor"]) - float(e["valor"])) < 1e-9), None)
        if j is None:
            por_esp.append({**e, "capturada": False, "status_obtido": None, "correta": False})
            continue
        usadas.add(j)
        st = obtidas[j]["status"]
        por_esp.append({**e, "capturada": True, "status_obtido": st, "correta": st == e["status"]})
    espurias = [o for i, o in enumerate(obtidas) if i not in usadas]
    return {"esperadas": por_esp, "espurias": [{"trecho": o["trecho"], "grandeza": o["grandeza"],
                                                 "valor": o["valor"], "status": o["status"]} for o in espurias]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", default="dev", choices=["dev", "test", "todos"])
    ap.add_argument("--modos", nargs="*", default=["llm", "regex"])
    ap.add_argument("--rotulo", default="atual", help="versão do extrator (ex.: v0 antes da melhoria)")
    ap.add_argument("--casos", nargs="*")
    ap.add_argument("--final", action="store_true", help="autoriza o split de teste congelado (exige --motivo)")
    ap.add_argument("--motivo", default=None)
    a = ap.parse_args()
    man = yaml.safe_load(MANIFESTO.read_text(encoding="utf-8"))
    alvo = [c for c in man["casos"] if (a.split == "todos" or c["split"] == a.split)
            and (not a.casos or c["id"] in a.casos)]
    split = H.carregar_split()
    toca = H.toca_teste(split, {"alvo": [c["id"] for c in alvo]})
    erros = H.checar_uso_do_teste(toca, a.final, a.motivo, split)
    if erros:
        print("execução recusada:")
        for e in erros:
            print("  " + e)
        return 2
    saida = REPO / "dados_locais" / "eval" / f"narracoes_{a.split}_{a.rotulo}.jsonl"
    saida.parent.mkdir(parents=True, exist_ok=True)
    prov = None
    if any(m.startswith("llm") for m in a.modos):
        from laudo.llm.provider import OllamaProvider

        prov = OllamaProvider(modelo="qwen3.5:4b", perfil="escritorio")
    llm = H.info_llm(prov)
    meta = {"inicio": H.agora_iso(), "split": a.split, "modos": a.modos, "rotulo": a.rotulo, "casos": a.casos,
            "llm": llm, "sha256_src": H.hash_src(), "sha256_src_lf": H.hash_src_lf(),
            "sha256_eval": H.hash_eval()["sha256"], "final": bool(toca and a.final)}
    extra = {"split": a.split, "modos": a.modos, "rotulo": a.rotulo,
             "casos_teste": sorted({c["id"] for c in alvo if c["split"] == "test"}),
             "sha256_src": meta["sha256_src"], "llm": {k: llm.get(k) for k in ("modelo", "digest", "ollama_versao")}}
    with (H.uso_do_teste(toca and a.final, script="eval/ab_centralidade_v2/avaliar_narracoes.py",
                         alvo="ab_v2_test", motivo=a.motivo, argv=sys.argv[1:], extra=extra) as uso,
          tempfile.TemporaryDirectory() as tmp, saida.open("w", encoding="utf-8") as f):
        meta["execucao_registro"] = (uso or {}).get("execucao")
        repo = est.RepositorioFiscalizacoes(Path(tmp))
        for c in alvo:
            caso = yaml.safe_load((DIR_CASOS / c["id"] / "caso.yaml").read_text(encoding="utf-8"))
            hoje = date.fromisoformat(caso["data_fiscalizacao"])
            bruto = c["narracao"]["texto"]
            norm = numeros_falados(bruto)
            chk = checagens_verdadeiras(caso, c["rotulos"]["danfe"])
            for modo in a.modos:
                usa_llm = modo.startswith("llm")
                texto = bruto if "_bruto" in modo else norm.texto
                if usa_llm:
                    prov.hoje = hoje
                cond = Condutor(prov if usa_llm else None, repo=repo, registro={}, hoje=hoje,
                                extrair_alegacoes_llm=usa_llm)
                fis = Fiscalizacao(operacao=Operacao.model_validate(caso["operacao"]), data_referencia=hoje)
                resp = RespostaTurno(fiscalizacao_id=fis.id, turno=1, etapa=fis.estado_fsm, fala="")
                t0 = time.perf_counter()
                if modo.endswith("_v0"):  # sem o fallback de número por extenso no condutor
                    import laudo.speech.numeros as sn

                    orig = sn.normalizar
                    sn.normalizar = lambda t: type("R", (), {"numeros": []})()
                    try:
                        als = cond._extrair_alegacoes(fis, texto, "ev_fala", resp)
                    finally:
                        sn.normalizar = orig
                else:
                    als = cond._extrair_alegacoes(fis, texto, "ev_fala", resp)
                ms = int((time.perf_counter() - t0) * 1000)
                itens = [i for i in Operacao.model_validate(caso["operacao"]).itens]
                res = conciliar(als, itens, chk)
                p = pontuar(c["narracao"]["alegacoes_esperadas"], res["alegacoes"])
                reg = {"id": c["id"], "split": c["split"], "modo": modo, "rotulo": a.rotulo, "texto": texto,
                       "numeros_criticos": len(norm.criticos),
                       "palavras": c["narracao"]["palavras"], "ms": ms, "alegacoes": als, "conciliacao": res,
                       "avisos": resp.avisos, **p}
                f.write(json.dumps(reg, ensure_ascii=False, default=str) + "\n")
                ok = sum(e["correta"] for e in p["esperadas"])
                print(f"{c['id']} {modo:5s} {ok}/{len(p['esperadas'])} corretas; espúrias "
                      f"{[x['status'] for x in p['espurias']]} {ms} ms", flush=True)
        if uso is not None:
            uso["resultado"] = {"narracoes": len(alvo), "saida": H.argv_seguro([str(saida)])[0]}
    meta["fim"] = H.agora_iso()
    saida.with_name(saida.stem + ".meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1,
                                                                     default=str) + chr(10), encoding="utf-8")
    print("saída:", saida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
