# syntax=docker/dockerfile:1
# Imagem da demo do Laudo Vivo: interface web em replay na porta 8000, sem GPU e sem LLM ao vivo. A mesma
# imagem roda a demo da linha de comando, os testes e a conferência do laudo de exemplo (docker-compose.yml).
#
#   docker compose up --build demo                       # http://127.0.0.1:8000
#   docker build -t laudo-vivo:demo . && docker run --rm -p 127.0.0.1:8000:8000 laudo-vivo:demo
#
# O ambiente vem do conda-forge (environment.yml). No build, scripts/preparar_demo.py copia os ativos
# versionados da demo (vídeo semissintético e série Sentinel-2 da gleba) e baixa o detector YOLOX da
# release oficial, com sha256 conferido. Depois do build, nada precisa de rede (o mapa usa os tiles do
# OpenStreetMap só se houver internet). Tempos e problemas comuns: docs/COMO_RODAR.md.
FROM mambaorg/micromamba:2.9.0-debian12-slim

# ativa o ambiente base nos RUN abaixo (convenção da imagem mambaorg/micromamba)
ARG MAMBA_DOCKERFILE_ACTIVATE=1

COPY --chown=$MAMBA_USER:$MAMBA_USER environment.yml /tmp/environment.yml
RUN micromamba install --yes --name base --file /tmp/environment.yml \
    && micromamba clean --all --yes

# Voz (ASR local): faster-whisper e ctranslate2 só existem no PyPI. É opcional: sem eles a imagem roda a demo
# em replay normalmente e só os 5 testes de tests/unit/test_voz_asr.py falham. COM_VOZ=0 pula este passo.
ARG COM_VOZ=1
RUN if [ "$COM_VOZ" = "1" ]; then \
      python -m pip install --no-cache-dir --retries 1 --timeout 20 "faster-whisper>=1.1" \
      || echo "AVISO: faster-whisper não instalado (PyPI inacessível?); a demo em replay não depende dele"; \
    fi

USER root
RUN mkdir -p /app && chown "$MAMBA_USER:$MAMBA_USER" /app
USER $MAMBA_USER
WORKDIR /app

ENV PYTHONPATH=/app/src \
    PYTHONUTF8=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --chown=$MAMBA_USER:$MAMBA_USER . /app
RUN python scripts/preparar_demo.py

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=6 \
    CMD ["/opt/conda/bin/python", "-c", \
         "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/saude')"]

# O mesmo que scripts/rodar_demo.sh --replay: caso DEMO-0001, ferramentas reais, perfil campo, LLM e leitura
# do papel vindos da gravação, fala digitada. --host 0.0.0.0 só dentro do contêiner; o compose publica a porta
# apenas em 127.0.0.1.
CMD ["python", "-m", "laudo.api", "--host", "0.0.0.0", "--porta", "8000", "--caso", "DEMO-0001", \
     "--ferramentas", "reais", "--perfil", "campo", "--llm", "replay", "--asr", "desligado"]
