"""Validação determinística de campos lidos de foto/scan de DANFE e de GTA (lidos por VLM ou digitados).

Nada que vem de uma leitura (VLM, OCR ou digitação da fiscal) entra na conciliação sem passar por aqui.
Campo que não valida vira `indeterminado` com motivo e **nunca** é aceito: não há correção nem "chute".
Derivar um campo de outro já validado (ex.: CNPJ do emitente decomposto da chave de acesso com DV conferido)
é decomposição determinística, não invenção, e fica marcado em `origem = "derivado:<campo>"`.

Checagens (todas citáveis):
- chave de acesso: 44 dígitos, DV módulo 11 (MOC 4.00, item 5.4) e coerência com UF (cUF), ano/mês de
  emissão (AAMM), CNPJ/CPF do emitente, modelo 55, série e número impressos no DANFE;
- CNPJ e CPF: dígitos verificadores (IN RFB 2.119/2022 e IN RFB 1.548/2015);
- NCM: 8 dígitos (TEC); a posição 01.02 não é exigida aqui: NCM fora dela é achado da conciliação
  (`conciliar_nfe`), não erro de leitura;
- CFOP: 4 dígitos com 1º dígito de operação válido (Convênio s/nº de 1970, Anexo) e coerência com as UFs
  (5.xxx dentro do estado, 6.xxx entre estados);
- aritmética do item: quantidade × valor unitário = valor total; soma dos itens = valor total dos produtos;
- datas: calendário válido, emissão não futura, coerente com o AAMM da chave;
- GTA: número com 6 dígitos e série com 1-2 letras (IN MAPA 09/2021, art. 9º); soma por sexo e faixa =
  linha TOTAL = total por extenso (Manual SDA, itens 01 e 10); código IBGE com DV e prefixo da UF; nome do
  município coerente com o código (tabela IBGE de GO do bench); CPF/CNPJ com DV; validade ≥ emissão.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from laudo.docs_fiscais.comum import (
    cnpj_valido,
    cpf_valido,
    decompor_chave,
    hash_documento,
    mascarar_documento,
    mascarar_nome,
    so_alnum,
    tipo_documento,
    validar_chave,
)

StatusLeitura = Literal["ok", "indeterminado"]

CODIGO_UF: dict[str, str] = {
    "RO": "11", "AC": "12", "AM": "13", "RR": "14", "PA": "15", "AP": "16", "TO": "17", "MA": "21", "PI": "22",
    "CE": "23", "RN": "24", "PB": "25", "PE": "26", "AL": "27", "SE": "28", "BA": "29", "MG": "31", "ES": "32",
    "RJ": "33", "SP": "35", "PR": "41", "SC": "42", "RS": "43", "MS": "50", "MT": "51", "GO": "52", "DF": "53",
}
UF_POR_CODIGO = {v: k for k, v in CODIGO_UF.items()}
# Municípios cujo 7º dígito do código IBGE não segue a regra do DV (lista divulgada pelo IBGE).
_IBGE_EXCECOES = {"2201919", "2202251", "2201988", "2611533", "3117836", "3152131", "4305871", "5203962",
                  "5203939"}
FINALIDADES_GTA = {"ENGORDA", "REPRODUCAO", "RECRIA", "CRIA", "ABATE", "EXPORTACAO", "EXPOSICAO", "LEILAO",
                   "ESPORTE", "QUARENTENA", "PESQUISA", "DESTRUICAO", "SACRIFICIO_SANITARIO", "AGLOMERACAO",
                   "PRODUCAO_INSUMOS_BIOLOGICOS"}
UNIDADES_COMERCIAIS = {"CB", "CAB", "CABECA", "CABECAS", "CBC", "CABS", "UN", "UND", "UNID", "UNIDADE", "U", "KG",
                       "KGS", "@", "ARROBA", "ARROBAS", "ARR", "T", "TON", "TONELADA"}
FAIXAS = ("0-12", "13-24", "25-36", ">36")


class CampoLido(BaseModel):
    """Um campo lido do documento, já normalizado e validado."""

    nome: str
    valor: Any = None
    status: StatusLeitura
    motivo: str = ""
    critico: bool = True  # entra na conciliação
    origem: str = "leitura"  # leitura | derivado:<campo>
    concordancia: str | None = None  # "2/2", "2/3" (autoconsistência entre leituras do VLM)


class ResultadoLeitura(BaseModel):
    tipo_documento: Literal["danfe", "gta"]
    campos: dict[str, CampoLido] = Field(default_factory=dict)
    documento: dict[str, Any] = Field(default_factory=dict)  # só campos aceitos; documentos como hash
    pedido_nova_foto: str | None = None

    @property
    def criticos_indeterminados(self) -> list[str]:
        return [n for n, c in self.campos.items() if c.critico and c.status != "ok"]


# ---------------------------------------------------------------------------
# Normalização
# ---------------------------------------------------------------------------


def sem_acento(t: str | None) -> str:
    t = unicodedata.normalize("NFKD", t or "")
    return re.sub(r"\s+", " ", "".join(ch for ch in t if not unicodedata.combining(ch))).strip().upper()


def digitos(s: Any) -> str:
    return re.sub(r"\D", "", str(s or ""))


_RE_BR_DEC = re.compile(r"^\d{1,3}(?:\.\d{3})*,\d{1,4}$|^\d+,\d{1,4}$")
_RE_BR_MIL = re.compile(r"^\d{1,3}(?:\.\d{3})+$")


def valor_br(s: Any) -> float | None:
    """Número impresso no padrão brasileiro ("14.550,00", "4", "4,0000", "1.200"). Formato ambíguo
    ("14.55") devolve None: o DANFE imprime decimais com vírgula."""
    t = re.sub(r"\s|R\$", "", str(s or ""))
    if not t or t in {"-", "—"}:
        return None
    if _RE_BR_DEC.match(t):
        return float(t.replace(".", "").replace(",", "."))
    if _RE_BR_MIL.match(t):
        return float(t.replace(".", ""))
    if re.fullmatch(r"\d+", t):
        return float(t)
    return None


def data_br(s: Any) -> date | None:
    m = re.fullmatch(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*", str(s or ""))
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def inteiro_celula(s: Any) -> int | None:
    """Célula de quantidade da GTA: traço = 0; vazio = ilegível (None, nunca zero); senão inteiro."""
    t = str(s if s is not None else "").strip()
    if t in {"-", "—", "–", "--", "0"}:
        return 0
    return int(t) if re.fullmatch(r"\d{1,4}", t) else None


def ibge_dv_ok(codigo: str | None) -> bool:
    c = digitos(codigo)
    if len(c) != 7 or c[:2] not in UF_POR_CODIGO:
        return False
    if c in _IBGE_EXCECOES:
        return True
    soma = 0
    for d, p in zip(c[:6], (1, 2, 1, 2, 1, 2), strict=True):
        x = int(d) * p
        soma += x // 10 + x % 10
    return (10 - soma % 10) % 10 == int(c[6])


@lru_cache(maxsize=1)
def municipios_go() -> dict[str, str]:
    """Código IBGE → nome (sem acento, maiúsculo) dos 246 municípios de GO (bench Fiscal-GO, IBGE)."""
    p = Path(__file__).resolve().parents[3] / "bench" / "fiscal_go" / "rebanho_municipal_go.parquet"
    try:
        import pandas as pd

        df = pd.read_parquet(p, columns=["cod_ibge", "municipio"])
        return {str(c): sem_acento(n) for c, n in zip(df["cod_ibge"], df["municipio"], strict=True)}
    except Exception:  # noqa: BLE001 - sem a tabela, o nome fica só com a autoconsistência
        return {}


_EXTENSO: dict[str, int] | None = None


def extenso_para_int(texto: str | None) -> int | None:
    """"QUATRO BOVINOS" → 4; "VINTE E NOVE" → 29 (0 a 999). Ignora a palavra da espécie/unidade."""
    global _EXTENSO
    if _EXTENSO is None:
        from laudo.docs_fiscais.sintetico import por_extenso

        _EXTENSO = {por_extenso(n): n for n in range(1000)}
        _EXTENSO.update({"UMA": 1, "DUAS": 2, "DUZENTAS": 200, "TREZENTAS": 300, "QUATROCENTAS": 400,
                         "QUINHENTAS": 500, "CATORZE": 14})
    t = sem_acento(texto)
    t = re.sub(r"\b(BOVINOS?|BUBALINOS?|BOVIDEOS?|ANIMAIS|ANIMAL|CABECAS?|BUFALOS?)\b", " ", t)
    t = re.sub(r"[^A-Z ]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if t in _EXTENSO:
        return _EXTENSO[t]
    t2 = t.replace("CATORZE", "QUATORZE").replace("UMA", "UM").replace("DUAS", "DOIS")
    t2 = re.sub(r"\b(\w+)ENTAS\b", lambda m: m.group(1) + "ENTOS", t2)
    return _EXTENSO.get(t2)


def _ok(nome: str, valor: Any, motivo: str = "", critico: bool = True, origem: str = "leitura") -> CampoLido:
    return CampoLido(nome=nome, valor=valor, status="ok", motivo=motivo, critico=critico, origem=origem)


def _ind(nome: str, motivo: str, critico: bool = True, valor_lido: Any = None) -> CampoLido:
    c = CampoLido(nome=nome, valor=None, status="indeterminado", motivo=motivo, critico=critico)
    if valor_lido not in (None, ""):
        from laudo.privacidade import mascarar_texto

        # chave lida com erro também embute o CPF/CNPJ do emitente: vai mascarada
        c.motivo = f"{motivo} (lido: {mascarar_texto(str(valor_lido))[:40]})"
    return c


def _doc(nome: str, bruto: Any, critico: bool = True) -> CampoLido:
    d = so_alnum(bruto)
    if not d:
        return _ind(nome, "ilegível ou ausente", critico)
    t = tipo_documento(d)
    ok = cnpj_valido(d) if t == "cnpj" else cpf_valido(d) if t == "cpf" else False
    if not ok:
        return _ind(nome, "CPF/CNPJ com dígito verificador inválido", critico, mascarar_documento(d))
    return _ok(nome, d, f"{t.upper()} com DV válido", critico)


def _parte_saida(doc: str | None, nome: str | None, uf: str | None = None, **extra: Any) -> dict[str, Any]:
    t = tipo_documento(doc) if doc else None
    return {"tipo_doc": t, "doc_mascarado": mascarar_documento(doc), "doc_sha256": hash_documento(doc),
            "nome": mascarar_nome(nome, t) if nome else None, "uf": uf, **extra}


def _uf(nome: str, bruto: Any, critico: bool = True) -> CampoLido:
    u = so_alnum(bruto)
    if not u:
        return _ind(nome, "ilegível ou ausente", critico)
    return _ok(nome, u, critico=critico) if u in CODIGO_UF else _ind(nome, "UF inexistente", critico, u)


def _texto(nome: str, bruto: Any, critico: bool = False) -> CampoLido:
    t = re.sub(r"\s+", " ", str(bruto or "")).strip()
    return _ok(nome, t, critico=critico) if t else _ind(nome, "ilegível ou ausente", critico)


def _pedido(campos: dict[str, CampoLido], tipo: str) -> str | None:
    falhos = [c for c in campos.values() if c.critico and c.status != "ok"]
    if not falhos:
        return None
    lista = "; ".join(f"{c.nome} ({c.motivo})" for c in falhos[:6])
    resto = f" e mais {len(falhos) - 6}" if len(falhos) > 6 else ""
    alvo = ("o quadro CHAVE DE ACESSO e a tabela DADOS DOS PRODUTOS" if tipo == "danfe"
            else "a grade de quantidades e os quadros de procedência e destino")
    return (f"Não validei: {lista}{resto}. Refaça a foto com o papel inteiro, de cima, sem sombra e sem dobra; "
            f"se continuar, aproxime de {alvo}. Nada disso foi aceito como lido.")


# ---------------------------------------------------------------------------
# DANFE
# ---------------------------------------------------------------------------


_UNANIMES_DANFE = ("data_emissao", "numero", "serie")  # sem dígito verificador próprio
# Posições (4 dígitos) da TEC nos capítulos 01 (animais vivos) e 02 (carnes): NCM lido fora delas é erro de
# leitura, não achado (Resolução Gecex 272/2021, capítulos 01 e 02).
_POSICOES_TEC = {"01": {"0101", "0102", "0103", "0104", "0105", "0106"},
                 "02": {f"02{x:02d}" for x in range(1, 11)}}
_UNANIMES_GTA = ("data_emissao", "validade", "origem.codigo_estabelecimento", "destino.codigo_estabelecimento")


def _exigir_unanimidade(c: dict[str, CampoLido], nomes: tuple[str, ...], concord: dict[str, str] | None) -> None:
    """Campo crítico sem dígito verificador (data, código do estabelecimento, número sem chave válida) só é
    aceito se TODAS as leituras concordaram: 2 de 3 não basta (erro consistente do VLM passa no formato)."""
    if not concord:
        return
    for nome in nomes:
        q = concord.get(nome) or ""
        m = re.fullmatch(r"(\d+)/(\d+)", q)
        if c.get(nome) is not None and c[nome].status == "ok" and c[nome].origem == "leitura" and m \
                and m.group(1) != m.group(2):
            # mantém a criticidade do campo (o município do emitente é não crítico)
            c[nome] = _ind(nome, f"campo sem dígito verificador e leituras não unânimes ({q})",
                           critico=c[nome].critico)


def validar_danfe(bruto: dict[str, Any], hoje: date, concord: dict[str, str] | None = None) -> ResultadoLeitura:
    """`bruto`: chave, numero, serie, data_emissao, tp_nf, emitente_doc, emitente_uf, emitente_nome,
    destinatario_doc, destinatario_uf, destinatario_nome, itens[{descricao, ncm, cfop, unidade, quantidade,
    valor_unitario, valor_total}], v_prod, v_nf (strings como impressos)."""
    c: dict[str, CampoLido] = {}
    # --- campos simples
    ch = so_alnum(bruto.get("chave"))
    ok_dv, motivo_dv = validar_chave(ch) if ch else (False, "ilegível ou ausente")
    c["chave"] = _ok("chave", ch, motivo_dv) if ok_dv else _ind("chave", motivo_dv, valor_lido=ch or None)
    num = digitos(bruto.get("numero"))
    c["numero"] = _ok("numero", int(num)) if num and len(num) <= 9 else _ind("numero", "ilegível ou fora do formato")
    ser = digitos(bruto.get("serie"))
    c["serie"] = _ok("serie", int(ser)) if ser and len(ser) <= 3 else _ind("serie", "ilegível ou fora do formato")
    d = data_br(bruto.get("data_emissao"))
    if d is None:
        c["data_emissao"] = _ind("data_emissao", "data ilegível ou inválida", valor_lido=bruto.get("data_emissao"))
    elif d > hoje:
        c["data_emissao"] = _ind("data_emissao", f"data futura em relação a {hoje:%d/%m/%Y}", valor_lido=bruto.get(
            "data_emissao"))
    elif d.year < 2006:  # NF-e modelo 55 começou em 2006
        c["data_emissao"] = _ind("data_emissao", "data anterior à NF-e", valor_lido=bruto.get("data_emissao"))
    else:
        c["data_emissao"] = _ok("data_emissao", d.isoformat())
    tp = str(bruto.get("tp_nf") or "").strip()
    c["tp_nf"] = _ok("tp_nf", tp) if tp in {"0", "1"} else _ind("tp_nf", "entrada/saída ilegível")
    c["emitente_doc"] = _doc("emitente_doc", bruto.get("emitente_doc"))
    c["destinatario_doc"] = _doc("destinatario_doc", bruto.get("destinatario_doc"))
    c["emitente_uf"] = _uf("emitente_uf", bruto.get("emitente_uf"))
    c["destinatario_uf"] = _uf("destinatario_uf", bruto.get("destinatario_uf"))
    c["emitente_nome"] = _texto("emitente_nome", bruto.get("emitente_nome"))
    c["destinatario_nome"] = _texto("destinatario_nome", bruto.get("destinatario_nome"))
    mun = re.sub(r"\s*[-/]\s*[A-Z]{2}$", "", sem_acento(bruto.get("emitente_municipio")))  # "NIQUELANDIA - GO"
    tabela = municipios_go()
    if not mun:
        c["emitente_municipio"] = _ind("emitente_municipio", "ilegível ou ausente", critico=False)
    elif tabela and so_alnum(bruto.get("emitente_uf")) in ("GO", "") and mun not in tabela.values():
        c["emitente_municipio"] = _ind("emitente_municipio", "município inexistente em GO", critico=False,
                                       valor_lido=mun)
    else:  # entra (quando lido) na conferência da origem da GTA (MAPA-SDA-BOV-item11)
        c["emitente_municipio"] = _ok("emitente_municipio", mun, critico=False)
    _exigir_unanimidade(c, ("data_emissao",), concord)

    # --- coerência da chave com os campos impressos (MOC 4.00, composição da chave)
    if c["chave"].status == "ok":
        k = decompor_chave(ch)
        conflitos: list[str] = []
        if k["c_uf"] not in UF_POR_CODIGO:
            conflitos.append("cUF")
        if k["modelo"] != "55":
            conflitos.append("modelo")
        if not 1 <= k["mes"] <= 12 or k["ano"] > hoje.year:
            conflitos.append("AAMM")
        if not (cnpj_valido(k["doc_emitente"]) or cpf_valido(k["doc_emitente"][3:])):
            conflitos.append("CNPJ/CPF embutido")
        comparacoes = (
            ("emitente_uf", lambda v: CODIGO_UF.get(v) == k["c_uf"]),
            ("data_emissao", lambda v: v[2:4] + v[5:7] == k["aamm"]),
            ("emitente_doc", lambda v: v.zfill(14) == k["doc_emitente"]),
            ("serie", lambda v: v == k["serie"]),
            ("numero", lambda v: v == k["numero"]),
        )
        for nome, confere in comparacoes:
            if c[nome].status == "ok" and not confere(c[nome].valor):
                conflitos.append(nome)
                c[nome] = _ind(nome, "não confere com a chave de acesso", valor_lido=c[nome].valor)
        if conflitos:
            c["chave"] = _ind("chave", f"DV ok, mas incoerente com {', '.join(conflitos)}")
        else:
            c["chave"].motivo = "DV módulo 11 válido e coerente com UF, AAMM, emitente, série e número"
            derivados = {"emitente_uf": UF_POR_CODIGO[k["c_uf"]], "serie": k["serie"], "numero": k["numero"]}
            doc_k = k["doc_emitente"]
            derivados["emitente_doc"] = doc_k[3:] if doc_k[:3] == "000" and cpf_valido(doc_k[3:]) else doc_k
            for nome, v in derivados.items():
                if c[nome].status != "ok" and "não confere" not in c[nome].motivo:
                    c[nome] = _ok(nome, v, "decomposto da chave com DV conferido", origem="derivado:chave")

    if c["chave"].status != "ok":  # sem chave válida, número e série não têm com o que conferir
        _exigir_unanimidade(c, ("numero", "serie"), concord)
    # documento das partes define "comprador = tomador" e "vendedor ≠ tomador": exige unanimidade (salvo o do
    # emitente decomposto da chave válida) e não pode ser o documento do emitente lido em outro lugar
    _exigir_unanimidade(c, ("destinatario_doc", "emitente_municipio")
                        + (() if c["chave"].status == "ok" else ("emitente_doc",)), concord)
    emit_cand = {so_alnum(bruto.get("emitente_doc")).zfill(14)} | ({ch[6:20]} if len(ch) == 44 else set())
    if c["destinatario_doc"].status == "ok" and c["destinatario_doc"].valor.zfill(14) in emit_cand:
        c["destinatario_doc"] = _ind("destinatario_doc", "igual ao CPF/CNPJ do emitente (leitura trocada?); "
                                     "confira o papel e peça o XML")
    # emitente e destinatário com o mesmo documento: leitura trocada OU NF emitida para si mesmo (MCR 2-7-6);
    # pela foto não dá para distinguir: pendente, com pedido do XML (nunca divergência só pela leitura)
    if (c["emitente_doc"].status == "ok" and c["destinatario_doc"].status == "ok"
            and c["emitente_doc"].valor == c["destinatario_doc"].valor):
        c["destinatario_doc"] = _ind("destinatario_doc", "igual ao CPF/CNPJ do emitente: leitura trocada ou NF "
                                     "emitida para si mesmo; confira o papel e peça o XML")
    # --- itens
    itens_ok: list[dict[str, Any]] = []
    itens_brutos = list(bruto.get("itens") or [])
    if not itens_brutos:
        c["itens"] = _ind("itens", "tabela de produtos ilegível ou vazia")
    soma, soma_ok = 0.0, True
    for i, it in enumerate(itens_brutos, 1):
        pref = f"item{i}"
        ncm = digitos(it.get("ncm"))
        if len(ncm) != 8 or not 1 <= int(ncm[:2]) <= 97:
            c[f"{pref}.ncm"] = _ind(f"{pref}.ncm", "NCM sem 8 dígitos", valor_lido=it.get("ncm"))
        elif ncm[:2] in _POSICOES_TEC and ncm[:4] not in _POSICOES_TEC[ncm[:2]]:
            c[f"{pref}.ncm"] = _ind(f"{pref}.ncm", f"posição {ncm[:4]} inexistente no capítulo {ncm[:2]} da TEC",
                                    valor_lido=ncm)
        else:
            c[f"{pref}.ncm"] = _ok(f"{pref}.ncm", ncm)
            if not ncm.startswith("0102"):  # fora de bovídeo vivo vira achado da conciliação: exige unanimidade
                _exigir_unanimidade(c, (f"{pref}.ncm",), {f"{pref}.ncm": (concord or {}).get(f"itens.{i - 1}.ncm", "")}
                                    if concord else None)
        cfop = digitos(it.get("cfop"))
        c[f"{pref}.cfop"] = (_ok(f"{pref}.cfop", cfop) if len(cfop) == 4 and cfop[0] in "123567"
                             else _ind(f"{pref}.cfop", "CFOP fora do formato", valor_lido=it.get("cfop")))
        un = so_alnum(it.get("unidade")) or ("@" if str(it.get("unidade") or "").strip() == "@" else "")
        c[f"{pref}.unidade"] = (_ok(f"{pref}.unidade", un) if un in UNIDADES_COMERCIAIS
                                else _ind(f"{pref}.unidade", "unidade não reconhecida", valor_lido=un))
        q, vu, vt = valor_br(it.get("quantidade")), valor_br(it.get("valor_unitario")), valor_br(it.get("valor_total"))
        nomes = (f"{pref}.quantidade", f"{pref}.valor_unitario", f"{pref}.valor_total")
        if None in (q, vu, vt) or not q:
            for nm, v, bv in zip(nomes, (q, vu, vt), ("quantidade", "valor_unitario", "valor_total"), strict=True):
                c[nm] = _ok(nm, v) if v else _ind(nm, "número ilegível ou fora do formato", valor_lido=it.get(bv))
            # sem a conta fechada, nenhum dos três é aceito
            for nm in nomes:
                if c[nm].status == "ok":
                    c[nm] = _ind(nm, "quantidade × valor unitário não conferível (outro campo ilegível)",
                                 valor_lido=c[nm].valor)
            soma_ok = False
        elif abs(q * vu - vt) > max(0.011, 0.005 * q + 0.011):
            for nm in nomes:
                c[nm] = _ind(nm, f"quantidade × valor unitário ({q:g} × {vu:.2f}) ≠ valor total ({vt:.2f})")
            soma_ok = False
        else:
            for nm, v in zip(nomes, (q, vu, vt), strict=True):
                c[nm] = _ok(nm, v, "quantidade × valor unitário = valor total")
            soma += vt
        c[f"{pref}.descricao"] = _texto(f"{pref}.descricao", it.get("descricao"))
        itens_ok.append({"descricao": c[f"{pref}.descricao"].valor, "ncm": c[f"{pref}.ncm"].valor,
                         "cfop": c[f"{pref}.cfop"].valor, "unidade": c[f"{pref}.unidade"].valor,
                         "quantidade": c[f"{pref}.quantidade"].valor,
                         "valor_unitario": c[f"{pref}.valor_unitario"].valor,
                         "valor_total": c[f"{pref}.valor_total"].valor})
    vp, vn = valor_br(bruto.get("v_prod")), valor_br(bruto.get("v_nf"))
    if vp is None:
        c["v_prod"] = _ind("v_prod", "valor total dos produtos ilegível", valor_lido=bruto.get("v_prod"))
    elif itens_brutos and soma_ok and abs(soma - vp) > 0.011:
        c["v_prod"] = _ind("v_prod", f"soma dos itens ({soma:.2f}) ≠ total dos produtos ({vp:.2f})")
        for i in range(1, len(itens_brutos) + 1):  # algum item foi lido errado, sem saber qual
            for nm in (f"item{i}.quantidade", f"item{i}.valor_unitario", f"item{i}.valor_total"):
                c[nm] = _ind(nm, "soma dos itens não fecha com o total dos produtos")
                itens_ok[i - 1][nm.split(".")[1]] = None
    else:
        c["v_prod"] = _ok("v_prod", vp, "soma dos itens confere" if itens_brutos and soma_ok else "")
        if not (itens_brutos and soma_ok):  # sem a soma dos itens, o total não tem com o que conferir
            _exigir_unanimidade(c, ("v_prod",), concord)
    c["v_nf"] = _ok("v_nf", vn, critico=False) if vn is not None else _ind("v_nf", "ilegível", critico=False)

    # --- UF × CFOP (5.xxx dentro do estado; 6.xxx entre estados)
    ue, ud = c["emitente_uf"], c["destinatario_uf"]
    if ue.status == "ok" and ud.status == "ok":
        for i in range(1, len(itens_brutos) + 1):
            cf = c[f"item{i}.cfop"]
            if cf.status == "ok" and cf.valor[0] in "56" and (cf.valor[0] == "5") != (ue.valor == ud.valor):
                for nm in ("emitente_uf", "destinatario_uf", f"item{i}.cfop"):
                    c[nm] = _ind(nm, "CFOP incoerente com as UFs lidas (uma das leituras está errada)")
                    if nm.endswith("cfop"):
                        itens_ok[i - 1]["cfop"] = None
    # entrada/saída ilegível: o 1º dígito do CFOP define (1-3 entrada; 5-7 saída; Convênio s/nº de 1970)
    cfs = {c[f"item{i}.cfop"].valor[0] for i in range(1, len(itens_brutos) + 1) if c[f"item{i}.cfop"].status == "ok"}
    if c["tp_nf"].status == "ok" and cfs and not cfs <= (set("123") if c["tp_nf"].valor == "0" else set("567")):
        c["tp_nf"] = _ind("tp_nf", "entrada/saída lida não confere com o CFOP")
    elif (c["tp_nf"].status != "ok" and "não confere" not in c["tp_nf"].motivo and cfs
          and (cfs <= set("123") or cfs <= set("567"))):
        c["tp_nf"] = _ok("tp_nf", "0" if cfs <= set("123") else "1", "1º dígito do CFOP", origem="derivado:cfop")
    # UF do destinatário ilegível: CFOP 5.xxx (operação interna) a faz igual à do emitente (decomposição da
    # regra do CFOP, não leitura)
    cfops = {c[f"item{i}.cfop"].valor for i in range(1, len(itens_brutos) + 1) if c[f"item{i}.cfop"].status == "ok"}
    if (c["destinatario_uf"].status != "ok" and "não confere" not in c["destinatario_uf"].motivo
            and "CFOP incoerente" not in c["destinatario_uf"].motivo and cfops and all(x[0] == "5" for x in cfops)
            and c["emitente_uf"].status == "ok"):
        c["destinatario_uf"] = _ok("destinatario_uf", c["emitente_uf"].valor, "CFOP 5.xxx: operação interna",
                                   origem="derivado:cfop")
    for i, it in enumerate(itens_ok, 1):
        for k2 in ("quantidade", "valor_unitario", "valor_total"):
            if c[f"item{i}.{k2}"].status != "ok":
                it[k2] = None

    r = ResultadoLeitura(tipo_documento="danfe", campos=c)
    v = {n: (x.valor if x.status == "ok" else None) for n, x in c.items()}
    k = decompor_chave(v["chave"]) if v["chave"] else None
    r.documento = {
        "tipo": "danfe", "chave": v["chave"], "numero": v["numero"], "serie": v["serie"],
        "c_uf": k["c_uf"] if k else CODIGO_UF.get(v["emitente_uf"] or ""), "modelo": "55" if k else None,
        "data_emissao": v["data_emissao"], "tp_nf": v["tp_nf"],
        "emitente": _parte_saida(v["emitente_doc"], v["emitente_nome"], v["emitente_uf"],
                                 municipio=v["emitente_municipio"]),
        "destinatario": _parte_saida(v["destinatario_doc"], v["destinatario_nome"], v["destinatario_uf"]),
        "itens": itens_ok, "v_prod": v["v_prod"], "v_nf": v["v_nf"],
        "ilegiveis": sorted(n for n, x in c.items() if x.critico and x.status != "ok"),
    }
    r.pedido_nova_foto = _pedido(c, "danfe")
    return r


# ---------------------------------------------------------------------------
# GTA
# ---------------------------------------------------------------------------


def _linhas_grade(linhas: list[str]) -> tuple[dict[str, tuple[int, int, int]], tuple[int, int, int] | None, str]:
    """Linhas "FAIXA | M | F | T" → {faixa: (m, f, t)} e a linha TOTAL. Devolve também o motivo de falha."""
    grade: dict[str, tuple[int, int, int]] = {}
    total = None
    for ln in linhas:
        partes = [p.strip() for p in re.split(r"\s*\|\s*", str(ln).strip().strip("|")) if p is not None]
        if len(partes) != 4:
            if any(x.strip() for x in partes):
                return {}, None, "linha da grade sem as 4 colunas (faixa | machos | fêmeas | total)"
            continue
        rot = sem_acento(partes[0]).replace(" ", "").replace("MESES", "")
        vals = [inteiro_celula(x) for x in partes[1:]]
        if None in vals:
            return {}, None, "célula da grade ilegível"
        trio = (vals[0], vals[1], vals[2])  # type: ignore[assignment]
        if rot.startswith("TOTA"):
            total = trio
        elif rot in FAIXAS or rot.replace("ACIMADE", ">").replace("+", ">") in FAIXAS:
            faixa = rot if rot in FAIXAS else rot.replace("ACIMADE", ">").replace("+", ">")
            if faixa in grade:
                return {}, None, f"faixa {faixa} repetida na grade"
            grade[faixa] = trio  # type: ignore[assignment]
        else:
            return {}, None, f"faixa etária não reconhecida ({partes[0][:12]})"
    return grade, total, ""


def _local(c: dict[str, CampoLido], lado: str, bruto: dict[str, Any]) -> None:
    c[f"{lado}.doc"] = _doc(f"{lado}.doc", bruto.get("doc"))
    c[f"{lado}.uf"] = _uf(f"{lado}.uf", bruto.get("uf"))
    ib = digitos(bruto.get("ibge"))
    nome = sem_acento(bruto.get("municipio"))
    tabela = municipios_go()
    if not ib:
        c[f"{lado}.ibge"] = _ind(f"{lado}.ibge", "código IBGE ilegível ou ausente")
    elif not ibge_dv_ok(ib):
        c[f"{lado}.ibge"] = _ind(f"{lado}.ibge", "código IBGE com DV inválido", valor_lido=ib)
    elif c[f"{lado}.uf"].status == "ok" and CODIGO_UF[c[f"{lado}.uf"].valor] != ib[:2]:
        c[f"{lado}.ibge"] = _ind(f"{lado}.ibge", "código IBGE de outra UF", valor_lido=ib)
        c[f"{lado}.uf"] = _ind(f"{lado}.uf", "UF não confere com o código IBGE")
    elif ib[:2] == "52" and tabela and ib not in tabela:
        c[f"{lado}.ibge"] = _ind(f"{lado}.ibge", "código IBGE inexistente em GO", valor_lido=ib)
    else:
        c[f"{lado}.ibge"] = _ok(f"{lado}.ibge", ib, "DV do código IBGE válido")
    if not nome:
        c[f"{lado}.municipio"] = _ind(f"{lado}.municipio", "ilegível ou ausente")
    elif c[f"{lado}.ibge"].status == "ok" and ib in tabela:
        if tabela[ib] == nome:
            c[f"{lado}.municipio"] = _ok(f"{lado}.municipio", nome, "nome confere com o código IBGE")
        else:
            c[f"{lado}.municipio"] = _ind(f"{lado}.municipio", "nome não confere com o código IBGE",
                                          valor_lido=nome)
            c[f"{lado}.ibge"] = _ind(f"{lado}.ibge", "código não confere com o nome do município", valor_lido=ib)
    elif tabela and nome not in tabela.values() and (ib[:2] == "52" or c[f"{lado}.uf"].valor in ("GO", None)):
        c[f"{lado}.municipio"] = _ind(f"{lado}.municipio", "município inexistente em GO", valor_lido=nome)
    else:
        c[f"{lado}.municipio"] = _ok(f"{lado}.municipio", nome)
    cod = re.sub(r"\s+", "", str(bruto.get("codigo_estabelecimento") or "")).upper()
    if re.fullmatch(r"\d{7}", cod) or cnpj_valido(cod) or cpf_valido(cod):  # IBGE ou CPF/CNPJ: campo vizinho
        cod = ""
    c[f"{lado}.codigo_estabelecimento"] = (_ok(f"{lado}.codigo_estabelecimento", cod) if len(cod) >= 4
                                           else _ind(f"{lado}.codigo_estabelecimento", "ilegível ou ausente"))
    c[f"{lado}.nome"] = _texto(f"{lado}.nome", bruto.get("nome"))
    c[f"{lado}.estabelecimento"] = _texto(f"{lado}.estabelecimento", bruto.get("estabelecimento"))


def validar_gta(bruto: dict[str, Any], hoje: date, concord: dict[str, str] | None = None) -> ResultadoLeitura:
    """`bruto`: uf, serie, numero, especie, linhas_quantidade[str], total_por_extenso, origem{...}, destino{...}
    (nome, doc, estabelecimento, codigo_estabelecimento, municipio, ibge, uf), finalidade, data_emissao,
    validade, local_emissao, chave_nfe."""
    c: dict[str, CampoLido] = {}
    c["uf_emissao"] = _uf("uf_emissao", bruto.get("uf"))
    num = digitos(bruto.get("numero"))
    c["numero"] = (_ok("numero", num) if re.fullmatch(r"\d{6}", num)
                   else _ind("numero", "número da GTA sem 6 dígitos", valor_lido=bruto.get("numero")))
    ser = sem_acento(bruto.get("serie")).replace(" ", "")
    c["serie"] = (_ok("serie", ser) if re.fullmatch(r"[A-Z]{1,2}", ser)
                  else _ind("serie", "série fora do padrão (1-2 letras)", valor_lido=ser))
    esp = sem_acento(bruto.get("especie"))
    c["especie"] = (_ok("especie", "bovina") if esp.startswith("BOVIN") else _ok("especie", "bubalina")
                    if esp.startswith(("BUBALIN", "BUFAL")) else _ind("especie", "espécie ilegível", valor_lido=esp))
    # --- quantidades: grade × linha TOTAL × total por extenso
    grade, tot, motivo = _linhas_grade(list(bruto.get("linhas_quantidade") or []))
    ext = extenso_para_int(bruto.get("total_por_extenso"))
    c["total_por_extenso"] = (_ok("total_por_extenso", ext) if ext is not None
                              else _ind("total_por_extenso", "total por extenso ilegível",
                                        valor_lido=bruto.get("total_por_extenso")))
    quantidades: list[dict[str, Any]] | None = None
    if motivo or tot is None:
        motivo = motivo or "linha TOTAL da grade ilegível"
        for nm in ("total", "total_machos", "total_femeas", "quantidades_por_faixa"):
            c[nm] = _ind(nm, motivo)
    else:
        tm, tf, tt = tot
        problemas = []
        if tm + tf != tt:
            problemas.append("machos + fêmeas ≠ total")
        if ext is None or ext != tt:
            problemas.append("total ≠ total por extenso")
        if problemas:
            for nm in ("total", "total_machos", "total_femeas", "quantidades_por_faixa"):
                c[nm] = _ind(nm, "; ".join(problemas))
        else:
            c["total"] = _ok("total", tt, "linha TOTAL = machos + fêmeas = total por extenso")
            c["total_machos"] = _ok("total_machos", tm)
            c["total_femeas"] = _ok("total_femeas", tf)
            faixa_ok = (bool(grade) and all(m + f == t for m, f, t in grade.values())
                        and sum(m for m, _, _ in grade.values()) == tm
                        and sum(f for _, f, _ in grade.values()) == tf)
            if faixa_ok:
                c["quantidades_por_faixa"] = _ok("quantidades_por_faixa",
                                                 {fx: [m, f] for fx, (m, f, _) in grade.items() if m or f},
                                                 "linhas somam a linha TOTAL", critico=False)
                quantidades = [{"sexo": s, "faixa_etaria": fx, "quantidade": q} for fx, (m, f, _) in grade.items()
                               for s, q in (("M", m), ("F", f)) if q]
            else:
                c["quantidades_por_faixa"] = _ind("quantidades_por_faixa", "linhas por faixa não somam a linha "
                                                  "TOTAL (totais por sexo aceitos)", critico=False)
                quantidades = [{"sexo": s, "faixa_etaria": "nao_lida", "quantidade": q}
                               for s, q in (("M", tm), ("F", tf)) if q]
    for lado in ("origem", "destino"):
        _local(c, lado, bruto.get(lado) or {})
    fin = sem_acento(bruto.get("finalidade")).replace(" ", "_")
    c["finalidade"] = (_ok("finalidade", fin) if fin in FINALIDADES_GTA
                       else _ind("finalidade", "finalidade não reconhecida", valor_lido=fin))
    de, dv = data_br(bruto.get("data_emissao")), data_br(bruto.get("validade"))
    if de is None:
        c["data_emissao"] = _ind("data_emissao", "data ilegível ou inválida", valor_lido=bruto.get("data_emissao"))
    elif de > hoje:
        c["data_emissao"] = _ind("data_emissao", "data de emissão futura", valor_lido=bruto.get("data_emissao"))
    else:
        c["data_emissao"] = _ok("data_emissao", de.isoformat())
    if dv is None:
        c["validade"] = _ind("validade", "data ilegível ou inválida", valor_lido=bruto.get("validade"))
    elif de is not None and not 0 <= (dv - de).days <= 30:
        c["validade"] = _ind("validade", "validade incoerente com a emissão (0 a 30 dias)")
        c["data_emissao"] = _ind("data_emissao", "emissão incoerente com a validade")
    else:
        c["validade"] = _ok("validade", dv.isoformat())
    chs = so_alnum(bruto.get("chave_nfe"))
    if not chs:
        c["chave_nfe"] = _ind("chave_nfe", "sem chave de NF-e vinculada legível", critico=False)
    else:
        ok, mot = validar_chave(chs)
        c["chave_nfe"] = _ok("chave_nfe", chs, mot, critico=False) if ok else _ind("chave_nfe", mot, critico=False)
    c["local_emissao"] = _texto("local_emissao", bruto.get("local_emissao"))
    _exigir_unanimidade(c, _UNANIMES_GTA, concord)
    c["emitente"] = _texto("emitente", bruto.get("emitente"))  # item 19: só presença (formato)

    r = ResultadoLeitura(tipo_documento="gta", campos=c)
    v = {n: (x.valor if x.status == "ok" else None) for n, x in c.items()}

    def loc(lado: str) -> dict[str, Any]:
        doc = v[f"{lado}.doc"]
        return {"documento_sha256": hash_documento(doc), "doc_mascarado": mascarar_documento(doc),
                "nome": mascarar_nome(v[f"{lado}.nome"], tipo_documento(doc)) if v[f"{lado}.nome"] else None,
                "estabelecimento": v[f"{lado}.estabelecimento"],
                "codigo_estabelecimento": v[f"{lado}.codigo_estabelecimento"],
                "municipio_nome": v[f"{lado}.municipio"], "municipio_ibge": v[f"{lado}.ibge"], "uf": v[f"{lado}.uf"]}

    r.documento = {
        "tipo": "gta", "uf_emissao": v["uf_emissao"], "numero": v["numero"], "serie": v["serie"],
        "especie": v["especie"], "quantidades": quantidades, "total": v["total"],
        "total_por_extenso": bruto.get("total_por_extenso") if v["total_por_extenso"] is not None else None,
        "origem": loc("origem"), "destino": loc("destino"), "finalidade": v["finalidade"],
        "emissao": {"data": v["data_emissao"], "validade": v["validade"], "local_municipio": v["local_emissao"]},
        "nfe_chaves": [v["chave_nfe"]] if v["chave_nfe"] else [],
        "emitente": v["emitente"],
        "observacao": (str(bruto.get("observacoes") or "").strip() or None),  # ex.: "CARGA 1 DE 2" (item 17)
        "ilegiveis": sorted(n for n, x in c.items() if x.critico and x.status != "ok"),
    }
    r.pedido_nova_foto = _pedido(c, "gta")
    return r


# ---------------------------------------------------------------------------
# Autoconsistência: consenso campo a campo entre k leituras (antes da validação)
# ---------------------------------------------------------------------------

_NUMERICOS = {"quantidade", "valor_unitario", "valor_total", "v_prod", "v_nf"}
_DIGITOS = {"numero", "ncm", "cfop", "ibge"}
_ALFANUM = {"chave", "chave_nfe", "doc", "emitente_doc", "destinatario_doc"}  # CNPJ pode ser alfanumérico
_DATAS = {"data_emissao", "validade"}
_NAO_VOTADOS = {"informacoes_complementares", "observacoes"}  # só para a varredura de injeção (POL-06)


def _canon(chave: str, v: Any) -> str:
    folha = chave.rsplit(".", 1)[-1]
    if v is None:
        return ""
    s = str(v).strip()
    if not s:
        return ""
    if folha in _NUMERICOS:
        x = valor_br(s)
        return f"{x:.4f}" if x is not None else "?" + s
    if folha in _DATAS:
        d = data_br(s)
        return d.strftime("%d/%m/%Y") if d else "?" + s
    if folha in _DIGITOS:
        return digitos(s) or "?" + s
    if folha in _ALFANUM:
        return so_alnum(s) or "?" + s
    return sem_acento(s)


def _reconstruir(chave: str, canon: str) -> str:
    folha = chave.rsplit(".", 1)[-1]
    if canon.startswith("?"):
        return canon[1:]
    if folha in _NUMERICOS:
        return canon.replace(".", ",")
    return canon


def _achatar(d: Any, pref: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(_achatar(v, f"{pref}{k}."))
    elif isinstance(d, list) and pref.rstrip(".") == "itens":
        for i, v in enumerate(d):
            out.update(_achatar(v, f"{pref}{i}."))
    else:
        out[pref.rstrip(".")] = d
    return out


def _grade_canon(linhas: Any) -> tuple[str, str]:
    """Linhas da grade da GTA → (faixas canônicas, linha TOTAL canônica)."""
    faixas, total = [], ""
    for ln in linhas or []:
        partes = [p.strip() for p in re.split(r"\s*\|\s*", str(ln).strip().strip("|"))]
        if len(partes) != 4:
            if any(partes):
                faixas.append("?" + "|".join(partes))
            continue
        rot = sem_acento(partes[0]).replace(" ", "").replace("MESES", "")
        vals = [inteiro_celula(x) for x in partes[1:]]
        cel = "|".join("?" if x is None else str(x) for x in vals)
        if rot.startswith("TOTA"):
            total = f"TOTAL|{cel}"
        else:
            faixas.append(f"{rot}|{cel}")
    return ";".join(sorted(faixas)), total


def _voto_posicional(valores: list[str], minimo: int) -> str | None:
    """Maioria por posição entre leituras de mesmo comprimento; None se alguma posição não tiver maioria."""
    if any(v.startswith("?") for v in valores):
        return None
    por_tam: dict[int, list[str]] = {}
    for v in valores:
        por_tam.setdefault(len(v), []).append(v)
    tam, grupo = max(por_tam.items(), key=lambda kv: len(kv[1]))
    if len(grupo) < minimo or list(map(len, por_tam.values())).count(len(grupo)) > 1:
        return None
    saida = []
    for i in range(tam):
        cont: dict[str, int] = {}
        for v in grupo:
            cont[v[i]] = cont.get(v[i], 0) + 1
        ch, q = max(cont.items(), key=lambda kv: kv[1])
        if q < minimo or list(cont.values()).count(q) > 1:
            return None
        saida.append(ch)
    return "".join(saida)


def consenso(brutos: list[dict[str, Any]], minimo: int = 2) -> tuple[dict[str, Any], dict[str, str]]:
    """Consenso campo a campo entre leituras independentes do mesmo documento.

    Um campo só tem valor se ao menos `minimo` leituras devolveram o mesmo valor canônico (dígitos, número,
    data ou texto sem acento); se as leituras discordam, o campo fica vazio e marcado como "discordante" (a
    validação o torna indeterminado). Devolve (bruto de consenso, concordância por campo)."""
    planos = []
    for b in brutos:
        b = dict(b)
        if "linhas_quantidade" in b:
            b["grade_faixas"], b["grade_total"] = _grade_canon(b.pop("linhas_quantidade"))
        planos.append(_achatar(b))
    caminhos = sorted({c for p in planos for c in p})
    saida: dict[str, Any] = {}
    concord: dict[str, str] = {}
    n = len(planos)
    for c in caminhos:
        folha = c.rsplit(".", 1)[-1]
        if folha in _NAO_VOTADOS:  # texto livre: a transcrição mais longa (a varredura de injeção usa todas)
            saida[c] = max((str(p.get(c) or "").strip() for p in planos), key=len, default="")
            continue
        if folha in ("grade_faixas", "grade_total"):
            valores = [str(p.get(c) or "") for p in planos]
        else:
            valores = [_canon(c, p.get(c)) for p in planos]
        cont: dict[str, int] = {}
        for v in valores:
            if v:
                cont[v] = cont.get(v, 0) + 1
        if not cont:
            concord[c] = f"0/{n}"
            saida[c] = ""
            continue
        melhor, q = max(cont.items(), key=lambda kv: kv[1])
        if q >= minimo and list(cont.values()).count(q) == 1:
            concord[c] = f"{q}/{n}"
            saida[c] = melhor if folha in ("grade_faixas", "grade_total") else _reconstruir(c, melhor)
        elif folha in _ALFANUM and (pos := _voto_posicional([v for v in valores if v], minimo)):
            # chave/CPF/CNPJ: maioria caractere a caractere (cada leitura erra num lugar diferente); o resultado
            # ainda passa pelo DV e pela coerência na validação
            concord[c] = f"posicional {minimo}/{n}"
            saida[c] = pos
        else:
            concord[c] = "discordante"
            saida[c] = ""
    # desachata
    bruto: dict[str, Any] = {}
    itens: dict[int, dict[str, Any]] = {}
    for c, v in saida.items():
        partes = c.split(".")
        if partes[0] == "itens" and len(partes) == 3:
            itens.setdefault(int(partes[1]), {})[partes[2]] = v
        elif len(partes) == 2:
            bruto.setdefault(partes[0], {})[partes[1]] = v
        else:
            bruto[c] = v
    if itens:
        bruto["itens"] = [itens[i] for i in sorted(itens) if any(itens[i].values())]
    if "grade_faixas" in bruto or "grade_total" in bruto:
        linhas = []
        for ln in (bruto.pop("grade_faixas", "") or "").split(";"):
            if ln and not ln.startswith("?"):
                linhas.append(" | ".join(ln.split("|")))
        tot = bruto.pop("grade_total", "")
        if tot:
            linhas.append(" | ".join(tot.split("|")))
        bruto["linhas_quantidade"] = linhas
    return bruto, concord


_MAPA_CAMPO = {"grade_total": ("total", "total_machos", "total_femeas"), "grade_faixas": ("quantidades_por_faixa",),
               "uf": ("uf_emissao",), "v_prod": ("v_prod",)}


def aplicar_concordancia(r: ResultadoLeitura, concord: dict[str, str]) -> ResultadoLeitura:
    """Anota a concordância em cada campo e explica os indeterminados que vieram de leituras discordantes."""
    for caminho, q in concord.items():
        partes = caminho.split(".")
        if partes[0] == "itens" and len(partes) == 3:
            nomes: tuple[str, ...] = (f"item{int(partes[1]) + 1}.{partes[2]}",)
        elif caminho in _MAPA_CAMPO:
            nomes = _MAPA_CAMPO[caminho]
        else:
            nomes = (caminho,)
        for nome in nomes:
            campo = r.campos.get(nome)
            if campo is None:
                continue
            campo.concordancia = q
            if q == "discordante" and campo.status != "ok":
                campo.motivo = "as leituras independentes discordam (autoconsistência)"
    r.pedido_nova_foto = _pedido(r.campos, r.tipo_documento)
    return r


# ---------------------------------------------------------------------------
# Várias fotos do mesmo documento (refazer a foto): mescla campo a campo
# ---------------------------------------------------------------------------


def _ident(doc: dict[str, Any]) -> str | None:
    """Identidade do documento: chave da NF-e (ou número, sem chave legível); número da GTA (6 dígitos; a série
    sozinha não distingue duas cargas)."""
    if doc.get("tipo") == "gta":
        return f"gta:{doc['numero']}" if doc.get("numero") else None
    if doc.get("chave"):
        return doc["chave"]
    return f"nf:{doc['numero']}" if doc.get("numero") else None


def _mesclar_dois(a: Any, b: Any) -> Any:
    """Valor aceito em uma leitura e ausente na outra: fica. Aceito nas duas com valores diferentes: some
    (vira indeterminado). Listas de itens e partes são mescladas por posição/chave."""
    if a is None:
        return b
    if b is None:
        return a
    if isinstance(a, dict) and isinstance(b, dict):
        return {k: _mesclar_dois(a.get(k), b.get(k)) for k in dict.fromkeys([*a, *b])}
    if isinstance(a, list) and isinstance(b, list) and all(isinstance(x, dict) for x in a + b):
        if len(a) != len(b):
            return None
        return [_mesclar_dois(x, y) for x, y in zip(a, b, strict=True)]
    return a if a == b else None


def mesclar_leituras(docs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Leituras do mesmo documento (mesma chave da NF-e ou mesma série+número da GTA) viram uma só; leitura sem
    identificador vai para o único documento identificado (se houver só um) e, havendo vários, é descartada
    com alerta (não dá para saber de qual é; somar seria contar o mesmo lote duas vezes)."""
    grupos: dict[str, list[dict[str, Any]]] = {}
    sem_id: list[dict[str, Any]] = []
    for d in docs:
        k = _ident(d)
        (grupos.setdefault(k, []) if k else sem_id).append(d)
    alertas = []
    if sem_id:
        if len(grupos) <= 1:
            k = next(iter(grupos), "_sem_id")
            grupos.setdefault(k, []).extend(sem_id)
        else:
            alertas.append(f"{len(sem_id)} leitura(s) sem chave/número descartada(s): há {len(grupos)} documentos "
                           "identificados e não dá para saber de qual são; refaça a foto")
    saida = []
    for lista in grupos.values():
        m = lista[0]
        for d in lista[1:]:
            ileg = sorted(set(m.get("ilegiveis") or []) & set(d.get("ilegiveis") or []))
            m = {**_mesclar_dois(m, d), "ilegiveis": ileg, "tipo": m.get("tipo")}
        saida.append(m)
    return saida, alertas
