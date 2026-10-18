"""Rulebooks: esquema, citações literais conferidas contra docs/normas e a ferramenta explicar_regra."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from laudo.contracts import REGISTRO, CodigoErro
from laudo.rulebooks import Regra, avaliar_condicao, carregar, todos
from laudo.tools import regras as R

RAIZ = Path(__file__).resolve().parents[2]


def _normalizar(txt: str) -> str:
    for a, b in (("“", '"'), ("”", '"'), ("‘", "'"), ("’", "'")):
        txt = txt.replace(a, b)
    return re.sub(r"\s+", " ", txt).strip()


def _todas_regras():
    return [(rb, r) for rb in todos() for r in rb.regras]


def test_rulebooks_carregam_com_versao_e_vigencia():
    rb27, rb29 = carregar("mcr-2-7"), carregar("mcr-2-9")
    assert re.fullmatch(r"\d+\.\d+\.\d+", rb27.versao)
    assert rb27.vigencia_inicio == date(2026, 3, 1)  # Res. CMN 5.267, art. 2º
    assert rb29.vigencia_inicio == date(2026, 7, 1)  # Res. CMN 5.314 (item 16) — consolidação mais recente
    assert len(rb27.sha256) == 64 and rb27.fonte_versao == f"rulebook-mcr-2-7@{rb27.versao}"
    for rb in (rb27, rb29):
        assert all(f.url.startswith("https://") for f in rb.fontes)
        assert all(f.acesso == date(2026, 10, 8) for f in rb.fontes)


@pytest.mark.parametrize("rb,regra", _todas_regras(), ids=lambda x: getattr(x, "id", ""))
def test_citacao_literal_existe_no_texto_normativo(rb, regra):
    """Toda citação de norma precisa aparecer, literalmente, no texto salvo em docs/normas."""
    if regra.origem != "norma":
        return
    texto = _normalizar((RAIZ / rb.texto_normativo).read_text(encoding="utf-8"))
    for cit in [regra.citacao, *regra.citacoes_adicionais]:
        assert _normalizar(cit) in texto, f"{regra.id}: citação não encontrada em {rb.texto_normativo}: {cit!r}"


@pytest.mark.parametrize("rb,regra", _todas_regras(), ids=lambda x: getattr(x, "id", ""))
def test_id_da_regra_bate_com_o_item_citado(rb, regra):
    if regra.origem == "parametro_operacional":
        assert regra.id.startswith("OP-") and regra.justificativa and regra.base_normativa
        return
    m = re.match(r"MCR-(\d+)-(\d+)-item(\d+)([A-Z]?)([a-z]?)-", regra.id)  # 17A = item 17-A; 18d = alínea d
    assert m, regra.id
    esperado = f"MCR {m[1]}-{m[2]}-{m[3]}" + (f"-{m[4]}" if m[4] else "") + (f"-{m[5]}" if m[5] else "")
    assert re.match(re.escape(esperado) + r"(\D|$)", regra.item), (regra.id, regra.item)


def test_avaliadores_e_referencias_existem():
    for rb in todos():
        for r in rb.regras:
            if r.avaliador:
                assert r.avaliador in R.AVALIADORES or r.avaliador in R.AVALIADORES_INTERNOS, r.id
            assert set(r.usado_por) <= {"planejar_metodo", "avaliar_regras"}, r.id
        for fluxo in rb.fluxos.values():
            for c in fluxo.campos:
                assert rb.regra(c.regra).avaliador, f"{c.regra} está num fluxo mas não é executável"
        for c in rb.campos_laudo:
            assert rb.regra(c.regra).avaliador


def test_parametros_operacionais_separados_da_norma():
    rb = carregar("mcr-2-7")
    assert rb.param("PAR-contagem-tolerancia-pct") == 5
    assert rb.param("PAR-geofence-perto-m") == 100
    assert all(p.origem == "parametro_operacional" and len(p.justificativa) >= 20 for p in rb.parametros)
    origens = {r.origem for r in rb.regras}
    assert origens == {"norma", "parametro_operacional"}


@pytest.mark.parametrize(
    "dados,erro",
    [
        ({"id": "MCR-2-7-item16-x", "item": "MCR 2-7-16", "tipo": "prazo", "origem": "norma", "titulo": "t"},
         "citacao"),
        ({"id": "OP-x", "item": "operacional", "tipo": "prazo", "origem": "parametro_operacional",
          "titulo": "t"}, "justificativa"),
        ({"id": "MCR-2-7-item16-x", "item": "operacional", "tipo": "prazo", "origem": "parametro_operacional",
          "titulo": "t", "justificativa": "x" * 30}, "OP-"),
        ({"id": "regra solta", "item": "x", "tipo": "prazo", "origem": "norma", "titulo": "t", "citacao": "c"},
         "inválido"),
    ],
    ids=["norma-sem-citacao", "operacional-sem-justificativa", "operacional-com-prefixo-MCR", "id-invalido"],
)
def test_esquema_recusa_regra_malformada(dados, erro):
    with pytest.raises(ValidationError, match=erro):
        Regra.model_validate(dados)


@pytest.mark.parametrize(
    "cond,ctx,esperado",
    [
        ({"campo": "a", "op": "gt", "valor": 300}, {"a": 300}, False),
        ({"campo": "a", "op": "gt", "valor": 300}, {"a": 300.01}, True),
        ({"campo": "a", "op": "gt", "valor": 300}, {}, None),
        ({"todas": [{"campo": "a", "op": "eq", "valor": 1}, {"campo": "b", "op": "eq", "valor": 1}]}, {"a": 2}, False),
        ({"todas": [{"campo": "a", "op": "eq", "valor": 1}, {"campo": "b", "op": "eq", "valor": 1}]}, {"a": 1}, None),
        ({"alguma": [{"campo": "a", "op": "eq", "valor": 1}, {"campo": "b", "op": "eq", "valor": 1}]}, {"a": 1}, True),
        ({"nao": {"campo": "a", "op": "in", "valor": [1, 2]}}, {"a": 3}, True),
        ({"campo": "a", "op": "existe"}, {"a": None}, False),
    ],
    ids=["300-nao-e-superior", "300.01", "dado-ausente-indeterminado", "todas-falso-domina",
         "todas-indeterminado", "alguma-verdadeiro-domina", "nao", "existe"],
)
def test_condicao_tres_valores(cond, ctx, esperado):
    assert avaliar_condicao(cond, ctx) is esperado


def test_ferramentas_registradas():
    for nome in ("planejar_metodo", "avaliar_regras", "explicar_regra"):
        assert nome in REGISTRO and REGISTRO[nome].deterministica


def test_explicar_regra_devolve_citacao_e_fonte():
    env = REGISTRO["explicar_regra"].funcao(R.ExplicarRegraEntrada(regra_id="MCR-2-7-item16-maquinas-60d"))
    assert env.ok and env.fonte_versao.startswith("rulebook-mcr-2-7@")
    regra = env.data["regra"]
    assert regra["citacao"] == ("as ações de monitoramento e fiscalização devem ocorrer até sessenta dias da "
                                "liberação do crédito")
    assert regra["item"] == "MCR 2-7-16-b-II" and regra["origem"] == "norma"
    assert any("manuais.bcb.gov.br" in f["url"] for f in env.data["rulebook"]["fontes"])


def test_explicar_parametro_operacional_traz_justificativa():
    env = REGISTRO["explicar_regra"].funcao({"regra_id": "PAR-contagem-tolerancia-pct"})
    assert env.ok and env.data["tipo"] == "parametro"
    assert env.data["parametro"]["origem"] == "parametro_operacional"
    assert "OP-bovinos-contagem-tolerancia" in env.data["usado_por_regras"]


def test_explicar_regra_desconhecida_e_entrada_invalida():
    env = REGISTRO["explicar_regra"].funcao({"regra_id": "MCR-2-7-item99"})
    assert not env.ok and env.error.code == CodigoErro.ENTRADA_INVALIDA
    assert env.data["sugestoes"]
