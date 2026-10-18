"""Tarefa da rodada r4 congelada (L05/L06/L07/L43/L60): sequência, a seco, estado e retomada.

Nada aqui roda a avaliação de verdade nem toca o Ollama: a sequência é conferida como dado, o `--a-seco` roda num
subprocesso e a execução usa etapas falsas (um `python -c` que grava um arquivo) num diretório temporário.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "eval"))

import gerar_slide as GS
import harness as H
import rodada_r4 as R4

DATA = "2026-10-20"


def _etapas() -> dict[str, R4.Etapa]:
    return {e.id: e for e in R4.etapas(DATA)}


def test_sequencia_tem_tudo_o_que_a_r4_pede_na_ordem():
    ids = [e.id for e in R4.etapas(DATA)]
    assert ids == ["deterministico", "deterministico_ideal", "redteam_deterministico", "casos_publicos",
                   "casos_publicos_custeio", "indice_zf", "agente", "agente_rep", "redteam_agente",
                   "redteam_v3cego_agente", "redteam_v3cego_deterministico", "ab1", "narracoes_dev", "ab2_dev",
                   "leitura_teste", "narracoes_teste", "ab2_teste", "custo", "slide", "numeros_aplicar",
                   "numeros_verificar", "desclassificacao_verificar"]
    fases = [e.fase for e in R4.etapas(DATA)]
    assert fases == sorted(fases)  # sem LLM, depois LLM, depois números
    # o cego no agente e logo em seguida sem LLM, no mesmo src/ (ninguém olha o primeiro antes do segundo)
    assert ids.index("redteam_v3cego_deterministico") == ids.index("redteam_v3cego_agente") + 1


def test_todo_uso_do_teste_tem_final_e_motivo_e_todo_relatorio_tem_o_sufixo_r4():
    for e in R4.etapas(DATA):
        cmd = e.cmds[0]
        if e.toca_teste:
            assert "--final" in cmd and cmd[cmd.index("--motivo") + 1].strip(), e.id
        if cmd[0].startswith("eval/run_") or "run_ab" in cmd[0]:
            assert cmd[cmd.index("--sufixo") + 1].startswith("_r4"), e.id
        for s in e.saidas:
            if s.startswith("eval/reports/") and s.endswith(".json") and "palco" not in s:
                assert s.startswith(f"eval/reports/{DATA}_"), (e.id, s)
    e = _etapas()
    assert "--split" in e["agente_rep"].cmds[0] and e["agente_rep"].cmds[0][-2] == "_r4_rep"
    for k in ("redteam_v3cego_agente", "redteam_v3cego_deterministico"):
        c = e[k].cmds[0]
        assert c[c.index("--conjunto") + 1] == "v3_cego" and "_r4_v3cego" in c and "--motivo" in c
    assert "--manter-modelo" not in e["redteam_v3cego_deterministico"].cmds[0]


def test_saidas_sao_os_nomes_que_o_slide_e_os_numeros_leem():
    """O que a r4 grava é o que `gerar_slide`/`gerar_numeros` procuram com `--data DATA --sufixo _r4`."""
    saidas = {s for e in R4.etapas(DATA) for s in e.saidas}
    for nome in ("agente", "deterministico", "redteam_agente", "redteam_deterministico", "ab_centralidade",
                 "ab_centralidade_v2"):
        assert f"eval/reports/{DATA}_{nome}_r4.json" in saidas
    for nome, extras in GS.OPCIONAIS.values():
        assert any(f"eval/reports/{DATA}_{nome}_r4{x}.json" in saidas for x in extras), nome
    assert f"eval/reports/{DATA}_custo_demo.json" in saidas  # gerar_numeros lê <data>_custo_demo.json
    aplicar = _etapas()["numeros_aplicar"].cmds[0]
    assert {"--aplicar", "--fixar-palco"} <= set(aplicar) and aplicar[aplicar.index("--data") + 1] == DATA


def test_um_modelo_so_e_nenhuma_gravacao_dos_testes_e_tocada():
    for e in R4.etapas(DATA):
        for c in e.cmds:
            if "--modelo" in c:
                assert c[c.index("--modelo") + 1] == R4.MODELO
            assert not any("tests/unit/dados_agente" in x for x in c), (e.id, c)  # replays e cache do VLM
    custo = _etapas()["custo"].cmds[0]
    assert custo[custo.index("--vlm-cache") + 1].startswith("dados_locais/")  # o cache dos testes fica intacto


def test_a_seco_so_imprime_e_nao_grava_nada(tmp_path):
    dir_estado = tmp_path / "r4"
    r = subprocess.run([sys.executable, str(REPO / "eval" / "rodada_r4.py"), "--a-seco", "--dir-estado",
                        str(dir_estado)], cwd=REPO, capture_output=True, text=True, encoding="utf-8",
                       env={**os.environ, "PYTHONPATH": str(REPO / "src"), "PYTHONUTF8": "1",
                            H.VAR_DATA_RODADA: DATA}, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "a seco: nada foi executado" in r.stdout and f"data dos relatórios {DATA}" in r.stdout
    assert "--final --motivo 'rodada r4 congelada' --sufixo _r4" in r.stdout
    assert "Pré-condições:" in r.stdout
    assert not dir_estado.exists()


# --- execução com etapas falsas -----------------------------------------------------------------------------------


def _falsa(tmp: Path, nome: str, codigo: int = 0, llm: bool = False) -> R4.Etapa:
    alvo = tmp / f"{nome}.txt"
    prog = f"import pathlib,sys; pathlib.Path(r'{alvo}').write_text('ok'); print('feito {nome}'); sys.exit({codigo})"
    return R4.Etapa(nome, f"etapa {nome}", [["-c", prog]], 1, saidas=[str(alvo)], llm=llm)


@pytest.fixture()
def falsas(tmp_path, monkeypatch):
    lista = [_falsa(tmp_path, "a"), _falsa(tmp_path, "b"), _falsa(tmp_path, "c")]
    monkeypatch.setattr(R4, "etapas", lambda data, dir_estado=None: lista)
    monkeypatch.setattr(R4, "precondicoes", lambda lista, verificar_ollama=True: [])
    monkeypatch.setattr(R4, "descarregar_todos", list)  # nunca fala com o Ollama de verdade
    monkeypatch.setenv(H.VAR_DATA_RODADA, DATA)
    return lista


def test_roda_em_ordem_grava_estado_e_logs(tmp_path, falsas):
    dir_estado = tmp_path / "estado"
    assert R4.main(["--dir-estado", str(dir_estado)]) == 0
    est = R4.ler_estado(dir_estado)
    assert est["data"] == DATA and est["sha256_src"] == H.hash_src() and est.get("concluido_em")
    assert [est["etapas"][k]["status"] for k in "abc"] == ["ok", "ok", "ok"]
    assert "feito b" in (dir_estado / "logs" / "b.log").read_text(encoding="utf-8")


def test_sem_retomar_nao_recomeca_por_cima(tmp_path, falsas):
    dir_estado = tmp_path / "estado"
    assert R4.main(["--dir-estado", str(dir_estado)]) == 0
    assert R4.main(["--dir-estado", str(dir_estado)]) == 2  # já iniciada: só com --retomar
    assert R4.main(["--retomar", "--dir-estado", str(tmp_path / "vazio")]) == 2  # nada a retomar


def test_falha_para_a_rodada_e_retomar_continua_dali(tmp_path, falsas, monkeypatch):
    dir_estado = tmp_path / "estado"
    falsas[1] = _falsa(tmp_path, "b", codigo=1)
    assert R4.main(["--dir-estado", str(dir_estado)]) == 1
    est = R4.ler_estado(dir_estado)
    assert est["etapas"]["a"]["status"] == "ok" and est["etapas"]["b"]["status"] == "erro"
    assert "c" not in est["etapas"]  # parou na falha
    (tmp_path / "a.txt").write_text("marca", encoding="utf-8")
    falsas[1] = _falsa(tmp_path, "b")
    assert R4.main(["--retomar", "--dir-estado", str(dir_estado)]) == 0
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "marca"  # a etapa feita não rodou de novo
    assert R4.ler_estado(dir_estado)["etapas"]["c"]["status"] == "ok"


def test_retomar_recusa_se_src_mudou(tmp_path, falsas, monkeypatch):
    dir_estado = tmp_path / "estado"
    falsas[2] = _falsa(tmp_path, "c", codigo=1)
    assert R4.main(["--dir-estado", str(dir_estado)]) == 1
    monkeypatch.setattr(H, "hash_src", lambda: "f" * 64)
    assert R4.main(["--retomar", "--dir-estado", str(dir_estado)]) == 2


def test_etapa_que_nao_grava_a_saida_esperada_falha(tmp_path, falsas):
    """Ex.: relatório saiu com outra data: a rodada para em vez de seguir com um buraco."""
    falsas[0] = R4.Etapa("a", "sem saída", [["-c", "print(1)"]], 1, saidas=[str(tmp_path / "nunca.json")])
    dir_estado = tmp_path / "estado"
    assert R4.main(["--dir-estado", str(dir_estado)]) == 1
    assert "saídas esperadas ausentes" in R4.ler_estado(dir_estado)["etapas"]["a"]["erro"]


def test_etapa_do_llm_recusa_outro_modelo_carregado(tmp_path, falsas, monkeypatch):
    falsas[0] = _falsa(tmp_path, "a", llm=True)
    monkeypatch.setattr(R4, "modelos_carregados", lambda: ["qwen3:14b"])
    dir_estado = tmp_path / "estado"
    assert R4.main(["--dir-estado", str(dir_estado)]) == 1
    reg = R4.ler_estado(dir_estado)["etapas"]["a"]
    assert reg["status"] == "erro" and "outro modelo carregado" in reg["erro"]
    assert not (tmp_path / "a.txt").exists()


def test_relatorio_das_etapas_sem_relatorio_proprio(tmp_path, falsas):
    """Casos públicos e índice ZF só imprimem: a r4 grava a saída num .md com comando, src/ e código."""
    md = tmp_path / "saida.md"
    falsas[0] = R4.Etapa("a", "Casos públicos", [["-c", "print('PUB-0001: confere'); raise SystemExit(1)"]], 1,
                         saidas=[str(md)], codigos_ok=(0, 1), relatorio=str(md))
    assert R4.main(["--dir-estado", str(tmp_path / "estado")]) == 0
    texto = md.read_text(encoding="utf-8")
    assert "PUB-0001: confere" in texto and "código de saída 1" in texto and "sha256(src/)" in texto


def test_data_da_rodada_vem_da_variavel(monkeypatch):
    monkeypatch.setenv(H.VAR_DATA_RODADA, "2026-10-21")
    assert H.data_rodada() == "2026-10-21"
    monkeypatch.setenv(H.VAR_DATA_RODADA, "21/10/2026")
    with pytest.raises(ValueError):
        H.data_rodada()
    monkeypatch.delenv(H.VAR_DATA_RODADA)
    assert len(H.data_rodada()) == 10


def test_tarefas_sh_e_makefile_tem_a_tarefa_r4():
    tarefas = (REPO / "scripts" / "tarefas.sh").read_text(encoding="utf-8")
    assert "r4() { py eval/rodada_r4.py" in tarefas and "|r4|" in tarefas
    assert "\r\n" not in (REPO / "scripts" / "tarefas.sh").read_bytes().decode("utf-8")  # bash quebra com CRLF
    make = (REPO / "Makefile").read_bytes().decode("utf-8")
    assert " r4 " in make.split("ALVOS :=")[1].splitlines()[0] and "\r\n" not in make


def test_ci_tem_frases_e_numeros():
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "bash scripts/tarefas.sh frases" in ci and "bash scripts/tarefas.sh numeros --verificar" in ci
    assert "só do dev" in ci  # a avaliação do CI é só dev; o número de palco é o da r4


def test_eval_readme_lista_os_mesmos_comandos_da_tarefa():
    """Os comandos da r4 no eval/README.md (regra 4 do congelamento) são os que a tarefa roda (sem deriva)."""
    readme = (REPO / "eval" / "README.md").read_text(encoding="utf-8")
    for e in R4.etapas(DATA):
        if e.id in ("custo", "casos_publicos_custeio"):
            continue  # o README resume estes dois numa linha de comentário
        c = e.cmds[0]
        linha = "scripts/py.sh " + " ".join(f'"{x}"' if " " in x else x for x in c).replace(DATA, "<data>")
        assert linha in readme, linha


def test_etapa_com_saida_json_ignora_o_stderr(tmp_path, falsas):
    """O custo sai como JSON no stdout: um aviso no stderr não pode estragar o arquivo."""
    alvo = tmp_path / "custo.json"
    prog = "import sys, json; print('aviso qualquer', file=sys.stderr); print(json.dumps([{'uso': 1}]))"
    falsas[0] = R4.Etapa("a", "custo", [["-c", prog]], 2, saidas=[str(alvo)], json_stdout=str(alvo))
    assert R4.main(["--dir-estado", str(tmp_path / "estado")]) == 0
    assert json.loads(alvo.read_text(encoding="utf-8")) == [{"uso": 1}]
