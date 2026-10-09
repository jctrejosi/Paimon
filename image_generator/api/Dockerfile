# syntax=docker/dockerfile:1

# API de generación de imágenes (fachada sobre ComfyUI y proveedores externos).
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OUTPUT_DIR=/data/outputs

WORKDIR /srv/api

COPY requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY app ./app
COPY workflows ./workflows

RUN mkdir -p /data/outputs

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
