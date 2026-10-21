# syntax=docker/dockerfile:1

# Servicio de procesamiento de imágenes de Paimon (quita-fondo con rembg).
# Python 3.12: wheels de onnxruntime más probados que en 3.13.
FROM python:3.12-slim

# onnxruntime usa OpenMP (libgomp); no hace falta OpenCV ni GL.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    U2NET_HOME=/models

WORKDIR /srv/api

COPY api/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

# Código de la API (models/ y .env se montan/ignoran, no se hornean).
COPY api/app ./app

# El contenedor corre con el UID del host; darle dueño de /srv/api.
ARG PUID=1001
ARG PGID=1001
RUN chown -R ${PUID}:${PGID} /srv/api

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
