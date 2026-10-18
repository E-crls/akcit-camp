"""Pacote de exibição BCB/Justiça: a fiscalização SELADA num ZIP que o supervisor do BCB ou um juiz conferem.

Por que existe: a IF responde pela fiscalização e guarda a documentação à disposição do BCB (MCR 2-7-1-d e
2-7-23); para pedir a reversão de uma desclassificação ela precisa de documentação por operação (IN BCB nº
758, DOU 10/07/2026); e a JF de Rio Verde/GO (decisão noticiada em 07/10/2026; a íntegra não foi lida)
suspendeu uma cobrança porque a IF não exibiu vetor, coordenadas, imagens datadas, meteorologia e fundamento.
O pacote junta isso num arquivo só.

Regras:
- **Só depois de SELADO** (assinatura humana com PIN e hash, POL-03). Antes disso a ação é negada
  (`BLOQUEADO_POLITICA`) e a decisão vai para o trace.
- **Ação humana, sem LLM**: botão da interface (`POST /api/fiscalizacoes/{id}/pacote`), `scripts/demo_cli.py
  --pacote` ou `scripts/py.sh -m laudo.tools.pacote`. Não é ferramenta do agente: fica fora do `REGISTRO`
  global (registro próprio, `ACOES_HUMANAS`), então as requisições ao LLM e os replays não mudam.
- **Nada muda no estado selado** (POL-04): o pacote é derivado do estado e do laudo selado, que vão dentro
  dele.
- **Só sai laudo que confere**: antes de montar, `laudo.audit.selo.verificar_laudo` confere selo,
  assinatura, conteúdo (hash raiz recalculado do rascunho assinado), cadeia, HTML e aprovações; se não
  conferir, o pacote não é gerado. O rascunho assinado vai junto (`laudo/rascunho_assinado.json`) e
  `validar_pacote` refaz a conferência só com o ZIP.
- **Nada é inventado**: o que falta sai como "ausente" ou "parcial", com o motivo; "não aplicável" só com
  justificativa e nunca conta como presente (checklist "Ordem JF Rio Verde" com status real por item).
- **PII (POL-08)**: CPF/CNPJ e chave de acesso da NF-e só mascarados; documentos fiscais (XML da NF-e, GTA,
  foto do DANFE) e vídeo entram por hash e referência, nunca o arquivo; fotos de campo e quadros-chave entram
  inteiros.
- **Demonstração**: operação sintética leva a marca d'água em toda página, no LEIA-ME e no nome do ZIP.

Conteúdo do ZIP (ver `ARQUIVOS_OBRIGATORIOS`): manifest com sha256 e tamanho de cada arquivo, laudo selado
(JSON e HTML, como foram assinados) e o rascunho assinado, GeoJSON da gleba e das fotos, cenas do satélite
(id, data, sensor, resoluções espacial e radiométrica e bandas, MCR 2-7-4-b; com a atribuição Copernicus),
fundamento por item (citação literal da norma) e das regras de documentos fiscais (resumo do catálogo, marcado
como não literal), memória de cálculo (contagem, conciliações, lotação), por que a operação caiu na amostra,
termo de ciência do mutuário com prazo de contestação, seção de reversão de desclassificação (IN BCB 758),
checklist "Ordem JF Rio Verde", cadeia de evidências e trace. `validar_pacote` confere tudo isso num ZIP já
gerado (teste de aceitação: `tests/unit/test_pacote_exibicao.py`).
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
import zipfile
from datetime import datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field

from laudo import demonstracao
from laudo.agent.pii import CNPJ, CPF, EMAIL, TELEFONE, mascarar
from laudo.audit import hashchain, otel
from laudo.contracts import CodigoErro, Envelope, Ferramenta, Fiscalizacao, registrar, sha256_bytes

VERSAO = "pacote-exibicao@0.1.0"
REPO = Path(__file__).resolve().parents[3]
_TEMPLATES = Path(__file__).resolve().parents[1] / "agent" / "templates"
_ENV = Environment(loader=FileSystemLoader(str(_TEMPLATES)), autoescape=select_autoescape(["html", "j2"]))

REGRA_LIBERACAO = "POL-03"  # o pacote só sai de fiscalização selada por assinatura humana
ACAO = "gerar_pacote_exibicao"
# Prazo para o mutuário contestar o resultado: parâmetro operacional da IF (não é norma), dentro dos 60 dias
# que a IF tem para desclassificar a contar da ciência do fato (MCR 2-8-3).
PAR_PRAZO = "PAR-pacote-prazo-contestacao-dias"
PRAZO_CONTESTACAO_DIAS = 15
MAX_ARQUIVO_EVIDENCIA = 25 * 1024 * 1024
MAX_TOTAL_EVIDENCIAS = 80 * 1024 * 1024
TIPOS_ARQUIVO_INCLUIDO = ("foto", "quadro_chave")  # documento fiscal, vídeo e áudio: só hash e referência

ITENS_ORDEM_JF = ("vetor_poligono", "coordenadas", "imagens_datadas", "meteorologia", "fundamento")
STATUS_CHECKLIST = ("presente", "parcial", "ausente", "nao_aplicavel")
ROTULO_CHECKLIST = {
    "presente": "presente",
    "parcial": "parcial",
    "ausente": "ausente",
    "nao_aplicavel": "não aplicável",
}

ARQ = {
    "manifest": "manifest.json",
    "leia_me": "LEIA-ME.txt",
    "indice_html": "pacote.html",
    "pacote_json": "pacote.json",
    "laudo_json": "laudo/laudo_selado.json",
    "laudo_html": "laudo/laudo_selado.html",
    "rascunho": "laudo/rascunho_assinado.json",
    "gleba": "geo/gleba.geojson",
    "fotos": "geo/fotos.geojson",
    "cenas": "satelite/cenas.json",
    "fundamento": "fundamento/fundamento_por_item.json",
    "memoria": "calculo/memoria_de_calculo.json",
    "amostra": "amostra/por_que_na_amostra.json",
    "ciencia_html": "mutuario/ciencia_e_contestacao.html",
    "ciencia": "mutuario/ciencia_e_contestacao.json",
    "reversao": "reversao/reversao_desclassificacao_in758.json",
    "checklist": "checklist/ordem_jf_rio_verde.json",
    "cadeia": "trilha/cadeia_de_evidencias.json",
    "trace": "trilha/trace.jsonl",
}
ARQUIVOS_OBRIGATORIOS = tuple(ARQ.values())

# trechos que nunca são dado pessoal e que a máscara confundiria: hash hexadecimal (11 dígitos de um sha256
# podem ter DV de CPF válido por acaso) e versão "nome@0.1.0" (parece e-mail). O hash precisa ter ao menos uma
# letra a-f: uma sequência só de dígitos (a chave de acesso da NF-e, 44 dígitos sem espaço) não é hash e passa
# pela máscara e pelo detector.
_RX_PROTEGIDO = re.compile(
    r"(?<![0-9A-Za-z])(?=[0-9]*[a-f])[0-9a-f]{16,}(?![0-9A-Za-z])|[\w.:/-]+@\d[\w.:-]*"
)
_RX_CHAVE_SEM_MASCARA = re.compile(
    r"(sha256|hash|selo|raiz|_id$|^id$|trace|span|url|uri|arquivo|caminho|^ids?_)", re.IGNORECASE
)
_RX_CHAVE_NFE = re.compile(r"(?<![0-9A-Za-z])\d(?:[ .]?\d){43}(?![0-9A-Za-z])")


class ErroPacote(Exception):
    def __init__(self, codigo: CodigoErro, msg: str, regra_id: str = REGRA_LIBERACAO):
        super().__init__(msg)
        self.codigo, self.msg, self.regra_id = codigo, msg, regra_id


# ---------------------------------------------------------------------------
# PII
# ---------------------------------------------------------------------------


def _mascarar_texto(s: str) -> str:
    """`mascarar` (POL-08) sem tocar em hash hexadecimal nem em versão `nome@x.y.z` (`_RX_PROTEGIDO`)."""
    partes, pos = [], 0
    for m in _RX_PROTEGIDO.finditer(s):
        partes += [mascarar(s[pos : m.start()]), m.group(0)]
        pos = m.end()
    partes.append(mascarar(s[pos:]))
    return "".join(partes)


def mascarar_obj(obj: Any, chave: str = "") -> Any:
    """Máscara recursiva para o que vai ao pacote; valores de chaves de hash, id, trace, url e caminho
    ficam."""
    if isinstance(obj, str):
        return obj if chave and _RX_CHAVE_SEM_MASCARA.search(chave) else _mascarar_texto(obj)
    if isinstance(obj, dict):
        return {k: mascarar_obj(v, str(k)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [mascarar_obj(v, chave) for v in obj]
    return obj


def pii_no_texto(texto: str) -> list[str]:
    """Tipos de dado pessoal à vista no texto (CPF, CNPJ, e-mail, telefone, chave de acesso inteira)."""
    limpo = _RX_PROTEGIDO.sub(" ", texto or "")
    m = mascarar(limpo, nomes=False)
    achados = [t for t in (CPF, CNPJ, EMAIL, TELEFONE) if t in m and t not in limpo]
    if _RX_CHAVE_NFE.search(limpo):
        achados.append("chave de acesso da NF-e sem máscara")
    return achados


# ---------------------------------------------------------------------------
# Texto literal das normas (docs/normas, a mesma fonte conferida pelos testes do rulebook)
# ---------------------------------------------------------------------------

_RX_LOC = re.compile(r"^MCR (\d+-\d+)-(\d+(?:-[A-Z])?)(?:-([a-z]))?(?:-([IVXL]+))?$")


@cache
def _textos_normativos() -> dict[tuple, str]:
    textos: dict[tuple, str] = {}
    for arq, padrao in (("mcr_2_7.md", "2-7"), ("mcr_2_9.md", "2-9")):
        p = REPO / "docs" / "normas" / arq
        if not p.is_file():
            continue
        secao = item = alinea = None
        for linha in p.read_text(encoding="utf-8").splitlines():
            s = linha.strip()
            if s.startswith("#"):
                m = re.search(r"(?:Seção|MCR) (\d+-\d+)", s)
                secao = m.group(1) if m else (padrao if "Texto literal" in s else None)
                item = alinea = None
                continue
            if secao is None or not s:
                continue
            if m := re.match(r"^(\d+(?:-[A-Z])?) - \S", s):
                item, alinea = m.group(1), None
                textos[(secao, item)] = s
            elif (m := re.match(r"^([a-z])\) \S", s)) and item:
                alinea = m.group(1)
                textos[(secao, item, alinea)] = s
            elif (m := re.match(r"^([IVXL]+) - \S", s)) and item:
                textos[(secao, item, alinea, m.group(1))] = s
    return textos


def trecho_literal(localizador: str) -> str | None:
    """`MCR 2-7-2-a-I` → texto literal do item (cabeça […] alínea […] inciso), de `docs/normas/`. None se o
    localizador não é simples ou o trecho não está no texto normativo do repositório (nunca inventa)."""
    m = _RX_LOC.match((localizador or "").strip())
    if not m:
        return None
    secao, item, alinea, inciso = m.groups()
    t = _textos_normativos()
    partes = [t.get((secao, item))]
    if alinea:
        partes.append(t.get((secao, item, alinea)))
    if inciso:
        partes.append(t.get((secao, item, alinea, inciso)))
    if any(p is None for p in partes):
        return None
    return " […] ".join(partes)  # type: ignore[arg-type]


def _fontes_rb(rb) -> list[dict[str, Any]]:
    return [{"descricao": f.descricao, "url": f.url, "acesso": f.acesso.isoformat()} for f in rb.fontes]


def fundamento(regra_id: str | None) -> dict[str, Any]:
    """Fundamento de uma regra: citação literal (norma), ou justificativa + citação literal da base normativa
    (parâmetro operacional), ou o resumo do catálogo de documentos fiscais (marcado como não literal)."""
    from laudo.rulebooks import buscar_regra

    rid = str(regra_id or "")
    try:
        rb, r = buscar_regra(rid)
    except KeyError:
        rb = r = None
    if r is not None:
        d: dict[str, Any] = {
            "regra_id": rid,
            "titulo": r.titulo,
            "item": r.item,
            "origem": r.origem,
            "rulebook": f"{rb.id}@{rb.versao}",
            "rulebook_sha256": rb.sha256,
            "texto_normativo": rb.texto_normativo,
            "fontes": _fontes_rb(rb),
        }
        if r.origem == "norma":
            return d | {
                "citacao_literal": r.citacao,
                "citacoes_adicionais": list(r.citacoes_adicionais),
                "status": "literal" if r.citacao else "sem_citacao",
            }
        base = [{"item": loc, "citacao_literal": trecho_literal(loc)} for loc in r.base_normativa]
        ok = [b for b in base if b["citacao_literal"]]
        st = "literal_na_base" if base and len(ok) == len(base) else ("parcial" if ok else "sem_citacao")
        return d | {
            "citacao_literal": None,
            "justificativa": r.justificativa,
            "base_normativa": base,
            "status": st,
            "aviso": "parâmetro operacional (escolha documentada da IF/do sistema), não é norma; a norma "
            "que ele executa vai citada literalmente em base_normativa",
        }
    from laudo.docs_fiscais.fontes import REGRAS

    if rid in REGRAS:
        x = REGRAS[rid]
        return {
            "regra_id": rid,
            "origem": "documentos_fiscais",
            "norma": x.get("norma"),
            "resumo": x.get("texto"),
            "url": x.get("url"),
            "citacao_literal": None,
            "status": "resumo",
            "aviso": "resumo do catálogo de documentos fiscais (laudo.docs_fiscais.fontes); texto literal "
                     "não conferido no repositório",
        }
    return {
        "regra_id": rid,
        "origem": "desconhecida",
        "citacao_literal": None,
        "status": "sem_citacao",
        "aviso": "regra sem citação no rulebook nem no catálogo de documentos fiscais (ex.: regra provisória "
        "ou de ferramenta simulada)",
    }


def tem_literal(f: dict[str, Any]) -> bool:
    return f.get("status") in ("literal", "literal_na_base")


# ---------------------------------------------------------------------------
# Por que caiu na amostra (motivos de laudo.geo.triagem)
# ---------------------------------------------------------------------------


def _criterios_triagem() -> list[tuple[str, re.Pattern, str, str]]:
    from laudo.geo.triagem import LIMIARES as L
    from laudo.geo.triagem import fmt

    def pct(x: float) -> str:
        return f"{fmt(100 * x, 0)}%"

    rx = lambda s: re.compile(s, re.IGNORECASE)
    lot = (
        f"quantidade financiada ÷ área informada (Sicor). Compra de matrizes/reprodutores (investimento): "
        f"acima de {fmt(L['lot_inv_1'], 0)} cab/ha +1, acima de {fmt(L['lot_inv_2'], 0)} +2, acima de "
        f"{fmt(L['lot_inv_3'], 0)} +3; aquisição para recria/engorda (custeio): acima de "
        f"{fmt(L['lot_cust_1'], 0)} +1, acima de {fmt(L['lot_cust_2'], 0)} +2. Confinamento não pontua."
    )
    sob = (
        f"fração da gleba sobreposta a outra operação da mesma safra: a partir de "
        f"{pct(L['sobrep_frac_alta'])} +2, a partir de {pct(L['sobrep_frac_baixa'])} +1; +1 se a outra "
        "operação é de outra IF"
    )
    area = (
        f"área dos polígonos ÷ área informada fora de {fmt(L['area_razao_min'], 1)} a "
        f"{fmt(L['area_razao_max'], 1)} +1"
    )
    valor = (
        "valor financiado por cabeça (ou UA) fora da faixa p1–p99 das operações semelhantes (mesma "
        "modalidade e unidade) +1"
    )
    reb = (
        f"quantidade financiada de {pct(L['frac_rebanho_mun'])} ou mais do rebanho bovino do município "
        "(IBGE PPM) +1"
    )
    return [
        ("LOTACAO_ALTA", rx(r"^lotação implícita"), "Lotação implícita alta", lot),
        ("SOBREPOSICAO_GLEBAS", rx(r"^gleba sobreposta"), "Gleba sobreposta a outra operação", sob),
        ("AREA_DIVERGENTE", rx(r"^área dos polígonos"), "Área dos polígonos × área informada", area),
        ("VALOR_CABECA_ATIPICO", rx(r"^valor financiado por"), "Valor por cabeça atípico", valor),
        (
            "FRACAO_REBANHO_MUNICIPAL",
            rx(r"^quantidade financiada equivale"),
            "Fração do rebanho do município",
            reb,
        ),
    ]


_ROT_NIVEL = {"alta": "alta", "media": "média", "baixa": "baixa", "sem_sinal": "sem sinal"}


def por_que_na_amostra(triagem: dict[str, Any] | None, compacto: bool = False) -> dict[str, Any]:
    """Abertura legível da prioridade de verificação: cada motivo com código, pontos e o critério de
    `laudo.geo.triagem` que o gerou, as observações (que não pontuam) e a regra do nível. Nunca acusa.
    `compacto` (lista da carteira) deixa de fora a citação literal do fundamento."""
    from laudo.geo.triagem import NIVEIS

    t = dict(triagem or {})
    aviso = "Prioridade de verificação não é indício de irregularidade: só orienta a amostra da fiscalização."
    base = {
        "aviso": aviso,
        "regra_nivel": "; ".join(f"{_ROT_NIVEL[n]}: {p} ponto(s) ou mais" for p, n in NIVEIS if p)
        + "; sem sinal: 0",
        "fundamento": []
        if compacto
        else [
            {"item": loc, "citacao_literal": trecho_literal(loc)}
            for loc in ("MCR 2-7-2-b-II", "MCR 2-7-2-b-IV")
        ],
        "nota": "Os limiares são parâmetros de triagem (laudo.geo.triagem.LIMIARES), não norma.",
        "fonte_versao": t.get("fonte_versao") or t.get("fonte"),
    }
    motivos = [str(m) for m in (t.get("motivos") or []) if m]
    if not t or (not motivos and t.get("prioridade_nivel") is None):
        return base | {
            "tem_triagem": False,
            "nivel": None,
            "nivel_rotulo": None,
            "pontos": None,
            "motivos": [],
            "observacoes": [],
            "resumo": "operação sem triagem registrada (aberta fora da carteira)",
        }
    codigos = [str(c) for c in (t.get("motivos_codigos") or t.get("codigos") or [])]
    crit = _criterios_triagem()
    saida = []
    for i, m in enumerate(motivos):
        mp = re.search(r"\s*\(\+(\d+)\)\s*$", m)
        texto = m[: mp.start()] if mp else m
        cod = (
            codigos[i]
            if i < len(codigos)
            else next((c for c, rx, _, _ in crit if rx.search(texto)), "SEM_CODIGO")
        )
        c = next((x for x in crit if x[0] == cod), None)
        saida.append(
            {
                "codigo": cod,
                "titulo": c[2] if c else "Motivo informado pelo caso",
                "texto": texto,
                "pontos": int(mp.group(1)) if mp else None,
                "criterio": c[3] if c else "motivo sem regra correspondente em laudo.geo.triagem",
            }
        )
    pontos = t.get("prioridade_verificacao")
    if pontos is None and any(x["pontos"] is not None for x in saida):
        pontos = sum(x["pontos"] or 0 for x in saida)
    nivel = t.get("prioridade_nivel")
    resumo = f"prioridade {_ROT_NIVEL.get(str(nivel), nivel or '—')}"
    if pontos is not None:
        resumo += f" ({pontos} ponto(s))"
    if saida:
        resumo += ": " + "; ".join(x["texto"] for x in saida)
    return base | {
        "tem_triagem": True,
        "nivel": nivel,
        "nivel_rotulo": _ROT_NIVEL.get(str(nivel), nivel),
        "pontos": pontos,
        "motivos": saida,
        "observacoes": [str(o) for o in (t.get("observacoes") or [])],
        "resumo": resumo,
    }


# ---------------------------------------------------------------------------
# Seções do pacote (funções puras sobre o estado selado)
# ---------------------------------------------------------------------------


def _iso(v: Any) -> str | None:
    if v is None:
        return None
    return v.isoformat() if hasattr(v, "isoformat") else str(v)


def _substituidas(fis: Fiscalizacao) -> set[str]:
    return {s for c in fis.checagens for s in (c.resultado.get("substitui") or [])}


def gleba_geojson(fis: Fiscalizacao) -> dict[str, Any]:
    """FeatureCollection (WGS84, RFC 7946) das glebas da operação, com área e centroide de cada uma."""
    from shapely import wkt as shp_wkt
    from shapely.geometry import mapping

    from laudo.geo.geometria import area_ha

    op = fis.operacao
    feats, erros = [], []
    for i, w in enumerate(op.glebas_wkt, 1):
        try:
            g = shp_wkt.loads(w)
        except Exception as e:  # noqa: BLE001 - WKT inválido vira erro declarado, não derruba o pacote
            erros.append(f"gleba {i}: WKT inválido ({type(e).__name__})")
            continue
        if g.is_empty or g.geom_type not in ("Polygon", "MultiPolygon"):
            erros.append(f"gleba {i}: geometria vazia ou não poligonal ({g.geom_type})")
            continue
        c = g.centroid
        feats.append(
            {
                "type": "Feature",
                "geometry": mapping(g),
                "properties": {
                    "gleba": i,
                    "ref_bacen": op.ref_bacen,
                    "area_ha": round(area_ha(g), 4),
                    "centroide": [round(c.x, 7), round(c.y, 7)],
                    "fonte": "Sicor/BCB (glebas públicas)" if op.fonte == "sicor" else op.fonte,
                    "valido": bool(g.is_valid),
                },
            }
        )
    out: dict[str, Any] = {
        "type": "FeatureCollection",
        "name": f"glebas_{op.ref_bacen}",
        "features": feats,
        "crs_nota": "WGS84 (EPSG:4326), ordem lon/lat (RFC 7946)",
    }
    if demonstracao.eh_demonstracao(op):
        out["demonstracao"] = demonstracao.bloco_laudo(op)
    if erros:
        out["erros"] = erros
    return out


def fotos_geojson(fis: Fiscalizacao, incluidas: dict[str, str]) -> dict[str, Any]:
    """Fotos de campo como pontos: coordenadas, precisão, horário de captura e de recebimento, geofence e
    integridade (o que as ferramentas registraram; nada recalculado)."""
    chks = [c for c in fis.checagens if c.id not in _substituidas(fis)]
    feats, sem_gps = [], []
    for e in fis.evidencias:
        if e.tipo != "foto":
            continue
        geo = next((c for c in reversed(chks) if c.ferramenta == "geofence" and e.id in c.evidencias), None)
        integ = next(
            (c for c in reversed(chks) if c.ferramenta == "integridade_foto" and e.id in c.evidencias), None
        )
        props = {
            "evidencia_id": e.id,
            "item_id": e.meta.get("item_id"),
            "sha256": e.sha256,
            "capturada_em": _iso(e.capturada_em),
            "recebida_em": _iso(e.recebida_em),
            "gps_fonte": e.gps.fonte if e.gps else None,
            "precisao_m": e.gps.precisao_m if e.gps else None,
            "gps_capturado_em": _iso(e.gps.capturada_em) if e.gps else None,
            "localizacao_simulada": e.gps.mock if e.gps else None,
            "arquivo_no_pacote": incluidas.get(e.id),
            "geofence": (
                {
                    "status": geo.status,
                    "checagem_id": geo.id,
                    "posicao": geo.resultado.get("posicao") or geo.resultado.get("status_ferramenta"),
                    "distancia_borda_m": geo.resultado.get("distancia_borda_m"),
                }
                if geo
                else None
            ),
            "integridade": (
                {
                    "status": integ.status,
                    "checagem_id": integ.id,
                    "exif": integ.resultado.get("exif"),
                    "gps_exif": integ.resultado.get("gps_exif"),
                    "delta_captura_s": integ.resultado.get("delta_captura_s"),
                }
                if integ
                else None
            ),
        }
        if e.gps is None:
            sem_gps.append(e.id)
            feats.append(
                {"type": "Feature", "geometry": None, "properties": props | {"motivo": "foto sem GPS"}}
            )
            continue
        feats.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(e.gps.lon, 7), round(e.gps.lat, 7)]},
                "properties": props,
            }
        )
    return {
        "type": "FeatureCollection",
        "name": f"fotos_{fis.operacao.ref_bacen}",
        "features": feats,
        "sem_gps": sem_gps,
        "crs_nota": "WGS84 (EPSG:4326), ordem lon/lat (RFC 7946)",
    }


def cenas_satelite(fis: Fiscalizacao) -> dict[str, Any]:
    """IDs de cena e metadados do sensoriamento remoto (MCR 2-7-4-b: satélite e sensor, datas, resoluções
    espacial e radiométrica, bandas, metodologia e uso). O que a ferramenta não informou fica dito."""
    ni = "não informado pela ferramenta"
    checks = [c for c in fis.checagens if c.ferramenta == "serie_ndvi"]
    if not checks:
        return {
            "aplicavel": False,
            "cenas": [],
            "checagens": [],
            "justificativa": "nenhuma checagem por sensoriamento remoto nesta fiscalização: o MCR 2-7-4-b só "
            "se aplica quando o método remoto é usado (a obrigatoriedade do item 5 é para "
            "área total acima de 300 ha em operação contratada a partir de 01/03/2026)",
        }
    try:
        from laudo.geo.stac import COLECAO, EARTH_SEARCH
    except Exception:  # noqa: BLE001 - sem o módulo STAC o pacote só não monta a URL da cena
        COLECAO = EARTH_SEARCH = None
    cenas, resumo = [], []
    for c in checks:
        r = c.resultado or {}
        meta = r.get("metadados_laudo") or r
        bandas = meta.get("bandas")
        bandas_lista = list(bandas) if isinstance(bandas, (dict, list)) else ([bandas] if bandas else [])
        sensor = meta.get("sensor") or ni
        produto = meta.get("produto")
        comum = {
            "checagem_id": c.id,
            "sensor": sensor,
            "produto": produto,
            "resolucao_espacial_m": meta.get("resolucao_m"),
            "resolucao_radiometrica_bits": meta.get("resolucao_radiometrica_bits")
            or meta.get("resolucao_radiometrica"),
            "bandas": bandas_lista,
            "bandas_descricao": bandas if isinstance(bandas, dict) else None,
        }
        resumo.append(
            comum
            | {
                "status": c.status,
                "fonte_versao": c.fonte_versao,
                "satelite": meta.get("satelite") or meta.get("plataforma") or ni,
                "datas": meta.get("datas") or [],
                "metodologia": meta.get("metodologia") or ni,
                "uso_na_fiscalizacao": meta.get("uso_na_fiscalizacao") or meta.get("uso") or ni,
                "resolucao_temporal": meta.get("resolucao_temporal"),
                "licenca": meta.get("licenca"),
                "n_cenas_stac": r.get("n_cenas_stac"),
                "erros": r.get("erros") or [],
            }
        )
        for o in r.get("serie") or []:
            if not isinstance(o, dict):
                continue
            cid = o.get("item_id") or o.get("id")
            url = (
                f"{EARTH_SEARCH}/collections/{COLECAO}/items/{cid}"
                if cid and COLECAO and produto and COLECAO in str(produto)
                else None
            )
            cenas.append(
                comum
                | {
                    "id_cena": cid,
                    "data": o.get("data"),
                    "plataforma": o.get("plataforma"),
                    "tile": o.get("tile"),
                    "nuvem_cena_pct": o.get("nuvem_cena"),
                    "frac_limpa": o.get("frac_limpa"),
                    "limpa": o.get("limpa"),
                    "ndvi_p50": o.get("ndvi_p50"),
                    "stac_url": url,
                }
            )
    sem_id = [x["data"] for x in cenas if not x.get("id_cena")]
    from laudo.tools.laudo import atribuicoes_dados

    out: dict[str, Any] = {
        "aplicavel": True,
        "cenas": cenas,
        "checagens": resumo,
        "regra_id": "MCR-2-7-item4-metadados-sr",
        # licença dos dados Copernicus: a atribuição acompanha qualquer uso de cena Sentinel-2
        "atribuicoes": atribuicoes_dados(fis),
    }
    if not cenas:
        out["motivo"] = "a ferramenta registrou o sensoriamento, mas não a lista de cenas (IDs)"
    elif sem_id:
        out["motivo"] = f"{len(sem_id)} cena(s) sem ID informado"
    return out


def fundamento_por_item(laudo: dict[str, Any]) -> list[dict[str, Any]]:
    from laudo.tools.laudo import _REGRA_AGREGACAO

    out = []
    for it in laudo.get("itens") or []:
        if it.get("regra_id") == _REGRA_AGREGACAO:
            continue
        f = fundamento(it.get("regra_id"))
        out.append(
            {
                "campo": it.get("campo"),
                "item_id": it.get("item_id"),
                "item_descricao": it.get("item_descricao"),
                "aspecto": it.get("aspecto"),
                "status": it.get("status"),
                "motivo": it.get("motivo"),
                "regra_id": it.get("regra_id"),
                "fundamento": f,
                "literal": tem_literal(f),
            }
        )
    return out


def fundamento_documentos_fiscais(fis: Fiscalizacao) -> list[dict[str, Any]]:
    """Fundamento das regras dos critérios das conciliações de NF-e e GTA (as que valem no laudo selado) e das
    conferências que ficaram fora do alcance offline. A regra do rulebook sai com a citação literal; a do
    catálogo de documentos fiscais sai como **resumo** (`status: resumo`, `literal: false`), nunca como
    citação."""
    subst = _substituidas(fis)
    por_regra: dict[str, dict[str, Any]] = {}
    for c in fis.checagens:
        if c.id in subst or c.ferramenta not in ("conciliar_nfe", "conciliar_gta"):
            continue
        r = c.resultado or {}
        crits = [x for x in r.get("criterios") or [] if isinstance(x, dict)]
        offline = [x for x in r.get("nao_verificado_offline") or [] if isinstance(x, dict)]
        for x, origem in [
            *((k, "criterio") for k in crits),
            *((k, "nao_verificado_offline") for k in offline),
        ]:
            rid = str(x.get("regra_id") or "")
            if not rid:
                continue
            d = por_regra.setdefault(rid, {"regra_id": rid, "ferramentas": [], "campos": [], "usos": []})
            for chave, valor in (
                ("ferramentas", c.ferramenta),
                ("campos", x.get("campo") or x.get("id")),
                ("usos", origem),
            ):
                if valor and valor not in d[chave]:
                    d[chave].append(valor)
    out = []
    for rid, d in sorted(por_regra.items()):
        f = fundamento(rid)
        out.append(d | {"fundamento": f, "status": f.get("status"), "literal": tem_literal(f)})
    return out


def _parametro(pid: str) -> Any:
    from laudo.rulebooks import todos

    for rb in todos():
        for p in rb.parametros:
            if p.id == pid:
                return p.valor
    return None


def memoria_de_calculo(
    fis: Fiscalizacao, laudo: dict[str, Any], triagem: dict[str, Any] | None
) -> dict[str, Any]:
    """Os números do laudo com a conta por trás: contagem × quantidade financiada (com a tolerância do
    rulebook), critérios das conciliações de NF-e e GTA e lotação implícita. Repete o que as ferramentas e o
    verificador registraram; a única conta nova é a aritmética de exibição (limite e lotação), que não muda
    status nenhum."""
    from laudo.geo.triagem import LIMIARES, classe_lotacao

    subst = _substituidas(fis)
    chks = [c for c in fis.checagens if c.id not in subst]
    evs = {e.id: e for e in fis.evidencias}
    itens = {i.id: i for i in fis.operacao.itens}
    campos_laudo = {it["campo"]: it for it in laudo.get("itens") or []}
    tol = _parametro("PAR-contagem-tolerancia-pct")

    contagens = []
    for c in chks:
        if c.ferramenta != "contar_bovinos_video":
            continue
        r = c.resultado or {}
        item = itens.get(c.item_id or "")
        q = item.quantidade if item else None
        limite = round(q * (1 - float(tol) / 100), 2) if q is not None and tol is not None else None
        iv = r.get("intervalo")
        campo = campos_laudo.get(f"item:{c.item_id}:quantidade") or {}
        contagens.append(
            {
                "checagem_id": c.id,
                "item_id": c.item_id,
                "status_checagem": c.status,
                "video": [
                    {"evidencia_id": x, "sha256": evs[x].sha256, "capturada_em": _iso(evs[x].capturada_em)}
                    for x in c.evidencias
                    if x in evs and evs[x].tipo == "video"
                ],
                "contagem": r.get("contagem"),
                "intervalo": iv,
                "abstencao": r.get("abstencao"),
                "metodo": r.get("metodo") or r.get("modo"),
                "modelo": r.get("modelo"),
                "versao": r.get("versao"),
                "conf_media": r.get("conf_media"),
                "oclusao": r.get("oclusao"),
                "quadros_chave": [
                    {
                        "t_s": q_.get("t_s"),
                        "contagem_ate_aqui": q_.get("contagem_ate_aqui"),
                        "sha256": q_.get("sha256"),
                    }
                    for q_ in (r.get("quadros_chave") or [])
                    if isinstance(q_, dict)
                ],
                "quantidade_financiada": q,
                "unidade": item.unidade if item else None,
                "tolerancia_pct": tol,
                "parametro": "PAR-contagem-tolerancia-pct",
                "limite": limite,
                "formula": "limite = Q × (1 − tolerância); verificado se inferior ≥ limite; divergente "
                "se superior < limite; senão pendente (OP-bovinos-contagem-tolerancia)",
                "status_campo": campo.get("status"),
                "motivo_campo": campo.get("motivo"),
                "justificativa_humana": campo.get("justificativa_humana"),
            }
        )

    conciliacoes = []
    for c in chks:
        if c.ferramenta not in ("conciliar_nfe", "conciliar_gta"):
            continue
        r = c.resultado or {}
        conciliacoes.append(
            {
                "checagem_id": c.id,
                "ferramenta": c.ferramenta,
                "item_id": c.item_id,
                "status": c.status,
                "motivo": r.get("motivo"),
                "evidencias": [
                    {"evidencia_id": x, "tipo": evs[x].tipo, "sha256": evs[x].sha256}
                    for x in c.evidencias
                    if x in evs
                ],
                "criterios": [
                    {k: x.get(k) for k in ("campo", "status", "regra_id", "motivo")}
                    for x in (r.get("criterios") or [])
                    if isinstance(x, dict)
                ],
                "totais": r.get("totais"),
                "nao_verificado_offline": [
                    {k: x.get(k) for k in ("id", "regra_id", "motivo")}
                    for x in (r.get("nao_verificado_offline") or [])
                    if isinstance(x, dict)
                ],
                "simulada": bool(r.get("fake")),
            }
        )

    lot_chks = [c for c in chks if c.ferramenta == "checar_lotacao"]
    lotacao: dict[str, Any]
    if lot_chks:
        lotacao = {
            "origem": "checar_lotacao",
            "checagens": [
                {
                    "checagem_id": c.id,
                    "status": c.status,
                    **{
                        k: c.resultado.get(k)
                        for k in (
                            "cabecas",
                            "unidade",
                            "area_ha",
                            "lotacao_cab_ha",
                            "classe",
                            "pontos_triagem",
                            "municipio",
                            "razao_lotacao_densidade_municipal",
                            "fracao_rebanho_municipal",
                            "texto",
                        )
                    },
                }
                for c in lot_chks
            ],
        }
    else:
        op = fis.operacao
        bov = [i for i in op.itens if i.tipo == "bovinos" and i.quantidade]
        area = op.area_informada_ha or op.area_financiada_ha
        compra = {"investimento": "investimento", "custeio": "custeio"}.get(str(op.finalidade))
        if not bov:
            lotacao = {"origem": "nao_aplicavel", "motivo": "operação sem item de bovinos com quantidade"}
        elif not area:
            lotacao = {
                "origem": "indeterminada",
                "motivo": "sem área informada: lotação implícita indeterminada",
            }
        else:
            cab = sum(float(i.quantidade or 0) for i in bov)
            lot = cab / float(area)
            pontos, rotulo = classe_lotacao(lot, compra)
            lotacao = {
                "origem": "calculada_no_pacote",
                "cabecas": cab,
                "area_ha": area,
                "area_fonte": "área informada"
                if op.area_informada_ha
                else "área financiada (VL_AREA_FINANC)",
                "lotacao_cab_ha": round(lot, 4),
                "compra": compra,
                "classe": rotulo or "dentro dos limiares",
                "pontos_triagem": pontos,
                "formula": "lotação = cabeças financiadas ÷ área (ha)",
                "limiares": {k: v for k, v in LIMIARES.items() if k.startswith("lot_")},
                "ressalva": "a área do Sicor é proporcional ao crédito e pode não ser o pasto; a lotação é "
                "sinal de triagem (prioridade de verificação), nunca divergência",
            }
            t = triagem or {}
            if t.get("lotacao_implicita_cab_ha") is not None:
                lotacao["triagem_registrada_cab_ha"] = t.get("lotacao_implicita_cab_ha")
            if t.get("densidade_bovina_mun_cab_ha"):
                lotacao["densidade_bovina_mun_cab_ha"] = t.get("densidade_bovina_mun_cab_ha")
                lotacao["razao_densidade_municipal"] = round(lot / float(t["densidade_bovina_mun_cab_ha"]), 2)
    return {
        "contagem": contagens or [{"nao_aplicavel": True, "motivo": "nenhuma contagem de animais"}],
        "conciliacoes": conciliacoes
        or [{"nao_aplicavel": True, "motivo": "nenhuma conciliação de NF-e/GTA"}],
        "conciliacao_alegacoes": laudo.get("alegacoes_x_evidencia") or [],
        "lotacao": lotacao,
        "nota": "Valores registrados pelas ferramentas determinísticas; o status de cada campo é o do "
                "verificador no laudo selado. O modelo de linguagem não calculou nada aqui.",
    }


def _meteorologia(fis: Fiscalizacao, laudo: dict[str, Any]) -> dict[str, Any]:
    """Meteorologia só é "não aplicável" quando nenhuma conclusão depende de clima: sem lavoura/pastagem
    financiada, sem comprovação de perdas e sem campo não verificado apoiado no satélite. Caso contrário é
    "ausente" (o Laudo Vivo não coleta meteorologia nesta versão), nunca "presente" por aproximação."""
    tipos = {i.tipo for i in fis.operacao.itens}
    sat = {c.id for c in fis.checagens if c.ferramenta == "serie_ndvi"}
    pelo_satelite = [
        it["campo"]
        for it in laudo.get("itens") or []
        if it.get("status") != "verificado"
        and (
            str(it.get("campo", "")).endswith(":ndvi")
            or sat & {c.get("id") for c in it.get("checagens") or []}
        )
    ]
    aplicavel = (
        fis.tipo == "comprovacao_perdas" or bool(tipos & {"lavoura", "pastagem"}) or bool(pelo_satelite)
    )
    if aplicavel:
        return {
            "status": "ausente",
            "evidencias": [],
            "motivo": "a conclusão depende de condição de cultivo/pastagem, de perda ou do satélite"
            + (f" ({', '.join(pelo_satelite)})" if pelo_satelite else "")
            + ", e o pacote não tem dado meteorológico (o Laudo Vivo não coleta meteorologia nesta "
            "versão)",
        }
    just = (
        "operação com animais e benfeitorias: as conclusões do laudo vêm de contagem, documentos (NF-e, "
        "GTA) e fotos georreferenciadas, e nenhuma depende de condição meteorológica."
    )
    if sat:
        just += (
            " A série de NDVI (MCR 2-7-9, pastagem) é informativa, com as cenas nubladas descartadas pela "
            "máscara de nuvem, e nenhum campo não verificado se apoia nela."
        )
    else:
        just += " Não houve sensoriamento remoto nesta fiscalização."
    return {"status": "nao_aplicavel", "evidencias": [], "justificativa": just}


def checklist_ordem_jf(
    fis: Fiscalizacao,
    laudo: dict[str, Any],
    gleba: dict[str, Any],
    fotos: dict[str, Any],
    cenas: dict[str, Any],
    fund: list[dict[str, Any]],
    fund_docs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """O que a decisão da JF de Rio Verde/GO (noticiada em 07/10/2026; a íntegra não foi lida) mandou a IF
    exibir, com o status real de cada item nesta fiscalização. "Não aplicável" exige justificativa e não conta
    como presente. O fundamento conta os campos do laudo **e** as regras de documentos fiscais: resumo não é
    citação literal, e o item só fica "presente" se tudo for literal."""
    itens: list[dict[str, Any]] = []
    n_gl = len(gleba.get("features") or [])
    itens.append(
        {
            "id": "vetor_poligono",
            "titulo": "Vetor/polígono da área",
            "status": "presente" if n_gl and not gleba.get("erros") else ("parcial" if n_gl else "ausente"),
            "evidencias": [ARQ["gleba"]] if n_gl else [],
            "motivo": f"{n_gl} polígono(s) em WGS84" if n_gl else "operação sem polígono público da gleba",
        }
    )
    fts = fotos.get("features") or []
    com_gps = [f for f in fts if f.get("geometry")]
    st_coord = "ausente" if not com_gps else ("presente" if len(com_gps) == len(fts) else "parcial")
    itens.append(
        {
            "id": "coordenadas",
            "titulo": "Coordenadas das evidências de campo",
            "status": st_coord,
            "evidencias": [ARQ["fotos"]] if com_gps else [],
            "motivo": f"{len(com_gps)} de {len(fts)} foto(s) com GPS" if fts else "nenhuma foto de campo",
        }
    )
    fotos_datadas = [f for f in fts if (f.get("properties") or {}).get("capturada_em")]
    cenas_datadas = [c for c in cenas.get("cenas") or [] if c.get("data")]
    videos = [e for e in fis.evidencias if e.tipo == "video" and e.capturada_em]
    partes = [
        f"{len(fotos_datadas)} de {len(fts)} foto(s) com horário de captura",
        f"{len(cenas_datadas)} cena(s) de satélite datada(s)",
        f"{len(videos)} vídeo(s) com horário",
    ]
    if not fotos_datadas and not cenas_datadas and not videos:
        st_img = "ausente"
    elif len(fotos_datadas) < len(fts) or (cenas.get("aplicavel") and not cenas_datadas):
        st_img = "parcial"
    else:
        st_img = "presente"
    itens.append(
        {
            "id": "imagens_datadas",
            "titulo": "Imagens com data",
            "status": st_img,
            "evidencias": [
                x for x, ok in ((ARQ["fotos"], fotos_datadas), (ARQ["cenas"], cenas_datadas)) if ok
            ],
            "motivo": "; ".join(partes),
        }
    )
    met = _meteorologia(fis, laudo)
    itens.append({"id": "meteorologia", "titulo": "Dados meteorológicos", **met})
    docs = list(fund_docs or [])
    com_lit = [f for f in fund if f["literal"]]
    docs_lit = [f for f in docs if f["literal"]]
    total, literais = len(fund) + len(docs), len(com_lit) + len(docs_lit)
    st_f = "ausente" if not literais else ("presente" if literais == total else "parcial")
    sem = [f["campo"] for f in fund if not f["literal"]]
    resumo_docs = [f["regra_id"] for f in docs if not f["literal"]]
    motivo = f"{len(com_lit)} de {len(fund)} campo(s) do laudo com citação literal"
    if docs:
        lista = ", ".join(resumo_docs[:4]) + (
            f" e mais {len(resumo_docs) - 4}" if len(resumo_docs) > 4 else ""
        )
        motivo += f"; {len(docs_lit)} de {len(docs)} regra(s) de documentos fiscais com citação literal" + (
            f" (as demais só em resumo, não literal: {lista})" if resumo_docs else ""
        )
    if sem:
        motivo += f"; campos sem citação literal: {', '.join(sem)}"
    itens.append(
        {
            "id": "fundamento",
            "titulo": "Fundamento normativo por item",
            "status": st_f,
            "evidencias": [ARQ["fundamento"]] if fund or docs else [],
            "motivo": motivo,
            "contagem": {
                "literais": literais,
                "total": total,
                "campos_literais": len(com_lit),
                "campos": len(fund),
                "documentos_literais": len(docs_lit),
                "documentos": len(docs),
            },
        }
    )
    for it in itens:
        it["rotulo"] = ROTULO_CHECKLIST[it["status"]]
    cont = {s: sum(1 for i in itens if i["status"] == s) for s in STATUS_CHECKLIST}
    return {
        "referencia": "JF Rio Verde/GO, decisão noticiada em 07/10/2026 (a íntegra não foi lida): ordem de "
        "exibir vetor/polígono, coordenadas, imagens datadas, meteorologia e fundamento",
        "itens": itens,
        "contagem": cont,
        "resumo": f"{cont['presente']} presente(s), {cont['parcial']} parcial(is), {cont['ausente']} "
                  f"ausente(s), {cont['nao_aplicavel']} não aplicável(is) com justificativa",
        "nota": 'Status real por item; "não aplicável" exige justificativa e não conta como presente.',
    }


def ciencia_mutuario(
    fis: Fiscalizacao, laudo: dict[str, Any], selado_em: datetime | None, prazo_dias: int
) -> dict[str, Any]:
    from laudo.tools.laudo import _REGRA_AGREGACAO

    achados = [
        {
            "campo": it["campo"],
            "item_descricao": it.get("item_descricao"),
            "aspecto": it.get("aspecto"),
            "status": it["status"],
            "status_rotulo": it.get("status_rotulo"),
            "motivo": it.get("motivo"),
            "justificativa_humana": it.get("justificativa_humana"),
            "evidencias": [e.get("id") for e in it.get("evidencias") or []],
        }
        for it in laudo.get("itens") or []
        if it.get("regra_id") != _REGRA_AGREGACAO
    ]
    contestaveis = [a for a in achados if a["status"] in ("divergente", "pendente", "abstencao")]
    ref = selado_em.date() if selado_em else None
    return {
        "status": "aguardando_ciencia_do_mutuario",
        "prazo_contestacao_dias": prazo_dias,
        "parametro": PAR_PRAZO,
        "prazo_regra": f"{prazo_dias} dias corridos contados da data da ciência registrada no termo "
                       "(parâmetro operacional da IF, não é norma)",
        "exemplo_data_limite_se_ciente_no_selo": (ref + timedelta(days=prazo_dias)).isoformat()
        if ref
        else None,
        "selado_em": _iso(selado_em),
        "tomador_ref": fis.operacao.tomador_ref,
        "achados": achados,
        "contestaveis": contestaveis,
        "como_contestar": "apresentar à IF, dentro do prazo, documento ou nova evidência sobre o item "
                          "contestado (ex.: vídeo do lote completo, GTA, nota). O laudo selado não muda: a "
                          "contestação aceita vira nova fiscalização, com nova evidência e nova assinatura "
                          "humana (POL-04).",
        "base": [
            {"item": loc, "citacao_literal": trecho_literal(loc)} for loc in ("MCR 2-8-3", "MCR 2-7-18")
        ],
        "nota_pii": "o termo usa só o pseudônimo do tomador; documento de identificação é conferido pela IF "
                    "e não é anotado neste pacote",
    }


def in758_literal() -> dict[str, Any] | None:
    """Citação literal da IN BCB nº 758 (nota do Campo 60-B, alíneas b, c e e) **conferida por sha256** em
    `docs/normas/in_bcb_758.md`, lida por `laudo.rulebooks.normas.citacao_reversao()` (a única leitura do
    arquivo; aqui não se interpreta título nem tabela). None se o arquivo não está lá ou mudou depois da
    conferência: o pacote então diz "não conferida" e não cita o artigo (nunca inventa)."""
    try:
        from laudo.rulebooks import normas
    except ImportError:  # pragma: no cover - a área de Regras sempre entrega o módulo
        return None
    c = normas.citacao_reversao()
    if not c or not c.get("citacao_conferida") or not c.get("citacao_literal"):
        return None
    return {
        "citacao_literal": c["citacao_literal"],
        "localizador": c.get("localizador"),
        "arquivo": c.get("texto_normativo"),
        "url": c.get("url"),
        "acesso": c.get("acesso"),
        "fonte": c.get("norma"),
    }


def _data_br(iso: str | None) -> str | None:
    """`2026-10-16` → `16/10/2026` (texto de exibição); outra forma passa como está."""
    if iso and re.fullmatch(r"\d{4}-\d{2}-\d{2}", iso):
        a, m, d = iso.split("-")
        return f"{d}/{m}/{a}"
    return iso


def reversao_in758(
    laudo: dict[str, Any], checklist: dict[str, Any], fund: list[dict[str, Any]]
) -> dict[str, Any]:
    sustentam = [f["campo"] for f in fund if f["status"] == "verificado"]
    nao = [
        {
            "campo": f["campo"],
            # rótulo para o texto lido por gente: "Aquisição de 29 vacas leiteiras: Quantidade
            # (contagem)"
            "rotulo": ": ".join(
                x for x in ((f.get("item_descricao") or "").split(" (")[0], f.get("aspecto")) if x
            )
            or f["campo"],
            "status": f["status"],
            "motivo": f.get("motivo"),
        }
        for f in fund
        if f["status"] != "verificado"
    ]
    lit = in758_literal()
    return {
        "norma": "IN BCB nº 758 (DOU 10/07/2026)",
        "o_que_pede": "documentação por operação para a IF pedir a reversão de uma desclassificação",
        "citacao_literal": lit["citacao_literal"] if lit else None,
        "citacao_conferida": bool(lit),
        "localizador": lit["localizador"] if lit else None,
        "fonte_literal": {k: lit[k] for k in ("arquivo", "url", "acesso", "fonte")} if lit else None,
        "aviso": (
            f"texto literal ({lit['localizador']}) conferido contra a fonte oficial ({lit['url']}, acesso em "
            f"{_data_br(lit['acesso'])}) e amarrado por sha256 em {lit['arquivo']}"
        )
        if lit
        else (
            "o texto literal da IN BCB 758 não está conferido em docs/normas (arquivo ausente ou alterado "
            "depois da conferência); conferir no buscador de normativos do BCB antes de citar o artigo no "
            "pedido"
        ),
        "base_mcr": [
            {"item": loc, "citacao_literal": trecho_literal(loc)}
            for loc in ("MCR 2-7-19", "MCR 2-7-20", "MCR 2-7-23")
        ]
        + [
            {
                "item": "MCR 2-8-2-i",
                "citacao_literal": fundamento("MCR-2-8-item2-aplicacao-nao-comprovada").get(
                    "citacao_literal"
                ),
            }
        ],
        "documentacao_desta_operacao": [
            {
                "documento": "laudo selado (JSON e HTML) com hash raiz assinado e selo",
                "arquivos": [ARQ["laudo_json"], ARQ["laudo_html"]],
            },
            {
                "documento": "trilha: cadeia de evidências encadeada por hash e trace OpenTelemetry",
                "arquivos": [ARQ["cadeia"], ARQ["trace"]],
            },
            {
                "documento": "georreferência: polígono da gleba e pontos das fotos",
                "arquivos": [ARQ["gleba"], ARQ["fotos"]],
            },
            {"documento": "sensoriamento remoto (MCR 2-7-4-b)", "arquivos": [ARQ["cenas"]]},
            {"documento": "fundamento normativo por item", "arquivos": [ARQ["fundamento"]]},
            {"documento": "memória de cálculo", "arquivos": [ARQ["memoria"]]},
            {"documento": "ciência do mutuário e prazo de contestação", "arquivos": [ARQ["ciencia_html"]]},
            {"documento": "checklist da ordem judicial (JF Rio Verde)", "arquivos": [ARQ["checklist"]]},
        ],
        "itens_que_sustentam_aplicacao": sustentam,
        "itens_que_nao_sustentam": nao,
        "checklist_jf_resumo": checklist.get("resumo"),
        "leitura": "Itens verificados sustentam a comprovação da aplicação (MCR 2-8-2-i trata de aplicação "
                   "não comprovada); itens divergentes ou pendentes vão como estão, com motivo e "
                   "justificativa do fiscal: o pacote não esconde o que não fecha.",
    }


def cadeia_evidencias(fis: Fiscalizacao, incluidas: dict[str, str]) -> dict[str, Any]:
    cad = hashchain.verificar_cadeia(fis.evidencias)
    evs = []
    for e in fis.evidencias:
        d = {
            "id": e.id,
            "tipo": e.tipo,
            "sha256": e.sha256,
            "hash_anterior": e.hash_anterior,
            "hash_elo": hashchain.hash_elo(e),
            "capturada_em": _iso(e.capturada_em),
            "recebida_em": _iso(e.recebida_em),
            "gps": e.gps.model_dump(mode="json") if e.gps else None,
            "item_id": e.meta.get("item_id"),
            "arquivo_no_pacote": incluidas.get(e.id),
            "fora_do_pacote": None
            if e.id in incluidas or not e.caminho
            else (
                "documento fiscal/vídeo: só hash e referência (PII e tamanho); original sob guarda da IF "
                "(MCR 2-7-23)"
            ),
        }
        if e.tipo == "declaracao":
            d["texto"] = e.meta.get("texto")
        elif e.tipo == "ocorrencia":
            d["descricao"], d["ocorrencia_tipo"] = e.meta.get("descricao"), e.meta.get("tipo")
        evs.append(d)
    return {"integra": cad.integra, "raiz": cad.raiz, "n": cad.n, "motivo": cad.motivo, "evidencias": evs}


# ---------------------------------------------------------------------------
# Montagem do ZIP
# ---------------------------------------------------------------------------


def _laudo_selado(dir_laudos: Path) -> tuple[dict[str, Any], bytes, bytes]:
    pj, ph = dir_laudos / "laudo_selado.json", dir_laudos / "laudo_selado.html"
    if not pj.is_file() or not ph.is_file():
        raise ErroPacote(CodigoErro.SEM_DADOS, "laudo selado não encontrado no disco")
    bj = pj.read_bytes()
    return json.loads(bj.decode("utf-8")), bj, ph.read_bytes()


def _rascunho_da_cadeia(fis: Fiscalizacao, laudo: dict[str, Any]) -> bytes | None:
    """Bytes do rascunho assinado (a evidência `documento` com `meta.laudo` e o hash raiz do laudo selado), se
    o arquivo está no disco e é o registrado na cadeia."""
    h = laudo.get("hash_raiz")
    ev = next(
        (
            e
            for e in reversed(fis.evidencias)
            if e.tipo == "documento" and e.meta.get("laudo") and e.meta.get("hash_raiz") == h
        ),
        None,
    )
    if ev is None or not ev.caminho or not Path(ev.caminho).is_file():
        return None
    b = Path(ev.caminho).read_bytes()
    return b if sha256_bytes(b) == ev.sha256 else None


def _integridade(fis: Fiscalizacao, laudo: dict[str, Any], bj: bytes, bh: bytes) -> dict[str, Any]:
    """Conferência completa do laudo selado (`laudo.audit.selo.verificar_laudo`): selo, assinatura, conteúdo
    (hash raiz recalculado do conteúdo assinado), cadeia de evidências, HTML e aprovações da fiscalização."""
    from laudo.audit import selo as selo_mod

    res = selo_mod.verificar_laudo(
        laudo,
        evidencias=fis.evidencias,
        aprovacoes=[a.model_dump(mode="json") for a in fis.aprovacoes],
        html=bh,
    )
    cad = hashchain.verificar_cadeia(fis.evidencias)
    aprov = fis.aprovacoes[-1] if fis.aprovacoes else None
    return {
        "valido": res.valido,
        "verificacao": res.motivo,
        "selo": laudo.get("selo"),
        "selo_confere": res.selo_confere,
        "hash_raiz_assinado": laudo.get("hash_raiz"),
        "hash_raiz_confere_assinatura": bool(aprov and aprov.hash_assinado == laudo.get("hash_raiz"))
        and res.assinatura_confere,
        "conteudo_confere": res.conteudo_confere,
        "hash_raiz_recalculado": res.hash_raiz_recalculado,
        "origem_conteudo": res.origem_conteudo,
        "cadeia_confere": res.cadeia_confere,
        "html_confere": res.html_confere,
        "aprovacoes_conferem": res.aprovacoes_conferem,
        "avisos": list(res.avisos),
        "raiz_cadeia_no_selo": (laudo.get("cadeia") or {}).get("raiz"),
        "raiz_cadeia_atual": cad.raiz,
        "cadeia_integra": cad.integra,
        "sha256_laudo_selado_json": sha256_bytes(bj),
    }


def _triagem_do_estado(fis: Fiscalizacao) -> dict[str, Any]:
    c = next(
        (c for c in fis.checagens if c.ferramenta == "carregar_operacao" and c.resultado.get("triagem")), None
    )
    return dict(c.resultado["triagem"]) if c else {}


def nome_zip(fis: Fiscalizacao, selo: str) -> str:
    ref = re.sub(r"[^0-9A-Za-z_-]+", "_", fis.operacao.ref_bacen)[:40]
    pref = "DEMONSTRACAO_" if demonstracao.eh_demonstracao(fis.operacao) else ""
    return f"{pref}pacote_exibicao_{ref}_{(selo or 'sem-selo')[:12]}.zip"


def montar(
    fis: Fiscalizacao,
    dir_laudos: Path,
    arquivo_trace: Path | None = None,
    triagem: dict[str, Any] | None = None,
    prazo_dias: int = PRAZO_CONTESTACAO_DIAS,
    agora: datetime | None = None,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    """Arquivos do pacote (caminho no ZIP → bytes, sem o manifest) e o `pacote.json` (todas as seções)."""
    if fis.estado_fsm != "SELADO" or not fis.aprovacoes:
        raise ErroPacote(
            CodigoErro.BLOQUEADO_POLITICA,
            f"fiscalização em {fis.estado_fsm}: o pacote de exibição só é liberado depois de SELADO "
            "(assinatura humana com PIN e hash, POL-03)",
        )
    laudo, bj, bh = _laudo_selado(Path(dir_laudos))
    if laudo.get("tipo") != "selado":
        raise ErroPacote(CodigoErro.BLOQUEADO_POLITICA, "o laudo no disco não é o selado")
    integ = _integridade(fis, laudo, bj, bh)
    if not integ["valido"] or not integ["hash_raiz_confere_assinatura"]:
        raise ErroPacote(
            CodigoErro.ENTRADA_INVALIDA,
            f"laudo selado não confere ({integ['verificacao'][:300]}): pacote não gerado",
            regra_id="POL-04",
        )
    br = _rascunho_da_cadeia(fis, laudo)
    if br is None:  # verificar_laudo já exigiu o rascunho da cadeia; aqui só por segurança
        raise ErroPacote(
            CodigoErro.ENTRADA_INVALIDA, "rascunho assinado ausente: pacote não gerado", regra_id="POL-04"
        )
    agora = agora or datetime.now().astimezone()
    demo = demonstracao.bloco_laudo(fis.operacao)
    arquivos: dict[str, bytes] = {}

    def j(obj: Any) -> bytes:
        return json.dumps(obj, ensure_ascii=False, indent=1, default=str).encode("utf-8")

    # evidências com arquivo (fotos de campo e quadros-chave); documentos fiscais e vídeo só por hash
    incluidas: dict[str, str] = {}
    total = 0
    for e in fis.evidencias:
        if e.tipo not in TIPOS_ARQUIVO_INCLUIDO or not e.caminho:
            continue
        p = Path(e.caminho)
        if (
            not p.is_file()
            or p.stat().st_size > MAX_ARQUIVO_EVIDENCIA
            or total + p.stat().st_size > MAX_TOTAL_EVIDENCIAS
        ):
            continue
        b = p.read_bytes()
        if sha256_bytes(b) != e.sha256 and e.tipo == "foto":
            continue  # arquivo trocado depois do registro: não entra como se fosse a prova
        nome = re.sub(r"[^0-9A-Za-z._-]+", "_", p.name)[:80]
        destino = f"evidencias/{e.id}_{nome}"
        arquivos[destino] = b
        incluidas[e.id] = destino
        total += len(b)

    pii_laudo = (
        pii_no_texto(bj.decode("utf-8", "replace"))
        + pii_no_texto(bh.decode("utf-8", "replace"))
        + pii_no_texto(br.decode("utf-8", "replace"))
    )
    if pii_laudo:  # o selado não deveria ter PII; se tiver, vai a cópia mascarada e o hash do original
        arquivos[ARQ["laudo_json"]] = j(mascarar_obj(laudo))
        arquivos[ARQ["laudo_html"]] = _mascarar_texto(bh.decode("utf-8", "replace")).encode("utf-8")
        arquivos[ARQ["rascunho"]] = j(mascarar_obj(json.loads(br.decode("utf-8"))))
    else:
        arquivos[ARQ["laudo_json"]], arquivos[ARQ["laudo_html"]], arquivos[ARQ["rascunho"]] = bj, bh, br
    tri = triagem if triagem else _triagem_do_estado(fis)
    gleba = gleba_geojson(fis)
    fotos = mascarar_obj(fotos_geojson(fis, incluidas))
    cenas = cenas_satelite(fis)
    fund = mascarar_obj(fundamento_por_item(laudo))
    fund_docs = mascarar_obj(fundamento_documentos_fiscais(fis))
    memoria = mascarar_obj(memoria_de_calculo(fis, laudo, tri))
    amostra = mascarar_obj(por_que_na_amostra(tri))
    checklist = checklist_ordem_jf(fis, laudo, gleba, fotos, cenas, fund, fund_docs)
    selado_em = fis.aprovacoes[-1].em
    ciencia = mascarar_obj(ciencia_mutuario(fis, laudo, selado_em, prazo_dias))
    reversao = mascarar_obj(reversao_in758(laudo, checklist, fund))
    cadeia = mascarar_obj(cadeia_evidencias(fis, incluidas))
    op = fis.operacao
    pacote = {
        "versao": VERSAO,
        "tipo": "pacote_exibicao",
        "gerado_em": agora.isoformat(timespec="seconds"),
        "demonstracao": demo,
        "fiscalizacao_id": fis.id,
        "operacao": mascarar_obj(
            {
                "ref_bacen": op.ref_bacen,
                "tomador_ref": op.tomador_ref,
                "uf": op.uf,
                "municipio_ibge": op.municipio_ibge,
                "municipio_nome": op.municipio_nome,
                "instituicao": op.instituicao,
                "finalidade": op.finalidade,
                "empreendimento": op.empreendimento,
                "data_contratacao": _iso(op.data_contratacao),
                "valor_rs": op.valor_rs,
                "area_informada_ha": op.area_informada_ha,
                "area_financiada_ha": op.area_financiada_ha,
                "fonte": op.fonte,
                "itens": [i.model_dump(mode="json") for i in op.itens],
            }
        ),
        "metodo": fis.metodo,
        "rulebook": fis.rulebook_versao,
        "assinaturas": [a.model_dump(mode="json") for a in fis.aprovacoes],
        "integridade": integ,
        "pii_no_laudo_selado": pii_laudo,
        "liberacao": {
            "regra_id": REGRA_LIBERACAO,
            "etapa": fis.estado_fsm,
            "acao": "humana (botão ou linha de comando); nenhum modelo de linguagem envolvido",
        },
        "por_que_na_amostra": amostra,
        "gleba": {
            "arquivo": ARQ["gleba"],
            "n_poligonos": len(gleba["features"]),
            "erros": gleba.get("erros") or [],
        },
        "fotos": {"arquivo": ARQ["fotos"], "n": len(fotos["features"]), "sem_gps": fotos["sem_gps"]},
        "sensoriamento_remoto": cenas,
        "atribuicoes": laudo.get("atribuicoes") or cenas.get("atribuicoes") or [],
        "fundamento_por_item": fund,
        "fundamento_documentos_fiscais": fund_docs,
        "memoria_de_calculo": memoria,
        "ciencia_mutuario": ciencia,
        "reversao_desclassificacao": reversao,
        "checklist_ordem_jf": checklist,
        "evidencias_incluidas": incluidas,
        "arquivos_obrigatorios": list(ARQUIVOS_OBRIGATORIOS),
    }
    arquivos[ARQ["gleba"]] = j(gleba)
    arquivos[ARQ["fotos"]] = j(fotos)
    arquivos[ARQ["cenas"]] = j(cenas)
    arquivos[ARQ["fundamento"]] = j(
        {
            "demonstracao": demo,
            "itens": fund,
            "documentos_fiscais": fund_docs,
            "nota": "itens: fundamento de cada campo do laudo (citação literal da norma ou parâmetro "
                    "operacional com a norma de base); documentos_fiscais: regras dos critérios de NF-e e "
                    "GTA, com o resumo do catálogo quando o texto literal não está no repositório (status "
                    "'resumo', literal=false)",
        }
    )
    arquivos[ARQ["memoria"]] = j({"demonstracao": demo, **memoria})
    arquivos[ARQ["amostra"]] = j({"demonstracao": demo, **amostra})
    arquivos[ARQ["ciencia"]] = j({"demonstracao": demo, **ciencia})
    arquivos[ARQ["reversao"]] = j({"demonstracao": demo, **reversao})
    arquivos[ARQ["checklist"]] = j({"demonstracao": demo, **checklist})
    arquivos[ARQ["cadeia"]] = j({"demonstracao": demo, **cadeia})
    linhas = []
    if arquivo_trace and Path(arquivo_trace).is_file():
        for ln in Path(arquivo_trace).read_text(encoding="utf-8").splitlines():
            if ln.strip():
                try:
                    linhas.append(json.dumps(mascarar_obj(json.loads(ln)), ensure_ascii=False))
                except json.JSONDecodeError:
                    continue
    arquivos[ARQ["trace"]] = ("\n".join(linhas) + ("\n" if linhas else "")).encode("utf-8")
    arquivos[ARQ["pacote_json"]] = j(pacote)
    ctx = {"p": pacote, "arq": ARQ, "laudo": laudo, "gleba": gleba, "fotos": fotos}
    arquivos[ARQ["indice_html"]] = _ENV.get_template("pacote.html.j2").render(**ctx).encode("utf-8")
    arquivos[ARQ["ciencia_html"]] = (
        _ENV.get_template("ciencia_mutuario.html.j2").render(**ctx).encode("utf-8")
    )
    arquivos[ARQ["leia_me"]] = _leia_me(pacote).encode("utf-8")
    return arquivos, pacote


def _leia_me(p: dict[str, Any]) -> str:
    d = p.get("demonstracao")
    linhas = []
    if d:
        linhas += [f"*** {d['marca_dagua']} ***", d["aviso"], ""]
    op = p["operacao"]
    municipio = f"{op.get('municipio_nome') or '—'}/{op['uf']}"
    linhas += [
        f"Pacote de exibição BCB/Justiça — operação {op['ref_bacen']} ({municipio})",
        f"Fiscalização {p['fiscalizacao_id']} · gerado em {p['gerado_em']} · {p['versao']}",
        f"Selo do laudo: {p['integridade']['selo']}",
        f"Hash raiz assinado: {p['integridade']['hash_raiz_assinado']}",
        "",
        "Como conferir: o manifest.json traz o sha256 e o tamanho de cada arquivo deste ZIP; recalcule",
        "o sha256 de cada um (ex.: `sha256sum`, `certutil -hashfile <arquivo> SHA256`) e compare.",
        "O laudo selado vai como foi selado e o rascunho que o humano assinou vai junto",
        "(laudo/rascunho_assinado.json): o hash raiz é o sha256 de raiz_da_cadeia | JSON canônico do",
        "conteúdo, e o laudo selado repete o conteúdo do rascunho (muda só tipo, gerado_em, assinaturas",
        "e cadeia, com os valores da emissão em conteudo_assinado). Conferência completa (conteúdo,",
        "cadeia, HTML): `scripts/py.sh -m laudo.audit.selo --dados <dados> <fiscalização>`.",
        f"Conferência no momento da geração: {p['integridade'].get('verificacao') or '—'}.",
        "",
        'Checklist "Ordem JF Rio Verde": ' + p["checklist_ordem_jf"]["resumo"] + ".",
        "",
    ]
    for a in p.get("atribuicoes") or []:
        linhas += [f"{a}.", ""]
    linhas += [
        "Conteúdo:",
    ]
    linhas += [f"  {c}" for c in ARQUIVOS_OBRIGATORIOS]
    linhas += [
        "  evidencias/ (fotos de campo e quadros-chave da contagem; documentos fiscais e vídeo só por hash)",
        "",
        "Dados pessoais: CPF/CNPJ e chave de acesso da NF-e aparecem só mascarados; o tomador aparece só por",
        "pseudônimo. Prioridade de verificação não é indício de irregularidade.",
    ]
    return "\n".join(linhas) + "\n"


def _zip(arquivos: dict[str, bytes], manifest: dict[str, Any], quando: datetime) -> bytes:
    buf = io.BytesIO()
    dt = (quando.year, quando.month, quando.day, quando.hour, quando.minute, quando.second)
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for nome in sorted(arquivos) + ["manifest.json"]:
            info = zipfile.ZipInfo(nome, date_time=dt)
            info.compress_type = zipfile.ZIP_DEFLATED
            dados = (
                arquivos[nome]
                if nome != "manifest.json"
                else json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8")
            )
            z.writestr(info, dados)
    return buf.getvalue()


def _manifest(arquivos: dict[str, bytes], pacote: dict[str, Any]) -> dict[str, Any]:
    return {
        "versao": VERSAO,
        "algoritmo": "sha256",
        "gerado_em": pacote["gerado_em"],
        "fiscalizacao_id": pacote["fiscalizacao_id"],
        "ref_bacen": pacote["operacao"]["ref_bacen"],
        "demonstracao": pacote["demonstracao"],
        "selo": pacote["integridade"]["selo"],
        "hash_raiz_assinado": pacote["integridade"]["hash_raiz_assinado"],
        "raiz_cadeia": pacote["integridade"]["raiz_cadeia_atual"],
        "checklist_ordem_jf": {i["id"]: i["status"] for i in pacote["checklist_ordem_jf"]["itens"]},
        "arquivos": [
            {"caminho": n, "sha256": sha256_bytes(b), "bytes": len(b)} for n, b in sorted(arquivos.items())
        ],
    }


def gerar(
    fis: Fiscalizacao,
    dir_laudos: Path,
    arquivo_trace: Path | None = None,
    triagem: dict[str, Any] | None = None,
    prazo_dias: int = PRAZO_CONTESTACAO_DIAS,
) -> dict[str, Any]:
    """Gera o ZIP em `<dir_laudos>/pacote/` e devolve o resumo (caminho, sha256, checklist, faltas)."""
    agora = datetime.now().astimezone()
    arquivos, pacote = montar(fis, dir_laudos, arquivo_trace, triagem, prazo_dias, agora)
    manifest = _manifest(arquivos, pacote)
    dados = _zip(arquivos, manifest, agora)
    destino_dir = Path(dir_laudos) / "pacote"
    destino_dir.mkdir(parents=True, exist_ok=True)
    for antigo in destino_dir.glob("*.zip"):
        antigo.unlink()
    destino = destino_dir / nome_zip(fis, pacote["integridade"]["selo"])
    tmp = destino.with_suffix(".zip.tmp")
    tmp.write_bytes(dados)
    tmp.replace(destino)
    faltas = validar_pacote(destino)
    resumo = {
        "ok": not faltas,
        "arquivo": str(destino),
        "nome": destino.name,
        "sha256_zip": sha256_bytes(dados),
        "sha256_manifest": sha256_bytes(json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8")),
        "bytes": len(dados),
        "n_arquivos": len(manifest["arquivos"]) + 1,
        "gerado_em": pacote["gerado_em"],
        "selo": pacote["integridade"]["selo"],
        "checklist_ordem_jf": pacote["checklist_ordem_jf"],
        "por_que_na_amostra": pacote["por_que_na_amostra"],
        "demonstracao": pacote["demonstracao"],
        "evidencias_incluidas": len(pacote["evidencias_incluidas"]),
        "faltas": faltas,
        "prazo_contestacao_dias": prazo_dias,
    }
    (destino_dir / "ultimo.json").write_text(
        json.dumps(resumo, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return resumo


def ultimo(dir_laudos: Path) -> dict[str, Any] | None:
    p = Path(dir_laudos) / "pacote" / "ultimo.json"
    if not p.is_file():
        return None
    try:
        r = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return r if Path(r.get("arquivo") or "").is_file() else None


# ---------------------------------------------------------------------------
# Validação (teste de aceitação): falha se faltar qualquer item
# ---------------------------------------------------------------------------


def validar_pacote(caminho_zip: str | Path) -> list[str]:
    """Lista do que falta ou não confere no ZIP (vazia = pacote completo). Confere: manifest (sha256 e tamanho
    de cada arquivo, nenhum arquivo fora dele), laudo selado (`laudo.audit.selo.verificar_laudo`: selo,
    assinatura, conteúdo contra o rascunho assinado e HTML), gleba, fotos (coordenadas, horário de captura e
    de recebimento), cenas (id, sensor, resoluções espacial e radiométrica, bandas e atribuição Copernicus
    quando houve satélite), fundamento por item e das regras de documentos fiscais (resumo nunca conta como
    literal), memória de cálculo (contagem, conciliações, lotação), amostra, ciência com prazo e citações,
    reversão IN 758, checklist JF com os 5 itens e status real, marca d'água da demonstração e ausência de
    CPF/CNPJ/chave de NF-e sem máscara."""
    f: list[str] = []
    try:
        z = zipfile.ZipFile(caminho_zip)
    except (OSError, zipfile.BadZipFile) as e:
        return [f"zip: ilegível ({e})"]
    with z:
        nomes = set(z.namelist())
        for obrig in ARQUIVOS_OBRIGATORIOS:
            if obrig not in nomes:
                f.append(f"arquivo: falta {obrig}")
        if "manifest.json" not in nomes:
            return f
        try:
            man = json.loads(z.read("manifest.json"))
        except json.JSONDecodeError:
            return f + ["manifest: JSON inválido"]
        listados = {a["caminho"]: a for a in man.get("arquivos") or []}
        for n in nomes - {"manifest.json"}:
            a = listados.get(n)
            if a is None:
                f.append(f"manifest: {n} fora do manifest")
                continue
            b = z.read(n)
            if a.get("sha256") != sha256_bytes(b) or a.get("bytes") != len(b):
                f.append(f"manifest: sha256/tamanho de {n} não confere")
        for n in set(listados) - nomes:
            f.append(f"manifest: {n} listado mas ausente do ZIP")

        def ler(n: str) -> Any:
            if n not in nomes:
                return None
            try:
                return json.loads(z.read(n))
            except (json.JSONDecodeError, UnicodeDecodeError):
                f.append(f"{n}: JSON inválido")
                return None

        p = ler(ARQ["pacote_json"]) or {}
        laudo = ler(ARQ["laudo_json"]) or {}
        rascunho = ler(ARQ["rascunho"])
        if laudo and laudo.get("tipo") != "selado":
            f.append("laudo: não é o selado")
        if laudo and p.get("pii_no_laudo_selado"):
            f.append("laudo: cópia mascarada (o selado tinha dado pessoal); conteúdo não conferível pelo ZIP")
        elif laudo:
            # selo, assinatura e conteúdo (hash raiz recalculado do rascunho assinado que vai no ZIP) e
            # HTML
            from laudo.audit import selo as selo_mod

            html = z.read(ARQ["laudo_html"]) if ARQ["laudo_html"] in nomes else None
            r = selo_mod.verificar_laudo(
                laudo, rascunho=rascunho if isinstance(rascunho, dict) else None, html=html
            )
            if not r.valido:
                f.append(f"laudo: não confere ({r.motivo[:300]})")
        gl = ler(ARQ["gleba"])
        chk = ler(ARQ["checklist"]) or {}
        st = {i.get("id"): i for i in chk.get("itens") or []}
        if gl is not None:
            ok_gl = gl.get("type") == "FeatureCollection" and all(
                (x.get("geometry") or {}).get("type") in ("Polygon", "MultiPolygon")
                for x in gl.get("features") or []
            )
            if not ok_gl:
                f.append("gleba: GeoJSON sem polígono válido")
            if not gl.get("features") and (st.get("vetor_poligono") or {}).get("status") != "ausente":
                f.append("gleba: sem polígono e o checklist não diz 'ausente'")
        fo = ler(ARQ["fotos"])
        if fo is not None:
            for x in fo.get("features") or []:
                pr = x.get("properties") or {}
                if x.get("geometry") is None and not pr.get("motivo"):
                    f.append(f"fotos: {pr.get('evidencia_id')} sem coordenadas e sem motivo")
                if "capturada_em" not in pr:
                    f.append(f"fotos: {pr.get('evidencia_id')} sem o campo de horário de captura")
                if not pr.get("recebida_em"):
                    f.append(f"fotos: {pr.get('evidencia_id')} sem o horário de recebimento (recebida_em)")
        ce = ler(ARQ["cenas"])
        if ce is not None:
            if ce.get("aplicavel"):
                if not ce.get("cenas") and not ce.get("motivo"):
                    f.append("cenas: sensoriamento usado, sem cenas e sem motivo")
                for c in ce.get("cenas") or []:
                    # MCR 2-7-4-b: sensor, datas, resoluções espacial e radiométrica, bandas
                    for k in (
                        "id_cena",
                        "data",
                        "sensor",
                        "resolucao_espacial_m",
                        "resolucao_radiometrica_bits",
                        "bandas",
                    ):
                        if not c.get(k):
                            f.append(f"cenas: {c.get('id_cena') or c.get('data')} sem {k}")
                if ce.get("cenas") and not any("Copernicus" in a for a in ce.get("atribuicoes") or []):
                    f.append("cenas: cena Sentinel-2 sem a atribuição Copernicus")
            elif not ce.get("justificativa"):
                f.append("cenas: 'não aplicável' sem justificativa")
        fu = ler(ARQ["fundamento"]) or {}
        campos_fund = {x.get("campo") for x in fu.get("itens") or []}
        from laudo.tools.laudo import _REGRA_AGREGACAO

        for it in laudo.get("itens") or []:
            if it.get("regra_id") != _REGRA_AGREGACAO and it.get("campo") not in campos_fund:
                f.append(f"fundamento: falta o item {it.get('campo')}")
        for x in fu.get("itens") or []:
            fd = x.get("fundamento") or {}
            if not fd.get("status") or (
                x.get("literal")
                and not (
                    fd.get("citacao_literal")
                    or any(b.get("citacao_literal") for b in fd.get("base_normativa") or [])
                )
            ):
                f.append(f"fundamento: {x.get('campo')} sem status ou com 'literal' sem citação")
        for x in fu.get("documentos_fiscais") or []:
            fd = x.get("fundamento") or {}
            if not fd.get("status"):
                f.append(f"fundamento: regra de documento fiscal {x.get('regra_id')} sem status")
            elif fd.get("status") == "resumo" and (x.get("literal") or not fd.get("resumo")):
                f.append(f"fundamento: {x.get('regra_id')} é resumo e não pode contar como literal")
            elif x.get("literal") and not fd.get("citacao_literal"):
                f.append(f"fundamento: {x.get('regra_id')} marcado literal sem citação")
        nao_literais = [
            x
            for x in [*(fu.get("itens") or []), *(fu.get("documentos_fiscais") or [])]
            if not x.get("literal")
        ]
        if nao_literais and (st.get("fundamento") or {}).get("status") == "presente":
            f.append(
                f"checklist JF: fundamento 'presente' com {len(nao_literais)} regra(s) sem citação literal"
            )
        me = ler(ARQ["memoria"]) or {}
        for k in ("contagem", "conciliacoes", "lotacao"):
            if not me.get(k):
                f.append(f"memória de cálculo: falta {k}")
        am = ler(ARQ["amostra"]) or {}
        if "motivos" not in am or not am.get("aviso"):
            f.append("amostra: falta a abertura 'por que caiu na amostra'")
        ci = ler(ARQ["ciencia"]) or {}
        if not isinstance(ci.get("prazo_contestacao_dias"), int) or ci.get("prazo_contestacao_dias", 0) <= 0:
            f.append("ciência do mutuário: falta o prazo de contestação")
        if ARQ["ciencia_html"] in nomes and "contesta" not in z.read(ARQ["ciencia_html"]).decode(
            "utf-8", "replace"
        ):
            f.append("ciência do mutuário: termo sem a contestação")
        base_ci = ci.get("base") or []
        if not base_ci or not all(b.get("citacao_literal") for b in base_ci):
            f.append("ciência do mutuário: base normativa sem citação literal (MCR 2-8-3 e 2-7-18)")
        rv = ler(ARQ["reversao"]) or {}
        if "758" not in str(rv.get("norma")) or not rv.get("documentacao_desta_operacao"):
            f.append("reversão: falta a seção da IN BCB 758 com a documentação da operação")
        fl = rv.get("fonte_literal") or {}
        if rv.get("citacao_conferida") is True and not (
            rv.get("citacao_literal") and rv.get("localizador") and fl.get("url") and fl.get("acesso")
        ):
            f.append(
                "reversão: IN BCB 758 'conferida' sem citação literal, localizador, URL ou data de acesso"
            )
        elif rv.get("citacao_conferida") is not True and rv.get("citacao_literal"):
            f.append("reversão: texto da IN BCB 758 apresentado como citação sem conferência")
        for iid in ITENS_ORDEM_JF:
            it = st.get(iid)
            if it is None:
                f.append(f"checklist JF: falta o item {iid}")
                continue
            if it.get("status") not in STATUS_CHECKLIST:
                f.append(f"checklist JF: {iid} com status inválido {it.get('status')!r}")
            elif it["status"] == "nao_aplicavel" and not it.get("justificativa"):
                f.append(f"checklist JF: {iid} 'não aplicável' sem justificativa")
            elif it["status"] in ("presente", "parcial") and not it.get("evidencias"):
                f.append(f"checklist JF: {iid} '{it['status']}' sem arquivo de evidência")
        demo = p.get("demonstracao") or laudo.get("demonstracao")
        for n in sorted(nomes):
            if not n.endswith((".json", ".jsonl", ".html", ".txt", ".geojson")):
                continue
            texto = z.read(n).decode("utf-8", "replace")
            if pii_no_texto(texto):
                f.append(f"PII: {n} com {', '.join(pii_no_texto(texto))}")
            if demo and n.endswith((".html", ".txt")) and demonstracao.MARCA_DAGUA not in texto:
                f.append(f"demonstração: {n} sem a marca d'água")
    return f


# ---------------------------------------------------------------------------
# Ação humana (registro próprio: fora do REGISTRO global e do alcance do LLM)
# ---------------------------------------------------------------------------

ACOES_HUMANAS: dict[str, Ferramenta] = {}


class EntradaPacote(BaseModel):
    fiscalizacao_id: str = Field(description="id da fiscalização selada (fis_...)")
    prazo_contestacao_dias: int = Field(
        PRAZO_CONTESTACAO_DIAS, ge=5, le=60, description="prazo do mutuário para contestar (parâmetro da IF)"
    )


def executar(
    fis: Fiscalizacao,
    dir_laudos: Path,
    arquivo_trace: Path | None = None,
    triagem: dict[str, Any] | None = None,
    prazo_dias: int = PRAZO_CONTESTACAO_DIAS,
) -> Envelope:
    """Gera o pacote com span e decisão de política no trace (negada antes de SELADO)."""
    t0 = time.perf_counter()
    with otel.contexto_fiscalizacao(fis.id), otel.span("humano.gerar_pacote_exibicao") as s:
        try:
            r = gerar(fis, dir_laudos, arquivo_trace, triagem, prazo_dias)
        except ErroPacote as e:
            sid = otel.registrar_decisao(e.regra_id, "negar", ACAO, e.msg, **{"policy.origem": "humano"})
            return Envelope.falha(
                ACAO,
                e.codigo,
                e.msg,
                t0=t0,
                fonte_versao=VERSAO,
                data={"pendencias": [{"regra_id": e.regra_id, "falta": e.msg}], "policy_span_id": sid},
            )
        sid = otel.registrar_decisao(
            REGRA_LIBERACAO,
            "permitir",
            ACAO,
            "fiscalização selada por assinatura humana",
            **{"policy.origem": "humano"},
        )
        otel.definir(
            s,
            **{
                "pacote.sha256_zip": r["sha256_zip"],
                "pacote.n_arquivos": r["n_arquivos"],
                "pacote.faltas": len(r["faltas"]),
            },
        )
    return Envelope.sucesso(
        ACAO,
        r | {"status": "ok" if r["ok"] else "indeterminado", "policy_span_id": sid},
        fonte_versao=VERSAO,
        t0=t0,
    )


@registrar(
    ACAO,
    "Gera o pacote de exibição BCB/Justiça (ZIP com manifest sha256) de uma fiscalização SELADA. "
    "Ação humana: não é oferecida ao agente.",
    EntradaPacote,
    timeout_s=60.0,
    registro=ACOES_HUMANAS,
)
def gerar_pacote_exibicao(args: EntradaPacote) -> Envelope:
    from laudo.tools import laudo as ferr_laudo

    t0 = time.perf_counter()
    try:
        fis = ferr_laudo._repo().carregar(args.fiscalizacao_id)
    except (FileNotFoundError, ValueError) as e:
        return Envelope.falha(ACAO, CodigoErro.ENTRADA_INVALIDA, f"fiscalização não encontrada: {e}", t0=t0)
    return executar(
        fis,
        ferr_laudo.diretorio_laudos(fis.id),
        otel.arquivo_trace(fis.id),
        None,
        args.prazo_contestacao_dias,
    )


def main(argv: list[str] | None = None) -> int:
    """`scripts/py.sh -m laudo.tools.pacote --dados dados_locais/api fis_demo_0001`"""
    from laudo.agent import estado as est

    ap = argparse.ArgumentParser(
        description="Gera o pacote de exibição BCB/Justiça de uma fiscalização SELADA."
    )
    ap.add_argument("fiscalizacao_id")
    ap.add_argument(
        "--dados",
        default=str(REPO / "dados_locais" / "api"),
        help="pasta de dados (com fiscalizacoes/, laudos/ e traces/)",
    )
    ap.add_argument("--prazo", type=int, default=PRAZO_CONTESTACAO_DIAS, help="prazo de contestação (dias)")
    a = ap.parse_args(argv)
    dados = Path(a.dados)
    otel.configurar(dados / "traces")
    repo = est.RepositorioFiscalizacoes(dados)
    try:
        fis = repo.carregar(a.fiscalizacao_id)
    except (FileNotFoundError, ValueError) as e:
        print(f"fiscalização não encontrada em {dados}: {e}")
        return 2
    env = executar(fis, dados / "laudos" / fis.id, otel.arquivo_trace(fis.id), None, a.prazo)
    print(formatar_resumo(env))
    return 0 if env.ok and not (env.data or {}).get("faltas") else 1


def formatar_resumo(env: Envelope) -> str:
    if not env.ok:
        codigo, msg = (env.error.code, env.error.msg) if env.error else ("?", "")
        return f"Pacote NÃO gerado ({codigo}): {msg}"
    d = env.data or {}
    linhas = []
    if d.get("demonstracao"):
        linhas.append(f"*** {d['demonstracao']['marca_dagua']} ***")
    linhas += [
        f"Pacote de exibição: {d['arquivo']}",
        f"  {d['n_arquivos']} arquivo(s) · {d['bytes'] / 1024:.0f} KiB · sha256 do ZIP {d['sha256_zip']}",
        f"  manifest sha256 {d['sha256_manifest']} · selo {d['selo']}",
        '  Checklist "Ordem JF Rio Verde": ' + d["checklist_ordem_jf"]["resumo"],
    ]
    for it in d["checklist_ordem_jf"]["itens"]:
        extra = it.get("justificativa") or it.get("motivo") or ""
        linhas.append(f"    - {it['titulo']}: {it['rotulo']}" + (f" ({extra[:120]})" if extra else ""))
    amostra = d.get("por_que_na_amostra") or {}
    if amostra.get("resumo"):
        linhas.append(f"  Por que caiu na amostra: {amostra['resumo']}")
    if d.get("faltas"):
        linhas.append("  FALTAS: " + "; ".join(d["faltas"]))
    return "\n".join(linhas)


if __name__ == "__main__":
    sys.exit(main())
