"""Frases proibidas (`scripts/checar_frases_proibidas.py`): o autoteste de cada regra (o exemplo é acusado, a
frase certa e o "diga no lugar" não), as regras de contexto pós-r4 (P21, P22 e P24), o texto de dentro do .zip
do pacote de exibição, a exceção normativa do MCR 2-7, item 21, e a varredura padrão.

A varredura padrão é conferida pelo que ela cobre e por rodar sem erro, não por sair limpa: as linhas que as
regras P20 a P25 acusam hoje são trabalho dos pacotes de texto (plano pós-r4), e o portão de 0 achados é o
`scripts/tarefas.sh ci` do fechamento.
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import checar_frases_proibidas as CF

NOVAS = ("P20", "P21", "P22", "P23", "P24", "P25")


def ids(texto: str, arquivo: str = "<texto>") -> list[str]:
    """IDs das regras que acusam o texto (sem as linhas liberadas)."""
    return [a.regra.id for a in CF.achados_no_texto(texto, arquivo) if not a.liberado]


def test_autoteste_sem_erros():
    assert CF.autoteste() == []


def test_regras_novas_existem_e_ids_unicos():
    todos = [r.id for r in CF.REGRAS]
    assert len(todos) == len(set(todos))
    assert set(NOVAS) <= set(todos)


@pytest.mark.parametrize("regra", CF.REGRAS, ids=lambda r: r.id)
def test_exemplos_acusados_pela_propria_regra(regra):
    assert regra.exemplos
    for ex in regra.exemplos:
        assert regra.id in ids(ex), ex


@pytest.mark.parametrize("regra", CF.REGRAS, ids=lambda r: r.id)
def test_frases_certas_e_diga_no_lugar_nao_acusados(regra):
    for limpo in regra.limpos:
        assert ids(limpo) == [], limpo
    assert ids(regra.diga.replace("R$ 79", "R$ 79 (preço-alvo)")) == [], regra.diga


@pytest.mark.parametrize("rid", NOVAS)
def test_regras_novas_tem_exemplo_e_frase_certa(rid):
    regra = next(r for r in CF.REGRAS if r.id == rid)
    assert regra.exemplos and regra.limpos


# P20 -----------------------------------------------------------------------------------------------------------

def test_p20_concilia_mais_e_a_forma_negada():
    assert "P20" in ids("No teste, a IA concilia mais fiscalizações que o formulário.")
    assert "P20" in ids('confira que "concilia mais\n   fiscalizações que o formulário" continua valendo')
    assert "P20" not in ids("Contra um formulário digitado, o agente não conciliou mais fiscalizações no teste.")


# P21: ressalva na mesma linha ou na mesma frase ----------------------------------------------------------------

def test_p21_ressalva_do_cego_na_linha_ou_na_frase():
    assert "P21" in ids("O agente nunca afirma o que não tem prova, se abstém quando deve.")
    assert "P21" not in ids("O agente nunca afirma o que não tem prova; no red-team cego, três declarações "
                            "viraram 'verificado' sem prova.")
    # a ressalva na linha seguinte, mas ainda na mesma frase, vale
    assert "P21" not in ids("O agente não afirma o que não tem prova,\nmas no conjunto cego 3 declarações passaram.")
    # outra linha e outra frase: não vale
    assert "P21" in ids("O agente não afirma o que não tem prova.\nNo red-team cego, 3 declarações passaram.")
    # "não é cego" não é a ressalva
    assert "P21" in ids("O agente não afirma o que não tem prova (o red-team não é cego).")


# P22: o cego no mesmo parágrafo (item de lista e linha de tabela são parágrafos) -------------------------------

def test_p22_cego_no_mesmo_paragrafo():
    assert "P22" in ids("No red-team, 0 de 80 ataques passaram.")
    assert "P22" not in ids("Red-team da equipe: 0/80 ataques.\nNo red-team cego, passaram 6 de 30.")
    assert "P22" in ids("Red-team da equipe: 0/80 ataques.\n\nNo red-team cego, passaram 6 de 30.")
    # o número do cego (6/30, 6/26) também é a ressalva; o marcador escondido não atrapalha
    assert "P22" not in ids("<!--n:redteam.ataques.kn-->0/80<!--/n--> × "
                            "<!--n:redteam.cego_ataques.kn-->6/30<!--/n-->")


def test_p22_item_de_lista_e_linha_de_tabela_sao_paragrafos():
    lista = "- Red-team da equipe: 0/80.\n- Red-team cego: 6/30."
    assert [a.linha for a in CF.achados_no_texto(lista) if a.regra.id == "P22"] == [1]
    tabela = "| Red-team da equipe | 0/80 |\n| Red-team cego | 6/30 |"
    assert [a.linha for a in CF.achados_no_texto(tabela) if a.regra.id == "P22"] == [1]
    assert "P22" not in ids("| Red-team | equipe 0/80; cego 6/30 (6/26 sem a família semi-cega) |")


@pytest.mark.parametrize("texto", [
    "0/80 ataques passaram num red-team escrito pela equipe; falta um conjunto cego.",
    "O red-team também não é cego: 0/80 ataques passaram.",
    "red-team 0/80 ataques; red-team escrito pela equipe (não cego)",
    "0/80 ataques bem-sucedidos (casos escritos pela equipe, não cegos)",
    "red-team 0% [0–5%] de ataques bem-sucedidos; sem conjunto cego",
])
def test_p22_ressalva_negada_nao_vale(texto):
    assert "P22" in ids(texto)


def test_p22_outros_numeros_nao_casam():
    assert "P22" not in ids("R$ 0,80 por foto; 10/80 páginas; 0/800 erros; 0,80 de recall")


def test_registro_de_chaves_fora_das_regras_de_contexto():
    linha = "| `redteam.ataques` | 0% [0–5%] (0/80) | 0 de 80 |"
    assert "P22" in ids(linha, "docs/entregaveis/qa-banca.md")
    for nome in CF.REGISTRO_DE_CHAVES:
        assert ids(linha, nome) == []


# P23 -----------------------------------------------------------------------------------------------------------

def test_p23_papel_e_fala_reais():
    assert "P23" in ids("<h2>Papel e fala reais: A/B v2, fiscal simulado</h2>")
    assert "P23" not in ids("Papel fotografado e fala livre, sintéticos, com fiscal simulado.")


# P24: número do dev numa frase sobre o teste, sem "dev" ---------------------------------------------------------

def test_p24_frase_do_teste_sem_dev():
    assert "P24" in ids("Dos campos aceitos no teste, 3904/3916 estavam certos.")
    assert "P24" not in ids("Dos campos aceitos no dev, 3904/3916 estavam certos.")
    assert "P24" not in ids("Dos campos aceitos, 3904/3916 estavam certos.")  # sem o teste: é do par do P2
    # a frase acaba no ponto: o teste na frase seguinte não conta
    assert "P24" not in ids("Leitura: 3904/3916. Isso foi antes do teste congelado.")
    assert "P24" not in ids("No teste congelado, 2533 de 2541 estavam certos (no dev, 3904/3916).")


def test_p24_par_97_42_com_marcadores_e_quebra_de_linha():
    rq2 = ("> 00:58. Num teste com fiscal simulado, com\n"
           ">    papel fotografado e fala livre, a IA levou <!--n:ab2.residual.valor-->97%<!--/n--> das\n"
           ">    fiscalizações ao conteúdo conciliado, contra <!--n:ab2.formulario.valor-->42%<!--/n--> digitando.")
    assert [a.linha for a in CF.achados_no_texto(rq2) if a.regra.id == "P24"] == [2]
    assert "P24" in ids("No teste congelado, <!--n:ab2.residual.valor-->97%<!--/n--> × "
                        "<!--n:ab2.formulario.valor-->42%<!--/n-->.")
    assert "P24" not in ids("No dev, onde o A/B foi desenvolvido: 97% contra 42%. No teste congelado, 19/24 "
                            "contra 21/24.")
    # 97% e 42% em frases diferentes não formam o par
    assert "P24" not in ids("No teste congelado, 97% dos campos. O formulário teve 42%.")


# P25 -----------------------------------------------------------------------------------------------------------

def test_p25_quem_escolhe_as_checagens():
    assert "P25" in ids("Por desenho, o LLM não escolhe as checagens nem dá o status.")
    assert "P25" in ids("o plano determinístico decide o que checar a partir do que chega")
    assert "P25" not in ids("O LLM pode chamar as checagens da etapa; quando não chama a óbvia, o plano mínimo "
                            "determinístico chama.")
    assert "P25" not in ids("o LLM não escolhe o status: ele vem das regras e do verificador")


# .zip, exceção normativa e linha de comando ---------------------------------------------------------------------

def _zip(caminho: Path, arquivos: dict[str, str]) -> Path:
    with zipfile.ZipFile(caminho, "w") as z:
        for nome, texto in arquivos.items():
            z.writestr(nome, texto)
    return caminho


def test_texto_de_dentro_do_zip_e_varrido(tmp_path):
    pacote = _zip(tmp_path / "pacote.zip", {
        "fundamento/f.json": '{"t": "a prova que falta nas fraudes do tipo boi de papel"}',
        "trilha/trace.jsonl": '{"fala": "o produtor suspeito"}\n',
        "evidencias/foto.jpg": "fraude",
    })
    achados = CF.varrer([pacote])
    assert sorted((a.arquivo.rsplit("!", 1)[1], a.regra.id) for a in achados) == [
        ("fundamento/f.json", "P08"), ("trilha/trace.jsonl", "P07")]
    assert all(a.arquivo.endswith((".zip!fundamento/f.json", ".zip!trilha/trace.jsonl")) for a in achados)


def test_excecao_normativa_so_em_docs_exemplos_e_so_para_o_termo():
    norma = "Ilícito penal ou fraude fiscal: IF comunica MP/autoridade tributária"
    no_exemplo = list(CF.achados_no_texto(norma, "docs/exemplos/DEMO.zip!pacote.json"))
    assert no_exemplo and all(a.liberado and "MCR 2-7" in a.nota for a in no_exemplo)
    assert "P08" in ids(norma, "docs/entregaveis/qa-banca.md")
    assert "P08" in ids("ilícitos penais ou fraudes fiscais; fraudes do tipo boi de papel", "docs/exemplos/x.html")
    assert "P08" in ids("a fraude fiscal do produtor", "docs/exemplos/x.html")


def test_main_relatorio_so_e_zip_ilegivel(tmp_path, capsys):
    texto = tmp_path / "t.md"
    texto.write_text("a IA concilia mais fiscalizações que o formulário; operação suspeita\n", encoding="utf-8")
    assert CF.main([str(texto)]) == 1
    assert CF.main([str(texto), "--relatorio"]) == 0
    saida = capsys.readouterr().out
    assert "resumo por regra" in saida and "P20: 1 linha(s)" in saida and "P07: 1 linha(s)" in saida
    assert CF.main([str(texto), "--so", "P20-P25"]) == 1
    assert "[P07]" not in capsys.readouterr().out
    assert CF.main([str(texto), "--so", "P01,P02"]) == 0
    assert CF.ids_de("P20-P25,p08") == {"P08", *NOVAS}
    with pytest.raises(ValueError):
        CF.ids_de("P99")
    ruim = tmp_path / "ruim.zip"
    ruim.write_bytes(b"isto nao e um zip")
    assert CF.main([str(ruim)]) == 2


def test_textos_do_zip_aceita_memoria():
    buf = io.BytesIO()
    _zip(buf, {"a.html": "<p>papel e fala reais</p>", "b.png": "papel e fala reais"})
    buf.seek(0)
    assert [n for n, _ in CF.textos_do_zip(buf, "docs/exemplos/x.zip")] == ["docs/exemplos/x.zip!a.html"]


# varredura padrão ------------------------------------------------------------------------------------------------

def test_varredura_padrao_cobre_os_textos_publicos_e_o_pacote():
    no_repo = [p for p in CF.RAIZES_PADRAO if p != CF.NEGOCIO]
    assert all(p.exists() for p in no_repo), [str(p) for p in no_repo if not p.exists()]
    assert CF.REPO / "docs" / "exemplos" in CF.RAIZES_PADRAO
    nomes = [n for n, _ in CF.textos(no_repo)]
    for esperado in ("README.md", "docs/entregaveis/pitch-regional-3min.md", "docs/entregaveis/qa-banca.md",
                     "docs/entregaveis/deck/index.html", "docs/fluxo_do_agente.md"):
        assert esperado in nomes
    pacote = CF.REPO / "docs" / "exemplos" / "DEMONSTRACAO_pacote_exibicao.zip"
    if pacote.exists():
        assert any(n.startswith("docs/exemplos/DEMONSTRACAO_pacote_exibicao.zip!") for n in nomes)
    assert not any(n.startswith("../negocio/afirmacoes_proibidas") for n in nomes)


def test_varredura_padrao_roda_e_cada_achado_aponta_uma_linha():
    raizes = [p for p in CF.RAIZES_PADRAO if p.exists()]
    achados = CF.varrer(raizes)
    for a in achados:
        assert a.linha >= 1 and a.arquivo and a.regra.id in {r.id for r in CF.REGRAS}
    assert CF.main(["--so", "P01"]) in (0, 1)
