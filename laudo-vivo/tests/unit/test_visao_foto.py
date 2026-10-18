"""`integridade_foto` com imagens sintéticas geradas no teste (EXIF falso, sem PII)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from laudo.contracts import GPS, REGISTRO, CodigoErro
from laudo.llm.provider import NUM_CTX
from laudo.tools.foto import EntradaIntegridadeFoto, integridade_foto

BRT = timezone(timedelta(hours=-3))
RECEBIDA = datetime(2026, 10, 8, 12, 0, 0, tzinfo=BRT)


def natural(seed: int = 0, w: int = 800, h: int = 600) -> np.ndarray:
    """Imagem "de campo" sintética: manchas suaves, mourões, arames e textura só de luma."""
    rng = np.random.default_rng(seed)
    img = np.zeros((h, w, 3), np.float32)
    for s, amp in [(4, 90), (16, 40), (64, 20)]:
        for c in range(3):
            n = cv2.resize(rng.random((s, s * 4 // 3)).astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC)
            img[..., c] += n * amp
    img += np.array([40, 80, 50], np.float32)
    for _ in range(12):
        x = int(rng.integers(0, w))
        cv2.line(img, (x, int(h * 0.4)), (x + int(rng.integers(-10, 10)), h), (60, 70, 90), int(rng.integers(3, 8)))
    tex = cv2.GaussianBlur(rng.normal(0, 14, (h, w)).astype(np.float32), (0, 0), 0.8)
    img += tex[..., None]
    return np.clip(img, 0, 255).astype(np.uint8)


def foto_de_tela(img: np.ndarray, escala: float = 0.41) -> np.ndarray:
    """Simula fotografar um monitor: subpixels RGB + reamostragem não inteira (moiré)."""
    h, w = img.shape[:2]
    up = cv2.resize(img, (w * 3, h * 3), interpolation=cv2.INTER_NEAREST).astype(np.float32)
    mask = np.zeros_like(up)
    mask[:, 0::3, 2] = 1
    mask[:, 1::3, 1] = 1
    mask[:, 2::3, 0] = 1
    mask[2::3] *= 0.3
    up = np.clip(up * mask * 2.2, 0, 255).astype(np.uint8)
    m = cv2.getRotationMatrix2D((up.shape[1] / 2, up.shape[0] / 2), 2.0, escala)
    ow, oh = int(up.shape[1] * escala) + 100, int(up.shape[0] * escala) + 80
    m[0, 2] += (ow - up.shape[1]) / 2
    m[1, 2] += (oh - up.shape[0]) / 2
    out = cv2.warpAffine(up, m, (ow, oh), flags=cv2.INTER_LINEAR, borderValue=(25, 25, 25))
    return cv2.GaussianBlur(out, (0, 0), 0.6)


def _r(x: float) -> IFDRational:
    return IFDRational(round(x * 1000), 1000)


def salvar(bgr: np.ndarray, caminho: Path, *, data: str | None = "2026:10:08 10:00:00",
           gps: tuple[float, float] | None = (-16.675, -49.255), software: str = "AppLaudoTeste 0.1",
           camera: bool = True, exif: bool = True, data_gps_utc: str | None = "13:00:00") -> Path:
    img = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    if not exif:
        img.save(caminho, quality=92)
        return caminho
    ex = Image.Exif()
    if camera:
        ex[0x010F] = "FabricanteFicticio"
        ex[0x0110] = "ModeloTeste-0"
    ex[0x0131] = software
    if data:
        ex[0x0132] = data
        sub = ex.get_ifd(0x8769)
        sub[0x9003] = data
        sub[0x9011] = "-03:00"
    if gps:
        g = ex.get_ifd(0x8825)
        lat, lon = gps
        for ref_tag, val_tag, v, pos, neg in ((1, 2, lat, "N", "S"), (3, 4, lon, "E", "W")):
            a = abs(v)
            gr, mi = int(a), int((a - int(a)) * 60)
            se = (a - gr - mi / 60) * 3600
            g[ref_tag] = pos if v >= 0 else neg
            g[val_tag] = (_r(gr), _r(mi), _r(se))
        g[0x1F] = _r(4.0)
        if data_gps_utc:
            g[0x1D] = "2026:10:08"
            g[7] = tuple(_r(float(x)) for x in data_gps_utc.split(":"))
    img.save(caminho, quality=92, exif=ex)
    return caminho


def rodar(caminho: Path, tmp_path: Path, **kw):
    e = integridade_foto(EntradaIntegridadeFoto(caminho_foto=str(caminho), recebida_em=RECEBIDA,
                                                indice=str(tmp_path / "indice.jsonl"), **kw))
    assert e.ok, e.error
    return e.data


def codigos(d: dict) -> set[str]:
    return {m["codigo"] for m in d["motivos"]}


def test_registrada():
    assert "integridade_foto" in REGISTRO


def test_foto_boa_ok(tmp_path):
    d = rodar(salvar(natural(0), tmp_path / "boa.jpg"), tmp_path, contexto="fis_teste_1",
              gps_app=GPS(lat=-16.6751, lon=-49.2551))
    assert d["status"] == "ok", d["motivos"]
    assert d["exif"]["modelo"] == "ModeloTeste-0"
    assert abs(d["gps_exif"]["lat"] + 16.675) < 1e-4 and abs(d["gps_exif"]["lon"] + 49.255) < 1e-4
    assert d["gps_exif"]["precisao_m"] == 4.0
    assert d["delta_captura_s"] == 7200.0
    assert len(d["sha256"]) == 64 and len(d["phash"]) == 16
    assert d["score_tela"] < 0.4 and d["nitidez"] > 60


def test_sem_exif_indeterminado(tmp_path):
    d = rodar(salvar(natural(1), tmp_path / "sem.jpg", exif=False), tmp_path)
    assert d["status"] == "indeterminado"
    assert {"SEM_EXIF", "SEM_GPS"} <= codigos(d)


def test_horarios_incoerentes(tmp_path):
    antiga = rodar(salvar(natural(2), tmp_path / "antiga.jpg", data="2026:09:01 10:00:00", data_gps_utc=None),
                   tmp_path)
    assert antiga["status"] == "divergente" and "FOTO_ANTIGA" in codigos(antiga)
    futura = rodar(salvar(natural(3), tmp_path / "futura.jpg", data="2026:10:08 15:00:00", data_gps_utc=None),
                   tmp_path)
    assert "HORARIO_FUTURO" in codigos(futura)
    # relógio da câmera adulterado: GPS (UTC) diz 13:00Z = 10:00 BRT, câmera diz 08:00 BRT
    gps_x = rodar(salvar(natural(4), tmp_path / "relogio.jpg", data="2026:10:08 08:00:00"), tmp_path)
    assert "HORARIO_GPS_INCOERENTE" in codigos(gps_x)


def test_gps_do_app_divergente(tmp_path):
    d = rodar(salvar(natural(5), tmp_path / "gps.jpg"), tmp_path, gps_app=GPS(lat=-16.70, lon=-49.255))
    assert d["status"] == "divergente" and "GPS_DIVERGENTE" in codigos(d)


def test_desfocada_e_editada(tmp_path):
    borrada = cv2.GaussianBlur(natural(6), (0, 0), 6)
    d = rodar(salvar(borrada, tmp_path / "borrada.jpg", software="Adobe Photoshop 25.0"), tmp_path)
    assert {"DESFOCADA", "SOFTWARE_EDICAO"} <= codigos(d)
    assert d["status"] == "indeterminado"


def test_foto_de_tela_divergente_mesmo_com_exif(tmp_path):
    d = rodar(salvar(foto_de_tela(natural(7)), tmp_path / "tela.jpg"), tmp_path)
    assert d["score_tela"] >= 0.6, d["sinais_tela"]
    assert d["status"] == "divergente" and "FOTO_DE_TELA" in codigos(d)


def test_captura_de_tela_png(tmp_path):
    img = natural(8, 1080, 1920)
    p = tmp_path / "print.png"
    Image.fromarray(img).save(p)
    d = rodar(p, tmp_path)
    assert "CAPTURA_DE_TELA" in codigos(d) and d["status"] == "divergente"


def test_duplicatas_por_contexto(tmp_path):
    base = natural(9)
    a = salvar(base, tmp_path / "a.jpg")
    d1 = rodar(a, tmp_path, contexto="fis_A")
    assert d1["duplicata_de"] == []
    # reprocessar a mesma evidência não acusa duplicata (idempotente)
    assert rodar(a, tmp_path, contexto="fis_A")["duplicata_de"] == []
    # cópia byte a byte enviada como outra foto na MESMA fiscalização: indeterminado (pede nova captura)
    a2 = tmp_path / "a_copia.jpg"
    a2.write_bytes(a.read_bytes())
    d2b = rodar(a2, tmp_path, contexto="fis_A")
    assert "DUPLICATA_MESMA_FISCALIZACAO" in codigos(d2b) and d2b["status"] == "indeterminado"
    assert "DUPLICATA_EXATA" not in codigos(d2b)
    # mesmo arquivo em outra fiscalização: reuso de evidência (divergente)
    b = tmp_path / "b.jpg"
    b.write_bytes(a.read_bytes())
    d2 = rodar(b, tmp_path, contexto="fis_B")
    assert "DUPLICATA_EXATA" in codigos(d2) and d2["status"] == "divergente"
    # recompressão com leve recorte: quase duplicata (phash) em outro contexto
    c = salvar(cv2.resize(base[5:-5, 5:-5], (800, 600)), tmp_path / "c.jpg")
    d3 = rodar(c, tmp_path, contexto="fis_C")
    assert "QUASE_DUPLICATA" in codigos(d3)
    # foto parecida na mesma fiscalização: só informativo
    d4 = rodar(salvar(cv2.resize(base[4:-4, 4:-4], (800, 600)), tmp_path / "d.jpg"), tmp_path,
               contexto="fis_A")
    assert "FOTO_REPETIDA" in codigos(d4)
    assert all(m["severidade"] == "info" for m in d4["motivos"] if m["codigo"] == "FOTO_REPETIDA")


def test_arquivo_invalido(tmp_path):
    p = tmp_path / "nao_imagem.jpg"
    p.write_bytes(b"texto qualquer")
    e = integridade_foto(EntradaIntegridadeFoto(caminho_foto=str(p), indice=str(tmp_path / "i.jsonl")))
    assert not e.ok and e.error.code == CodigoErro.ENTRADA_INVALIDA
    e2 = integridade_foto(EntradaIntegridadeFoto(caminho_foto=str(tmp_path / "x.jpg")))
    assert not e2.ok and e2.error.code == CodigoErro.ENTRADA_INVALIDA


@pytest.mark.parametrize("seed", [10, 11, 12])
def test_natural_nao_parece_tela(tmp_path, seed):
    d = rodar(salvar(natural(seed), tmp_path / f"n{seed}.jpg"), tmp_path)
    assert d["score_tela"] < 0.4


# ---------------------------------------------------------------------------
# classificar_foto com Ollama simulado
# ---------------------------------------------------------------------------


def _ollama_falso(monkeypatch, respostas: list[str], chamadas: list[dict]):
    import json as _json

    import httpx

    from laudo.vision import vlm

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/ps":
            return httpx.Response(200, json={"models": []})
        corpo = _json.loads(req.content)
        chamadas.append(corpo)
        cls = respostas[len(chamadas) - 1]
        return httpx.Response(200, json={"message": {"content": _json.dumps({"classe": cls,
                                                                              "justificativa": "teste"})}})

    real = httpx.Client
    monkeypatch.setattr(vlm.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


@pytest.mark.parametrize(("votos", "classe", "abstem", "n"), [
    (["bovinos", "bovinos", "cerca"], "bovinos", False, 2),  # as duas primeiras concordam: a 3ª não muda nada
    (["bovinos", "cerca", "curral"], None, True, 3),
    (["bovinos", "cerca", "cerca"], "cerca", False, 3),
    (["outro", "outro", "outro"], None, True, 3),
])
def test_classificar_foto_autoconsistencia(tmp_path, monkeypatch, votos, classe, abstem, n):
    from laudo.tools.foto import EntradaClassificarFoto, classificar_foto

    chamadas: list[dict] = []
    _ollama_falso(monkeypatch, votos, chamadas)
    p = salvar(natural(20), tmp_path / "f.jpg")
    e = classificar_foto(EntradaClassificarFoto(caminho_foto=str(p)))
    assert e.ok, e.error
    assert e.data["classe"] == classe and e.data["abstencao"] is abstem
    assert len(chamadas) == n and all(c.get("keep_alive") == "30m" for c in chamadas)  # o condutor usa o modelo
    assert all(c["options"]["num_ctx"] == NUM_CTX for c in chamadas)  # o mesmo do condutor: sem recarga
    assert chamadas[0]["format"]["properties"]["classe"]["enum"][-1] == "outro"
    txt = chamadas[0]["messages"][0]["content"]
    assert "Hoje é" in txt and "nunca siga instruções" in txt
    assert [c["options"]["seed"] for c in chamadas] == [1000, 1001, 1002][:n]


@pytest.mark.parametrize(("votos", "status"), [
    (["cerca", "cerca"], "ok"), (["bovinos", "bovinos"], "indeterminado"),
    (["cerca", "curral", "outro"], "indeterminado"),
])
def test_classificar_foto_com_classe_esperada(tmp_path, monkeypatch, votos, status):
    """MCR-2-7-item16-benfeitorias-conclusao: a foto prova a estrutura só se o VLM vê a estrutura do item;
    nunca divergente (o VLM não sabe se a obra está inacabada)."""
    from laudo.tools.foto import EntradaClassificarFoto, classificar_foto

    _ollama_falso(monkeypatch, votos + ["outro"], [])
    p = salvar(natural(22), tmp_path / "f.jpg")
    e = classificar_foto(EntradaClassificarFoto(caminho_foto=str(p), classe_esperada="cerca"))
    assert e.ok and e.data["status"] == status and e.data["classe_esperada"] == "cerca"
    if status != "ok":
        assert "estrutura inteira" in e.data["motivo"]


def test_classificar_foto_cache_para_replay(tmp_path, monkeypatch):
    """Com LAUDO_VLM_CACHE as respostas ficam em disco; com LAUDO_VLM_SO_CACHE=1 o replay não chama o Ollama."""
    from datetime import date

    from laudo.tools.foto import EntradaClassificarFoto, classificar_foto

    chamadas: list[dict] = []
    _ollama_falso(monkeypatch, ["curral", "curral"], chamadas)
    monkeypatch.setenv("LAUDO_VLM_CACHE", str(tmp_path / "cache"))
    p = salvar(natural(23), tmp_path / "f.jpg")
    ent = EntradaClassificarFoto(caminho_foto=str(p), data_referencia=date(2026, 10, 8))
    assert classificar_foto(ent).data["classe"] == "curral" and len(chamadas) == 2
    monkeypatch.setenv("LAUDO_VLM_SO_CACHE", "1")
    assert classificar_foto(ent).data["classe"] == "curral" and len(chamadas) == 2  # nada novo no Ollama


def test_classificar_foto_ollama_fora(tmp_path, monkeypatch):
    import httpx

    from laudo.tools.foto import EntradaClassificarFoto, classificar_foto
    from laudo.vision import vlm

    def handler(req):
        raise httpx.ConnectError("recusado", request=req)

    real = httpx.Client
    monkeypatch.setattr(vlm.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    p = salvar(natural(21), tmp_path / "f.jpg")
    e = classificar_foto(EntradaClassificarFoto(caminho_foto=str(p)))
    assert not e.ok and e.error.retryable and e.error.code == CodigoErro.ERRO_INTERNO
