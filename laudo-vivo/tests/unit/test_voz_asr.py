"""ASR local (laudo.speech.asr): decodificação, VAD, falhas sem modelo e, no modo lento, o Whisper real.

A fixture `dados_voz/fala_contagem_sapi.wav` é fala sintética (voz pt-BR do Windows, SAPI), sem dado pessoal:
"Cheguei na fazenda. Contei quarenta e duas cabeças no curral, e a cerca nova tem uns oitocentos metros."

Decodificação e VAD usam o faster-whisper (PyAV e Silero): sem ele instalado (ex.: o pip do faster-whisper falhou
no Docker, que tolera a falha), esses testes são pulados em vez de falhar.
"""

import io
import os
import wave
from pathlib import Path

import numpy as np
import pytest

from laudo.speech import asr
from laudo.speech.numeros import normalizar

WAV = Path(__file__).parent / "dados_voz" / "fala_contagem_sapi.wav"


def _exigir_faster_whisper():
    """Pula o teste sem o faster-whisper (decodificação por PyAV e VAD Silero vêm dele)."""
    return pytest.importorskip("faster_whisper", reason="faster-whisper não instalado (decodificação/VAD)")


@pytest.fixture
def faster_whisper():
    return _exigir_faster_whisper()


def _wav_bytes(x: np.ndarray, taxa: int = 16000) -> bytes:
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return b.getvalue()


def test_decodifica_wav_em_16k_mono(faster_whisper):
    x = asr.decodificar(WAV)
    assert x.dtype == np.float32 and 9.5 < x.size / asr.TAXA < 10.5


def test_decodifica_bytes_de_outra_taxa(faster_whisper):
    t = np.linspace(0, 1, 8000, endpoint=False)
    x = asr.decodificar(_wav_bytes(0.3 * np.sin(2 * np.pi * 440 * t), taxa=8000))
    assert abs(x.size - 16000) < 200  # reamostrado para 16 kHz


def test_audio_invalido_vira_erro_asr(faster_whisper):
    with pytest.raises(asr.ErroASR) as e:
        asr.decodificar(b"isto nao e audio")
    assert e.value.codigo == "AUDIO_INVALIDO"


def test_vad_acha_fala_e_ignora_silencio(faster_whisper):
    assert asr.trechos_de_fala(asr.decodificar(WAV))
    assert asr.trechos_de_fala(np.zeros(asr.TAXA * 2, dtype=np.float32)) == []


def test_silencio_volta_vazio_sem_carregar_o_modelo(faster_whisper):
    t = asr.TranscritorWhisper(modelo="nao/existe")  # se tentasse carregar, falharia
    r = t.transcrever(np.zeros(asr.TAXA * 2, dtype=np.float32))
    assert r.vazio and "VAD" in r.motivo_vazio and not t.carregado


def test_modelo_ausente_nao_baixa_nada(tmp_path, monkeypatch):
    pytest.importorskip("huggingface_hub", reason="huggingface_hub não instalado (vem com o faster-whisper)")
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    with pytest.raises(asr.ErroASR) as e:
        asr.localizar_modelo("Systran/modelo-que-nao-existe")
    assert e.value.codigo == "MODELO_AUSENTE"


def test_sem_faster_whisper_os_testes_de_decodificacao_sao_pulados(monkeypatch):
    """P3-15: num ambiente sem o faster-whisper, a fixture pula (skipped), não falha com ImportError."""
    import sys

    monkeypatch.setitem(sys.modules, "faster_whisper", None)  # import passa a levantar ImportError
    with pytest.raises(pytest.skip.Exception, match="faster-whisper"):
        _exigir_faster_whisper()


def test_ordem_de_tentativas_gpu_depois_cpu():
    assert asr.TranscritorWhisper()._tentativas() == [("cuda", "float16"), ("cpu", "int8")]
    assert asr.TranscritorWhisper(dispositivo="cpu")._tentativas() == [("cpu", "int8")]


@pytest.mark.lento
def test_whisper_real_transcreve_numeros(request):
    """Carrega o large-v3 do cache (GPU float16, ou CPU int8). Rode com -m lento ou LAUDO_LENTO=1."""
    if "lento" not in (request.config.getoption("markexpr") or "") and not os.environ.get("LAUDO_LENTO"):
        pytest.skip("teste lento: rode com -m lento ou LAUDO_LENTO=1")
    try:
        asr.localizar_modelo()
    except asr.ErroASR:
        pytest.skip("modelo faster-whisper-large-v3 não está no cache")
    t = asr.TranscritorWhisper()
    r = t.transcrever(WAV)
    n = normalizar(r.texto)
    assert "42 cabeças" in n.texto and "800 metros" in n.texto, r.texto
    assert n.pedido_confirmacao() == "Entendi 42 cabeças e 800 metros. Confirma?"
    assert r.dispositivo in ("cuda", "cpu") and r.latencia_ms > 0
    t.descarregar()
