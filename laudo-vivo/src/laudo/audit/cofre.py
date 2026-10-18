"""Retenção e expurgo LGPD por *crypto-shredding*: uma chave por fiscalização.

Os arquivos brutos com dado pessoal de uma fiscalização (áudio da fala, vídeo, fotos, NF-e e GTA com nome e
CPF/CNPJ, quadros-chave e a conversa) são cifrados com a chave daquela fiscalização. No fim do prazo
de retenção, ou a pedido do titular, **apaga-se a chave** (`expurgar`): os arquivos cifrados ficam
ilegíveis, sem precisar caçar cópias, e a **cadeia de hash continua íntegra**, porque ela guarda o sha256
do conteúdo e os metadados de cada evidência, não o arquivo. O laudo selado continua provando *que* a
evidência existiu e qual era o hash.

Cifra: só biblioteca padrão (o ambiente não tem `cryptography`). Fluxo HMAC-SHA256 em modo contador (PRF em
CTR) com nonce aleatório de 16 bytes, mais etiqueta HMAC-SHA256 (encrypt-then-MAC) sobre versão, fiscalização,
nonce e texto cifrado; chaves de cifra e de MAC derivadas da chave da fiscalização. Em produção: AES-256-GCM
e a chave num KMS/HSM separado dos dados (aqui a chave fica em `<dados>/chaves/`, fora do repositório).

Limites declarados: o texto das falas que vira evidência `declaracao` fica no estado (dentro da cadeia) e
não é cifrado por esta rotina; o expurgo apaga a chave, mas uma cópia de backup da chave feita fora do sistema
continuaria valendo. Ver `docs/fluxo_do_agente.md`, seção 5.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import date, datetime
from pathlib import Path
from typing import Any

VERSAO = b"LVC1"
_NONCE = 16
_TAG = 32
SUFIXO = ".lvc"
_BLOCO_ARQUIVO = 1 << 20  # 1 MiB (múltiplo de 32: o fluxo continua de onde parou)
RETENCAO_BRUTOS_DIAS = 90  # proposta (fluxo_do_agente.md §5): brutos 90 dias após o selo; a IF define o prazo


class ErroCofre(Exception):
    pass


class ChaveExpurgada(ErroCofre):
    """A chave da fiscalização foi apagada: o dado cifrado é irrecuperável (crypto-shredding)."""


class ErroIntegridade(ErroCofre):
    """Etiqueta HMAC não confere: arquivo cifrado alterado ou de outra fiscalização."""


def _seguro(fis_id: str) -> str:
    s = "".join(c for c in fis_id if c.isalnum() or c in "_-")
    if not s or s != fis_id:
        raise ValueError(f"id de fiscalização inválido: {fis_id!r}")
    return s


def _fluxo(chave_enc: bytes, nonce: bytes, n: int, inicio: int = 0) -> bytes:
    """`n` bytes do fluxo a partir da posição `inicio` (múltiplo de 32: cifra de arquivo em blocos)."""
    if inicio % 32:
        raise ValueError("início do fluxo precisa ser múltiplo de 32")
    primeiro = inicio // 32
    blocos = []
    for i in range(primeiro, primeiro + (n + 31) // 32):
        blocos.append(hmac.new(chave_enc, nonce + i.to_bytes(8, "big"), hashlib.sha256).digest())
    return b"".join(blocos)[:n]


def _xor(a: bytes, b: bytes) -> bytes:
    return (int.from_bytes(a, "big") ^ int.from_bytes(b, "big")).to_bytes(len(a), "big") if a else b""


class Cofre:
    """Chaves por fiscalização em `<diretorio>/<fis_id>.chave` e registro de expurgos em `expurgos.jsonl`."""

    def __init__(self, diretorio: str | Path | None = None):
        if diretorio is None:
            from laudo.agent.estado import diretorio_dados

            diretorio = diretorio_dados() / "chaves"
        self.dir = Path(diretorio)

    # -- chaves ---------------------------------------------------------------------
    def _arq_chave(self, fis_id: str) -> Path:
        return self.dir / f"{_seguro(fis_id)}.chave"

    def tem_chave(self, fis_id: str) -> bool:
        return self._arq_chave(fis_id).is_file()

    def expurgado(self, fis_id: str) -> bool:
        return any(r.get("fiscalizacao_id") == fis_id for r in self.expurgos())

    def chave(self, fis_id: str, criar: bool = False) -> bytes:
        arq = self._arq_chave(fis_id)
        if arq.is_file():
            return bytes.fromhex(arq.read_text(encoding="ascii").strip())
        if not criar or self.expurgado(fis_id):
            raise ChaveExpurgada(f"sem chave para {fis_id}: dado cifrado irrecuperável")
        self.dir.mkdir(parents=True, exist_ok=True)
        k = secrets.token_bytes(32)
        tmp = arq.with_suffix(".tmp")
        tmp.write_text(k.hex(), encoding="ascii")
        os.replace(tmp, arq)
        return k

    def _subchaves(self, fis_id: str, criar: bool) -> tuple[bytes, bytes]:
        k = self.chave(fis_id, criar=criar)
        return (
            hmac.new(k, b"laudo-vivo/cifra", hashlib.sha256).digest(),
            hmac.new(k, b"laudo-vivo/mac", hashlib.sha256).digest(),
        )

    # -- bytes ----------------------------------------------------------------------
    def cifrar(self, fis_id: str, dados: bytes) -> bytes:
        k_enc, k_mac = self._subchaves(fis_id, criar=True)
        nonce = secrets.token_bytes(_NONCE)
        cifrado = _xor(dados, _fluxo(k_enc, nonce, len(dados)))
        tag = hmac.new(k_mac, VERSAO + fis_id.encode() + nonce + cifrado, hashlib.sha256).digest()
        return VERSAO + nonce + cifrado + tag

    def decifrar(self, fis_id: str, blob: bytes) -> bytes:
        if blob[:4] != VERSAO or len(blob) < 4 + _NONCE + _TAG:
            raise ErroIntegridade("formato desconhecido")
        k_enc, k_mac = self._subchaves(fis_id, criar=False)
        nonce, cifrado, tag = blob[4 : 4 + _NONCE], blob[4 + _NONCE : -_TAG], blob[-_TAG:]
        esperado = hmac.new(k_mac, VERSAO + fis_id.encode() + nonce + cifrado, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, esperado):
            raise ErroIntegridade("etiqueta não confere")
        return _xor(cifrado, _fluxo(k_enc, nonce, len(cifrado)))

    def cifrar_texto(self, fis_id: str, texto: str) -> str:
        return "lvc1:" + base64.b64encode(self.cifrar(fis_id, texto.encode("utf-8"))).decode("ascii")

    def decifrar_texto(self, fis_id: str, token: str) -> str:
        if not token.startswith("lvc1:"):
            raise ErroIntegridade("não é texto cifrado")
        return self.decifrar(fis_id, base64.b64decode(token[5:])).decode("utf-8")

    # -- arquivos -------------------------------------------------------------------
    def cifrar_arquivo(self, fis_id: str, caminho: str | Path, apagar_original: bool = True) -> Path:
        """`x.jpg` → `x.jpg.lvc`. O original é apagado (num SSD, apagar não garante sumiço físico: por isso o
        dado só deve existir em claro durante o processamento, e a garantia do expurgo vem da chave).

        Cifra em blocos de 1 MiB (vídeo de 600 MB não vai inteiro para a memória) no mesmo formato de `cifrar`
        (`decifrar` lê os dois). Escreve num temporário e só troca de nome no fim: se cair no meio, o original
        continua lá e não fica `.lvc` pela metade."""
        p = Path(caminho)
        destino = p.with_name(p.name + SUFIXO)
        k_enc, k_mac = self._subchaves(fis_id, criar=True)
        nonce = secrets.token_bytes(_NONCE)
        mac = hmac.new(k_mac, VERSAO + fis_id.encode() + nonce, hashlib.sha256)
        tmp = destino.with_name(destino.name + ".tmp")
        try:
            with open(p, "rb") as ent, open(tmp, "wb") as sai:
                sai.write(VERSAO + nonce)
                pos = 0
                while bloco := ent.read(_BLOCO_ARQUIVO):
                    cifrado = _xor(bloco, _fluxo(k_enc, nonce, len(bloco), inicio=pos))
                    mac.update(cifrado)
                    sai.write(cifrado)
                    pos += len(bloco)
                sai.write(mac.digest())
            os.replace(tmp, destino)
        finally:
            if tmp.exists():
                tmp.unlink()
        if apagar_original:
            p.unlink()
        return destino

    def decifrar_arquivo(self, fis_id: str, caminho_cifrado: str | Path) -> bytes:
        return self.decifrar(fis_id, Path(caminho_cifrado).read_bytes())

    # -- expurgo --------------------------------------------------------------------
    def expurgar(self, fis_id: str, motivo: str, quando: datetime | None = None) -> dict[str, Any]:
        """Apaga a chave (sobrescreve e remove) e registra o expurgo. Idempotente."""
        arq = self._arq_chave(fis_id)
        existia = arq.is_file()
        if existia:
            arq.write_text(secrets.token_hex(32), encoding="ascii")
            arq.unlink()
        reg = {
            "fiscalizacao_id": fis_id,
            "em": (quando or datetime.now().astimezone()).isoformat(timespec="seconds"),
            "motivo": motivo,
            "chave_existia": existia,
        }
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.dir / "expurgos.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(reg, ensure_ascii=False) + "\n")
        return reg

    def expurgos(self) -> list[dict[str, Any]]:
        arq = self.dir / "expurgos.jsonl"
        if not arq.is_file():
            return []
        return [json.loads(x) for x in arq.read_text(encoding="utf-8").splitlines() if x.strip()]


def data_do_selo(fis: Any) -> date | None:
    """Data da assinatura humana (início da contagem da retenção dos brutos)."""
    aprov = getattr(fis, "aprovacoes", None) or []
    if getattr(fis, "estado_fsm", "") != "SELADO" or not aprov:
        return None
    return aprov[-1].em.date()


def vencidas(fiscalizacoes: list[Any], hoje: date, dias: int = RETENCAO_BRUTOS_DIAS) -> list[str]:
    """Ids das fiscalizações seladas há mais de `dias` (brutos devem ser expurgados)."""
    saida = []
    for f in fiscalizacoes:
        d = data_do_selo(f)
        if d is not None and (hoje - d).days > dias:
            saida.append(f.id)
    return saida
