"""Imagens "de papel" dos documentos sintéticos: DANFE a partir do XML da NF-e e GTA em formulário, mais a
simulação de foto de celular (rotação, perspectiva, desfoque, sombra, dobra, baixa resolução, JPEG).

Serve ao conjunto de entradas bagunçadas (`gerar_baguncados.py`). Só Pillow e numpy; determinístico dado o
gerador aleatório. As imagens carregam os marcadores de documento sintético (homologação, "SEM VALOR FISCAL",
CNPJ 99.999.999, CPF 000.000) e não imitam a identidade visual de nenhum órgão.

Layout do DANFE: blocos do Anexo II do MOC 4.00 (canhoto, identificação do emitente, DANFE, chave de acesso,
natureza da operação e protocolo, destinatário, cálculo do imposto, transportador, produtos, dados
adicionais), sem o código de barras CODE-128C (ver limitações no README do gerador). Layout da GTA: itens
01 a 20 do formulário descritos no Manual SDA de trânsito de bovinos e bubalinos (quantidade por sexo e faixa
etária em grade, procedência, destino, finalidade, emissão e validade).
"""

from __future__ import annotations

import io
import math
import random
from datetime import datetime
from typing import Any

import numpy as np
from lxml import etree
from PIL import Image, ImageDraw, ImageFilter, ImageFont

NS = "{http://www.portalfiscal.inf.br/nfe}"
LARGURA, ALTURA = 1240, 1754  # A4 a 150 dpi
_FONTES = {"normal": ("arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"),
           "negrito": ("arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"),
           "mono": ("consola.ttf", "cour.ttf", "DejaVuSansMono.ttf", "LiberationMono-Regular.ttf")}
_CACHE: dict[tuple[str, int], Any] = {}


def fonte(tipo: str, tamanho: int) -> Any:
    chave = (tipo, tamanho)
    if chave not in _CACHE:
        for nome in _FONTES[tipo]:
            try:
                _CACHE[chave] = ImageFont.truetype(nome, tamanho)
                break
            except OSError:
                continue
        else:
            _CACHE[chave] = ImageFont.load_default(size=tamanho)
    return _CACHE[chave]


def fontes_usadas() -> dict[str, str]:
    """Nome do arquivo de fonte efetivamente usado por tipo (os bytes das imagens dependem disso)."""
    out = {}
    for tipo in _FONTES:
        f = fonte(tipo, 12)
        out[tipo] = getattr(f, "path", "load_default")
    return out


# ---------------------------------------------------------------------------
# Formatação brasileira
# ---------------------------------------------------------------------------


def br_num(v: float, casas: int = 2) -> str:
    return f"{v:,.{casas}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def fmt_doc(doc: str) -> str:
    d = "".join(c for c in doc if c.isalnum())
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    return d


def fmt_chave(ch: str) -> str:
    return " ".join(ch[i:i + 4] for i in range(0, 44, 4))


def fmt_ncm(ncm: str) -> str:
    return ncm  # o DANFE imprime o NCM com 8 dígitos, sem pontos


# ---------------------------------------------------------------------------
# Desenho de caixas
# ---------------------------------------------------------------------------


class Folha:
    def __init__(self) -> None:
        self.img = Image.new("RGB", (LARGURA, ALTURA), "white")
        self.dr = ImageDraw.Draw(self.img)

    def caixa(self, x: int, y: int, w: int, h: int, rotulo: str = "", valor: str = "", tam: int = 19,
              tipo: str = "normal", alinhar: str = "esq") -> None:
        self.dr.rectangle([x, y, x + w, y + h], outline="black", width=2)
        if rotulo:
            self.dr.text((x + 5, y + 3), rotulo.upper(), font=fonte("normal", 12), fill="black")
        if valor:
            f = fonte(tipo, tam)
            tw = self.dr.textlength(valor, font=f)
            while tw > w - 10 and tam > 11:  # encolhe para caber (como os geradores de DANFE)
                tam -= 1
                f = fonte(tipo, tam)
                tw = self.dr.textlength(valor, font=f)
            tx = x + 6 if alinhar == "esq" else x + w - 6 - tw if alinhar == "dir" else x + (w - tw) / 2
            self.dr.text((tx, y + h - tam - 7), valor, font=f, fill="black")

    def texto(self, x: float, y: float, s: str, tam: int = 18, tipo: str = "normal") -> None:
        self.dr.text((x, y), s, font=fonte(tipo, tam), fill="black")

    def marca_dagua(self, s: str, tam: int = 70, cor: tuple[int, int, int, int] = (200, 0, 0, 70)) -> None:
        f = fonte("negrito", tam)
        caixa = self.dr.textbbox((0, 0), s, font=f)
        marca = Image.new("RGBA", (caixa[2] + 20, caixa[3] + 20), (255, 255, 255, 0))
        ImageDraw.Draw(marca).text((10, 10), s, font=f, fill=cor)
        marca = marca.rotate(30, expand=True, resample=Image.BICUBIC)
        self.img.paste(marca, ((LARGURA - marca.width) // 2, (ALTURA - marca.height) // 2), marca)


# ---------------------------------------------------------------------------
# DANFE a partir do XML
# ---------------------------------------------------------------------------


def _t(el: Any, caminho: str) -> str:
    if el is None:
        return ""
    v = el.findtext("/".join(NS + p for p in caminho.split("/")))
    return (v or "").strip()


def dados_danfe(xml: bytes) -> dict[str, Any]:
    """Campos do XML que o DANFE imprime (valores em claro: só documentos sintéticos)."""
    raiz = etree.fromstring(xml, etree.XMLParser(resolve_entities=False, no_network=True))
    nfe = raiz if raiz.tag == NS + "NFe" else raiz.find(NS + "NFe")
    inf = nfe.find(NS + "infNFe")
    prot = raiz.find(f"{NS}protNFe/{NS}infProt")
    ide, emit, dest = inf.find(NS + "ide"), inf.find(NS + "emit"), inf.find(NS + "dest")
    itens = []
    for det in inf.findall(NS + "det"):
        p = det.find(NS + "prod")
        itens.append({"codigo": _t(p, "cProd"), "descricao": _t(p, "xProd"), "ncm": _t(p, "NCM"),
                      "cfop": _t(p, "CFOP"), "unidade": _t(p, "uCom"), "quantidade": float(_t(p, "qCom")),
                      "valor_unitario": float(_t(p, "vUnCom")), "valor_total": float(_t(p, "vProd"))})
    dh = datetime.fromisoformat(_t(ide, "dhEmi"))
    return {
        "chave": (inf.get("Id") or "")[3:],
        "numero": int(_t(ide, "nNF")), "serie": int(_t(ide, "serie")), "tp_nf": _t(ide, "tpNF"),
        "nat_op": _t(ide, "natOp"), "tp_amb": _t(ide, "tpAmb"), "dh_emi": dh,
        "emitente": {"nome": _t(emit, "xNome"), "doc": _t(emit, "CNPJ") or _t(emit, "CPF"),
                     "ie": _t(emit, "IE"), "lgr": _t(emit, "enderEmit/xLgr"), "mun": _t(emit, "enderEmit/xMun"),
                     "uf": _t(emit, "enderEmit/UF"), "cep": _t(emit, "enderEmit/CEP")},
        "destinatario": {"nome": _t(dest, "xNome"), "doc": _t(dest, "CNPJ") or _t(dest, "CPF"),
                         "ie": _t(dest, "IE"), "lgr": _t(dest, "enderDest/xLgr"), "mun": _t(dest, "enderDest/xMun"),
                         "uf": _t(dest, "enderDest/UF"), "cep": _t(dest, "enderDest/CEP")},
        "itens": itens,
        "v_prod": float(_t(inf, "total/ICMSTot/vProd") or 0), "v_nf": float(_t(inf, "total/ICMSTot/vNF") or 0),
        "inf_cpl": _t(inf, "infAdic/infCpl"),
        "protocolo": (f"{_t(prot, 'nProt')} - {datetime.fromisoformat(_t(prot, 'dhRecbto')):%d/%m/%Y %H:%M:%S}"
                      if prot is not None and _t(prot, "nProt") else ""),
    }


def renderizar_danfe(xml: bytes) -> Image.Image:
    d = dados_danfe(xml)
    f = Folha()
    m, w = 40, LARGURA - 80
    num = f"{d['numero']:09d}"
    num_fmt = f"{num[:3]}.{num[3:6]}.{num[6:]}"
    serie = f"{d['serie']:03d}"
    e, de = d["emitente"], d["destinatario"]
    # canhoto
    y = 30
    f.caixa(m, y, w - 260, 70, "", "")
    f.texto(m + 8, y + 8, f"RECEBEMOS DE {e['nome']} OS PRODUTOS CONSTANTES DA NOTA FISCAL INDICADA AO LADO", 13)
    f.texto(m + 8, y + 40, "DATA DE RECEBIMENTO: ____/____/______   IDENTIFICAÇÃO E ASSINATURA DO RECEBEDOR", 13)
    f.caixa(m + w - 260, y, 260, 70)
    f.texto(m + w - 240, y + 8, "NF-e", 20, "negrito")
    f.texto(m + w - 240, y + 36, f"Nº {num_fmt}  SÉRIE {serie}", 16)
    # identificação do emitente | DANFE | chave
    y = 120
    f.caixa(m, y, 470, 210)
    f.texto(m + 10, y + 12, "IDENTIFICAÇÃO DO EMITENTE", 12)
    f.texto(m + 10, y + 40, e["nome"][:34], 20, "negrito")
    f.texto(m + 10, y + 72, e["nome"][34:68], 20, "negrito")
    f.texto(m + 10, y + 110, f"{e['lgr']}, SN - ZONA RURAL", 15)
    f.texto(m + 10, y + 135, f"{e['mun']} - {e['uf']}  CEP {e['cep'][:5]}-{e['cep'][5:]}", 15)
    f.caixa(m + 470, y, 220, 210)
    f.texto(m + 520, y + 10, "DANFE", 30, "negrito")
    f.texto(m + 482, y + 50, "DOCUMENTO AUXILIAR DA", 13)
    f.texto(m + 482, y + 66, "NOTA FISCAL ELETRÔNICA", 13)
    f.texto(m + 482, y + 92, "0 - ENTRADA", 14)
    f.texto(m + 482, y + 110, "1 - SAÍDA", 14)
    f.dr.rectangle([m + 620, y + 92, m + 660, y + 128], outline="black", width=2)
    f.texto(m + 632, y + 96, d["tp_nf"], 24, "negrito")
    f.texto(m + 482, y + 140, f"Nº {num_fmt}", 18, "negrito")
    f.texto(m + 482, y + 164, f"SÉRIE {serie}   FOLHA 1/1", 15)
    xk = m + 690
    f.caixa(xk, y, w - 690, 80, "CONTROLE DO FISCO")
    f.texto(xk + 12, y + 30, "(código de barras não reproduzido)", 14)
    f.caixa(xk, y + 80, w - 690, 70, "CHAVE DE ACESSO", fmt_chave(d["chave"]), 19, "mono", "centro")
    f.caixa(xk, y + 150, w - 690, 60)
    f.texto(xk + 8, y + 156, "Consulta de autenticidade no portal nacional da NF-e", 13)
    f.texto(xk + 8, y + 174, "www.nfe.fazenda.gov.br/portal ou no site da Sefaz Autorizadora", 13)
    y += 210
    f.caixa(m, y, 690, 56, "NATUREZA DA OPERAÇÃO", d["nat_op"])
    f.caixa(m + 690, y, w - 690, 56, "PROTOCOLO DE AUTORIZAÇÃO DE USO", d["protocolo"], 17)
    y += 56
    f.caixa(m, y, 390, 56, "INSCRIÇÃO ESTADUAL", e["ie"] or "")
    f.caixa(m + 390, y, 390, 56, "INSC. ESTADUAL DO SUBST. TRIB.", "")
    f.caixa(m + 780, y, w - 780, 56, "CNPJ / CPF", fmt_doc(e["doc"]))
    # destinatário
    y += 70
    f.texto(m, y, "DESTINATÁRIO / REMETENTE", 14, "negrito")
    y += 22
    f.caixa(m, y, 690, 56, "NOME / RAZÃO SOCIAL", de["nome"], 17)
    f.caixa(m + 690, y, 260, 56, "CNPJ / CPF", fmt_doc(de["doc"]))
    f.caixa(m + 950, y, w - 950, 56, "DATA DA EMISSÃO", d["dh_emi"].strftime("%d/%m/%Y"))
    y += 56
    f.caixa(m, y, 560, 56, "ENDEREÇO", de["lgr"])
    f.caixa(m + 560, y, 230, 56, "BAIRRO / DISTRITO", "ZONA RURAL")
    f.caixa(m + 790, y, 160, 56, "CEP", f"{de['cep'][:5]}-{de['cep'][5:]}")
    f.caixa(m + 950, y, w - 950, 56, "DATA DA SAÍDA/ENTRADA", d["dh_emi"].strftime("%d/%m/%Y"))
    y += 56
    f.caixa(m, y, 560, 56, "MUNICÍPIO", de["mun"])
    f.caixa(m + 560, y, 90, 56, "UF", de["uf"])
    f.caixa(m + 650, y, 300, 56, "INSCRIÇÃO ESTADUAL", de["ie"] or "")
    f.caixa(m + 950, y, w - 950, 56, "HORA DA SAÍDA", d["dh_emi"].strftime("%H:%M:%S"))
    # cálculo do imposto
    y += 70
    f.texto(m, y, "CÁLCULO DO IMPOSTO", 14, "negrito")
    y += 22
    cols = [("BASE DE CÁLC. DO ICMS", "0,00"), ("VALOR DO ICMS", "0,00"), ("BASE CÁLC. ICMS ST", "0,00"),
            ("VALOR DO ICMS ST", "0,00"), ("V. TOTAL PRODUTOS", br_num(d["v_prod"]))]
    cw = w // len(cols)
    for i, (r, v) in enumerate(cols):
        f.caixa(m + i * cw, y, cw if i < len(cols) - 1 else w - i * cw, 56, r, v, alinhar="dir")
    y += 56
    cols = [("VALOR DO FRETE", "0,00"), ("VALOR DO SEGURO", "0,00"), ("DESCONTO", "0,00"),
            ("OUTRAS DESPESAS", "0,00"), ("VALOR TOTAL DA NOTA", br_num(d["v_nf"]))]
    for i, (r, v) in enumerate(cols):
        f.caixa(m + i * cw, y, cw if i < len(cols) - 1 else w - i * cw, 56, r, v,
                tipo="negrito" if i == 4 else "normal", alinhar="dir")
    # transportador
    y += 70
    f.texto(m, y, "TRANSPORTADOR / VOLUMES TRANSPORTADOS", 14, "negrito")
    y += 22
    f.caixa(m, y, 690, 56, "RAZÃO SOCIAL", "")
    f.caixa(m + 690, y, 260, 56, "FRETE POR CONTA", "9-SEM FRETE", 16)
    f.caixa(m + 950, y, w - 950, 56, "PLACA DO VEÍCULO", "")
    # produtos
    y += 70
    f.texto(m, y, "DADOS DOS PRODUTOS / SERVIÇOS", 14, "negrito")
    y += 22
    colunas = [("CÓDIGO", 90), ("DESCRIÇÃO DO PRODUTO / SERVIÇO", 330), ("NCM/SH", 110), ("CST", 55),
               ("CFOP", 70), ("UNID", 65), ("QUANT", 100), ("VALOR UNIT", 140), ("VALOR TOTAL", w - 960)]
    x = m
    for nome, cw2 in colunas:
        f.caixa(x, y, cw2, 30, nome)
        x += cw2
    y += 30
    altura_tab = 360
    f.dr.rectangle([m, y, m + w, y + altura_tab], outline="black", width=2)
    yl = y + 10
    for it in d["itens"]:
        q = it["quantidade"]
        valores = [it["codigo"], it["descricao"], fmt_ncm(it["ncm"]), "040", it["cfop"], it["unidade"],
                   br_num(q, 0 if float(q).is_integer() else 4), br_num(it["valor_unitario"]),
                   br_num(it["valor_total"])]
        x = m
        for (nome, cw2), v in zip(colunas, valores, strict=True):
            linhas = [v[i:i + 28] for i in range(0, len(v), 28)] if nome.startswith("DESCR") else [v]
            for k, ln in enumerate(linhas[:2]):
                fs = 16
                fnt = fonte("normal", fs)
                tw = f.dr.textlength(ln, font=fnt)
                tx = x + cw2 - 8 - tw if nome in ("QUANT", "VALOR UNIT", "VALOR TOTAL") else x + 6
                f.dr.text((tx, yl + 22 * k), ln, font=fnt, fill="black")
            x += cw2
        yl += 52
    x = m
    for _, cw2 in colunas[:-1]:
        x += cw2
        f.dr.line([x, y, x, y + altura_tab], fill="black", width=1)
    y += altura_tab + 14
    f.texto(m, y, "DADOS ADICIONAIS", 14, "negrito")
    y += 22
    f.caixa(m, y, w - 300, 150, "INFORMAÇÕES COMPLEMENTARES")
    cpl = d["inf_cpl"] or ""
    for k in range(0, min(len(cpl), 300), 75):
        f.texto(m + 8, y + 26 + 22 * (k // 75), cpl[k:k + 75], 15)
    f.caixa(m + w - 300, y, 300, 150, "RESERVADO AO FISCO")
    if d["tp_amb"] == "2":
        f.marca_dagua("SEM VALOR FISCAL", 110)
    return f.img


# ---------------------------------------------------------------------------
# GTA em formulário
# ---------------------------------------------------------------------------

FAIXAS = ("0-12", "13-24", "25-36", ">36")


def renderizar_gta(g: dict[str, Any]) -> Image.Image:
    """Formulário de GTA (itens do Manual SDA). `g` é o JSON do modelo `docs_fiscais.gta.GTA`."""
    f = Folha()
    m, w = 40, LARGURA - 80
    y = 36
    f.texto(m, y, "GUIA DE TRÂNSITO ANIMAL - GTA", 32, "negrito")
    f.texto(m, y + 44, "Bovídeos (bovinos e bubalinos) - documento sintético para testes", 16)
    f.caixa(m + w - 330, y - 6, 330, 84)
    f.texto(m + w - 318, y, f"UF {g.get('uf_emissao') or ''}   SÉRIE {g.get('serie') or ''}", 20, "negrito")
    f.texto(m + w - 318, y + 34, f"Nº {g.get('numero') or ''}", 30, "negrito")
    y = 140
    f.caixa(m, y, w, 40, "")
    f.texto(m + 8, y + 9, f"01 - ESPÉCIE: {(g.get('especie') or '').upper()}", 19, "negrito")
    y += 40
    # grade sexo × faixa etária
    q = {(x["sexo"], x["faixa_etaria"]): x["quantidade"] for x in g.get("quantidades") or []}
    col = [("FAIXA ETÁRIA (MESES)", 300), ("MACHOS", 220), ("FÊMEAS", 220), ("TOTAL", w - 740)]
    x = m
    for nome, cw in col:
        f.caixa(x, y, cw, 36, "", nome, 16, "negrito", "centro")
        x += cw
    y += 36
    for fx in FAIXAS:
        mm, ff = q.get(("M", fx), 0), q.get(("F", fx), 0)
        vals = [fx, str(mm) if mm else "-", str(ff) if ff else "-", str(mm + ff) if mm + ff else "-"]
        x = m
        for (_, cw), v in zip(col, vals, strict=True):
            f.caixa(x, y, cw, 40, "", v, 20, "normal", "centro")
            x += cw
        y += 40
    total = g.get("total") if g.get("total") is not None else sum(q.values())
    x = m
    for (_, cw), v in zip(col, ["TOTAL", str(sum(v for (s, _), v in q.items() if s == "M")),
                                str(sum(v for (s, _), v in q.items() if s == "F")), str(total)], strict=True):
        f.caixa(x, y, cw, 40, "", v, 20, "negrito", "centro")
        x += cw
    y += 40
    f.caixa(m, y, 420, 56, "02 - MARCA DO REBANHO", g.get("marca_rebanho") or "")
    f.caixa(m + 420, y, w - 420, 56, "10 - TOTAL DE ANIMAIS POR EXTENSO", g.get("total_por_extenso") or "")
    y += 70
    for titulo, lado in (("11 - PROCEDÊNCIA", "origem"), ("12 - DESTINO", "destino")):
        loc = g.get(lado) or {}
        f.texto(m, y, titulo, 15, "negrito")
        y += 22
        f.caixa(m, y, 760, 56, "NOME DO PRODUTOR", loc.get("nome") or "", 17)
        f.caixa(m + 760, y, w - 760, 56, "CPF / CNPJ", fmt_doc(loc.get("documento") or ""))
        y += 56
        f.caixa(m, y, 560, 56, "ESTABELECIMENTO", loc.get("estabelecimento") or "", 17)
        f.caixa(m + 560, y, w - 560, 56, "CÓDIGO DO ESTABELECIMENTO", loc.get("codigo_estabelecimento") or "")
        y += 56
        f.caixa(m, y, 560, 56, "MUNICÍPIO", loc.get("municipio_nome") or "")
        f.caixa(m + 560, y, 220, 56, "CÓD. IBGE", loc.get("municipio_ibge") or "")
        f.caixa(m + 780, y, w - 780, 56, "UF", loc.get("uf") or "")
        y += 70
    mt = g.get("meio_transporte") or {}
    f.caixa(m, y, 420, 56, "13 - FINALIDADE", g.get("finalidade") or "")
    f.caixa(m + 420, y, 400, 56, "14 - MEIO DE TRANSPORTE", mt.get("tipo") or "")
    f.caixa(m + 820, y, w - 820, 56, "PLACA", mt.get("placa") or "")
    y += 56
    vac = "; ".join(f"{v.get('doenca')} {v.get('data')}" for v in g.get("vacinacoes") or []) or "-"
    f.caixa(m, y, w, 56, "15 - VACINAÇÕES", vac, 16)
    y += 56
    obs = g.get("observacao") or ""
    f.caixa(m, y, w, 80, "17 - OBSERVAÇÕES")
    f.texto(m + 8, y + 24, obs[:95], 15)
    f.texto(m + 8, y + 48, obs[95:190], 15)
    y += 80
    em = g.get("emitente") or {}
    f.caixa(m, y, 600, 56, "18 - UNIDADE EXPEDIDORA", em.get("unidade_expedidora") or "", 16)
    f.caixa(m + 600, y, w - 600, 56, "19 - EMITENTE", f"{em.get('tipo') or ''} - {em.get('identificacao') or ''}",
            15)
    y += 56
    emi = g.get("emissao") or {}
    data = _data_br(emi.get("data"))
    f.caixa(m, y, 460, 56, "20 - LOCAL DE EMISSÃO", emi.get("local_municipio") or "")
    f.caixa(m + 460, y, 260, 56, "DATA DE EMISSÃO", data)
    f.caixa(m + 720, y, 160, 56, "HORA", emi.get("hora") or "")
    f.caixa(m + 880, y, w - 880, 56, "VÁLIDA ATÉ", _data_br(emi.get("validade")))
    y += 56
    chaves = ", ".join(g.get("nfe_chaves") or [])
    f.caixa(m, y, w, 56, "NF-E VINCULADA (CHAVE DE ACESSO)", fmt_chave(chaves) if len(chaves) == 44 else chaves,
            16, "mono")
    if g.get("sintetico"):
        f.marca_dagua("DOCUMENTO SINTÉTICO - SEM VALOR LEGAL", 54)
    return f.img


def _data_br(iso: str | None) -> str:
    if not iso:
        return ""
    a, mth, d = str(iso)[:10].split("-")
    return f"{d}/{mth}/{a}"


# ---------------------------------------------------------------------------
# Simulação de foto de celular
# ---------------------------------------------------------------------------

# Níveis de degradação (parâmetros explícitos; não calibrados contra fotos reais de campo).
NIVEIS: dict[str, dict[str, Any]] = {
    "limpa": {"rot": 0.0, "persp": 0.0, "blur": 0.0, "sombra": 0.0, "dobra": False, "lado": 1600, "jpeg": 90,
              "ruido": 0.0},
    "leve": {"rot": 2.0, "persp": 0.02, "blur": 0.6, "sombra": 0.25, "dobra": False, "lado": 1500, "jpeg": 82,
             "ruido": 3.0},
    "media": {"rot": 5.0, "persp": 0.04, "blur": 1.1, "sombra": 0.40, "dobra": True, "lado": 1250, "jpeg": 72,
              "ruido": 5.0},
    "pesada": {"rot": 9.0, "persp": 0.06, "blur": 1.7, "sombra": 0.55, "dobra": True, "lado": 950, "jpeg": 58,
               "ruido": 8.0},
}


def _coef_perspectiva(origem: list[tuple[float, float]], destino: list[tuple[float, float]]) -> list[float]:
    a = []
    b = []
    for (x, y), (u, v) in zip(destino, origem, strict=True):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        b += [u, v]
    return np.linalg.solve(np.array(a, dtype=float), np.array(b, dtype=float)).tolist()


def fotografar(img: Image.Image, nivel: str, rng: random.Random) -> tuple[Image.Image, dict[str, Any]]:
    """Simula a foto do papel: fundo de mesa, perspectiva, rotação, dobra, sombra, desfoque, ruído e redução."""
    p = NIVEIS[nivel]
    w, h = img.size
    meta: dict[str, Any] = {"nivel": nivel}
    if p["dobra"]:  # dobra horizontal: faixa mais escura + leve deslocamento
        y0 = int(h * rng.uniform(0.35, 0.65))
        arr = np.asarray(img).astype(np.float32)
        faixa = np.exp(-((np.arange(h) - y0) ** 2) / (2 * 6.0**2))[:, None, None]
        arr *= 1 - 0.35 * faixa
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        meta["dobra_y"] = y0
    # papel sobre fundo (mesa/capô) com margem, perspectiva e rotação
    margem = int(0.08 * max(w, h))
    fundo_cor = tuple(rng.randint(60, 140) for _ in range(3))
    tela = Image.new("RGB", (w + 2 * margem, h + 2 * margem), fundo_cor)
    tela.paste(img, (margem, margem))
    if p["persp"]:
        W, H = tela.size
        d = p["persp"] * W
        cantos = [(0, 0), (W, 0), (W, H), (0, H)]
        destino = [(x + rng.uniform(-d, d), y + rng.uniform(-d, d)) for x, y in cantos]
        tela = tela.transform(tela.size, Image.PERSPECTIVE, _coef_perspectiva(cantos, destino), Image.BICUBIC,
                              fillcolor=fundo_cor)
    ang = rng.uniform(-p["rot"], p["rot"])
    if ang:
        tela = tela.rotate(ang, resample=Image.BICUBIC, expand=False, fillcolor=fundo_cor)
    meta["rotacao_graus"] = round(ang, 2)
    if p["sombra"]:  # sombra (mão/celular) como gradiente diagonal
        W, H = tela.size
        xs, ys = np.meshgrid(np.linspace(0, 1, W), np.linspace(0, 1, H))
        th = rng.uniform(0, 2 * math.pi)
        g = (np.cos(th) * xs + np.sin(th) * ys)
        g = (g - g.min()) / (g.max() - g.min() + 1e-9)
        mascara = 1 - p["sombra"] * np.clip((g - 0.45) * 2.5, 0, 1)
        arr = np.asarray(tela).astype(np.float32) * mascara[:, :, None]
        tela = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    if p["blur"]:
        tela = tela.filter(ImageFilter.GaussianBlur(p["blur"]))
    if p["ruido"]:
        nrng = np.random.default_rng(rng.randrange(1 << 30))
        arr = np.asarray(tela).astype(np.float32) + nrng.normal(0, p["ruido"], (tela.size[1], tela.size[0], 1))
        tela = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    r = p["lado"] / max(tela.size)
    if r < 1:
        tela = tela.resize((round(tela.size[0] * r), round(tela.size[1] * r)), Image.LANCZOS)
    meta["tamanho"] = list(tela.size)
    meta["jpeg_q"] = p["jpeg"]
    return tela, meta


def jpeg_bytes(img: Image.Image, qualidade: int) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=qualidade, optimize=False)
    return buf.getvalue()


def pdf_bytes(img: Image.Image, dpi: float = 150.0, data: datetime | None = None) -> bytes:
    """PDF de uma página com a imagem (como um scan); o Pillow grava a imagem RGB com DCTDecode (JPEG).
    `data` fixa CreationDate/ModDate (sem ela, os bytes mudam a cada execução)."""
    buf = io.BytesIO()
    extra = {"creationDate": data.timetuple(), "modDate": data.timetuple()} if data else {}
    img.save(buf, "PDF", resolution=dpi, **extra)
    return buf.getvalue()
