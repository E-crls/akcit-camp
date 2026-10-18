"""Download em streaming de arquivos públicos (BCB, IBGE) sem guardar o bruto.

Usado pelos scripts `scripts/dados_*.py`. Lê o corpo HTTP em blocos, descompacta gzip
(inclusive gzip com vários membros) e entrega linhas, sem carregar o arquivo inteiro na
memória. Se o Python falhar no TLS de algum host, cai para `curl` (disponível no Git Bash).
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import zlib
from collections.abc import Iterator
from dataclasses import dataclass, field

import httpx

UA = "laudo-vivo/0.1 (AKCIT Camp 2026; dados publicos)"


@dataclass
class InfoDownload:
    """Metadados do que foi baixado (para o data card e para reprodutibilidade)."""

    url: str
    bytes_transferidos: int = 0
    sha256: str = ""
    last_modified: str = ""
    content_length: int | None = None
    via: str = "httpx"
    linhas_lidas: int = 0
    linhas_mantidas: int = 0
    extras: dict = field(default_factory=dict)

    def como_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def _blocos_httpx(url: str, info: InfoDownload, bloco: int) -> Iterator[bytes]:
    with httpx.Client(timeout=httpx.Timeout(60.0, read=120.0), headers={"User-Agent": UA},
                      follow_redirects=True) as cli, cli.stream("GET", url) as r:
        r.raise_for_status()
        info.last_modified = r.headers.get("last-modified", "")
        cl = r.headers.get("content-length")
        info.content_length = int(cl) if cl else None
        # Content-Encoding (ex.: IBGE manda JSON com gzip de transporte) é decodificado aqui;
        # um .gz servido como arquivo (BCB) vem cru e é descompactado por `gunzip`.
        if r.headers.get("content-encoding"):
            info.extras["content_encoding"] = r.headers["content-encoding"]
            for b in r.iter_bytes(bloco):
                yield b
        else:
            for b in r.iter_raw(bloco):
                yield b


def _blocos_curl(url: str, info: InfoDownload, bloco: int) -> Iterator[bytes]:
    curl = shutil.which("curl")
    if not curl:
        raise RuntimeError("curl não encontrado para o fallback")
    info.via = "curl"
    with subprocess.Popen([curl, "-s", "-L", "--fail", "-A", UA, url], stdout=subprocess.PIPE) as p:
        assert p.stdout is not None
        while b := p.stdout.read(bloco):
            yield b
        if p.wait() != 0:
            raise RuntimeError(f"curl falhou ({p.returncode}) em {url}")


def blocos(url: str, info: InfoDownload, bloco: int = 1 << 20) -> Iterator[bytes]:
    """Itera os bytes crus do corpo HTTP, contando bytes e calculando o sha256."""
    h = hashlib.sha256()
    try:
        fonte = _blocos_httpx(url, info, bloco)
        primeiro = next(fonte)
    except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout, OSError):
        fonte = _blocos_curl(url, info, bloco)
        primeiro = next(fonte, b"")
    for b in _encadear(primeiro, fonte):
        info.bytes_transferidos += len(b)
        h.update(b)
        yield b
    info.sha256 = h.hexdigest()


def _encadear(primeiro: bytes, resto: Iterator[bytes]) -> Iterator[bytes]:
    if primeiro:
        yield primeiro
    yield from resto


def gunzip(fonte: Iterator[bytes]) -> Iterator[bytes]:
    """Descompacta gzip em streaming (suporta vários membros concatenados)."""
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    for b in fonte:
        while b:
            out = d.decompress(b)
            if out:
                yield out
            if d.eof:
                b = d.unused_data
                d = zlib.decompressobj(16 + zlib.MAX_WBITS)
            else:
                b = b""
    resto = d.flush()
    if resto:
        yield resto


def linhas(fonte: Iterator[bytes], encoding: str = "latin-1") -> Iterator[str]:
    """Quebra um fluxo de bytes em linhas de texto (sem o fim de linha)."""
    pendente = b""
    for b in fonte:
        pendente += b
        partes = pendente.split(b"\n")
        pendente = partes.pop()
        for p in partes:
            yield p.rstrip(b"\r").decode(encoding)
    if pendente:
        yield pendente.rstrip(b"\r").decode(encoding)


def baixar_bytes(url: str, info: InfoDownload | None = None) -> bytes:
    """Baixa um arquivo pequeno inteiro (tabelas de domínio, JSON do IBGE)."""
    info = info or InfoDownload(url=url)
    return b"".join(blocos(url, info))
