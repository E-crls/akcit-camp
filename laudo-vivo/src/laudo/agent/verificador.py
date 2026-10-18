"""Verificador independente: status por item e grounding numérico.

Independente do condutor: não lê nada que o LLM escreveu (nem fala do agente, nem argumentos propostos);
só olha checagens das ferramentas, evidências, itens da operação e alegações (que têm ponteiro para a fala).

- Status por campo: chama `avaliar_regras` quando ela existe no REGISTRO. Se não existe (ou falha, ou devolve
  algo fora do contrato), aplica uma **regra mínima própria, marcada como provisória**
  (`regra_id="PROVISORIO/MCR-2-7"`) que espelha as checagens; nunca fica sem status.
- Grounding numérico (POL-05): todo número de um texto livre (fala do agente, resumo do laudo) precisa existir
  no estado (com tolerância de arredondamento). Datas também.
- Sem fonte, sem afirmação: checagem de ferramenta que trabalha sobre evidência (vídeo, foto, NF-e, GTA,
  documento lido) e que não está ligada a nenhuma evidência da fiscalização não define campo, nem na regra
  provisória nem na entrada de `avaliar_regras`.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from laudo.agent.executor import ExecutorFerramentas, preencher_argumentos, sobre_evidencia
from laudo.contracts import (
    REGISTRO,
    Bloqueio,
    CampoLaudo,
    Checagem,
    Ferramenta,
    Fiscalizacao,
    ItemFinanciado,
)

REGRA_PROVISORIA = "PROVISORIO/MCR-2-7"
FONTE_PROVISORIA = "regra-provisoria-agente@0.1.0"

# Ferramenta → sufixo do campo do laudo (campo = "item:<id>:<sufixo>" ou "operacao:<sufixo>").
CAMPO_POR_FERRAMENTA = {
    "contar_bovinos_video": "quantidade",
    "conciliar_nfe": "nfe",
    "conciliar_gta": "gta",
    "integridade_foto": "existencia",
    "geofence": "existencia",
    "serie_ndvi": "ndvi",
    "checar_lotacao": "lotacao",
}
_STATUS_CAMPO = {
    "ok": "verificado",
    "divergente": "divergente",
    "indeterminado": "abstencao",
    "erro": "pendente",
}

_REQ_BOVINOS = [
    (
        "quantidade",
        "vídeo do lote passando pelo corredor (contagem por cruzamento de linha)",
        ["video"],
        "contar_bovinos_video",
    ),
    ("nfe", "NF-e (XML) da compra dos animais", ["nfe_xml"], "conciliar_nfe"),
    ("gta", "GTA do transporte dos animais", ["gta"], "conciliar_gta"),
]
_REQ_BENFEITORIA = [
    ("existencia", "foto georreferenciada do item, tirada de dentro da gleba", ["foto"], "integridade_foto")
]
_REQ_MAQUINA = [("nfe", "NF-e (XML) da compra", ["nfe_xml"], "conciliar_nfe")] + _REQ_BENFEITORIA


def requisitos_provisorios(itens: Iterable[ItemFinanciado]) -> list[dict[str, Any]]:
    reqs: list[dict[str, Any]] = []
    for item in itens:
        modelo = (
            _REQ_BOVINOS
            if item.tipo == "bovinos"
            else _REQ_MAQUINA
            if item.tipo == "maquina"
            else _REQ_BENFEITORIA
        )
        for suf, desc, tipos, ferr in modelo:
            reqs.append(
                {
                    "id": f"req_{item.id}_{suf}",
                    "campo": f"item:{item.id}:{suf}",
                    "item_id": item.id,
                    "descricao": f"{desc} — {item.descricao}",
                    "pedido": f"{desc} ({item.id})",
                    "tipos_evidencia": tipos,
                    "ferramenta": ferr,
                    "regra_id": REGRA_PROVISORIA,
                    "obrigatorio": True,
                }
            )
    return reqs


def normalizar_requisitos(fis: Fiscalizacao) -> list[dict[str, Any]]:
    """Requisitos do rulebook (vindos de planejar_metodo/avaliar_regras) ou, sem eles, os provisórios."""
    if not fis.requisitos:
        return requisitos_provisorios(fis.operacao.itens)
    saida = []
    for i, r in enumerate(fis.requisitos):
        r = dict(r)
        if not r.get("campo") and r.get("ferramenta") in CAMPO_POR_FERRAMENTA:
            alvo = f"item:{r['item_id']}" if r.get("item_id") else "operacao"
            r["campo"] = f"{alvo}:{CAMPO_POR_FERRAMENTA[r['ferramenta']]}"
        r.setdefault("id", f"req_{i}")
        r.setdefault("descricao", r.get("campo") or r["id"])
        r.setdefault("regra_id", REGRA_PROVISORIA)
        r.setdefault("obrigatorio", True)
        saida.append(r)
    return saida


def campo_justificavel(c: CampoLaudo) -> bool:
    """Divergente, em abstenção ou pendente que o rulebook deixa resolver por justificativa do fiscal (foto fora
    da gleba na faixa intermediária, rulebook 0.3.0: `valor.aceita_justificativa`)."""
    if c.status in ("divergente", "abstencao"):
        return True
    return c.status == "pendente" and isinstance(c.valor, dict) and bool(c.valor.get("aceita_justificativa"))


def campo_da_checagem(chk: Checagem) -> str | None:
    suf = CAMPO_POR_FERRAMENTA.get(chk.ferramenta)
    if suf is None:
        return None
    return f"item:{chk.item_id}:{suf}" if chk.item_id else f"operacao:{suf}"


class ResultadoVerificacao(BaseModel):
    campos: dict[str, CampoLaudo] = Field(default_factory=dict)
    requisitos: list[dict[str, Any]] = Field(default_factory=list)
    # Pendências que impedem o rascunho (POL-01): vêm de `avaliar_regras` ou, sem ele, da regra provisória.
    bloqueios: list[Bloqueio] = Field(default_factory=list)
    fonte: str = FONTE_PROVISORIA
    provisoria: bool = True
    requisitos_do_rulebook: bool = False  # True só quando `avaliar_regras` devolveu os requisitos
    span_id: str = ""
    aviso: str = ""


class Verificador:
    def __init__(
        self, registro: dict[str, Ferramenta] | None = None, executor: ExecutorFerramentas | None = None
    ):
        self.registro = REGISTRO if registro is None else registro
        self.executor = executor or ExecutorFerramentas(self.registro)

    # -- status por item -----------------------------------------------------
    def sem_lastro(self, fis: Fiscalizacao) -> list[Checagem]:
        """Checagens de ferramenta sobre evidência que não apontam para nenhuma evidência existente."""
        ids = {e.id for e in fis.evidencias}
        return [c for c in fis.checagens
                if sobre_evidencia(c.ferramenta, self.registro) and not any(e in ids for e in c.evidencias)]

    def _com_lastro(self, fis: Fiscalizacao) -> Fiscalizacao:
        """A fiscalização como as regras a veem: sem as checagens sem evidência (cópia rasa; o estado não
        muda)."""
        fora = {c.id for c in self.sem_lastro(fis)}
        if not fora:
            return fis
        return fis.model_copy(update={"checagens": [c for c in fis.checagens if c.id not in fora]})

    def recalcular(self, fis: Fiscalizacao) -> ResultadoVerificacao:
        requisitos = normalizar_requisitos(fis)
        aviso = ""
        fis_regras = self._com_lastro(fis)
        if "avaliar_regras" in self.registro:
            args = preencher_argumentos(self.registro["avaliar_regras"], fis_regras, {})
            env, span_id, _ = self.executor.executar("avaliar_regras", args)
            if env.ok and isinstance(env.data, dict) and "campos" in env.data:
                try:
                    brutos = env.data["campos"]
                    lista = brutos.values() if isinstance(brutos, dict) else brutos
                    campos = {c.campo: c for c in (CampoLaudo.model_validate(x) for x in lista)}
                    do_rulebook = bool(env.data.get("requisitos"))
                    reqs = env.data.get("requisitos") or requisitos
                    bloqueios = [Bloqueio.model_validate(b) for b in env.data.get("bloqueios") or []]
                    campos = self._preservar(fis, campos)
                    return ResultadoVerificacao(
                        campos=campos,
                        requisitos=reqs,
                        bloqueios=self._sem_abstencao_justificada(bloqueios, campos),
                        fonte=env.fonte_versao or "avaliar_regras",
                        provisoria=False,
                        requisitos_do_rulebook=do_rulebook,
                        span_id=span_id,
                    )
                except (ValidationError, TypeError, AttributeError) as e:
                    aviso = (
                        f"avaliar_regras devolveu campos fora do contrato ({type(e).__name__}); "
                        "regra provisória"
                    )
            else:
                aviso = "avaliar_regras falhou; regra provisória aplicada"
        campos = self._preservar(fis, self._campos_provisorios(fis_regras, requisitos))
        return ResultadoVerificacao(
            campos=campos,
            requisitos=requisitos,
            bloqueios=self._bloqueios_provisorios(fis_regras, requisitos, campos),
            aviso=aviso,
        )

    @staticmethod
    def _sem_abstencao_justificada(bloqueios: list[Bloqueio], campos: dict[str, CampoLaudo]) -> list[Bloqueio]:
        """Abstenção (ou pendência que aceita justificativa, rulebook 0.3.0) com justificativa humana registrada
        no estado não bloqueia mais (a justificativa pode ter chegado depois da avaliação)."""
        saida = []
        for b in bloqueios:
            c = campos.get(b.campo or "")
            if c is not None and c.justificativa_humana and (b.status == "abstencao" or campo_justificavel(c)):
                continue
            saida.append(b)
        return saida

    @staticmethod
    def _bloqueios_provisorios(
        fis: Fiscalizacao, requisitos: list[dict[str, Any]], campos: dict[str, CampoLaudo]
    ) -> list[Bloqueio]:
        """Sem `avaliar_regras`: evidência mínima de cada requisito obrigatório e metadados do item 4."""
        bloqueios: list[Bloqueio] = []
        for req in requisitos:
            if not req.get("obrigatorio", True):
                continue
            c = campos.get(req.get("campo", ""))
            regra = str(req.get("regra_id") or REGRA_PROVISORIA)
            if c is None or c.status == "pendente":
                falta = str(req.get("descricao") or req.get("campo"))
                motivo = c.motivo if c else "sem checagem"
                bloqueios.append(
                    Bloqueio(regra_id=regra, campo=req.get("campo"), status="pendente", falta=f"{falta} ({motivo})")
                )
            elif c.status == "abstencao" and not c.justificativa_humana:
                bloqueios.append(
                    Bloqueio(
                        regra_id=regra,
                        campo=c.campo,
                        status="abstencao",
                        falta=f"nova captura ou justificativa do fiscal ({c.motivo})",
                    )
                )
        ultimas_sr = {  # vale a última série por gleba/item
            chk.item_id: chk
            for chk in fis.checagens
            if chk.ferramenta == "serie_ndvi" and chk.status in ("ok", "divergente")
        }
        for chk in ultimas_sr.values():
            meta = chk.resultado.get("metadados_laudo") or chk.resultado
            faltam = [k for k in ("sensor", "datas", "metodologia") if not meta.get(k)]
            if faltam:
                bloqueios.append(
                    Bloqueio(
                        regra_id="MCR-2-7-item4",
                        campo=f"laudo:metadados_sensoriamento:{chk.id}",
                        status="pendente",
                        falta=f"metadados do sensoriamento remoto: {', '.join(faltam)}",
                    )
                )
        return bloqueios

    def aplicar(self, fis: Fiscalizacao, res: ResultadoVerificacao) -> None:
        fis.campos = res.campos
        # Requisitos só entram no estado quando vêm do rulebook (planejar_metodo ou avaliar_regras); os
        # provisórios são recalculados a cada vez e nunca são gravados como se fossem do rulebook.
        if not fis.requisitos and res.requisitos and res.requisitos_do_rulebook:
            fis.requisitos = res.requisitos

    @staticmethod
    def _preservar(fis: Fiscalizacao, campos: dict[str, CampoLaudo]) -> dict[str, CampoLaudo]:
        """Justificativa humana não se perde no recálculo."""
        for nome, c in campos.items():
            antigo = fis.campos.get(nome)
            if antigo and antigo.justificativa_humana and not c.justificativa_humana:
                c.justificativa_humana = antigo.justificativa_humana
        return campos

    def _campos_provisorios(
        self, fis: Fiscalizacao, requisitos: list[dict[str, Any]]
    ) -> dict[str, CampoLaudo]:
        por_campo: dict[str, list[Checagem]] = defaultdict(list)
        for chk in fis.checagens:
            c = campo_da_checagem(chk)
            if c:
                por_campo[c].append(chk)
        nomes = list(dict.fromkeys([r["campo"] for r in requisitos if r.get("campo")] + list(por_campo)))
        desc = {r["campo"]: r.get("descricao", "") for r in requisitos if r.get("campo")}
        saida: dict[str, CampoLaudo] = {}
        for nome in nomes:
            chks = por_campo.get(nome, [])
            suf = nome.rsplit(":", 1)[-1]
            if not chks:
                saida[nome] = CampoLaudo(
                    campo=nome,
                    status="pendente",
                    regra_id=REGRA_PROVISORIA,
                    motivo=f"sem checagem; falta: {desc.get(nome) or nome}",
                )
            elif suf == "quantidade":
                saida[nome] = self._quantidade(fis, nome, chks)
            elif suf == "existencia":
                saida[nome] = self._existencia(nome, chks)
            else:
                saida[nome] = self._simples(nome, chks)
        return saida

    @staticmethod
    def _base(nome: str, chks: list[Checagem], status: str, valor: Any, motivo: str) -> CampoLaudo:
        evs = list(dict.fromkeys(e for c in chks for e in c.evidencias))
        regra = next((c.regra_id for c in reversed(chks) if c.regra_id), None) or REGRA_PROVISORIA
        return CampoLaudo(
            campo=nome,
            valor=valor,
            status=status,
            regra_id=regra,
            evidencias=evs,  # type: ignore[arg-type]
            checagens=[c.id for c in chks],
            motivo=motivo,
        )

    def _simples(self, nome: str, chks: list[Checagem]) -> CampoLaudo:
        ultimas: dict[str, Checagem] = {}
        for c in chks:
            ultimas[c.ferramenta] = c
        status = [_STATUS_CAMPO[c.status] for c in ultimas.values()]
        final = (
            "divergente"
            if "divergente" in status
            else "pendente"
            if "pendente" in status
            else "abstencao"
            if "abstencao" in status
            else "verificado"
        )
        ult = list(ultimas.values())[-1]
        valor = next(
            (ult.resultado[k] for k in ("quantidade", "contagem", "valor") if k in ult.resultado), None
        )
        motivo = "; ".join(
            f"{c.ferramenta}: {c.status}"
            + (f" ({c.resultado.get('motivo')})" if c.resultado.get("motivo") else "")
            for c in ultimas.values()
        )
        return self._base(nome, chks, final, valor, motivo)

    def _existencia(self, nome: str, chks: list[Checagem]) -> CampoLaudo:
        por_ev: dict[str, dict[str, Checagem]] = defaultdict(dict)
        for c in chks:
            for ev in c.evidencias or [c.id]:
                por_ev[ev][c.ferramenta] = c
        integ_div = [
            ev
            for ev, d in por_ev.items()
            if d.get("integridade_foto") and d["integridade_foto"].status == "divergente"
        ]
        ok = [
            ev
            for ev, d in por_ev.items()
            if all(d.get(f) and d[f].status == "ok" for f in ("integridade_foto", "geofence"))
        ]
        geo_div = [
            ev for ev, d in por_ev.items() if d.get("geofence") and d["geofence"].status == "divergente"
        ]
        indet = [ev for ev, d in por_ev.items() if any(c.status == "indeterminado" for c in d.values())]
        if integ_div:
            return self._base(
                nome,
                chks,
                "divergente",
                None,
                f"integridade da foto reprovada em {', '.join(integ_div)} (indício de fraude)",
            )
        if ok:
            return self._base(
                nome, chks, "verificado", True, f"foto íntegra e dentro da gleba: {', '.join(ok)}"
            )
        if geo_div:
            return self._base(nome, chks, "divergente", None, f"foto fora da gleba: {', '.join(geo_div)}")
        if indet:
            return self._base(
                nome,
                chks,
                "abstencao",
                None,
                "checagem indeterminada (GPS impreciso ou sem EXIF): repetir a captura no app",
            )
        faltam = sorted({f for d in por_ev.values() for f in ("integridade_foto", "geofence") if f not in d})
        return self._base(nome, chks, "pendente", None, f"falta checagem: {', '.join(faltam) or 'erro'}")

    def _quantidade(self, fis: Fiscalizacao, nome: str, chks: list[Checagem]) -> CampoLaudo:
        item_id = nome.split(":")[1]
        item = next((i for i in fis.operacao.itens if i.id == item_id), None)
        por_lote: dict[str, Checagem] = {}
        for c in chks:
            if c.ferramenta != "contar_bovinos_video":
                continue
            lote = str(c.resultado.get("lote") or (c.evidencias[0] if c.evidencias else c.id))
            por_lote[lote] = c
        validas = [c for c in por_lote.values() if c.status != "erro"]
        if not validas:
            return self._base(nome, chks, "pendente", None, "contagem com erro de ferramenta; repetir")
        indet = [c for c in validas if c.status == "indeterminado" or _contagem(c) is None]
        if indet:
            motivos = "; ".join(
                "; ".join(c.resultado.get("pedidos_recaptura") or [])
                or str(c.resultado.get("motivo", "contagem indeterminada"))
                for c in indet
            )
            return self._base(
                nome, chks, "abstencao", None, f"{motivos}: filme o lote passando pelo corredor, sem oclusão"
            )
        total = sum(_contagem(c) for c in validas)  # type: ignore[misc]
        lo = sum(_intervalo(c)[0] for c in validas)
        hi = sum(_intervalo(c)[1] for c in validas)
        esperado = item.quantidade if item else None
        alegs = [
            a for a in fis.alegacoes if a.get("item_id") == item_id and a.get("grandeza") == "quantidade"
        ]
        txt_aleg = f"; alegação do fiscal: {_fmt(alegs[-1]['valor'])}" if alegs else ""
        base = f"contagem {_fmt(total)} (intervalo {_fmt(lo)} a {_fmt(hi)}) em {len(validas)} vídeo(s)"
        if esperado is None:
            return self._base(nome, chks, "abstencao", total, f"{base}; quantidade financiada não informada")
        if lo <= esperado <= hi:
            return self._base(
                nome, chks, "verificado", total, f"{base}; financiado {_fmt(esperado)}{txt_aleg}"
            )
        return self._base(nome, chks, "divergente", total, f"{base}; financiado {_fmt(esperado)}{txt_aleg}")


def _contagem(c: Checagem) -> float | None:
    for k in ("contagem", "total", "n", "quantidade"):
        v = c.resultado.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return None


def _intervalo(c: Checagem) -> tuple[float, float]:
    n = _contagem(c) or 0.0
    for k in ("intervalo", "ic", "ic95", "ic80"):
        v = c.resultado.get(k)
        if isinstance(v, (list, tuple)) and len(v) == 2:
            return float(v[0]), float(v[1])
        if isinstance(v, dict) and {"min", "max"} <= set(v):
            return float(v["min"]), float(v["max"])
    return n, n


def _fmt(v: Any) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).replace(".", ",") if isinstance(v, float) else str(v)


# ---------------------------------------------------------------------------
# Grounding numérico (POL-05)
# ---------------------------------------------------------------------------

_REMOVER = [
    re.compile(r"\b(?:ev|chk|oc|fis|req|alg|laudo)_[0-9a-zA-Z_]+\b"),
    re.compile(r"\b[0-9a-f]{12,64}\b"),
    re.compile(r"\b(?:qwen|gemma|llama|mistral)[\w.:-]*", re.IGNORECASE),
    re.compile(r"\b[A-Z][A-Za-z]*(?:[-/.]\w+)*-\d[\w./-]*"),  # MCR-2-7-item16, POL-02, Sentinel-2
    re.compile(
        r"\b(?:MCR|Res\.?|Resolução|Resolucao|CMN|Lei|Decreto|MP|IN|Portaria|art\.?|artigo|item|"
        r"inciso|alínea|seção|se[cç][aã]o|§)\s*(?:n[º°o.]\s*)?\d[\d.\-/]*(?:/\d{2,4})?",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:NCM|CFOP|CNAE)\s*[\d.]+", re.IGNORECASE),
]
# Identificadores (chave de acesso, CPF/CNPJ, número de documento) são referências, não números que o texto
# afirma: mascarados ou não, não entram no grounding (antes o filtro existia só no harness da avaliação).
IDENTIFICADORES = [
    re.compile(r"\S*\d[\d.]*(?:…|\.\.\.)[\d.]*\d\S*"),  # chave mascarada: 522607…27121456
    re.compile(r"\S*\*{2,}\S*"),  # documento mascarado: ***.456.789-** e 12.345.678/****-**
    re.compile(r"\[(?:CPF|CNPJ|TELEFONE|EMAIL|NOME)\]"),  # marcadores do POL-08
    re.compile(r"(?<![\d.])\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)"),  # CPF formatado
    re.compile(r"(?<![0-9A-Za-z])[0-9A-Z]{2}\.[0-9A-Z]{3}\.[0-9A-Z]{3}/[0-9A-Z]{4}-\d{2}(?!\d)"),  # CNPJ
    re.compile(r"(?<![\d.,])(?:\d{4}[ .]){5,10}\d{1,4}(?!\d|,\d)"),  # chave impressa em blocos de 4 (DANFE)
    re.compile(r"(?<![\d.,])\d{11,}(?!\d|,\d)"),  # sequência longa de dígitos: chave/CPF/CNPJ, nunca quantidade
    re.compile(r"(?<![\d.,])0\d{2}(?:\.\d{3}){2}(?!\d|,\d)"),  # número da NF-e impresso: 000.004.051
]


def remover_identificadores(texto: str) -> str:
    """Tira do texto chaves de acesso, CPF/CNPJ (mascarados ou não) e números de documento impressos."""
    t = texto or ""
    for rx in IDENTIFICADORES:
        t = rx.sub(" ", t)
    return t


_DATA_BR = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})(?!\d)")
_DATA_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_HORA = re.compile(r"(?<![\d:])(\d{1,2})[:h](\d{2})(?![\d:])")
_NUM = re.compile(r"(?<![\w.,/])(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)(?!\d)(\s*%)?")


class NumeroTexto(BaseModel):
    bruto: str
    valor: float
    casas: int = 0
    percentual: bool = False


class ResultadoGrounding(BaseModel):
    ok: bool
    numeros: list[NumeroTexto] = Field(default_factory=list)
    sem_lastro: list[str] = Field(default_factory=list)


def _valor_pt(bruto: str) -> tuple[float, int]:
    s = bruto
    if "," in s:
        casas = len(s.split(",")[1])
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", s):
        casas = 0
        s = s.replace(".", "")
    else:
        casas = len(s.split(".")[1]) if "." in s else 0
    return float(s), casas


def _datas_do_texto(texto: str) -> tuple[list[date | None], str]:
    datas: list[date | None] = []

    def br(m: re.Match) -> str:
        d, mth, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
        a = a + 2000 if a < 100 else a
        try:
            datas.append(date(a, mth, d))
        except ValueError:
            datas.append(None)
        return " "

    def iso(m: re.Match) -> str:
        try:
            datas.append(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            datas.append(None)
        return " "

    texto = _DATA_BR.sub(br, texto)
    texto = _DATA_ISO.sub(iso, texto)
    return datas, texto


def extrair_numeros(texto: str) -> tuple[list[NumeroTexto], list[date | None], list[str]]:
    """Números (pt-BR), datas e horas de um texto livre, ignorando IDs, hashes, citações normativas e
    identificadores de documento (chave de acesso, CPF/CNPJ, mascarados ou não)."""
    t = remover_identificadores(texto or "")
    for rx in _REMOVER:
        t = rx.sub(" ", t)
    datas, t = _datas_do_texto(t)
    horas = [f"{int(h):02d}:{mm}" for h, mm in _HORA.findall(t)]
    t = _HORA.sub(" ", t)
    nums = []
    for m in _NUM.finditer(t):
        v, casas = _valor_pt(m.group(1))
        nums.append(NumeroTexto(bruto=m.group(0).strip(), valor=v, casas=casas, percentual=bool(m.group(2))))
    return nums, datas, horas


def _walk(obj: Any, nums: set[float], datas: set[date], horas: set[str], textos: bool) -> None:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        nums.add(float(obj))
    elif isinstance(obj, str):
        if re.match(r"^\d{4}-\d{2}-\d{2}", obj):
            try:
                dt = datetime.fromisoformat(obj)
                datas.add(dt.date())
                if "T" in obj or " " in obj:
                    horas.add(dt.strftime("%H:%M"))
            except ValueError:
                try:
                    datas.add(date.fromisoformat(obj[:10]))
                except ValueError:
                    pass
            return
        if textos:
            ns, ds, hs = extrair_numeros(obj)
            nums.update(n.valor for n in ns)
            datas.update(d for d in ds if d)
            horas.update(hs)
    elif isinstance(obj, dict):
        for v in obj.values():
            _walk(v, nums, datas, horas, textos)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _walk(v, nums, datas, horas, textos)


def lastro_do_estado(
    fis: Fiscalizacao, extras: Iterable[Any] = (), hoje: date | None = None
) -> tuple[set[float], set[date], set[str]]:
    """Valores numéricos, datas e horas com lastro no estado (ferramentas, operação, alegações, contagens)."""
    nums: set[float] = set()
    datas: set[date] = {hoje or datetime.now().astimezone().date()}
    horas: set[str] = set()
    _walk(fis.operacao.model_dump(mode="json"), nums, datas, horas, textos=True)
    for chk in fis.checagens:
        _walk(chk.resultado, nums, datas, horas, textos=True)
    for c in fis.campos.values():
        _walk(c.valor, nums, datas, horas, textos=False)
        _walk(c.motivo, nums, datas, horas, textos=True)
    for a in fis.alegacoes:
        _walk(
            {k: v for k, v in a.items() if k not in ("trecho", "ponteiro")}, nums, datas, horas, textos=False
        )
    for ev in fis.evidencias:  # metadados numéricos (GPS, datas); textos de OCR/ASR não dão lastro
        _walk(ev.gps.model_dump() if ev.gps else None, nums, datas, horas, textos=False)
        _walk(ev.capturada_em.isoformat() if ev.capturada_em else None, nums, datas, horas, textos=False)
        _walk(ev.recebida_em.isoformat(), nums, datas, horas, textos=False)
    for oc in fis.ocorrencias:
        _walk(oc.em.isoformat(), nums, datas, horas, textos=False)
    # contagens derivadas do próprio estado
    contagens: dict[str, int] = defaultdict(int)
    for ev in fis.evidencias:
        contagens[f"ev:{ev.tipo}"] += 1
    for chk in fis.checagens:
        contagens[f"chk:{chk.status}"] += 1
    for c in fis.campos.values():
        contagens[f"campo:{c.status}"] += 1
        if c.regra_id != "OP-agregacao-item":  # o resumo do laudo conta aspectos, sem o status agregado do item
            contagens[f"aspecto:{c.status}"] += 1
            if c.status == "divergente" and c.justificativa_humana:
                contagens["aspecto:divergente_justificado"] += 1
    for oc in fis.ocorrencias:
        contagens[f"oc:{oc.tipo}"] += 1
    nums.update(float(v) for v in contagens.values())
    nums.update(
        float(x)
        for x in (
            len(fis.evidencias),
            len(fis.checagens),
            len(fis.campos),
            len(fis.ocorrencias),
            len(fis.alegacoes),
            len(fis.operacao.itens),
        )
    )
    _walk(list(extras), nums, datas, horas, textos=True)
    return nums, datas, horas


def _casa(s: float, v: float, casas: int) -> bool:
    """Igualdade exata ou arredondamento do valor do estado para as casas do texto. Sem casas decimais no
    texto, o arredondamento só vale para |valor| ≥ 10 (números pequenos precisam bater exatamente)."""
    if abs(s - v) <= 1e-9 * max(1.0, abs(s)):
        return True
    if casas == 0 and abs(s) < 10:
        return False
    return round(s, casas) == round(v, casas)


def _tem_lastro(n: NumeroTexto, valores: set[float]) -> bool:
    for s in valores:
        if _casa(s, n.valor, n.casas):
            return True
        if n.percentual and (_casa(s * 100, n.valor, n.casas) or _casa(s, n.valor / 100, n.casas + 2)):
            return True
    return False


def grounding(
    texto: str, fis: Fiscalizacao, extras: Iterable[Any] = (), hoje: date | None = None
) -> ResultadoGrounding:
    """POL-05: todo número/data/hora do texto precisa existir no estado."""
    nums, datas, horas = extrair_numeros(texto)
    v_ok, d_ok, h_ok = lastro_do_estado(fis, extras=extras, hoje=hoje)
    sem = [n.bruto for n in nums if not _tem_lastro(n, v_ok)]
    sem += [d.isoformat() if d else "data inválida" for d in datas if d is None or d not in d_ok]
    sem += [h for h in horas if h not in h_ok]
    return ResultadoGrounding(ok=not sem, numeros=nums, sem_lastro=sem)
