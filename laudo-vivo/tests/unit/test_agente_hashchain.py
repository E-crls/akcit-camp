"""Cadeia de hash das evidências (append-only, POL-04)."""

import pytest

from laudo.audit import hashchain
from laudo.contracts import Evidencia


def _ev(i: int) -> Evidencia:
    return Evidencia(id=f"ev_{i:04d}", tipo="foto", sha256=f"{i:064x}", meta={"n": i})


def test_genesis_encadeamento_e_raiz():
    evs: list[Evidencia] = []
    hashchain.anexar(evs, _ev(1))
    assert evs[0].hash_anterior == hashchain.GENESIS
    hashchain.anexar(evs, _ev(2))
    assert evs[1].hash_anterior == hashchain.hash_elo(evs[0])
    r = hashchain.verificar_cadeia(evs)
    assert r.integra and r.n == 2 and r.raiz == hashchain.raiz(evs) == hashchain.hash_elo(evs[1])
    assert hashchain.raiz([]) == hashchain.GENESIS


def test_adulterar_meta_quebra_a_cadeia_no_elo_seguinte():
    evs: list[Evidencia] = []
    for i in range(4):
        hashchain.anexar(evs, _ev(i))
    evs[1].meta["n"] = 999  # adulteração
    r = hashchain.verificar_cadeia(evs)
    assert not r.integra and r.quebra_em == 2 and r.evidencia_id == "ev_0002"


def test_adulterar_ultima_muda_a_raiz():
    evs: list[Evidencia] = []
    for i in range(3):
        hashchain.anexar(evs, _ev(i))
    antes = hashchain.raiz(evs)
    evs[-1].sha256 = "f" * 64
    assert hashchain.raiz(evs) != antes  # a raiz assinada no laudo não confere mais


def test_caminho_fora_do_hash_e_id_duplicado():
    evs: list[Evidencia] = []
    e = hashchain.anexar(evs, _ev(1))
    h = hashchain.hash_elo(e)
    e.caminho = "/outro/lugar.jpg"
    assert hashchain.hash_elo(e) == h
    with pytest.raises(ValueError):
        hashchain.anexar(evs, _ev(1))


def test_hash_raiz_laudo_deterministico():
    a = hashchain.hash_raiz_laudo("ab" * 32, {"x": 1, "y": [1, 2]})
    b = hashchain.hash_raiz_laudo("ab" * 32, {"y": [1, 2], "x": 1})
    assert a == b and len(a) == 64
    assert hashchain.hash_raiz_laudo("ab" * 32, {"x": 2, "y": [1, 2]}) != a
