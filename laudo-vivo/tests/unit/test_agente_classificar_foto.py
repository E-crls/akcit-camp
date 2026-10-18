"""classificar_foto no fluxo (rodada 3): na foto da cerca/curral, o plano roda o VLM (autoconsistência, abstenção)
para conferir se a foto mostra a estrutura do item (MCR-2-7-item16-benfeitorias-conclusao). É ferramenta do plano,
não oferecida ao LLM; roda uma vez por foto; o resultado vai para o campo de conclusão da obra no laudo."""

from __future__ import annotations

import json

import pytest

from laudo.agent import estado as est
from laudo.agent.condutor import Condutor, Evento, NovaEvidencia
from laudo.agent.ferramentas_falsas import GPS_DENTRO, criar_ferramentas_falsas, operacao_exemplo
from laudo.audit import otel
from laudo.contracts import GPS, REGISTRO
from laudo.llm.provider import ProvedorRoteirizado, RespostaLLM
from laudo.tools import carregar_todas
from laudo.tools import laudo as ferr_laudo

CENARIO = {"cerca.jpg": {"integridade_foto": {"status": "ok"}}, "cerca2.jpg": {"integridade_foto": {"status": "ok"}}}


class LLM:
    def __init__(self):
        self.ferramentas: list[set[str]] = []

    def __call__(self, mensagens, ferramentas, formato):
        if formato and "alegacoes" in json.dumps(formato):
            return RespostaLLM(conteudo='{"alegacoes": []}')
        self.ferramentas.append({f["function"]["name"] for f in ferramentas or []})
        return RespostaLLM(conteudo="Agora envie o vídeo do lote.")


@pytest.fixture()
def amb(tmp_path, monkeypatch):
    otel.configurar(tmp_path / "traces")
    est.ids_deterministicos("classificar-foto")
    for nome in CENARIO:
        (tmp_path / nome).write_bytes(nome.encode())
    votos: list[str] = []

    def falso(caminho, classes, k=3, modelo="", descarregar=False, **kw):
        v = votos.pop(0) if votos else "outro"
        return {"classe": None if v == "outro" else v, "classe_majoritaria": v, "votos": {v: 2},
                "concordancia": 1.0, "k": 2, "abstencao": v == "outro", "status": "ok" if v != "outro" else
                "indeterminado", "motivo": "", "justificativas": []}

    from laudo.vision import vlm

    monkeypatch.setattr(vlm, "classificar", falso)
    yield tmp_path, votos
    est.ids_deterministicos(None)
    ferr_laudo.configurar(None, None)


def _cond(tmp_path, llm):
    carregar_todas()
    reg = criar_ferramentas_falsas(CENARIO) | {n: REGISTRO[n] for n in ("classificar_foto", "avaliar_regras")}
    return Condutor(ProvedorRoteirizado(llm), repo=est.RepositorioFiscalizacoes(tmp_path), registro=reg)


def _foto(tmp_path, nome="cerca.jpg"):
    return NovaEvidencia(tipo="foto", caminho=str(tmp_path / nome), item_id="cerca1", gps=GPS(**GPS_DENTRO))


def test_foto_da_cerca_passa_pelo_vlm_no_plano_e_vai_para_a_conclusao(amb):
    tmp_path, votos = amb
    votos.append("cerca")
    llm = LLM()
    cond = _cond(tmp_path, llm)
    fis = cond.abrir(operacao_exemplo(), estado_fsm="COLETA", metodo="presencial")
    r = cond.turno(fis.id, Evento(texto="Foto da cerca nova.", evidencia=_foto(tmp_path)))
    nomes = [(a.acao, a.origem) for a in r.acoes]
    assert ("classificar_foto", "fallback") in nomes
    assert nomes.index(("classificar_foto", "fallback")) > nomes.index(("geofence", "fallback"))
    assert all("classificar_foto" not in f for f in llm.ferramentas)  # ferramenta do plano, não do LLM
    final = cond.repo.carregar(fis.id)
    concl = final.campos["item:cerca1:conclusao"]
    assert concl.status == "verificado" and "VLM" in concl.motivo
    assert "O VLM confere que a foto mostra a cerca" in r.fala


def test_vlm_inconclusivo_nao_entra_em_laco_e_a_declaracao_resolve(amb):
    tmp_path, votos = amb
    votos += ["bovinos", "outro"]
    cond = _cond(tmp_path, LLM())
    fis = cond.abrir(operacao_exemplo(), estado_fsm="COLETA", metodo="presencial")
    cond.turno(fis.id, Evento(evidencia=_foto(tmp_path)))
    r = cond.turno(fis.id, Evento(texto="Outra foto.", evidencia=_foto(tmp_path, "cerca2.jpg")))
    final = cond.repo.carregar(fis.id)
    assert sum(1 for c in final.checagens if c.ferramenta == "classificar_foto") == 2  # uma por foto, nunca mais
    assert final.campos["item:cerca1:conclusao"].status == "abstencao"  # 2 inconclusivas: decisão humana
    assert "O VLM não confirmou a cerca" in r.fala
    r = cond.turno(fis.id, Evento(texto="A cerca está concluída, com mourões e cinco fios."))
    assert cond.repo.carregar(fis.id).campos["item:cerca1:conclusao"].status == "verificado"


def test_sem_modelo_o_plano_nao_chama_o_vlm(amb):
    tmp_path, _ = amb
    carregar_todas()
    reg = criar_ferramentas_falsas(CENARIO) | {n: REGISTRO[n] for n in ("classificar_foto", "avaliar_regras")}
    cond = Condutor(None, repo=est.RepositorioFiscalizacoes(tmp_path), registro=reg)
    fis = cond.abrir(operacao_exemplo(), estado_fsm="COLETA", metodo="presencial")
    r = cond.turno(fis.id, Evento(evidencia=_foto(tmp_path)))
    assert not any(a.acao == "classificar_foto" for a in r.acoes)
