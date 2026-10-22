"""Foto sem GPS do app ou sem GPS no EXIF (P2-11 e P2-12, sondas de 22/10/2026 com caso novo).

- P2-11: foto escolhida no notebook, sem GPS do navegador, mas com GPS no EXIF: o geofence usa o do EXIF (antes:
  ERRO ENTRADA_INVALIDA "lat: Field required"). Sem GPS nenhum, a mensagem é um pedido legível ao fiscal.
- P2-12: foto de celular sem GPS no EXIF (o navegador costuma tirar) com o GPS do app bom (≤ 30 m): SEM_GPS vira
  informação e a integridade não fica pendente por isso.
"""

from __future__ import annotations

import pytest
from test_visao_foto import RECEBIDA, codigos, natural, rodar, salvar

from laudo.agent import estado as est
from laudo.agent.condutor import MSG_FOTO_SEM_GPS, Condutor, Evento, NovaEvidencia
from laudo.agent.executor import gps_exif_da_foto
from laudo.agent.ferramentas_falsas import GPS_DENTRO, operacao_exemplo
from laudo.audit import otel
from laudo.contracts import GPS, REGISTRO
from laudo.tools import carregar_todas
from laudo.tools import laudo as ferr_laudo

DENTRO = (GPS_DENTRO["lat"], GPS_DENTRO["lon"])


def _sem_gps(d: dict) -> dict:
    return next(m for m in d["motivos"] if m["codigo"] == "SEM_GPS")


def test_sem_gps_no_exif_com_gps_do_app_bom_vira_informacao(tmp_path):
    foto = salvar(natural(41), tmp_path / "f.jpg", gps=None)
    d = rodar(foto, tmp_path, gps_app=GPS(lat=DENTRO[0], lon=DENTRO[1], precisao_m=5.0, fonte="app"))
    assert d["status"] == "ok" and _sem_gps(d)["severidade"] == "info"
    assert "GPS do aparelho" in _sem_gps(d)["msg"] and "±5 m" in _sem_gps(d)["msg"]


@pytest.mark.parametrize("gps_app", [
    None,  # sem GPS do app: continua pendente
    GPS(lat=DENTRO[0], lon=DENTRO[1], precisao_m=45.0, fonte="app"),  # precisão pior que 30 m
    GPS(lat=DENTRO[0], lon=DENTRO[1], precisao_m=None, fonte="app"),  # precisão desconhecida
    GPS(lat=DENTRO[0], lon=DENTRO[1], precisao_m=5.0, fonte="app", mock=True),  # localização simulada
])
def test_sem_gps_no_exif_sem_gps_do_app_bom_continua_indeterminado(tmp_path, gps_app):
    foto = salvar(natural(42), tmp_path / "f.jpg", gps=None)
    d = rodar(foto, tmp_path, gps_app=gps_app)
    assert d["status"] == "indeterminado" and _sem_gps(d)["severidade"] == "indeterminado"


def test_foto_com_gps_no_exif_nao_muda(tmp_path):
    foto = salvar(natural(43), tmp_path / "f.jpg", gps=DENTRO)
    d = rodar(foto, tmp_path, gps_app=GPS(lat=DENTRO[0], lon=DENTRO[1], precisao_m=5.0, fonte="app"))
    assert d["status"] == "ok" and "SEM_GPS" not in codigos(d)
    d = rodar(salvar(natural(44), tmp_path / "g.jpg", gps=None), tmp_path, exigir_gps=False,
              gps_app=GPS(lat=DENTRO[0], lon=DENTRO[1], precisao_m=5.0, fonte="app"))
    assert "SEM_GPS" not in codigos(d)  # exigir_gps=False: como antes, nenhum motivo


@pytest.fixture()
def cond(tmp_path):
    otel.configurar(tmp_path / "traces")
    est.ids_deterministicos("foto-sem-gps")
    carregar_todas()
    reg = {n: REGISTRO[n] for n in ("integridade_foto", "geofence")}
    c = Condutor(None, repo=est.RepositorioFiscalizacoes(tmp_path / "fis"), registro=reg)
    yield c
    est.ids_deterministicos(None)
    ferr_laudo.configurar(None, None)


def _turno_foto(cond, caminho, gps=None):
    fis = cond.abrir(operacao_exemplo(), estado_fsm="COLETA", metodo="presencial")
    r = cond.turno(fis.id, Evento(evidencia=NovaEvidencia(tipo="foto", caminho=str(caminho), item_id="cerca1",
                                                          gps=gps, recebida_em=RECEBIDA)))
    final = cond.repo.carregar(fis.id)
    geo = [c for c in final.checagens if c.ferramenta == "geofence"]
    assert len(geo) == 1
    return r, final, geo[0]


def test_geofence_usa_o_gps_do_exif_quando_falta_o_do_app(cond, tmp_path):
    foto = salvar(natural(45), tmp_path / "cerca.jpg", gps=DENTRO)  # EXIF com GPS e precisão de 4 m
    r, fis, geo = _turno_foto(cond, foto, gps=None)
    assert geo.status == "ok" and geo.resultado["posicao"] == "dentro"
    assert geo.resultado["fonte_gps"] == "exif" and "GPS do EXIF" in geo.resultado["motivo"]
    assert not any("Field required" in a.resultado for a in r.acoes)
    g = gps_exif_da_foto(fis, next(e for e in fis.evidencias if e.tipo == "foto"))
    assert g is not None and g.fonte == "exif" and g.precisao_m == pytest.approx(4.0)


def test_foto_sem_gps_nenhum_da_pedido_legivel(cond, tmp_path):
    foto = salvar(natural(46), tmp_path / "cerca.jpg", gps=None)
    r, _, geo = _turno_foto(cond, foto, gps=None)
    assert geo.status == "erro" and geo.resultado["erro"]["msg"] == MSG_FOTO_SEM_GPS
    textos = " ".join(a.resultado for a in r.acoes) + " " + r.fala
    assert "Field required" not in textos and "lat:" not in textos


def test_foto_de_celular_sem_gps_no_exif_com_gps_do_app_fica_verificada(cond, tmp_path):
    """Caso da sonda sonda_sem_gps_exif: GPS do navegador a ±5 m dentro da gleba, EXIF sem GPS."""
    foto = salvar(natural(47), tmp_path / "cerca.jpg", gps=None)
    _, fis, geo = _turno_foto(cond, foto, gps=GPS(**GPS_DENTRO))
    integ = next(c for c in fis.checagens if c.ferramenta == "integridade_foto")
    assert integ.status == "ok" and geo.status == "ok" and "fonte_gps" not in geo.resultado
