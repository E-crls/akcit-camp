"""Relatórios reprodutíveis (L59), repetição do agente (L60), A/B v2 dev × teste no slide (L07) e rótulo do
conjunto cego do red-team (L43). Sem Ollama: o cliente HTTP é falso."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "eval"))

import gerar_slide as GS
import harness as H
import metrics as M
import run_redteam as RT

# --- L59: o que identifica a rodada -----------------------------------------------------------------------------


class _Resp:
    def __init__(self, dados):
        self._d = dados

    def json(self):
        return self._d


class _ClienteFalso:
    def __init__(self, falhar: bool = False):
        self.falhar, self.urls = falhar, []

    def get(self, url, timeout=None):
        self.urls.append(url)
        if self.falhar:
            raise OSError("conexão recusada")
        if url.endswith("/api/version"):
            return _Resp({"version": "0.12.3"})
        return _Resp({"models": [{"name": "outro:1b", "digest": "x"},
                                 {"name": "qwen3.5:4b", "model": "qwen3.5:4b", "digest": "sha256:abc123",
                                  "details": {"family": "qwen35", "quantization_level": "Q4_K_M"}}]})


class _ProvFalso:
    nome, modelo, base_url, perfil = "ollama", "qwen3.5:4b", "http://127.0.0.1:11434", "escritorio"
    opcoes, think, keep_alive, retentativas = {"temperature": 0, "seed": 42, "num_ctx": 8192}, False, "30m", 2


def test_info_llm_sem_llm_e_na():
    info = H.info_llm(None)
    assert {info[k] for k in ("provedor", "modelo", "digest", "ollama_versao", "opcoes")} == {"n/a"}


def test_info_llm_com_ollama_registra_digest_versao_e_opcoes():
    cli = _ClienteFalso()
    info = H.info_llm(_ProvFalso(), cliente=cli)
    assert info["modelo"] == "qwen3.5:4b" and info["digest"] == "sha256:abc123"
    assert info["ollama_versao"] == "0.12.3" and info["ollama_local"] is True
    assert info["opcoes"]["options"] == {"temperature": 0, "seed": 42, "num_ctx": 8192}
    assert info["opcoes"]["think"] is False and info["detalhes"]["quantization_level"] == "Q4_K_M"
    assert cli.urls == ["http://127.0.0.1:11434/api/version", "http://127.0.0.1:11434/api/tags"]


def test_info_llm_com_ollama_fora_do_ar_nao_inventa():
    info = H.info_llm(_ProvFalso(), cliente=_ClienteFalso(falhar=True))
    assert info["digest"] == "n/a" and info["ollama_versao"] == "n/a" and info["modelo"] == "qwen3.5:4b"


def test_config_reprodutivel_tem_os_campos_do_l59():
    cfg = H.config_reprodutivel(llm=H.info_llm(None))
    for k in ("sha256_src", "sha256_src_lf", "sha256_eval", "sha256_eval_partes", "manifesto", "llm", "python",
              "pacotes"):
        assert k in cfg
    assert cfg["sha256_src"] == H.hash_src()
    assert {"golden/casos", "redteam", "(raiz)"} <= set(cfg["sha256_eval_partes"])
    assert cfg["manifesto"]["conferido"] == "ok"


def test_bytes_canonicos_so_normalizam_texto_convertido_pelo_git(tmp_path):
    txt, jpg = tmp_path / "a.py", tmp_path / "b.jpg"
    txt.write_bytes(b"x = 1\r\ny = 2\r\n")
    jpg.write_bytes(b"\xff\xd8\r\n\x00")
    sem = tmp_path / "sem"
    sem.mkdir()
    (sem / ".gitattributes").write_text("* -text\n", encoding="utf-8")
    cru = sem / "c.yaml"
    cru.write_bytes(b"a: 1\r\n")
    dirs = H._dirs_sem_conversao(tmp_path)
    assert H._bytes_canonicos(txt, dirs) == b"x = 1\ny = 2\n"
    assert H._bytes_canonicos(jpg, dirs) == b"\xff\xd8\r\n\x00"
    assert H._bytes_canonicos(cru, dirs) == b"a: 1\r\n"


def test_hash_eval_ignora_relatorios_e_registro():
    he = H.hash_eval()
    assert len(he["sha256"]) == 64 and he["n_arquivos"] > 400
    assert not any(k.startswith("reports") for k in he["partes"])


# --- L60: repetição -----------------------------------------------------------------------------------------------


def _caso(cid: str, status: str = "verificado", emissao: bool = True, fala: str = "Ok.") -> dict:
    return {"id": cid, "grupos": {"quantidade": {"esperado": "verificado", "sistema": status}},
            "emissao_permitida": emissao, "turnos": [{"acoes": ["conciliar_nfe[llm]"], "fala": fala}]}


def test_repeticao_identica_e_frase():
    a = {"test": [_caso("GLD-1"), _caso("GLD-2")]}
    d = M.comparar_rodadas(a, a)["test"]
    assert d["identica"] and d["casos_com_status_diferente"]["k"] == 0
    assert "idêntica" in M.frase_repeticao(d) and "não que o resultado valeria" in M.frase_repeticao(d)


def test_repeticao_que_muda_status_ou_so_fala():
    a = {"test": [_caso("GLD-1"), _caso("GLD-2")]}
    so_fala = {"test": [_caso("GLD-1", fala="Certo."), _caso("GLD-2")]}
    d = M.comparar_rodadas(a, so_fala)["test"]
    assert not d["identica"] and d["turnos_com_fala_diferente"]["k"] == 1
    assert "não muda nenhum número" in M.frase_repeticao(d)
    status = {"test": [_caso("GLD-1", status="pendente", emissao=False), _caso("GLD-2")]}
    d = M.comparar_rodadas(a, status)["test"]
    assert d["status_diferentes"] == [{"id": "GLD-1", "campos": {"quantidade": ["verificado", "pendente"]}}]
    assert d["emissao_ids"] == ["GLD-1"]
    assert "intervalo das duas execuções" in M.frase_repeticao(d)


# --- L07: A/B v2 dev × teste no slide ----------------------------------------------------------------------------


def _ab2(n: int, fo: int, res: int, so_a: int, so_f: int, p: float) -> dict:
    def br(k):
        return {"completas": M.proporcao(k, n), "completas_sem_registro": M.proporcao(k, n)}

    par = {"so_agente": so_a, "so_formulario": so_f, "mcnemar_p_exato": p}
    return {"config": {"n_casos": n, "split": "x"},
            "principal": {"formulario": br(fo), "agente": br(fo), "agente_residual": br(res),
                          "pareado": {"agente_residual": par, "agente_residual_sem_registro": par}}}


@pytest.mark.parametrize(("teste", "esperado"), [
    ((24, 10, 22, 12, 0, 0.0002), "o ganho se repete"),
    ((24, 18, 21, 4, 1, 0.375), "não é estatisticamente significativa"),
    ((24, 20, 20, 2, 2, 1.0), "empate"),
    ((24, 21, 18, 1, 4, 0.375), "se inverte"),
])
def test_frase_honesta_do_ab2_no_teste_para_cada_resultado(teste, esperado):
    dev = _ab2(36, 28, 35, 8, 1, 0.039)
    frase = GS.frase_ab2_teste(dev, _ab2(*teste))
    assert esperado in frase
    linhas = GS.linhas_ab2_teste(dev, _ab2(*teste))
    assert any("lado a lado" in x for x in linhas) and any("**teste**" in x for x in linhas)


def test_slide_mostra_dev_e_teste_e_a_repeticao(tmp_path, monkeypatch):
    """Com os relatórios complementares da rodada final, o slide ganha o A/B v2 do teste ao lado do dev e a
    repetição do agente (aqui, cópias dos relatórios da r3 renomeadas, só para exercitar o caminho)."""
    import json
    import shutil

    nomes = ("agente", "deterministico", "redteam_agente", "redteam_deterministico", "ab_centralidade",
             "ab_centralidade_v2")
    if not all((GS.DIR / f"2026-10-09_{n}_r3.json").exists() for n in nomes):
        pytest.skip("relatórios da r3 ausentes")
    for n in nomes:
        shutil.copy(GS.DIR / f"2026-10-09_{n}_r3.json", tmp_path / f"2026-10-09_{n}_rx.json")
    ab2 = json.loads((GS.DIR / "2026-10-09_ab_centralidade_v2_r3.json").read_text(encoding="utf-8"))
    ab2["config"] |= {"split": "test", "n_casos": 24}
    (tmp_path / "2026-10-09_ab_centralidade_v2_rx_teste.json").write_text(json.dumps(ab2), encoding="utf-8")
    ag = json.loads((GS.DIR / "2026-10-09_agente_r3.json").read_text(encoding="utf-8"))
    ag["repeticao"] = {"referencia": "2026-10-09_agente_rx.json", "comparavel": True, "motivos": [],
                       "splits": M.comparar_rodadas(ag["casos"], ag["casos"], ag["splits"], ag["splits"])}
    (tmp_path / "2026-10-09_agente_rx_rep.json").write_text(json.dumps(ag), encoding="utf-8")
    monkeypatch.setattr(GS, "DIR", tmp_path)
    GS.SUFIXO["valor"] = "_rx"
    try:
        md = GS.gerar("2026-10-09")
        extras = GS.hashes_opcionais("2026-10-09")
    finally:
        GS.SUFIXO["valor"] = ""
    assert "A/B v2 no dev e no teste, lado a lado" in md and "**Leitura honesta (escrita antes de rodar):**" in md
    assert "Repetição do agente no teste" in md and "idêntica caso a caso" in md
    assert set(extras) == {"ab_centralidade_v2_teste", "agente_rep"}


def test_slide_recusa_relatorio_so_do_dev(tmp_path, monkeypatch):
    """Sem --final, run_eval.py roda só o dev (L41): o slide recusa com mensagem clara, em vez de KeyError."""
    import json

    (tmp_path / "2026-10-16_deterministico.json").write_text(
        json.dumps({"config": {"sha256_src": "0" * 64}, "splits": {"dev": {}}, "casos": {"dev": []}}),
        encoding="utf-8")
    monkeypatch.setattr(GS, "DIR", tmp_path)
    with pytest.raises(SystemExit, match="não tem o split de teste"):
        GS.gerar("2026-10-16")


def test_slide_sem_relatorios_complementares_nao_muda():
    assert GS.linhas_ab2_teste({"x": 1}, None) == []
    assert GS.linhas_repeticao(None) == []
    assert GS.linhas_cego(None, None) == []
    GS.SUFIXO["valor"] = ""
    try:
        assert GS._ler_opcional("2026-10-09", "agente_rep") is None
    finally:
        GS.SUFIXO["valor"] = ""


# --- L43: rótulo dos conjuntos do red-team -------------------------------------------------------------------------


def test_conjunto_do_arquivo():
    assert RT.conjunto_do_arquivo("pressao_social.yaml") == "original"
    assert RT.conjunto_do_arquivo("v2_pressao.yaml") == "v2"
    assert RT.conjunto_do_arquivo("v3_cego_agente_pressao.yaml") == "v3_cego"
    assert RT.conjunto_do_arquivo("v3_cego_agente/pressao.yaml") == "v3_cego"
    assert RT.conjunto_do_arquivo("qualquer.yaml", "v3_cego_humano") == "v3_cego"
    assert RT.conjunto_do_arquivo("qualquer.yaml", "v2") == "v2"


def test_padrao_do_redteam_deixa_o_cego_de_fora():
    """O cego só roda quando pedido (`--conjunto v3_cego`): nem o CI nem a equivalência gastam a execução cega."""
    padrao = RT.carregar()
    assert {c["conjunto"] for c in padrao} <= {"original", "v2"}
    cegos = RT.carregar(conjuntos=["v3_cego"])
    assert all(c["conjunto"] == "v3_cego" for c in cegos)
    assert not {c["id"] for c in cegos} & {c["id"] for c in padrao}


def test_relatorio_do_redteam_separa_os_conjuntos():
    def r(conj, legit=False, falhou=False):
        return {"categoria": "pressao_social" if not legit else "legitimo", "conjunto": conj, "legitimo": legit,
                "sucesso_ataque": falhou, "over_blocking": False, "defesa_esperada": [], "defesa_registrada": [],
                "acao_permitida": None, "acao_permitida_executada": False, "afirma_acao_sem_lastro": [],
                "esclarecimento": False, "id": f"RT-{conj}-{legit}", "acoes": [], "falas": [], "falhas": []}

    rs = [r("original"), r("v2"), r("v3_cego", falhou=True), r("v3_cego", legit=True)]
    res = RT.resumo(rs)
    assert set(res["conjuntos"]) == {"original", "v2", "v3_cego"}
    assert res["conjuntos"]["v3_cego"]["ataques"]["k"] == 1
    cfg = {"modo": "agente", "data": "2026-10-16", "n_casos": 4, "n_ataques": 3, "n_legitimos": 1, "duracao_s": 1,
           "sha256_src": "0" * 64, "argv": [], "v3_cego_execucao": {"modo": 1, "total": 1}}
    md = RT.relatorio_md({"config": cfg, "resumo": res, "casos": rs})
    assert "`v3_cego` = escritos por um agente isolado" in md
    assert "1ª execução registrada deste conjunto" in md
    linhas = GS.linhas_cego({"resumo": res, "config": cfg}, None)
    assert linhas and "Conjunto cego" in linhas[0] and "1 ataque(s) passaram" in linhas[0]


# --- L59 no A/B v1 (onda 3) -----------------------------------------------------------------------------------------


def test_ab1_config_reprodutivel_sem_llm():
    import argparse

    sys.path.insert(0, str(REPO / "eval" / "ab_centralidade"))
    import run_ab as AB

    a = argparse.Namespace(perfil_llm="escritorio", perfis=["P1"], bracos=["checklist"])
    split = H.carregar_split()
    cfg = AB.montar_config(a, ["GLD-0002"], split, None, H.info_llm(None), 1.0, None, None)
    for k in ("sha256_src", "sha256_eval", "sha256_eval_partes", "manifesto", "llm", "pacotes", "python",
              "sha256_split", "fiscal_simulado_sha256", "casos", "bracos", "ollama_ps_inicio", "data"):
        assert k in cfg, k
    assert cfg["llm"]["digest"] == H.NA and cfg["manifesto"]["conferido"] == "ok"
    pareado = {"n_pares": 0, "so_agente_suficiente": 0, "so_checklist_suficiente": 0, "mcnemar_p_exato": None}
    md = AB.relatorio_md({"config": cfg, "resumo": {"pareado": pareado}, "episodios": []})
    assert "Reprodutibilidade: `sha256(eval/)=" in md and "LLM: n/a" in md
