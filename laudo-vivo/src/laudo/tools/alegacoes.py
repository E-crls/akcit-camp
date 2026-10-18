"""Ferramenta `conciliar_alegacoes`: o que a fiscal disse (fala livre) × o que as checagens mostram.

A fala no curral mistura contagem "no olho", metragem de cerca, item que não foi financiado e informação que
ninguém pediu. O condutor extrai as alegações (número + grandeza + trecho literal com ponteiro); esta
ferramenta, determinística, confronta cada uma com a evidência e devolve um status **por alegação**:

| status | quando | regra |
|---|---|---|
| `confere` | a alegação bate com a evidência (contagem dentro do intervalo do vídeo; NF; projeto) | MCR-2-7-item1 |
| `divergente` | declaração × evidência: "contei 29" e o vídeo deu 12 [12–17]; ou declaração × declaração ("a cerca está concluída" e "fizeram só 800 m") | OP-alegacao-declaracao-x-evidencia |
| `pendente` | declaração × projeto sem evidência física que resolva: "só 800 m" de 1.200 m projetados (obra declarada incompleta) | MCR-2-7-item16-benfeitorias-conclusao |
| `registro` | menção a item não financiado ou a categoria diferente da financiada (trator, galpão, bezerros nascidos na fazenda): fica registrada, não muda campo | MCR-2-7-item1-registro-verificacoes |
| `sem_evidencia` | ainda não há checagem para confrontar (vídeo não enviado, NF não lida) | MCR-2-7-item1-registro-verificacoes |

Alegação nunca define o status de um campo do laudo (contrato): quem decide é o verificador a partir das
checagens. Aqui só se aponta onde a fala e a prova não batem, para o laudo registrar as duas e para a
fiscal justificar (POL-02). Tolerâncias são parâmetros explícitos de entrada.
"""

from __future__ import annotations

import re
import time
import unicodedata
from typing import Any, Literal

from pydantic import BaseModel, Field

from laudo.contracts import CodigoErro, Envelope, ItemFinanciado, registrar

VERSAO = "alegacoes@0.1.0"
StatusAlegacao = Literal["confere", "divergente", "pendente", "registro", "sem_evidencia"]

# Objeto da alegação reconhecido no trecho literal (determinístico; não depende do LLM).
_OBJETOS: list[tuple[str, str, re.Pattern[str]]] = [
    ("bovinos", "bezerro", re.compile(r"\bbezerr[oa]s?\b")),
    ("bovinos", "vaca", re.compile(r"\bvacas?\b|\bmatriz(es)?\b")),
    ("bovinos", "novilha", re.compile(r"\bnovilh[oa]s?\b")),
    ("bovinos", "touro", re.compile(r"\btour(o|os|inhos?)\b|\breprodutor(es)?\b")),
    ("bovinos", "garrote", re.compile(r"\bgarrotes?\b|\bbois?\b")),
    ("bovinos", None, re.compile(r"\bcabe[cç]as?\b|\bbovinos?\b|\banimais\b|\breses\b|\bgado\b|\blote\b")),
    ("cerca", None, re.compile(r"\bcercas?\b|\bmour[oõ]es\b|\barame\b")),
    ("curral", None, re.compile(r"\bcurra(l|is)\b|\bbrete\b|\btronco\b")),
    ("galpao", None, re.compile(r"\bgalp(ao|oes)\b|\bbarrac(ao|oes)\b|\bestabulo\b")),
    ("maquina", None, re.compile(r"\btrator(es)?\b|\bcolheitadeira\b|\bplantadeira\b|\bcarreta\b|\bmaquin")),
]
_FEMEAS = {"vaca", "novilha", "bezerra"}
_COMPATIVEIS = {  # categoria financiada → categorias faladas que se referem ao mesmo lote
    "vaca": {"vaca", None}, "vaca leiteira": {"vaca", None}, "novilha": {"novilha", "vaca", None},
    "touro": {"touro", None}, "garrote": {"garrote", None}, "boi": {"garrote", None},
}


def _norm(t: str | None) -> str:
    t = unicodedata.normalize("NFKD", t or "")
    return "".join(ch for ch in t if not unicodedata.combining(ch)).lower()


# Em contagem, "curral" e "cerca" são lugar ("contei 29 no curral"), não o objeto contado.
_OBJETOS_POR_GRANDEZA = {"quantidade": {"bovinos", "maquina", "galpao"}, "comprimento": {"cerca", "curral", "galpao"},
                         "area": {"galpao", "curral"}}
_RX_CONTAGEM = re.compile(r"\b(cont(ei|amos|ando|agem|ado|ou)|achei|acharam|deu|deram|tinha|tinham|passou|passaram|"
                          r"lote)\b")
_RX_OUTRA_UNIDADE = re.compile(r"\b(km|quil[oô]metros?|horas?|h|anos?|filhos?|dias?|reais|r\$|litros?|kg|quilos?)\b")


def objeto_do_trecho(trecho: str, grandeza: str | None = None) -> tuple[str | None, str | None]:
    """(tipo de item, categoria animal) mencionados no trecho; o primeiro que aparecer no texto vence.
    Com `grandeza`, só contam os objetos que fazem sentido para ela."""
    t = _norm(trecho)
    validos = _OBJETOS_POR_GRANDEZA.get(grandeza or "", None)
    achados = [(m.start(), tipo, cat) for tipo, cat, rx in _OBJETOS
               if (validos is None or tipo in validos) and (m := rx.search(t))]
    if not achados:
        return None, None
    _, tipo, cat = min(achados, key=lambda x: (x[0], x[2] is None))
    return tipo, cat


class ParametrosAlegacoes(BaseModel):
    tolerancia_comprimento_pct: float = Field(0.05, ge=0, le=1, description="fração do projeto (benfeitoria)")
    tolerancia_valor_pct: float = Field(0.05, ge=0, le=1, description="fração do valor da NF")


class EntradaConciliarAlegacoes(BaseModel):
    fiscalizacao: dict[str, Any] | None = Field(None, description="Estado da fiscalização (preenchido pelo "
                                                                  "condutor): alegações, checagens e itens")
    alegacoes: list[dict[str, Any]] = Field(default_factory=list, description="Alegações com trecho e ponteiro "
                                                                              "(se não vier a fiscalização)")
    itens: list[ItemFinanciado] = Field(default_factory=list)
    checagens: list[dict[str, Any]] = Field(default_factory=list, description="{ferramenta, status, item_id, "
                                                                              "resultado}")
    parametros: ParametrosAlegacoes = Field(default_factory=ParametrosAlegacoes)


def _ultima(checagens: list[dict[str, Any]], ferramenta: str, item_id: str | None) -> dict[str, Any] | None:
    for c in reversed(checagens):
        if c.get("ferramenta") == ferramenta and c.get("status") != "erro" and c.get("item_id") in (None, item_id):
            return c
    return None


def _fmt(v: float) -> str:
    return f"{int(v)}" if float(v).is_integer() else f"{v:.2f}".replace(".", ",")


def conciliar(alegacoes: list[dict[str, Any]], itens: list[ItemFinanciado], checagens: list[dict[str, Any]],
              p: ParametrosAlegacoes | None = None) -> dict[str, Any]:
    """Função pura: status por alegação."""
    p = p or ParametrosAlegacoes()
    por_id = {i.id: i for i in itens}
    saida = []
    for a in alegacoes:
        trecho = str(a.get("trecho") or "")
        grandeza = a.get("grandeza")
        valor = a.get("valor")
        tipo_falado, cat_falada = objeto_do_trecho(trecho, grandeza)
        item = por_id.get(a.get("item_id") or "")
        base = {"alegacao_id": a.get("id"), "trecho": trecho, "ponteiro": a.get("ponteiro"), "grandeza": grandeza,
                "valor": valor, "item_id": item.id if item else None}

        def res(status: StatusAlegacao, regra: str, motivo: str, base: dict[str, Any] = base, **evid: Any) -> None:
            saida.append({**base, "status": status, "regra_id": regra, "motivo": motivo, "evidencia": evid})

        if valor is None:
            res("registro", "MCR-2-7-item1-registro-verificacoes", "alegação sem número")
            continue
        if grandeza == "quantidade" and not float(valor).is_integer():  # "8,5 vacas" é hora mal lida, não animal
            res("registro", "MCR-2-7-item1-registro-verificacoes", "quantidade não inteira: não é contagem de animais")
            continue
        unidade = _norm(str(a.get("unidade") or ""))
        if grandeza in ("quantidade", "comprimento", "area") and tipo_falado is None and (
                _RX_OUTRA_UNIDADE.search(unidade) or (grandeza != "quantidade" and unidade.startswith("km"))
                or (grandeza == "quantidade" and not _RX_CONTAGEM.search(_norm(trecho)))
                or (grandeza != "quantidade" and _RX_OUTRA_UNIDADE.search(_norm(trecho)))):
            # número sem objeto reconhecível ("tem 3 filhos", "30 km de chão"): nunca vira contagem nem metragem
            res("registro", "MCR-2-7-item1-registro-verificacoes",
                "número sem objeto financiado reconhecível no trecho: registrado, não confrontado")
            continue
        # o objeto dito no trecho manda: "2 tratores" nunca vira contagem do lote de vacas
        if tipo_falado is not None and (item is None or item.tipo != tipo_falado):
            cand = [i for i in itens if i.tipo == tipo_falado]
            item = cand[0] if len(cand) == 1 else None
            base["item_id"] = item.id if item else None
        if item is None and tipo_falado is None and grandeza in ("quantidade", "comprimento"):
            # "contei 29 no curral", "fizeram só 800 metros": sem objeto dito, vale o único item do tipo óbvio
            cand = [i for i in itens if i.tipo == ("bovinos" if grandeza == "quantidade" else "cerca")]
            item = cand[0] if len(cand) == 1 else None
            base["item_id"] = item.id if item else None
        if item is None:
            alvo = tipo_falado or "objeto não identificado"
            res("registro", "MCR-2-7-item1-registro-verificacoes",
                f"menção a {alvo} sem item financiado correspondente: registrada, não altera campo do laudo")
            continue
        cat_fin = (item.categoria_animal or "").lower()
        if item.tipo == "bovinos" and cat_falada is not None and cat_fin and                 cat_falada not in _COMPATIVEIS.get(cat_fin, {cat_fin}):
            res("registro", "MCR-2-7-item1-registro-verificacoes",
                f"fala de {cat_falada}(s); o item financiado é {item.categoria_animal}: registrada como "
                "informação, não confrontada com o lote")
            continue
        v = float(valor)
        if item.tipo == "bovinos" and grandeza == "quantidade":
            cont = _ultima(checagens, "contar_bovinos_video", item.id)
            r = (cont or {}).get("resultado") or {}
            if cont and cont.get("status") == "ok" and r.get("intervalo"):
                lo, hi = (float(x) for x in r["intervalo"])
                if lo <= v <= hi:
                    res("confere", "OP-bovinos-contagem-tolerancia",
                        f"declarou {_fmt(v)}; o vídeo contou {r.get('contagem')} [{_fmt(lo)}–{_fmt(hi)}]",
                        contagem=r.get("contagem"), intervalo=[lo, hi])
                else:
                    res("divergente", "OP-alegacao-declaracao-x-evidencia",
                        f"declarou {_fmt(v)}; o vídeo contou {r.get('contagem')} [{_fmt(lo)}–{_fmt(hi)}]: a "
                        "declaração não bate com a evidência; o laudo registra as duas e pede justificativa",
                        contagem=r.get("contagem"), intervalo=[lo, hi])
                continue
            nf = _ultima(checagens, "conciliar_nfe", item.id)
            cab = (((nf or {}).get("resultado") or {}).get("totais") or {}).get("cabecas")
            if cab is not None:
                st: StatusAlegacao = "confere" if abs(cab - v) < 1e-9 else "divergente"
                res(st, "OP-alegacao-declaracao-x-evidencia",
                    f"declarou {_fmt(v)}; a NF-e comprova {cab} cabeças (sem contagem física conclusiva ainda)",
                    nfe_cabecas=cab)
                continue
            res("sem_evidencia", "MCR-2-7-item1-registro-verificacoes",
                f"declarou {_fmt(v)} cabeças; ainda não há contagem nem NF para confrontar (envie o vídeo do lote)")
            continue
        if item.tipo in ("cerca", "benfeitoria") and grandeza == "comprimento":
            if not item.quantidade:
                res("sem_evidencia", "MCR-2-7-item1-registro-verificacoes", "projeto sem metragem para comparar")
                continue
            minimo = item.quantidade * (1 - p.tolerancia_comprimento_pct)
            concl = _ultima(checagens, "declaracao_conclusao", item.id)
            if v >= minimo:
                res("confere", "MCR-2-7-item16-benfeitorias-conclusao",
                    f"declarou {_fmt(v)} m; projeto {_fmt(item.quantidade)} m", projeto_m=item.quantidade)
            elif concl and concl.get("status") == "ok":
                res("divergente", "OP-alegacao-declaracao-x-evidencia",
                    f"declarou {_fmt(v)} m de {_fmt(item.quantidade)} m do projeto, mas a obra foi declarada "
                    "concluída: as duas declarações não batem", projeto_m=item.quantidade)
            else:
                res("pendente", "MCR-2-7-item16-benfeitorias-conclusao",
                    f"declarou {_fmt(v)} m de {_fmt(item.quantidade)} m do projeto ({v / item.quantidade:.0%}): "
                    "obra declarada incompleta; confira a conclusão e registre a justificativa",
                    projeto_m=item.quantidade)
            continue
        if grandeza == "valor":
            nf = _ultima(checagens, "conciliar_nfe", item.id)
            vn = (((nf or {}).get("resultado") or {}).get("totais") or {}).get("valor_bovinos_rs")
            if vn:
                st = "confere" if abs(vn - v) <= p.tolerancia_valor_pct * vn else "divergente"
                res(st, "OP-alegacao-declaracao-x-evidencia",
                    f"declarou R$ {_fmt(v)}; a NF-e soma R$ {_fmt(vn)}", nfe_valor=vn)
            else:
                res("sem_evidencia", "MCR-2-7-item1-registro-verificacoes", "sem NF conciliada para comparar")
            continue
        res("registro", "MCR-2-7-item1-registro-verificacoes",
            f"{grandeza} sobre {item.tipo}: sem checagem que a confronte; registrada")
    cont = {s: sum(1 for x in saida if x["status"] == s) for s in ("confere", "divergente", "pendente", "registro",
                                                                    "sem_evidencia")}
    status = ("divergente" if cont["divergente"] else "indeterminado" if cont["pendente"] or cont["sem_evidencia"]
              else "ok")
    motivo = "; ".join(f"{x['trecho'][:40]!r}: {x['status']}" for x in saida if x["status"] != "confere")[:600]
    return {"status": status, "alegacoes": saida, "contagem_status": cont,
            "motivo": motivo or ("sem alegações" if not saida else "todas as alegações conferem")}


@registrar(
    "conciliar_alegacoes",
    "Confronta as alegações extraídas da fala do fiscal (com trecho e ponteiro) com as checagens: contagem do "
    "vídeo, NF-e, projeto e declarações. Devolve status por alegação (confere, divergente, pendente, registro, "
    "sem_evidencia). Não altera campo do laudo.",
    EntradaConciliarAlegacoes,
)
def conciliar_alegacoes(args: EntradaConciliarAlegacoes) -> Envelope:
    t0 = time.perf_counter()
    nome = "conciliar_alegacoes"
    alegacoes, itens, checagens = list(args.alegacoes), list(args.itens), list(args.checagens)
    if args.fiscalizacao:
        fis = args.fiscalizacao
        alegacoes = alegacoes or list(fis.get("alegacoes") or [])
        try:
            itens = itens or [ItemFinanciado.model_validate(i) for i in (fis.get("operacao") or {}).get("itens") or []]
        except ValueError as e:
            return Envelope.falha(nome, CodigoErro.ENTRADA_INVALIDA, f"itens inválidos: {e}"[:300], t0=t0)
        checagens = checagens or [{"ferramenta": c.get("ferramenta"), "status": c.get("status"),
                                   "item_id": c.get("item_id"), "resultado": c.get("resultado") or {}}
                                  for c in fis.get("checagens") or []]
    if not alegacoes:
        return Envelope.falha(nome, CodigoErro.SEM_DADOS, "nenhuma alegação para conciliar", t0=t0)
    try:
        data = conciliar(alegacoes, itens, checagens, args.parametros)
    except Exception as e:  # noqa: BLE001 - nunca valor inventado
        return Envelope.falha(nome, CodigoErro.ERRO_INTERNO, f"{type(e).__name__}: {e}"[:300], t0=t0)
    return Envelope.sucesso(nome, data, fonte_versao=VERSAO, t0=t0)
