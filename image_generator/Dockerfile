# syntax=docker/dockerfile:1

# Imagen de ComfyUI para Paimon (generador de imágenes).
# Build CPU (la máquina no tiene GPU NVIDIA; la Vega integrada no soporta ROCm).
FROM python:3.13-slim

# --- Sistema: libs para Pillow / PyOpenGL / av, y utilidades ---
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# PyTorch CPU primero, para fijar el índice y no bajar un build CUDA inútil.
RUN pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

# Resto de dependencias (torch/torchvision ya quedan satisfechas).
COPY ComfyUI/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

# Código de ComfyUI (models/input/output/temp/user se montan como volúmenes).
COPY ComfyUI/ ./

# El contenedor corre con el UID del host; darle dueño de /app para que pueda
# crear/eliminar entradas (p. ej. limpiar /app/temp) sin ser root.
ARG PUID=1001
ARG PGID=1001
RUN chown -R ${PUID}:${PGID} /app

EXPOSE 8188

# --cpu: sin GPU en esta máquina. Cambiar por flags de GPU si se migra.
CMD ["python", "main.py", "--listen", "0.0.0.0", "--port", "8188", "--cpu", "--disable-auto-launch"]
