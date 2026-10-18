"""L87(a): o selo passa a cobrir o conteúdo do laudo. Numa cópia do laudo selado, alterar um valor mantinha
o selo válido (a fórmula `{hash_raiz, aprovacoes}` não olha o conteúdo); a verificação de `audit.selo`
recalcula o hash raiz do conteúdo a partir da cadeia e falha se divergir. Sem GPU (modo determinístico,
ferramentas falsas)."""

from __future__ import annotations

import copy
import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from laudo.agent import estado as est
from laudo.agent.condutor import Condutor, Evento, NovaEvidencia
from laudo.agent.ferramentas_falsas import GPS_DENTRO, criar_ferramentas_falsas, operacao_exemplo
from laudo.audit import otel, selo
from laudo.contracts import GPS
from laudo.tools import laudo as ferr_laudo

CENARIO = {
    "nfe.xml": {"conciliar_nfe": {"status": "ok", "quantidade": 40}},
    "gta.json": {"conciliar_gta": {"status": "ok", "quantidade": 40}},
    "curral.mp4": {"contar_bovinos_video": {"status": "ok", "contagem": 40, "intervalo": [39, 41]}},
}


def _ate_o_rascunho(tmp_path, hoje: date | None = None) -> tuple[Condutor, str]:
    otel.configurar(tmp_path / "traces")
    est.ids_deterministicos("teste-selo")
    for nome in [*CENARIO, "cerca.jpg"]:
        (tmp_path / nome).write_bytes(nome.encode())
    cond = Condutor(None, repo=est.RepositorioFiscalizacoes(tmp_path),
                    registro=criar_ferramentas_falsas(CENARIO), hoje=hoje)
    fis = cond.abrir(operacao_exemplo())
    cond.turno(fis.id, Evento(texto="Bom dia, vamos começar."))
    for tipo, nome, item, extra in (("nfe_xml", "nfe.xml", "bov1", {}), ("gta", "gta.json", "bov1", {}),
                                    ("video", "curral.mp4", "bov1", {}),
                                    ("foto", "cerca.jpg", "cerca1", {"gps": GPS(**GPS_DENTRO)})):
        ev = NovaEvidencia(tipo=tipo, caminho=str(tmp_path / nome), item_id=item, **extra)
        cond.turno(fis.id, Evento(evidencia=ev))
    r = cond.turno(fis.id, Evento(texto="Pode emitir o laudo."))
    assert r.etapa == "RASCUNHO", r.pendencias
    return cond, fis.id


@pytest.fixture()
def selado(tmp_path):
    cond, fis_id = _ate_o_rascunho(tmp_path)
    fis = cond.repo.carregar(fis_id)
    cond.turno(fis.id, Evento(texto="Manda para a minha assinatura."))
    rasc = cond.ultimo_laudo(fis.id)
    ok = cond.assinar(fis.id, "fiscal", "fiscal-sintetico", hash_confirmado=rasc["hash_raiz"], pin_ok=True)
    # conferido ao selar
    assert ok.etapa == "SELADO" and ok.laudo["conteudo_confere"], ok.laudo["verificacao"]
    yield cond, cond.repo.carregar(fis.id), tmp_path / "laudos" / fis.id
    est.ids_deterministicos(None)
    ferr_laudo.configurar(None, None)


def _laudo(d):
    return json.loads((d / "laudo_selado.json").read_text(encoding="utf-8"))


def test_laudo_selado_intacto_confere_com_a_cadeia_e_o_html(selado):
    _, fis, d = selado
    r = selo.verificar_em_disco(d, fis)
    assert r.valido, r.motivo
    assert r.conteudo_confere and r.cadeia_confere and r.html_confere and r.aprovacoes_conferem
    assert r.origem_conteudo == "conteudo_assinado"  # `selar` grava o bloco (L87a, onda 3)
    assert r.hash_raiz_recalculado == r.hash_raiz == fis.aprovacoes[-1].hash_assinado
    sem_estado = selo.verificar_em_disco(d)  # rascunho achado pelo nome, sem a cadeia
    assert sem_estado.valido and sem_estado.cadeia_confere is None


def test_valor_alterado_numa_copia_mantinha_o_selo_e_agora_falha(selado):
    _, fis, d = selado
    copia = copy.deepcopy(_laudo(d))
    i = next(n for n, it in enumerate(copia["itens"]) if it["valor"] is not None)
    copia["itens"][i].update(valor=25.0, valor_fmt="25", motivo="adulterado")
    assert selo.selo_v1(copia) == copia["selo"]  # o furo: a fórmula do selo não vê o conteúdo
    r = selo.verificar_laudo(copia, evidencias=fis.evidencias)
    assert not r.valido and r.conteudo_confere is False and r.selo_confere
    assert f"itens[{i}]" in r.motivo and r.hash_raiz_recalculado != r.hash_raiz
    # outro campo do conteúdo (operação, ocorrências, resumo...) também
    for campo, valor in (("resumo", {"texto": "tudo certo", "origem": "template", "motivo": ""}),
                         ("ocorrencias", [{"id": "oc_inventada", "tipo": "outro"}]),
                         ("data_referencia", "2020-01-01")):
        c2 = {**_laudo(d), campo: valor}
        assert not selo.verificar_laudo(c2, evidencias=fis.evidencias).valido, campo


def test_html_editado_ou_arquivo_do_rascunho_trocado_falham(selado, tmp_path):
    _, fis, d = selado
    copia = tmp_path / "copia"
    shutil.copytree(d, copia)
    h = copia / "laudo_selado.html"
    texto = h.read_text(encoding="utf-8")
    assert "</body>" in texto
    h.write_text(texto.replace("</body>", "<p>Quantidade: 25 cabeças</p></body>"), encoding="utf-8")
    r = selo.verificar_em_disco(copia, fis)
    assert not r.valido and r.html_confere is False and r.conteudo_confere
    # rascunho alterado no disco: o sha256 registrado na cadeia não confere e o hash raiz recalculado diverge
    ev = next(e for e in fis.evidencias if e.meta.get("laudo"))
    rasc = json.loads(Path(ev.caminho).read_text(encoding="utf-8"))
    rasc["itens"][0]["motivo"] = "adulterado"
    r = selo.verificar_laudo(_laudo(d), evidencias=fis.evidencias, rascunho=rasc,
                             rascunho_bytes=json.dumps(rasc).encode())
    assert not r.valido and r.cadeia_confere is False and r.conteudo_confere is False
    assert "rascunho assinado foi alterado" in r.motivo


def test_assinante_trocado_com_selo_recalculado_falha_contra_o_estado(selado):
    _, fis, d = selado
    copia = _laudo(d)
    copia["assinaturas"][-1].update(nome_ref="Beltrano Teste", papel="analista_if")
    copia["selo"] = selo.selo_v1(copia)  # sem segredo: qualquer um recalcula (L87 b/c)
    r = selo.verificar_laudo(copia, evidencias=fis.evidencias,
                             aprovacoes=[a.model_dump(mode="json") for a in fis.aprovacoes])
    assert not r.valido and r.aprovacoes_conferem is False and r.selo_confere


def test_sem_rascunho_nem_bloco_conteudo_assinado_nao_diz_valido(selado):
    _, _, d = selado
    sem_bloco = {k: v for k, v in _laudo(d).items() if k != "conteudo_assinado"}  # laudo selado antigo
    r = selo.verificar_laudo(sem_bloco)
    assert not r.valido and r.conteudo_confere is None and "não conferível" in r.motivo


def test_bloco_conteudo_assinado_proposto_para_selar_dispensa_o_rascunho(selado):
    """Formato proposto à frente C (tools/laudo.py::selar): o selado guarda os 4 campos da emissão."""
    _, fis, d = selado
    ev = next(e for e in fis.evidencias if e.meta.get("laudo"))
    rasc = json.loads(Path(ev.caminho).read_text(encoding="utf-8"))
    laudo = {**_laudo(d), "conteudo_assinado": {k: rasc[k] for k in selo.CAMPOS_DO_SELO}}
    r = selo.verificar_laudo(laudo)
    assert r.valido and r.origem_conteudo == "conteudo_assinado"
    laudo["operacao"] = {**laudo["operacao"], "valor_rs": 1.0}
    assert not selo.verificar_laudo(laudo).valido


def test_linha_de_comando(selado, capsys):
    _, fis, d = selado
    assert selo.main(["--dados", str(d.parents[1]), fis.id]) == 0
    assert json.loads(capsys.readouterr().out)["valido"] is True


def _assinar(cond: Condutor, fis_id: str, hash_raiz: str, pin_ok: bool = True):
    return cond.assinar(fis_id, "fiscal", "fiscal-sintetico", hash_confirmado=hash_raiz, pin_ok=pin_ok)


def test_fala_com_numero_depois_do_rascunho_a_verificacao_acusa_o_selado(tmp_path):
    """Fala depois da emissão é `declaracao` e não barra a assinatura do hash do rascunho (é o que
    `test_api_retomada` espera), mas a alegação com número muda o laudo: `selar` monta o selado de novo do
    estado e ele sai com conteúdo que o humano não assinou. A verificação ao selar acusa (aviso), dizendo o
    que diverge; a correção é `selar` copiar o rascunho assinado (frente C, tools/laudo.py)."""
    cond, fis_id = _ate_o_rascunho(tmp_path)
    try:
        r = cond.turno(fis_id, Evento(texto="Contei 41 cabeças no curral, uma a mais."))
        assert r.alegacoes and r.etapa == "RASCUNHO"
        cond.turno(fis_id, Evento(texto="Manda para a minha assinatura."))
        rasc = cond.ultimo_laudo(fis_id)
        ok = _assinar(cond, fis_id, rasc["hash_raiz"])
        assert ok.etapa == "SELADO"
        d = Path(ok.laudo["laudo_json"]).parent
        rascunho = selo.ler_laudo(d / f"rascunho_{rasc['hash_raiz'][:12]}.json")
        if _laudo(d)["alegacoes"] == rascunho["alegacoes"]:  # `selar` já copia o rascunho assinado
            assert ok.laudo["conteudo_confere"] and not ok.avisos
            return
        assert not ok.laudo["conteudo_confere"] and "alegacoes" in ok.laudo["verificacao"]
        assert any("não confere com o rascunho assinado" in a for a in ok.avisos)
        assert not selo.verificar_em_disco(d, cond.repo.carregar(fis_id)).valido
    finally:
        est.ids_deterministicos(None)
        ferr_laudo.configurar(None, None)


def test_selado_usa_a_data_de_referencia_do_rascunho_assinado(tmp_path):
    """A emissão não recebe `hoje` (usa a data da fiscalização ou a do relógio) e `selar` recebia
    `self.hoje`: com os dois diferentes (fiscalização sem data de referência), o selado saía com outra data e
    não conferia com o rascunho assinado (e a guarda da assinatura recusaria sempre). O selado usa a data do
    rascunho."""
    cond, fis_id = _ate_o_rascunho(tmp_path, hoje=date(2026, 1, 2))
    try:
        assert cond.repo.carregar(fis_id).data_referencia is None
        cond.turno(fis_id, Evento(texto="Manda para a minha assinatura."))
        rasc = cond.ultimo_laudo(fis_id)
        ok = _assinar(cond, fis_id, rasc["hash_raiz"])
        assert ok.etapa == "SELADO" and ok.laudo["conteudo_confere"], ok.laudo["verificacao"]
        d = Path(ok.laudo["laudo_json"]).parent
        rascunho = selo.ler_laudo(d / f"rascunho_{rasc['hash_raiz'][:12]}.json")
        assert _laudo(d)["data_referencia"] == rascunho["data_referencia"] != "2026-01-02"  # a do relógio
    finally:
        est.ids_deterministicos(None)
        ferr_laudo.configurar(None, None)


def _selado_sintetico(template_sha256: str) -> dict:
    """Laudo selado mínimo e coerente (hash raiz do conteúdo, assinatura, selo e bloco `conteudo_assinado`)
    que declara o template com que foi gerado (campo proposto para `montar_laudo`)."""
    conteudo = {"versao": "teste", "tipo": "rascunho", "gerado_em": "2026-10-16T10:00:00-03:00",
                "cadeia": {"raiz": "0" * 64, "n": 0, "integra": True}, "assinaturas": [],
                "itens": [{"campo": "item:bov1:quantidade", "valor": 40}],
                "template": {"sha256": template_sha256}}
    h = selo.hash_do_conteudo(conteudo)
    laudo = {**conteudo, "tipo": "selado", "gerado_em": "2026-10-16T10:05:00-03:00", "hash_raiz": h,
             "assinaturas": [{"papel": "fiscal", "nome_ref": "fiscal-sintetico", "hash_assinado": h}],
             "conteudo_assinado": {k: conteudo[k] for k in selo.CAMPOS_DO_SELO}}
    laudo["selo"] = selo.selo_v1(laudo)
    return laudo


def test_html_de_laudo_arquivado_com_template_antigo_fica_nao_conferivel_e_nao_invalido():
    """O HTML é conferido renderizando o JSON com o template de hoje: um laudo arquivado ficava "inválido" a
    cada mudança do template. Com o sha256 do template no conteúdo assinado, template diferente vira aviso
    (vale o JSON); com o mesmo template, HTML editado continua inválido."""
    def renderizar(laudo):
        return "<p>renderizado hoje</p>"

    antigo = _selado_sintetico("a" * 64)
    r = selo.verificar_laudo(antigo, html="<p>gerado com o template antigo</p>", renderizar=renderizar)
    assert r.valido and r.html_confere is None and "template do laudo mudou" in r.motivo
    atual = _selado_sintetico(selo.sha256_template_laudo())
    r = selo.verificar_laudo(atual, html="<p>editado: 25 cabeças</p>", renderizar=renderizar)
    assert not r.valido and r.html_confere is False
    assert selo.verificar_laudo(atual, html="<p>renderizado hoje</p>", renderizar=renderizar).valido
    adulterado = {**antigo, "itens": [{"campo": "item:bov1:quantidade", "valor": 25}]}
    assert not selo.verificar_laudo(adulterado, html="<p>x</p>", renderizar=renderizar).valido
