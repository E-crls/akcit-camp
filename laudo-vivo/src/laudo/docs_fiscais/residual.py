"""Residual da leitura por foto: o que o VLM não validou, a fiscal completa — e o código confere antes de aceitar.

Quando `ler_documento_foto` deixa campos críticos `indeterminado`, o agente não pede o documento inteiro de novo:
pede **só esses campos**, com instrução específica ("leia os 4 últimos dígitos da chave de acesso"; "diga a
quantidade de cabeças da nota, o valor unitário e o valor total da linha 1"), por voz ou digitação. A resposta
passa pelas **mesmas regras determinísticas** da leitura (`leitura.validar_danfe` / `validar_gta`): DV da chave
e coerência com UF, AAMM, série e número; DV de CPF/CNPJ; quantidade × unitário = total; soma dos itens = total
dos produtos; machos + fêmeas = total; DV e nome do código IBGE; datas. Só o que valida é aceito, com a
proveniência **"lido de foto e completado pela fiscal"**; o que não valida volta para um novo pedido (até
`MAX_TENTATIVAS`) e, depois disso, fica pendente com pedido do XML/e-GTA. Nada é "corrigido" nem chutado.

Privacidade: CPF/CNPJ só por digitação (o pedido diz isso) e, como na leitura, saem só como máscara + hash. Os
documentos já aceitos na leitura não são reconstituídos (a trilha só guarda máscara + hash): a coerência com a
chave e "emitente ≠ destinatário" são conferidas pelo hash (`comum.hash_documento`).

Chave de acesso: as posições que outros campos validados determinam (cUF pela UF, AAMM pela data, modelo 55, série
e número) e as que todas as leituras do VLM concordam ficam; só os grupos de 4 dígitos (o DANFE imprime a chave em
11 grupos) com posição incerta são pedidos. Se mais de 4 grupos estão incertos, pede a chave inteira (digitação).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from laudo.docs_fiscais import leitura as L
from laudo.docs_fiscais.comum import hash_documento, mascarar_documento, so_alnum

MAX_TENTATIVAS = 3
MAX_CAMPOS_POR_PEDIDO = 6  # acima disso, a foto está ruim demais: o pedido sugere refazer a foto primeiro
PROVENIENCIA = "lido de foto e completado pela fiscal"
FERRAMENTA = "completar_leitura_documento"
VERSAO = "residual@0.1.0"
_DOCS = ("emitente_doc", "destinatario_doc", "origem.doc", "destino.doc")

Formato = Literal["digitos", "numero", "data", "uf", "texto", "documento", "municipio", "finalidade", "especie",
                  "serie_gta", "tp_nf", "grade"]


class PedidoCampo(BaseModel):
    """Um campo (ou grupo de campos validados juntos) que a fiscal precisa ler do papel."""

    campos: list[str]  # nomes canônicos da leitura (ex.: ["chave"], ["item1.quantidade", ...])
    rotulo: str
    instrucao: str
    formato: Formato
    modo: Literal["voz_ou_digitacao", "digitacao"] = "voz_ou_digitacao"
    n_digitos: int | None = None  # dígitos esperados (chave parcial, número da GTA)
    blocos_chave: list[int] = Field(default_factory=list)  # grupos de 4 dígitos da chave pedidos (1 a 11)
    base_chave: str | None = None  # chave com "?" nas posições pedidas
    # campo sem dígito verificador digitado (código do estabelecimento): dupla digitação, as duas têm de conferir
    confirmar: bool = False


class PedidoResidual(BaseModel):
    tipo_documento: Literal["danfe", "gta"]
    tentativa: int = 1
    campos: list[PedidoCampo] = Field(default_factory=list)
    refazer_foto: bool = False
    texto: str = ""

    @property
    def nomes(self) -> list[str]:
        return [n for c in self.campos for n in c.campos]


# ---------------------------------------------------------------------------
# Leitura (saída de `ler_documento_foto`) ↔ valores
# ---------------------------------------------------------------------------


def _ok(campos: dict[str, dict[str, Any]], nome: str) -> bool:
    c = campos.get(nome) or {}
    return c.get("status") == "ok"


def _valor(campos: dict[str, dict[str, Any]], nome: str) -> Any:
    c = campos.get(nome) or {}
    return c.get("valor") if c.get("status") == "ok" else None


def _br(v: float, casas: int = 2) -> str:
    return f"{v:,.{casas}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def impresso(campo: str, v: Any) -> str:
    """Valor (no espaço dos campos validados) → como aparece no papel (o que `validar_*` lê)."""
    if v is None:
        return ""
    folha = campo.rsplit(".", 1)[-1]
    if folha in ("data_emissao", "validade"):
        partes = str(v)[:10].split("-")
        if len(partes) != 3:
            return str(v)
        a, m, d = partes
        return f"{d}/{m}/{a}"
    if folha in ("valor_unitario", "valor_total", "v_prod", "v_nf"):
        return _br(float(v))
    if folha == "quantidade":
        return _br(float(v), 0) if float(v).is_integer() else _br(float(v), 4)
    if campo == "numero" and isinstance(v, int):
        return f"{v:09d}"
    if campo == "serie" and isinstance(v, int):
        return f"{v:03d}"
    return str(v)


def bruto_de_campos(tipo: str, v: dict[str, Any]) -> dict[str, Any]:
    """Valores por campo (aceitos, digitados ou verdadeiros) → dicionário "como impresso" para
    `leitura.validar_danfe` / `validar_gta`. Também usado pela avaliação (A/B v2)."""
    if tipo == "danfe":
        idx = [int(k[4:k.index(".")]) for k in v if k.startswith("item") and "." in k and k[4:k.index(".")].isdigit()]
        itens = [{"descricao": v.get(f"item{i}.descricao") or "ITEM",
                  **{f: impresso(f, v.get(f"item{i}.{f}")) for f in ("ncm", "cfop", "unidade", "quantidade",
                                                                       "valor_unitario", "valor_total")}}
                 for i in range(1, 1 + max(idx or [0]))]
        b = {k: impresso(k, v.get(k)) for k in ("chave", "numero", "serie", "data_emissao", "tp_nf", "emitente_doc",
                                                "destinatario_doc", "emitente_uf", "destinatario_uf", "v_prod")}
        b.update(itens=itens, v_nf=impresso("v_nf", v.get("v_nf")) or b["v_prod"],
                 emitente_nome=v.get("emitente_nome") or "X", destinatario_nome=v.get("destinatario_nome") or "X",
                 emitente_municipio=v.get("emitente_municipio") or "")
        return b
    q = v.get("quantidades_por_faixa") or {}
    linhas = [f"{fx} | {m or '-'} | {f or '-'} | {(m + f) or '-'}" for fx, (m, f) in q.items()]
    for fx in L.FAIXAS:
        if fx not in q and q:
            linhas.append(f"{fx} | - | - | -")
    tot = v.get("total")
    if tot is not None and v.get("total_machos") is not None and v.get("total_femeas") is not None:
        linhas.append(f"TOTAL | {v['total_machos']} | {v['total_femeas']} | {tot}")
    ext = v.get("total_por_extenso")
    if ext is None and tot is not None:
        ext = tot
    from laudo.docs_fiscais.sintetico import por_extenso

    def loc(lado: str) -> dict[str, Any]:
        return {"nome": v.get(f"{lado}.nome") or "X", "doc": v.get(f"{lado}.doc") or "",
                "estabelecimento": v.get(f"{lado}.estabelecimento") or "X",
                "codigo_estabelecimento": v.get(f"{lado}.codigo_estabelecimento") or "",
                "municipio": v.get(f"{lado}.municipio") or "", "ibge": v.get(f"{lado}.ibge") or "",
                "uf": v.get(f"{lado}.uf") or ""}

    return {"uf": v.get("uf_emissao") or "", "serie": v.get("serie") or "", "numero": v.get("numero") or "",
            "especie": v.get("especie") or "", "linhas_quantidade": linhas,
            "total_por_extenso": por_extenso(int(ext)) if isinstance(ext, (int, float)) and 0 <= ext < 1000 else "",
            "origem": loc("origem"), "destino": loc("destino"), "finalidade": v.get("finalidade") or "",
            "data_emissao": impresso("data_emissao", v.get("data_emissao")),
            "validade": impresso("validade", v.get("validade")), "local_emissao": v.get("local_emissao") or "X",
            "chave_nfe": v.get("chave_nfe") or "", "emitente": v.get("emitente") or "X",
            "observacoes": v.get("observacao") or ""}


def criticos_indeterminados(leitura: dict[str, Any]) -> list[str]:
    return [n for n, c in (leitura.get("campos") or {}).items() if c.get("critico", True) and c.get("status") != "ok"]


# ---------------------------------------------------------------------------
# Pedido
# ---------------------------------------------------------------------------

_ROTULO_DANFE = {
    "numero": ("o número da nota (Nº, no alto à direita)", "digitos"),
    "serie": ("a série da nota (SÉRIE, ao lado do número)", "digitos"),
    "data_emissao": ("a data de emissão (quadro DATA DA EMISSÃO)", "data"),
    "tp_nf": ("o dígito do quadro ENTRADA/SAÍDA (0 ou 1)", "tp_nf"),
    "emitente_uf": ("a UF do emitente", "uf"),
    "destinatario_uf": ("a UF do destinatário", "uf"),
    "emitente_doc": ("o CNPJ/CPF do emitente", "documento"),
    "destinatario_doc": ("o CNPJ/CPF do destinatário", "documento"),
    "v_prod": ("o V. TOTAL PRODUTOS (quadro CÁLCULO DO IMPOSTO)", "numero"),
}
_ROTULO_GTA = {
    "uf_emissao": ("a UF da GTA (quadro do canto superior direito)", "uf"),
    "numero": ("o número da GTA (6 dígitos, canto superior direito)", "digitos"),
    "serie": ("a série da GTA (a letra depois de SÉRIE)", "serie_gta"),
    "especie": ("a espécie (item 01)", "especie"),
    "finalidade": ("a finalidade (item 13)", "finalidade"),
    "data_emissao": ("a data de emissão (item 20)", "data"),
    "validade": ("a data de validade (item 20, VÁLIDA ATÉ)", "data"),
    "total_por_extenso": ("o total por extenso (item 10)", "numero"),
}


# Posições da chave determinadas por outros campos (MOC 4.00, composição da chave de acesso).
_POS_DERIVADAS = {"emitente_uf": (0, 2), "data_emissao": (2, 6), "emitente_doc": (6, 20), "serie": (22, 25),
                  "numero": (25, 34)}


def _derivar_posicoes(valores: dict[str, Any]) -> dict[int, str]:
    """Posição → dígito, a partir dos campos que compõem a chave (UF → cUF, data → AAMM, série, número)."""
    out: dict[int, str] = {20: "5", 21: "5"}  # modelo 55
    uf, data = valores.get("emitente_uf"), valores.get("data_emissao")
    serie, numero = valores.get("serie"), valores.get("numero")
    if uf in L.CODIGO_UF:
        out.update({0: L.CODIGO_UF[uf][0], 1: L.CODIGO_UF[uf][1]})
    if isinstance(data, str) and re.match(r"\d{4}-\d{2}", data):
        out.update(dict(zip(range(2, 6), data[2:4] + data[5:7], strict=True)))
    if isinstance(serie, int) and 0 <= serie < 1000:
        out.update(dict(zip(range(22, 25), f"{serie:03d}", strict=True)))
    if isinstance(numero, int) and 0 <= numero < 10**9:
        out.update(dict(zip(range(25, 34), f"{numero:09d}", strict=True)))
    doc = so_alnum(str(valores.get("emitente_doc") or ""))  # só o documento em claro (digitado pela fiscal)
    if len(doc) in (11, 14):
        out.update(dict(zip(range(6, 20), doc.zfill(14), strict=True)))
    return out


def _blocos_incertos(leitura: dict[str, Any], faltam: list[str]) -> tuple[list[int], str]:
    """Grupos de 4 dígitos (1 a 11) da chave que a fiscal precisa ler e a chave-base: dígito conhecido, "d" para
    posição que sai de um campo que também está sendo pedido (montada na completação) e "?" para ler."""
    campos = leitura.get("campos") or {}
    pos = ["?"] * 44
    lidas = [so_alnum(str(b.get("chave") or "")) for b in leitura.get("leituras_brutas") or []]
    lidas = [x for x in lidas if len(x) == 44 and x.isdigit()]
    if len(lidas) >= 2:  # posições em que todas as leituras do VLM concordam
        for i in range(44):
            col = {x[i] for x in lidas}
            if len(col) == 1:
                pos[i] = col.pop()
    for nome, (a, b) in _POS_DERIVADAS.items():  # campo pedido agora: a posição vem da resposta dele
        if nome in faltam and nome != "emitente_doc":  # o documento só por digitação: pode não vir
            pos[a:b] = ["d"] * (b - a)
    for i, dig in _derivar_posicoes({n: _valor(campos, n) for n in _POS_DERIVADAS}).items():
        pos[i] = dig  # campo validado prevalece sobre o VLM
    base = "".join(pos)
    # os 3 últimos grupos (fim do número, tipo de emissão, código numérico aleatório e DV) são sempre lidos pela
    # fiscal: o VLM tende a errar igual nas leituras, e duas posições erradas passam no DV 1 vez em 11
    blocos = sorted({b for b in range(1, 12) if "?" in base[4 * (b - 1):4 * b]} | {9, 10, 11})
    return blocos, base


def _pedido_chave(leitura: dict[str, Any], faltam: list[str], tentativa: int = 1) -> PedidoCampo:
    blocos, base = _blocos_incertos(leitura, faltam)
    if len(blocos) > 4 or tentativa > 1:  # muitos grupos incertos, ou a montagem parcial já falhou: chave inteira
        return PedidoCampo(campos=["chave"], rotulo="chave de acesso", formato="digitos", modo="voz_ou_digitacao",
                           n_digitos=44, blocos_chave=list(range(1, 12)), base_chave="?" * 44,
                           instrucao="leia a chave de acesso inteira (44 dígitos, de 4 em 4) ou digite-a")
    marcada = list(base)
    for b in blocos:
        marcada[4 * (b - 1):4 * b] = list("????")
    n = 4 * len(blocos)
    if blocos == list(range(12 - len(blocos), 12)):
        instr = f"leia os {n} últimos dígitos da chave de acesso"
    elif len(blocos) == 1:
        instr = f"leia o {blocos[0]}º grupo de 4 dígitos da chave de acesso (conte da esquerda)"
    else:
        lista = ", ".join(f"{b}º" for b in blocos[:-1]) + f" e {blocos[-1]}º"
        instr = f"leia o {lista} grupos de 4 dígitos da chave de acesso (conte da esquerda)"
    return PedidoCampo(campos=["chave"], rotulo="chave de acesso", formato="digitos", n_digitos=n,
                       blocos_chave=blocos, base_chave="".join(marcada), instrucao=instr)


def _pedidos_danfe(leitura: dict[str, Any], faltam: list[str], tentativa: int = 1) -> list[PedidoCampo]:
    out: list[PedidoCampo] = []
    resto = list(faltam)
    if "chave" in resto:
        out.append(_pedido_chave(leitura, faltam, tentativa))
        resto.remove("chave")
    itens: dict[str, list[str]] = {}
    for n in list(resto):
        m = re.fullmatch(r"(item\d+)\.(\w+)", n)
        if m:
            itens.setdefault(m.group(1), []).append(n)
            resto.remove(n)
    for item, nomes in itens.items():
        linha = item[4:]
        valores = [x for x in nomes if x.rsplit(".", 1)[1] in ("quantidade", "valor_unitario", "valor_total")]
        if valores:
            # a conta fecha junto: os três são pedidos juntos (só a quantidade não basta para validar)
            trio = [f"{item}.quantidade", f"{item}.valor_unitario", f"{item}.valor_total"]
            out.append(PedidoCampo(campos=trio, rotulo=f"quantidade e valores da linha {linha}", formato="numero",
                                   instrucao=(f"diga a quantidade, o valor unitário e o valor total da linha {linha} "
                                              "da tabela DADOS DOS PRODUTOS")))
        for x in nomes:
            folha = x.rsplit(".", 1)[1]
            if folha == "ncm":
                out.append(PedidoCampo(campos=[x], rotulo=f"NCM da linha {linha}", formato="digitos", n_digitos=8,
                                       instrucao=f"leia o NCM/SH da linha {linha} (8 dígitos)"))
            elif folha == "cfop":
                out.append(PedidoCampo(campos=[x], rotulo=f"CFOP da linha {linha}", formato="digitos", n_digitos=4,
                                       instrucao=f"leia o CFOP da linha {linha} (4 dígitos)"))
            elif folha == "unidade":
                out.append(PedidoCampo(campos=[x], rotulo=f"unidade da linha {linha}", formato="texto",
                                       instrucao=f"diga a unidade (UNID) da linha {linha}, por exemplo CB ou UN"))
    for n in resto:
        if n == "itens":
            continue  # tabela ilegível: só uma foto nova (ou o XML) resolve
        rot, fmt = _ROTULO_DANFE.get(n, (n, "texto"))
        out.append(PedidoCampo(campos=[n], rotulo=rot, formato=fmt,  # type: ignore[arg-type]
                               modo="digitacao" if n in _DOCS else "voz_ou_digitacao",
                               instrucao=("digite " if n in _DOCS else "diga ") + rot))
    return out


def _pedidos_gta(leitura: dict[str, Any], faltam: list[str]) -> list[PedidoCampo]:
    out: list[PedidoCampo] = []
    resto = list(faltam)
    totais = [n for n in ("total", "total_machos", "total_femeas") if n in resto]
    if totais:
        out.append(PedidoCampo(campos=["total", "total_machos", "total_femeas"], rotulo="linha TOTAL da grade",
                               formato="grade", instrucao=("diga a linha TOTAL da grade (item 01): o total de "
                                                           "cabeças, quantos machos e quantas fêmeas")))
        resto = [n for n in resto if n not in ("total", "total_machos", "total_femeas", "quantidades_por_faixa",
                                               "total_por_extenso")]
    for lado, rot_lado in (("origem", "da procedência (item 11)"), ("destino", "do destino (item 12)")):
        loc = [n for n in resto if n.startswith(lado + ".")]
        if any(n.endswith((".municipio", ".ibge", ".uf")) for n in loc):
            out.append(PedidoCampo(campos=[f"{lado}.municipio", f"{lado}.ibge", f"{lado}.uf"],
                                   rotulo=f"município {rot_lado}", formato="municipio",
                                   instrucao=(f"diga o município {rot_lado} e, se não for de Goiás, o código IBGE "
                                              "(7 dígitos)")))
        if f"{lado}.codigo_estabelecimento" in loc:
            out.append(PedidoCampo(campos=[f"{lado}.codigo_estabelecimento"],
                                   rotulo=f"código do estabelecimento {rot_lado}", formato="texto",
                                   modo="digitacao", confirmar=True,
                                   instrucao=(f"digite duas vezes o código do estabelecimento {rot_lado} (não tem "
                                              "dígito verificador)")))
        if f"{lado}.doc" in loc:
            out.append(PedidoCampo(campos=[f"{lado}.doc"], rotulo=f"CPF/CNPJ {rot_lado}", formato="documento",
                                   modo="digitacao", instrucao=f"digite o CPF/CNPJ {rot_lado}"))
        resto = [n for n in resto if not n.startswith(lado + ".")]
    for n in resto:
        rot, fmt = _ROTULO_GTA.get(n, (n, "texto"))
        out.append(PedidoCampo(campos=[n], rotulo=rot, formato=fmt,  # type: ignore[arg-type]
                               n_digitos=6 if n == "numero" else None, instrucao=f"diga {rot}"))
    return out


# Recusa que não é erro de leitura (o papel diz isso mesmo): não adianta pedir de novo à fiscal; só o XML resolve.
_NAO_E_LEITURA = ("igual ao CPF/CNPJ do emitente",)


def pedido_residual(leitura: dict[str, Any], tentativa: int = 1) -> PedidoResidual | None:
    """Pedido dos campos críticos que a leitura não validou (None se não falta nada ou não é DANFE/GTA). Campo que
    a fiscal já leu e que falhou por motivo que não é de leitura (ex.: comprador = vendedor no papel) não é pedido
    de novo."""
    tipo = leitura.get("tipo_documento")
    if tipo not in ("danfe", "gta") or not leitura.get("campos") or tentativa > MAX_TENTATIVAS:
        return None
    campos_l = leitura.get("campos") or {}
    faltam = [n for n in criticos_indeterminados(leitura)
              if not (tentativa > 1 and any(m in str((campos_l.get(n) or {}).get("motivo")) for m in _NAO_E_LEITURA))]
    if not faltam:
        return None
    campos = _pedidos_danfe(leitura, faltam, tentativa) if tipo == "danfe" else _pedidos_gta(leitura, faltam)
    if not campos:
        return PedidoResidual(tipo_documento=tipo, tentativa=tentativa, refazer_foto=True,
                              texto=("A tabela do documento ficou ilegível na foto: refaça a foto do papel inteiro, "
                                     "de cima, ou envie o XML."))
    doc = "nota" if tipo == "danfe" else "GTA"
    refazer = len(campos) > MAX_CAMPOS_POR_PEDIDO
    pedidos = "; ".join(f"({i}) {c.instrucao}" for i, c in enumerate(campos[:MAX_CAMPOS_POR_PEDIDO], 1))
    if refazer:
        texto = (f"Muitos campos da {doc} não validaram na foto ({len(campos)}). Refaça a foto do papel inteiro, de "
                 f"cima, sem sombra; se preferir, confira no papel: {pedidos}.")
    else:
        texto = (f"Para completar a {doc}, preciso só disto do papel: {pedidos}. Pode falar ou digitar; eu confiro "
                 "cada valor (dígito verificador, somas e datas) antes de aceitar.")
    if tentativa > 1:
        texto = f"Tentativa {tentativa} de {MAX_TENTATIVAS}. " + texto
    return PedidoResidual(tipo_documento=tipo, tentativa=tentativa, campos=campos, refazer_foto=refazer, texto=texto)


# ---------------------------------------------------------------------------
# Resposta da fiscal (voz já transcrita ou texto digitado) → valores por campo
# ---------------------------------------------------------------------------

_UF_NOMES = {"goias": "GO", "minas gerais": "MG", "mato grosso do sul": "MS", "mato grosso": "MT", "bahia": "BA",
             "tocantins": "TO", "sao paulo": "SP", "distrito federal": "DF", "para": "PA", "parana": "PR"}
_MESES = {"janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
          "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}
_RX_DATA = re.compile(r"(\d{1,2})\s*(?:/|-|\.|\s+d[eo]\s+|\s+)\s*(\d{1,2}|[a-zç]+)\s*(?:/|-|\.|\s+de\s+|\s+)\s*"
                      r"(\d{4})")
_RX_NUM = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?")
_RX_NAO_VALOR = re.compile(r"\b\d+\s*(?:º|o\b|ª)?\s*(?:ultimos?|primeiros?|digitos?|grupos?|blocos?|linha)\b"
                           r"|\b(?:grupo|bloco|linha)\s+\d+\b")
_RX_MACHOS = re.compile(r"\b(\d+|nenhum|nenhuma|zero)\s+mach\w*")
_RX_FEMEAS = re.compile(r"\b(\d+|nenhum|nenhuma|zero)\s+feme\w*")
_RX_TOTAL = re.compile(r"\btotal\s+(?:de\s+|e\s+)?(\d+)")


def _sem_acento_igual(t: str) -> str:
    """Tira acentos sem mudar o comprimento (os índices continuam valendo para o texto original)."""
    import unicodedata

    return "".join(unicodedata.normalize("NFKD", ch)[0] for ch in t)


def _numeros_do_texto(texto: str) -> str:
    """Números por extenso → algarismos (`laudo.speech.numeros`), só nos trechos sem algarismo: o que já veio em
    algarismos fica como está (zeros à esquerda contam na chave, no NCM e no número da nota)."""
    from laudo.speech.numeros import normalizar

    partes = re.split(r"(\S*\d\S*)", texto or "")
    return _um_entre_digitos("".join(x if re.search(r"\d", x) else normalizar(x).texto for x in partes))


_RX_PALAVRA = re.compile(r"\S+")
_PONTUACAO = ".,;:!?()"


def _um_entre_digitos(texto: str) -> str:
    """"um"/"uma" ditados numa sequência de algarismos viram 1. O normalizador trata "um" isolado como artigo
    ("uma cerca"), e a chave lida algarismo por algarismo perderia o dígito: "6 4 um 5 5 9" ficaria com 5.
    Troca quando há algarismo antes e depois (atravessando outros "um"); na ponta de uma sequência ditada
    algarismo por algarismo (2 ou mais soltos), troca no começo ("um 5 4") e no fim só se o "um" fecha a frase
    ou o trecho ("4 3 um." / "4 3 um, CNPJ ..."), para "1 2 3, uma cabeça" continuar artigo."""
    toks = list(_RX_PALAVRA.finditer(texto or ""))
    if not toks:
        return texto
    nucleo = [m.group().strip(_PONTUACAO).lower() for m in toks]
    um = [n in ("um", "uma") for n in nucleo]
    dig = [bool(re.fullmatch(r"\d+", n)) for n in nucleo]
    solto = [d and len(n) == 1 for d, n in zip(dig, nucleo, strict=True)]
    trocar: list[int] = []
    for i, eh in enumerate(um):
        if not eh:
            continue
        a = i - 1
        while a >= 0 and um[a]:
            a -= 1
        b = i + 1
        while b < len(toks) and um[b]:
            b += 1
        antes, depois = a >= 0 and dig[a], b < len(toks) and dig[b]
        fecha = b == len(toks) or toks[b - 1].group()[-1] in ".,;:!?"  # o último "um" da sequência fecha o trecho
        if (antes and depois) or (depois and b + 1 < len(toks) and solto[b] and solto[b + 1]) or (
            antes and fecha and a >= 1 and solto[a] and solto[a - 1]
        ):
            trocar.append(i)
    for i in reversed(trocar):
        m = toks[i]
        texto = texto[:m.start()] + re.sub(r"(?i)uma|um", "1", m.group(), count=1) + texto[m.end():]
    return texto


class _Texto:
    """Texto da resposta com consumo: cada trecho lido por um campo some (vira espaço) para o próximo."""

    def __init__(self, texto: str):
        t = _sem_acento_igual(_numeros_do_texto(texto))
        self.o = t  # caixa original
        self.n = t.lower()

    def tirar(self, a: int, b: int) -> None:
        self.o = self.o[:a] + " " * (b - a) + self.o[b:]
        self.n = self.n[:a] + " " * (b - a) + self.n[b:]

    def buscar(self, rx: re.Pattern, caixa: bool = False) -> re.Match | None:
        return rx.search(self.o if caixa else self.n)


_RX_DIG = re.compile(r"\d+")
_RX_UF_NOME = re.compile(r"\b(" + "|".join(sorted(_UF_NOMES, key=len, reverse=True)) + r")\b")
_RX_UF_SIGLA = re.compile(r"\b([A-Za-z]{2})\b")
_RX_TP = re.compile(r"\b([01])\b|\b(entrada|saida)\b")
_RX_ESPECIE = re.compile(r"\b(bovin\w*|bubalin\w*|bufal\w*)\b")
_RX_SERIE_DITA = re.compile(r"\bserie\s+([a-z])(?:\s?([a-z]))?\b")
_RX_SERIE_LETRAS = re.compile(r"\b([A-Z]{1,2})\b")
_RX_UNIDADE = re.compile(r"\b(cb|cab|cabecas?|un|und|unid|unidade|kg|arrobas?)\b")


def _digitos_seguidos(tx: _Texto, n: int | None) -> str:
    """Dígitos dos próximos trechos numéricos até completar `n` (sem passar de `n`); sem `n`, o 1º trecho."""
    achado = ""
    for m in list(_RX_DIG.finditer(tx.n)):
        if n and len(achado) + len(m.group(0)) > n:
            if not achado:  # um trecho maior que o esperado: leva assim mesmo (a validação recusa)
                achado = m.group(0)
                tx.tirar(m.start(), m.end())
            break
        achado += m.group(0)
        tx.tirar(m.start(), m.end())
        if not n or len(achado) == n:
            break
    return achado


def _municipio(tx: _Texto) -> tuple[str, str, str] | None:
    """(nome, código IBGE, UF): o código IBGE dito (7 dígitos) com o nome antes dele, ou o município de GO mais
    à esquerda no texto (o mais longo, se empatar). A validação confere DV, UF e nome × código."""
    cod = re.search(r"(?<!\d)(\d{7})(?!\d)", tx.n)
    tabela = L.municipios_go()
    alto = tx.o.upper()
    melhor = None
    for c, nome in tabela.items():
        m = re.search(rf"\b{re.escape(nome)}\b", alto)
        if m and (melhor is None or (m.start(), -len(nome)) < (melhor[0].start(), -len(melhor[1]))):
            melhor = (m, nome, c)
    if cod and (melhor is None or cod.start() < melhor[0].start() or cod.group(1)[:2] != "52"):
        ini = max(alto.rfind(",", 0, cod.start()), alto.rfind(";", 0, cod.start())) + 1
        nome = re.sub(r"\b(?:CODIGO|IBGE|COD)\b", " ", alto[ini:cod.start()])
        nome = L.sem_acento(re.sub(r"[^A-Z ]", " ", nome))
        tx.tirar(ini, cod.end())
        uf = L.UF_POR_CODIGO.get(cod.group(1)[:2], "")
        return nome, cod.group(1), uf
    if melhor is None:
        return None
    tx.tirar(melhor[0].start(), melhor[0].end())
    return melhor[1], melhor[2], "GO"


def interpretar_resposta(pedido: PedidoResidual, texto: str | None = None,
                         digitado: dict[str, str] | None = None) -> dict[str, str]:
    """Valores por campo do pedido. `digitado` (formulário da interface) prevalece; o texto (fala transcrita ou
    digitada) é lido campo a campo, na ordem do pedido: cada campo consome o trecho mais à esquerda do seu
    formato (dígitos, número, data, UF, município...). Nada é completado ou corrigido aqui: quem aceita é a
    validação determinística (`completar`)."""
    out: dict[str, str] = {}
    dig = {k: str(v).strip() for k, v in (digitado or {}).items() if str(v or "").strip()}
    tx = _Texto(texto or "")
    for m in list(_RX_NAO_VALOR.finditer(tx.n)):  # "os 4 últimos dígitos", "o 3º grupo": instrução repetida
        tx.tirar(m.start(), m.end())
    for pc in pedido.campos:
        if any(n in dig for n in pc.campos):
            out.update({n: dig[n] for n in pc.campos if n in dig})
            out.update({n + "#2": dig[n + "#2"] for n in pc.campos if pc.confirmar and n + "#2" in dig})
            continue
        if pc.modo == "digitacao":
            continue  # CPF/CNPJ e código do estabelecimento: só por digitação (CPF não é lido da fala)
        nome = pc.campos[0]
        if pc.formato == "digitos":
            if v := _digitos_seguidos(tx, pc.n_digitos):
                out[nome] = v
        elif pc.formato == "grade":
            rot = {"total_machos": _RX_MACHOS, "total_femeas": _RX_FEMEAS, "total": _RX_TOTAL}
            achados = {n: m for n, rx in rot.items() if (m := tx.buscar(rx))}
            if len(achados) >= 2:  # resposta rotulada ("29 fêmeas, nenhum macho, total 29")
                vals = {n: (0 if m.group(1) in ("nenhum", "nenhuma", "zero") else int(m.group(1)))
                        for n, m in achados.items()}
                if "total" not in vals:
                    vals["total"] = vals["total_machos"] + vals["total_femeas"]
                elif len(vals) == 2:
                    outro = next(n for n in vals if n != "total")
                    falta = next(n for n in rot if n not in vals)
                    vals[falta] = vals["total"] - vals[outro]
                out.update({n: str(v) for n, v in vals.items()})
                for m in achados.values():
                    tx.tirar(m.start(), m.end())
                continue
            for n in pc.campos:
                m = tx.buscar(_RX_NUM)
                if not m:
                    break
                out[n] = m.group(0)
                tx.tirar(m.start(), m.end())
        elif pc.formato == "numero":
            for n in pc.campos:
                m = tx.buscar(_RX_NUM)
                if not m:
                    break
                out[n] = m.group(0)
                tx.tirar(m.start(), m.end())
        elif pc.formato == "data":
            if m := tx.buscar(_RX_DATA):
                mes = m.group(2)
                mes_n = int(mes) if mes.isdigit() else _MESES.get(mes)
                if mes_n:
                    out[nome] = f"{int(m.group(1)):02d}/{mes_n:02d}/{m.group(3)}"
                tx.tirar(m.start(), m.end())
        elif pc.formato == "uf":
            if m := tx.buscar(_RX_UF_NOME):
                out[nome] = _UF_NOMES[m.group(1)]
                tx.tirar(m.start(), m.end())
            else:
                for m in _RX_UF_SIGLA.finditer(tx.o):
                    if m.group(1).upper() in L.CODIGO_UF:
                        out[nome] = m.group(1).upper()
                        tx.tirar(m.start(), m.end())
                        break
        elif pc.formato == "tp_nf":
            if m := tx.buscar(_RX_TP):
                out[nome] = m.group(1) or ("0" if m.group(2) == "entrada" else "1")
                tx.tirar(m.start(), m.end())
        elif pc.formato == "municipio":
            if achado := _municipio(tx):
                out[pc.campos[0]], out[pc.campos[1]], out[pc.campos[2]] = achado
        elif pc.formato == "finalidade":
            for f in sorted(L.FINALIDADES_GTA, key=len, reverse=True):
                if m := re.search(rf"\b{f.lower().replace('_', ' ')}\b", tx.n):
                    out[nome] = f
                    tx.tirar(m.start(), m.end())
                    break
        elif pc.formato == "especie":
            if m := tx.buscar(_RX_ESPECIE):
                out[nome] = m.group(1).upper()
                tx.tirar(m.start(), m.end())
        elif pc.formato == "serie_gta":
            if m := tx.buscar(_RX_SERIE_DITA):
                out[nome] = (m.group(1) + (m.group(2) or "")).upper()
                tx.tirar(m.start(), m.end())
            elif m := tx.buscar(_RX_SERIE_LETRAS, caixa=True):  # "AB" digitado ou transcrito em maiúsculas
                out[nome] = m.group(1)
                tx.tirar(m.start(), m.end())
        elif pc.formato == "texto" and nome.endswith("unidade") and (m := tx.buscar(_RX_UNIDADE)):
            out[nome] = m.group(1).upper()
            tx.tirar(m.start(), m.end())
    return out


def resposta_do_papel(pedido: PedidoResidual, papel: dict[str, Any]) -> tuple[str, dict[str, str]]:
    """O que a fiscal diria e digitaria lendo o papel, para cada campo do pedido (`papel`: valores por campo, no
    espaço de `bruto_de_campos`). Fala para os campos de voz (dígitos da chave um a um, números como impressos,
    "total N, M machos e F fêmeas", município); digitação para CPF/CNPJ e código do estabelecimento. Serve à
    demo (roteiro) e à avaliação (A/B v2), que injeta erro humano por cima."""
    falas: list[str] = []
    dig: dict[str, str] = {}
    for pc in pedido.campos:
        if pc.modo == "digitacao":
            for n in pc.campos:
                if papel.get(n) is not None:
                    dig[n] = str(papel[n])
                    if pc.confirmar:
                        dig[n + "#2"] = str(papel[n])
            continue
        if pc.campos == ["chave"] and papel.get("chave"):
            ch = str(papel["chave"])
            d = ch if pc.n_digitos == 44 else "".join(ch[4 * (b - 1):4 * b] for b in pc.blocos_chave)
            falas.append(" ".join(d))
        elif pc.formato == "grade":
            falas.append(f"total {papel.get('total')}, {papel.get('total_machos')} machos e "
                         f"{papel.get('total_femeas')} fêmeas")
        elif pc.formato == "municipio":
            nome = str(papel.get(pc.campos[0]) or "").title()
            uf = papel.get(pc.campos[2])
            falas.append(nome + ("" if uf in (None, "GO") else f", código IBGE {papel.get(pc.campos[1])}"))
        else:
            falas.extend(impresso(n, papel.get(n)) for n in pc.campos if papel.get(n) is not None)
    return ", ".join(x for x in falas if x), dig


# ---------------------------------------------------------------------------
# Completar a leitura com a resposta e validar
# ---------------------------------------------------------------------------


class ResultadoResidual(BaseModel):
    status: Literal["ok", "indeterminado"]
    documento: dict[str, Any]
    campos: dict[str, dict[str, Any]]  # campos para a trilha (CPF/CNPJ mascarados), com `origem`
    aceitos_da_fiscal: list[str] = Field(default_factory=list)
    recusados: list[dict[str, str]] = Field(default_factory=list)  # {campo, motivo}
    pedido: PedidoResidual | None = None
    motivo: str = ""


def _chave_com_blocos(base: str, blocos: list[int], digitos: str, valores: dict[str, Any]) -> tuple[str | None, str]:
    """Chave montada: dígitos lidos pela fiscal nos grupos pedidos + posições derivadas dos campos (já com as
    respostas dela) + o que as leituras concordaram. Devolve (chave, motivo da recusa)."""
    d = re.sub(r"\D", "", digitos or "")
    if len(d) != 4 * len(blocos):
        return None, f"esperava {4 * len(blocos)} dígitos, recebi {len(d)}"
    c = list(base)
    for i, b in enumerate(blocos):
        c[4 * (b - 1):4 * b] = list(d[4 * i:4 * i + 4])
    derivadas = _derivar_posicoes(valores)
    for i, dig in derivadas.items():
        if c[i] == "d" or (6 <= i < 20 and _doc_valido(valores.get("emitente_doc"))):
            c[i] = dig  # o CNPJ/CPF do emitente digitado (com DV válido) prevalece sobre o lido
    faltam = sorted({n for n, (a, b) in _POS_DERIVADAS.items() if "d" in c[a:b]})
    if faltam:
        return None, f"para montar a chave falta validar: {', '.join(faltam)}"
    return "".join(c), ""


def _doc_valido(doc: Any) -> bool:
    d = so_alnum(str(doc or ""))
    return (len(d) == 14 and L.cnpj_valido(d)) or (len(d) == 11 and L.cpf_valido(d))


def _hash_parte(documento: dict[str, Any], tipo: str, nome: str) -> tuple[str | None, str | None]:
    """(sha256, máscara) do documento de uma parte já aceito na leitura."""
    if tipo == "danfe":
        p = documento.get("emitente" if nome == "emitente_doc" else "destinatario") or {}
        return p.get("doc_sha256"), p.get("doc_mascarado")
    p = documento.get(nome.split(".")[0]) or {}
    return p.get("documento_sha256"), p.get("doc_mascarado")


def completar(leitura: dict[str, Any], respostas: dict[str, str], hoje: date,
              pedido: PedidoResidual | None = None) -> ResultadoResidual:
    """Junta o que a leitura validou com o que a fiscal leu e revalida tudo com `leitura.validar_*`."""
    tipo = str(leitura.get("tipo_documento"))
    campos = leitura.get("campos") or {}
    pedido = pedido or pedido_residual(leitura)
    valores: dict[str, Any] = {n: (c.get("valor") if c.get("status") == "ok" else None) for n, c in campos.items()}
    docs_leitura = {n for n in _DOCS if _ok(campos, n)}
    for n in docs_leitura:
        valores[n] = None  # máscara não revalida: o documento aceito na leitura volta pelo hash, depois
    recusados: list[dict[str, str]] = []
    fiscal: set[str] = set()
    ja_fiscal = {n for n, c in campos.items() if c.get("origem") == "fiscal"}  # completado em tentativa anterior
    pc_chave = None
    for pc in (pedido.campos if pedido else []):
        for nome in pc.campos:
            if nome not in respostas:
                continue
            if pc.confirmar and str(respostas.get(nome + "#2", "")).strip() != str(respostas[nome]).strip():
                recusados.append({"campo": nome, "motivo": "as duas digitações não conferem"})
                continue
            if nome == "chave" and pc.base_chave and pc.blocos_chave and pc.n_digitos != 44:
                pc_chave = pc  # montada depois das outras respostas (posições derivadas de UF, data, série, número)
                continue
            fiscal.add(nome)
            valores[nome] = _do_texto(tipo, nome, str(respostas[nome]).strip())
    if pc_chave is not None:
        ch, motivo = _chave_com_blocos(pc_chave.base_chave or "", pc_chave.blocos_chave, str(respostas["chave"]),
                                       valores)
        if ch is None:
            recusados.append({"campo": "chave", "motivo": motivo})
        else:
            fiscal.add("chave")
            valores["chave"] = ch
    if tipo == "gta" and "total" in fiscal and not _ok(campos, "total_por_extenso"):
        valores["total_por_extenso"] = valores.get("total")  # a fiscal leu o total (a linha e o extenso batem)
        fiscal.add("total_por_extenso")
    if tipo == "gta" and "total" in fiscal:
        valores["quantidades_por_faixa"] = None  # a grade lida não vale com o total corrigido
    res = (L.validar_danfe if tipo == "danfe" else L.validar_gta)(bruto_de_campos(tipo, valores), hoje)
    c = res.campos
    doc_orig = leitura.get("documento") or {}
    # documentos aceitos na leitura voltam pelo hash, e a coerência com a chave/outra parte é conferida pelo hash
    restaurados: dict[str, str] = {}
    for n in docs_leitura - fiscal:
        h, masc = _hash_parte(doc_orig, tipo, n)
        if not h:
            continue
        derivado = c.get(n)
        if (derivado is not None and derivado.status == "ok" and derivado.origem.startswith("derivado")
                and hash_documento(derivado.valor) != h):
            c["chave"] = L.CampoLido(nome="chave", valor=None, status="indeterminado",
                                     motivo="a chave lida não confere com o CNPJ/CPF do emitente lido da foto")
        c[n] = L.CampoLido(nome=n, valor=masc, status="ok", motivo="CPF/CNPJ com DV válido (leitura da foto)",
                           origem="leitura")
        restaurados[n] = h
    hashes = {n: (restaurados.get(n) or (hash_documento(c[n].valor) if n in c and c[n].status == "ok" else None))
              for n in _DOCS if n in c}
    if tipo == "danfe" and hashes.get("emitente_doc") and hashes.get("emitente_doc") == hashes.get("destinatario_doc"):
        c["destinatario_doc"] = L.CampoLido(nome="destinatario_doc", status="indeterminado",
                                            motivo="igual ao CPF/CNPJ do emitente; confira o papel e peça o XML")
    # documento final: o de `validar_*`, com as partes restauradas e os campos que a validação derrubou
    documento = dict(res.documento)
    for n, h in restaurados.items():
        if tipo == "danfe":
            parte = "emitente" if n == "emitente_doc" else "destinatario"
            documento[parte] = {**(documento.get(parte) or {}), **{k: (doc_orig.get(parte) or {}).get(k) for k in
                                                                   ("tipo_doc", "doc_mascarado", "doc_sha256")}}
        else:
            parte = n.split(".")[0]
            documento[parte] = {**(documento.get(parte) or {}), "documento_sha256": h,
                                "doc_mascarado": (doc_orig.get(parte) or {}).get("doc_mascarado")}
    for parte in (("emitente", "destinatario") if tipo == "danfe" else ("origem", "destino")):
        if (doc_orig.get(parte) or {}).get("nome"):
            documento[parte] = {**(documento.get(parte) or {}), "nome": doc_orig[parte]["nome"]}
    if tipo == "danfe" and c.get("destinatario_doc") is not None and c["destinatario_doc"].status != "ok":
        documento["destinatario"] = {**(documento.get("destinatario") or {}), "doc_sha256": None,
                                     "doc_mascarado": None, "tipo_doc": None}
    if tipo == "danfe" and c.get("chave") is not None and c["chave"].status != "ok":
        documento["chave"] = None
    documento["ilegiveis"] = sorted(n for n, x in c.items() if x.critico and x.status != "ok")
    documento["proveniencia"] = PROVENIENCIA if fiscal | ja_fiscal else "lido de foto e validado"
    saida: dict[str, dict[str, Any]] = {}
    for n, x in c.items():
        d = x.model_dump(exclude={"nome"})
        if (n in fiscal or n in ja_fiscal) and x.status == "ok":
            d["origem"] = "fiscal"
        if n.endswith("doc") and d["valor"] and n not in restaurados:
            d["valor"] = mascarar_documento(str(d["valor"]))
        if n.endswith("nome"):
            d["valor"] = None
        saida[n] = d
    aceitos = sorted(n for n in fiscal if n in c and c[n].status == "ok")
    for n in sorted(fiscal - set(aceitos)):
        if n in c:
            recusados.append({"campo": n, "motivo": c[n].motivo or "não validou"})
    proximo = None
    restam = [n for n, x in c.items() if x.critico and x.status != "ok"]
    tentativa = (pedido.tentativa if pedido else 0) + 1
    if restam:
        prov = {"tipo_documento": tipo, "campos": saida,
                "leituras_brutas": leitura.get("leituras_brutas") if "chave" in restam else []}
        proximo = pedido_residual(prov, tentativa=tentativa)
    status: Literal["ok", "indeterminado"] = "indeterminado" if restam else "ok"
    if not restam:
        motivo = f"todos os campos críticos validaram ({len(aceitos)} completado(s) pela fiscal)"
    elif proximo is None:
        quando = f"após {MAX_TENTATIVAS} tentativas" if tentativa > MAX_TENTATIVAS else "e o papel não resolve"
        motivo = (f"{len(restam)} campo(s) crítico(s) sem validação {quando}: {', '.join(restam[:6])}; peça o XML "
                  "da NF-e ou a e-GTA")
    else:
        motivo = f"{len(restam)} campo(s) crítico(s) ainda sem validação: {', '.join(restam[:6])}"
    return ResultadoResidual(status=status, documento=documento, campos=saida, aceitos_da_fiscal=aceitos,
                             recusados=recusados, pedido=proximo, motivo=motivo)


def _do_texto(tipo: str, nome: str, bruto: str) -> Any:
    """Resposta da fiscal → valor no espaço dos campos (o que `bruto_de_campos` sabe imprimir)."""
    folha = nome.rsplit(".", 1)[-1]
    b = bruto.strip()
    if folha in ("data_emissao", "validade"):
        d = L.data_br(b)
        return d.isoformat() if d else b
    if folha in ("quantidade", "valor_unitario", "valor_total", "v_prod"):
        v = L.valor_br(b)
        return v if v is not None else b
    if folha in ("total", "total_machos", "total_femeas", "total_por_extenso"):
        return int(L.digitos(b)) if L.digitos(b) else b
    if tipo == "danfe" and nome in ("numero", "serie"):
        return int(L.digitos(b)) if L.digitos(b) else b
    if folha == "doc":
        return so_alnum(b)
    if nome in ("emitente_doc", "destinatario_doc"):
        return so_alnum(b)
    if folha == "municipio":
        return L.sem_acento(b)
    return b

