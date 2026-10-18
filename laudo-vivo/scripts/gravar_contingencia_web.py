"""Grava a contingência da interface web (replay do LLM) sem clicar: roda o roteiro inteiro do caso pela API.

Faz o que o operador faria com `scripts/rodar_demo.sh --gravar` e a tecla →, do primeiro passo até o selo:
abre o caso, executa cada passo do roteiro (inclusive a foto do DANFE e o residual lido do papel), assina com
o PIN de demonstração e, no fim, escreve a fixture de replay (só chave → resposta, sem os prompts).

Uso (na raiz; precisa do Ollama com o qwen3.5:4b, do yolox_m e do vídeo semissintético):
  scripts/py.sh scripts/gravar_contingencia_web.py                       # grava eval/golden/demo/DEMO-0001/
  scripts/py.sh scripts/gravar_contingencia_web.py --saida dados_locais/api/gravacoes/DEMO-0001.jsonl
  scripts/py.sh scripts/gravar_contingencia_web.py --conferir             # só confere a gravação (replay)
  scripts/py.sh scripts/gravar_contingencia_web.py --conferir --tempos    # e mede cada passo

Com `--tempos`, cada passo mostra o tempo das ferramentas reais na CPU e a latência do LLM registrada na
gravação (feita ao vivo com o qwen3.5:4b): a soma estima o tempo do passo na demo ao vivo com
`rodar_demo.sh --vlm-gravado` (os tempos do `ROTEIRO_DEMO.md` vêm daqui).

A leitura do DANFE usa o cache do VLM da demo (`tests/unit/dados_agente/vlm_cache_demo`): a mesma foto, o
mesmo pedido; a contingência roda sem GPU. Com `--conferir`, sai com erro se alguma requisição ao LLM não
estiver na gravação ou se a fiscalização não terminar SELADA.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
CACHE_VLM = REPO / "tests" / "unit" / "dados_agente" / "vlm_cache_demo"


def _llm_s(out: dict) -> float:
    """Latência do LLM no passo (registrada na gravação, no replay), em segundos."""
    llm = ((out.get("resposta") or {}).get("llm") or {}).values()
    return sum(float((v or {}).get("latencia_ms") or 0) for v in llm if isinstance(v, dict)) / 1000


def rodar(
    llm: str,
    caso: str,
    gravar: Path | None,
    replay: Path | None,
    dados: Path,
    tempos: list[tuple[int, str, float, float]] | None = None,
) -> tuple[str, int, int]:
    """Roda o roteiro pela API (Servico, sem HTTP). Devolve (etapa final, nº de passos, substituições). Com
    `tempos`, acrescenta (passo, título, tempo das ferramentas em s, latência do LLM gravada em s)."""
    from laudo.agent import estado as est
    from laudo.api.servico import PIN_DEMO, Config, Servico
    from laudo.tools import laudo as ferr_laudo

    cfg = Config(
        llm=llm,
        ferramentas="reais",
        caso=caso,
        asr="desligado",
        dados=dados,
        gravar=str(gravar) if gravar else None,
        replay=str(replay) if replay else None,
    )
    srv = Servico(cfg)
    try:
        e = srv.abrir_caso(caso)
        fis, n = e["id"], 0
        while True:
            t0 = time.perf_counter()
            try:
                out = srv.passo_roteiro(fis)
            except Exception as erro:  # fim do roteiro (409) ou falha: para e relata
                if getattr(erro, "status", None) == 409:
                    break
                raise
            n += 1
            titulo = out["passo"]["titulo"]
            fala = ((out.get("resposta") or {}).get("fala") or out.get("aviso") or "")[:110]
            parede = time.perf_counter() - t0
            if tempos is not None:
                tempos.append((n, titulo, parede, _llm_s(out)))
                fala = f"(ferramentas {parede:.1f} s + LLM {_llm_s(out):.1f} s) {fala}"
            print(f"[{n:02d}] {titulo}: {fala}", flush=True)
            if out.get("acao_humana") == "assinar":
                e = srv.estado(fis)
                if not e.get("laudo"):  # mensagem clara em vez de TypeError
                    pend = (
                        "; ".join(str(p.get("falta")) for p in (e.get("pendencias") or [])[:4]) or "nenhuma"
                    )
                    print(
                        f"     ERRO: passo de assinatura sem rascunho emitido (etapa {e['etapa']}; "
                        f"pendências: {pend}). Confira a data das evidências (recebida_em) e o roteiro "
                        "do caso.",
                        flush=True,
                    )
                    break
                h = e["laudo"]["hash_raiz"]
                srv.assinar(fis, PIN_DEMO, h)
                print(f"     assinatura humana (PIN de demonstração) sobre o hash {h[:12]}…", flush=True)
        etapa = srv.carregar(fis).estado_fsm
        subs = int(getattr(srv.provedor, "substituicoes", 0) or 0)
        return etapa, n, subs
    finally:
        est.ids_deterministicos(None)
        ferr_laudo.configurar(None, None)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--caso", default="DEMO-0001")
    ap.add_argument(
        "--saida", default=None, help="fixture de replay (padrão: <pasta do caso>/replay_qwen35_4b.jsonl)"
    )
    ap.add_argument("--conferir", action="store_true", help="só reproduz a gravação e confere")
    ap.add_argument("--descarregar", action="store_true", help="descarrega o modelo do Ollama ao final")
    ap.add_argument(
        "--tempos", action="store_true", help="com --conferir: tempo de cada passo (ferramentas + LLM)"
    )
    a = ap.parse_args()
    from laudo.api import casos as casos_mod

    pasta = casos_mod.localizar_caso(a.caso)
    if pasta is None:
        print(f"caso {a.caso} não encontrado", file=sys.stderr)
        return 2
    saida = Path(a.saida) if a.saida else pasta / "replay_qwen35_4b.jsonl"
    os.environ.setdefault("LAUDO_VLM_CACHE", str(CACHE_VLM))
    tmp = Path(tempfile.mkdtemp(prefix="laudo-contingencia-"))
    try:
        if a.conferir:
            os.environ["LAUDO_VLM_SO_CACHE"] = "1"
            tempos: list[tuple[int, str, float, float]] | None = [] if a.tempos else None
            etapa, n, subs = rodar("replay", a.caso, None, saida, tmp / "dados", tempos)
            print(f"replay: {n} passos, etapa final {etapa}, {subs} requisição(ões) fora da gravação")
            if tempos:
                total = sum(p + q for _, _, p, q in tempos)
                lento = max(tempos, key=lambda x: x[2] + x[3])
                print(
                    f"tempo do sistema nos {len(tempos)} passos: {total:.1f} s (sem a reação do operador); "
                    f"passo mais lento: {lento[0]} {lento[1]} ({lento[2] + lento[3]:.1f} s)"
                )
            return 0 if etapa == "SELADO" and subs == 0 else 1
        bruto = tmp / "gravacao.jsonl"
        etapa, n, _ = rodar("ollama", a.caso, bruto, None, tmp / "dados")
        if etapa != "SELADO":
            print(f"o roteiro terminou em {etapa}, não em SELADO: gravação descartada", file=sys.stderr)
            return 1
        saida.parent.mkdir(parents=True, exist_ok=True)
        with open(bruto, encoding="utf-8") as f, open(saida, "w", encoding="utf-8") as out:
            k = 0
            for linha in f:
                if linha.strip():
                    d = json.loads(linha)
                    out.write(
                        json.dumps(
                            {"chave": d["chave"], "resposta": d["resposta"], "tipo": d["tipo"]},
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                        + "\n"
                    )
                    k += 1
        print(f"gravado: {saida} ({k} respostas, {n} passos, etapa final {etapa})")
        if a.descarregar:
            from laudo.llm.provider import OllamaProvider

            OllamaProvider(perfil="campo").descarregar()
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
