"""L39: Ollama travado não segura o palco. TIMEOUT não é repetido, o turno tem orçamento de LLM (perfil de
palco) e o disjuntor deixa o LLM de fora nos turnos seguintes; relógio virtual, sem GPU e sem esperar de
verdade."""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from laudo.agent import estado as est
from laudo.agent.condutor import Condutor, Evento, NovaEvidencia
from laudo.agent.ferramentas_falsas import criar_ferramentas_falsas, operacao_exemplo
from laudo.audit import otel
from laudo.llm.provider import ErroLLM, OllamaProvider, ProvedorRoteirizado, RespostaLLM
from laudo.tools import laudo as ferr_laudo

CENARIO = {"curral.mp4": {"contar_bovinos_video": {"status": "ok", "contagem": 32, "intervalo": [31, 33]}}}


class OllamaTravado:
    """Aceita a conexão e não responde: cada POST consome (no relógio virtual) o timeout de leitura pedido."""

    def __init__(self):
        self.t = 0.0
        self.posts = 0
        self.timeouts: list[float] = []
        self.responde = False

    def relogio(self) -> float:
        return self.t

    def dormir(self, s: float) -> None:
        self.t += s

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if not req.url.path.endswith("/api/chat"):
            return httpx.Response(200, json={"version": "x"})
        self.posts += 1
        lido = req.extensions["timeout"]["read"]
        self.timeouts.append(lido)
        if self.responde:
            self.t += 0.7
            return httpx.Response(200, json={"model": "qwen3.5:4b", "done": True,
                                             "message": {"role": "assistant", "content": "Certo, seguimos."}})
        self.t += lido
        raise httpx.ReadTimeout("sem resposta", request=req)


@pytest.fixture()
def amb(tmp_path, monkeypatch):
    monkeypatch.delenv("LAUDO_ORCAMENTO_TURNO_S", raising=False)
    otel.configurar(tmp_path / "traces")
    est.ids_deterministicos("teste-l39")
    (tmp_path / "curral.mp4").write_bytes(b"video sintetico")
    yield tmp_path
    est.ids_deterministicos(None)
    ferr_laudo.configurar(None, None)


def _cond(amb, trav: OllamaTravado, perfil: str = "campo") -> Condutor:
    prov = OllamaProvider(modelo="qwen3.5:4b", perfil=perfil, hoje=date(2026, 10, 16), dormir=trav.dormir,
                          relogio=trav.relogio, cliente=httpx.Client(transport=httpx.MockTransport(trav)))
    return Condutor(prov, repo=est.RepositorioFiscalizacoes(amb), registro=criar_ferramentas_falsas(CENARIO),
                    relogio=trav.relogio, hoje=date(2026, 10, 16))


def _turno(cond, trav, fis_id, evento):
    t0, p0 = trav.t, trav.posts
    r = cond.turno(fis_id, evento)
    return r, trav.posts - p0, trav.t - t0


def test_ollama_travado_custa_no_maximo_um_orcamento_e_o_disjuntor_segura_os_turnos_seguintes(amb):
    trav = OllamaTravado()
    cond = _cond(amb, trav)
    fis = cond.abrir(operacao_exemplo())

    # 1º turno: uma chamada só, cortada no orçamento (25 s), sem retentativa; o plano mínimo segue
    r, posts, gasto = _turno(cond, trav, fis.id, Evento(texto="Bom dia, vamos começar."))
    assert posts == 1 and trav.timeouts == [25.0] and gasto <= 30
    assert r.etapa == "COLETA"
    assert any(a.acao == "planejar_metodo" and a.origem == "fallback" for a in r.acoes)
    assert any("LLM indisponível (TIMEOUT)" in x for x in r.avisos) and r.fala_origem == "template"

    # 2º e 3º turnos (dentro dos 60 s do disjuntor): nenhuma chamada, nenhum segundo de espera
    r, posts, gasto = _turno(cond, trav, fis.id, Evento(texto="Contei 40 bois no curral, todos com brinco."))
    assert posts == 0 and gasto == 0 and r.alegacoes and r.alegacoes[0]["origem_extracao"] == "regex"
    assert r.llm["disjuntor"]["aberto"] and r.llm["alegacoes"]["pulado"] == "disjuntor"
    video = NovaEvidencia(tipo="video", caminho=str(amb / "curral.mp4"), item_id="bov1")
    r, posts, gasto = _turno(cond, trav, fis.id, Evento(evidencia=video))
    assert posts == 0 and gasto == 0
    assert any(a.acao == "contar_bovinos_video" and a.origem == "fallback" and a.ok for a in r.acoes)
    assert r.fala.startswith("Contagem do vídeo: 32 animais")
    assert trav.t <= 30  # antes da L39: 6 a 12 min de palco parado (120 s x 3 tentativas x 2 chamadas)

    # passou o tempo do disjuntor: meio-aberto, uma tentativa; travado de novo, reabre
    trav.t += 61
    r, posts, gasto = _turno(cond, trav, fis.id, Evento(texto="E agora, o que falta?"))
    assert posts == 1 and gasto <= 25
    r, posts, _ = _turno(cond, trav, fis.id, Evento(texto="Vou buscar a nota."))
    assert posts == 0

    # o Ollama voltou: depois do disjuntor, o LLM conduz de novo e o disjuntor fecha
    trav.responde = True
    trav.t += 70
    r, posts, _ = _turno(cond, trav, fis.id, Evento(texto="Voltei, vamos seguir."))
    assert posts >= 1 and r.fala_origem == "llm" and "disjuntor" not in r.llm
    r, posts, _ = _turno(cond, trav, fis.id, Evento(texto="Pode seguir."))
    assert posts >= 1


def test_escritorio_sem_orcamento_nem_disjuntor_mas_sem_retentativa_de_timeout(amb):
    """Avaliação (perfil escritório): o timeout configurado vale e não há disjuntor entre turnos; o TIMEOUT
    continua sem retentativa, e uma falha nas alegações não faz a condução esperar de novo no mesmo turno."""
    trav = OllamaTravado()
    cond = _cond(amb, trav, perfil="escritorio")
    assert cond.espera_disjuntor_s is None
    fis = cond.abrir(operacao_exemplo(), estado_fsm="COLETA", metodo="presencial")
    r, posts, gasto = _turno(cond, trav, fis.id, Evento(texto="Contei 40 bois no curral."))
    assert posts == 1 and gasto == 120.0  # só as alegações; a condução já sabe que o LLM não responde
    assert r.alegacoes and any("nas alegações" in x for x in r.avisos)
    r, posts, _ = _turno(cond, trav, fis.id, Evento(texto="E a cerca?"))
    assert posts == 1  # sem disjuntor entre turnos


def test_erro_de_formato_nao_abre_o_disjuntor(amb):
    chamadas = {"n": 0}

    def resposta(mensagens, ferramentas, formato):
        chamadas["n"] += 1
        if formato:
            return ErroLLM("FORMATO", "json inválido")
        return RespostaLLM(conteudo="Seguimos com a coleta.")

    cond = Condutor(ProvedorRoteirizado(resposta), repo=est.RepositorioFiscalizacoes(amb),
                    registro=criar_ferramentas_falsas(CENARIO), espera_disjuntor_s=60.0)
    fis = cond.abrir(operacao_exemplo(), estado_fsm="COLETA", metodo="presencial")
    r = cond.turno(fis.id, Evento(texto="Contei 40 bois no curral."))
    assert chamadas["n"] >= 2 and r.fala_origem == "llm" and cond._disjuntor_ate is None
