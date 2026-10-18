"""Sobe a API e a interface web: `scripts/py.sh -m laudo.api [opções]` (ou `scripts/rodar_demo.sh`).

Exemplos:
  scripts/py.sh -m laudo.api                                   # sem GPU: LLM roteirizado, ferramentas falsas
  scripts/py.sh -m laudo.api --llm ollama --ferramentas mistas --aquecer
  scripts/py.sh -m laudo.api --llm replay                      # contingência: demo gravada, sem GPU nem rede
  scripts/py.sh -m laudo.api --llm ollama --gravar dados_locais/api/gravacao.jsonl   # grava para replay
  scripts/py.sh -m laudo.api --caso DEMO-0001                  # caso do golden set no botão "demo"
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--llm", choices=["roteiro", "ollama", "replay"], default=os.environ.get("LAUDO_LLM", "roteiro")
    )
    ap.add_argument(
        "--ferramentas",
        choices=["falsas", "mistas", "reais"],
        default=os.environ.get("LAUDO_FERRAMENTAS", "falsas"),
    )
    ap.add_argument(
        "--caso",
        default=os.environ.get("LAUDO_CASO_DEMO", "roteiro"),
        help="caso do botão de demo: roteiro, DEMO-0001 ou pasta com caso.yaml",
    )
    ap.add_argument("--replay", default=None, help="JSONL gravado (padrão: o do caso)")
    ap.add_argument("--gravar", default=None, help="grava requisição→resposta do Ollama neste JSONL")
    ap.add_argument("--perfil", default="campo", choices=["campo", "escritorio", "lote"])
    ap.add_argument("--modelo", default=None)
    ap.add_argument("--modo", default="tools", choices=["tools", "estruturado"])
    ap.add_argument("--dados", default=None, help="pasta de estado (padrão dados_locais/api)")
    ap.add_argument(
        "--asr", default=os.environ.get("LAUDO_ASR", "auto"), choices=["auto", "cuda", "cpu", "desligado"]
    )
    ap.add_argument("--asr-beam", type=int, default=int(os.environ.get("LAUDO_ASR_BEAM", "1")))
    ap.add_argument(
        "--aquecer", action="store_true", help="carrega o Whisper (e o modelo do Ollama) na subida"
    )
    ap.add_argument("--hoje", default=None, help="data de referência AAAA-MM-DD (replay determinístico)")
    ap.add_argument("--host", default="127.0.0.1", help="0.0.0.0 para o celular na mesma rede")
    ap.add_argument("--porta", type=int, default=8000)
    ap.add_argument("--ssl-certfile", default=None, help="HTTPS (o celular só libera microfone/GPS em HTTPS)")
    ap.add_argument("--ssl-keyfile", default=None)
    ap.add_argument(
        "--vlm-cache",
        default=os.environ.get("LAUDO_VLM_CACHE"),
        help="respostas gravadas do VLM (leitura do DANFE). No --llm replay, padrão: o cache da demo "
        "(tests/unit/dados_agente/vlm_cache_demo), só leitura, sem GPU",
    )
    a = ap.parse_args()
    # contingência: a leitura da foto do DANFE vem do cache gravado (a mesma foto e o mesmo pedido), sem GPU
    repo = Path(__file__).resolve().parents[3]
    if a.llm == "replay":
        os.environ["LAUDO_VLM_CACHE"] = a.vlm_cache or str(
            repo / "tests" / "unit" / "dados_agente" / "vlm_cache_demo"
        )
        os.environ["LAUDO_VLM_SO_CACHE"] = "1"
    elif a.vlm_cache:
        os.environ["LAUDO_VLM_CACHE"] = a.vlm_cache

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")  # ver laudo.speech.asr
    import uvicorn

    from laudo.api.main import criar_app
    from laudo.api.servico import Config

    cfg = Config(
        llm=a.llm,
        ferramentas=a.ferramentas,
        caso=a.caso,
        replay=a.replay,
        gravar=a.gravar,
        perfil=a.perfil,
        modelo=a.modelo,
        modo=a.modo,
        asr=a.asr,
        asr_beam=a.asr_beam,
        hoje=date.fromisoformat(a.hoje) if a.hoje else None,
    )
    if a.dados:
        cfg.dados = Path(a.dados)
    app = criar_app(cfg)
    srv = app.state.servico
    if a.aquecer:
        if srv.transcritor is not None:
            try:
                print("ASR:", srv.aquecer_asr(), flush=True)
            except Exception as e:  # noqa: BLE001 - a demo segue por texto
                print("ASR indisponível:", e, flush=True)
        if a.llm == "ollama":
            try:
                print("LLM:", srv.aquecer_llm(), flush=True)
            except Exception as e:  # noqa: BLE001
                print("LLM indisponível:", e, flush=True)
    # PID para o rodar_demo.sh encerrar o processo certo
    # (o micromamba não repassa o sinal ao filho no Windows)
    try:
        (srv.dados / "api.pid").write_text(str(os.getpid()), encoding="ascii")
    except OSError:
        pass
    esquema = "https" if a.ssl_certfile else "http"
    print(
        f"Laudo Vivo em {esquema}://{a.host}:{a.porta}/  (LLM {a.llm}, ferramentas {a.ferramentas}, "
        f"caso {a.caso}, ASR {a.asr})",
        flush=True,
    )
    uvicorn.run(
        app,
        host=a.host,
        port=a.porta,
        log_level="warning",
        ssl_certfile=a.ssl_certfile,
        ssl_keyfile=a.ssl_keyfile,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
