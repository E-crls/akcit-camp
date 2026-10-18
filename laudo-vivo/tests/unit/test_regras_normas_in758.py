"""IN BCB nº 758/2026 em docs/normas: texto literal com URL e data, lido por `laudo.rulebooks.normas` para o
pacote de exibição citar a reversão de desclassificação literalmente (antes: `citacao_conferida=false`).

A seção "Texto literal" foi conferida linha a linha contra a API de normativos do BCB em 16/10/2026; o sha256
dela fica em `normas.FONTES` e amarra a conferência: texto editado depois deixa de sair como "conferido"."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from laudo.rulebooks import normas

REPO = Path(__file__).resolve().parents[2]
ARQ = REPO / "docs" / "normas" / "in_bcb_758.md"


def test_arquivo_com_fonte_oficial_url_e_data_de_acesso():
    texto = ARQ.read_text(encoding="utf-8")
    assert normas.FONTES[normas.IN_BCB_758]["url"] in texto
    assert "16/10/2026" in texto and "DOU 10/07/2026" in texto
    assert "Não revogada, não cancelada" in texto


# (seção, alínea, trecho que tem de estar no texto literal) — conferidos contra a API de normativos do BCB
TRECHOS = [
    ("Campo 60-B, Nota", None, "A reversão da desclassificação poderá ser realizada pela instituição financeira"),
    ("Campo 60-B, Nota", "b", "não poderão ser revertidas, salvo autorização expressa do BC"),
    ("Campo 60-B, Nota", "c", "registrar, para cada operação, a documentação comprobatória das justificativas"),
    ("Campo 60-B, Nota", "e", "deverá ser mantida à disposição do BC pelo prazo previsto nas normas legais"),
    ("Campo 52, Nota", "b", "deve adotar as providências previstas no MCR 2-8 e, quando couber, no MCR 2-7-21"),
    ("Art. 4º", None, "entra em vigor na data de sua publicação"),
]


def test_trechos_literais_por_secao_e_alinea():
    for secao, alinea, esperado in TRECHOS:
        t = normas.trecho(normas.IN_BCB_758, secao, alinea)
        assert t is not None and esperado in t, (secao, alinea)
        if alinea:
            assert t.startswith(f"{alinea}) ")


def test_citacao_da_reversao_para_o_pacote():
    c = normas.citacao_reversao()
    assert c is not None and c["citacao_conferida"] is True
    assert c["url"].startswith("https://www.bcb.gov.br/") and c["acesso"] == "2026-10-16"
    assert "Campo 60-B" in c["localizador"] and c["citacao_literal"].count(" […] ") == 3
    assert "para cada operação" in c["citacao_literal"] and set(c["alineas"]) == set("abcde")
    assert all(c["alineas"].values())


def test_sem_o_texto_nao_inventa(monkeypatch, tmp_path):
    monkeypatch.setattr(normas, "REPO", tmp_path)
    normas.trechos.cache_clear()
    try:
        assert normas.trecho(normas.IN_BCB_758, "Campo 60-B, Nota", "c") is None
        assert normas.citacao_reversao() is None
        assert normas.trecho("norma-desconhecida", "x") is None
    finally:
        normas.trechos.cache_clear()


# --------------------------------------------- amarração com a conferência (revisão da onda 3)


def test_sha256_da_secao_literal_e_o_conferido():
    """Mudou o texto da seção "Texto literal"? Reconfira contra a fonte oficial (URL em FONTES) e só então
    atualize `sha256_texto_literal` e a data de acesso."""
    esperado = normas.FONTES[normas.IN_BCB_758]["sha256_texto_literal"]
    assert normas.sha256_secao_literal(normas.IN_BCB_758) == esperado
    assert normas.conferida(normas.IN_BCB_758)


@pytest.fixture()
def copia(monkeypatch, tmp_path):
    """Cópia de docs/normas num repositório temporário (para editar sem tocar no arquivo de verdade)."""
    destino = tmp_path / "docs" / "normas"
    destino.mkdir(parents=True)
    shutil.copy(ARQ, destino / ARQ.name)
    monkeypatch.setattr(normas, "REPO", tmp_path)
    normas.trechos.cache_clear()
    yield destino / ARQ.name
    normas.trechos.cache_clear()


def _editar(arq: Path, antes: str, depois: str) -> None:
    texto = arq.read_text(encoding="utf-8")
    assert antes in texto
    arq.write_text(texto.replace(antes, depois), encoding="utf-8")
    normas.trechos.cache_clear()


def test_texto_literal_editado_deixa_de_ser_citado_como_conferido(copia):
    assert normas.citacao_reversao() is not None  # a cópia intacta confere
    _editar(copia, "salvo autorização expressa do BC", "salvo autorização do BC")
    assert not normas.conferida(normas.IN_BCB_758) and normas.citacao_reversao() is None


def test_editar_fora_da_transcricao_nao_muda_a_conferencia(copia):
    _editar(copia, "## Leitura para o produto", "## Leitura (nota nossa)")
    assert normas.conferida(normas.IN_BCB_758) and normas.citacao_reversao() is not None


def test_titulos_fora_da_transcricao_nao_se_dizem_literais():
    """O título "Fora do recorte (resumo, não literal)" fazia o leitor do pacote
    (`tools/pacote.py::in758_literal`, que procura "literal" nos títulos) citar o resumo como "texto literal
    conferido". Só a seção "## Texto literal" pode ter a palavra no título."""
    titulos = [ln.strip() for ln in ARQ.read_text(encoding="utf-8").splitlines() if ln.lstrip().startswith("#")]
    assert [t for t in titulos if "literal" in t.lower()] == ["## Texto literal (IN BCB nº 758/2026)"]


def test_pacote_nunca_apresenta_resumo_como_texto_literal():
    """Integração com o pacote de exibição (J1): se ele diz "conferida", a citação tem de ser a transcrição da
    nota do Campo 60-B (nunca o resumo "Fora do recorte") e a data tem de ser a do acesso, não a da IN."""
    from laudo.tools import pacote

    r = pacote.reversao_in758({}, {}, [])
    if not r["citacao_conferida"]:
        assert not r["citacao_literal"]
        return
    lit = r["citacao_literal"]
    assert "A reversão da desclassificação poderá ser realizada" in lit and "nova redação do item 18" not in lit
    fonte = {k: v for k, v in r.items() if k != "citacao_literal" and "acesso" in str(k)}
    fonte |= {k: v for k, v in (r.get("fonte_literal") or {}).items() if "acesso" in str(k)}
    datas = re.findall(r"\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2}", " ".join(map(str, fonte.values())))
    assert datas and set(datas) <= {"16/10/2026", "2026-10-16"}, fonte
