# syntax=docker/dockerfile:1

# Servicio RAG de Paimon: ingesta, embeddings y búsqueda semántica.
# Python 3.12 (wheels de onnxruntime/fastembed probados).
FROM python:3.12-slim

# onnxruntime (fastembed) usa OpenMP.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FASTEMBED_CACHE_DIR=/models \
    UPLOAD_DIR=/data/uploads

WORKDIR /srv/api

COPY api/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

# Código de la API (models/ y uploads/ se montan como volúmenes).
COPY api/app ./app

ARG PUID=1001
ARG PGID=1001
RUN mkdir -p /models /data/uploads && chown -R ${PUID}:${PGID} /srv/api /models /data

USER ${PUID}:${PGID}

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
