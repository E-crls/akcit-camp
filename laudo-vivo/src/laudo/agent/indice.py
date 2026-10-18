"""Índice de documentos reutilizados ligado ao produto: consulta pelo executor, registro só na selagem.

O índice (`laudo.docs_fiscais.indice`) guarda, só com HMAC do sal da instalação, a GTA (`UF-SÉRIE-NÚMERO`) e a
chave de NF-e de cada laudo **selado**, com a operação (ref. Bacen) e o item que o documento comprovou. Mora
no diretório de dados do condutor (`<dir_dados>/indices/documentos.jsonl`, ao lado de `fotos.jsonl`).

- **Consulta (toda conciliação):** `argumentos_de_consulta` dá a `conciliar_nfe`/`conciliar_gta` o caminho do
  índice e a `operacao_ref`; quem preenche é o executor (`preencher_argumentos`), nunca o LLM (os dois campos
  ficam fora do esquema que ele vê). A consulta só lê: o documento em laudo selado de outra operação diverge;
  da mesma operação e só de outro item fica indeterminado; da mesma operação e do mesmo item
  (refiscalização legítima: nova visita, laudo refeito, inclusive NF-e que o laudo selado aceitou em dois
  itens) é ok.
- **Registro (só na selagem):** `registrar_na_selagem(fis, dir_dados)` é chamado por `tools/laudo.py::selar`
  depois da assinatura humana. Confere a etapa (SELADO) e a assinatura, e registra só os documentos que
  comprovaram o item (`docs_fiscais.indice.documentos_selaveis`: conciliação final, status ok, com evidência).
  Conciliação intermediária, documento enviado por engano e fiscalização não selada nunca entram.

**Chave de contexto = operação (ref. Bacen) + item**, nunca o id da fiscalização: a refiscalização da mesma
operação abre outra fiscalização e reapresenta os mesmos documentos, e isso não é reuso (MCR 2-7-6-b e
2-7-7-d tratam de duplicidade de crédito, isto é, de outra operação). O id da fiscalização vai na linha só
como trilha.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from laudo.agent.fsm import Etapa
from laudo.audit import otel
from laudo.docs_fiscais import indice as indice_mod

ARQUIVO = Path("indices") / "documentos.jsonl"
ETAPA_SELADO = Etapa.SELADO


def caminho_indice(dir_dados: str | Path) -> Path:
    """Arquivo do índice de documentos no diretório de dados do condutor."""
    return Path(dir_dados) / ARQUIVO


def argumentos_de_consulta(fis: Any, dir_dados: str | Path | None) -> dict[str, str]:
    """`indice_documentos` + `operacao_ref` (ref. Bacen) para as conciliações; vazio sem diretório de dados
    ou sem ref. Bacen (sem a operação não há como separar refiscalização de reuso)."""
    ref = (getattr(fis.operacao, "ref_bacen", None) or "").strip()
    if dir_dados is None or not ref:
        return {}
    return {"indice_documentos": str(caminho_indice(dir_dados)), "operacao_ref": ref}


def registrar_na_selagem(fis: Any, dir_dados: str | Path) -> int:
    """Registra no índice os documentos que comprovaram os itens do laudo selado; devolve quantas linhas
    gravou (selar de novo a mesma operação não duplica).

    Não registra nada (0) se a fiscalização não está SELADA ou não tem assinatura humana. Falha de E/S no
    índice não derruba a selagem (o laudo já foi assinado): vira span com erro no trace e 0.
    """
    with otel.span("indice.registrar_na_selagem", **{"laudo.etapa": str(fis.estado_fsm)}) as s:
        if fis.estado_fsm != ETAPA_SELADO or not fis.aprovacoes:
            otel.definir(s, **{"indice.registrados": 0, "indice.motivo": "fiscalização não selada"})
            return 0
        docs = indice_mod.documentos_selaveis(fis)
        try:
            n = indice_mod.IndiceDocumentos(caminho_indice(dir_dados)).registrar_documentos(
                docs, fis.operacao.ref_bacen, fis.id
            )
        except (OSError, ValueError) as e:
            otel.marcar_erro(s, f"índice de documentos não gravado: {type(e).__name__}")
            otel.definir(s, **{"indice.registrados": 0})
            return 0
        otel.definir(s, **{"indice.documentos": len(docs), "indice.registrados": n})
        return n
