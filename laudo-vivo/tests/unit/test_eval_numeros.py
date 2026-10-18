"""Fonte única de números (L06/L49, onda 3): versão de palco num lugar só, ALVOS ampliados, regra do
congelamento que depende do `SPLIT.yaml` e desclassificações de palco (14/10/2026) sempre com a data de corte.

Pós-r4 (16/10/2026, P2): chaves do A/B v2 no teste, do red-team cego e da repetição lidas dos relatórios gravados,
par obrigatório no `--verificar` (o dev nunca sem o teste, o red-team da equipe nunca sem o cego), aceite do hash
LF de `src/` (clone), régua nova do veredito para rodadas futuras e a seção "Depois da r4" condicionada aos
relatórios."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "eval"))

import desclassificacao_marcadores as DM
import gerar_numeros as GN
import gerar_slide as GS

TAB = {"desc.ano_2026.valor": "4.599", "desc.ate.valor": "13/10/2026", "desc.motivo013_2026.valor": "368",
       "desc.ano_2026.com_data": "4.599 (até 13/10/2026)", "desc.memorando.ano_2026.valor": "4.553",
       "desc.memorando.ate.valor": "06/10/2026"}


def m(chave: str) -> str:
    return f"<!--n:{chave}-->{TAB[chave]}<!--/n-->"


def test_versao_de_palco_vem_de_um_lugar_so():
    p = GS.palco()
    assert (GN.DATA_PADRAO, GN.SUFIXO_PADRAO) == (p["rodada"]["data"], p["rodada"]["sufixo"])
    assert GN.DESC_PALCO == p["desclassificacao"]["palco"] == "atual"
    assert (DM.GN.DATA_PADRAO, DM.GN.SUFIXO_PADRAO) == (GN.DATA_PADRAO, GN.SUFIXO_PADRAO)
    # o arquivo versionado existe e fica fora do sha256(eval/) (reports/)
    assert GS.PALCO.exists() and GS.PALCO.parent.name == "reports"
    assert json.loads(GS.PALCO.read_text(encoding="utf-8"))["rodada"]["sufixo"].startswith("_r")


def test_alvos_absorvem_os_textos_do_observatorio_e_os_novos():
    novos = {"CHANGELOG.md", "eval/single_vs_multi.md", "bench/desclassificacao/README.md", "validacao/README.md",
             "eval/retroteste/README.md"}
    assert novos <= set(GN.ALVOS)
    assert set(DM.TEXTOS) <= set(GN.ALVOS)


@pytest.mark.parametrize(("texto", "congelado", "acusa"), [
    ("O split de teste será congelado em 16/10/2026.", True, True),
    ("O split de teste **ainda não está congelado**.", True, True),
    ("O split de teste foi congelado em 16/10/2026 (sha256 f47e4446…).", True, False),
    ("golden set congelado desde 08/10", False, True),
    ("golden set congelado em 16/10/2026", True, False),
    ("O split de teste será congelado em 16/10/2026. <!--historico-->", True, False),
])
def test_regra_do_congelamento_depende_do_split(texto, congelado, acusa):
    erros = GN.conferir_texto("README.md", texto, {}, congelado=congelado)
    assert bool(erros) == acusa, erros


def test_total_de_2026_sempre_com_a_data_de_corte():
    sem_data = f"Em 2026 já houve {m('desc.ano_2026.valor')} desclassificações; {m('desc.motivo013_2026.valor')} por 013."
    erros = GN.conferir_desclassificacoes("docs/entregaveis/pitch-regional-3min.md", sem_data)
    assert len(erros) == 2 and all("data de corte" in e for e in erros)
    com_data = f"{m('desc.ano_2026.valor')} desclassificações em 2026, até {m('desc.ate.valor')}."
    assert GN.conferir_desclassificacoes("docs/entregaveis/pitch-regional-3min.md", com_data) == []
    # a data pode estar em outra linha do mesmo parágrafo (tabela), ou vir na variante com_data
    tabela = f"| 2026 | {m('desc.ano_2026.valor')} |\n| corte | {m('desc.ate.valor')} |"
    assert GN.conferir_desclassificacoes("bench/desclassificacao/README.md", tabela) == []
    assert GN.conferir_desclassificacoes("x.md", f"Foram {m('desc.ano_2026.com_data')}.") == []
    # outro parágrafo não vale
    longe = f"{m('desc.ano_2026.valor')} em 2026.\n\nCorte: {m('desc.ate.valor')}."
    assert GN.conferir_desclassificacoes("x.md", longe)


def test_versao_historica_nao_entra_no_palco():
    hist = f"Versão de 07/10: {m('desc.memorando.ano_2026.valor')} até {m('desc.memorando.ate.valor')}."
    assert GN.conferir_desclassificacoes("validacao/README.md", hist) == []  # fora do palco: histórico com data
    erros = GN.conferir_desclassificacoes("docs/entregaveis/qa-banca.md", hist)
    assert erros and "07/10/2026" in erros[0]
    assert GN.conferir_texto("docs/entregaveis/qa-banca.md", "Foram 4.553 desclassificações.", {}, True)
    assert GN.conferir_texto("bench/desclassificacao/README.md", "a versão de 07/10 (15.902 registros)", {}, True) == []


def test_numeros_das_desclassificacoes_tem_a_variante_com_data():
    n: dict = {}
    GN.numeros_desclassificacao(n, {})
    if not n:
        pytest.skip("bench/desclassificacao/resumo.json ausente")
    assert n["desc.ano_2026"]["com_data"] == f"{n['desc.ano_2026']['valor']} (até {n['desc.ate']['valor']})"
    assert n["desc.ate"]["valor"] != n["desc.memorando.ate"]["valor"]  # 14/10 (palco) × 07/10 (histórico)


def test_aplicar_com_outra_versao_exige_fixar_palco(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["gerar_numeros.py", "--data", "2026-10-20", "--sufixo", "_r4", "--aplicar"])
    assert GN.main() == 2
    assert "--fixar-palco" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["gerar_numeros.py", "--verificar", "--fixar-palco"])
    assert GN.main() == 2


def test_fixar_palco_guarda_a_anterior(tmp_path, monkeypatch):
    palco = tmp_path / "palco.json"
    palco.write_text(json.dumps(GS.PALCO_PADRAO), encoding="utf-8")
    monkeypatch.setattr(GS, "PALCO", palco)
    monkeypatch.setattr(GN, "REPO", tmp_path)
    novo = GN.fixar_palco("2026-10-20", "_r4", "rodada r4 congelada")
    assert novo["rodada"] == {"data": "2026-10-20", "sufixo": "_r4"}
    assert novo["anteriores"][0]["sufixo"] == "_r3" and novo["desclassificacao"]["palco"] == "atual"
    assert GS.palco()["rodada"]["sufixo"] == "_r4"
    assert b"\r\n" not in palco.read_bytes()


def test_gravar_texto_mantem_o_fim_de_linha(tmp_path):
    crlf, lf = tmp_path / "a.md", tmp_path / "b.md"
    crlf.write_bytes(b"x\r\ny\r\n")
    lf.write_bytes(b"x\ny\n")
    GN.gravar_texto(crlf, "x\nz\n")
    GN.gravar_texto(lf, "x\nz\n")
    assert crlf.read_bytes() == b"x\r\nz\r\n" and lf.read_bytes() == b"x\nz\n"


def test_rodape_de_rodada_anterior_ao_congelamento_nao_diz_sera_congelado():
    import yaml

    split = yaml.safe_load((REPO / "eval" / "golden" / "casos" / "SPLIT.yaml").read_text(encoding="utf-8"))
    frase = GS.frase_antes_do_congelamento({"sha256_conteudo": {"test": split["sha256_conteudo"]["test"]}})
    assert "será congelado" not in frase and "mesmo conjunto que foi congelado em 16/10/2026" in frase
    outro = GS.frase_antes_do_congelamento({"sha256_conteudo": {"test": "0" * 64}})
    assert "NÃO é o conjunto congelado" in outro


# --- Pós-r4 (P2): chaves do teste e do cego, par obrigatório, hash LF, régua e r4.1 ------------------------------

R4 = ("2026-10-16", "_r4")
_COMPLEMENTARES = ("ab_centralidade_v2_r4_teste", "redteam_agente_r4_v3cego", "redteam_deterministico_r4_v3cego",
                   "agente_r4_rep")


def _montar_r4() -> dict:
    principais = ("agente", "deterministico", "redteam_agente", "redteam_deterministico", "ab_centralidade",
                  "ab_centralidade_v2")
    existem = [GS.DIR / f"{R4[0]}_{n}{R4[1]}.json" for n in principais]
    existem += [GS.DIR / f"{R4[0]}_{n}.json" for n in _COMPLEMENTARES]
    if not all(p.exists() for p in existem):
        pytest.skip("relatórios da r4 ausentes")
    try:
        return GN.montar(*R4)
    finally:
        GS.SUFIXO["valor"] = ""


def test_chaves_novas_com_os_valores_do_relatorio_real():
    n = _montar_r4()["numeros"]
    v = {k: x.get("fmt") or x.get("valor") for k, x in n.items()}
    assert v["ab2_teste.residual"] == "71% [51–85%] (17/24)"
    assert v["ab2_teste.formulario"] == "58% [39–76%] (14/24)"
    assert v["ab2_teste.residual_sem_registro"] == "79% [60–91%] (19/24)"
    assert v["ab2_teste.formulario_sem_registro"] == "88% [69–96%] (21/24)"
    assert v["ab2_teste.mcnemar"] == "p = 0,5078" and n["ab2_teste.mcnemar"]["curto"] == "p = 0,51"
    assert v["ab2_teste.mcnemar_sem_registro"] == "p = 0,6875"
    assert n["ab2_teste.mcnemar_sem_registro"]["curto"] == "p = 0,69"
    assert v["ab2_teste.pares"] == "6 × 3" and v["ab2_teste.pares_sem_registro"] == "2 × 4"
    assert n["ab2_teste.fala_llm"]["kn"] == "40/46" and n["ab2_teste.fala_regras"]["kn"] == "32/46"
    assert v["ab2_teste.espurias_llm"] == "1" and v["ab2_teste.espurias_regras"] == "0"
    assert n["ab2_teste.leitura_precisao_aceitos"]["kn"] == "2533/2541"
    assert n["ab2_teste.residual_completo"]["kn"] == "31/32"
    assert n["ab2_teste.tempo_residual"]["uma_casa"] == "34,5 s" and v["ab2_teste.tempo_formulario"] == "215 s"
    assert v["ab2_teste.tempo_maquina_residual"] == "48 s" and v["ab2_teste.toques_residual"] == "12"
    assert v["ab2_teste.toques_formulario"] == "304" and v["ab2_teste.n"] == "24"
    assert v["ab2_teste.media_residual_sem_registro"] == "77,6%"  # 0,7755 gravado: meio para cima
    assert v["redteam.cego_ataques"] == "20% [10–37%] (6/30)"
    assert n["redteam.cego_ataques_sem_semicega"]["kn"] == "6/26"
    assert n["redteam.cego_sem_llm_ataques"]["kn"] == "5/30" and n["redteam.cego_overblocking"]["kn"] == "0/10"
    assert n["agente_rep.casos_status_diferente"]["kn"] == "0/24"
    assert v["versao.sha256_src_lf"] == "02d050f4267708c9"
    # o p da fala por pares não está em relatório nenhum: não vira chave
    assert not any(k.startswith("ab2_teste.fala") and "mcnemar" in k for k in n)


def test_chaves_antigas_continuam_iguais():
    n = _montar_r4()["numeros"]
    assert n["ab2.residual"]["fmt"] == "97% [86–100%] (35/36)" and n["ab2.formulario"]["kn"] == "15/36"
    assert n["ab2.mcnemar_sem_registro"]["valor"] == "p = 0,039"  # p_valor (3 casas) não mudou
    assert n["redteam.ataques"]["kn"] == "0/80" and n["recall_teste"]["kn"] == "9/9"
    assert n["ab2.tempo_residual"] == {"valor": "37 s"}
    gravado = json.loads((REPO / "docs" / "entregaveis" / "numeros.json").read_text(encoding="utf-8"))["numeros"]
    assert all(n.get(k) == x for k, x in gravado.items())  # nenhuma chave gravada mudou de valor


@pytest.mark.parametrize(("texto", "acusa"), [
    ("O agente fechou <!--n:ab2.residual.valor-->97%<!--/n--> no dev.", True),
    ("<!--n:ab2.residual.valor-->97%<!--/n--> no dev; no teste, <!--n:ab2_teste.residual.valor-->71%<!--/n-->.",
     False),
    # outra linha do mesmo parágrafo vale; outro parágrafo não
    ("Dev: <!--n:ab2.formulario_sem_registro.valor-->78%<!--/n-->\nteste: <!--n:ab2_teste.n.valor-->24<!--/n-->",
     False),
    ("Dev: <!--n:ab2.formulario.valor-->42%<!--/n-->\n\nTeste: <!--n:ab2_teste.formulario.valor-->58%<!--/n-->",
     True),
    # numa tabela, a unidade é a linha
    ("| dev | <!--n:ab2.residual.valor-->97%<!--/n--> |\n| teste | <!--n:ab2_teste.residual.valor-->71%<!--/n--> |",
     True),
    ("| A/B | <!--n:ab2.residual.valor-->97%<!--/n--> (dev) · <!--n:ab2_teste.residual.valor-->71%<!--/n--> |",
     False),
    ("Red-team <!--n:redteam.ataques.kn-->0/80<!--/n-->.", True),
    ("Red-team <!--n:redteam.ataques.kn-->0/80<!--/n--> e cego <!--n:redteam.cego_ataques.kn-->6/30<!--/n-->.",
     False),
    # o 6/26 sozinho não substitui o 6/30
    (("Red-team <!--n:redteam.ataques.kn-->0/80<!--/n-->; cego "
      "<!--n:redteam.cego_ataques_sem_semicega.kn-->6/26<!--/n-->."), True),
    ("Depois da correção: <!--n:r41.v3_regressao_sem_llm_ataques.kn-->0/30<!--/n-->.", True),
    ("Histórico: <!--n:ab2.residual.valor-->97%<!--/n--> <!--historico-->", False),
    ("Sem LLM, <!--n:redteam.sem_llm_ataques.kn-->0/80<!--/n-->; fala <!--n:ab2.fala_llm.valor-->99%<!--/n-->.",
     False),
])
def test_par_obrigatorio(texto, acusa):
    erros = GN.conferir_pares("docs/entregaveis/qa-banca.md", texto)
    assert bool(erros) == acusa, erros
    tabela = dict(GN.RX_MARCADOR.findall(texto))  # os valores conferem: só o par pode acusar
    assert bool(GN.conferir_texto("docs/entregaveis/qa-banca.md", texto, tabela, True)) == acusa


def test_par_obrigatorio_em_html_usa_a_linha_da_tabela():
    tela = ("<div>\n  <b><!--n:redteam.ataques.kn-->0/80<!--/n--></b>\n  <i><!--n:redteam.cego_ataques.kn-->6/30"
            "<!--/n--></i>\n</div>\n<table>\n  <tr>\n    <td><!--n:ab2.residual.valor-->97%<!--/n--></td>\n"
            "  </tr>\n  <tr><td><!--n:ab2_teste.residual.valor-->71%<!--/n--></td></tr>\n</table>")
    erros = GN.conferir_pares("docs/entregaveis/deck/index.html", tela)
    assert len(erros) == 1 and ":7:" in erros[0] and "ab2.residual" in erros[0]  # só o <tr> do dev
    junto = tela.replace("<td><!--n:ab2.residual.valor-->97%<!--/n--></td>",
                         "<td><!--n:ab2.residual.valor-->97%<!--/n--> / "
                         "<!--n:ab2_teste.residual.valor-->71%<!--/n--></td>")
    assert GN.conferir_pares("docs/entregaveis/deck/index.html", junto) == []


def test_alvos_e_palco_pos_r4():
    assert "docs/decisao.md" in GN.ALVOS
    assert "docs/entregaveis/deck/index.html" in GN.TEXTOS_PALCO and set(GN.TEXTOS_PALCO) <= set(GN.ALVOS)


def test_aceita_o_hash_lf_de_um_clone(monkeypatch):
    versao = {"sha256_src": "a" * 64, "sha256_src_lf": "b" * 64}
    monkeypatch.setattr(GN, "_hash_src_atual", lambda: "b" * 64)  # num clone com LF, hash_src() dá o LF
    monkeypatch.setattr(GN, "_hash_src_lf_atual", lambda: "b" * 64)
    linhas = GN.conferir_src(versao, None)
    assert not any(x.startswith("AVISO") for x in linhas) and "hash LF" in linhas[-1]
    assert "aaaaaaaaaaaaaaaa" in linhas[0] and "bbbbbbbbbbbbbbbb" in linhas[0]  # mostra os dois
    monkeypatch.setattr(GN, "_hash_src_atual", lambda: "a" * 64)  # Windows: os mesmos bytes
    assert not any(x.startswith("AVISO") for x in GN.conferir_src(versao, None))
    monkeypatch.setattr(GN, "_hash_src_atual", lambda: "c" * 64)  # o código mudou
    monkeypatch.setattr(GN, "_hash_src_lf_atual", lambda: "d" * 64)
    assert GN.conferir_src(versao, None)[-1].startswith("AVISO")
    assert not GN.conferir_src(versao, {"sha256_src_atual": "c" * 64, "data": "x"})[-1].startswith("AVISO")
    assert GN.conferir_src(versao, {"sha256_src_atual": "e" * 64})[-1].startswith("AVISO")


def _ab(n: int, fo: int, res: int, so_a: int, so_f: int, p: float, data: str) -> dict:
    def br(k: int) -> dict:
        return {"completas": GS.M.proporcao(k, n), "completas_sem_registro": GS.M.proporcao(k, n)}

    par = {"so_agente": so_a, "so_formulario": so_f, "mcnemar_p_exato": p}
    return {"config": {"n_casos": n, "data": data},
            "principal": {"formulario": br(fo), "agente": br(fo), "agente_residual": br(res),
                          "pareado": {"agente_residual": par, "agente_residual_sem_registro": par}}}


def test_regua_nova_so_para_rodadas_futuras():
    assert GS.veredito_teste(0.79, 0.88, 0.6875) == "inverte"  # a régua da r4, escrita antes de rodar
    assert GS.veredito_teste(0.79, 0.88, 0.6875, "pos_r4") == "abaixo_sem_significancia"
    assert GS.veredito_teste(0.40, 0.88, 0.001, "pos_r4") == "inverte"
    assert GS.regua_do_teste({"config": {"data": "2026-10-16"}}) == "r4"
    assert GS.regua_do_teste({"config": {"data": "2026-11-20"}}) == "pos_r4"
    dev = _ab(36, 28, 35, 8, 1, 0.039, "2026-10-16")
    futura = GS.frase_ab2_teste(dev, _ab(24, 21, 19, 2, 4, 0.6875, "2026-11-20"))
    assert "não é estatisticamente significativa" in futura and "ajuste ao dev" not in futura
    assert "Nada foi ajustado" not in futura
    r4 = GS.frase_ab2_teste(dev, _ab(24, 21, 19, 2, 4, 0.6875, "2026-10-16"))
    assert "o resultado se inverte" in r4 and "parte do resultado do dev era ajuste ao dev" in r4


def test_nota_pos_resultado_confere_com_o_registro_e_com_o_relatorio():
    nota = GS.NOTAS_POS_RESULTADO["216355e9efc1"]["refazer"]
    reg = [json.loads(x) for x in GS.REGISTRO_TESTE.read_text(encoding="utf-8").splitlines() if x.strip()]
    seq = {e["seq"]: e for e in reg}
    a, b = nota["seq"]
    assert seq[a]["execucao"] == nota["primeira_execucao"] and seq[b]["execucao"] == "216355e9efc1"
    assert seq[a + 1]["em"].endswith(nota["primeiro_fim"] + "-03:00")
    assert seq[a + 1]["resumo"]["residual_completas"] == "{}/{}".format(*nota["antes"]["completas"])
    assert seq[b]["resumo"]["residual_completas"] == "17/24"
    antes = REPO / "dados_locais" / "r4" / "antes_refazer" / "2026-10-16_ab_centralidade_v2_r4_teste.json"
    if antes.exists():  # fora do git: só confere onde a cópia existe
        r = json.loads(antes.read_text(encoding="utf-8"))
        p = r["principal"]
        res = p["agente_residual"]
        assert (res["completas"]["k"], res["completas"]["n"]) == nota["antes"]["completas"]
        assert res["completas_sem_registro"]["k"] == nota["antes"]["sem_registro"][0]
        assert p["pareado"]["agente_residual_sem_registro"]["mcnemar_p_exato"] == nota["antes"]["p_sem_registro"]
        est = r["estabilidade_replicacoes"]["agente_residual"]
        assert est["completas_sem_registro"] == nota["antes"]["media_sem_registro"]
        bar = r["leitura"]["barragem"]
        assert (bar["cru_errado_barrado"], bar["cru_errado_aceito"]) == (nota["antes"]["barrados"],
                                                                         nota["antes"]["aceitos_errados"])
    assert GS.pct_meio(0.7755) == "77,6%" and GS.pct_meio(0.7406) == "74,1%"


def test_secao_r41_so_com_a_equivalencia_e_a_regressao(tmp_path, monkeypatch):
    monkeypatch.setattr(GS, "DIR", tmp_path)
    GS.SUFIXO["valor"] = "_r4"
    try:
        assert GS.linhas_pos_rodada("2026-10-16") == []
        eq = {"data": "20/10/2026 10:00", "referencia": {"sha256_src": "1154df4aceffbf20" + "0" * 48},
              "sha256_src_atual": "f" * 64, "motivo": "r4.1: correcoes de declaracao e PIN",
              "conferencias": [{"nome": x, "resultado": "igual"} for x in (
                  "golden set sem LLM", "red-team sem LLM", "A/B v2", "replay da demo na CLI, 19 passos",
                  "replay da demo na CLI, 17 passos", "contingência da interface, 19 passos")]}
        (tmp_path / "2026-10-16_equivalencia_r4.json").write_text(json.dumps(eq), encoding="utf-8")
        assert GS.linhas_pos_rodada("2026-10-16") == []  # só a equivalência: ainda não
        n: dict = {}
        GN.numeros_pos_rodada(n, "_r4", eq, {})
        assert n == {}
        reg = {"config": {"v3_cego_execucao": {"modo": 2, "total": 3}},
               "resumo": {"conjuntos": {"v3_cego": {"ataques": GS.M.proporcao(1, 30),
                                                    "ataques_sem_semicego": GS.M.proporcao(1, 26),
                                                    "over_blocking": GS.M.proporcao(0, 10)}}}}
        nome = "2026-10-20_redteam_deterministico_r4.1_v3regressao.json"
        (tmp_path / nome).write_text(json.dumps(reg), encoding="utf-8")
        md = "\n".join(GS.linhas_pos_rodada("2026-10-16"))
        assert "## Depois da r4 (r4.1): não cego" in md and "6/6 igual" in md and "2ª execução" in md
        assert "Não substitui o resultado cego" in md and "não foram remedidos com o LLM" in md
        assert "sem requisição nova ao LLM" in md
        GN.numeros_pos_rodada(n, "_r4", eq, {})
        assert n["r41.equivalencia_iguais"]["valor"] == "6/6"
        assert n["r41.v3_regressao_sem_llm_ataques"]["kn"] == "1/30"
        eq["conferencias"][0]["resultado"] = "DIFERENTE"
        (tmp_path / "2026-10-16_equivalencia_r4.json").write_text(json.dumps(eq), encoding="utf-8")
        assert "não passa no portão" in "\n".join(GS.linhas_pos_rodada("2026-10-16"))
    finally:
        GS.SUFIXO["valor"] = ""
