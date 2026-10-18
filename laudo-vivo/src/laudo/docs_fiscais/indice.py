"""Índice local de documentos que já comprovaram uma operação (GTA e chave de NF-e), só com HMAC.

Análogo, do lado da IF, da regra 10ZF04-20 da NT 2024.003 v1.03 (rejeição 838, "Guia de Trânsito já
utilizada", facultativa por UF): a SEFAZ confere a guia na base integrada com o órgão sanitário; a IF só tem
as fiscalizações que ela mesma selou nesta instalação.

**Chave: a operação de crédito, não a fiscalização.** Refiscalizar a mesma operação (nova visita, laudo
refeito, revisão) reapresenta os mesmos documentos de forma legítima. Reuso é o mesmo documento comprovando
**outra operação** (MCR 2-7-6-b e 2-7-7-d, aplicáveis à pecuária pelo item 9: elementos de duplicidade de
crédito ou de recuperação de capital investido).

**Duas fases, separadas de propósito:**

- consulta (`conferir_reuso`): só lê. É o que `conciliar_nfe` e `conciliar_gta` fazem quando recebem
  `indice_documentos` + `operacao_ref`. A conciliação roda a cada envio, com estados intermediários (documento
  enviado por engano e depois trocado); por isso nunca grava, e as duas ferramentas continuam sem efeito
  colateral (inclusive no servidor MCP somente leitura);
- registro (`registrar_documentos`, `registrar_fiscalizacao`): só os documentos que **comprovaram** o item num
  laudo selado (assinado pelo humano): conciliação final (não substituída pela reconciliação cumulativa), com
  status `ok` e ligada a uma evidência da fiscalização (`documentos_selaveis`). Documento enviado por engano
  (a conciliação que o inclui diverge ou fica indeterminada, ou foi substituída) e leitura de foto não
  validada não entram: um registro errado faria a operação de verdade parecer "reuso". Quem chama no produto
  é a selagem (`laudo.agent.indice.registrar_na_selagem`, que confere a etapa SELADO e a assinatura); o
  runner dos casos públicos e o `conferir_indice_zf.py` simulam a selagem com `registrar_fiscalizacao`.

Cada linha do JSONL guarda só hashes: `{tipo, hash, operacao, fiscalizacao, item_id, versao, instalacao,
registrado_em}`, com `hash` = HMAC-SHA256 com o **sal da instalação** (`laudo.privacidade.salgar`) do
identificador da GTA (`UF-SÉRIE-NÚMERO`, normalizado) ou da chave de acesso da NF-e
(`privacidade.hash_chave`, o mesmo `chave_hash` do estado) e `operacao` = HMAC da referência da operação
(ref. Bacen). Valor em claro nunca é gravado (a chave embute o documento do emitente). Hashes de instalações
diferentes não se comparam (é o objetivo do sal): o índice vale dentro da instalação.

Status da consulta, coerente com a política de foto duplicada
(`vision/integridade.py`):

- já registrado para **outra operação** → `divergente` (um documento não comprova duas compras);
- registrado para **esta operação, só para outro item** → `indeterminado` (um documento não comprova dois
  itens: o fiscal confirma a qual item ele pertence);
- registrado para esta operação e este item (refiscalização; vale também quando o mesmo laudo selado o
  aceitou em dois itens, como uma NF-e de dois lotes: a decisão foi do fiscal que assinou), ou não
  registrado → `ok`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from laudo import privacidade
from laudo.docs_fiscais.comum import Criterio, so_alnum, validar_chave

VERSAO_INDICE = 2  # 2: chave por operação (HMAC da ref. Bacen); registro só na selagem
DOMINIO_GTA = "indice-gta/v1"
DOMINIO_OPERACAO = "indice-operacao/v1"
CAMPO = {"gta": "documento:gta:reuso", "nfe": "documento:nfe:reuso"}
NOME = {"gta": "GTA", "nfe": "NF-e"}
# MCR 2-7-6-b e 2-7-7-d (pecuária: item 9) em fontes.REGRAS; análogo: NT-2024.003-ZF04-20
REGRA = "MCR-2-7-item6"
FERRAMENTA_TIPO = {"conciliar_nfe": "nfe", "conciliar_gta": "gta"}


def identificador_gta(uf: str | None, serie: str | None, numero: str | None) -> str | None:
    """`UF-SÉRIE-NÚMERO` normalizado (número como inteiro, sem zeros à esquerda); None se faltar parte."""
    u, s, n = so_alnum(uf), so_alnum(serie), re.sub(r"\D", "", numero or "")
    if len(u) != 2 or not s or not n:
        return None
    return f"{u}-{s}-{int(n)}"


def hash_gta(uf: str | None, serie: str | None, numero: str | None) -> str | None:
    ident = identificador_gta(uf, serie, numero)
    return privacidade.salgar(DOMINIO_GTA, ident) if ident else None


def hash_nfe(chave: str | None) -> str | None:
    """Hash da chave de acesso (mesmo domínio de `privacidade.hash_chave`); só para chave com DV válido."""
    c = privacidade.so_chave(chave)
    return privacidade.hash_chave(c) if c and validar_chave(c)[0] else None


def hash_operacao(ref: str | None) -> str | None:
    """HMAC da referência da operação (ref. Bacen): o índice não guarda o número do contrato."""
    r = (ref or "").strip()
    return privacidade.salgar(DOMINIO_OPERACAO, r) if r else None


def _curto(h: str | None) -> str:
    return f"op:{(h or '?')[:8]}"


class IndiceDocumentos:
    """JSONL append-only. A leitura é em streaming e guarda só as linhas dos hashes procurados."""

    def __init__(self, caminho: str | Path):
        self.caminho = Path(caminho)

    def _linhas(self) -> Iterable[dict[str, Any]]:
        if not self.caminho.exists():
            return
        with open(self.caminho, encoding="utf-8") as f:  # diretório ou sem permissão: OSError ao chamador
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    e = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                if isinstance(e, dict) and e.get("hash") and e.get("tipo"):
                    yield e

    def buscar(self, tipo: str, hashes: Iterable[str]) -> dict[str, list[dict[str, Any]]]:
        """Entradas por hash (só os procurados)."""
        alvo = set(hashes)
        out: dict[str, list[dict[str, Any]]] = {h: [] for h in alvo}
        for e in self._linhas():
            if e["tipo"] == tipo and e["hash"] in alvo:
                out[e["hash"]].append(e)
        return out

    def registrar_documentos(
        self,
        documentos: Iterable[tuple[str, str, str | None]],
        operacao_ref: str,
        fiscalizacao_id: str | None = None,
    ) -> int:
        """Grava `(tipo, hash, item_id)` de um laudo selado da operação. Uma linha por tipo, hash, operação e
        item (selar de novo a mesma operação não duplica). Devolve quantas linhas gravou."""
        op = hash_operacao(operacao_ref)
        if not op:
            raise ValueError("operacao_ref vazio: o índice é por operação")
        docs = list(dict.fromkeys((t, h, i) for t, h, i in documentos if t in CAMPO and h))
        if not docs:
            return 0
        ja: set[tuple[str, str, str | None]] = set()
        for t in {t for t, _, _ in docs}:
            for h, es in self.buscar(t, {h for tt, h, _ in docs if tt == t}).items():
                ja |= {(t, h, e.get("item_id")) for e in es if e.get("operacao") == op}
        novos = [d for d in docs if d not in ja]
        if not novos:
            return 0
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        agora = datetime.now(UTC).isoformat()
        with open(self.caminho, "a", encoding="utf-8") as f:
            for t, h, item_id in novos:
                linha = {"tipo": t, "hash": h, "operacao": op, "fiscalizacao": fiscalizacao_id,
                         "item_id": item_id, "versao": VERSAO_INDICE,
                         "instalacao": privacidade.id_instalacao(), "registrado_em": agora}
                f.write(json.dumps(linha, ensure_ascii=False) + "\n")
        return len(novos)


def documentos_do_resultado(ferramenta: str, data: dict[str, Any], item_id: str | None = None
                            ) -> list[tuple[str, str, str | None]]:
    """`(tipo, hash, item_id)` dos documentos de uma saída de `conciliar_nfe`/`conciliar_gta`: a do envelope
    (chave em claro) ou a guardada no estado (chave mascarada + `chave_hash`,
    `privacidade.proteger_resultado`)."""
    tipo = FERRAMENTA_TIPO.get(ferramenta)
    item = item_id or data.get("item_id")
    out: list[tuple[str, str, str | None]] = []
    if tipo == "nfe":
        for n in data.get("notas") or []:
            h = hash_nfe(n.get("chave")) or n.get("chave_hash")
            if h:
                out.append(("nfe", h, item))
    elif tipo == "gta":
        for g in data.get("gtas") or []:
            h = hash_gta(g.get("uf_emissao"), g.get("serie"), g.get("numero"))
            if h:
                out.append(("gta", h, item))
    return out


def conciliacoes_finais(checagens: Iterable[Any]) -> list[Any]:
    """Checagens de `conciliar_nfe`/`conciliar_gta` que valem no fim: sem erro e não substituídas pela
    reconciliação cumulativa (`resultado.substitui`, condutor)."""
    chs = [c for c in checagens if c.ferramenta in FERRAMENTA_TIPO and c.status != "erro"]
    substituidas: set[str] = set()
    for c in chs:
        substituidas.update((c.resultado or {}).get("substitui") or [])
        substituidas.update(getattr(c, "substitui", None) or [])
    return [c for c in chs if c.id not in substituidas]


def documentos_selaveis(fis: Any) -> list[tuple[str, str, str | None]]:
    """`(tipo, hash, item_id)` que a selagem registra (contrato `Fiscalizacao`): só das conciliações finais
    com status `ok` (todos os critérios conferem, inclusive o próprio reuso), ligadas a pelo menos uma evidência
    da fiscalização (sem fonte, sem afirmação) e de um item da operação. Fica de fora o que diverge, o que
    ficou indeterminado (documento de outro item, leitura de foto não validada) e o que foi substituído."""
    evidencias = {e.id for e in getattr(fis, "evidencias", None) or []}
    itens = {i.id for i in fis.operacao.itens}
    docs: list[tuple[str, str, str | None]] = []
    for c in conciliacoes_finais(fis.checagens):
        if c.status != "ok" or c.item_id not in itens or not any(e in evidencias for e in c.evidencias):
            continue
        docs += documentos_do_resultado(c.ferramenta, c.resultado or {}, c.item_id)
    return list(dict.fromkeys(docs))


def registrar_fiscalizacao(caminho: str | Path, fis: Any) -> int:
    """Registra no índice os documentos seláveis (`documentos_selaveis`) de uma fiscalização **selada**
    (contrato `Fiscalizacao`: `operacao.ref_bacen`, `id`, `checagens`, `evidencias`). Não confere a etapa: no
    produto, chame `laudo.agent.indice.registrar_na_selagem`; aqui é a simulação da selagem (runner, harness)."""
    docs = documentos_selaveis(fis)
    return IndiceDocumentos(caminho).registrar_documentos(docs, fis.operacao.ref_bacen, fis.id)


def conferir_reuso(
    indice: IndiceDocumentos,
    tipo: str,
    documentos: list[tuple[str, str | None]],
    operacao_ref: str,
    item_id: str | None,
) -> Criterio | None:
    """Consulta (só leitura) dos documentos de um tipo. `documentos`: `(rótulo sem PII, hash)`; o rótulo é a
    GTA `UF-SÉRIE-NÚMERO` ou a chave **mascarada** da NF-e. Devolve o critério do campo
    `documento:<tipo>:reuso` (None se nenhum documento tem identificador)."""
    validos = [(r, h) for r, h in documentos if h]
    op = hash_operacao(operacao_ref)
    if not validos or not op:
        return None
    base = {"id": f"{tipo}.reuso", "campo": CAMPO[tipo], "regra_id": REGRA}
    nome = NOME[tipo]
    achados = indice.buscar(tipo, {h for _, h in validos})
    outra, mesma, refisc = [], [], 0
    for rot, h in validos:
        es = achados.get(h) or []
        da_op = [e for e in es if e.get("operacao") == op]
        de_outra = sorted({f"{_curto(e.get('operacao'))}, fiscalização {e.get('fiscalizacao') or '?'}"
                           for e in es if e.get("operacao") != op})
        # refiscalização: o documento já comprovou ESTE item desta operação num laudo selado. Se no mesmo laudo
        # ele também comprovou outro item (uma NF-e de dois lotes), quem decidiu foi o fiscal que assinou: a
        # refiscalização não reabre isso como pendência. "Outro item" só vale para documento que nunca
        # comprovou este item.
        deste_item = any(e.get("item_id") == item_id for e in da_op)
        de_outro_item = sorted({str(e.get("item_id")) for e in da_op if e.get("item_id") != item_id})
        if de_outra:
            outra.append(f"{nome} {rot} já comprovou outra operação em laudo selado ({'; '.join(de_outra)})")
        elif deste_item:
            refisc += 1
        elif de_outro_item:
            mesma.append(f"{nome} {rot} já comprovou o item {', '.join(de_outro_item)} desta operação")
    val = {"documentos": len(validos), "analogo": "NT-2024.003-ZF04-20",
           "indice": "local, laudos selados desta instalação, HMAC com o sal da instalação"}
    if outra:
        por_que = ("análogo à rejeição 838 'Guia de Trânsito já utilizada', NT 2024.003 10ZF04-20"
                   if tipo == "gta" else "indício de duplicidade de crédito, MCR 2-7-6-b e 2-7-7-d")
        return Criterio(status="divergente", valores=val | {"outra_operacao": len(outra)},
                        motivo="; ".join(outra) + f": reuso de documento (um documento não comprova duas "
                                                  f"compras; {por_que})", **base)
    if mesma:
        return Criterio(status="indeterminado", valores=val | {"outro_item": len(mesma)},
                        motivo="; ".join(mesma) + ": um documento não comprova dois itens; confirme a qual "
                                                  "item ele pertence", **base)
    if refisc:
        return Criterio(status="ok", valores=val | {"refiscalizacao": refisc},
                        motivo=f"{nome} já comprovou este item desta operação em laudo selado (refiscalização, "
                               "não é reuso) e não consta em laudo selado de outra operação (índice local desta "
                               "instalação)", **base)
    return Criterio(status="ok", valores=val,
                    motivo=f"{nome} não consta em laudo selado de outra operação (índice local desta "
                           "instalação)", **base)
