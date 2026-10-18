"""Roda `ler_documento_foto` (VLM local + validação) em todas as fotos/PDFs do conjunto bagunçado e grava, por
arquivo, o resultado e as leituras brutas (para medir quanto a validação barrou). Retomável.

Uso (na raiz do repositório; precisa do Ollama com qwen3.5:4b):
  scripts/py.sh eval/ab_centralidade_v2/avaliar_leitura.py --split dev
  # L07, split de teste congelado (~55 min de GPU; uma vez, no sha256(src/) final):
  scripts/py.sh eval/ab_centralidade_v2/avaliar_leitura.py --split test --final --motivo "L07 AB v2 no teste r4"

O split de teste está congelado: `--split test|todos` (ou `--casos` com um caso do teste) exige `--final` e
`--motivo`, confere o `golden/casos/MANIFESTO.yaml` e fica no `golden/casos/registro_teste.jsonl` (L41).

Saída: `dados_locais/eval/leitura_v2_<split>.jsonl` (fora do git: as leituras brutas trazem os CPF/CNPJ
sintéticos dos documentos) e, ao lado, `leitura_v2_<split>.meta.json` com cada sessão de gravação (modelo, digest,
versão do Ollama, pares temperatura/semente usados, sha256(src/) e sha256(eval/); L59), que `run_ab_v2.py` copia
para o `config` do relatório. As métricas saem de `run_ab_v2.py`.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

import yaml

AQUI = Path(__file__).resolve().parent
REPO = AQUI.parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "eval"))

import harness as H

from laudo.tools import leitura_documentos as LD

MANIFESTO = REPO / "eval" / "golden" / "baguncados" / "MANIFESTO.yaml"
DIR_ARQ = REPO / "dados_locais" / "golden_baguncado"
HOJE = date(2026, 10, 8)


def caminho_meta(saida: Path) -> Path:
    """`leitura_v2_<split>.jsonl` → `leitura_v2_<split>.meta.json` (sessões de gravação, L59)."""
    return saida.with_name(saida.stem + ".meta.json")


def gravar_sessao(saida: Path, sessao: dict) -> None:
    """Acrescenta a sessão ao `.meta.json` (a gravação é retomável: cada retomada é uma sessão)."""
    meta = caminho_meta(saida)
    dados = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {"sessoes": []}
    dados["sessoes"].append(sessao)
    meta.write_text(json.dumps(dados, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", default="dev", choices=["dev", "test", "todos"])
    ap.add_argument("--casos", nargs="*")
    ap.add_argument("--niveis", nargs="*")
    ap.add_argument("--saida", default=None)
    ap.add_argument("--modelo", default="qwen3.5:4b")
    ap.add_argument("--sem-classificar", action="store_true", help="não mede a classificação automática do tipo")
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
        print("execução recusada:", *erros, sep="\n  ")
        return 2
    saida = Path(a.saida or REPO / "dados_locais" / "eval" / f"leitura_v2_{a.split}.jsonl")
    saida.parent.mkdir(parents=True, exist_ok=True)
    feitos = set()
    if saida.exists():
        for ln in saida.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                d = json.loads(ln)
                feitos.add((d["id"], d["arquivo"]))
    base = LD._ollama(a.modelo, 180.0)
    chamadas: list[dict] = []
    pares: set[tuple[float, int]] = set()

    def leitor(img_b64, prompt, esquema, temp, semente):
        t0 = time.perf_counter()
        r = base(img_b64, prompt, esquema, temp, semente)
        chamadas.append({"ms": int((time.perf_counter() - t0) * 1000), "resposta": r})
        pares.add((temp, semente))
        return r

    opcoes = {"leitor": "laudo.tools.leitura_documentos._ollama", "timeout_s": 180.0, "k_min": 2, "k_max": 3,
              "nota": "num_ctx, num_predict e think fixos no leitor (versão em sha256_src)"}
    llm = H.info_llm(modelo=a.modelo, base_url=LD.OLLAMA, opcoes=opcoes)
    sessao = {"inicio": H.agora_iso(), "split": a.split, "casos": a.casos, "niveis": a.niveis, "llm": llm,
              "sha256_src": H.hash_src(), "sha256_src_lf": H.hash_src_lf(), "sha256_eval": H.hash_eval()["sha256"],
              "manifesto_baguncados_sha256_conteudo": man.get("sha256_conteudo"), "final": bool(toca and a.final)}
    t_ini = time.perf_counter()
    n = 0
    extra = {"split": a.split, "casos_teste": sorted({c["id"] for c in alvo if c["split"] == "test"}),
             "sha256_src": sessao["sha256_src"], "llm": {k: llm.get(k) for k in ("modelo", "digest", "ollama_versao")},
             "saida": H.argv_seguro([str(saida)])[0]}
    try:
        with (H.uso_do_teste(toca and a.final, script="eval/ab_centralidade_v2/avaliar_leitura.py",
                             alvo="ab_v2_test", motivo=a.motivo, argv=sys.argv[1:], extra=extra) as uso,
              saida.open("a", encoding="utf-8") as f):
            sessao["execucao_registro"] = (uso or {}).get("execucao")
            for c in alvo:
                for arq in c["arquivos"]:
                    if a.niveis and arq["nivel"] not in a.niveis:
                        continue
                    if (c["id"], arq["arquivo"]) in feitos:
                        continue
                    img = LD.carregar_imagem(str(DIR_ARQ / c["id"] / arq["arquivo"]))
                    reg = {"id": c["id"], "split": c["split"], "classe": c["classe"], "codigo": c["codigo"],
                           "arquivo": arq["arquivo"], "tipo": arq["tipo"], "doc": arq["doc"], "nivel": arq["nivel"]}
                    if not a.sem_classificar:
                        chamadas.clear()
                        t0 = time.perf_counter()
                        reg["tipo_auto"] = LD.classificar_tipo(img, HOJE, leitor)
                        reg["ms_classificar"] = int((time.perf_counter() - t0) * 1000)
                    chamadas.clear()
                    t0 = time.perf_counter()
                    try:
                        out = LD.ler(img, arq["tipo"], HOJE, 2, 3, leitor)
                        out.pop("leituras_brutas", None)
                        reg["resultado"] = out
                    except Exception as e:  # noqa: BLE001 - registra e segue
                        reg["erro"] = f"{type(e).__name__}: {e}"[:300]
                    reg["ms"] = int((time.perf_counter() - t0) * 1000)
                    reg["respostas_vlm"] = [x["resposta"] for x in chamadas]
                    reg["ms_chamadas"] = [x["ms"] for x in chamadas]
                    f.write(json.dumps(reg, ensure_ascii=False, default=str) + "\n")
                    f.flush()
                    n += 1
                    st = (reg.get("resultado") or {}).get("status", reg.get("erro"))
                    print(f"{c['id']} {arq['arquivo']:22s} {st:14s} k={(reg.get('resultado') or {}).get('k')} "
                          f"{reg['ms'] / 1000:.1f}s tipo_auto={reg.get('tipo_auto')}", flush=True)
            if uso is not None:
                uso["resultado"] = {"arquivos_lidos": n, "saida_sha256": H.sha256_arquivo(saida)}
    finally:
        sessao |= {"fim": H.agora_iso(), "n_novos": n, "pares_temperatura_semente": sorted(pares)}
        gravar_sessao(saida, sessao)
    print(f"{n} arquivos em {time.perf_counter() - t_ini:.0f} s -> {saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
