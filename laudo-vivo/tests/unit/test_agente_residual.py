"""Residual no condutor (rodada 3): foto do DANFE com a linha de produtos ilegível → o agente pede só a quantidade
e os valores da linha → a fiscal fala → a completação valida (mesmas regras), a conciliação roda de novo e o
laudo registra a origem "lido de foto e completado pela fiscal". Sem GPU: o VLM é um leitor falso."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from laudo.agent import estado as est
from laudo.agent.condutor import Condutor, Evento, NovaEvidencia, residual_pendente
from laudo.audit import otel
from laudo.contracts import Operacao
from laudo.docs_fiscais import residual as R
from laudo.tools import carregar_todas
from laudo.tools import laudo as ferr_laudo
from laudo.tools import leitura_documentos as LD

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "eval" / "golden" / "gerador"))
import documentos_imagem as DI

CASO = REPO / "eval" / "golden" / "casos" / "GLD-0002"


def _danfe_com_linha_errada() -> dict[str, dict[str, Any]]:
    """O que o VLM "leu": tudo certo, menos o valor total da linha 1 (a conta não fecha → residual)."""
    d = DI.dados_danfe((CASO / "nfe_1.xml").read_bytes())
    it = d["itens"][0]
    num = f"{d['numero']:09d}"
    linha = (f"{it['codigo']} | {it['descricao']} | {it['ncm']} | 040 | {it['cfop']} | {it['unidade']} | "
             f"{DI.br_num(it['quantidade'], 0)} | {DI.br_num(it['valor_unitario'])} | "
             f"{DI.br_num(it['valor_total'] + 10000)}")
    return {
        "cima": {"chave_acesso": DI.fmt_chave(d["chave"]), "numero_nfe": f"{num[:3]}.{num[3:6]}.{num[6:]}",
                 "serie": f"{d['serie']:03d}", "data_emissao": d["dh_emi"].strftime("%d/%m/%Y"),
                 "emitente_nome": d["emitente"]["nome"], "emitente_cnpj_cpf": DI.fmt_doc(d["emitente"]["doc"]),
                 "emitente_municipio": d["emitente"]["mun"], "emitente_uf": d["emitente"]["uf"],
                 "destinatario_nome": d["destinatario"]["nome"],
                 "destinatario_cnpj_cpf": DI.fmt_doc(d["destinatario"]["doc"]),
                 "destinatario_uf": d["destinatario"]["uf"], "entrada_ou_saida": d["tp_nf"]},
        "baixo": {"linhas_produtos": [linha], "v_total_produtos": DI.br_num(d["v_prod"]),
                  "valor_total_da_nota": DI.br_num(d["v_nf"]), "informacoes_complementares": ""},
    }, it


@pytest.fixture()
def cenario(tmp_path):
    otel.configurar(tmp_path / "traces")
    est.ids_deterministicos("residual-condutor")
    partes, item = _danfe_com_linha_errada()

    def leitor(img, prompt, esquema, temperatura, semente):
        if "Responda o tipo" in prompt:
            return {"tipo": "danfe"}
        return dict(partes["cima" if "parte de cima" in prompt else "baixo"])

    LD.configurar_leitor(leitor)
    caso = yaml.safe_load((CASO / "caso.yaml").read_text(encoding="utf-8"))
    op = dict(caso["operacao"], tomador_ref=f"sha256:{caso['tomador']['documento_sha256']}")
    op["codigo_estabelecimento"] = caso["projeto"]["propriedade"]["codigo_estabelecimento"]
    repo = est.RepositorioFiscalizacoes(tmp_path)
    cond = Condutor(None, repo=repo, registro=dict(carregar_todas()), hoje=__import__("datetime").date(2026, 10, 8))
    fis = cond.abrir(Operacao.model_validate(op), estado_fsm="COLETA", metodo="presencial")
    bov = next(i["id"] for i in caso["operacao"]["itens"] if i["tipo"] == "bovinos")
    foto = NovaEvidencia(tipo="documento", caminho=str(CASO / "fotos" / "foto_lote_1.jpg"), item_id=bov,
                         meta={"tipo_documento": "danfe"})
    yield cond, fis, foto, item
    LD.configurar_leitor(None)
    est.ids_deterministicos(None)
    ferr_laudo.configurar(None, None)


def test_foto_do_danfe_pede_so_o_residual_e_a_fala_completa(cenario):
    cond, fis, foto, item = cenario
    r1 = cond.turno(fis.id, Evento(texto="Foto da nota impressa.", evidencia=foto))
    assert any(a.acao == "ler_documento_foto" for a in r1.acoes)
    assert r1.residual is not None and r1.residual["tipo_documento"] == "danfe"
    assert r1.residual["campos"][0]["campos"] == ["item1.quantidade", "item1.valor_unitario", "item1.valor_total"]
    assert "quantidade, o valor unitário e o valor total da linha 1" in r1.fala
    pend = residual_pendente(cond.repo.carregar(fis.id))
    assert pend is not None and pend.pedido.tentativa == 1

    # resposta errada (a conta não fecha): recusada, novo pedido (tentativa 2), nada aceito
    q, vu, vt = int(item["quantidade"]), item["valor_unitario"], item["valor_total"]
    r2 = cond.turno(fis.id, Evento(texto=f"{q} cabeças, {DI.br_num(vu)} cada, total {DI.br_num(vt + 1)}"))
    acao = next(a for a in r2.acoes if a.acao == R.FERRAMENTA)
    assert acao.origem == "residual" and "Não aceitei" in r2.fala and r2.residual["tentativa"] == 2
    assert r2.alegacoes == []  # leitura do papel não é alegação
    assert not r2.llm.get("condutor")  # turno determinístico (sem LLM)

    # resposta certa por voz (números por extenso viram algarismos): aceita e a conciliação roda de novo
    r3 = cond.turno(fis.id, Evento(texto=f"{q} cabeças, {DI.br_num(vu)} reais cada, total {DI.br_num(vt)}",
                                   origem="asr"))
    assert "Aceitei o que você leu da nota" in r3.fala and r3.residual is None
    assert any(a.acao == "conciliar_nfe" and a.origem == "residual" for a in r3.acoes)
    final = cond.repo.carregar(fis.id)
    comp = [c for c in final.checagens if c.ferramenta == R.FERRAMENTA]
    assert comp[-1].status == "ok" and comp[-1].resultado["documento"]["proveniencia"] == R.PROVENIENCIA
    assert str(acao.argumentos) == str({"evidencia_id": acao.argumentos["evidencia_id"],
                                        "campos": acao.argumentos["campos"]})  # valores fora dos argumentos
    nfe = [c for c in final.checagens if c.ferramenta == "conciliar_nfe"][-1]
    assert nfe.resultado["campos"]["item:bov1:nfe_quantidade"]["status"] == "ok"


def test_fala_sem_os_valores_pedidos_segue_o_turno_normal(cenario):
    cond, fis, foto, _ = cenario
    cond.turno(fis.id, Evento(texto="Foto da nota impressa.", evidencia=foto))
    r = cond.turno(fis.id, Evento(texto="Bom, agora vou para o curral."))
    assert not any(a.acao == R.FERRAMENTA for a in r.acoes) and r.residual is not None


def test_formulario_digitado_completa_sem_fala(cenario):
    cond, fis, foto, item = cenario
    cond.turno(fis.id, Evento(texto="", evidencia=foto))
    dig = {"item1.quantidade": str(int(item["quantidade"])), "item1.valor_unitario": DI.br_num(item["valor_unitario"]),
           "item1.valor_total": DI.br_num(item["valor_total"])}
    r = cond.turno(fis.id, Evento(texto="(formulário)", residual=dig))
    assert any(a.acao == R.FERRAMENTA and a.ok for a in r.acoes) and r.residual is None


def test_laudo_mostra_a_origem_do_valor_completado_pela_fiscal(cenario):
    cond, fis, foto, item = cenario
    cond.turno(fis.id, Evento(texto="Foto da nota impressa.", evidencia=foto))
    q, vu, vt = int(item["quantidade"]), item["valor_unitario"], item["valor_total"]
    cond.turno(fis.id, Evento(texto=f"{q}, {DI.br_num(vu)} e {DI.br_num(vt)}"))
    final = cond.repo.carregar(fis.id)
    res = cond.verificador.recalcular(final)
    final.campos = res.campos
    laudo = ferr_laudo.montar_laudo(final, res, politica=cond.politica)
    linha = next(x for x in laudo["itens"] if x["campo"].endswith(":comprovante_nfe"))
    assert "lido de foto e completado pela fiscal" in linha["proveniencia"]
    html = ferr_laudo.renderizar_html(laudo)
    assert "Origem do valor" in html and "lido de foto e completado pela fiscal" in html
