"""Ferramentas do laudo: `emitir_rascunho` e `registrar_ocorrencia`.

`emitir_rascunho` recalcula o status pelo verificador, pede autorização à política (POL-01, POL-02, POL-04) e:
- se permitido, gera o laudo **HTML** (jinja2) e **JSON** com identificação da operação (campos públicos),
  método e metadados (sensor, datas, resolução, bandas, metodologia quando houver sensoriamento remoto), itens
  com status, **origem de cada valor** ("XML", "lido de foto e validado", "lido de foto e completado pela
  fiscal", "vídeo", "satélite"...) e links para evidências, checagens e spans, ocorrências, a seção
  **alegações × evidência** (OP-alegacao-declaracao-x-evidencia: cada alegação da fala ao lado da prova que a
  confronta), o **vetor da gleba** (GeoJSON) e as **coordenadas e o horário das fotos** (dentro do hash raiz
  que o humano assina), hash raiz e espaço de assinatura humana;
- se não, devolve `BLOQUEADO_POLITICA` com a lista de pendências em `data["pendencias"]`.

Texto livre opcional (`texto_redigido`, vindo do LLM) só entra se passar no grounding numérico (POL-05);
senão o resumo cai no template. A ferramenta não altera o estado persistido: quem registra a emissão na
cadeia de hash é o condutor (`registrar_emissao`).

Selo por construção: `selar` não monta o laudo de novo a partir do estado. Ele lê o JSON do **rascunho
assinado** (a evidência `documento` com `meta.laudo` e o hash que o humano assinou, conferido pelo sha256 da
cadeia e pelo hash raiz recalculado), troca só `tipo`, `gerado_em`, `assinaturas` e `cadeia` e grava os
valores da emissão no bloco `conteudo_assinado`; `laudo.audit.selo.verificar_laudo` reconstrói dali o conteúdo
assinado. Uma fala com número depois do rascunho (que não barra a assinatura) não entra no selado. O laudo
declara o sha256 do template HTML com que foi gerado (`template.sha256`).
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field

from laudo import demonstracao
from laudo.agent import estado as est
from laudo.agent.politica import Politica
from laudo.agent.verificador import ResultadoVerificacao
from laudo.audit import hashchain, otel
from laudo.audit import selo as selo_mod
from laudo.contracts import CodigoErro, Envelope, Fiscalizacao, registrar, sha256_bytes
from laudo.formatacao import (  # noqa: F401 (reexportados)
    ROTULO_METODO,
    fmt_valor,
    rotulo_metodo,
    texto_sem_ids,
)

log = logging.getLogger(__name__)
VERSAO = "laudo-vivo@0.1.0"
_TEMPLATES = Path(__file__).resolve().parents[1] / "agent" / "templates"
_ENV = Environment(loader=FileSystemLoader(str(_TEMPLATES)), autoescape=select_autoescape(["html", "j2"]))

# Contexto configurável: o condutor injeta o mesmo repositório/política que usa; testes usam diretório
# temporário.
_CTX: dict[str, Any] = {"repo": None, "politica": None}

_ASPECTO = {
    "quantidade": "Quantidade (contagem)",
    "nfe": "Nota fiscal eletrônica",
    "gta": "GTA",
    "existencia": "Existência física georreferenciada",
    "ndvi": "Vigor da vegetação (NDVI)",
    "lotacao": "Lotação",
    "comprovante_nfe": "Comprovante de aquisição (NF-e)",
    "integridade_foto": "Integridade da foto",
    "localizacao": "Localização (foto na gleba)",
    "conclusao": "Conclusão da obra",
    "prazo_cronograma": "Prazo do cronograma",
    "prazo_60d": "Prazo de 60 dias",
    "numero_serie": "Número de série",
    "metodo": "Método de fiscalização",
    "independencia_fiscal": "Independência do fiscal",
    "sensoriamento_remoto": "Sensoriamento remoto",
    "metadados_sensoriamento": "Metadados do sensoriamento (MCR 2-7-4-b)",
}
ROTULO_AGREGADO = "Resultado do item"
# Atribuição exigida pela licença dos dados Copernicus (Sentinel-2) quando uma cena entra no laudo ou no
# pacote.
ATRIBUICAO_COPERNICUS = "Contém dados Copernicus Sentinel modificados ({anos})"
# Rótulos legíveis: o laudo e a tela mostram o nome da ferramenta e do tipo de evidência, não o id
ROTULO_FERRAMENTA = {
    "contar_bovinos_video": "Contagem no vídeo",
    "conciliar_nfe": "Conciliação da NF-e",
    "conciliar_gta": "Conciliação da GTA",
    "integridade_foto": "Integridade da foto",
    "geofence": "Foto na gleba",
    "classificar_foto": "Classificação da foto",
    "serie_ndvi": "Série NDVI (satélite)",
    "planejar_metodo": "Plano de método",
    "avaliar_regras": "Regras do MCR",
    "checar_lotacao": "Lotação",
    "ler_documento_foto": "Leitura da foto do documento",
    "completar_leitura_documento": "Campos lidos pela fiscal",
    "conciliar_alegacoes": "Alegações × evidência",
    "carregar_operacao": "Operação (Sicor)",
    "explicar_regra": "Explicação da regra",
    "declaracao_conclusao": "Declaração do fiscal",
    "declaracao_independencia": "Declaração de independência",
    "registrar_conclusao_obra": "Conclusão da obra (fiscal)",
    "registrar_justificativa": "Justificativa do fiscal",
}
ROTULO_TIPO_EVIDENCIA = {
    "video": "Vídeo",
    "foto": "Foto",
    "nfe_xml": "NF-e (XML)",
    "gta": "e-GTA",
    "documento": "Documento",
    "declaracao": "Fala do fiscal",
    "ocorrencia": "Ocorrência",
    "audio": "Áudio",
    "quadro_chave": "Quadro-chave",
    "satelite": "Cena de satélite",
}
_ENV.globals.update(rotulo_ferramenta=ROTULO_FERRAMENTA, rotulo_tipo=ROTULO_TIPO_EVIDENCIA)
# motivo/justificativa sem ids crus no HTML para imprimir; a versão do filtro vai no comentário do
# template
_ENV.filters["sem_ids"] = lambda t: texto_sem_ids(t, ROTULO_FERRAMENTA)
_ROTULO = {
    "verificado": "verificado",
    "divergente": "divergente",
    "pendente": "pendente",
    "abstencao": "abstenção",
}


def _descricao_curta(texto: str | None) -> str:
    """Descrição do item sem o sufixo técnico do Sicor ("… — Sicor: AQUISIÇÃO DE ANIMAIS …")."""
    return str(texto or "").split(" — Sicor:")[0].split(" (projeto sintético")[0].strip()


def configurar(repo: est.RepositorioFiscalizacoes | None = None, politica: Politica | None = None) -> None:
    _CTX["repo"] = repo
    _CTX["politica"] = politica


def _repo() -> est.RepositorioFiscalizacoes:
    if _CTX["repo"] is None:
        _CTX["repo"] = est.RepositorioFiscalizacoes()
    return _CTX["repo"]


def _politica() -> Politica:
    if _CTX["politica"] is None:
        _CTX["politica"] = Politica()
    return _CTX["politica"]


# ---------------------------------------------------------------------------
# Montagem do laudo
# ---------------------------------------------------------------------------


def _fmt_num(v: Any, casas: int = 2) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "sim" if v else "não"
    if isinstance(v, (int, float)):
        if float(v).is_integer():
            s = f"{int(v):,}".replace(",", ".")
        else:
            s = f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return s
    return str(v)


def href_relativo(caminho: str | Path | None, base: Path) -> str:
    """Link relativo à pasta do laudo (o laudo não carrega caminho absoluto da máquina, como o disco local).

    Fora do mesmo disco, ou sem caminho, devolve "#". A API troca esses links por rotas próprias
    (`Servico.laudo_html`) usando esta mesma função."""
    if not caminho:
        return "#"
    try:
        rel = os.path.relpath(Path(caminho).resolve(), Path(base).resolve())
    except ValueError:
        return "#"
    return Path(rel).as_posix()


def _sensoriamento(fis: Fiscalizacao) -> list[dict[str, Any]]:
    """Metadados do sensoriamento remoto (MCR 2-7 item 4). Nunca inventa: o que faltar fica dito."""
    saida = []
    ni = "não informado pela ferramenta"
    for c in fis.checagens:
        if c.ferramenta != "serie_ndvi":
            continue
        r = c.resultado.get("metadados_laudo") or c.resultado
        datas = r.get("datas") or [
            o.get("data") for o in c.resultado.get("obs", []) if isinstance(o, dict) and o.get("data")
        ]
        bandas = r.get("bandas")
        if isinstance(bandas, dict):
            bandas = "; ".join(f"{k}: {v}" for k, v in bandas.items())
        elif isinstance(bandas, list):
            bandas = ", ".join(map(str, bandas))
        sensor = r.get("sensor")
        if sensor and r.get("produto"):
            sensor = f"{sensor} — {r['produto']}"
        satelite = r.get("satelite") or r.get("plataforma")
        if isinstance(satelite, list):
            satelite = ", ".join(map(str, satelite))
        bits = r.get("resolucao_radiometrica_bits") or r.get("resolucao_radiometrica")
        saida.append(
            {
                "checagem_id": c.id,
                "satelite": satelite or ni,
                "sensor": sensor or ni,
                "datas": ", ".join(map(str, datas)) if datas else ni,
                "resolucao": f"{_fmt_num(r['resolucao_m'])} m" if r.get("resolucao_m") else ni,
                "resolucao_radiometrica": f"{bits} bits" if bits else ni,
                "bandas": bandas or ni,
                "metodologia": r.get("metodologia") or ni,
                "uso": r.get("uso_na_fiscalizacao") or r.get("uso") or ni,
                "status": c.status,
                "fonte_versao": c.fonte_versao,
            }
        )
    return saida


def _cena_sentinel(r: dict[str, Any]) -> tuple[bool, set[str]]:
    """A checagem `serie_ndvi` usou cena Sentinel-2? Devolve (usou, anos das cenas)."""
    meta = r.get("metadados_laudo") or r
    serie = [o for o in r.get("serie") or r.get("obs") or [] if isinstance(o, dict)]
    datas = [str(d) for d in meta.get("datas") or []] + [str(o.get("data")) for o in serie if o.get("data")]
    marca = json.dumps({k: meta.get(k) for k in ("satelite", "plataforma", "produto", "sensor")}, default=str)
    marca += json.dumps([o.get("plataforma") or o.get("item_id") or "" for o in serie], default=str)
    usou = bool(datas or serie) and ("sentinel" in marca.lower() or '"S2' in marca)
    return usou, {d[:4] for d in datas if d[:4].isdigit()}


def atribuicoes_dados(fis: Fiscalizacao) -> list[str]:
    """Atribuições de licença dos dados de terceiros usados no laudo: Copernicus Sentinel quando houver cena
    Sentinel-2. Lista vazia quando não houve sensoriamento remoto."""
    anos: set[str] = set()
    usou = False
    for c in fis.checagens:
        if c.ferramenta != "serie_ndvi":
            continue
        u, a = _cena_sentinel(c.resultado or {})
        usou, anos = usou or u, anos | a
    if not usou:
        return []
    ref = fis.data_referencia or fis.criada_em.date()
    return [ATRIBUICAO_COPERNICUS.format(anos=", ".join(sorted(anos)) or str(ref.year))]


def fotos_georreferenciadas(fis: Fiscalizacao) -> list[dict[str, Any]]:
    """Coordenadas e horário de cada foto de campo, como registrados na evidência (nada recalculado)."""
    saida = []
    for e in fis.evidencias:
        if e.tipo != "foto":
            continue
        g = e.gps
        saida.append(
            {
                "evidencia_id": e.id,
                "item_id": e.meta.get("item_id"),
                "sha256": e.sha256,
                "lat": g.lat if g else None,
                "lon": g.lon if g else None,
                "precisao_m": g.precisao_m if g else None,
                "gps_fonte": g.fonte if g else None,
                "capturada_em": e.capturada_em.isoformat() if e.capturada_em else None,
                "recebida_em": e.recebida_em.isoformat(timespec="seconds") if e.recebida_em else None,
            }
        )
    return saida


_REGRA_AGREGACAO = "OP-agregacao-item"  # status do item (pior dos campos): não conta como aspecto à parte
REGRA_ALEGACOES = "OP-alegacao-declaracao-x-evidencia"
_LEITURAS = ("ler_documento_foto", "completar_leitura_documento")
_ORIGEM_FERRAMENTA = {
    "contar_bovinos_video": "vídeo (contagem por visão computacional)",
    "serie_ndvi": "satélite (Sentinel-2)",
    "classificar_foto": "foto classificada pelo VLM",
    "declaracao_conclusao": "declaração do fiscal",
    "integridade_foto": "foto georreferenciada",
    "geofence": "foto georreferenciada",
}


def proveniencia(
    fis: Fiscalizacao, evidencias: list[str], checagens: list[str], justificativa: bool = False
) -> list[str]:
    """De onde vem o valor de um campo do laudo: XML autorizado, e-GTA, DANFE/GTA lido de foto e validado,
    completado pela fiscal (residual), vídeo, satélite, foto, VLM ou declaração do fiscal."""
    evs = {e.id: e for e in fis.evidencias}
    chks = {c.id: c for c in fis.checagens}
    out: list[str] = []

    def add(x: str) -> None:
        if x not in out:
            out.append(x)

    for e in (evs[x] for x in evidencias if x in evs):
        if e.tipo == "nfe_xml":
            add("XML da NF-e")
        elif e.tipo == "gta":
            add("e-GTA (JSON)")
        elif e.tipo == "documento" and not e.meta.get("laudo"):
            leit = [c for c in fis.checagens if c.ferramenta in _LEITURAS and e.id in c.evidencias]
            if any(c.ferramenta == "completar_leitura_documento" and c.status == "ok" for c in leit) or any(
                c.ferramenta == "completar_leitura_documento" and c.resultado.get("aceitos_da_fiscal")
                for c in leit
            ):
                add("lido de foto e completado pela fiscal")
            elif leit:
                add("lido de foto e validado")
        elif e.tipo == "declaracao" and e.meta.get("assunto"):
            add("declaração do fiscal")
    for c in (chks[x] for x in checagens if x in chks):
        if c.ferramenta in _ORIGEM_FERRAMENTA:
            add(_ORIGEM_FERRAMENTA[c.ferramenta])
    if justificativa:
        add("justificativa do fiscal")
    return out


def alegacoes_x_evidencia(fis: Fiscalizacao) -> list[dict[str, Any]]:
    """Cada alegação da fala ao lado da evidência que a confronta (OP-alegacao-declaracao-x-evidencia). Função
    pura (`tools.alegacoes.conciliar`, determinística) sobre o estado: não muda status de campo nenhum."""
    if not fis.alegacoes:
        return []
    from laudo.tools.alegacoes import conciliar

    substituidas = {s for c in fis.checagens for s in (c.resultado.get("substitui") or [])}
    chks = [
        {"ferramenta": c.ferramenta, "status": c.status, "item_id": c.item_id, "resultado": c.resultado}
        for c in fis.checagens
        if c.id not in substituidas
    ]
    try:
        res = conciliar(list(fis.alegacoes), list(fis.operacao.itens), chks)
    except Exception:  # noqa: BLE001 - o laudo não cai por causa da seção informativa
        return []
    rot = {
        "confere": "confere",
        "divergente": "divergente",
        "pendente": "pendente",
        "registro": "registro",
        "sem_evidencia": "sem evidência",
    }
    return [
        {**a, "status_rotulo": rot.get(a["status"], a["status"]), "valor_fmt": _fmt_num(a.get("valor"))}
        for a in res["alegacoes"]
    ]


def _justificativa_metodo(plano: dict[str, Any], fis: Fiscalizacao | None = None) -> str | None:
    """Por que este método, legível: o texto do plano ou, no plano do rulebook, o método de cada item
    pela descrição do item e o enquadramento normativo (sem ids de item nem de regra; a regra de cada campo
    está na tabela de itens)."""
    if plano.get("justificativa") or plano.get("motivo"):
        return str(plano.get("justificativa") or plano.get("motivo"))
    desc = {i.id: _descricao_curta(i.descricao) for i in (fis.operacao.itens if fis else [])}
    por_item = []
    for m in plano.get("metodos_por_item") or []:
        prio = {"media": "média"}.get(str(m.get("prioridade")), m.get("prioridade"))
        detalhe = [f"prioridade {prio}"] if prio is not None else []
        if m.get("enquadramento_normativo"):
            detalhe.append(f"enquadramento {m.get('enquadramento_normativo')}")
        nome = desc.get(str(m.get("item_id"))) or "item"
        por_item.append(
            f"{nome}: {rotulo_metodo(m.get('metodo'))}" + (f" ({'; '.join(detalhe)})" if detalhe else "")
        )
    obrig = [str(o.get("motivo")) for o in plano.get("obrigatoriedades") or [] if o.get("motivo")]
    partes = por_item + obrig
    return "; ".join(partes) or None


def resumo_template(fis: Fiscalizacao, res: ResultadoVerificacao) -> str:
    aspectos = [c for c in res.campos.values() if c.regra_id != _REGRA_AGREGACAO]
    cont = {
        s: sum(1 for c in aspectos if c.status == s)
        for s in ("verificado", "divergente", "pendente", "abstencao")
    }
    just = sum(1 for c in aspectos if c.status == "divergente" and c.justificativa_humana)
    metodo = rotulo_metodo(fis.metodo) if fis.metodo else "sem método definido"
    partes = [
        f"Fiscalização {metodo} da operação {fis.operacao.ref_bacen}:",
        f"{cont['verificado']} aspecto(s) verificado(s)",
    ]
    if cont["divergente"]:
        partes.append(f"{cont['divergente']} divergente(s) ({just} com justificativa do fiscal)")
    if cont["abstencao"]:
        partes.append(f"{cont['abstencao']} abstenção(ões)")
    if cont["pendente"]:
        partes.append(f"{cont['pendente']} pendente(s)")
    texto = ", ".join(partes[1:])
    oc = len(fis.ocorrencias)
    return (
        f"{partes[0]} {texto}. {oc} ocorrência(s) registrada(s). Cada item abaixo aponta para a evidência, "
        "a checagem e o trace; o status foi atribuído pelo verificador, não pelo modelo de linguagem."
    )


def montar_laudo(
    fis: Fiscalizacao,
    res: ResultadoVerificacao,
    texto_redigido: str | None = None,
    politica: Politica | None = None,
    hoje: date | None = None,
    tipo: str = "rascunho",
) -> dict[str, Any]:
    politica = politica or _politica()
    op = fis.operacao
    itens_por_id = {i.id: i for i in op.itens}
    evs = {e.id: e for e in fis.evidencias}
    chks = {c.id: c for c in fis.checagens}
    base = diretorio_laudos(fis.id)
    linhas = []
    ordem = {i.id: n for n, i in enumerate(op.itens)}
    ordem_req = {r.get("campo"): n for n, r in enumerate(res.requisitos)}

    def chave(kv: tuple[str, Any]) -> tuple[int, int, str]:
        item = kv[0].split(":")[1] if kv[0].startswith("item:") else ""
        return ordem.get(item, 99), ordem_req.get(kv[0], 99), kv[0]

    for nome, c in sorted(res.campos.items(), key=chave):
        partes = nome.split(":")
        item = itens_por_id.get(partes[1]) if partes[0] == "item" and len(partes) >= 2 else None
        agregado = c.regra_id == _REGRA_AGREGACAO or (partes[0] == "item" and len(partes) == 2)
        suf = partes[-1]
        linhas.append(
            {
                "campo": nome,
                "item_id": item.id if item else None,
                "item_descricao": item.descricao if item else "Operação",
                "aspecto": ROTULO_AGREGADO if agregado else _ASPECTO.get(suf, suf.replace("_", " ")),
                "agregado": agregado,
                "status": c.status,
                "status_rotulo": _ROTULO[c.status],
                "valor": c.valor,
                # valor legível: contagem com intervalo, nunca o dicionário cru do verificador
                "valor_fmt": fmt_valor(c.valor),
                "regra_id": c.regra_id,
                "motivo": c.motivo,
                "proveniencia": proveniencia(fis, c.evidencias, c.checagens, bool(c.justificativa_humana)),
                "justificativa_humana": c.justificativa_humana,
                "evidencias": [
                    {
                        "id": e,
                        "tipo": evs[e].tipo if e in evs else "?",
                        "sha256": evs[e].sha256 if e in evs else None,
                        "uri": href_relativo(evs[e].caminho, base) if e in evs else "#",
                    }
                    for e in c.evidencias
                ],
                "checagens": [
                    {
                        "id": k,
                        "ferramenta": chks[k].ferramenta if k in chks else "?",
                        "status": chks[k].status if k in chks else "?",
                        "span_id": chks[k].trace_id if k in chks else None,
                    }
                    for k in c.checagens
                ],
            }
        )
    plano = next(
        (c for c in reversed(fis.checagens) if c.ferramenta == "planejar_metodo" and c.status == "ok"), None
    )
    resumo_tpl = resumo_template(fis, res)
    resumo = {"texto": resumo_tpl, "origem": "template", "motivo": ""}
    if texto_redigido:
        d = politica.checar_texto(texto_redigido, fis, acao="redacao_laudo")
        if d.permitido:
            resumo = {"texto": texto_redigido, "origem": "llm", "motivo": "grounding numérico ok"}
        else:
            resumo["motivo"] = f"redação do LLM descartada: {d.motivo}"
    cadeia = hashchain.verificar_cadeia(fis.evidencias)
    arq_trace = otel.arquivo_trace(fis.id)
    from laudo.tools.pacote import gleba_geojson  # o mesmo GeoJSON vai ao pacote de exibição

    laudo: dict[str, Any] = {
        "versao": VERSAO,
        "tipo": tipo,
        # operação sintética (golden set ou demo): marca d'água no HTML, no JSON e na tela; entra no hash raiz
        "demonstracao": demonstracao.bloco_laudo(op),
        "fiscalizacao_id": fis.id,
        "gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
        "data_referencia": (hoje or fis.data_referencia or datetime.now().astimezone().date()).isoformat(),
        "operacao": {
            **{k: v for k, v in op.model_dump(mode="json").items() if k not in ("glebas_wkt", "itens")},
            "n_glebas": len(op.glebas_wkt),
            # vetor da gleba dentro do que o humano assina (entra no hash raiz); ordem de exibição da JF Rio
            # Verde
            "glebas_geojson": gleba_geojson(fis),
            "valor_fmt": f"R$ {_fmt_num(op.valor_rs)}" if op.valor_rs else "não informado",
            "area_fmt": f"{_fmt_num(op.area_financiada_ha)} ha" if op.area_financiada_ha else "não informada",
            "itens": [i.model_dump(mode="json") for i in op.itens],
        },
        "metodo": {
            "metodo": fis.metodo,
            "rotulo": rotulo_metodo(fis.metodo),
            "rulebook_versao": fis.rulebook_versao or res.fonte,
            "justificativa": _justificativa_metodo(plano.resultado, fis) if plano else None,
            "verificacao": res.fonte,
            "provisoria": res.provisoria,
        },
        "sensoriamento_remoto": _sensoriamento(fis),
        # licença dos dados de satélite (Copernicus Sentinel) quando houver cena Sentinel-2
        "atribuicoes": atribuicoes_dados(fis),
        "fotos_georreferenciadas": fotos_georreferenciadas(fis),
        "itens": linhas,
        "ocorrencias": [
            {**o.model_dump(mode="json"), "em": o.em.strftime("%d/%m/%Y %H:%M")} for o in fis.ocorrencias
        ],
        "alegacoes": [{**a, "valor_fmt": _fmt_num(a.get("valor"))} for a in fis.alegacoes],
        "alegacoes_x_evidencia": alegacoes_x_evidencia(fis),
        "regra_alegacoes": REGRA_ALEGACOES,
        "checagens": [
            {
                "id": c.id,
                "ferramenta": c.ferramenta,
                "status": c.status,
                "entrada_hash": c.entrada_hash,
                "span_id": c.trace_id,
                "fonte_versao": c.fonte_versao,
                "item_id": c.item_id,
                "evidencias": c.evidencias,
            }
            for c in fis.checagens
        ],
        "resumo": resumo,
        "cadeia": {"raiz": cadeia.raiz, "n": cadeia.n, "integra": cadeia.integra},
        "trace": {"arquivo": href_relativo(arq_trace, base), "uri": href_relativo(arq_trace, base)},
        "assinaturas": [a.model_dump(mode="json") for a in fis.aprovacoes],
        # template HTML com que o laudo foi gerado: o HTML de um laudo arquivado fica "não conferível" (e não
        # inválido) quando o template muda depois (laudo.audit.selo)
        "template": {"sha256": selo_mod.sha256_template_laudo()},
    }
    laudo["hash_raiz"] = hashchain.hash_raiz_laudo(cadeia.raiz, laudo)
    return laudo


def renderizar_html(laudo: dict[str, Any]) -> str:
    return _ENV.get_template("laudo.html.j2").render(l=laudo)


def gravar(laudo: dict[str, Any], html: str, diretorio: Path, prefixo: str) -> tuple[Path, Path]:
    diretorio.mkdir(parents=True, exist_ok=True)
    pj = diretorio / f"{prefixo}.json"
    ph = diretorio / f"{prefixo}.html"
    pj.write_text(json.dumps(laudo, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    ph.write_text(html, encoding="utf-8")
    return pj, ph


def diretorio_laudos(fis_id: str) -> Path:
    return _repo().dir.parent / "laudos" / fis_id


def registrar_emissao(fis: Fiscalizacao, data: dict[str, Any]) -> None:
    """Põe o rascunho emitido na cadeia de hash (evidência do tipo "documento", meta `laudo=True`)."""
    caminho = data.get("laudo_json")
    conteudo = (
        Path(caminho).read_bytes()
        if caminho and Path(caminho).exists()
        else json.dumps(data, sort_keys=True).encode()
    )
    est.adicionar_evidencia(
        fis,
        "documento",
        caminho=caminho,
        sha256=sha256_bytes(conteudo),
        meta={
            "laudo": True,
            "tipo_laudo": data.get("tipo", "rascunho"),
            "hash_raiz": data.get("hash_raiz"),
            "laudo_html": data.get("laudo_html"),
        },
    )


def ultimo_rascunho(fis: Fiscalizacao) -> dict[str, Any] | None:
    ev = next((e for e in reversed(fis.evidencias) if e.meta.get("laudo")), None)
    return dict(ev.meta, evidencia_id=ev.id) if ev else None


class ErroSelagem(RuntimeError):
    """O rascunho assinado não está disponível ou não confere: o laudo não é selado (nada é remontado)."""


def rascunho_assinado(fis: Fiscalizacao) -> tuple[dict[str, Any], Any]:
    """JSON do rascunho que o humano assinou e a evidência dele na cadeia. Confere o sha256 do arquivo com o
    registrado na cadeia e o hash raiz recalculado do conteúdo com o hash assinado; senão `ErroSelagem`."""
    if not fis.aprovacoes:
        raise ErroSelagem("sem assinatura humana registrada")
    assinado = fis.aprovacoes[-1].hash_assinado
    ev = next(
        (
            e
            for e in reversed(fis.evidencias)
            if e.tipo == "documento" and e.meta.get("laudo") and e.meta.get("hash_raiz") == assinado
        ),
        None,
    )
    if ev is None:
        raise ErroSelagem("a cadeia não tem o rascunho com o hash assinado")
    arq = Path(ev.caminho) if ev.caminho else None
    if arq is None or not arq.is_file():
        raise ErroSelagem("arquivo do rascunho assinado ausente")
    if sha256_bytes(arq.read_bytes()) != ev.sha256:
        raise ErroSelagem("o arquivo do rascunho não é o registrado na cadeia (sha256 diverge)")
    rasc = selo_mod.ler_laudo(arq)
    if rasc is None:
        raise ErroSelagem("rascunho assinado ilegível")
    corpo = {k: v for k, v in rasc.items() if k not in selo_mod.FORA_DO_CONTEUDO}
    if rasc.get("hash_raiz") != assinado or selo_mod.hash_do_conteudo(corpo) != assinado:
        raise ErroSelagem("o rascunho assinado foi alterado (hash raiz recalculado diverge do assinado)")
    return rasc, ev


def _registrar_indice(fis: Fiscalizacao) -> dict[str, Any]:
    """Registra os documentos da fiscalização no índice de documentos reutilizados, só na selagem. O índice é
    da área do agente (`laudo.agent.indice.registrar_na_selagem`); sem ele, a selagem segue e o retorno
    diz."""
    try:
        from laudo.agent.indice import registrar_na_selagem
    except ImportError:
        return {"registrado": False, "motivo": "laudo.agent.indice.registrar_na_selagem indisponível"}
    try:  # a função abre o próprio span (indice.registrar_na_selagem) e já trata falha de E/S
        n = registrar_na_selagem(fis, _repo().dir.parent)
    except Exception as e:  # noqa: BLE001 - o índice é auxiliar: a falha não desfaz o selo, mas fica dita
        log.warning("índice de documentos não registrado na selagem de %s: %s", fis.id, e)
        return {"registrado": False, "motivo": f"falha ao registrar no índice: {type(e).__name__}: {e}"[:200]}
    return {"registrado": True, "documentos": n if isinstance(n, (int, float)) else str(n)}


def selar(
    fis: Fiscalizacao, res: ResultadoVerificacao | None = None, hoje: date | None = None
) -> dict[str, Any]:
    """Gera o laudo selado (após a assinatura humana registrada em `fis.aprovacoes`) **a partir do rascunho
    assinado**: o conteúdo é o do rascunho; mudam só `tipo`, `gerado_em`, `assinaturas` e `cadeia`, e
    os valores da emissão ficam em `conteudo_assinado`. `res` e `hoje` ficam na assinatura por compatibilidade
    e não são usados: nada é recalculado do estado. Sem o rascunho assinado, ou com ele alterado,
    `ErroSelagem` e nada é gravado. Depois de gravar, registra os documentos no índice de reuso
    (`_registrar_indice`)."""
    rasc, _ = rascunho_assinado(fis)
    cadeia = hashchain.verificar_cadeia(fis.evidencias)
    laudo = {k: v for k, v in rasc.items() if k not in selo_mod.FORA_DO_CONTEUDO}
    laudo.update(
        tipo="selado",
        gerado_em=datetime.now().astimezone().isoformat(timespec="seconds"),
        assinaturas=[a.model_dump(mode="json") for a in fis.aprovacoes],
        cadeia={"raiz": cadeia.raiz, "n": cadeia.n, "integra": cadeia.integra},
    )
    laudo["hash_raiz"] = rasc["hash_raiz"]
    laudo["conteudo_assinado"] = {k: rasc[k] for k in selo_mod.CAMPOS_DO_SELO}
    laudo["selo"] = selo_mod.selo_v1(laudo)
    pj, ph = gravar(laudo, renderizar_html(laudo), diretorio_laudos(fis.id), "laudo_selado")
    return {
        "laudo_json": str(pj),
        "laudo_html": str(ph),
        "hash_raiz": laudo["hash_raiz"],
        "selo": laudo["selo"],
        "indice_documentos": _registrar_indice(fis),
    }


# ---------------------------------------------------------------------------
# Ferramentas registradas
# ---------------------------------------------------------------------------


class EntradaEmitirRascunho(BaseModel):
    fiscalizacao_id: str = Field(description="id da fiscalização (fis_...)")
    texto_redigido: str | None = Field(
        default=None,
        description="resumo opcional em pt-BR; só entra se todo número tiver lastro no estado (POL-05)",
    )


@registrar(
    "emitir_rascunho",
    "Gera o rascunho do laudo (HTML e JSON) quando o fiscal pede o laudo; se faltar "
    "evidência devolve BLOQUEADO_POLITICA com as pendências. Não assina nem envia para assinatura.",
    EntradaEmitirRascunho,
    timeout_s=20.0,
)
def emitir_rascunho(args: EntradaEmitirRascunho) -> Envelope:
    t0 = time.perf_counter()
    try:
        fis = _repo().carregar(args.fiscalizacao_id)
    except (FileNotFoundError, ValueError) as e:
        return Envelope.falha(
            "emitir_rascunho", CodigoErro.ENTRADA_INVALIDA, f"fiscalização não encontrada: {e}", t0=t0
        )
    pol = _politica()
    with otel.contexto_fiscalizacao(fis.id):
        if fis.estado_fsm in ("ASSINATURA", "SELADO"):
            return Envelope.falha(
                "emitir_rascunho",
                CodigoErro.BLOQUEADO_POLITICA,
                f"fiscalização em {fis.estado_fsm}: rascunho não pode ser refeito (POL-04)",
                t0=t0,
                data={"pendencias": [{"regra_id": "POL-04", "falta": "nova fiscalização"}]},
            )
        res = pol.verificador.recalcular(fis)
        dec = pol.autorizar_emissao(fis, res)
        if not dec.permitido:
            return Envelope.falha(
                "emitir_rascunho",
                CodigoErro.BLOQUEADO_POLITICA,
                dec.motivo,
                t0=t0,
                data={"pendencias": dec.pendencias, "policy_span_id": dec.span_id},
            )
        fis.campos = res.campos
        laudo = montar_laudo(fis, res, texto_redigido=args.texto_redigido, politica=pol)
        pj, ph = gravar(
            laudo, renderizar_html(laudo), diretorio_laudos(fis.id), f"rascunho_{laudo['hash_raiz'][:12]}"
        )
    return Envelope.sucesso(
        "emitir_rascunho",
        {
            "laudo_html": str(ph),
            "laudo_json": str(pj),
            "hash_raiz": laudo["hash_raiz"],
            "tipo": "rascunho",
            "resumo": laudo["resumo"]["texto"],
            "resumo_origem": laudo["resumo"]["origem"],
            "n_itens": len(laudo["itens"]),
            "policy_span_id": dec.span_id,
        },
        fonte_versao=VERSAO,
        t0=t0,
    )


class EntradaOcorrencia(BaseModel):
    fiscalizacao_id: str
    tipo: str = Field(description="pressao | injecao | fora_de_escopo | falha_ferramenta | outro")
    descricao: str
    evidencia_ref: str | None = None


@registrar(
    "registrar_ocorrencia",
    "Registra ocorrência (pressão, injeção, falha) na fiscalização, na cadeia de hash.",
    EntradaOcorrencia,
    timeout_s=2.0,
)
def registrar_ocorrencia(args: EntradaOcorrencia) -> Envelope:
    """Versão para API/MCP. Dentro do condutor a ocorrência é registrada no estado em memória."""
    t0 = time.perf_counter()
    tipos = {"pressao", "injecao", "fora_de_escopo", "falha_ferramenta", "outro"}
    if args.tipo not in tipos:
        return Envelope.falha(
            "registrar_ocorrencia", CodigoErro.ENTRADA_INVALIDA, f"tipo deve ser um de {sorted(tipos)}", t0=t0
        )
    try:
        fis = _repo().carregar(args.fiscalizacao_id)
        oc = est.registrar_ocorrencia(fis, args.tipo, args.descricao, args.evidencia_ref)
        _repo().salvar(fis)
    except (FileNotFoundError, ValueError, est.ViolacaoAppendOnly) as e:
        return Envelope.falha("registrar_ocorrencia", CodigoErro.ENTRADA_INVALIDA, str(e)[:200], t0=t0)
    return Envelope.sucesso(
        "registrar_ocorrencia",
        {"ocorrencia_id": oc.id, "sha256": fis.evidencias[-1].sha256},
        fonte_versao=VERSAO,
        t0=t0,
    )
