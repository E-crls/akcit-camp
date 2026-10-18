"""Replay da demo REAL (DEMO-0001: operação fictícia derivada do Sicor + ferramentas reais), sem GPU.

A fixture `dados_agente/replay_demo_real_qwen35_4b.jsonl` (roteiro padrão de 19 passos, com a foto do DANFE e o
residual lido do papel) foi gravada com o qwen3.5:4b em 09/10/2026 (rodada 4) por
`scripts/py.sh scripts/demo_cli.py --ferramentas reais --llm ollama --perfil campo --gravar <arq> --fixture <fixture>`;
`replay_demo_real_sem_danfe_qwen35_4b.jsonl` é o caminho só com o XML (`--sem-danfe`, 17 passos, gravado em 08/10).
O sal da instalação dos testes é novo a cada execução (tests/conftest.py): a gravação não pode depender dele.
As ferramentas rodam de verdade (contagem YOLOX em CPU, ~10 s; NF-e/GTA; integridade; geofence; NDVI com cache
em disco). Lento: roda com `-m lento` ou LAUDO_LENTO=1; precisa do modelo `yolox_m`, do vídeo semissintético
`dados_locais/videos/sinteticos/s03_fila_colada.mp4` e do cache do NDVI (a 1ª execução baixa ~40 MB).

**Pendente de regravação na r4 (16/10/2026, onda 3).** As descrições de `conciliar_nfe` e `conciliar_gta` para o
LLM mudaram (grupo ZF e reuso; `tools/documentos.py`), e o hash do esquema entra na chave do replay: até a
regravação, as duas fixtures reais dão 12 e 10 substituições (medido em 16/10, com o resto do roteiro igual).
Antes dessa mudança, com o índice de documentos já ligado no executor, as substituições eram 0.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from laudo.agent import estado as est
from laudo.agent import roteiro_demo as demo
from laudo.agent.condutor import Condutor
from laudo.audit import otel
from laudo.llm.provider import ReplayProvider
from laudo.tools import carregar_todas
from laudo.tools import laudo as ferr_laudo
from laudo.vision.modelos import MODELOS

pytestmark = pytest.mark.lento

FIXTURE = Path(__file__).parent / "dados_agente" / "replay_demo_real_qwen35_4b.jsonl"
FIXTURE_SEM_DANFE = Path(__file__).parent / "dados_agente" / "replay_demo_real_sem_danfe_qwen35_4b.jsonl"
CACHE_VLM = Path(__file__).parent / "dados_agente" / "vlm_cache_demo"


@pytest.fixture(autouse=True)
def _so_quando_pedido(request):
    if "lento" not in (request.config.getoption("markexpr") or "") and not os.environ.get("LAUDO_LENTO"):
        pytest.skip("teste lento: rode com -m lento ou LAUDO_LENTO=1")


def _rodar(tmp_path, monkeypatch, fixture: Path, com_danfe: bool):
    caso = demo.carregar_caso_real()
    faltam = [n for n, ev in caso.evidencias.items() if ev.caminho and not Path(ev.caminho).is_file()]
    if faltam or not MODELOS["yolox_m"].caminho.is_file():
        pytest.skip(f"dados locais ausentes: {faltam or 'modelo yolox_m'}")
    # respostas do VLM (classificação da foto da cerca, leitura do DANFE) vêm do cache gravado: sem GPU
    monkeypatch.setenv("LAUDO_VLM_CACHE", str(CACHE_VLM))
    monkeypatch.setenv("LAUDO_VLM_SO_CACHE", "1")
    otel.configurar(tmp_path / "traces")
    est.ids_deterministicos(demo.SEMENTE_IDS_REAL)
    prov = ReplayProvider(fixture, sequencial_se_ausente=True)
    cond = Condutor(prov, repo=est.RepositorioFiscalizacoes(tmp_path), registro=dict(carregar_todas()),
                    hoje=caso.data_referencia)
    return prov, cond, demo.executar_real(cond, caso, com_danfe=com_danfe)


@pytest.fixture()
def resultado(tmp_path, monkeypatch):
    yield _rodar(tmp_path, monkeypatch, FIXTURE, com_danfe=True)
    est.ids_deterministicos(None)
    ferr_laudo.configurar(None, None)


def test_roteiro_padrao_tem_a_foto_do_danfe_e_o_residual():
    passos = demo.passos_do_caso(demo.carregar_caso_real())
    titulos = [p["titulo"] for p in passos]
    assert len(passos) == 19
    i = titulos.index("Foto da nota impressa (DANFE)")
    assert titulos[i + 1].startswith("Residual") and titulos[i + 2] == "NF-e da compra"
    assert len(demo.passos_do_caso(demo.carregar_caso_real(), com_danfe=False)) == 17


def test_replay_real_foto_do_danfe_residual_e_xml(resultado):
    """Caminho padrão (rodada 4): foto da nota impressa → leitura por VLM (cache) validada pelas regras → o agente
    pede só o que não validou → a fiscal lê no papel → o DV e as somas conferem → conciliação; depois o XML
    chega e confere com o papel (a foto não prova assinatura nem protocolo)."""
    from laudo import privacidade
    from laudo.docs_fiscais.residual import FERRAMENTA, PROVENIENCIA

    prov, cond, passos = resultado
    assert prov.substituicoes == 0, "a gravação não casa mais com as requisições: regrave a fixture"
    por_titulo = {p.titulo.split(" [")[0]: p.resposta for p in passos}
    foto = por_titulo["Foto da nota impressa (DANFE)"]
    assert any(a.acao == "ler_documento_foto" for a in foto.acoes) and foto.residual
    resid = por_titulo["Residual: a fiscal lê no papel só o que faltou"]
    comp = next(a for a in resid.acoes if a.acao == FERRAMENTA)
    assert comp.ok and resid.residual is None
    final = cond.repo.carregar(demo.FIS_ID_REAL)
    chk = next(c for c in final.checagens if c.id == comp.checagem_id)
    assert chk.status == "ok" and chk.resultado["proveniencia"] == PROVENIENCIA
    # no estado, a chave de acesso só mascarada (LGPD); o papel confere com o XML pela chave do cofre
    mascara = chk.resultado["documento"]["chave"]
    assert "…" in mascara and len(mascara) == 15 and chk.resultado["documento"]["chave_hash"]
    assert chk.resultado["documento"]["chave_hash"] == privacidade.hash_chave(
        privacidade.restaurar_resultado(chk.resultado, final.id, cond.cofre)["documento"]["chave"])
    nfe = [c for c in final.checagens if c.ferramenta == "conciliar_nfe"][-1]
    assert nfe.status == "ok" and nfe.resultado["danfe_fotos"] == {"novas": 0, "conferidas_com_xml": 1}
    assert final.campos["item:bov1:comprovante_nfe"].status == "verificado"


def test_replay_real_sem_danfe_continua_valido(tmp_path, monkeypatch):
    """`--sem-danfe` (Ollama/VLM fora do ar): o caminho só com o XML continua selando, com a gravação de 08/10."""
    prov, cond, _ = _rodar(tmp_path, monkeypatch, FIXTURE_SEM_DANFE, com_danfe=False)
    try:
        assert prov.substituicoes == 0
        assert cond.repo.carregar(demo.FIS_ID_REAL).estado_fsm == "SELADO"
    finally:
        est.ids_deterministicos(None)
        ferr_laudo.configurar(None, None)


def test_replay_real_reproduz_a_historia_do_pitch(resultado):
    prov, cond, passos = resultado
    assert prov.substituicoes == 0, "a gravação não casa mais com as requisições: regrave a fixture"
    final = cond.repo.carregar(demo.FIS_ID_REAL)
    por_titulo = {p.titulo.split(" [")[0]: p.resposta for p in passos}
    assert final.estado_fsm == "SELADO"
    assert sorted(o.tipo for o in final.ocorrencias) == ["injecao", "pressao"]
    c = final.campos
    # contagem real do vídeo (12 [12-17]) contra 29 financiadas: divergente, com justificativa do fiscal
    assert c["item:bov1:quantidade"].status == "divergente" and c["item:bov1:quantidade"].justificativa_humana
    assert c["item:bov1:quantidade"].valor["intervalo"] == [12, 17]
    assert c["item:bov1:comprovante_nfe"].status == "verificado"
    assert c["item:bov1:gta"].status == "divergente" and c["item:bov1:gta"].justificativa_humana
    for campo in ("integridade_foto", "localizacao", "conclusao", "prazo_cronograma"):
        assert c[f"item:cerca1:{campo}"].status == "verificado", campo
    for campo in ("metodo", "independencia_fiscal", "metadados_sensoriamento"):
        assert c[f"laudo:{campo}"].status == "verificado", campo
    # a foto a ~650 m da gleba deixou a localização pendente e o 1º pedido de laudo foi bloqueado
    bloqueio = next(a for a in por_titulo["Pedido de laudo (bloqueado)"].acoes if a.acao == "emitir_rascunho")
    assert not bloqueio.ok and "BLOQUEADO_POLITICA" in bloqueio.resultado
    assert por_titulo["Pressão"].fala_origem == "guarda"
    assert por_titulo["Pedido para o agente assinar"].fala_origem == "guarda"
    assert por_titulo["Assinatura humana (PIN + hash)"].laudo["selo"]
    assert por_titulo["Tentativa de alterar laudo selado"].acoes[0].rule_id == "POL-04"
    # cada item do laudo aponta para a prova (evidência e checagem), inclusive os quadros-chave do vídeo
    assert any(e.tipo == "quadro_chave" and e.derivada_de for e in final.evidencias)
    for nome in ("item:bov1:quantidade", "item:bov1:gta", "item:cerca1:localizacao"):
        assert c[nome].evidencias and c[nome].checagens, nome
