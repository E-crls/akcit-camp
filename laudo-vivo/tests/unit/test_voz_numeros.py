"""Números falados em pt-BR → algarismos e pedido de confirmação (laudo.speech.numeros)."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from laudo.speech.numeros import eh_confirmacao, formatar_br, normalizar


@pytest.mark.parametrize(
    "fala, esperado",
    [
        ("Contei quarenta e duas cabeças no curral", "Contei 42 cabeças no curral"),
        ("a cerca nova tem uns oitocentos metros", "a cerca nova tem uns 800 metros"),
        ("mil e duzentos metros de cerca", "1200 metros de cerca"),
        ("dois mil e quinhentos reais", "2500 reais"),
        ("cento e vinte e cinco garrotes", "125 garrotes"),
        ("trezentas e vinte novilhas", "320 novilhas"),
        ("vinte e um bezerros", "21 bezerros"),
        ("quarenta duas cabeças", "42 cabeças"),  # o ASR às vezes engole o "e"
        ("um lote de quarenta cabeças", "um lote de 40 cabeças"),  # "um" artigo
        ("uma cabeça machucada e uma cerca caída", "1 cabeça machucada e uma cerca caída"),
        ("cinco e seis cabeças", "5 e 6 cabeças"),  # composição inválida não junta
        ("quinze e três", "15 e 3"),
        ("dois e meio hectares", "2,5 hectares"),
        ("um e meio hectare", "1,5 hectare"),
        ("três vírgula cinco hectares", "3,5 hectares"),
        ("zero vírgula zero cinco hectares", "0,05 hectares"),
        ("2 mil cabeças", "2000 cabeças"),
        ("R$ 112 mil", "R$ 112000"),
        ("R$ dois mil", "R$ 2000"),
        ("um milhão e duzentos mil reais", "1200000 reais"),
        ("cem mil reais", "100000 reais"),
        ("1.200 metros", "1200 metros"),
        ("Fazenda em Três Ranchos com trinta bois", "Fazenda em Três Ranchos com 30 bois"),  # nome próprio
        ("Três bois fugiram", "3 bois fugiram"),  # início de frase não é nome próprio
        ("Pode marcar 40 aí, o gerente já aprovou.", "Pode marcar 40 aí, o gerente já aprovou."),
        ("sem número nenhum aqui", "sem número nenhum aqui"),
        ("", ""),
    ],
)
def test_normaliza_numeros_falados(fala, esperado):
    assert normalizar(fala).texto == esperado


def test_numero_critico_pede_confirmacao():
    r = normalizar("Contei quarenta e duas cabeças e a cerca tem oitocentos metros")
    assert [n.valor for n in r.criticos] == [42, 800]
    assert [n.grandeza for n in r.criticos] == ["quantidade", "comprimento"]
    assert r.precisa_confirmar
    assert r.pedido_confirmacao() == "Entendi 42 cabeças e 800 metros. Confirma?"
    # posição aponta para o trecho original
    n = r.numeros[0]
    assert r.original[n.inicio : n.fim] == "quarenta e duas"


def test_numero_sem_unidade_nao_e_critico():
    """'Pode marcar 40' vai direto para o condutor: quem trata a pressão é a política (POL-07)."""
    r = normalizar("Pode marcar 40 aí, o resto está no pasto de cima.")
    assert r.numeros and not r.precisa_confirmar and r.pedido_confirmacao() is None


def test_rotulo_usa_a_palavra_dita_e_formata_milhar():
    r = normalizar("comprei mil e duzentos garrotes por dois milhões de reais")
    rotulos = [n.rotulo() for n in r.criticos]
    assert rotulos == ["1.200 garrotes", "R$ 2.000.000"]
    assert formatar_br(2.5) == "2,5"


@pytest.mark.parametrize(
    "fala, esperado",
    [
        ("sim", True),
        ("Sim, confirmo.", True),
        ("pode mandar", True),
        ("isso", True),
        ("não", False),
        ("errado", False),
        ("contei 40 cabeças no curral", None),
        ("", None),
    ],
)
def test_resposta_de_confirmacao(fala, esperado):
    assert eh_confirmacao(fala) is esperado


# ---------------------------------------------------------------------------
# Propriedade: número por extenso (gerado aqui) volta ao mesmo valor
# ---------------------------------------------------------------------------

_U = ["", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove"]
_D10 = ["dez", "onze", "doze", "treze", "quatorze", "quinze", "dezesseis", "dezessete", "dezoito", "dezenove"]
_D = ["", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa"]
_C = [
    "",
    "cento",
    "duzentos",
    "trezentos",
    "quatrocentos",
    "quinhentos",
    "seiscentos",
    "setecentos",
    "oitocentos",
    "novecentos",
]


def _ate_999(n: int) -> str:
    if n == 100:
        return "cem"
    c, r = divmod(n, 100)
    partes = [_C[c]] if c else []
    if 10 <= r < 20:
        partes.append(_D10[r - 10])
    else:
        d, u = divmod(r, 10)
        if d:
            partes.append(_D[d])
        if u:
            partes.append(_U[u])
    return " e ".join(partes)


def por_extenso(n: int) -> str:
    if n < 1000:
        return _ate_999(n)
    m, r = divmod(n, 1000)
    base = "mil" if m == 1 else f"{_ate_999(m)} mil"
    if not r:
        return base
    return f"{base} e {_ate_999(r)}" if r < 100 or r % 100 == 0 else f"{base} {_ate_999(r)}"


@settings(max_examples=300, deadline=None)
@given(st.integers(min_value=2, max_value=999_999))
def test_propriedade_extenso_volta_ao_valor(n):
    fala = f"contei {por_extenso(n)} cabeças"
    r = normalizar(fala)
    assert r.texto == f"contei {n} cabeças", fala
    assert r.criticos[0].valor == n
