"""ASR local em pt-BR com faster-whisper (modelo `Systran/faster-whisper-large-v3`, já em cache; outro modelo do
cache por `LAUDO_ASR_MODELO`, como o `medium` da demo pública em CPU).

- **Sem download**: o modelo vem só do cache local do Hugging Face (`local_files_only`); se não houver,
  `ErroASR("MODELO_AUSENTE")` (a interface cai para texto digitado).
- **GPU primeiro**: tenta CUDA `float16`; se o CTranslate2 não achar cuBLAS/cuDNN ou faltar VRAM, cai para
  CPU `int8` (mais lento, ~1,6 GB de RAM). O aquecimento roda um passo do codificador para pegar o erro na
  carga, e não na primeira fala do fiscal.
- **VAD** (Silero, embutido no faster-whisper, CPU): áudio sem fala volta como transcrição vazia sem passar
  pelo Whisper (evita "alucinação" em silêncio, como "Legendas pela comunidade Amara.org").
- Idioma fixo `pt` e um prompt inicial com o vocabulário do domínio (cabeças, garrotes, GTA, NF-e...).
- Um modelo por processo (`transcritor_padrao()`), carregado sob demanda e protegido por lock.

O áudio do navegador chega em webm/ogg (Opus), mp4/aac (Safari) ou wav; o PyAV decodifica todos.
"""

from __future__ import annotations

import io
import logging
import math
import os
import threading
import time
from pathlib import Path
from typing import Any, BinaryIO

import numpy as np
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

# O CTranslate2 traz o OpenMP da Intel (libiomp5md.dll) e o conda-forge carrega o da LLVM (libomp.dll,
# via numpy/onnxruntime). Sem esta variável o processo aborta com "OMP: Error #15" na primeira transcrição.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

MODELO_PADRAO = "Systran/faster-whisper-large-v3"
# Outro modelo do cache local (ex.: "Systran/faster-whisper-medium" na demo pública em CPU, Dockerfile.publico)
ENV_MODELO = "LAUDO_ASR_MODELO"
TAXA = 16000
PROMPT_DOMINIO = (
    "Fiscalização de crédito rural em Goiás. Contei 42 cabeças no curral: garrotes, novilhas, bezerros. "
    "A cerca nova tem 800 metros. Nota fiscal, NF-e, GTA, laudo, rascunho, assinatura, gleba, hectares."
)
# Frases típicas de alucinação do Whisper em silêncio/ruído (comparação sem acento e minúscula).
_ALUCINACOES = (
    "legendas pela comunidade amara.org",
    "obrigado por assistir",
    "inscreva-se no canal",
    "legenda adriana zanotto",
    "transcricao e legendas",
)


class ErroASR(Exception):
    """Falha do ASR. `codigo` ∈ {MODELO_AUSENTE, CARGA, AUDIO_INVALIDO, DESLIGADO}."""

    def __init__(self, codigo: str, msg: str):
        super().__init__(f"{codigo}: {msg}")
        self.codigo = codigo
        self.msg = msg


class Segmento(BaseModel):
    inicio: float
    fim: float
    texto: str
    avg_logprob: float
    no_speech_prob: float


class Transcricao(BaseModel):
    texto: str
    idioma: str = "pt"
    prob_idioma: float = 1.0
    duracao_audio_s: float = 0.0
    duracao_fala_s: float = 0.0  # depois do VAD
    latencia_ms: int = 0  # decodificação + VAD + Whisper (sem a carga do modelo)
    rtf: float | None = None  # latência / duração do áudio
    confianca: float = 0.0  # exp(média de avg_logprob), 0–1
    vazio: bool = False
    motivo_vazio: str = ""
    modelo: str = MODELO_PADRAO
    dispositivo: str = ""
    compute_type: str = ""
    segmentos: list[Segmento] = Field(default_factory=list)


def modelo_configurado() -> str:
    """Modelo do Whisper: `LAUDO_ASR_MODELO` (id do Hugging Face ou pasta com model.bin) ou o large-v3."""
    return (os.environ.get(ENV_MODELO) or "").strip() or MODELO_PADRAO


def localizar_modelo(repo_id: str = MODELO_PADRAO) -> Path:
    """Pasta do modelo no cache local do Hugging Face (nunca baixa)."""
    p = Path(repo_id)
    if p.is_dir() and (p / "model.bin").exists():
        return p
    # 1) procura direta no cache (o snapshot pode estar "incompleto" para o hub — sem README —, mas o
    #    model.bin, o config e o tokenizer bastam)
    hub = os.environ.get("HF_HUB_CACHE") or (
        Path(os.environ["HF_HOME"]) / "hub"
        if os.environ.get("HF_HOME")
        else Path.home() / ".cache" / "huggingface" / "hub"
    )
    snaps = Path(hub) / f"models--{repo_id.replace('/', '--')}" / "snapshots"
    if snaps.is_dir():
        candidatos = sorted(
            (d for d in snaps.iterdir() if (d / "model.bin").exists()),
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )
        if candidatos:
            return candidatos[0]
    # 2) API do hub, sem rede
    try:
        from huggingface_hub import snapshot_download

        pasta = Path(snapshot_download(repo_id, local_files_only=True))
    except Exception as e:
        raise ErroASR("MODELO_AUSENTE", f"{repo_id} não está no cache local ({type(e).__name__})") from e
    if not (pasta / "model.bin").exists():
        raise ErroASR("MODELO_AUSENTE", f"{pasta} sem model.bin")
    return pasta


_DLLS_PREPARADAS: list[str] = []


def preparar_dlls_cuda() -> list[str]:
    """Windows: o CTranslate2 procura cublas64_12.dll no PATH. Sem CUDA Toolkit instalado, usamos as DLLs
    de runtime que já estão na máquina — `LAUDO_CUDA_DLL_DIR` (separadas por `;`) ou as que o Ollama traz em
    `lib/ollama/cuda_v12`. Nada é baixado nem instalado. Devolve as pastas acrescentadas."""
    if os.name != "nt" or _DLLS_PREPARADAS:
        return list(_DLLS_PREPARADAS)
    candidatos = [p for p in os.environ.get("LAUDO_CUDA_DLL_DIR", "").split(os.pathsep) if p]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidatos.append(str(Path(local) / "Programs" / "Ollama" / "lib" / "ollama" / "cuda_v12"))
    for d in candidatos:
        if (Path(d) / "cublas64_12.dll").exists():
            try:
                os.add_dll_directory(d)
            except OSError:
                continue
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
            _DLLS_PREPARADAS.append(d)
            break
    return list(_DLLS_PREPARADAS)


def decodificar(audio: str | Path | bytes | BinaryIO | np.ndarray) -> np.ndarray:
    """Áudio qualquer (arquivo, bytes, ndarray float32 16 kHz) → ndarray float32 mono 16 kHz."""
    if isinstance(audio, np.ndarray):
        return audio.astype(np.float32, copy=False)
    from faster_whisper.audio import decode_audio

    fonte: Any = io.BytesIO(audio) if isinstance(audio, (bytes, bytearray)) else audio
    if isinstance(fonte, Path):
        fonte = str(fonte)
    try:
        x = decode_audio(fonte, sampling_rate=TAXA)
    except Exception as e:
        raise ErroASR("AUDIO_INVALIDO", f"não consegui decodificar o áudio ({type(e).__name__}: {e})") from e
    return np.asarray(x, dtype=np.float32)


def trechos_de_fala(x: np.ndarray, min_silencio_ms: int = 500) -> list[dict[str, int]]:
    """VAD Silero (onnx, CPU): trechos com fala em amostras ({start, end})."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    if x.size == 0:
        return []
    return list(get_speech_timestamps(x, VadOptions(min_silence_duration_ms=min_silencio_ms)))


def _sem_acento(t: str) -> str:
    import unicodedata

    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode("ascii").lower()


class TranscritorWhisper:
    """faster-whisper com carga preguiçosa, GPU→CPU, VAD e idioma pt."""

    def __init__(
        self,
        modelo: str | None = None,  # None: `LAUDO_ASR_MODELO` ou o large-v3 (modelo_configurado)
        dispositivo: str = "auto",  # auto | cuda | cpu
        compute_type: str | None = None,
        idioma: str = "pt",
        beam_size: int = 5,
        prompt: str | None = PROMPT_DOMINIO,
        cpu_threads: int = 4,
        vad: bool = True,
    ):
        self.modelo_id = modelo or modelo_configurado()
        self.dispositivo_pedido = dispositivo
        self.compute_type_pedido = compute_type
        self.idioma = idioma
        self.beam_size = beam_size
        self.prompt = prompt
        self.cpu_threads = cpu_threads
        self.vad = vad
        self._modelo = None
        self._lock = threading.Lock()
        self.dispositivo = ""
        self.compute_type = ""
        self.carga_s: float | None = None
        self.erro_gpu: str = ""
        self.erro_carga: str = ""
        self.dlls_cuda: list[str] = []

    # -- carga ---------------------------------------------------------------
    @property
    def carregado(self) -> bool:
        return self._modelo is not None

    def _tentativas(self) -> list[tuple[str, str]]:
        if self.dispositivo_pedido == "cpu":
            return [("cpu", self.compute_type_pedido or "int8")]
        if self.dispositivo_pedido == "cuda":
            return [("cuda", self.compute_type_pedido or "float16")]
        return [("cuda", self.compute_type_pedido or "float16"), ("cpu", "int8")]

    def carregar(self) -> dict[str, Any]:
        with self._lock:
            if self._modelo is None:
                self._carregar()
        return self.estado()

    def _carregar(self) -> None:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        from faster_whisper import WhisperModel

        pasta = localizar_modelo(self.modelo_id)
        erros = []
        for disp, ct in self._tentativas():
            if disp == "cuda":
                self.dlls_cuda = preparar_dlls_cuda()
                try:
                    import ctranslate2

                    if ctranslate2.get_cuda_device_count() == 0:
                        erros.append("cuda: nenhuma GPU visível")
                        continue
                except Exception as e:  # noqa: BLE001
                    erros.append(f"cuda: {e}")
                    continue
            t0 = time.perf_counter()
            try:
                m = WhisperModel(
                    str(pasta),
                    device=disp,
                    compute_type=ct,
                    cpu_threads=self.cpu_threads,
                    local_files_only=True,
                )
                # aquecimento: um passo do codificador acusa DLL de CUDA ausente já na carga
                segs, _ = m.transcribe(
                    np.zeros(TAXA // 2, dtype=np.float32),
                    language=self.idioma,
                    beam_size=1,
                    vad_filter=False,
                    without_timestamps=True,
                )
                list(segs)
            except Exception as e:  # noqa: BLE001 - qualquer falha → próxima tentativa
                erros.append(f"{disp}/{ct}: {type(e).__name__}: {str(e)[:200]}")
                log.warning("ASR: falha ao carregar em %s/%s: %s", disp, ct, e)
                continue
            self._modelo = m
            self.dispositivo, self.compute_type = disp, ct
            self.carga_s = round(time.perf_counter() - t0, 2)
            self.erro_gpu = "; ".join(x for x in erros if x.startswith("cuda"))
            log.info("ASR carregado em %s/%s (%.1f s)", disp, ct, self.carga_s)
            return
        self.erro_carga = "; ".join(erros)
        raise ErroASR("CARGA", self.erro_carga or "nenhuma tentativa de carga")

    def descarregar(self) -> None:
        with self._lock:
            self._modelo = None
            import gc

            gc.collect()

    def estado(self) -> dict[str, Any]:
        return {
            "modelo": self.modelo_id,
            "carregado": self.carregado,
            "dispositivo": self.dispositivo,
            "compute_type": self.compute_type,
            "carga_s": self.carga_s,
            "erro_gpu": self.erro_gpu,
            "erro_carga": self.erro_carga,
            "dlls_cuda": self.dlls_cuda,
            "idioma": self.idioma,
            "vad": self.vad,
        }

    # -- transcrição -----------------------------------------------------------
    def transcrever(self, audio: str | Path | bytes | BinaryIO | np.ndarray) -> Transcricao:
        t0 = time.perf_counter()
        x = decodificar(audio)
        dur = x.size / TAXA
        base = {"duracao_audio_s": round(dur, 2), "modelo": self.modelo_id}
        if dur < 0.2:
            return self._vazio(base, t0, "áudio curto demais")
        if self.vad and not trechos_de_fala(x):
            return self._vazio(base, t0, "nenhuma fala detectada (VAD)")
        if not self.carregado:
            self.carregar()
        with self._lock:
            segs, info = self._modelo.transcribe(  # type: ignore[union-attr]
                x,
                language=self.idioma,
                beam_size=self.beam_size,
                vad_filter=self.vad,
                vad_parameters={"min_silence_duration_ms": 500},
                initial_prompt=self.prompt,
                condition_on_previous_text=False,
                temperature=[0.0, 0.2, 0.4],
            )
            segmentos = [
                Segmento(
                    inicio=round(s.start, 2),
                    fim=round(s.end, 2),
                    texto=s.text.strip(),
                    avg_logprob=round(s.avg_logprob, 3),
                    no_speech_prob=round(s.no_speech_prob, 3),
                )
                for s in segs
            ]
        uteis = [s for s in segmentos if s.texto and not (s.no_speech_prob > 0.8 and s.avg_logprob < -1.0)]
        texto = " ".join(s.texto for s in uteis).strip()
        if texto and any(a in _sem_acento(texto) for a in _ALUCINACOES):
            texto, uteis = "", []
        lat = int((time.perf_counter() - t0) * 1000)
        conf = math.exp(sum(s.avg_logprob for s in uteis) / len(uteis)) if uteis else 0.0
        return Transcricao(
            texto=texto,
            idioma=info.language,
            prob_idioma=round(float(info.language_probability), 3),
            duracao_audio_s=round(dur, 2),
            duracao_fala_s=round(float(getattr(info, "duration_after_vad", dur) or 0.0), 2),
            latencia_ms=lat,
            rtf=round(lat / 1000 / dur, 3) if dur else None,
            confianca=round(min(max(conf, 0.0), 1.0), 3),
            vazio=not texto,
            motivo_vazio="" if texto else "Whisper não reconheceu fala",
            modelo=self.modelo_id,
            dispositivo=self.dispositivo,
            compute_type=self.compute_type,
            segmentos=segmentos,
        )

    def _vazio(self, base: dict[str, Any], t0: float, motivo: str) -> Transcricao:
        return Transcricao(
            texto="",
            vazio=True,
            motivo_vazio=motivo,
            latencia_ms=int((time.perf_counter() - t0) * 1000),
            dispositivo=self.dispositivo,
            compute_type=self.compute_type,
            **base,
        )


_PADRAO: dict[str, TranscritorWhisper | None] = {"t": None}
_LOCK_PADRAO = threading.Lock()


def transcritor_padrao(**kw: Any) -> TranscritorWhisper:
    """Um transcritor por processo (o modelo de 3 GB não pode ser carregado duas vezes)."""
    with _LOCK_PADRAO:
        if _PADRAO["t"] is None:
            _PADRAO["t"] = TranscritorWhisper(**kw)
        return _PADRAO["t"]  # type: ignore[return-value]
