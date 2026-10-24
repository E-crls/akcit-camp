"""Demo pública (`LAUDO_DEMO_PUBLICA=1`): cada visitante ganha a sua cópia da fiscalização de demonstração.

Ligada pela variável de ambiente (desligada por padrão; sem ela nada deste módulo entra em uso). O QR code do
slide leva ao app, que abre direto no caso `DEMO-0001`; quem lê o QR usa sozinho.

**Isolamento.** O visitante é um cookie aleatório (`lv_sessao`, HttpOnly, SameSite=Lax). A cópia dele é um
`ServicoPublico` com pasta própria no disco temporário da instância (`LAUDO_DEMO_DIR`, padrão
`<tmp>/laudo-demo-publica/<hash do cookie>`): estado, conversa, traces, laudos, evidências e índices. O id da
fiscalização continua o do caso (`fis_demo_0001`) em todas as cópias: ele entra no estado e o replay casa pela
chave da requisição, que depende do histórico e dos ids. O contador de ids reprodutíveis, a pasta dos traces e o
contexto da ferramenta de laudo, que no uso normal são do processo, ficam por cópia (`laudo.isolamento`). Assim 20
pessoas clicando ao mesmo tempo não se atrapalham, e cada uma roda em paralelo com as outras.

**Gravação e texto livre.** O LLM é `publico` (`servico.Config.llm`): o passo do roteiro sai da gravação, sem
custo; o que não está nela (texto livre, voz) vai ao LLM ao vivo da cadeia e, sem ele, ao plano mínimo e à fala
por template, sem erro. Para o passo seguinte continuar casando com a gravação depois de uma mensagem livre:
- a mensagem livre usa outro espaço de ids (`ids_livres`), e os ids do roteiro seguem a sequência gravada;
- o turno livre fica marcado na conversa (`livre: true`) e sai do histórico que o passo do roteiro manda ao LLM.
O texto (ou a fala transcrita) igual à fala do próximo passo, e o arquivo pronto do próximo passo, viram o passo.

**Limites (custo e abuso, por variável de ambiente; `Limites.do_ambiente`).** Cópias vivas (300), validade da
cópia parada (2 h), turnos livres (40), falas (25) e arquivos (12) por visitante, tamanho e tipo do arquivo (só
foto JPEG/PNG/WebP, vídeo MP4/MOV/WebM de até 20 s e XML da NF-e), duração da fala e total enviado. Estourou: 429
(ou 413/415 para tamanho e tipo) com mensagem para a tela e o evento `recusa_limite` (`api.eventos`).

**Pronto no build.** `python -m laudo.api.publica --preparar` roda o roteiro inteiro numa cópia, confere SELADO e 0
requisição fora da gravação e guarda o resultado da contagem do vídeo do caso (`LAUDO_DEMO_CACHE_CONTAGEM`): na
demo, o YOLOX não roda de novo para o vídeo pronto do caso (só para vídeo enviado pelo visitante).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from laudo import isolamento
from laudo.agent import estado as est
from laudo.api import eventos
from laudo.api.servico import REPO, Config, ErroServico, Servico, fala_corresponde
from laudo.contracts import Envelope, Ferramenta, hash_entrada, sha256_arquivo

log = logging.getLogger(__name__)

ENV = eventos.ENV_DEMO_PUBLICA
COOKIE = "lv_sessao"
_TOKEN_OK = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
MIB = 1024 * 1024
DIR_CACHE_CONTAGEM = Path(os.environ.get("LAUDO_DEMO_CACHE_CONTAGEM") or REPO / "dados_locais" / "cache_contagem")


def ligada() -> bool:
    return eventos.ligado()


def novo_token() -> str:
    return secrets.token_urlsafe(24)


def token_valido(token: str | None) -> bool:
    return bool(token) and bool(_TOKEN_OK.match(token or ""))


# ---------------------------------------------------------------------------
# Limites
# ---------------------------------------------------------------------------


def _num(env: dict[str, str] | os._Environ, nome: str, padrao: float) -> float:
    bruto = (env.get(nome) or "").strip().replace(",", ".")
    try:
        return float(bruto) if bruto else padrao
    except ValueError:
        log.warning("%s inválido (%r): uso %s", nome, bruto, padrao)
        return padrao


@dataclass
class Limites:
    max_sessoes: int = 300  # cópias vivas por instância
    ttl_s: float = 2 * 3600  # cópia parada há mais que isso é apagada
    max_turnos: int = 40  # mensagens livres (texto e arquivo do caso fora do roteiro); "Executar passo" não conta
    max_falas: int = 25  # falas pelo microfone (ASR)
    max_uploads: int = 12  # arquivos do aparelho
    upload_mb: dict[str, float] = field(default_factory=lambda: {"foto": 10.0, "video": 30.0, "nfe_xml": 2.0})
    upload_total_mb: float = 60.0  # soma dos arquivos de um visitante
    video_max_s: float = 20.0  # vídeo do visitante: o YOLOX roda na CPU (até ~1 min)
    audio_mb: float = 3.0
    audio_max_s: float = 30.0

    @classmethod
    def do_ambiente(cls, env: dict[str, str] | os._Environ | None = None) -> Limites:
        e = os.environ if env is None else env
        p = cls()
        return cls(
            max_sessoes=int(_num(e, "LAUDO_DEMO_MAX_SESSOES", p.max_sessoes)),
            ttl_s=_num(e, "LAUDO_DEMO_TTL_MIN", p.ttl_s / 60) * 60,
            max_turnos=int(_num(e, "LAUDO_DEMO_MAX_TURNOS", p.max_turnos)),
            max_falas=int(_num(e, "LAUDO_DEMO_MAX_FALAS", p.max_falas)),
            max_uploads=int(_num(e, "LAUDO_DEMO_MAX_UPLOADS", p.max_uploads)),
            upload_mb={
                "foto": _num(e, "LAUDO_DEMO_FOTO_MB", p.upload_mb["foto"]),
                "video": _num(e, "LAUDO_DEMO_VIDEO_MB", p.upload_mb["video"]),
                "nfe_xml": _num(e, "LAUDO_DEMO_XML_MB", p.upload_mb["nfe_xml"]),
            },
            upload_total_mb=_num(e, "LAUDO_DEMO_UPLOAD_TOTAL_MB", p.upload_total_mb),
            video_max_s=_num(e, "LAUDO_DEMO_VIDEO_MAX_S", p.video_max_s),
            audio_mb=_num(e, "LAUDO_DEMO_AUDIO_MB", p.audio_mb),
            audio_max_s=_num(e, "LAUDO_DEMO_AUDIO_MAX_S", p.audio_max_s),
        )

    def publico(self) -> dict[str, Any]:
        return {
            "turnos": self.max_turnos,
            "falas": self.max_falas,
            "uploads": self.max_uploads,
            "upload_mb": dict(self.upload_mb),
            "video_max_s": self.video_max_s,
            "audio_max_s": self.audio_max_s,
        }


class ErroLimite(ErroServico):
    """Limite da demonstração estourado: a tela mostra a mensagem; vira o evento `recusa_limite`."""

    def __init__(self, limite: str, msg: str, status: int = 429, sessao: str | None = None, **campos: Any):
        super().__init__(status, msg)
        self.limite = limite
        eventos.evento("recusa_limite", limite=limite, status=status, **({"sessao": sessao} if sessao else {}),
                       **campos)


# ---------------------------------------------------------------------------
# Cópia por visitante
# ---------------------------------------------------------------------------


class RepositorioPublico(est.RepositorioFiscalizacoes):
    """Marca o turno livre na conversa (`livre: true`) e, no passo do roteiro, tira os turnos livres do histórico
    que vai ao LLM (`ler_conversa(..., ultimos=)`, o único uso com `ultimos`, em `Condutor._mensagens`). A tela
    lê a conversa inteira."""

    def __init__(self, diretorio: Path):
        super().__init__(diretorio)
        self.marcar_livre = False
        self.ocultar_livres = False

    def anexar_conversa(self, fis_id: str, registro: dict[str, Any]) -> None:
        if self.marcar_livre:
            registro = {**registro, "livre": True}
        super().anexar_conversa(fis_id, registro)

    def ler_conversa(self, fis_id: str, ultimos: int | None = None) -> list[dict[str, Any]]:
        linhas = super().ler_conversa(fis_id)
        if ultimos and self.ocultar_livres:
            linhas = [x for x in linhas if not x.get("livre")]
        return linhas[-ultimos:] if ultimos else linhas


@dataclass
class Sessao:
    sid: str  # hash do cookie (nome da pasta); nunca o cookie
    dados: Path
    contexto: isolamento.Contexto
    gerenciador: GerenciadorSessoes | None = None
    criada: float = field(default_factory=time.time)
    usada: float = field(default_factory=time.time)
    turnos: int = 0
    falas: int = 0
    uploads: int = 0
    upload_bytes: int = 0
    servico: ServicoPublico | None = None
    ids_livres: dict[str, Any] = field(default_factory=lambda: {"semente": None, "n": 0})

    @property
    def ids_roteiro(self) -> dict[str, Any]:
        return self._ids_roteiro

    def __post_init__(self) -> None:
        self._ids_roteiro = self.contexto.ids  # o dicionário que `ids_deterministicos` reinicia no lugar

    @property
    def curta(self) -> str:
        return self.contexto.sessao

    @contextmanager
    def modo(self, livre: bool) -> Iterator[None]:
        """Turno livre (ids próprios, marcado na conversa) ou passo do roteiro (ids da gravação, histórico sem os
        turnos livres). Aninhável: volta ao modo anterior."""
        repo = self.servico.repo if self.servico is not None else None
        antes_ids = self.contexto.ids
        antes = (repo.marcar_livre, repo.ocultar_livres) if isinstance(repo, RepositorioPublico) else None
        self.contexto.ids = self.ids_livres if livre else self._ids_roteiro
        if antes is not None:
            repo.marcar_livre, repo.ocultar_livres = livre, not livre  # type: ignore[union-attr]
        try:
            yield
        finally:
            self.contexto.ids = antes_ids
            if antes is not None:
                repo.marcar_livre, repo.ocultar_livres = antes  # type: ignore[union-attr]

    def uso(self) -> dict[str, int]:
        return {"turnos": self.turnos, "falas": self.falas, "uploads": self.uploads}


def _passo_da_fala(p: Any, texto: str) -> bool:
    return bool(p) and p.acao == "turno" and not p.evidencia and bool(p.fala) and fala_corresponde(p.fala, texto)


def _passo_de_emissao(p: Any) -> bool:
    if not p or p.evidencia:
        return False
    if p.acao == "rascunho":
        return True
    from laudo.agent.intencao import comando_humano

    cmd = comando_humano(p.fala) if p.acao == "turno" and p.fala else None
    return bool(cmd) and cmd[0] == "emitir_rascunho"


class ServicoPublico(Servico):
    """O `Servico` de uma cópia: pasta, repositório, provedor e condutor próprios (ver o docstring do módulo)."""

    def __init__(self, cfg: Config, sessao: Sessao, transcritor: Any | None = None):
        self.sessao = sessao
        super().__init__(cfg, transcritor=transcritor)

    # -- montagem --------------------------------------------------------------------
    def _configurar_traces(self) -> None:
        # os traces vão para a pasta da cópia pelo contexto (`laudo.isolamento`), sem trocar o do processo
        (self.dados / "traces").mkdir(parents=True, exist_ok=True)

    def _novo_repositorio(self) -> est.RepositorioFiscalizacoes:
        return RepositorioPublico(self.dados)

    def _montar_registro(self, cenario: dict[str, dict[str, Any]]) -> tuple[dict, list[str]]:
        reg, falsas = super()._montar_registro(cenario)
        if "contar_bovinos_video" in reg and "contar_bovinos_video" not in falsas and self.cfg.ferramentas == "reais":
            reg = dict(reg)
            reg["contar_bovinos_video"] = contagem_com_cache(reg["contar_bovinos_video"], self._videos_do_caso)
        return reg, falsas

    def _videos_do_caso(self) -> set[str]:
        """sha256 dos vídeos prontos do caso de demonstração (a contagem deles sai do cache)."""
        ger = self.sessao.gerenciador
        cache = ger.videos_preset if ger is not None else None
        if cache is not None:
            return cache
        out = set()
        try:
            for a in self.caso(self.caso_padrao).arquivos:
                if a.tipo == "video" and a.disponivel and a.nova.caminho and Path(a.nova.caminho).is_file():
                    out.add(sha256_arquivo(a.nova.caminho))
        except (FileNotFoundError, ErroServico):
            pass
        if ger is not None:
            ger.videos_preset = out
        return out

    def caso(self, cid: str):
        """Os casos são lidos uma vez por processo (pela cópia de base) e divididos entre as cópias."""
        ger = self.sessao.gerenciador
        if ger is not None and cid in ger.casos:
            c = ger.casos[cid]
            self._casos.setdefault(cid, c)
            return c
        c = super().caso(cid)
        if ger is not None:
            ger.casos.setdefault(cid, c)
            ger.casos.setdefault(c.id, c)
        return c

    def listar_casos(self) -> list[dict[str, Any]]:
        return [self.caso(self.caso_padrao).resumo() | {"padrao": True}]

    def saude(self) -> dict[str, Any]:
        d = super().saude()
        d["config"]["demo_publica"] = True
        caso = self.caso(self.caso_padrao)
        lim = self.sessao.gerenciador.limites if self.sessao.gerenciador else Limites()
        d["demo_publica"] = {"fis_id": caso.fis_id, "caso": caso.id, "limites": lim.publico(),
                             "uso": self.sessao.uso()}
        return d

    # -- ações -----------------------------------------------------------------------
    def abrir_caso(self, cid: str, reiniciar: bool = True) -> dict[str, Any]:
        if cid not in {self.caso_padrao, self.caso(self.caso_padrao).id}:
            raise ErroServico(403, "Na demonstração pública só o caso de demonstração abre.")
        with self.sessao.modo(livre=False):
            out = super().abrir_caso(cid, reiniciar=reiniciar)
        if reiniciar:
            sem = self.sessao.ids_roteiro.get("semente")
            self.sessao.ids_livres.clear()
            self.sessao.ids_livres.update({"semente": f"{sem}:livre" if sem else None, "n": 0})
        return out

    def abrir_ref(self, ref_bacen: str, nova: bool = False) -> dict[str, Any]:
        raise ErroServico(403, "Na demonstração pública só o caso de demonstração abre (dados sintéticos).")

    def passo_do_texto(self, fis_id: str, texto: str) -> bool:
        atual = self._passo_atual(fis_id)
        return atual is not None and _passo_da_fala(atual[2], texto)

    def turno(self, fis_id: str, texto: str = "", origem: str = "texto", evidencia=None, passos_llm=None,
              extra=None, confianca_asr=None, residual=None, do_roteiro: bool = False,
              nome_caso: str | None = None) -> dict[str, Any]:
        # a fala transcrita (ou confirmada) igual à do próximo passo vira o passo: a resposta sai da gravação
        if origem == "asr" and evidencia is None and not residual and not do_roteiro:
            with self.lock:
                if self.passo_do_texto(fis_id, texto):
                    with self.sessao.modo(livre=False):
                        out = self.passo_roteiro(fis_id)
                    return out | (extra or {}) | {"pelo_roteiro": True}
        return super().turno(fis_id, texto, origem=origem, evidencia=evidencia, passos_llm=passos_llm,
                             extra=extra, confianca_asr=confianca_asr, residual=residual,
                             do_roteiro=do_roteiro, nome_caso=nome_caso)


# ---------------------------------------------------------------------------
# Fachada por requisição (o que as rotas chamam)
# ---------------------------------------------------------------------------

_FORMATOS = {"foto": ("jpeg", "png", "webp"), "video": ("mp4", "webm"), "nfe_xml": ("xml",)}
_ROTULO_TIPO = {"foto": "foto (JPEG, PNG ou WebP)", "video": "vídeo (MP4, MOV ou WebM)", "nfe_xml": "XML da NF-e"}


def formato_arquivo(cab: bytes) -> str | None:
    """Formato pelo começo do arquivo (assinatura), nunca pela extensão nem pelo tipo que o navegador diz."""
    if cab.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if cab.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if cab[:4] == b"RIFF" and cab[8:12] == b"WEBP":
        return "webp"
    if cab[4:8] == b"ftyp":
        marca = cab[8:12]
        if marca in (b"heic", b"heix", b"hevc", b"heim", b"heis", b"mif1", b"msf1", b"avif"):
            return "heic"
        return "mp4"
    if cab.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm"
    t = cab[3:] if cab.startswith(b"\xef\xbb\xbf") else cab
    if t.lstrip().startswith(b"<"):
        return "xml"
    return None


def duracao_video(caminho: Path) -> float | None:
    """Duração do vídeo pelo contêiner; sem ela (gravação do navegador), pelo último pacote. None: ilegível."""
    import av

    try:
        with av.open(str(caminho)) as c:
            if not c.streams.video:
                return None
            s = c.streams.video[0]
            if s.duration is not None and s.time_base is not None:
                return float(s.duration * s.time_base)
            if c.duration:
                return c.duration / 1_000_000
            fim = 0.0
            for pac in c.demux(s):
                if pac.pts is not None and pac.time_base is not None:
                    fim = max(fim, float(pac.pts * pac.time_base))
            return fim or None
    except Exception:  # noqa: BLE001 - qualquer falha de leitura: vídeo ilegível
        return None


class FachadaSessao:
    """O que as rotas chamam na demo pública: cada chamada roda no contexto da cópia do visitante, com a trava
    dela; as ações separam o passo do roteiro (gravação) do turno livre e conferem os limites."""

    def __init__(self, ger: GerenciadorSessoes, sessao: Sessao):
        self._ger = ger
        self._s = sessao

    @property
    def sessao(self) -> Sessao:
        return self._s

    @property
    def servico(self) -> ServicoPublico:
        assert self._s.servico is not None
        return self._s.servico

    @contextmanager
    def _ativo(self) -> Iterator[ServicoPublico]:
        srv = self.servico
        self._s.usada = self._ger.relogio()
        with isolamento.ativo(self._s.contexto), srv.lock:
            yield srv

    def __getattr__(self, nome: str) -> Any:
        alvo = getattr(self.servico, nome)
        if not callable(alvo):
            return alvo

        def chamada(*a: Any, **k: Any) -> Any:
            with self._ativo():
                return alvo(*a, **k)

        return chamada

    # -- limites -----------------------------------------------------------------------
    def _limite(self, contador: str, maximo: int, msg: str) -> None:
        if getattr(self._s, contador) >= maximo:
            raise ErroLimite(contador, msg, sessao=self._s.curta, maximo=maximo)
        setattr(self._s, contador, getattr(self._s, contador) + 1)

    def _fora(self) -> int:
        r = self.servico.replay_publico
        return int(getattr(r, "fora", 0) or 0)

    def _ev(self, nome: str, **campos: Any) -> None:
        eventos.evento(nome, sessao=self._s.curta, **campos)

    def _evento_turno(self, canal: str, out: dict[str, Any], t0: float, fora0: int, livre: bool, **extra: Any):
        est_ = out.get("estado") or {}
        self._ev("turno", canal=canal, livre=livre, etapa=est_.get("etapa"), passo=(out.get("passo") or {}).get("n"),
                 latencia_ms=int((time.perf_counter() - t0) * 1000), fora_da_gravacao=self._fora() - fora0, **extra)

    # -- passo do roteiro ------------------------------------------------------------------
    def _passo(self, fis_id: str, canal: str = "passo") -> dict[str, Any]:
        t0, fora0 = time.perf_counter(), self._fora()
        with self._ativo() as srv, self._s.modo(livre=False):
            out = srv.passo_roteiro(fis_id)
        self._evento_turno(canal, out, t0, fora0, livre=False)
        return out

    def passo_roteiro(self, fis_id: str, n: int | None = None) -> dict[str, Any]:
        with self._ativo() as srv:
            atual = srv._passo_atual(fis_id)
        if n is not None and (atual is None or atual[1] != n):
            raise ErroServico(400, "Na demonstração pública o roteiro segue em ordem: use “Executar passo”.")
        return self._passo(fis_id)

    def pular_passo(self, fis_id: str) -> dict[str, Any]:
        with self._ativo() as srv, self._s.modo(livre=False):
            return srv.pular_passo(fis_id)

    def abrir_caso(self, cid: str, reiniciar: bool = True) -> dict[str, Any]:
        with self._ativo() as srv:
            return srv.abrir_caso(cid, reiniciar=reiniciar)

    # -- turnos ----------------------------------------------------------------------------
    def turno(self, fis_id: str, texto: str = "", origem: str = "texto",
              residual: dict[str, str] | None = None) -> dict[str, Any]:
        with self._ativo() as srv:
            if not residual and srv.passo_do_texto(fis_id, texto):
                return self._passo(fis_id, canal="texto")
            self._limite("turnos", self._ger.limites.max_turnos,
                         f"Limite da demonstração: até {self._ger.limites.max_turnos} mensagens livres por visitante. "
                         "O roteiro continua em “Executar passo”.")
            t0, fora0 = time.perf_counter(), self._fora()
            with self._s.modo(livre=True):
                out = srv.turno(fis_id, texto, origem=origem, residual=residual)
        self._evento_turno("texto", out, t0, fora0, livre=True)
        return out

    def turno_audio(self, fis_id: str, nome: str, conteudo: bytes, confirmar_numeros: bool = True) -> dict[str, Any]:
        lim = self._ger.limites
        if len(conteudo) > lim.audio_mb * MIB:
            raise ErroLimite("audio_mb", f"Fala acima de {lim.audio_mb:g} MB: fale em trechos curtos.", status=413,
                             sessao=self._s.curta)
        with self._ativo() as srv:
            if srv.transcritor is None:
                raise ErroServico(503, "voz desligada neste modo: digite a fala")
            srv.carregar(fis_id)
            if conteudo:
                from laudo.speech.asr import TAXA, ErroASR, decodificar

                try:
                    dur = decodificar(conteudo).size / TAXA
                except ErroASR as e:
                    raise ErroServico(400, e.msg) from e
                if dur > lim.audio_max_s:
                    raise ErroLimite("audio_s", f"Fala de {dur:.0f} s: o limite da demonstração é "
                                     f"{lim.audio_max_s:g} s por fala.", status=413, sessao=self._s.curta)
            self._limite("falas", lim.max_falas, f"Limite da demonstração: até {lim.max_falas} falas por visitante. "
                         "Digite a mensagem ou use “Executar passo”.")
            t0, fora0 = time.perf_counter(), self._fora()
            with self._s.modo(livre=True):
                out = srv.turno_audio(fis_id, nome, conteudo, confirmar_numeros)
        tr = out.get("transcricao") or {}
        self._ev("asr", audio_s=tr.get("duracao_audio_s"), latencia_ms=tr.get("latencia_ms"), modelo=tr.get("modelo"),
                 dispositivo=tr.get("dispositivo"), vazio=tr.get("vazio"))
        if out.get("resposta") is not None:
            self._evento_turno("voz", out, t0, fora0, livre=not out.get("pelo_roteiro"))
        return out

    def confirmar(self, fis_id: str, aceitar: bool, texto: str | None = None) -> dict[str, Any]:
        t0, fora0 = time.perf_counter(), self._fora()
        with self._ativo() as srv, self._s.modo(livre=True):
            out = srv.confirmar(fis_id, aceitar, texto)
        if out.get("resposta") is not None:
            self._evento_turno("voz", out, t0, fora0, livre=not out.get("pelo_roteiro"))
        return out

    def evidencia_do_caso(self, fis_id: str, nome: str, texto: str = "") -> dict[str, Any]:
        with self._ativo() as srv:
            atual = srv._passo_atual(fis_id)
            p = atual[2] if atual else None
            if p is not None and p.acao == "turno" and p.evidencia == nome:
                return self._passo(fis_id)
            self._limite("turnos", self._ger.limites.max_turnos,
                         f"Limite da demonstração: até {self._ger.limites.max_turnos} mensagens livres por visitante.")
            t0, fora0 = time.perf_counter(), self._fora()
            with self._s.modo(livre=True):
                out = srv.evidencia_do_caso(fis_id, nome, texto)
        self._evento_turno("texto", out, t0, fora0, livre=True, arquivo_do_caso=True)
        return out

    def pedir_rascunho(self, fis_id: str) -> dict[str, Any]:
        with self._ativo() as srv:
            atual = srv._passo_atual(fis_id)
            if atual is not None and _passo_de_emissao(atual[2]):
                return self._passo(fis_id)
            with self._s.modo(livre=True):
                return srv.pedir_rascunho(fis_id)

    def assinar(self, fis_id: str, pin: str, hash_confirmado: str, papel: str = "fiscal",
                nome_ref: str = "fiscal-demo") -> dict[str, Any]:
        with self._ativo() as srv:
            atual = srv._passo_atual(fis_id)
            no_roteiro = atual is not None and atual[2].acao == "assinar"
            with self._s.modo(livre=not no_roteiro):
                out = srv.assinar(fis_id, pin, hash_confirmado, papel, nome_ref)
        etapa = (out.get("estado") or {}).get("etapa")
        self._ev("assinatura", ok=etapa == "SELADO", tentativas_restantes=out.get("tentativas_restantes"),
                 no_roteiro=no_roteiro)
        if etapa == "SELADO":
            self._ev("selo", passos_pulados=len(srv.meta(fis_id).get("passos_pulados") or []),
                     turnos_livres=self._s.turnos, falas=self._s.falas, uploads=self._s.uploads,
                     minutos=round((self._ger.relogio() - self._s.criada) / 60, 1))
        return out

    def upload(self, fis_id: str, nome: str, fluxo, tipo: str, item_id: str | None = None, lote: str | None = None,
               texto: str = "", gps: dict[str, Any] | None = None, capturada_em: str | None = None,
               mime: str = "") -> dict[str, Any]:
        lim, s = self._ger.limites, self._s
        if tipo not in lim.upload_mb:
            raise ErroLimite("tipo", "Na demonstração pública o aparelho envia só foto, vídeo curto ou o XML da NF-e; "
                             "a foto da nota ou da GTA vem dos arquivos prontos do caso.", status=415, sessao=s.curta,
                             tipo=tipo)
        self._limite("uploads", lim.max_uploads, f"Limite da demonstração: até {lim.max_uploads} arquivos por "
                     "visitante. Use os arquivos prontos do caso.")
        teto = int(lim.upload_mb[tipo] * MIB)
        with self._ativo() as srv:
            srv.carregar(fis_id)
            entrada = s.dados / "_entrada" / uuid.uuid4().hex[:10]
            entrada.mkdir(parents=True, exist_ok=True)
            tmp = entrada / "arquivo"
            try:
                n = 0
                with open(tmp, "wb") as f:
                    while bloco := fluxo.read(1 << 20):
                        n += len(bloco)
                        if n > teto:
                            raise ErroLimite("tamanho", f"Arquivo acima de {lim.upload_mb[tipo]:g} MB "
                                             f"({_ROTULO_TIPO[tipo]}).", status=413, sessao=s.curta, tipo=tipo)
                        f.write(bloco)
                if s.upload_bytes + n > lim.upload_total_mb * MIB:
                    raise ErroLimite("upload_total", f"Limite da demonstração: até {lim.upload_total_mb:g} MB de "
                                     "arquivos por visitante.", sessao=s.curta)
                with open(tmp, "rb") as f:
                    fmt = formato_arquivo(f.read(64))
                if fmt not in _FORMATOS[tipo]:
                    raise ErroLimite("tipo", f"Este arquivo não é {_ROTULO_TIPO[tipo]}.", status=415, sessao=s.curta,
                                     tipo=tipo, formato=fmt or "desconhecido")
                if tipo == "video":
                    dur = duracao_video(tmp)
                    if dur is None:
                        raise ErroServico(400, "Não consegui ler este vídeo.")
                    if dur > lim.video_max_s + 0.5:
                        raise ErroLimite("video_s", f"Vídeo de {dur:.0f} s: na demonstração pública, até "
                                         f"{lim.video_max_s:g} s (a contagem roda na CPU).", status=413,
                                         sessao=s.curta)
                s.upload_bytes += n
                t0, fora0 = time.perf_counter(), self._fora()
                # GPS do aparelho não entra (só os presets do caso): nada da localização do visitante é guardado
                with open(tmp, "rb") as f, s.modo(livre=True):
                    out = srv.upload(fis_id, nome, f, tipo, item_id=item_id, lote=lote, texto=texto, gps=None,
                                     capturada_em=capturada_em, mime=mime)
            finally:
                shutil.rmtree(entrada, ignore_errors=True)
        self._ev("upload", tipo=tipo, mb=round(n / MIB, 2))
        self._evento_turno("arquivo", out, t0, fora0, livre=True, tipo=tipo)
        return out


# ---------------------------------------------------------------------------
# Gerenciador das cópias
# ---------------------------------------------------------------------------


class GerenciadorSessoes:
    """Cópias vivas por cookie: cria (com o caso aberto), entrega e apaga as paradas há mais de `ttl_s`."""

    BASE = "_base"

    def __init__(self, cfg: Config, limites: Limites | None = None, raiz: Path | None = None,
                 transcritor: Any | None = None, relogio: Callable[[], float] = time.time):
        self.cfg_base = cfg
        self.limites = limites or Limites.do_ambiente()
        self.raiz = Path(raiz or os.environ.get("LAUDO_DEMO_DIR") or Path(tempfile.gettempdir()) / "laudo-demo-publica")
        self.transcritor = transcritor
        self.relogio = relogio
        self.lock = threading.Lock()
        self.sessoes: dict[str, Sessao] = {}
        self._criando: dict[str, threading.Event] = {}
        self.casos: dict[str, Any] = {}
        self.videos_preset: set[str] | None = None
        # as cópias não sobrevivem ao processo: a pasta recomeça vazia
        shutil.rmtree(self.raiz, ignore_errors=True)
        self.raiz.mkdir(parents=True, exist_ok=True)
        # cópia de base: lê os casos uma vez e responde a saúde de quem ainda não tem cópia (sem criar uma)
        self.base = self._criar(self.BASE, abrir=False)

    @staticmethod
    def sid_de(token: str) -> str:
        return hashlib.sha256(f"laudo-demo-publica:{token}".encode()).hexdigest()[:20]

    def _criar(self, sid: str, abrir: bool = True) -> Sessao:
        dados = self.raiz / sid
        ctx = isolamento.Contexto(traces=dados / "traces", sessao=sid[:10])
        s = Sessao(sid=sid, dados=dados, contexto=ctx, gerenciador=self, criada=self.relogio(), usada=self.relogio())
        cfg = dataclasses.replace(self.cfg_base, dados=dados)
        with isolamento.ativo(ctx):
            s.servico = ServicoPublico(cfg, s, transcritor=self.transcritor)
            if abrir:  # dados pré-selecionados: o caso de demonstração já aberto, no passo 1
                s.servico.abrir_caso(s.servico.caso_padrao)
        return s

    def obter(self, token: str | None, criar: bool = True) -> Sessao | None:
        if not token_valido(token):
            if not criar:
                return None
            raise ErroServico(400, "sessão inválida: recarregue a página")
        sid = self.sid_de(token or "")
        while True:
            velhas: list[Sessao] = []
            cheio = dono = False
            with self.lock:
                s = self.sessoes.get(sid)
                if s is not None:
                    s.usada = self.relogio()
                    return s
                if not criar:
                    return None
                espera = self._criando.get(sid)
                if espera is None:
                    velhas = self._expiradas()
                    vivas = len(self.sessoes) + len(self._criando)
                    cheio = vivas >= self.limites.max_sessoes
                    if not cheio:
                        espera = self._criando[sid] = threading.Event()
                        dono = True
            self._apagar(velhas)  # fora da trava do mapa: espera o turno em andamento da cópia vencida
            if cheio:
                raise ErroLimite("sessoes", "Limite da demonstração: muita gente usando agora. Tente de novo em "
                                 "alguns minutos.", sessao=sid[:10], vivas=vivas)
            if not dono:
                assert espera is not None
                espera.wait(60)
                continue
            nova: Sessao | None = None
            try:
                nova = self._criar(sid)
            finally:
                with self.lock:
                    if nova is not None:
                        self.sessoes[sid] = nova
                    self._criando.pop(sid).set()
                    vivas = len(self.sessoes)
            eventos.evento("sessao_nova", sessao=nova.curta, vivas=vivas)
            return nova

    def fachada(self, token: str | None, criar: bool = True) -> FachadaSessao | None:
        s = self.obter(token, criar=criar)
        return FachadaSessao(self, s) if s is not None else None

    def fachada_base(self) -> FachadaSessao:
        return FachadaSessao(self, self.base)

    def _expiradas(self) -> list[Sessao]:
        """Tira do mapa as cópias paradas há mais de `ttl_s` (chamar com `self.lock`)."""
        agora = self.relogio()
        velhas = [s for s in self.sessoes.values() if agora - s.usada > self.limites.ttl_s]
        for s in velhas:
            self.sessoes.pop(s.sid, None)
        return velhas

    def _apagar(self, velhas: list[Sessao]) -> None:
        for s in velhas:
            srv = s.servico
            # espera um turno em andamento terminar antes de apagar a pasta
            if srv is not None and srv.lock.acquire(timeout=30):
                srv.lock.release()
            shutil.rmtree(s.dados, ignore_errors=True)

    def limpar(self) -> int:
        """Apaga as cópias vencidas; devolve quantas."""
        with self.lock:
            velhas = self._expiradas()
        self._apagar(velhas)
        return len(velhas)

    def vivas(self) -> int:
        with self.lock:
            return len(self.sessoes)


# ---------------------------------------------------------------------------
# Contagem do vídeo pronto do caso: do cache (preparado no build)
# ---------------------------------------------------------------------------

_trava_cache = threading.Lock()


def _chave_contagem(args: Any, sha_video: str) -> str:
    base = args.model_dump(mode="json", exclude={"caminho_video", "dir_evidencias", "item_id"})
    return hash_entrada({"video": sha_video, "args": base})


def _prefixo(args: Any) -> str:
    # o mesmo prefixo dos quadros-chave que a ferramenta usaria (tools/bovinos.py)
    return f"{args.modo}_{hash_entrada(args.model_dump())[:6]}"


def contagem_com_cache(ferr: Ferramenta, presets: Callable[[], set[str]],
                       pasta: Path | None = None) -> Ferramenta:
    """A mesma ferramenta (nome, descrição e esquema iguais: o pedido ao LLM não muda); para o vídeo pronto do
    caso (`presets`, por sha256), o resultado vem do cache e os quadros-chave são copiados para a pasta da cópia.
    Vídeo enviado pelo visitante roda o YOLOX normalmente."""
    pasta = pasta or DIR_CACHE_CONTAGEM
    original = ferr.funcao

    def funcao(args: Any) -> Envelope:
        video = Path(args.caminho_video)
        if not video.is_file():
            return original(args)
        sha = sha256_arquivo(str(video))
        if sha not in presets():
            return original(args)
        destino = pasta / _chave_contagem(args, sha)
        arq = destino / "envelope.json"
        with _trava_cache:  # o primeiro calcula; os outros esperam e leem
            if not arq.is_file():
                env = original(args)
                if env.ok and env.data:
                    _gravar_contagem(destino, env)
                return env
        return _restaurar_contagem(arq, args, video)

    return ferr.model_copy(update={"funcao": funcao})


def _gravar_contagem(destino: Path, env: Envelope) -> None:
    try:
        tmp = destino.with_name(destino.name + f".{os.getpid()}.tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True, exist_ok=True)
        d = json.loads(env.model_dump_json())
        for q in d["data"].get("quadros_chave") or []:
            origem = Path(q["caminho"])
            if origem.is_file():
                shutil.copyfile(origem, tmp / origem.name)
            q["caminho"] = origem.name
        if isinstance(d["data"].get("video"), dict):  # o caminho local não vai para o cache (a restauração repõe)
            d["data"]["video"]["caminho"] = Path(d["data"]["video"].get("caminho") or "").name
        (tmp / "envelope.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        shutil.rmtree(destino, ignore_errors=True)
        tmp.replace(destino)
    except OSError as e:  # sem cache, a próxima cópia conta de novo
        log.warning("cache da contagem não gravado: %s", e)


def _restaurar_contagem(arq: Path, args: Any, video: Path) -> Envelope:
    d = json.loads(arq.read_text(encoding="utf-8"))
    dados = d["data"]
    dir_ev = Path(args.dir_evidencias) if args.dir_evidencias else arq.parent
    dir_ev.mkdir(parents=True, exist_ok=True)
    pre = _prefixo(args)
    for q in dados.get("quadros_chave") or []:
        nome = f"{pre}_{int(q['quadro']):06d}.jpg"
        shutil.copyfile(arq.parent / q["caminho"], dir_ev / nome)
        q["caminho"] = (dir_ev / nome).as_posix()
    dados["video"] = {**(dados.get("video") or {}), "caminho": video.as_posix()}
    dados["item_id"] = args.item_id
    return Envelope.model_validate(d)


# ---------------------------------------------------------------------------
# Build: roda o roteiro numa cópia, confere e deixa o cache pronto
# ---------------------------------------------------------------------------


def preparar(caso: str = "DEMO-0001", replay: str | None = None) -> int:
    """Roteiro inteiro numa cópia da demo pública (como um visitante clicando "Executar passo"), com a assinatura
    pelo PIN de demonstração. 0 = SELADO e nenhuma requisição fora da gravação; grava o cache da contagem."""
    from laudo.api.servico import PIN_DEMO

    os.environ.setdefault(ENV, "1")
    os.environ.setdefault("LAUDO_VLM_CACHE", str(REPO / "tests" / "unit" / "dados_agente" / "vlm_cache_demo"))
    os.environ.setdefault("LAUDO_VLM_SO_CACHE", "1")
    raiz = Path(tempfile.mkdtemp(prefix="laudo-demo-preparar-"))
    try:
        cfg = Config(llm="publico", ferramentas="reais", caso=caso, asr="desligado", replay=replay,
                     provedor_livre=_SemLLM())
        ger = GerenciadorSessoes(cfg, Limites(), raiz=raiz / "sessoes")
        fach = ger.fachada(novo_token())
        assert fach is not None
        fis = fach.estado(fach.servico.caso(caso).fis_id)["id"]
        t0 = time.perf_counter()
        n = 0
        while True:
            try:
                out = fach.passo_roteiro(fis)
            except ErroServico as e:
                if e.status == 409:
                    break
                raise
            n += 1
            print(f"[{n:02d}] {out['passo']['titulo']}", flush=True)
            if out.get("acao_humana") == "assinar":
                h = fach.estado(fis)["laudo"]["hash_raiz"]
                fach.assinar(fis, PIN_DEMO, h)
        etapa = fach.estado(fis)["etapa"]
        fora = fach._fora()
        print(f"demo pública: {n} passos em {time.perf_counter() - t0:.1f} s, etapa {etapa}, {fora} fora da gravação; "
              f"cache da contagem em {DIR_CACHE_CONTAGEM}", flush=True)
        return 0 if etapa == "SELADO" and fora == 0 else 1
    finally:
        est.ids_deterministicos(None)
        shutil.rmtree(raiz, ignore_errors=True)


class _SemLLM:
    """Segundo elo da cadeia no build: nenhum LLM ao vivo (o roteiro inteiro tem de sair da gravação)."""

    nome = "nenhum"
    modelo = ""
    externo = False

    def chat(self, *_a: Any, **_k: Any):
        from laudo.llm.provider import ErroLLM

        raise ErroLLM("INDISPONIVEL", "sem LLM ao vivo no preparo da imagem")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preparar", action="store_true", help="roteiro inteiro numa cópia; grava o cache da contagem")
    ap.add_argument("--caso", default="DEMO-0001")
    ap.add_argument("--replay", default=None)
    a = ap.parse_args()
    if not a.preparar:
        ap.print_help()
        sys.exit(2)
    logging.basicConfig(level=logging.WARNING)
    sys.exit(preparar(a.caso, a.replay))
