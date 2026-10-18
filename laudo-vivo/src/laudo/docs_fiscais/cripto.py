"""DER/X.509 mínimo e RSA PKCS#1 v1.5 em Python puro.

O ambiente não tem `cryptography`; para verificar offline a assinatura XMLDSig da NF-e basta:
(1) extrair módulo e expoente da chave pública do certificado embutido (X.509 em DER) e
(2) checar a assinatura PKCS#1 v1.5. A geração de chave e de certificado existe só para os
documentos sintéticos (golden set e testes): nunca use estas funções para proteger nada real.

Limites deliberados: não valida cadeia ICP-Brasil, LCR/OCSP nem extensões do certificado.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

# ---------------------------------------------------------------------------
# DER: codificação
# ---------------------------------------------------------------------------


def _der_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def der(tag: int, conteudo: bytes) -> bytes:
    return bytes([tag]) + _der_len(len(conteudo)) + conteudo


def der_int(v: int) -> bytes:
    b = v.to_bytes(max(1, (v.bit_length() + 8) // 8), "big")  # +8 garante bit de sinal zero
    return der(0x02, b)


def der_seq(*partes: bytes) -> bytes:
    return der(0x30, b"".join(partes))


def der_set(*partes: bytes) -> bytes:
    return der(0x31, b"".join(sorted(partes)))


def der_oid(oid: str) -> bytes:
    nums = [int(x) for x in oid.split(".")]
    corpo = bytearray([40 * nums[0] + nums[1]])
    for n in nums[2:]:
        grupo = [n & 0x7F]
        n >>= 7
        while n:
            grupo.append(0x80 | (n & 0x7F))
            n >>= 7
        corpo.extend(reversed(grupo))
    return der(0x06, bytes(corpo))


def der_null() -> bytes:
    return b"\x05\x00"


def der_bitstring(b: bytes) -> bytes:
    return der(0x03, b"\x00" + b)


def der_utf8(s: str) -> bytes:
    return der(0x0C, s.encode("utf-8"))


def der_printable(s: str) -> bytes:
    return der(0x13, s.encode("ascii"))


def der_utctime(dt: datetime) -> bytes:
    return der(0x17, dt.astimezone(UTC).strftime("%y%m%d%H%M%SZ").encode())


def der_explicito(n: int, conteudo: bytes) -> bytes:
    return der(0xA0 + n, conteudo)


# ---------------------------------------------------------------------------
# DER: leitura
# ---------------------------------------------------------------------------


class ErroDER(ValueError):
    pass


def ler_tlv(buf: bytes, pos: int) -> tuple[int, int, int]:
    """Lê um TLV em `pos`. Devolve (tag, início do conteúdo, fim do conteúdo)."""
    if pos + 2 > len(buf):
        raise ErroDER("DER truncado")
    tag = buf[pos]
    n = buf[pos + 1]
    pos += 2
    if n & 0x80:
        k = n & 0x7F
        if k == 0 or k > 4 or pos + k > len(buf):
            raise ErroDER("comprimento DER inválido")
        n = int.from_bytes(buf[pos:pos + k], "big")
        pos += k
    if pos + n > len(buf):
        raise ErroDER("DER truncado")
    return tag, pos, pos + n


def filhos(buf: bytes, ini: int, fim: int) -> list[tuple[int, int, int]]:
    out = []
    pos = ini
    while pos < fim:
        t, a, b = ler_tlv(buf, pos)
        out.append((t, a, b))
        pos = b
    return out


def _ler_oid(b: bytes) -> str:
    nums = [b[0] // 40, b[0] % 40]
    v = 0
    for x in b[1:]:
        v = (v << 7) | (x & 0x7F)
        if not x & 0x80:
            nums.append(v)
            v = 0
    return ".".join(str(n) for n in nums)


_OID_NOMES = {"2.5.4.3": "CN", "2.5.4.6": "C", "2.5.4.10": "O", "2.5.4.11": "OU", "2.5.4.8": "ST",
              "2.5.4.7": "L"}


def _ler_nome(buf: bytes, ini: int, fim: int) -> dict[str, str]:
    nome: dict[str, str] = {}
    for _, a, b in filhos(buf, ini, fim):  # SET
        for _, a2, b2 in filhos(buf, a, b):  # SEQ { OID, valor }
            (_, oa, ob), (_, va, vb) = filhos(buf, a2, b2)[:2]
            chave = _OID_NOMES.get(_ler_oid(buf[oa:ob]), _ler_oid(buf[oa:ob]))
            valor = buf[va:vb].decode("utf-8", errors="replace")
            nome[chave] = f"{nome[chave]}, {valor}" if chave in nome else valor
    return nome


def _ler_tempo(tag: int, b: bytes) -> datetime:
    s = b.decode("ascii")
    fmt = "%y%m%d%H%M%SZ" if tag == 0x17 else "%Y%m%d%H%M%SZ"
    return datetime.strptime(s, fmt).replace(tzinfo=UTC)


def ler_certificado(cert_der: bytes) -> dict[str, Any]:
    """Extrai o essencial de um X.509 v3 em DER: sujeito, emissor, validade e chave RSA."""
    _, a, b = ler_tlv(cert_der, 0)
    _tbs_t, tbs_a, tbs_b = filhos(cert_der, a, b)[0]
    campos = filhos(cert_der, tbs_a, tbs_b)
    if campos and campos[0][0] == 0xA0:  # versão explícita
        campos = campos[1:]
    _serial_t, sa, sb = campos[0]
    emissor = _ler_nome(cert_der, campos[2][1], campos[2][2])
    validade = filhos(cert_der, campos[3][1], campos[3][2])
    sujeito = _ler_nome(cert_der, campos[4][1], campos[4][2])
    spki = filhos(cert_der, campos[5][1], campos[5][2])
    alg = filhos(cert_der, spki[0][1], spki[0][2])
    oid_alg = _ler_oid(cert_der[alg[0][1]:alg[0][2]])
    bits_a, bits_b = spki[1][1], spki[1][2]
    chave_buf = cert_der[bits_a + 1:bits_b]  # pula o byte de bits não usados
    _, ka, kb = ler_tlv(chave_buf, 0)
    (_, na, nb), (_, ea, eb) = filhos(chave_buf, ka, kb)[:2]
    return {
        "serial": int.from_bytes(cert_der[sa:sb], "big"),
        "emissor": emissor,
        "sujeito": sujeito,
        "nao_antes": _ler_tempo(validade[0][0], cert_der[validade[0][1]:validade[0][2]]),
        "nao_depois": _ler_tempo(validade[1][0], cert_der[validade[1][1]:validade[1][2]]),
        "algoritmo_chave": oid_alg,
        "n": int.from_bytes(chave_buf[na:nb], "big"),
        "e": int.from_bytes(chave_buf[ea:eb], "big"),
    }


# ---------------------------------------------------------------------------
# RSA PKCS#1 v1.5
# ---------------------------------------------------------------------------

DIGEST_INFO = {
    "sha1": bytes.fromhex("3021300906052b0e03021a05000414"),
    "sha256": bytes.fromhex("3031300d060960864801650304020105000420"),
}


def _codificar_emsa(mensagem: bytes, hash_nome: str, k: int) -> bytes:
    t = DIGEST_INFO[hash_nome] + hashlib.new(hash_nome, mensagem).digest()
    if k < len(t) + 11:
        raise ValueError("módulo RSA pequeno demais")
    return b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t


def rsa_verificar(n: int, e: int, assinatura: bytes, mensagem: bytes, hash_nome: str) -> bool:
    k = (n.bit_length() + 7) // 8
    if len(assinatura) != k:
        return False
    s = int.from_bytes(assinatura, "big")
    if s >= n:
        return False
    em = pow(s, e, n).to_bytes(k, "big")
    return em == _codificar_emsa(mensagem, hash_nome, k)


@dataclass(frozen=True)
class ChaveRSA:
    n: int
    e: int
    d: int

    @property
    def bits(self) -> int:
        return self.n.bit_length()


def rsa_assinar(chave: ChaveRSA, mensagem: bytes, hash_nome: str) -> bytes:
    k = (chave.n.bit_length() + 7) // 8
    m = int.from_bytes(_codificar_emsa(mensagem, hash_nome, k), "big")
    return pow(m, chave.d, chave.n).to_bytes(k, "big")


_PRIMOS_PEQUENOS = [p for p in range(3, 2000) if all(p % q for q in range(2, int(p ** 0.5) + 1))]


def _primo_provavel(n: int, rng: random.Random, rodadas: int = 24) -> bool:
    if n < 4:
        return n in (2, 3)
    d, s = n - 1, 0
    while d % 2 == 0:
        d //= 2
        s += 1
    for _ in range(rodadas):
        x = pow(rng.randrange(2, n - 2), d, n)
        if x in (1, n - 1):
            continue
        for _ in range(s - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _gerar_primo(bits: int, rng: random.Random, e: int) -> int:
    while True:
        c = rng.getrandbits(bits) | (1 << (bits - 1)) | (1 << (bits - 2)) | 1
        if any(c % p == 0 for p in _PRIMOS_PEQUENOS) or (c - 1) % e == 0:
            continue
        if _primo_provavel(c, rng):
            return c


def gerar_chave_rsa(rng: random.Random, bits: int = 2048, e: int = 65537) -> ChaveRSA:
    """Chave RSA determinística pelo `rng` (apenas para documentos sintéticos)."""
    while True:
        p = _gerar_primo(bits // 2, rng, e)
        q = _gerar_primo(bits // 2, rng, e)
        n = p * q
        if p != q and n.bit_length() == bits:
            return ChaveRSA(n=n, e=e, d=pow(e, -1, (p - 1) * (q - 1)))


# ---------------------------------------------------------------------------
# Certificado X.509 sintético (autoassinado ou emitido por uma "AC TESTE")
# ---------------------------------------------------------------------------

_OID_RSA = "1.2.840.113549.1.1.1"
_OID_SHA256_RSA = "1.2.840.113549.1.1.11"


def _nome_der(cn: str, o: str = "DOCUMENTO SINTETICO - SEM VALOR LEGAL") -> bytes:
    return der_seq(
        der_set(der_seq(der_oid("2.5.4.6"), der_printable("BR"))),
        der_set(der_seq(der_oid("2.5.4.10"), der_utf8(o))),
        der_set(der_seq(der_oid("2.5.4.3"), der_utf8(cn))),
    )


def gerar_certificado(sujeito_cn: str, chave_sujeito: ChaveRSA, emissor_cn: str, chave_emissor: ChaveRSA,
                      serial: int, inicio: datetime, fim: datetime) -> bytes:
    """Certificado X.509 v3 mínimo (sem extensões) assinado com sha256WithRSAEncryption."""
    alg = der_seq(der_oid(_OID_SHA256_RSA), der_null())
    spki = der_seq(der_seq(der_oid(_OID_RSA), der_null()),
                   der_bitstring(der_seq(der_int(chave_sujeito.n), der_int(chave_sujeito.e))))
    tbs = der_seq(der_explicito(0, der_int(2)), der_int(serial), alg, _nome_der(emissor_cn),
                  der_seq(der_utctime(inicio), der_utctime(fim)), _nome_der(sujeito_cn), spki)
    assinatura = rsa_assinar(chave_emissor, tbs, "sha256")
    return der_seq(tbs, alg, der_bitstring(assinatura))
