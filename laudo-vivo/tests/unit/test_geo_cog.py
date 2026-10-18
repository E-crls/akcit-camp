"""Leitura janelada de COG por HTTP Range com rasterio, servida por um transporte falso (sem rede)."""

from __future__ import annotations

import re

import httpx
import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from laudo.geo.cog import ArquivoHTTP, Medidor, ler_janela

URL = "https://cog.invalid/22/K/DF/2026/9/S2X/B04.tif"


def cog_bytes(tam: int = 1024, bloco: int = 256) -> tuple[bytes, np.ndarray]:
    rng = np.random.default_rng(42)
    arr = rng.integers(1000, 5000, size=(tam, tam), dtype=np.uint16)
    perfil = {"driver": "GTiff", "width": tam, "height": tam, "count": 1, "dtype": "uint16", "nodata": 0,
              "crs": "EPSG:32722", "transform": from_origin(399960, 8100040, 10, 10), "tiled": True,
              "blockxsize": bloco, "blockysize": bloco, "compress": "deflate"}
    with MemoryFile() as mf:
        with mf.open(**perfil) as ds:
            ds.write(arr, 1)
        return mf.read(), arr


def transporte(dado: bytes, log: list[str]):
    def responder(req: httpx.Request) -> httpx.Response:
        log.append(str(req.url))
        if str(req.url) != URL:
            return httpx.Response(404)
        m = re.match(r"bytes=(\d+)-(\d+)", req.headers.get("range", ""))
        a, b = (int(m.group(1)), int(m.group(2)) + 1) if m else (0, len(dado))
        b = min(b, len(dado))
        return httpx.Response(206, content=dado[a:b], headers={"content-range": f"bytes {a}-{b - 1}/{len(dado)}"})

    return httpx.MockTransport(responder)


def test_arquivo_http_seek_read_e_cache():
    dado = bytes(range(256)) * 400  # 102.400 bytes
    log: list[str] = []
    cli = httpx.Client(transport=transporte(dado, log))
    med = Medidor()
    f = ArquivoHTTP(URL, cli, med, tamanho=len(dado))
    f.seek(100)
    assert f.read(10) == dado[100:110]
    assert f.read(5) == dado[110:115]  # veio do cache (bloco mínimo de 16 KB)
    assert med.requisicoes == 1 and med.bytes == 1 << 14
    f.seek(-4, 2)
    assert f.read() == dado[-4:]
    assert f.get_byte_ranges([50_000, 70_000], [100, 200]) == [dado[50_000:50_100], dado[70_000:70_200]]


def test_ler_janela_le_so_os_blocos_da_janela():
    dado, arr = cog_bytes()
    log: list[str] = []
    cli = httpx.Client(transport=transporte(dado, log))
    med = Medidor()
    # janela de 30x20 px a partir da coluna 300, linha 500 (cai num único bloco de 256)
    x0, y0 = 399960 + 300 * 10, 8100040 - 500 * 10
    jan = ler_janela(URL, (x0, y0 - 200, x0 + 300, y0), cli, med)
    assert jan.dados.shape == (20, 30)
    np.testing.assert_array_equal(jan.dados, arr[500:520, 300:330])
    assert (jan.col_off, jan.row_off) == (300, 500)
    assert med.bytes < len(dado) / 4  # não baixou o arquivo inteiro
    assert set(log) == {URL}  # nenhum arquivo auxiliar (.aux.xml/.ovr/.msk) foi sondado


def test_ler_janela_alinhada_a_pares_e_janela_explicita():
    dado, arr = cog_bytes()
    cli = httpx.Client(transport=transporte(dado, []))
    med = Medidor()
    x0, y0 = 399960 + 301 * 10, 8100040 - 501 * 10
    jan = ler_janela(URL, (x0, y0 - 150, x0 + 150, y0), cli, med, multiplo=2)
    assert jan.col_off % 2 == 0 and jan.row_off % 2 == 0
    assert jan.dados.shape[0] % 2 == 0 and jan.dados.shape[1] % 2 == 0
    exp = ler_janela(URL, (0, 0, 0, 0), cli, med, janela_px=(10, 20, 5, 4))
    np.testing.assert_array_equal(exp.dados, arr[20:24, 10:15])
