"""Golden DEV (36 casos) com o índice de documentos ligado e NF-e com o grupo ZF de GO: zero over-blocking.

Lento (cerca de 40 s): roda com LAUDO_LENTO=1. Reproduz o número do relatório da frente B com
`eval/golden/gerador/conferir_indice_zf.py` (dois modos do condutor sem LLM: base e índice + grupo ZF).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def relatorio(tmp_path_factory):
    if not os.environ.get("LAUDO_LENTO"):
        pytest.skip("teste lento: rode com LAUDO_LENTO=1")
    sys.path.insert(0, str(REPO / "eval" / "golden" / "gerador"))
    import conferir_indice_zf as C

    from laudo.agent import estado as est
    from laudo.audit import otel
    from laudo.tools import foto

    H = C.H
    antes_ids, antes_otel = dict(est._IDS), dict(otel._estado)
    antes_ev, antes_foto, ja_instalado = est.Evidencia, foto.INDICE_PADRAO, dict(H._INSTALADO)
    saida = tmp_path_factory.mktemp("indice_zf")
    try:
        codigo = C.main(["--saida", str(saida)])
    finally:  # o harness troca estado global (ids, traces, relógio das evidências, índice de fotos): restaura
        est._IDS.clear()
        est._IDS.update(antes_ids)
        otel._estado.clear()
        otel._estado.update(antes_otel)
        if not ja_instalado:
            est.Evidencia = antes_ev
            H._INSTALADO.clear()
        foto.INDICE_PADRAO = antes_foto
        H.RELOGIO.agora = None
    return codigo, json.loads((saida / "relatorio.json").read_text(encoding="utf-8"))


def test_indice_e_grupo_zf_nao_mudam_nenhum_status_do_dev(relatorio):
    codigo, r = relatorio
    assert codigo == 0 and r["status_do_laudo_mudou"] == []
    assert len(r["casos"]) == 36
    for modo in ("base", "indice_zf"):
        assert r[modo]["validos"] == 14
        assert r[modo]["over_blocking"] == [] and r[modo]["rascunho_bloqueado"] == [], modo
    assert r["indice_zf"]["divergencias_campo_rotulo"] == r["base"]["divergencias_campo_rotulo"]


def test_indice_compartilhado_sem_falso_reuso_e_grupo_zf_ok(relatorio):
    _, r = relatorio
    z = r["indice_zf"]
    assert z["reusos_acusados"] == [] and z["selados_no_indice"] > 36
    assert z["nfe_guia"] == 36 and z["nfe_guia_nao_ok"] == []
