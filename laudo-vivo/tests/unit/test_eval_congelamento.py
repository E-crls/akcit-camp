"""Congelamento verificável do golden set (L41): manifesto, `--final` e registro append-only do uso do teste.

Nenhum teste aqui roda um caso do split de teste real: o fluxo completo do `run_eval.py` usa um split falso, num
diretório temporário, montado com cópias de casos do **dev** (um deles fazendo o papel de "teste"), e o registro vai
para um arquivo temporário (`LAUDO_REGISTRO_TESTE`).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "eval"))

import harness as H

# --- o golden set versionado confere com o manifesto ---------------------------------------------------------


def test_manifesto_do_golden_versionado_confere():
    """Todo arquivo dos 60 casos (não só o caso.yaml) igual ao do congelamento; nenhum arquivo novo."""
    split = H.carregar_split()
    assert H.conferir_split(split) == []
    assert H.conferir_manifesto(split) == []
    man = H.carregar_manifesto()
    assert man["referencia"]["sha256_split"] == split["sha256_split"]
    assert man["referencia"]["sha256_conteudo"] == split["sha256_conteudo"]
    assert man["resumo"]["test"]["n_casos"] == len(split["test"]) == 24
    assert man["resumo"]["dev"]["n_casos"] == len(split["dev"]) == 36
    # cada caso do split tem pelo menos o caso.yaml e um documento no manifesto
    por_caso = {c.split("/", 1)[0] for c in man["arquivos"] if "/" in c}
    assert por_caso == set(split["dev"]) | set(split["test"])
    # o sha256 do caso.yaml no manifesto é o mesmo do SPLIT.yaml (as duas fontes concordam)
    for c in split["casos"]:
        assert man["arquivos"][f"{c['id']}/caso.yaml"]["sha256"] == c["sha256_caso"]


def test_registro_versionado_tem_cadeia_integra():
    caminho = H.DIR_CASOS / "registro_teste.jsonl"
    if not caminho.exists():
        pytest.skip("nenhum uso do teste registrado ainda")
    assert H.conferir_registro(caminho) == []


# --- split falso (cópias de casos do dev) --------------------------------------------------------------------


def _split_falso(destino: Path, dev: list[str], teste: list[str], congelado: bool = True) -> dict:
    destino.mkdir(parents=True, exist_ok=True)
    real = H.carregar_split()
    assert set(dev + teste) <= set(real["dev"]), "o split falso só pode usar casos do dev"
    casos = []
    for cid in dev + teste:
        shutil.copytree(H.DIR_CASOS / cid, destino / cid)
        b = (destino / cid / "caso.yaml").read_bytes()
        classe = yaml.safe_load(b.decode("utf-8"))["classe"]
        casos.append({"id": cid, "classe": classe, "split": "dev" if cid in dev else "test",
                      "sha256_caso": hashlib.sha256(b).hexdigest()})
    listas = {"dev": dev, "test": teste}

    def conteudo(ids):
        return hashlib.sha256("".join(f"{c['id']}:{c['sha256_caso']}\n" for c in casos if c["id"] in ids)
                              .encode()).hexdigest()

    split = {"gerador": {"versao": "teste"}, "congelado": congelado, "dev": dev, "test": teste, "casos": casos,
             "sha256_split": hashlib.sha256(json.dumps(listas, sort_keys=True).encode()).hexdigest(),
             "sha256_conteudo": {"dev": conteudo(dev), "test": conteudo(teste)}}
    (destino / "SPLIT.yaml").write_text(yaml.safe_dump(split, allow_unicode=True, sort_keys=False), encoding="utf-8")
    shutil.copy(H.DIR_CASOS / ".gitattributes", destino / ".gitattributes")
    H.escrever_manifesto(H.montar_manifesto(split, destino), destino / "MANIFESTO.yaml")
    return split


@pytest.fixture
def falso(tmp_path, monkeypatch):
    d = tmp_path / "casos"
    split = _split_falso(d, ["GLD-0002"], ["GLD-0010"])
    monkeypatch.setenv("LAUDO_REGISTRO_TESTE", str(tmp_path / "registro.jsonl"))
    return d, split, tmp_path / "registro.jsonl"


def test_manifesto_acusa_arquivo_mudado_sumido_novo_e_split(falso):
    d, split, _ = falso
    assert H.conferir_manifesto(split, d) == []
    alvo = d / "GLD-0010" / "nfe_1.xml"
    alvo.write_bytes(alvo.read_bytes() + b" ")
    (d / "GLD-0010" / "gta_1.json").unlink()
    (d / "GLD-0002" / "extra.txt").write_text("novo", encoding="utf-8")
    probs = H.conferir_manifesto(split, d)
    assert any("GLD-0010/nfe_1.xml: conteúdo mudou" in p for p in probs)
    assert any("GLD-0010/gta_1.json: sumiu" in p for p in probs)
    assert any("GLD-0002/extra.txt: arquivo novo" in p for p in probs)
    outro = {**split, "test": ["GLD-0002"], "dev": ["GLD-0010"]}
    assert any("SPLIT.yaml" in p for p in H.conferir_manifesto(outro, d))


def test_texto_livre_do_split_nao_invalida_o_manifesto(falso):
    d, split, _ = falso
    corrigido = {**split, "nota": "texto corrigido depois", "congelamento": {"protocolo": "seção nova"}}
    assert H.conferir_manifesto(corrigido, d) == []
    assert H.conferir_manifesto(split, d) == []


def test_manifesto_e_yaml_valido_com_lf(falso):
    d, _, _ = falso
    bruto = (d / "MANIFESTO.yaml").read_bytes()
    assert b"\r\n" not in bruto
    man = yaml.safe_load(bruto.decode("utf-8"))
    assert man["sha256_manifesto"] == man["resumo"]["total"]["sha256"]
    assert set(man["resumo"]) >= {"dev", "test", "total"}


def test_gate_do_teste_congelado(falso):
    d, split, _ = falso
    assert H.toca_teste(split, {"dev": ["GLD-0002"]}) is False
    assert H.toca_teste(split, {"selecao": ["GLD-0010"]}) is True
    assert H.checar_uso_do_teste(False, False, None, split, d) == []
    erros = H.checar_uso_do_teste(True, False, None, split, d)
    assert erros and "--final" in erros[0]
    assert any("--motivo" in e for e in H.checar_uso_do_teste(True, True, None, split, d))
    assert any("--motivo" in e for e in H.checar_uso_do_teste(True, True, "curto", split, d))
    assert H.checar_uso_do_teste(True, True, "rodada final de teste", split, d) == []
    (d / "GLD-0010" / "caso.yaml").write_bytes(b"adulterado")
    assert any("MANIFESTO" in e for e in H.checar_uso_do_teste(True, True, "rodada final de teste", split, d))


def test_split_aberto_nao_exige_final(tmp_path):
    d = tmp_path / "casos"
    split = _split_falso(d, ["GLD-0002"], ["GLD-0010"], congelado=False)
    assert H.checar_uso_do_teste(True, False, None, split, d) == []


# --- registro append-only ------------------------------------------------------------------------------------


def test_registro_encadeia_e_acusa_edicao(tmp_path):
    reg = tmp_path / "r.jsonl"
    for i in range(3):
        H.registrar_uso_teste({"evento": "inicio", "execucao": f"x{i}", "alvo": "golden_test"}, reg)
    assert H.conferir_registro(reg) == []
    linhas = reg.read_bytes().split(b"\n")
    assert json.loads(linhas[0])["anterior_sha256"] == "0" * 64
    assert json.loads(linhas[1])["anterior_sha256"] == hashlib.sha256(linhas[0]).hexdigest()
    # apagar a 2ª linha (esconder um uso) quebra a cadeia
    reg.write_bytes(b"\n".join([linhas[0], linhas[2]]) + b"\n")
    probs = H.conferir_registro(reg)
    assert any("seq" in p for p in probs) and any("anterior_sha256" in p for p in probs)
    # o registro continua aceitando eventos, e o próximo leva a marca da quebra para sempre
    novo = H.registrar_uso_teste({"evento": "inicio", "execucao": "x9", "alvo": "golden_test"}, reg)
    assert novo["cadeia_anterior"].startswith("QUEBRADA")


def test_uso_do_teste_registra_inicio_e_fim_com_status(tmp_path):
    reg = tmp_path / "r.jsonl"
    with H.uso_do_teste(True, script="x.py", alvo="golden_test", motivo="teste ok", argv=["--final"],
                        caminho=reg) as uso:
        uso["resultado"] = {"relatorio": "eval/reports/x.json"}
    with pytest.raises(RuntimeError), H.uso_do_teste(True, script="x.py", alvo="golden_test", motivo="teste erro",
                                                      argv=[], caminho=reg):
        raise RuntimeError("falhou")
    with pytest.raises(KeyboardInterrupt), H.uso_do_teste(True, script="x.py", alvo="golden_test",
                                                           motivo="teste ctrl-c", argv=[], caminho=reg):
        raise KeyboardInterrupt
    with H.uso_do_teste(False, script="x.py", alvo="golden_test", motivo=None, argv=[], caminho=reg) as nada:
        assert nada is None
    regs = H.ler_registro(reg)
    assert [r["evento"] for r in regs] == ["inicio", "fim"] * 3
    assert [r["status"] for r in regs if r["evento"] == "fim"] == ["ok", "erro: RuntimeError", "interrompido"]
    assert regs[1]["relatorio"] == "eval/reports/x.json"
    assert regs[0]["execucao"] == regs[1]["execucao"]
    assert H.conferir_registro(reg) == []
    res = H.resumo_registro(reg)
    assert res["execucoes"] == 3 and res["sem_fim"] == [] and res["cadeia"] == "ok"


def test_argv_seguro_tira_caminho_da_maquina():
    fora = str(Path(os.path.expanduser("~")) / "AppData" / "Temp" / "laudo-x" / "saida")
    dentro = str(REPO / "eval" / "reports")
    out = H.argv_seguro(["--saida", fora, "--outra", dentro, "--motivo", "r4: final"])
    assert out[1] == "<fora do repositório>/saida"
    assert out[3] == "eval/reports"
    assert out[5] == "r4: final"


# --- fluxo completo do run_eval.py num split falso (subprocesso: o harness troca classes do app) -------------

_EMBRULHO = '''
import json, sys
from pathlib import Path
sys.path.insert(0, {eval_!r})
import harness as H
H.DIR_CASOS = Path({casos!r})
H.DIR_TMP_PADRAO = Path({trab!r})
import run_eval as R
saida = {saida!r}
codigos = {{}}
for nome, extra in [("dev", []), ("teste_sem_final", ["--split", "test"]),
                    ("final_sem_motivo", ["--split", "test", "--final"]),
                    ("final", ["--final", "--motivo", "teste do fluxo final", "--sufixo", "_f"])]:
    sys.argv = ["run_eval.py", "--modo", "deterministico", "--saida", saida, *extra]
    codigos[nome] = R.main()
print("CODIGOS=" + json.dumps(codigos))
'''


def test_run_eval_exige_final_e_registra_o_uso(tmp_path):
    casos = tmp_path / "casos"
    _split_falso(casos, ["GLD-0002"], ["GLD-0010"])
    saida = tmp_path / "reports"
    reg = tmp_path / "registro.jsonl"
    script = tmp_path / "embrulho.py"
    script.write_text(_EMBRULHO.format(eval_=str(REPO / "eval"), casos=str(casos), trab=str(tmp_path / "trab"),
                                       saida=str(saida)), encoding="utf-8")
    env = {**os.environ, "LAUDO_REGISTRO_TESTE": str(reg), "PYTHONUTF8": "1",
           "PYTHONPATH": os.pathsep.join([str(REPO / "src"), os.environ.get("PYTHONPATH", "")])}
    r = subprocess.run([sys.executable, str(script)], cwd=REPO, env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300, check=False)
    linha = next((x for x in r.stdout.splitlines() if x.startswith("CODIGOS=")), None)
    assert linha, r.stdout[-3000:] + r.stderr[-3000:]
    codigos = json.loads(linha.split("=", 1)[1])
    assert codigos == {"dev": 0, "teste_sem_final": 2, "final_sem_motivo": 2, "final": 0}
    assert "só roda com --final" in r.stdout
    # sem --final: só o dev, nada no registro
    rel_dev = json.loads(next(p for p in saida.glob("*_deterministico.json")).read_text(encoding="utf-8"))
    assert list(rel_dev["splits"]) == ["dev"] and rel_dev["config"]["final"] is False
    # com --final: dev e teste, config reprodutível e o uso registrado (início e fim, com o relatório)
    rel = json.loads(next(p for p in saida.glob("*_deterministico_f.json")).read_text(encoding="utf-8"))
    cfg = rel["config"]
    assert list(rel["splits"]) == ["dev", "test"]
    assert cfg["final"] is True and cfg["motivo"] == "teste do fluxo final"
    assert cfg["llm"]["modelo"] == "n/a" and cfg["llm"]["digest"] == "n/a" and cfg["llm"]["ollama_versao"] == "n/a"
    assert len(cfg["sha256_eval"]) == 64 and len(cfg["sha256_src_lf"]) == 64
    assert cfg["manifesto"]["conferido"] == "ok"
    assert not any(":" in a and "\\" in a for a in cfg["argv"])  # sem caminho absoluto da máquina
    regs = H.ler_registro(reg)
    assert [x["evento"] for x in regs] == ["inicio", "fim"]
    assert regs[0]["casos_teste"] == ["GLD-0010"] and regs[0]["alvo"] == "golden_test"
    assert regs[0]["execucao"] == cfg["execucao_registro"] == regs[1]["execucao"]
    assert regs[1]["status"] == "ok"
    assert regs[1]["relatorio_sha256"] == H.sha256_arquivo(next(saida.glob("*_deterministico_f.json")))
    assert set(regs[1]["resumo"]) == {"dev", "test"}
    assert H.conferir_registro(reg) == []
