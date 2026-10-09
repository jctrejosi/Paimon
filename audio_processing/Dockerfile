# syntax=docker/dockerfile:1

# Imagen del servicio de transcripción de audio de Paimon.
# Python 3.12 (no 3.13): wheels binarios de ctranslate2/onnxruntime más probados.
FROM python:3.12-slim

# --- Sistema: ffmpeg (decodificación robusta de formatos de audio) ---
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencias: por defecto la base (transcripción + cadena mínima).
# Para incluir los módulos opcionales pesados:
#   docker build --build-arg PIP_EXTRAS=requirements-extras.txt .
ARG PIP_EXTRAS=requirements.txt
COPY api/requirements.txt api/requirements-extras.txt ./
RUN pip install -r "${PIP_EXTRAS}"

# Código de la API (models/ se monta como volumen).
COPY api/ ./

# El contenedor corre con el UID del host; darle dueño de /app.
ARG PUID=1001
ARG PGID=1001
RUN chown -R ${PUID}:${PGID} /app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
