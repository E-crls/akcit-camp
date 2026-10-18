"""Leitura janelada de COG remoto com rasterio, medindo bytes e requisições.

O rasterio abre o href https do STAC por meio de um `opener` Python (rasterio >= 1.4): o GDAL
pede trechos do arquivo e este módulo os busca com requisições HTTP `Range`, contando cada byte.
Motivos para não usar `/vsicurl/` direto: (1) aqui sabemos exatamente quantos bytes cada leitura
custou (requisito do laudo e do orçamento de rede); (2) no Windows, processos que usam o curl do
GDAL podem travar na saída do interpretador. O resultado é o mesmo: só o
cabeçalho e os blocos que tocam a janela são transferidos.

O contêiner só "enxerga" o próprio href (sem arquivos auxiliares .aux.xml/.ovr/.msk), para o GDAL
não sondar o S3 atrás deles, e implementa leitura de várias faixas em paralelo
(`get_byte_ranges`), usada quando a janela toca mais de um bloco.
"""

from __future__ import annotations

import io
import logging
import threading
import time
import warnings
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import httpx
import numpy as np

# rasterio 1.5 + NumPy 2.5 emitem DeprecationWarning ao ler janelas; não afeta o resultado
warnings.filterwarnings("ignore", message="Setting the shape on a NumPy array", category=DeprecationWarning)

BLOCO_MIN = 1 << 14  # 16 KB: o cabeçalho do COG do Sentinel-2 cabe aqui
log = logging.getLogger(__name__)


@dataclass
class Medidor:
    """Conta bytes e requisições (thread-safe)."""

    bytes: int = 0
    requisicoes: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def somar(self, n: int) -> None:
        with self._lock:
            self.bytes += n
            self.requisicoes += 1


def _get_faixa(cli: httpx.Client, url: str, a: int, b: int, med: Medidor) -> tuple[bytes, str]:
    """GET bytes [a, b) com até 3 tentativas para erro de transporte ou 5xx; 4xx falha na hora."""
    ultimo: Exception | None = None
    t = time.perf_counter()
    for tentativa in range(3):
        try:
            r = cli.get(url, headers={"Range": f"bytes={a}-{b - 1}"})
            if 400 <= r.status_code < 500:
                raise FileNotFoundError(f"HTTP {r.status_code} em {url}")
            r.raise_for_status()
            break
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            ultimo = e
            time.sleep(0.5 * (tentativa + 1))
    else:
        raise OSError(f"falha ao ler {url} [{a}-{b}]: {ultimo}")
    dado = r.content
    med.somar(len(dado))
    log.debug("GET %s [%d-%d) %d B em %.2f s", url.rsplit("/", 1)[-1], a, b, len(dado), time.perf_counter() - t)
    return dado, r.headers.get("content-range", "")


class ArquivoHTTP(io.RawIOBase):
    """Arquivo remoto somente leitura com `seek`/`read` sobre requisições HTTP Range."""

    def __init__(self, url: str, cliente: httpx.Client, medidor: Medidor, tamanho: int,
                 cabecalho: bytes = b"", bloco_min: int = BLOCO_MIN, max_cache: int = 32):
        super().__init__()
        self.url, self.cli, self.med, self.bloco_min = url, cliente, medidor, bloco_min
        self.tam = tamanho
        self.pos = 0
        self._cache: OrderedDict[tuple[int, int], bytes] = OrderedDict()
        self._max_cache = max_cache
        if cabecalho:
            self._guardar(0, len(cabecalho), cabecalho)

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, off: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_SET:
            self.pos = off
        elif whence == io.SEEK_CUR:
            self.pos += off
        else:
            self.pos = self.tam + off
        return self.pos

    def _do_cache(self, a: int, b: int) -> bytes | None:
        for (ca, cb), dado in self._cache.items():
            if ca <= a and b <= cb:
                self._cache.move_to_end((ca, cb))
                return dado[a - ca:b - ca]
        return None

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = self.tam - self.pos
        a, b = self.pos, min(self.tam, self.pos + n)
        if b <= a:
            return b""
        dado = self._do_cache(a, b)
        if dado is None:
            fim = min(self.tam, max(b, a + self.bloco_min))
            bruto, _ = _get_faixa(self.cli, self.url, a, fim, self.med)
            self._guardar(a, a + len(bruto), bruto)
            dado = bruto[: b - a]
        self.pos = b
        return dado

    def readinto(self, buf) -> int:
        d = self.read(len(buf))
        buf[: len(d)] = d
        return len(d)

    def get_byte_ranges(self, offsets: list[int], sizes: list[int]) -> list[bytes]:
        """Várias faixas de uma vez (blocos da janela), buscadas em paralelo."""
        def uma(i: int) -> bytes:
            a, b = offsets[i], offsets[i] + sizes[i]
            d = self._do_cache(a, b)
            if d is not None:
                return d
            bruto, _ = _get_faixa(self.cli, self.url, a, b, self.med)
            return bruto

        if len(offsets) == 1:
            return [uma(0)]
        with ThreadPoolExecutor(max_workers=min(6, len(offsets))) as ex:
            return list(ex.map(uma, range(len(offsets))))

    def _guardar(self, a: int, b: int, dado: bytes) -> None:
        self._cache[(a, b)] = dado
        while len(self._cache) > self._max_cache:
            self._cache.popitem(last=False)


def _container_base():
    from rasterio.abc import MultiByteRangeResourceContainer

    return MultiByteRangeResourceContainer


class _ContainerHTTPBase:
    """Implementação comum; a classe concreta herda do ABC do rasterio (import tardio)."""

    def __init__(self, href: str, cliente: httpx.Client, medidor: Medidor):
        self.href, self.cli, self.med = href, cliente, medidor
        self._tam: int | None = None
        self._cab = b""

    def _garantir(self) -> None:
        if self._tam is None:
            dado, cr = _get_faixa(self.cli, self.href, 0, BLOCO_MIN, self.med)
            self._cab = dado
            self._tam = int(cr.rsplit("/", 1)[-1]) if "/" in cr else len(dado)

    def open(self, path: str, mode: str = "r", **kwds):
        if path != self.href:
            raise FileNotFoundError(path)
        self._garantir()
        return ArquivoHTTP(self.href, self.cli, self.med, self._tam or 0, self._cab)

    def isfile(self, path: str) -> bool:
        return path == self.href

    def isdir(self, path: str) -> bool:
        return False

    def ls(self, path: str) -> list[str]:
        return []

    def mtime(self, path: str) -> int:
        return 0

    def rm(self, path: str) -> None:
        raise PermissionError("somente leitura")

    def size(self, path: str) -> int:
        if path != self.href:
            raise FileNotFoundError(path)
        self._garantir()
        return int(self._tam or 0)


_CLASSE: type | None = None


def container_http(href: str, cliente: httpx.Client, medidor: Medidor):
    global _CLASSE
    if _CLASSE is None:
        _CLASSE = type("ContainerHTTP", (_ContainerHTTPBase, _container_base()), {})
    return _CLASSE(href, cliente, medidor)


def novo_cliente(timeout_s: float = 30.0) -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(timeout_s), follow_redirects=True,
                        headers={"User-Agent": "laudo-vivo/0.1 (AKCIT Camp 2026)"},
                        limits=httpx.Limits(max_connections=16, max_keepalive_connections=8))


@dataclass
class Janela:
    dados: np.ndarray
    transform: object  # affine.Affine
    crs: str
    nodata: float | None
    col_off: int
    row_off: int


def ler_janela(href: str, bounds: tuple[float, float, float, float], cliente: httpx.Client, medidor: Medidor,
               multiplo: int = 1, janela_px: tuple[int, int, int, int] | None = None) -> Janela:
    """Lê a janela que cobre `bounds` (no CRS do raster) da banda 1 de um COG remoto.

    `multiplo` alinha deslocamento e tamanho a múltiplos de N pixels (usado para casar a grade de
    10 m com a de 20 m). `janela_px` (col, row, largura, altura) força uma janela exata.
    """
    import rasterio
    from rasterio.windows import Window, from_bounds

    with (rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_PAM_ENABLED="NO"),
          rasterio.open(href, opener=container_http(href, cliente, medidor)) as ds):
        if janela_px is None:
            w = from_bounds(*bounds, transform=ds.transform)
            c0 = int(np.floor(w.col_off / multiplo) * multiplo)
            r0 = int(np.floor(w.row_off / multiplo) * multiplo)
            c1 = int(np.ceil((w.col_off + w.width) / multiplo) * multiplo)
            r1 = int(np.ceil((w.row_off + w.height) / multiplo) * multiplo)
            c0, r0 = max(c0, 0), max(r0, 0)
            c1, r1 = min(c1, ds.width), min(r1, ds.height)
        else:
            c0, r0, cw, rh = janela_px
            c1, r1 = c0 + cw, r0 + rh
        if c1 <= c0 or r1 <= r0:
            raise ValueError("janela fora do raster")
        win = Window(c0, r0, c1 - c0, r1 - r0)
        arr = ds.read(1, window=win)
        return Janela(dados=arr, transform=ds.window_transform(win), crs=ds.crs.to_string(),
                      nodata=ds.nodata, col_off=c0, row_off=r0)
