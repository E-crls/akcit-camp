"""Serviço da interface: um condutor por processo, casos de demo, voz e ações humanas.

Programa contra a API pública do agente: `Condutor.abrir()`, `turno()`, `executar_acao()` (pedido humano de
rascunho), `assinar()` e `ultimo_laudo()`; o repositório só é lido. Funciona com ferramentas falsas, mistas
(documentos e fotos reais, vídeo simulado) ou reais, e com LLM roteirizado, Ollama ou replay.

Concorrência: a demo é de um fiscal por vez. Turnos e ações humanas passam por um lock (o condutor não é
thread-safe); o ASR roda fora dele, com lock próprio.

Roteiro da demo: o ponteiro (`proximo_passo` no meta) avança pelo botão "Executar passo" e também quando
o fiscal faz o passo atual por outro caminho: diz a fala do passo no microfone (ou digita), usa a evidência
pronta do passo, aperta "Emitir rascunho" no passo do pedido de laudo ou completa o residual pedido. Assim o →
seguinte não repete a pressão nem o bloqueio, e o replay não sai da gravação. "Pular passo" avança sem
executar.

Uploads: GTA ou NF-e enviados como PDF, JPEG ou PNG são a foto/scan do papel e viram `documento`
(a e-GTA é o JSON; a NF-e eletrônica é o XML); cada tipo tem limite de tamanho, conferido enquanto o arquivo
chega.

Retomada: nada da fiscalização fica só na memória do processo. O estado e a cadeia de hash estão no
JSON do repositório (gravação atômica); a confirmação de números falados ainda pendente, as tentativas erradas
de PIN e as pendências do último turno ficam no meta da interface (`<dados>/ui/<id>.json`, também gravado de
forma atômica). Se o servidor cair e subir de novo, a fiscalização continua de onde parou, e a trava do PIN
não é zerada pelo reinício.
"""

from __future__ import annotations

import difflib
import hashlib
import hmac
import json
import logging
import os
import re
import shutil
import threading
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from laudo import demonstracao
from laudo.agent import estado as est
from laudo.agent.condutor import (
    AcaoExecutada,
    Condutor,
    Evento,
    NovaEvidencia,
    RespostaTurno,
    residual_pendente,
)
from laudo.agent.ferramentas_falsas import registro_com_falsas
from laudo.agent.pii import mascarar, mascarar_obj
from laudo.api import casos as casos_mod
from laudo.api import visao
from laudo.audit import otel
from laudo.contracts import GPS, REGISTRO, Fiscalizacao, Operacao
from laudo.tools.laudo import ErroSelagem, rotulo_metodo
from laudo.tools.pacote import por_que_na_amostra

log = logging.getLogger(__name__)
REPO = Path(__file__).resolve().parents[3]
PIN_DEMO = "2410"
MAX_TENTATIVAS_PIN = 5
# Limite de tamanho por tipo de evidência (MB), conferido em streaming no upload
LIMITE_UPLOAD_MB = {"foto": 25, "video": 600, "nfe_xml": 5, "gta": 10, "documento": 25}
LIMITE_AUDIO_MB = 20
# Assinatura do arquivo: GTA/NF-e enviada como PDF ou imagem é o papel (foto/scan), não o documento eletrônico
_ASSINATURA_PAPEL = ((b"%PDF", "PDF"), (b"\xff\xd8\xff", "JPEG"), (b"\x89PNG", "PNG"))
_PAPEL_DE = {"gta": "gta", "nfe_xml": "danfe"}


@dataclass
class Config:
    llm: str = "roteiro"  # roteiro | ollama | replay
    ferramentas: str = "falsas"  # falsas | mistas | reais
    caso: str = "roteiro"  # caso aberto pelo botão "demo": roteiro | DEMO-0001 | pasta com caso.yaml
    replay: str | None = None  # JSONL gravado (llm=replay); padrão: o do caso
    gravar: str | None = None  # grava requisições do Ollama (para virar replay de contingência)
    perfil: str = "campo"
    modelo: str | None = None
    modo: str = "tools"
    dados: Path = field(default_factory=lambda: REPO / "dados_locais" / "api")
    asr: str = "auto"  # auto | cuda | cpu | desligado
    asr_beam: int = 1
    pin: str = field(default_factory=lambda: os.environ.get("LAUDO_PIN") or PIN_DEMO)
    web: Path = field(default_factory=lambda: REPO / "apps" / "web")
    hoje: date | None = None

    def publico(self) -> dict[str, Any]:
        return {
            "llm": self.llm,
            "ferramentas": self.ferramentas,
            "caso": self.caso,
            "perfil": self.perfil,
            "modelo": self.modelo,
            "modo": self.modo,
            "asr": self.asr,
            "replay": self.replay,
            "gravando": bool(self.gravar),
            "pin_demo": self.pin == PIN_DEMO,
        }


class ErroServico(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status
        self.msg = msg


_ID_OK = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def checar_id(x: str) -> str:
    if not _ID_OK.match(x or ""):
        raise ErroServico(400, "identificador inválido")
    return x


def nome_seguro(nome: str, padrao: str = "arquivo") -> str:
    base = Path(nome or padrao).name
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._") or padrao
    return base[:100]


class Servico:
    def __init__(self, cfg: Config, transcritor: Any | None = None):
        self.cfg = cfg
        self.dados = Path(cfg.dados)
        self.dados.mkdir(parents=True, exist_ok=True)
        (self.dados / "ui").mkdir(exist_ok=True)
        otel.configurar(self.dados / "traces")
        self.repo = est.RepositorioFiscalizacoes(self.dados)
        self.lock = threading.RLock()
        self._casos: dict[str, casos_mod.CasoDemo] = {}
        self.caso_padrao = cfg.caso or casos_mod.caso_padrao()
        cenario: dict[str, dict[str, Any]] = {}
        for cid in dict.fromkeys(["roteiro", self.caso_padrao]):
            try:
                c = self.caso(cid)
                cenario.update(c.cenario)
            except FileNotFoundError as e:
                log.warning("caso %s indisponível: %s", cid, e)
        self.cenario = cenario
        self.registro, self.falsas = self._montar_registro(cenario)
        self.roteiro_llm = None
        self.provedor = self._novo_provedor()
        self.cond = Condutor(
            self.provedor,
            repo=self.repo,
            registro=self.registro,
            modo=cfg.modo,  # type: ignore[arg-type]
            hoje=cfg.hoje,
        )
        self.transcritor = transcritor
        if transcritor is None and cfg.asr != "desligado":
            from laudo.speech.asr import transcritor_padrao

            self.transcritor = transcritor_padrao(dispositivo=cfg.asr, beam_size=cfg.asr_beam)
        # guardados no meta da interface (sobrevivem a reinício do servidor; ver docstring do módulo)
        self._pendente = _NoMeta(self, "confirmacao_pendente")  # confirmação de números falados
        self._pins = _NoMeta(self, "pin_erros")  # tentativas erradas de PIN
        self._ultimo = _NoMeta(self, "ultimo_turno")  # pendências/eventos do último turno
        self._selos: dict[str, tuple[tuple, dict[str, Any]]] = {}  # conferência do selo por fiscalização

    # -- montagem ----------------------------------------------------------------
    def _montar_registro(self, cenario: dict[str, dict[str, Any]]) -> tuple[dict, list[str]]:
        modo = self.cfg.ferramentas
        if modo == "falsas":
            from laudo.tools import laudo as _laudo  # noqa: F401  (registra emitir_rascunho)

            base = {k: v for k, v in REGISTRO.items() if k in ("emitir_rascunho", "registrar_ocorrencia")}
            return registro_com_falsas(cenario, base=base)
        from laudo.tools import carregar_todas

        base = dict(carregar_todas())
        if modo == "mistas":  # documentos, fotos, geofence e regras reais; contagem de vídeo simulada
            base.pop("contar_bovinos_video", None)
        return registro_com_falsas(cenario, base=base)

    def _novo_provedor(self):
        from laudo.llm.provider import Gravador, OllamaProvider, ProvedorRoteirizado, ReplayProvider

        cfg = self.cfg
        if cfg.llm == "roteiro":
            from laudo.agent.roteiro_demo import RoteiroDemo

            self.roteiro_llm = RoteiroDemo()
            return ProvedorRoteirizado(self.roteiro_llm, modelo="roteiro-demo")
        if cfg.llm == "ollama":
            return OllamaProvider(
                modelo=cfg.modelo,
                perfil=cfg.perfil,
                hoje=cfg.hoje or datetime.now().astimezone().date(),
                gravador=Gravador(cfg.gravar) if cfg.gravar else None,
            )
        if cfg.llm == "replay":
            caso = self.caso(self.caso_padrao)
            gravada = self.dados / "gravacoes" / f"{caso.id}.jsonl"  # rodar_demo.sh --gravar grava aqui
            arq = cfg.replay or (str(gravada) if gravada.exists() else None) or caso.replay_padrao
            if not arq or not Path(arq).exists():
                raise ErroServico(500, f"replay sem gravação: {arq or 'nenhum arquivo'}")
            return ReplayProvider(arq, sequencial_se_ausente=True)
        raise ErroServico(500, f"LLM desconhecido: {cfg.llm}")

    def caso(self, cid: str) -> casos_mod.CasoDemo:
        if cid not in self._casos:
            # pela API só vale id (procurado em eval/golden) ou a pasta passada na linha de comando
            if cid not in ("roteiro", self.cfg.caso) and not _ID_OK.match(cid or ""):
                raise FileNotFoundError(f"caso {cid!r} não permitido")
            try:
                c = casos_mod.carregar_caso(cid, self.dados / "casos")
            except casos_mod.CasoDoTesteCongelado as e:
                raise ErroServico(403, str(e)) from e
            self._casos[cid] = c
            self._casos.setdefault(c.id, c)
        return self._casos[cid]

    # -- metadados da interface (arquivo ao lado do estado) -------------------------
    def _meta_path(self, fis_id: str) -> Path:
        return self.dados / "ui" / f"{checar_id(fis_id)}.json"

    def meta(self, fis_id: str) -> dict[str, Any]:
        p = self._meta_path(fis_id)
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}
        return {}

    def _salvar_meta(self, fis_id: str, m: dict[str, Any]) -> None:
        destino = self._meta_path(fis_id)
        tmp = destino.with_name(f".{destino.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(m, ensure_ascii=False, default=str, indent=1), encoding="utf-8")
        os.replace(tmp, destino)  # atômico: queda no meio da gravação não deixa meta pela metade

    def carregar(self, fis_id: str) -> Fiscalizacao:
        checar_id(fis_id)
        if not self.repo.existe(fis_id):
            raise ErroServico(404, f"fiscalização {fis_id} não encontrada")
        return self.repo.carregar(fis_id)

    # -- saúde ---------------------------------------------------------------------
    def saude(self) -> dict[str, Any]:
        llm: dict[str, Any] = {"tipo": self.cfg.llm, "modelo": getattr(self.provedor, "modelo", "")}
        if self.cfg.llm == "ollama":
            llm["disponivel"] = bool(self.provedor.disponivel())  # type: ignore[union-attr]
            llm["url"] = getattr(self.provedor, "base_url", "")
        else:
            llm["disponivel"] = True
        if self.cfg.llm == "replay":
            llm["arquivo"] = str(getattr(self.provedor, "caminho", ""))
            llm["substituicoes"] = getattr(self.provedor, "substituicoes", 0)
        asr = {"modo": self.cfg.asr, "disponivel": self.transcritor is not None}
        if self.transcritor is not None and hasattr(self.transcritor, "estado"):
            asr |= self.transcritor.estado()
        return {
            "ok": True,
            "versao": "laudo-vivo-api@0.1.0",
            "config": self.cfg.publico(),
            "llm": llm,
            "ferramentas": {
                "modo": self.cfg.ferramentas,
                "falsas": self.falsas,
                "registro": sorted(self.registro),
            },
            "asr": asr,
            "caso_padrao": self.caso_padrao,
            "casos": self.listar_casos(),
        }

    def listar_casos(self) -> list[dict[str, Any]]:
        # o caso padrão (o da demo do palco) vem primeiro; o roteiro de teste do agente e os demais depois
        ids = list(dict.fromkeys([self.caso_padrao, "roteiro", *casos_mod.listar_casos_disponiveis()]))
        out = []
        for cid in ids:
            try:
                c = self.caso(cid)
            except (FileNotFoundError, ValueError, KeyError) as e:
                out.append({"id": cid, "erro": str(e)[:200]})
                continue
            out.append(c.resumo() | {"padrao": cid == self.caso_padrao})
        return out

    # -- fiscalizações ----------------------------------------------------------------
    def listar(self) -> list[dict[str, Any]]:
        out = []
        for fid in self.repo.listar():
            try:
                f = self.repo.carregar(fid)
            except Exception as e:  # noqa: BLE001 - arquivo corrompido não derruba a lista
                log.warning("fiscalização %s ilegível: %s", fid, e)
                continue
            m = self.meta(fid)
            out.append(
                {
                    "id": fid,
                    "ref_bacen": f.operacao.ref_bacen,
                    "municipio": f.operacao.municipio_nome,
                    "etapa": f.estado_fsm,
                    "criada_em": f.criada_em.isoformat(timespec="seconds"),
                    "caso_id": m.get("caso_id"),
                    "origem": m.get("origem"),
                }
            )
        return sorted(out, key=lambda x: x["criada_em"], reverse=True)

    def abrir_caso(self, cid: str, reiniciar: bool = True) -> dict[str, Any]:
        caso = self.caso(cid)
        with self.lock:
            if not reiniciar and self.repo.existe(caso.fis_id):
                return self.estado(caso.fis_id)
            self._apagar_demo(caso.fis_id)
            est.ids_deterministicos(caso.semente_ids)  # o replay casa pela chave da requisição (ids)
            if self.cfg.llm == "replay":
                self.provedor = self._novo_provedor()
                self.cond.provedor = self.provedor
            extras: dict[str, Any] = {"id": caso.fis_id}
            if caso.data_fiscalizacao:
                extras["data_fiscalizacao"] = caso.data_fiscalizacao
            if caso.data_referencia:
                extras["data_referencia"] = caso.data_referencia
            self.cond.abrir(caso.operacao, **extras)
            self._salvar_meta(
                caso.fis_id,
                {
                    "caso_id": caso.id,
                    "origem": "caso",
                    "proximo_passo": 1,
                    "triagem": caso.triagem,
                    "criada_em": datetime.now().astimezone().isoformat(),
                },
            )
            self._pendente.pop(caso.fis_id, None)
            self._pins.pop(caso.fis_id, None)
            self._ultimo.pop(caso.fis_id, None)
        return self.estado(caso.fis_id)

    def _apagar_demo(self, fis_id: str) -> None:
        """Recomeça a fiscalização de demonstração do zero (só ids de caso de demo; nunca uma real)."""
        checar_id(fis_id)
        d = self.repo.dir
        for p in (
            d / f"{fis_id}.json",
            d / f"{fis_id}.conversa.jsonl",
            self._meta_path(fis_id),
            self.dados / "traces" / f"{fis_id}.jsonl",
        ):
            if p.exists():
                p.unlink()
        for sub in (
            self.dados / "laudos" / fis_id,
            self.dados / "evidencias" / fis_id,
            self.dados / "audio" / fis_id,
        ):
            shutil.rmtree(sub, ignore_errors=True)
        self._tirar_do_indice(fis_id)

    def _tirar_do_indice(self, fis_id: str) -> None:
        """A demo recomeçada tira do índice de documentos as linhas que a selagem anterior dela registrou: sem
        isso, a mesma NF-e/GTA da demo apareceria como "já usada" e a conciliação (e o replay) mudariam."""
        p = self.dados / "indices" / "documentos.jsonl"
        if not p.is_file():
            return
        manter = []
        for linha in p.read_text(encoding="utf-8").splitlines():
            try:
                if linha.strip() and json.loads(linha).get("fiscalizacao") == fis_id:
                    continue
            except json.JSONDecodeError:
                pass
            manter.append(linha)
        tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
        tmp.write_text("".join(x + "\n" for x in manter), encoding="utf-8")
        os.replace(tmp, p)

    def abrir_ref(self, ref_bacen: str, nova: bool = False) -> dict[str, Any]:
        """Fiscalização de uma operação real do Fiscal-GO 2026 (Sicor/BCB), pelo REF_BACEN."""
        from laudo.tools import carteira  # noqa: F401  (registra carregar_operacao)

        if not re.fullmatch(r"\d{5,12}", ref_bacen or ""):
            raise ErroServico(400, "REF_BACEN deve ter de 5 a 12 dígitos")
        if not nova:
            for f in self.listar():
                if f["ref_bacen"] == ref_bacen and f["etapa"] != "SELADO" and f.get("origem") == "sicor":
                    return self.estado(f["id"])
        ferr = REGISTRO["carregar_operacao"]
        env = ferr.funcao(ferr.entrada.model_validate({"ref_bacen": ref_bacen}))
        if not env.ok:
            raise ErroServico(404, env.error.msg if env.error else "operação não encontrada")
        op = Operacao.model_validate(env.data["operacao"])
        with self.lock:
            fis = self.cond.abrir(op)
            self._salvar_meta(
                fis.id,
                {
                    "origem": "sicor",
                    "ref_bacen": ref_bacen,
                    "triagem": (env.data or {}).get("triagem") or {},
                    "aviso": (env.data or {}).get("aviso"),
                    "criada_em": datetime.now().astimezone().isoformat(),
                },
            )
        return self.estado(fis.id)

    # -- turnos ------------------------------------------------------------------------
    def _status(self, fis: Fiscalizacao) -> dict[str, str]:
        return {c.campo: c.status for c in fis.campos.values()}

    def turno(
        self,
        fis_id: str,
        texto: str = "",
        origem: str = "texto",
        evidencia: NovaEvidencia | None = None,
        passos_llm: list[Any] | None = None,
        extra: dict[str, Any] | None = None,
        confianca_asr: float | None = None,
        residual: dict[str, str] | None = None,
        do_roteiro: bool = False,
        nome_caso: str | None = None,
    ) -> dict[str, Any]:
        texto = (texto or "").strip()[:2000]
        residual = {
            str(k)[:60]: str(v)[:80] for k, v in (residual or {}).items() if str(v or "").strip()
        } or None
        if not texto and evidencia is None and not residual:
            raise ErroServico(400, "turno vazio: envie texto, áudio, evidência ou os campos pedidos")
        with self.lock:
            fis = self.carregar(fis_id)
            antes = self._status(fis)
            residual_antes = residual_pendente(fis) is not None
            if self.roteiro_llm is not None:
                self.roteiro_llm.turno(*(passos_llm or []))
            t0 = time.perf_counter()
            r: RespostaTurno = self.cond.turno(
                fis_id,
                Evento(
                    texto=texto,
                    origem=origem,
                    evidencia=evidencia,  # type: ignore[arg-type]
                    confianca_asr=confianca_asr,
                    residual=residual,
                ),
            )
            lat = int((time.perf_counter() - t0) * 1000)
            if not do_roteiro:
                self._avancar_roteiro(fis_id, texto=texto, nome_caso=nome_caso, residual_antes=residual_antes)
            return self._resultado(fis_id, r.model_dump(mode="json"), antes, lat, extra)

    # -- ponteiro do roteiro ----------------------------------------------------------
    def _passo_atual(self, fis_id: str) -> tuple[dict[str, Any], int, casos_mod.PassoRoteiro] | None:
        m = self.meta(fis_id)
        if not m.get("caso_id"):
            return None
        try:
            caso = self.caso(m["caso_id"])
        except (FileNotFoundError, ErroServico):
            return None
        n = int(m.get("proximo_passo") or 1)
        if not 1 <= n <= len(caso.roteiro):
            return None
        return m, n, caso.roteiro[n - 1]

    def _avancar_roteiro(
        self,
        fis_id: str,
        *,
        texto: str = "",
        nome_caso: str | None = None,
        residual_antes: bool = False,
        rascunho: bool = False,
    ) -> bool:
        """Avança o ponteiro do roteiro quando o fiscal fez o passo atual por fora do botão "Executar passo":
        a fala do passo (dita ou digitada), a evidência pronta do passo, o botão "Emitir rascunho" no passo do
        pedido de laudo ou o residual completado. Devolve se avançou."""
        atual = self._passo_atual(fis_id)
        if atual is None:
            return False
        m, n, p = atual
        feito = False
        if rascunho:
            from laudo.agent.intencao import comando_humano

            cmd = comando_humano(p.fala) if p.fala else None
            feito = p.acao == "rascunho" or (
                p.acao == "turno" and not p.evidencia and bool(cmd) and cmd[0] == "emitir_rascunho"
            )
        elif p.acao == "residual":
            feito = residual_antes and residual_pendente(self.carregar(fis_id)) is None
        elif p.acao == "turno":
            if p.evidencia:
                feito = bool(nome_caso) and nome_caso == p.evidencia
            else:
                feito = bool(texto) and fala_corresponde(p.fala, texto)
        if feito:
            m["proximo_passo"] = n + 1
            self._salvar_meta(fis_id, m)
        return feito

    def pular_passo(self, fis_id: str) -> dict[str, Any]:
        """Botão "Pular passo": avança o ponteiro do roteiro sem executar o passo (nada vai ao agente)."""
        with self.lock:
            atual = self._passo_atual(fis_id)
            if atual is None:
                raise ErroServico(409, "roteiro concluído ou fiscalização sem roteiro")
            m, n, p = atual
            m["proximo_passo"] = n + 1
            m.setdefault("passos_pulados", []).append(n)
            self._salvar_meta(fis_id, m)
            estado = self.estado(fis_id)
        return {
            "resposta": None,
            "eventos": [],
            "estado": estado,
            "pulado": p.model_dump(),
            "aviso": f"Passo {n} pulado: {p.titulo}.",
        }

    def _resultado(
        self,
        fis_id: str,
        resp: dict[str, Any],
        antes: dict[str, str],
        lat: int,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        estado = self.estado(fis_id, pendencias=resp.get("pendencias"))
        eventos = visao.eventos_turno(resp, antes, estado["matriz"])
        self._ultimo[fis_id] = {"pendencias": resp.get("pendencias"), "eventos": eventos}
        return {
            "resposta": resp,
            "fala_voz": visao.fala_para_voz(resp.get("fala", "")),
            "eventos": eventos,
            "latencia_ms": lat,
            "estado": estado,
            **(extra or {}),
        }

    def passo_roteiro(self, fis_id: str, n: int | None = None) -> dict[str, Any]:
        m = self.meta(fis_id)
        cid = m.get("caso_id")
        if not cid:
            raise ErroServico(400, "esta fiscalização não tem roteiro (não é caso de demo)")
        caso = self.caso(cid)
        n = n or int(m.get("proximo_passo") or 1)
        if not 1 <= n <= len(caso.roteiro):
            raise ErroServico(409, "roteiro concluído")
        p = caso.roteiro[n - 1]
        if p.acao == "assinar":
            return {
                "passo": p.model_dump(),
                "acao_humana": "assinar",
                "estado": self.estado(fis_id),
                "eventos": [],
                "resposta": None,
            }
        if p.acao == "rascunho":
            out = self.pedir_rascunho(fis_id, do_roteiro=True)
        elif p.acao == "residual":
            out = self._passo_residual(fis_id, caso, p)
        else:
            ev = None
            if p.evidencia:
                a = caso.arquivo(p.evidencia)
                if a is None:
                    raise ErroServico(500, f"passo {n} cita evidência inexistente: {p.evidencia}")
                ev = a.nova.model_copy(deep=True)
            out = self.turno(
                fis_id, p.fala, origem="fala_fiscal", evidencia=ev, passos_llm=p.passos_llm, do_roteiro=True
            )
        m = self.meta(fis_id)
        m["proximo_passo"] = n + 1
        self._salvar_meta(fis_id, m)
        out["passo"] = p.model_dump()
        out["estado"]["roteiro"] = self._roteiro_visao(fis_id)
        return out

    def _passo_residual(
        self, fis_id: str, caso: casos_mod.CasoDemo, p: casos_mod.PassoRoteiro
    ) -> dict[str, Any]:
        """Passo "a fiscal lê no papel só o que faltou": monta a fala (dígitos da chave um a um) e os campos
        digitados (CPF/CNPJ) a partir do que está impresso no DANFE do caso, como a fiscal faria pelo
        microfone e pelo cartão "Complete a nota". Sem pedido pendente (ex.: VLM fora do ar e leitura sem
        resultado), o passo não faz nada e o roteiro segue para o XML."""
        from laudo.docs_fiscais.residual import resposta_do_papel

        pend = residual_pendente(self.carregar(fis_id))
        if pend is None or pend.pedido.tipo_documento != "danfe" or not caso.papel_danfe:
            return {
                "resposta": None,
                "eventos": [],
                "estado": self.estado(fis_id),
                "aviso": "Nenhum campo da foto pendente: passo do residual pulado.",
            }
        fala, digitado = resposta_do_papel(pend.pedido, caso.papel_danfe)
        return self.turno(
            fis_id,
            (p.fala_prefixo or "") + fala,
            origem="fala_fiscal",
            residual=digitado or None,
            do_roteiro=True,
        )

    def marcar_passo_assinado(self, fis_id: str) -> None:
        m = self.meta(fis_id)
        cid = m.get("caso_id")
        if not cid:
            return
        caso = self.caso(cid)
        n = int(m.get("proximo_passo") or 1)
        if 1 <= n <= len(caso.roteiro) and caso.roteiro[n - 1].acao == "assinar":
            m["proximo_passo"] = n + 1
            self._salvar_meta(fis_id, m)

    def evidencia_do_caso(self, fis_id: str, nome: str, texto: str = "") -> dict[str, Any]:
        m = self.meta(fis_id)
        if not m.get("caso_id"):
            raise ErroServico(400, "esta fiscalização não tem evidências de caso")
        a = self.caso(m["caso_id"]).arquivo(nome)
        if a is None:
            raise ErroServico(404, f"evidência {nome!r} não existe no caso")
        return self.turno(
            fis_id, texto, origem="texto", evidencia=a.nova.model_copy(deep=True), nome_caso=nome
        )

    def upload(
        self,
        fis_id: str,
        nome: str,
        fluxo,
        tipo: str,
        item_id: str | None = None,
        lote: str | None = None,
        texto: str = "",
        gps: dict[str, Any] | None = None,
        capturada_em: str | None = None,
        mime: str = "",
    ) -> dict[str, Any]:
        tipos = LIMITE_UPLOAD_MB
        if tipo not in tipos:
            raise ErroServico(400, f"tipo de evidência inválido: {tipo}")
        fis = self.carregar(fis_id)
        if item_id and item_id not in {i.id for i in fis.operacao.itens}:
            raise ErroServico(400, f"item {item_id} não existe na operação")
        nome_ok = nome_seguro(nome, f"{tipo}.bin")
        if nome_ok.lower().endswith((".exe", ".bat", ".cmd", ".ps1", ".sh", ".js", ".html", ".htm", ".svg")):
            raise ErroServico(400, "tipo de arquivo não aceito como evidência")
        destino = self.dados / "evidencias" / fis_id / uuid.uuid4().hex[:10] / nome_ok
        destino.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256()
        limite = tipos[tipo] * 1024 * 1024
        n = 0
        try:
            with open(destino, "wb") as f:
                while bloco := fluxo.read(1 << 20):
                    n += len(bloco)
                    if n > limite:
                        raise ErroServico(413, f"arquivo acima de {tipos[tipo]} MB")
                    h.update(bloco)
                    f.write(bloco)
        except ErroServico:
            shutil.rmtree(destino.parent, ignore_errors=True)
            raise
        if n == 0:
            shutil.rmtree(destino.parent, ignore_errors=True)
            raise ErroServico(400, "arquivo vazio")
        meta: dict[str, Any] = {
            "nome_original": nome_ok,
            "tamanho_bytes": n,
            "mime": mime[:80],
            "origem": "upload_web",
        }
        extra: dict[str, Any] | None = None
        papel = _formato_papel(destino) if tipo in _PAPEL_DE else None
        # GTA/NF-e em PDF ou imagem é o papel: vai para a leitura de foto, não para a conciliação
        if papel:
            meta |= {"tipo_documento": _PAPEL_DE[tipo], "enviado_como": tipo, "formato_arquivo": papel}
            nome_doc, nome_papel = ("GTA", "GTA") if tipo == "gta" else ("NF-e", "DANFE")
            extra = {
                "aviso": f"O arquivo enviado como {nome_doc} é {papel}: tratado como foto/scan do papel "
                f"({nome_papel}), lido pela IA e conferido pelas regras. A e-GTA é o JSON e a NF-e "
                "eletrônica é o XML."
            }
            tipo = "documento"
        g = None
        if gps and gps.get("lat") is not None and gps.get("lon") is not None:
            g = GPS(
                lat=float(gps["lat"]),
                lon=float(gps["lon"]),
                precisao_m=gps.get("precisao_m"),
                fonte="app",
                capturada_em=_dt(gps.get("capturada_em")),
                mock=gps.get("mock"),
            )
        nova = NovaEvidencia(
            tipo=tipo,
            caminho=str(destino),
            sha256=h.hexdigest(),
            gps=g,  # type: ignore[arg-type]
            capturada_em=_dt(capturada_em),
            item_id=item_id or None,
            lote=lote or None,
            meta=meta,
        )
        return self.turno(fis_id, texto, origem="texto", evidencia=nova, extra=extra)

    # -- voz ------------------------------------------------------------------------
    def turno_audio(
        self, fis_id: str, nome: str, conteudo: bytes, confirmar_numeros: bool = True
    ) -> dict[str, Any]:
        from laudo.speech.asr import ErroASR
        from laudo.speech.numeros import eh_confirmacao, normalizar

        if self.transcritor is None:
            raise ErroServico(503, "voz desligada neste modo: digite a fala")
        self.carregar(fis_id)
        if not conteudo:
            raise ErroServico(400, "áudio vazio")
        if len(conteudo) > LIMITE_AUDIO_MB * 1024 * 1024:
            raise ErroServico(413, f"áudio acima de {LIMITE_AUDIO_MB} MB")
        sha = hashlib.sha256(conteudo).hexdigest()
        ext = (Path(nome_seguro(nome, "fala.webm")).suffix or ".webm")[:6]
        pasta = self.dados / "audio" / fis_id
        pasta.mkdir(parents=True, exist_ok=True)
        arq = pasta / f"{sha[:16]}{ext}"
        arq.write_bytes(conteudo)
        try:
            with (
                otel.contexto_fiscalizacao(fis_id),
                otel.span("asr.transcrever", **{"audio.sha256": sha}) as s,
            ):
                tr = self.transcritor.transcrever(str(arq))
                otel.definir(
                    s,
                    **{
                        "asr.modelo": tr.modelo,
                        "asr.dispositivo": tr.dispositivo,
                        "asr.latencia_ms": tr.latencia_ms,
                        "asr.duracao_s": tr.duracao_audio_s,
                        "asr.confianca": tr.confianca,
                        "asr.vazio": tr.vazio,
                    },
                )
        except ErroASR as e:
            raise ErroServico(503 if e.codigo in ("MODELO_AUSENTE", "CARGA") else 400, e.msg) from e
        trd = tr.model_dump(mode="json")
        with open(pasta / "asr.jsonl", "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "em": datetime.now().astimezone().isoformat(timespec="seconds"),
                        "audio_sha256": sha,
                        "texto": mascarar(tr.texto),
                        "latencia_ms": tr.latencia_ms,
                        "dispositivo": tr.dispositivo,
                        "modelo": tr.modelo,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
        base = {"transcricao": trd, "audio_sha256": sha}
        if tr.vazio:
            return base | {
                "resposta": None,
                "aviso": f"Não entendi a fala ({tr.motivo_vazio}). Pode repetir?",
                "estado": self.estado(fis_id),
                "eventos": [],
            }
        pend = self._pendente.get(fis_id)
        if pend is not None:
            sim = eh_confirmacao(tr.texto)
            if sim is True:
                return self.confirmar(fis_id, True) | base
            if sim is False:
                self._pendente.pop(fis_id, None)
                return base | {
                    "resposta": None,
                    "aviso": "Certo, descartei. Pode repetir a fala?",
                    "fala_voz": "Certo, descartei. Pode repetir?",
                    "estado": self.estado(fis_id),
                    "eventos": [],
                }
        norm = normalizar(tr.texto)
        base["numeros"] = norm.como_dict()
        # Resposta a um pedido de residual (campos de DANFE/GTA lidos no papel): a validação determinística
        # (DV, somas) substitui a confirmação dos números; confiança baixa do ASR continua pedindo
        # confirmação.
        if residual_pendente(self.carregar(fis_id)) is not None and tr.confianca >= 0.35:
            confirmar_numeros = False
        if confirmar_numeros and (norm.precisa_confirmar or tr.confianca < 0.35):
            pergunta = norm.pedido_confirmacao() or "Não tenho certeza do que ouvi. Confirma?"
            self._pendente[fis_id] = {
                "texto": norm.texto,
                "pergunta": pergunta,
                "audio_sha256": sha,
                "confianca_asr": tr.confianca,
            }
            return base | {
                "resposta": None,
                "confirmacao": {
                    "pergunta": pergunta,
                    "texto": norm.texto,
                    "numeros": base["numeros"]["numeros"],
                },
                "fala_voz": pergunta,
                "estado": self.estado(fis_id),
                "eventos": [],
            }
        return self.turno(fis_id, norm.texto, origem="asr", extra=base, confianca_asr=tr.confianca)

    def confirmar(self, fis_id: str, aceitar: bool, texto: str | None = None) -> dict[str, Any]:
        pend = self._pendente.pop(fis_id, None)
        if not aceitar:
            return {"resposta": None, "aviso": "Descartado.", "estado": self.estado(fis_id), "eventos": []}
        final = (texto or (pend or {}).get("texto") or "").strip()
        if not final:
            raise ErroServico(409, "nada a confirmar")
        # o fiscal confirmou o que ouviu: a confiança passa a ser a dele (não volta a pedir repetição)
        return self.turno(fis_id, final, origem="asr", extra={"confirmado": True})

    def aquecer_asr(self) -> dict[str, Any]:
        if self.transcritor is None:
            raise ErroServico(503, "voz desligada neste modo")
        from laudo.speech.asr import ErroASR

        t0 = time.perf_counter()
        try:
            est_asr = self.transcritor.carregar()
        except ErroASR as e:
            raise ErroServico(503, e.msg) from e
        return {"asr": est_asr, "ms": int((time.perf_counter() - t0) * 1000)}

    def aquecer_llm(self) -> dict[str, Any]:
        """Carrega o modelo no Ollama sem passar pelo provedor (não grava nem gera span)."""
        if self.cfg.llm != "ollama":
            return {"ok": True, "aviso": f"LLM {self.cfg.llm}: nada a aquecer"}
        import httpx

        t0 = time.perf_counter()
        try:
            r = httpx.post(
                f"{self.provedor.base_url}/api/generate",  # type: ignore[union-attr]
                # mesmas opções do condutor: outro num_ctx faria o Ollama recarregar o modelo no 1º turno (15-20 s)
                json={"model": self.provedor.modelo, "prompt": "", "keep_alive": "30m",
                      "options": dict(getattr(self.provedor, "opcoes", {}))},
                timeout=120,
            )
            ok = r.status_code == 200
        except httpx.HTTPError as e:
            raise ErroServico(503, f"Ollama indisponível: {e}") from e
        return {"ok": ok, "modelo": self.provedor.modelo, "ms": int((time.perf_counter() - t0) * 1000)}

    # -- ações humanas ------------------------------------------------------------------
    def pedir_rascunho(self, fis_id: str, do_roteiro: bool = False) -> dict[str, Any]:
        """Botão "emitir rascunho": ação humana direta, autorizada pela política (pode voltar BLOQUEADO). Fora
        do roteiro, avança o ponteiro se o passo atual é o pedido de laudo."""
        with self.lock:
            fis = self.carregar(fis_id)
            antes = self._status(fis)
            t0 = time.perf_counter()
            if fis.estado_fsm == "SELADO":
                resp = RespostaTurno(
                    fiscalizacao_id=fis_id,
                    turno=0,
                    etapa=fis.estado_fsm,
                    fala="Esta fiscalização está selada; nada pode ser alterado.",
                    fala_origem="guarda",
                )
                return self._resultado(fis_id, resp.model_dump(mode="json"), antes, 0)
            with otel.contexto_fiscalizacao(fis.id), otel.span("humano.pedir_rascunho"):
                acao = self.cond.executar_acao(fis, "emitir_rascunho", {}, origem="humano")
                self.repo.salvar(fis)
            if acao.ok:
                h = (acao.dados or {}).get("hash_raiz", "")
                fala = f"Rascunho emitido (hash {h[:12]}). Confira o hash e assine; eu não assino."
            else:
                pend = (acao.dados or {}).get("pendencias") or []
                if pend:
                    faltas = "; ".join(
                        str(p.get("falta")) + (f" ({p['campo']})" if p.get("campo") else "") for p in pend[:3]
                    )
                    fala = f"Rascunho bloqueado pela política: {len(pend)} pendência(s). Falta: {faltas}."
                else:
                    fala = f"Não emiti o rascunho: {acao.resultado}"
            resp = RespostaTurno(
                fiscalizacao_id=fis_id,
                turno=0,
                etapa=fis.estado_fsm,
                fala=fala,
                fala_origem="template",
                acoes=[acao],
                pendencias=(acao.dados or {}).get("pendencias") or [],
            )
            self.repo.anexar_conversa(
                fis_id,
                {
                    "turno": "rascunho",
                    "fiscal": "(botão) Emitir rascunho do laudo",
                    "agente": fala,
                    "etapa": fis.estado_fsm,
                    "acoes": [f"emitir_rascunho:{'ok' if acao.ok else 'negado'}"],
                },
            )
            if not do_roteiro:
                self._avancar_roteiro(fis_id, rascunho=True)
            return self._resultado(
                fis_id, resp.model_dump(mode="json"), antes, int((time.perf_counter() - t0) * 1000)
            )

    def assinar(
        self,
        fis_id: str,
        pin: str,
        hash_confirmado: str,
        papel: str = "fiscal",
        nome_ref: str = "fiscal-demo",
    ) -> dict[str, Any]:
        if papel not in ("fiscal", "agronomo_responsavel", "analista_if"):
            raise ErroServico(400, "papel inválido")
        with self.lock:
            fis = self.carregar(fis_id)
            if self._pins.get(fis_id, 0) >= MAX_TENTATIVAS_PIN:
                raise ErroServico(
                    423,
                    "assinatura travada nesta fiscalização: PIN errado 5 vezes (a trava "
                    "sobrevive a reinício do servidor; na demo, use 'Recomeçar demo')",
                )
            antes = self._status(fis)
            pin_ok = hmac.compare_digest((pin or "").encode(), self.cfg.pin.encode())
            if not pin_ok:
                self._pins[fis_id] = self._pins.get(fis_id, 0) + 1
            t0 = time.perf_counter()
            try:
                r = self.cond.assinar(
                    fis_id,
                    papel=papel,
                    nome_ref=mascarar(nome_ref)[:60] or "fiscal",
                    hash_confirmado=(hash_confirmado or "").strip().lower(),
                    pin_ok=pin_ok,
                )
            except ErroSelagem as e:
                # o rascunho assinado sumiu ou foi alterado no disco: `selar` recusa antes de gravar e o
                # condutor não salva o estado; aqui vira recusa POL-03 legível (não HTTP 500)
                r = self._recusa_selagem(fis_id, str(e))
            if r.etapa == "SELADO":
                self._pins.pop(fis_id, None)
                self.marcar_passo_assinado(fis_id)
            out = self._resultado(
                fis_id, r.model_dump(mode="json"), antes, int((time.perf_counter() - t0) * 1000)
            )
            out["tentativas_restantes"] = MAX_TENTATIVAS_PIN - self._pins.get(fis_id, 0)
            return out

    def _recusa_selagem(self, fis_id: str, motivo: str) -> RespostaTurno:
        """Resposta de assinatura recusada quando `selar` não acha o rascunho assinado íntegro
        (`ErroSelagem`): nada foi selado nem gravado (nem a aprovação). Como o rascunho não pode ser refeito
        em ASSINATURA (POL-04), a saída é o arquivo voltar a ser o registrado na cadeia ou uma nova
        fiscalização."""
        fis = self.carregar(fis_id)  # o estado em disco: o condutor não salvou a tentativa
        erro = (
            f"o rascunho assinado não confere ({motivo}); nada foi selado. O arquivo do rascunho tem de ser "
            "o registrado na cadeia de evidências; se não puder ser restaurado, abra nova fiscalização "
            "(POL-04; na demo, 'Recomeçar demo')"
        )
        log.warning("selagem recusada em %s: %s", fis_id, motivo)
        with otel.contexto_fiscalizacao(fis.id):
            d = otel.registrar_decisao("POL-03", "negar", "assinar", erro, **{"policy.origem": "humano"})
        return RespostaTurno(
            fiscalizacao_id=fis.id,
            turno=0,
            etapa=fis.estado_fsm,
            fala=f"Assinatura recusada: {erro}.",
            fala_origem="guarda",
            avisos=[f"laudo não selado: {motivo}"],
            acoes=[
                AcaoExecutada(
                    acao="assinar",
                    origem="humano",
                    permitido=False,
                    rule_id="POL-03",
                    resultado=erro,
                    span_id=d,
                )
            ],
        )

    def gerar_pacote(self, fis_id: str, prazo_dias: int | None = None) -> dict[str, Any]:
        """Botão "Pacote de exibição (BCB/Justiça)": ação humana, sem LLM, só depois de SELADO
        (`tools.pacote`). Não muda o estado selado; a decisão (permitir/negar) vai para o trace."""
        from laudo.tools import pacote

        with self.lock:
            fis = self.carregar(fis_id)
            triagem = self.meta(fis_id).get("triagem") or None
            env = pacote.executar(
                fis,
                self.dados / "laudos" / fis.id,
                self.trace_arquivo(fis.id),
                triagem,
                prazo_dias or pacote.PRAZO_CONTESTACAO_DIAS,
            )
        if not env.ok:
            codigo = env.error.code if env.error else None
            status = 409 if codigo == pacote.CodigoErro.BLOQUEADO_POLITICA else 422
            raise ErroServico(status, env.error.msg if env.error else "pacote não gerado")
        d = dict(env.data or {})
        d.pop("arquivo", None)  # caminho local da máquina não vai para a tela
        return d | {"url": f"/api/fiscalizacoes/{fis.id}/pacote.zip"}

    def pacote_arquivo(self, fis_id: str) -> Path:
        from laudo.tools import pacote

        fis = self.carregar(fis_id)
        info = pacote.ultimo(self.dados / "laudos" / fis.id)
        if not info:
            raise ErroServico(404, "pacote de exibição ainda não gerado (só depois de SELADO)")
        return Path(info["arquivo"])

    def pacote_info(self, fis: Fiscalizacao) -> dict[str, Any]:
        from laudo.tools import pacote

        info = pacote.ultimo(self.dados / "laudos" / fis.id) if fis.estado_fsm == "SELADO" else None
        base = {
            "liberado": fis.estado_fsm == "SELADO",
            "regra_id": pacote.REGRA_LIBERACAO,
            "motivo": None
            if fis.estado_fsm == "SELADO"
            else "liberado só depois de SELADO (assinatura humana)",
        }
        if not info:
            return base | {"gerado": False}
        return base | {
            "gerado": True,
            "url": f"/api/fiscalizacoes/{fis.id}/pacote.zip",
            "nome": info.get("nome"),
            "sha256_zip": info.get("sha256_zip"),
            "gerado_em": info.get("gerado_em"),
            "n_arquivos": info.get("n_arquivos"),
            "checklist_ordem_jf": info.get("checklist_ordem_jf"),
            "faltas": info.get("faltas") or [],
        }

    # -- laudo e trace ----------------------------------------------------------------
    def laudo_info(self, fis: Fiscalizacao) -> dict[str, Any] | None:
        from laudo.tools import laudo as ferr_laudo

        d = self.dados / "laudos" / fis.id
        selado = d / "laudo_selado.json"
        if selado.exists():
            j = json.loads(selado.read_text(encoding="utf-8"))
            conf = self._conferencia_selo(fis, d)
            return {
                "tipo": "selado",
                "hash_raiz": j.get("hash_raiz"),
                "selo": j.get("selo"),
                "selado_em": j.get("gerado_em"),
                # o selado confere com o rascunho assinado? (laudo.audit.selo, recalculado do disco)
                "conteudo_confere": conf["valido"],
                "verificacao": conf["motivo"],
                "avisos_verificacao": conf["avisos"],
                "json_url": f"/api/fiscalizacoes/{fis.id}/laudo",
                "html_url": f"/api/fiscalizacoes/{fis.id}/laudo.html",
            }
        r = ferr_laudo.ultimo_rascunho(fis)
        if not r:
            return None
        return {
            "tipo": "rascunho",
            "hash_raiz": r.get("hash_raiz"),
            "evidencia_id": r.get("evidencia_id"),
            "json_url": f"/api/fiscalizacoes/{fis.id}/laudo",
            "html_url": f"/api/fiscalizacoes/{fis.id}/laudo.html",
            "valido_para_assinar": not any(
                e.tipo != "declaracao"
                for e in fis.evidencias[[x.id for x in fis.evidencias].index(r["evidencia_id"]) + 1 :]
            )
            if r.get("evidencia_id") in {x.id for x in fis.evidencias}
            else False,
        }

    def _conferencia_selo(self, fis: Fiscalizacao, d: Path) -> dict[str, Any]:
        """`laudo.audit.selo.verificar_em_disco` do laudo selado, guardada enquanto os arquivos e a cadeia não
        mudam (a tela consulta o estado a cada turno)."""
        from laudo.audit import selo as selo_mod

        chave = tuple(
            (p.stat().st_mtime_ns, p.stat().st_size) if p.is_file() else None
            for p in (d / "laudo_selado.json", d / "laudo_selado.html")
        ) + (len(fis.evidencias), len(fis.aprovacoes))
        guardado = self._selos.get(fis.id)
        if guardado and guardado[0] == chave:
            return guardado[1]
        try:
            r = selo_mod.verificar_em_disco(d, fis)
            conf = {"valido": r.valido, "motivo": r.motivo, "avisos": list(r.avisos)}
        except Exception as e:  # noqa: BLE001 - a tela mostra que não deu para conferir, sem cair
            conf = {
                "valido": False,
                "motivo": f"não foi possível conferir o selo: {type(e).__name__}",
                "avisos": [],
            }
        self._selos[fis.id] = (chave, conf)
        return conf

    def laudo_json(self, fis_id: str) -> dict[str, Any]:
        fis = self.carregar(fis_id)
        caminho = self._caminho_laudo(fis, ".json")
        return json.loads(caminho.read_text(encoding="utf-8"))

    def _caminho_laudo(self, fis: Fiscalizacao, ext: str) -> Path:
        from laudo.tools import laudo as ferr_laudo

        d = self.dados / "laudos" / fis.id
        if (d / f"laudo_selado{ext}").exists():
            return d / f"laudo_selado{ext}"
        r = ferr_laudo.ultimo_rascunho(fis)
        if not r:
            raise ErroServico(404, "nenhum laudo emitido ainda")
        base = Path(r.get("laudo_html") or "")
        p = base.with_suffix(ext)
        if not p.exists():
            raise ErroServico(404, "arquivo do laudo não encontrado")
        return p

    def laudo_html(self, fis_id: str) -> str:
        """HTML do laudo com os links relativos (ou file:// de laudos antigos) trocados por rotas da API."""
        from laudo.tools.laudo import href_relativo

        fis = self.carregar(fis_id)
        arq = self._caminho_laudo(fis, ".html")
        html = arq.read_text(encoding="utf-8")
        base = arq.parent
        for ev in fis.evidencias:
            if ev.caminho:
                rota = f'href="/api/fiscalizacoes/{fis.id}/evidencias/{ev.id}/arquivo"'
                rel = href_relativo(ev.caminho, base)
                if rel != "#":
                    html = html.replace(f'href="{rel}"', rota)
                try:
                    html = html.replace(f'href="{Path(ev.caminho).resolve().as_uri()}"', rota)
                except ValueError:
                    pass
        trace_p = self.dados / "traces" / f"{fis.id}.jsonl"
        for trace in {href_relativo(trace_p, base), trace_p.resolve().as_uri()} - {"#"}:
            html = html.replace(f'href="{trace}#', f'href="/api/fiscalizacoes/{fis.id}/trace?span_id=')
            html = html.replace(f'href="{trace}"', f'href="/api/fiscalizacoes/{fis.id}/trace"')
        html = re.sub(r'href="file:[^"]*"', 'href="#"', html)  # qualquer outro caminho local não vaza
        html = re.sub(r'href="(?:\.\./)+[^"]*"', 'href="#"', html)  # nem caminho relativo fora da API
        return html

    def trace_arquivo(self, fis_id: str) -> Path:
        checar_id(fis_id)
        return self.dados / "traces" / f"{fis_id}.jsonl"

    def trace(self, fis_id: str, span_id: str | None = None) -> list[dict[str, Any]]:
        spans = visao.ler_trace(self.trace_arquivo(fis_id))
        if span_id:
            return visao.spans_relacionados(spans, span_id)
        return spans

    # -- arquivos de prova ------------------------------------------------------------
    def arquivo_evidencia(self, fis_id: str, ev_id: str) -> Path:
        fis = self.carregar(fis_id)
        ev = est.evidencia_por_id(fis, checar_id(ev_id))
        if ev is None or not ev.caminho or ev.tipo not in visao.TIPOS_COM_ARQUIVO:
            raise ErroServico(404, "evidência sem arquivo")
        p = Path(ev.caminho)
        if not p.is_file():
            raise ErroServico(404, "arquivo da evidência não está neste computador")
        return p

    def quadro_chave(self, fis_id: str, chk_id: str, i: int) -> Path:
        fis = self.carregar(fis_id)
        chk = next((c for c in fis.checagens if c.id == checar_id(chk_id)), None)
        if chk is None:
            raise ErroServico(404, "checagem não encontrada")
        qs = chk.resultado.get("quadros_chave") or []
        if not 0 <= i < len(qs) or not isinstance(qs[i], dict):
            raise ErroServico(404, "quadro-chave não encontrado")
        p = Path(str(qs[i].get("caminho") or ""))
        if not p.is_file() or p.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            raise ErroServico(404, "arquivo do quadro-chave ausente")
        return p

    def trecho(self, fis_id: str, ev_id: str) -> dict[str, Any]:
        """Trecho legível da NF-e (produtos, data, número) ou da GTA (sem dados pessoais)."""
        p = self.arquivo_evidencia(fis_id, ev_id)
        if p.stat().st_size > 2 * 1024 * 1024:
            raise ErroServico(413, "documento grande demais para o trecho")
        if p.suffix.lower() == ".xml":
            return _trecho_nfe(p.read_bytes())
        if p.suffix.lower() == ".json":
            try:
                g = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                raise ErroServico(400, f"JSON inválido: {e}") from e
            campos = [
                ("Número", g.get("numero")),
                ("Espécie", g.get("especie")),
                ("Total", g.get("total")),
                ("Finalidade", g.get("finalidade")),
                ("Origem (município)", (g.get("origem") or {}).get("municipio_nome")),
                ("Destino (município)", (g.get("destino") or {}).get("municipio_nome")),
                ("Emissão", (g.get("emissao") or {}).get("data")),
                ("Validade", (g.get("emissao") or {}).get("validade")),
                ("NF-e vinculadas", len(g.get("nfe_chaves") or [])),
            ]
            return {
                "tipo": "gta",
                "campos": [{"rotulo": a, "valor": mascarar(str(b))} for a, b in campos if b is not None],
            }
        return {"tipo": "outro", "campos": [{"rotulo": "Arquivo", "valor": p.name}]}

    # -- estado para a interface ---------------------------------------------------------
    def _roteiro_visao(self, fis_id: str) -> dict[str, Any] | None:
        m = self.meta(fis_id)
        if not m.get("caso_id"):
            return None
        caso = self.caso(m["caso_id"])
        prox = int(m.get("proximo_passo") or 1)
        return {
            "caso_id": caso.id,
            "titulo": caso.titulo,
            "proximo": prox,
            "total": len(caso.roteiro),
            "passos": [p.model_dump() for p in caso.roteiro],
            "arquivos": [a.model_dump(exclude={"nova"}) for a in caso.arquivos],
        }

    def estado(self, fis_id: str, pendencias: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        fis = self.carregar(fis_id)
        m = self.meta(fis_id)
        linhas = visao.matriz(fis)
        evs = [visao.evidencia_visao(fis.id, e) for e in fis.evidencias]
        chks = [visao.checagem_visao(fis, c) for c in fis.checagens]
        spans = visao.ler_trace(self.trace_arquivo(fis_id))
        if pendencias is None:
            pendencias = (self._ultimo.get(fis_id) or {}).get("pendencias")
        op = fis.operacao
        conversa = self.repo.ler_conversa(fis_id)
        return {
            "id": fis.id,
            "etapa": fis.estado_fsm,
            "etapas": [{"id": e, "rotulo": visao.ROTULO_ETAPA[e]} for e in visao.ETAPAS],
            "metodo": fis.metodo,
            "metodo_rotulo": rotulo_metodo(fis.metodo) if fis.metodo else None,
            "rulebook": fis.rulebook_versao,
            "operacao": {
                **{k: v for k, v in op.model_dump(mode="json").items() if k not in ("glebas_wkt", "itens")},
                "itens": [i.model_dump(mode="json") for i in op.itens],
                "glebas": visao.glebas_coords(op.glebas_wkt),
                "valor_fmt": f"R$ {visao.fmt_num(op.valor_rs)}" if op.valor_rs else "—",
            },
            "triagem": m.get("triagem") or {},
            # abertura "por que caiu na amostra": cada motivo com código, pontos e critério de
            # laudo.geo.triagem
            "amostra": por_que_na_amostra(m.get("triagem") or {}),
            "pacote": self.pacote_info(fis),
            "origem": m.get("origem"),
            # operação sintética (demo ou golden set): a tela mostra a marca d'água e o aviso
            "demonstracao": demonstracao.bloco_laudo(op),
            "matriz": linhas,
            "contagem": visao.contagem_status(linhas),
            "pendencias": mascarar_obj(pendencias) if pendencias is not None else None,
            "evidencias": [e for e in evs if e["tipo"] not in ("declaracao", "ocorrencia")],
            "falas": [e for e in evs if e["tipo"] == "declaracao"],
            "checagens": chks,
            "ocorrencias": [o.model_dump(mode="json") for o in fis.ocorrencias],
            "alegacoes": fis.alegacoes,
            "conversa": conversa[-60:],
            "governanca": visao.governanca(spans),
            "n_spans": len(spans),
            "laudo": self.laudo_info(fis),
            "assinaturas": [a.model_dump(mode="json") for a in fis.aprovacoes],
            "roteiro": self._roteiro_visao(fis_id),
            "confirmacao_pendente": self._pendente.get(fis_id),
            "residual": (rp.para_interface() if (rp := residual_pendente(fis)) else None),
            "ultimos_eventos": (self._ultimo.get(fis_id) or {}).get("eventos") or [],
            "trace_url": f"/api/fiscalizacoes/{fis.id}/trace",
        }


class _NoMeta:
    """Valor por fiscalização guardado num campo do meta da interface: a mesma interface de um dict (`get`,
    `pop`, atribuição), mas em disco, para sobreviver a reinício do servidor."""

    def __init__(self, srv: Servico, campo: str):
        self.srv, self.campo = srv, campo

    def get(self, fis_id: str, padrao: Any = None) -> Any:
        return self.srv.meta(fis_id).get(self.campo, padrao)

    def __setitem__(self, fis_id: str, valor: Any) -> None:
        m = self.srv.meta(fis_id)
        m[self.campo] = valor
        self.srv._salvar_meta(fis_id, m)

    def pop(self, fis_id: str, padrao: Any = None) -> Any:
        m = self.srv.meta(fis_id)
        if self.campo not in m:
            return padrao
        valor = m.pop(self.campo)
        self.srv._salvar_meta(fis_id, m)
        return valor


def _dt(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v))
    except ValueError:
        return None


def _formato_papel(caminho: Path) -> str | None:
    """ "PDF", "JPEG" ou "PNG" se o arquivo começa com a assinatura desses formatos; None senão."""
    with open(caminho, "rb") as f:
        cab = f.read(8)
    return next((nome for assinatura, nome in _ASSINATURA_PAPEL if cab.startswith(assinatura)), None)


def _normalizar_fala(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(re.findall(r"[a-z0-9]+", t))


def fala_corresponde(fala_passo: str, texto: str, limiar: float = 0.8) -> bool:
    """A fala dita (ASR, já com os números em dígitos) ou digitada é a fala do passo do roteiro? Compara sem
    acento, caixa e pontuação; tolera a diferença miúda da transcrição (razão de semelhança >= `limiar`)."""
    a, b = _normalizar_fala(fala_passo), _normalizar_fala(texto)
    if not a or not b:
        return False
    return a == b or difflib.SequenceMatcher(None, a, b).ratio() >= limiar


def _trecho_nfe(conteudo: bytes) -> dict[str, Any]:
    from lxml import etree

    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, remove_comments=True)
    try:
        raiz = etree.fromstring(conteudo, parser)
    except etree.XMLSyntaxError as e:
        raise ErroServico(400, f"XML inválido: {e}") from e

    def achar(xpath: str) -> list:
        return raiz.xpath(xpath)

    def txt(xpath: str) -> str | None:
        r = achar(f"{xpath}/text()")
        return str(r[0]) if r else None

    ln = "*[local-name()='{}']"
    campos = [
        ("Número", txt(f"//{ln.format('ide')}/{ln.format('nNF')}")),
        ("Emissão", txt(f"//{ln.format('ide')}/{ln.format('dhEmi')}")),
        ("Natureza da operação", txt(f"//{ln.format('ide')}/{ln.format('natOp')}")),
        ("UF do emitente", txt(f"//{ln.format('emit')}//{ln.format('UF')}")),
        ("Protocolo de autorização", txt(f"//{ln.format('protNFe')}//{ln.format('nProt')}")),
        ("Valor total", txt(f"//{ln.format('ICMSTot')}/{ln.format('vNF')}")),
    ]
    produtos = []
    for prod in achar(f"//{ln.format('det')}/{ln.format('prod')}")[:10]:

        def c(nome: str, p=prod) -> str | None:
            r = p.xpath(f"{ln.format(nome)}/text()")
            return str(r[0]) if r else None

        produtos.append(
            {
                "descricao": c("xProd"),
                "ncm": c("NCM"),
                "cfop": c("CFOP"),
                "unidade": c("uCom"),
                "quantidade": c("qCom"),
                "valor_unitario": c("vUnCom"),
                "valor": c("vProd"),
            }
        )
    trecho = ""
    det = achar(f"//{ln.format('det')}")
    if det:
        trecho = etree.tostring(det[0], pretty_print=True, encoding="unicode")[:2500]
    return {
        "tipo": "nfe",
        "campos": [{"rotulo": a, "valor": mascarar(b)} for a, b in campos if b],
        "produtos": mascarar_obj(produtos),
        "xml": mascarar(re.sub(r'\sxmlns(:\w+)?="[^"]*"', "", trecho)),
    }
