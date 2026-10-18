"""Identificadores na trilha (LGPD): sal por instalação, hash com sal e chave de acesso mascarada.

A chave de acesso da NF-e (44 posições) embute o CNPJ **ou o CPF** do emitente (posições 7 a 20); quando quem
vende o gado é pessoa física, a chave é dado pessoal. E o hash de CPF sem sal se desfaz por força bruta
(10⁹ CPFs). Por isso, no **estado**, no **trace** e no **laudo**:

- a chave de acesso aparece só **mascarada** (`522604…59429439`: UF, ano/mês e o fim do código numérico + DV;
  nunca o documento do emitente) e com um **hash com sal da instalação** (`chave_hash`);
- CPF/CNPJ aparecem só mascarados e como `hash_documento`, também com o sal da instalação (HMAC-SHA256);
- a chave inteira e as leituras brutas do VLM (que o residual precisa para continuar) ficam **cifradas no
  cofre** da fiscalização (`audit.cofre`, a mesma chave por fiscalização do expurgo): servem para a consulta
  futura à SEFAZ e para completar a leitura, e somem com o expurgo (crypto-shredding).

O sal fica **fora do controle de versão**, em `<LAUDO_CONFIG_DIR ou dados_locais/config>/instalacao.json`
(`dados_locais/` está no `.gitignore`; nada é escrito fora da pasta do projeto), criado na primeira
execução com 256 bits aleatórios. Consequência declarada: hashes de instalações diferentes não se comparam (é o
objetivo); a referência que vem de fora (o cadastro da IF, o gerador do golden set) entra como hash **público**
`sha256:<hex>` (`docs_fiscais.comum.hash_documento_publico`) e é convertida aqui, na entrada, e nunca guardada.

O DV da chave continua validado na leitura (com a chave inteira em memória); o resultado da validação fica no
estado (status e motivo do campo), sem a chave.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

ARQUIVO = "instalacao.json"
VERSAO = 1
_CACHE: dict[str, dict[str, Any]] = {}

# Chaves de dicionário cujo valor é (ou contém) a chave de acesso: sempre mascaradas.
CAMPOS_CHAVE = ("chave", "ch_nfe", "chave_nfe", "chave_acesso", "base_chave")
LISTAS_CHAVE = ("nfe_chaves",)
# Valores que já são hash ou id: nunca passam pela máscara.
_RX_NAO_MASCARAR = re.compile(r"(sha256|hash|_id$|^id$|trace|span)", re.IGNORECASE)
# Sequência com cara de chave de acesso (inclusive lida com erro pelo VLM): 40 a 44 posições, dígitos e letras
# maiúsculas (CNPJ alfanumérico), com no máximo um espaço ou ponto entre elas (o DANFE imprime em grupos de 4).
# Também logo depois de "NFe" (Id do infNFe e URI da assinatura: "#NFe5226…").
_RX_CHAVE = re.compile(r"(?:(?<=NFe)|(?<![0-9A-Za-z]))\d(?:[ .]?[0-9A-Z]){39,43}(?![0-9A-Za-z])")
# Chave parcial do pedido do residual: dígitos, "?" e "d" (posição que vem de outro campo) em 44 posições.
_RX_BASE = re.compile(r"(?<![0-9A-Za-z?])[0-9A-Z?d]{44}(?![0-9A-Za-z?])")


# ---------------------------------------------------------------------------
# Sal por instalação
# ---------------------------------------------------------------------------


def dir_config() -> Path:
    """Pasta da configuração da instalação: `LAUDO_CONFIG_DIR` ou `<repo>/dados_locais/config` (fora do git)."""
    base = os.environ.get("LAUDO_CONFIG_DIR")
    return Path(base) if base else Path(__file__).resolve().parents[2] / "dados_locais" / "config"


def config_instalacao() -> dict[str, Any]:
    """Lê (ou cria, na primeira execução) a configuração da instalação. Criação exclusiva: dois processos que
    sobem juntos não geram dois sais."""
    d = dir_config()
    chave_cache = str(d.resolve())
    if chave_cache in _CACHE:
        return _CACHE[chave_cache]
    arq = d / ARQUIVO
    if not arq.is_file():
        d.mkdir(parents=True, exist_ok=True)
        cfg = {"versao": VERSAO, "sal": secrets.token_hex(32),
               "criado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
               "aviso": "Sal da instalação do Laudo Vivo (LGPD). Não versionar, não copiar para outra instalação; "
                        "trocar o sal invalida a comparação com hashes antigos."}
        try:
            with open(arq, "x", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=1)
            try:
                os.chmod(arq, 0o600)
            except OSError:  # Windows: permissão pela ACL do perfil do usuário
                pass
        except FileExistsError:
            pass
    cfg = json.loads(arq.read_text(encoding="utf-8"))
    if not re.fullmatch(r"[0-9a-f]{64}", str(cfg.get("sal", ""))):
        raise ValueError(f"{arq}: sal da instalação ausente ou inválido")
    _CACHE[chave_cache] = cfg
    return cfg


def sal() -> bytes:
    return bytes.fromhex(config_instalacao()["sal"])


def id_instalacao() -> str:
    """Impressão digital pública do sal (12 hex): diz qual instalação gerou os hashes, sem revelar o sal."""
    return hashlib.sha256(b"laudo-vivo/instalacao:" + sal()).hexdigest()[:12]


def limpar_cache() -> None:
    """Para testes que trocam `LAUDO_CONFIG_DIR`."""
    _CACHE.clear()


def salgar(dominio: str, valor: str, sal_explicito: str | None = None) -> str:
    """HMAC-SHA256(sal, dominio:valor) em hex. `sal_explicito` só para teste/compatibilidade."""
    k = sal_explicito.encode() if sal_explicito is not None else sal()
    return hmac.new(k, f"{dominio}:{valor}".encode(), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# Documento (CPF/CNPJ) e chave de acesso
# ---------------------------------------------------------------------------


def hash_de_publico(publico: str, sal_explicito: str | None = None) -> str:
    """Hash da instalação a partir do hash público de um CPF/CNPJ (`comum.hash_documento_publico`)."""
    return salgar("doc/v2", publico.lower(), sal_explicito)


def hash_referencia(ref: str | None) -> str | None:
    """Referência ao documento do tomador → hash desta instalação (o que `hash_documento` devolve).

    - `hmac:<hex>`: já é o hash desta instalação (o condutor guarda e repassa assim);
    - `sha256:<hex>` ou `<hex>` sem prefixo: hash **público** (sem sal), como o cadastro da IF, um cliente MCP
      ou o gerador do golden set calculam; é convertido aqui e não é guardado.
    Qualquer outra coisa (referência opaca como "anon" ou "TOMADOR-...") não serve para conferir partes."""
    r = (ref or "").strip().lower()
    if r.startswith("hmac:"):
        return r[5:] if re.fullmatch(r"[0-9a-f]{64}", r[5:]) else None
    r = r.removeprefix("sha256:")
    return hash_de_publico(r) if re.fullmatch(r"[0-9a-f]{64}", r) else None


def so_chave(valor: str | None) -> str:
    return re.sub(r"[^0-9A-Za-z?]", "", valor or "").upper()


def hash_chave(chave: str | None) -> str | None:
    c = so_chave(chave)
    return salgar("chave-nfe/v1", c) if len(c) == 44 and "?" not in c else None


def mascarar_chave(chave: str | None) -> str | None:
    """`522604…59429439`: UF + AAMM e as 8 últimas posições (fim do código numérico e DV). O documento do
    emitente (posições 7 a 20), modelo, série e número ficam de fora; série e número já estão em campo próprio."""
    if chave is None:
        return None
    c = re.sub(r"[^0-9A-Za-z?]", "", str(chave))
    if len(c) < 20:
        return "…" if c else ""
    return f"{c[:6]}…{c[-8:]}"


def mascarar_texto(texto: str) -> str:
    """Troca em texto livre toda sequência com cara de chave de acesso (inclusive lida com erro) pela máscara."""
    if not texto or not any(ch.isdigit() for ch in texto):
        return texto
    t = _RX_CHAVE.sub(lambda m: mascarar_chave(m.group(0)) or "", texto)
    return _RX_BASE.sub(lambda m: mascarar_chave(m.group(0)) or "", t)


# ---------------------------------------------------------------------------
# Resultado de checagem: proteger ao gravar, restaurar para a próxima ferramenta
# ---------------------------------------------------------------------------

Caminho = list[str | int]


def _proteger_no(no: Any, caminho: Caminho, originais: list[tuple[Caminho, str]], chave_pai: str = "") -> Any:
    if isinstance(no, dict):
        out: dict[str, Any] = {}
        for k, v in no.items():
            out[k] = _proteger_no(v, [*caminho, k], originais, str(k))
            if k in CAMPOS_CHAVE and isinstance(v, str) and k != "base_chave" and f"{k}_hash" not in no:
                h = hash_chave(v)
                if h:
                    out[f"{k}_hash"] = h
            if k in LISTAS_CHAVE and isinstance(v, list) and f"{k}_hash" not in no:
                out[f"{k}_hash"] = [hash_chave(x) if isinstance(x, str) else None for x in v]
        return out
    if isinstance(no, list):
        if chave_pai in LISTAS_CHAVE:
            saida = []
            for i, x in enumerate(no):
                if isinstance(x, str) and len(so_chave(x)) >= 20:
                    originais.append(([*caminho, i], x))
                    saida.append(mascarar_chave(x))
                else:
                    saida.append(x)
            return saida
        return [_proteger_no(x, [*caminho, i], originais, chave_pai) for i, x in enumerate(no)]
    if isinstance(no, str) and no:
        if _RX_NAO_MASCARAR.search(chave_pai):
            return no
        cara_de_chave = chave_pai in CAMPOS_CHAVE and len(so_chave(no)) >= 20
        novo = mascarar_chave(no) if cara_de_chave else mascarar_texto(no)
        if novo != no:
            originais.append((list(caminho), no))
            return novo
    return no


def proteger_resultado(data: dict[str, Any], fis_id: str | None = None, cofre: Any | None = None) -> dict[str, Any]:
    """Cópia de `data` sem chave de acesso em claro (máscara + `*_hash`). Os valores originais vão cifrados para o
    cofre da fiscalização em `_cofre` (para a próxima ferramenta e a consulta futura); sem cofre, são descartados."""
    originais: list[tuple[Caminho, str]] = []
    out = _proteger_no(data, [], originais)
    out.pop("_cofre", None)
    if originais and cofre is not None and fis_id:
        from laudo.audit.cofre import ErroCofre

        corpo = json.dumps([[c, v] for c, v in originais], ensure_ascii=False)
        try:
            out["_cofre"] = {"versao": VERSAO, "campos": len(originais), "token": cofre.cifrar_texto(fis_id, corpo)}
        except ErroCofre:  # chave da fiscalização já expurgada (pedido do titular): o original é descartado
            pass
    return out


def restaurar_resultado(data: dict[str, Any], fis_id: str | None = None, cofre: Any | None = None) -> dict[str, Any]:
    """Cópia de `data` com os valores originais de volta (em memória, para a ferramenta seguinte). Chave
    expurgada ou cofre ausente: devolve a cópia mascarada (a ferramenta segue com o que restou)."""
    out = copy.deepcopy(data)
    meta = out.pop("_cofre", None)
    if not meta or cofre is None or not fis_id:
        return out
    from laudo.audit.cofre import ErroCofre

    try:
        pares = json.loads(cofre.decifrar_texto(fis_id, str(meta.get("token") or "")))
    except (ErroCofre, ValueError):
        return out
    for caminho, valor in pares:
        alvo: Any = out
        try:
            for passo in caminho[:-1]:
                alvo = alvo[passo]
            alvo[caminho[-1]] = valor
        except (KeyError, IndexError, TypeError):
            continue
    return out


def chaves_para_consulta(resultados: list[dict[str, Any]], fis_id: str, cofre: Any) -> list[str]:
    """Chaves de acesso inteiras guardadas no cofre (consulta futura à SEFAZ, durante a retenção)."""
    achadas: list[str] = []
    for r in resultados:
        if not r.get("_cofre"):
            continue
        cheio = restaurar_resultado(r, fis_id, cofre)
        for doc in [cheio.get("documento") or {}, *(cheio.get("notas") or [])]:
            c = so_chave(doc.get("chave") if isinstance(doc, dict) else None)
            if len(c) == 44 and "?" not in c and c not in achadas:
                achadas.append(c)
    return achadas
