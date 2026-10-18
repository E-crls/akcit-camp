"""Demo de linha de comando: uma fiscalização de investimento pecuário ponta a ponta, por texto.

Mostra: plano de método, coleta (fala + NF-e + vídeo + foto), uma divergência na contagem, a recusa à pressão
"pode marcar 40", o bloqueio do rascunho (BLOQUEADO_POLITICA com pendências), a correção com nova evidência
(GTA e vídeo do lote que faltava, com tentativa de injeção no texto da GTA), a emissão do laudo, a recusa a
assinar pelo fiscal, a assinatura humana e o selo. Roteiro em `src/laudo/agent/roteiro_demo.py`.

Com `--ferramentas reais` roda o caso `eval/golden/demo/DEMO-0001`: operação FICTÍCIA (REF 000000001,
cooperativa fictícia; 29 vacas leiteiras + benfeitoria em Petrolina de Goiás) derivada de um registro público
do Sicor por `scripts/mascarar_demo.py`, com documentos, fotos e falas sintéticos, vídeo semissintético de
corredor e as ferramentas reais (contagem YOLOX em CPU, leitura do DANFE por VLM, NF-e/GTA, integridade,
geofence, NDVI, regras). O roteiro padrão (19 passos) inclui a FOTO DA NOTA IMPRESSA: o VLM lê o
DANFE, o código valida cada campo (DV da chave, CNPJ/CPF, somas), o agente pede só o que não validou, a fiscal
lê no papel e o código revalida; depois o XML chega e confere com o papel. `--sem-danfe` volta ao caminho de
17 passos (só o XML).

Uso (na raiz do repositório):
  scripts/py.sh scripts/demo_cli.py                       # sem GPU: LLM roteirizado, ferramentas falsas
  scripts/py.sh scripts/demo_cli.py --llm ollama --perfil campo --gravar dados_locais/demo/gravacao.jsonl
  scripts/py.sh scripts/demo_cli.py --llm replay --replay tests/unit/dados_agente/replay_demo_qwen35_4b.jsonl
  scripts/py.sh scripts/demo_cli.py --ferramentas reais --llm ollama --gravar dados_locais/demo/real.jsonl
      --fixture tests/unit/dados_agente/replay_demo_real_qwen35_4b.jsonl --descarregar
  scripts/py.sh scripts/demo_cli.py --ferramentas reais --llm replay
      --replay tests/unit/dados_agente/replay_demo_real_qwen35_4b.jsonl      # sem GPU, ferramentas reais
  scripts/py.sh scripts/demo_cli.py ... --pacote          # no fim, gera o pacote BCB/Justiça (ZIP)
  scripts/py.sh scripts/demo_cli.py --so-pacote fis_demo_0001 [--dados DIR]   # só o pacote de uma selada

Pacote de exibição (`laudo.tools.pacote`): ação humana, sem LLM, só depois de SELADO. ZIP com manifest sha256
de cada arquivo, laudo selado, GeoJSON da gleba e das fotos, cenas do satélite, fundamento literal por item,
memória de cálculo, ciência do mutuário com prazo de contestação, reversão (IN BCB 758) e checklist "Ordem JF
Rio Verde".

Com `--ferramentas reais`, as respostas do VLM (leitura da foto do DANFE e classificação da foto da cerca)
ficam em `--vlm-cache` (padrão `tests/unit/dados_agente/vlm_cache_demo/`): o Ollama grava; o replay e o
roteiro leem só do cache (`LAUDO_VLM_SO_CACHE=1`), sem GPU.

Nada aqui é dado pessoal nem aponta para operação real: a operação da demo é fictícia; tomador, vendedor,
documentos, fotos, falas e defeitos são sintéticos (marca d'água "DEMONSTRAÇÃO — dados sintéticos" no laudo).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import textwrap
import time
from datetime import datetime
from pathlib import Path

from laudo.agent import estado as est
from laudo.agent import roteiro_demo as demo
from laudo.agent.condutor import Condutor
from laudo.agent.ferramentas_falsas import registro_com_falsas
from laudo.audit import otel
from laudo.contracts import REGISTRO
from laudo.llm.provider import Gravador, OllamaProvider, ProvedorRoteirizado, ReplayProvider

REPO = Path(__file__).resolve().parents[1]
COR = {
    "fiscal": "\033[36m",
    "agente": "\033[32m",
    "aviso": "\033[33m",
    "bloq": "\033[31m",
    "fim": "\033[0m",
    "dim": "\033[2m",
}


def imprimir(p: demo.PassoDemo, cor: bool) -> None:
    def c(chave: str, texto: str) -> str:
        return f"{COR[chave]}{texto}{COR['fim']}" if cor else texto

    r = p.resposta
    trans = f"; {', '.join(r.transicoes)}" if r.transicoes else ""
    print(f"\n{'─' * 100}\n[{p.n:02d}] {p.titulo}   (etapa: {r.etapa}{trans})")
    if p.fala:
        print(c("fiscal", f"  FISCAL: {p.fala}"))
    for a in r.acoes:
        marca = "✔" if a.permitido and a.ok is not False else "✖"
        linha = f"  {marca} [{a.origem}] {a.acao}"
        if a.rule_id and (not a.permitido or a.origem in ("guarda", "humano")):
            linha += f" ({a.rule_id})"
        if a.acao == "emitir_rascunho" and a.ok and a.dados:
            linha += f": rascunho emitido, hash raiz {a.dados.get('hash_raiz')}"
        else:
            linha += f": {a.resultado[:150]}"
        print(c("bloq" if not a.permitido or a.ok is False else "dim", linha))
    for al in r.alegacoes:
        pt = al["ponteiro"]
        print(
            c(
                "dim",
                f"  • alegação {al['id']}: {al['grandeza']}={al['valor']} {al.get('unidade') or ''} "
                f"«{al['trecho']}» → {pt['evidencia_id']}[{pt['inicio']}:{pt['fim']}]",
            )
        )
    for o in r.ocorrencias:
        print(c("aviso", f"  ! ocorrência registrada: {o}"))
    for av in r.avisos:
        print(c("aviso", f"  ! {av[:160]}"))
    print(
        c("agente", f"  AGENTE ({r.fala_origem}): " + textwrap.fill(r.fala, 92, subsequent_indent=" " * 12))
    )


def gerar_fixture(gravacao: Path, destino: Path) -> int:
    """Fixture de replay a partir da gravação do Ollama: só chave → resposta (sem o prompt)."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(gravacao, encoding="utf-8") as f, open(destino, "w", encoding="utf-8") as out:
        for linha in f:
            if not linha.strip():
                continue
            d = json.loads(linha)
            out.write(
                json.dumps(
                    {"chave": d["chave"], "resposta": d["resposta"], "tipo": d["tipo"]},
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--llm", choices=["roteiro", "ollama", "replay"], default="roteiro")
    ap.add_argument("--perfil", default="escritorio", choices=["campo", "escritorio", "lote"])
    ap.add_argument("--modelo", default=None)
    ap.add_argument("--modo", default="tools", choices=["tools", "estruturado"])
    ap.add_argument("--gravar", default=None, help="JSONL para gravar requisição→resposta do Ollama")
    ap.add_argument("--replay", default=None, help="JSONL gravado (com --llm replay)")
    ap.add_argument("--ferramentas", choices=["falsas", "reais"], default="falsas")
    ap.add_argument("--dados", default=str(REPO / "dados_locais" / "demo"))
    ap.add_argument("--sem-cor", action="store_true")
    ap.add_argument("--descarregar", action="store_true", help="descarrega o modelo do Ollama ao final")
    ap.add_argument(
        "--caso", default=str(demo.CASO_REAL), help="pasta do caso real (com --ferramentas reais)"
    )
    ap.add_argument("--fixture", default=None, help="com --gravar: escreve a fixture de replay ao final")
    ap.add_argument(
        "--sem-danfe",
        action="store_true",
        help="(--ferramentas reais) pula a foto do DANFE e o residual (caminho só com o XML, 17 passos)",
    )
    ap.add_argument("--com-danfe", action="store_true", help=argparse.SUPPRESS)  # já é o padrão; aceito por compatibilidade
    ap.add_argument(
        "--pacote",
        action="store_true",
        help="no fim, se SELADO, gera o pacote de exibição BCB/Justiça (ação humana, sem LLM)",
    )
    ap.add_argument(
        "--so-pacote",
        default=None,
        metavar="FIS_ID",
        help="só gera o pacote de exibição de uma fiscalização já selada em --dados (não roda a demo)",
    )
    ap.add_argument(
        "--vlm-cache",
        default=str(REPO / "tests" / "unit" / "dados_agente" / "vlm_cache_demo"),
        help="pasta do cache das respostas do VLM (replay da leitura de foto sem GPU)",
    )
    a = ap.parse_args()
    cor = not a.sem_cor and sys.stdout.isatty()
    reais = a.ferramentas == "reais"

    dados = Path(a.dados)
    if a.so_pacote:  # antes da limpeza abaixo: usa a fiscalização que já está em --dados
        from laudo.tools import pacote

        return pacote.main(["--dados", str(dados), a.so_pacote])
    # caso do split de teste congelado não roda pela CLI (uso fora do registro; ver laudo.api.casos). A recusa
    # vem antes de qualquer limpeza: um caso recusado não apaga a pasta de dados nem a gravação
    if reais:
        from laudo.api import casos as casos_mod

        try:
            aviso = casos_mod.checar_uso_do_teste(Path(a.caso))
        except casos_mod.CasoDoTesteCongelado as e:
            print(f"Recusado: {e}")
            return 2
        if aviso:
            print(aviso)
    if a.gravar and Path(a.gravar).exists():
        Path(a.gravar).unlink()  # gravação nova a cada execução
    # a demo recomeça do zero na sua própria pasta (estado, laudos, traces, índice de fotos, quadros-chave)
    for sub in ("fiscalizacoes", "laudos", "traces", "indices", "evidencias"):
        shutil.rmtree(dados / sub, ignore_errors=True)
    otel.configurar(dados / "traces")
    caso = demo.carregar_caso_real(Path(a.caso)) if reais else None
    # ids reprodutíveis: o replay casa pela chave da requisição
    est.ids_deterministicos(demo.SEMENTE_IDS_REAL if reais else demo.SEMENTE_IDS)
    repo = est.RepositorioFiscalizacoes(dados)
    arquivos = None if caso else demo.preparar_arquivos(dados / "arquivos")

    if caso:
        from laudo.tools import carregar_todas

        # leitura do DANFE e classificação da foto: gravadas/relidas
        os.environ["LAUDO_VLM_CACHE"] = a.vlm_cache
        if a.llm != "ollama":
            os.environ["LAUDO_VLM_SO_CACHE"] = "1"

        registro, falsas = dict(carregar_todas()), []
        faltam = [n for n, ev in caso.evidencias.items() if ev.caminho and not Path(ev.caminho).is_file()]
        if faltam:
            print(
                "Arquivos do caso ausentes (gere com eval/golden/visao/gerar_semissintetico.py ou "
                "gerar_casos.py --so-demo):",
                ", ".join(faltam),
            )
            return 2
    else:
        from laudo.tools import laudo as _laudo  # noqa: F401  (registra emitir_rascunho)

        base = {k: v for k, v in REGISTRO.items() if k in ("emitir_rascunho", "registrar_ocorrencia")}
        registro, falsas = registro_com_falsas(demo.CENARIO, base=base)
    roteiro = None
    hoje = caso.data_referencia if caso else datetime.now().astimezone().date()
    if a.llm == "roteiro":
        roteiro = demo.RoteiroDemo()
        provedor = ProvedorRoteirizado(roteiro, modelo="roteiro-demo")
    elif a.llm == "ollama":
        provedor = OllamaProvider(
            modelo=a.modelo,
            perfil=a.perfil,
            hoje=hoje,
            gravador=Gravador(a.gravar) if a.gravar else None,
        )
        if not provedor.disponivel():
            print("Ollama indisponível em", provedor.base_url, "- use --llm roteiro ou --llm replay")
            return 2
    else:
        if not a.replay:
            ap.error("--llm replay exige --replay ARQUIVO")
        provedor = ReplayProvider(a.replay, sequencial_se_ausente=True)

    cond = Condutor(provedor, repo=repo, registro=registro, modo=a.modo, hoje=hoje if caso else None)
    fis_id = demo.FIS_ID_REAL if caso else demo.FIS_ID
    print(
        f"Laudo Vivo · demo · fiscalização {fis_id} · LLM: {a.llm} "
        f"({getattr(provedor, 'modelo', '')}) · "
        f"ferramentas falsas: {', '.join(falsas) or 'nenhuma'}"
    )
    if caso:
        from laudo.demonstracao import MARCA_DAGUA

        print(f"*** {MARCA_DAGUA} ***")
        print(textwrap.fill(f"Caso {caso.id}: {caso.aviso}", 100))
    tempos: list[tuple[int, str, float, int]] = []
    marca = [time.perf_counter()]

    def ao_passo(p: demo.PassoDemo) -> None:
        agora = time.perf_counter()
        llm_ms = sum(int(v.get("latencia_ms", 0)) for v in p.resposta.llm.values() if isinstance(v, dict))
        tempos.append((p.n, p.titulo, agora - marca[0], llm_ms))
        imprimir(p, cor)
        print(f"  ⏱ turno {agora - marca[0]:.1f} s (LLM {llm_ms / 1000:.1f} s)")
        marca[0] = time.perf_counter()

    t0 = time.perf_counter()
    if caso:
        demo.executar_real(cond, caso, roteiro=roteiro, ao_passo=ao_passo, com_danfe=not a.sem_danfe)
    else:
        demo.executar(cond, arquivos, roteiro=roteiro, ao_passo=ao_passo)
    total = time.perf_counter() - t0

    final = repo.carregar(fis_id)
    tipos = ", ".join(o.tipo for o in final.ocorrencias)
    print(
        f"\n{'═' * 100}\nEtapa final: {final.estado_fsm} · evidências: {len(final.evidencias)} · "
        f"checagens: {len(final.checagens)} · ocorrências: {len(final.ocorrencias)} ({tipos})"
    )
    for nome, campo in final.campos.items():
        print(f"  {nome:28s} {campo.status:11s} {campo.motivo[:90]}")
    for p in sorted((dados / "laudos" / fis_id).glob("*.html")):
        print(f"  laudo: {p}")
    print(f"  trace: {otel.arquivo_trace(fis_id)}")
    so_llm = sorted(t for _, _, t, ms in tempos if ms > 0)
    print(f"  tempo total: {total:.1f} s em {len(tempos)} turnos", end="")
    if so_llm:
        print(f"; turnos com LLM: p50 {so_llm[len(so_llm) // 2]:.1f} s, máx {so_llm[-1]:.1f} s")
    else:
        print()
    with open(dados / "tempos_turnos.json", "w", encoding="utf-8") as f:
        json.dump(
            [{"turno": n, "titulo": t, "s": round(s, 2), "llm_ms": ms} for n, t, s, ms in tempos],
            f,
            ensure_ascii=False,
            indent=1,
        )
    if isinstance(provedor, ReplayProvider):
        print(
            f"  replay: {provedor.substituicoes} requisição(ões) sem gravação exata (substituídas pela "
            "próxima do mesmo tipo)"
        )
    if a.pacote:
        from laudo.tools import pacote

        if final.estado_fsm == "SELADO":
            env = pacote.executar(final, dados / "laudos" / fis_id, otel.arquivo_trace(fis_id))
            print()
            print(pacote.formatar_resumo(env))
        else:
            print(f"Pacote de exibição não gerado: etapa {final.estado_fsm} (liberado só depois de SELADO)")
    if a.llm == "ollama" and a.gravar and a.fixture:
        n = gerar_fixture(Path(a.gravar), Path(a.fixture))
        print(f"  fixture de replay: {a.fixture} ({n} respostas)")
    if a.llm == "ollama" and a.descarregar:
        provedor.descarregar()
    return 0 if final.estado_fsm == "SELADO" else 1


if __name__ == "__main__":
    sys.exit(main())
