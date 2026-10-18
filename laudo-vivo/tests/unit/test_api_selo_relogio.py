"""Selo por construção (L87a) pela API e roteiro web do DEMO-0001 com integridade real e o relógio 30 dias à
frente (L99, rápido: sem GPU, sem rede, VLM pelo cache gravado).

Simulado no L99: a contagem do vídeo (ferramenta falsa) e a série NDVI (stub com 2 cenas Sentinel-2 de teste,
passo 2 do roteiro reescrito para chamá-la); integridade da foto, geofence, documentos e regras são reais.
"Relógio +30 dias" = o `recebida_em` padrão das evidências e o `hoje` do condutor; o `gerado_em` e os carimbos
seguem o relógio real.

- o laudo selado é o rascunho assinado: uma fala com número depois do rascunho não entra no selado, e a tela
  mostra a conferência do conteúdo (`estado.laudo.conteudo_confere`, item 3);
- o roteiro web inteiro sela mesmo rodando 30 dias depois das datas do caso (as evidências levam o
  `recebida_em` do caso, como a CLI: L01), e o laudo sai legível (L22, L33, L98) com a atribuição Copernicus
  (L62).
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from laudo.agent import estado as est
from laudo.agent.roteiro_demo import chamar
from laudo.api import casos as casos_mod
from laudo.api.main import criar_app
from laudo.api.servico import PIN_DEMO, Config
from laudo.contracts import Envelope, Ferramenta
from laudo.formatacao import fmt_valor, texto_sem_ids
from laudo.tools import laudo as ferr_laudo
from laudo.tools import pacote

FIS = "fis_demo_regional"
CACHE_VLM = Path(__file__).parent / "dados_agente" / "vlm_cache_demo"


@pytest.fixture(autouse=True)
def _limpar():
    yield
    est.ids_deterministicos(None)
    ferr_laudo.configurar(None, None)


def _roteiro(c: TestClient, fis: str, parar_antes: str | None = None) -> None:
    while True:
        rot = c.get(f"/api/fiscalizacoes/{fis}").json()["roteiro"]
        if rot["proximo"] > rot["total"] or rot["passos"][rot["proximo"] - 1]["titulo"] == parar_antes:
            return
        r = c.post(f"/api/fiscalizacoes/{fis}/roteiro/proximo")
        assert r.status_code == 200, r.text
        if r.json().get("acao_humana") == "assinar":
            return


def _assinar(c: TestClient, fis: str) -> dict:
    laudo = c.get(f"/api/fiscalizacoes/{fis}").json()["laudo"]
    assert laudo, "o roteiro não emitiu o rascunho (laudo ausente no estado)"
    return c.post(
        f"/api/fiscalizacoes/{fis}/assinar", json={"pin": PIN_DEMO, "hash_confirmado": laudo["hash_raiz"]}
    ).json()


def test_fmt_valor_sem_dicionario_cru():
    assert fmt_valor({"contagem": 12, "intervalo": [12, 17], "financiado": 29.0}) == "12 (12 a 17)"
    assert fmt_valor({"metodo": "autofiscalizacao_assistida"}) == "autofiscalização assistida"
    assert fmt_valor({"data_limite": "2026-11-30"}) == "até 2026-11-30"
    assert fmt_valor({"quantidade": "divergente", "gta": "verificado"}) == "—"
    assert fmt_valor(1200.0) == "1.200" and fmt_valor(None) == "—" and fmt_valor(True) == "sim"


def test_texto_sem_ids_espelha_a_tela():
    """L98 no laudo HTML: o filtro `sem_ids` do template faz o que `semIds` (apps/web/js/ui.js) faz na
    tela."""
    rot = ferr_laudo.ROTULO_FERRAMENTA
    assert texto_sem_ids("item:bov1:gta_data: divergente (GTA X emitida antes; em GO a chave é exigida)") == (
        "divergente (GTA X emitida antes; em GO a chave é exigida)"
    )
    assert texto_sem_ids("método registrado: autofiscalizacao_assistida") == (
        "método registrado: autofiscalização assistida"
    )
    assert texto_sem_ids("integridade_foto: ok; integridade_foto: ok", rot) == "Integridade da foto: ok"
    assert texto_sem_ids("quantidade divergente (item:bov1:quantidade) — checagem chk_2d88ee1829.") == (
        "quantidade divergente."
    )
    assert texto_sem_ids("a foto mostra cerca; o fiscal atestou; a foto mostra cerca") == (
        "a foto mostra cerca; o fiscal atestou"
    )
    assert texto_sem_ids(None) == "" and texto_sem_ids("divergente: quantidade, gta", rot) == (
        "divergente: quantidade, gta"
    )
    js = (Path(__file__).parents[2] / "apps" / "web" / "js" / "ui.js").read_text(encoding="utf-8")
    assert "texto_sem_ids" in js  # o espelho da tela aponta para este filtro (mudar os dois juntos)


def test_fala_com_numero_depois_do_rascunho_nao_entra_no_selado(tmp_path):
    """L87a: antes, `selar` montava o laudo de novo do estado e a alegação "41 cabeças", dita depois do
    rascunho (que não barra a assinatura), saía no selado sem ter sido assinada. Agora o selado é o rascunho
    assinado."""
    c = TestClient(criar_app(Config(dados=tmp_path / "api", asr="desligado")))
    c.post("/api/fiscalizacoes", json={"caso": "roteiro"})
    _roteiro(c, FIS, parar_antes="Assinatura humana (PIN + hash)")
    r = c.post(f"/api/fiscalizacoes/{FIS}/turno", json={"texto": "Contei 41 cabeças no curral, uma a mais."})
    assert r.json()["resposta"]["alegacoes"], r.json()["resposta"]
    ok = _assinar(c, FIS)
    assert ok["estado"]["etapa"] == "SELADO"
    sel = ok["resposta"]["laudo"]
    assert sel["conteudo_confere"] is True and sel["verificacao"] == "laudo selado confere", sel
    assert not any("não confere" in a for a in ok["resposta"]["avisos"])
    d = tmp_path / "api" / "laudos" / FIS
    selado = json.loads((d / "laudo_selado.json").read_text(encoding="utf-8"))
    rasc = json.loads(next(d.glob("rascunho_*.json")).read_text(encoding="utf-8"))
    assert selado["alegacoes"] == rasc["alegacoes"] and not any(
        a.get("valor") == 41 for a in selado["alegacoes"]
    )
    assert selado["conteudo_assinado"] == {k: rasc[k] for k in ("tipo", "gerado_em", "assinaturas", "cadeia")}
    assert selado["template"]["sha256"] and selado["hash_raiz"] == rasc["hash_raiz"]
    # a tela mostra a conferência (item 3) e a recalcula quando o arquivo muda
    info = c.get(f"/api/fiscalizacoes/{FIS}").json()["laudo"]
    assert info["conteudo_confere"] is True and info["verificacao"] == "laudo selado confere"
    selado["itens"][0]["motivo"] = "alterado depois do selo"
    (d / "laudo_selado.json").write_text(json.dumps(selado, ensure_ascii=False), encoding="utf-8")
    info = c.get(f"/api/fiscalizacoes/{FIS}").json()["laudo"]
    assert info["conteudo_confere"] is False and "diverge do assinado" in info["verificacao"]


def test_selar_recusa_rascunho_alterado(tmp_path):
    c = TestClient(criar_app(Config(dados=tmp_path / "api", asr="desligado")))
    c.post("/api/fiscalizacoes", json={"caso": "roteiro"})
    _roteiro(c, FIS, parar_antes="Assinatura humana (PIN + hash)")
    fis = est.RepositorioFiscalizacoes(tmp_path / "api").carregar(FIS)
    from laudo.contracts import AprovacaoHumana

    rasc_ev = next(e for e in reversed(fis.evidencias) if e.meta.get("laudo"))
    fis.aprovacoes.append(
        AprovacaoHumana(papel="fiscal", nome_ref="fiscal-teste", hash_assinado=rasc_ev.meta["hash_raiz"])
    )
    rasc, ev = ferr_laudo.rascunho_assinado(fis)
    assert ev.id == rasc_ev.id and rasc["hash_raiz"] == rasc_ev.meta["hash_raiz"]
    p = Path(ev.caminho)
    p.write_text(p.read_text(encoding="utf-8").replace('"rascunho"', '"rascunho" ', 1), encoding="utf-8")
    with pytest.raises(ferr_laudo.ErroSelagem, match="sha256 diverge"):
        ferr_laudo.selar(fis)
    assert not (tmp_path / "api" / "laudos" / FIS / "laudo_selado.json").exists()


def test_assinar_com_rascunho_alterado_e_recusa_legivel_e_nao_500(tmp_path):
    """Rascunho alterado no disco entre a emissão e a assinatura: a API devolve a recusa POL-03 com o motivo
    (antes: `ErroSelagem` subia como HTTP 500) e nada é gravado, nem a aprovação; com o arquivo restaurado ao
    registrado na cadeia, a mesma assinatura sela normalmente."""
    c = TestClient(criar_app(Config(dados=tmp_path / "api", asr="desligado")))  # 500 levantaria aqui
    c.post("/api/fiscalizacoes", json={"caso": "roteiro"})
    _roteiro(c, FIS, parar_antes="Assinatura humana (PIN + hash)")
    d = tmp_path / "api" / "laudos" / FIS
    p = next(d.glob("rascunho_*.json"))
    original = p.read_bytes()
    j = json.loads(original)
    j["itens"][0]["motivo"] = "alterado no disco"
    p.write_text(json.dumps(j, ensure_ascii=False, indent=1), encoding="utf-8")
    hash_raiz = c.get(f"/api/fiscalizacoes/{FIS}").json()["laudo"]["hash_raiz"]
    r = c.post(f"/api/fiscalizacoes/{FIS}/assinar", json={"pin": PIN_DEMO, "hash_confirmado": hash_raiz})
    assert r.status_code == 200, r.text
    resp = r.json()["resposta"]
    assert (
        resp["fala"].startswith("Assinatura recusada: o rascunho assinado não confere (")
        and "sha256" in resp["fala"]
    )
    assert "nova fiscalização (POL-04" in resp["fala"] and any("não selado" in a for a in resp["avisos"])
    acao = resp["acoes"][0]
    assert acao["acao"] == "assinar" and acao["permitido"] is False and acao["rule_id"] == "POL-03"
    assert r.json()["estado"]["etapa"] != "SELADO" and not (d / "laudo_selado.json").exists()
    assert not est.RepositorioFiscalizacoes(tmp_path / "api").carregar(FIS).aprovacoes
    # arquivo restaurado ao registrado na cadeia: a assinatura sela e o conteúdo confere
    p.write_bytes(original)
    ok = c.post(
        f"/api/fiscalizacoes/{FIS}/assinar", json={"pin": PIN_DEMO, "hash_confirmado": hash_raiz}
    ).json()
    assert ok["estado"]["etapa"] == "SELADO" and ok["resposta"]["laudo"]["conteudo_confere"] is True


# ---------------------------------------------------------------------------
# L99: roteiro web do DEMO-0001, integridade real, relógio 30 dias à frente
# ---------------------------------------------------------------------------


class _EntradaNdvi(BaseModel):
    poligono_wkt: str | None = None
    inicio: str | None = None
    fim: str | None = None


def _ndvi(_a: _EntradaNdvi) -> Envelope:
    datas = ("2026-08-01", "2026-09-05")
    serie = [
        {
            "data": d,
            "item_id": f"S2B_T22LFH_{d.replace('-', '')}T133546_L2A",
            "plataforma": "sentinel-2b",
            "nuvem_cena": 3.0,
            "frac_limpa": 0.98,
            "ndvi_p50": 0.4,
            "limpa": True,
        }
        for d in datas
    ]
    meta = {
        "satelite": ["sentinel-2b"],
        "sensor": "MSI (MultiSpectral Instrument)",
        "produto": "Sentinel-2 L2A, coleção sentinel-2-c1-l2a (Earth Search / Element 84, COG)",
        "bandas": {"B04": "vermelho", "B08": "infravermelho próximo"},
        "resolucao_m": 10,
        "resolucao_radiometrica_bits": 12,
        "datas": list(datas),
        "metodologia": "NDVI (teste)",
        "uso_na_fiscalizacao": "pastagem (teste)",
    }
    return Envelope.sucesso(
        "serie_ndvi",
        {"status": "ok", "serie": serie, "n_obs_limpas": 2, "n_cenas_stac": 2, "metadados_laudo": meta},
        fonte_versao="teste@1",
    )


@pytest.mark.skipif(
    casos_mod.localizar_caso("DEMO-0001") is None or not CACHE_VLM.is_dir(),
    reason="DEMO-0001 ou o cache do VLM ausentes",
)
def test_roteiro_web_sela_com_integridade_real_e_relogio_30_dias_a_frente(tmp_path, monkeypatch):
    monkeypatch.setenv("LAUDO_VLM_CACHE", str(CACHE_VLM))
    monkeypatch.setenv("LAUDO_VLM_SO_CACHE", "1")
    adiantado = timedelta(days=30)
    original = est.adicionar_evidencia

    def com_relogio(fis, tipo, **kw):  # o "agora" do recebimento é 30 dias depois do relógio da máquina
        if kw.get("recebida_em") is None:
            kw["recebida_em"] = datetime.now().astimezone() + adiantado
        return original(fis, tipo, **kw)

    monkeypatch.setattr(est, "adicionar_evidencia", com_relogio)
    # o "hoje" do condutor (contexto do LLM e argumentos das ferramentas) também anda 30 dias. Não andam: o
    # `gerado_em` e os carimbos (relógio real) e a data de referência do laudo, que vem do caso (2026-10-08)
    hoje = (datetime.now().astimezone() + adiantado).date()
    app = criar_app(
        Config(dados=tmp_path / "api", caso="DEMO-0001", asr="desligado", ferramentas="mistas", hoje=hoje)
    )
    srv = app.state.servico
    assert srv.falsas == ["contar_bovinos_video"]  # integridade, geofence, documentos e regras são reais
    srv.registro["serie_ndvi"] = Ferramenta(
        nome="serie_ndvi", descricao="NDVI de teste", entrada=_EntradaNdvi, funcao=_ndvi
    )
    caso = srv.caso("DEMO-0001")
    caso.roteiro[1].passos_llm = [chamar("serie_ndvi", args={"poligono_wkt": caso.operacao.glebas_wkt[0]})]
    c = TestClient(app)
    fis = c.post("/api/fiscalizacoes", json={"caso": "DEMO-0001"}).json()["id"]
    _roteiro(c, fis)
    ok = _assinar(c, fis)
    assert ok["estado"]["etapa"] == "SELADO", ok["resposta"]
    assert ok["resposta"]["laudo"]["conteudo_confere"] is True, ok["resposta"]["laudo"]
    f = est.RepositorioFiscalizacoes(tmp_path / "api").carregar(fis)
    integ = [k for k in f.checagens if k.ferramenta == "integridade_foto"]
    assert integ and all(not (k.resultado or {}).get("fake") for k in integ)
    assert "FOTO_ANTIGA" not in json.dumps([k.resultado for k in integ], ensure_ascii=False)
    fotos = {
        e.id: e
        for e in f.evidencias
        if e.tipo in ("foto", "video", "nfe_xml", "gta", "documento") and not e.meta.get("laudo")
    }
    assert all(e.recebida_em.date().isoformat() == "2026-10-08" for e in fotos.values()), {
        e.tipo: e.recebida_em.isoformat() for e in fotos.values()
    }
    laudo = c.get(f"/api/fiscalizacoes/{fis}/laudo").json()
    # L22: nenhum dicionário cru no valor apurado; L33: os contadores do laudo contam aspectos, como o resumo
    assert not any("{" in it["valor_fmt"] for it in laudo["itens"]), [
        it["valor_fmt"] for it in laudo["itens"]
    ]
    aspectos = [it for it in laudo["itens"] if not it["agregado"]]
    assert any(it["agregado"] and it["aspecto"] == "Resultado do item" for it in laudo["itens"])
    n_ver = sum(1 for it in aspectos if it["status"] == "verificado")
    assert f"{n_ver} aspecto(s) verificado(s)" in laudo["resumo"]["texto"]
    est_tela = c.get(f"/api/fiscalizacoes/{fis}").json()
    assert est_tela["contagem"]["verificado"] == n_ver and est_tela["laudo"]["conteudo_confere"] is True
    # L98: método e justificativa legíveis, sem ids de item ou de regra
    assert (
        laudo["metodo"]["rotulo"] == "autofiscalização assistida"
        and "autofiscalizacao_assistida" not in laudo["resumo"]["texto"]
    )
    assert not re.search(r"\b(?:bov1|cerca1)\b|MCR-2-7-item", laudo["metodo"]["justificativa"] or "")
    # L62: atribuição Copernicus no laudo e no pacote (houve cena Sentinel-2)
    assert laudo["atribuicoes"] == ["Contém dados Copernicus Sentinel modificados (2026)"]
    html = c.get(f"/api/fiscalizacoes/{fis}/laudo.html").text
    assert "Contém dados Copernicus Sentinel modificados (2026)" in html
    # L98 no laudo HTML para imprimir (vai no pacote): o texto visível não tem id de item, de checagem nem o
    # id do método; o id continua no title da linha
    visivel = re.sub(r"<[^>]+>", " ", re.sub(r"<(style|title)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL))
    assert not re.search(r"\bitem:[\w:-]+|autofiscalizacao_assistida|\bintegridade_foto:", visivel), [
        m.group(0)
        for m in re.finditer(
            r".{40}(?:item:[\w:-]+|autofiscalizacao_assistida|integridade_foto:).{40}", visivel
        )
    ]
    assert 'title="item:bov1:gta"' in html and "método registrado: autofiscalização assistida" in html
    assert ">divergente (GTA " in html and "Integridade da foto: ok; Integridade da foto: ok" not in html
    r = c.post(f"/api/fiscalizacoes/{fis}/pacote")
    assert r.status_code == 200 and r.json()["faltas"] == [], r.json().get("faltas")
    zp = next((tmp_path / "api" / "laudos" / fis / "pacote").glob("*.zip"))
    assert pacote.validar_pacote(zp) == []
    import zipfile

    with zipfile.ZipFile(zp) as z:
        cenas = json.loads(z.read(pacote.ARQ["cenas"]))
        leia = z.read(pacote.ARQ["leia_me"]).decode("utf-8")
        rv = json.loads(z.read(pacote.ARQ["reversao"]))
        pac_html = z.read(pacote.ARQ["indice_html"]).decode("utf-8")
    assert cenas["atribuicoes"] == laudo["atribuicoes"] and "Copernicus" in leia
    # item 2 + J2: a reversão cita a IN BCB 758 conferida (nota do Campo 60-B), com data do acesso, não da IN
    if pacote.in758_literal():
        assert rv["citacao_conferida"] is True and "A reversão da desclassificação" in rv["citacao_literal"]
        assert rv["fonte_literal"]["acesso"] == "2026-10-16" and "acesso em 16/10/2026" in rv["aviso"]
        assert "Campo 60-B, Nota" in pac_html and "ainda não está em docs/normas" not in pac_html
    assert os.environ.get("LAUDO_VLM_SO_CACHE") == "1"
