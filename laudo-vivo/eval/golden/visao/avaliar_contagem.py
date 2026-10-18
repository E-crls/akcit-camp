"""Avalia o contador de bovinos contra `contagens_referencia.yaml` e os semissintéticos.

Uso (raiz do repositório):
    scripts/py.sh eval/golden/visao/avaliar_contagem.py [--modelos yolox_s yolox_m] [--fps 8]
Saída: eval/golden/visao/resultados_contagem.json e tabelas em Markdown no terminal.
Os vídeos ficam em dados_locais/ (fora do git); o script pula o que não encontrar.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import yaml

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ / "src"))

from laudo.tools.bovinos import EntradaContarBovinos, contar_bovinos_video
from laudo.vision.detector import DetectorYOLOX
from laudo.vision.modelos import MODELOS
from laudo.vision.video import iterar_quadros

AQUI = Path(__file__).parent
DIR_EV = RAIZ / "dados_locais" / "evidencias" / "visao" / "eval"


def rodar(video: str, modo: str, modelo: str, fps: float, rotulo: str) -> dict:
    e = contar_bovinos_video(EntradaContarBovinos(caminho_video=video, modo=modo, modelo=modelo,
                                                  fps_amostragem=fps,
                                                  dir_evidencias=str(DIR_EV / f"{rotulo}_{modo}_{modelo}")))
    if not e.ok:
        return {"ok": False, "erro": e.error.msg}
    d = e.data
    return {"ok": True, "contagem": d["contagem"], "intervalo": d["intervalo"], "status": d["status"],
            "abstencao": d["abstencao"], "motivos": [m["codigo"] for m in d["motivos"]],
            "s_por_s_video": d["s_por_s_video"], "fps_processado": d["fps_processado"],
            "n_frames": d["n_frames"], "conf_media": d["conf_media"], "cobertura": d["cobertura"],
            "quadros_chave": [q["caminho"] for q in d["quadros_chave"]], "latency_ms": e.latency_ms}


def avaliar_quadros(ref: dict, modelo: str, limiar: float = 0.5) -> list[dict]:
    det = DetectorYOLOX(MODELOS[modelo].caminho)
    out = []
    por_video: dict[str, list[dict]] = {}
    for q in ref["quadros"]:
        por_video.setdefault(q["video"], []).append(q)
    for vid, alvos in por_video.items():
        caminho = RAIZ / "dados_locais" / "videos" / f"{vid}.webm"
        if not caminho.is_file():
            continue
        alvos = sorted(alvos, key=lambda a: a["t_s"])
        k = 0
        for fr in iterar_quadros(str(caminho), fps_amostragem=30, lado_max=1280):
            while k < len(alvos) and fr.t_s >= alvos[k]["t_s"] - 0.02:
                d = det.detectar(fr.img, 0.25)
                n = int((d[:, 4] >= limiar).sum()) if len(d) else 0
                out.append({**alvos[k], "detectados": n, "modelo": modelo})
                k += 1
            if k >= len(alvos):
                break
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modelos", nargs="+", default=["yolox_s", "yolox_m"])
    ap.add_argument("--fps", type=float, default=8.0)
    a = ap.parse_args(argv)
    ref = yaml.safe_load((AQUI / "contagens_referencia.yaml").read_text(encoding="utf-8"))
    manif_p = RAIZ / "dados_locais" / "videos" / "sinteticos" / "manifesto.json"
    manif = json.loads(manif_p.read_text(encoding="utf-8")) if manif_p.is_file() else []

    res: dict = {"data": time.strftime("%Y-%m-%d %H:%M"), "fps_amostragem": a.fps, "reais": [], "semi": [],
                 "quadros": []}
    for modelo in a.modelos:
        for v in ref["videos"]:
            p = RAIZ / v["arquivo"]
            if not p.is_file():
                print("ausente:", p)
                continue
            for modo in ("ids_unicos", "linha"):
                r = rodar(str(p), modo, modelo, a.fps, v["id"])
                ref_modo = v.get("referencia_linha") if modo == "linha" else v["referencia"]
                res["reais"].append({"id": v["id"], "modelo": modelo, "modo": modo, "recomendado":
                                     modo == v["modo_recomendado"], "referencia": ref_modo,
                                     "faixa": v["faixa_referencia"], "esperado": v["esperado"], **r})
                print(v["id"], modelo, modo, r.get("contagem"), r.get("intervalo"), r.get("status"),
                      r.get("motivos"), r.get("s_por_s_video"))
        for m in manif:
            p = RAIZ / m["arquivo"]
            for modo in ("linha", "ids_unicos"):
                r = rodar(str(p), modo, modelo, a.fps, m["id"])
                ref_modo = m["referencia_linha"] if modo == "linha" else m["referencia_ids"]
                res["semi"].append({"id": m["id"], "modelo": modelo, "modo": modo, "referencia": ref_modo, **r})
                print(m["id"], modelo, modo, ref_modo, r.get("contagem"), r.get("intervalo"), r.get("status"),
                      r.get("motivos"), r.get("s_por_s_video"))
        res["quadros"] += avaliar_quadros(ref, modelo)

    # tempo do yolox_tiny (só velocidade, num vídeo)
    v3 = RAIZ / "dados_locais/videos/v03_zebuinos_estabulo.webm"
    if v3.is_file() and MODELOS["yolox_tiny"].caminho.is_file():
        r = rodar(str(v3), "ids_unicos", "yolox_tiny", a.fps, "tempo")
        res["tempo_tiny"] = {"s_por_s_video": r.get("s_por_s_video"), "contagem": r.get("contagem")}

    res["resumo"] = resumir(res, a.modelos)
    (AQUI / "resultados_contagem.json").write_text(json.dumps(res, ensure_ascii=False, indent=1),
                                                     encoding="utf-8")
    imprimir(res, a.modelos)
    return 0


def _mae(xs: list[dict]) -> dict:
    ok = [x for x in xs if x.get("ok") and x["referencia"] is not None]
    if not ok:
        return {"n": 0}
    erros = [abs(x["contagem"] - x["referencia"]) for x in ok]
    rel = [abs(x["contagem"] - x["referencia"]) / max(x["referencia"], 1) for x in ok]
    cobre = [x["intervalo"][0] <= x["referencia"] <= x["intervalo"][1] for x in ok]
    sel = [x for x in ok if not x["abstencao"]]
    return {"n": len(ok), "mae": round(statistics.mean(erros), 2), "erro_rel_medio": round(statistics.mean(rel), 3),
            "acertos_exatos": sum(e == 0 for e in erros), "cobertura_intervalo": f"{sum(cobre)}/{len(ok)}",
            "abstencoes": sum(x["abstencao"] for x in ok),
            "mae_sem_abstencao": round(statistics.mean([abs(x["contagem"] - x["referencia"]) for x in sel]), 2)
            if sel else None, "n_sem_abstencao": len(sel)}


def resumir(res: dict, modelos: list[str]) -> dict:
    out = {}
    for m in modelos:
        reais_rec = [x for x in res["reais"] if x["modelo"] == m and x["recomendado"]]
        cont = [x for x in reais_rec if x["esperado"] == "contagem"]
        abst = [x for x in reais_rec if x["esperado"] == "abstencao"]
        semi_l = [x for x in res["semi"] if x["modelo"] == m and x["modo"] == "linha"]
        semi_i = [x for x in res["semi"] if x["modelo"] == m and x["modo"] == "ids_unicos"]
        qs = [q for q in res["quadros"] if q["modelo"] == m]
        tempos = [x["s_por_s_video"] for x in res["reais"] + res["semi"] if x["modelo"] == m and x.get("ok")]
        out[m] = {
            "reais_contaveis_modo_recomendado": _mae(cont),
            "reais_ambiguos_abstencao_correta": f"{sum(x.get('abstencao', False) for x in abst)}/{len(abst)}",
            "semissinteticos_linha": _mae(semi_l),
            "semissinteticos_ids_unicos": _mae(semi_i),
            "quadros_mae_vs_total": round(statistics.mean([abs(q["detectados"] - q["total"]) for q in qs]), 2)
            if qs else None,
            "quadros_mae_vs_nitidos": round(statistics.mean([abs(q["detectados"] - q["nitidos"]) for q in qs]), 2)
            if qs else None,
            "quadros_n": len(qs),
            "s_por_s_video_mediana": round(float(np.median(tempos)), 3) if tempos else None,
            "s_por_s_video_max": round(max(tempos), 3) if tempos else None,
        }
    return out


def imprimir(res: dict, modelos: list[str]) -> None:
    print("\n| id | modelo | modo | ref | contagem | intervalo | status | motivos | s/s |")
    print("|---|---|---|---|---|---|---|---|---|")
    for x in res["reais"] + res["semi"]:
        if not x.get("ok"):
            print(f"| {x['id']} | {x['modelo']} | {x['modo']} | {x['referencia']} | erro | | | {x.get('erro')} | |")
            continue
        print(f"| {x['id']} | {x['modelo']} | {x['modo']} | {x['referencia']} | {x['contagem']} | "
              f"{x['intervalo']} | {x['status']} | {', '.join(x['motivos'])} | {x['s_por_s_video']} |")
    print("\n| vídeo | t (s) | total | nítidos | " + " | ".join(modelos) + " |")
    print("|---|---|---|---|" + "---|" * len(modelos))
    chaves = sorted({(q["video"], q["t_s"]) for q in res["quadros"]})
    for vid, t in chaves:
        linha = [q for q in res["quadros"] if q["video"] == vid and q["t_s"] == t]
        det = {q["modelo"]: q["detectados"] for q in linha}
        print(f"| {vid} | {t} | {linha[0]['total']} | {linha[0]['nitidos']} | "
              + " | ".join(str(det.get(m, "")) for m in modelos) + " |")
    print("\n" + json.dumps(res["resumo"], ensure_ascii=False, indent=1))
    if "tempo_tiny" in res:
        print("tiny:", res["tempo_tiny"])


if __name__ == "__main__":
    raise SystemExit(main())
