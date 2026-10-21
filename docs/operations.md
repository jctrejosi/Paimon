# Operación

Notas comunes para operar los aplicativos: puertos, tokens, logs, build y problemas
típicos.

## Puertos

| Servicio | Puerto (host, loopback) |
|----------|-------------------------|
| `audio_processing` — API | `8000` |
| `image_generator` — API | `8000` |
| `image_generator` — ComfyUI | `8188` |
| `image_generator` — Redis | `6379` |
| `image_generator` — worker (métricas) | `9100` |
| `image_processing` — API | `8002` |

Las APIs de audio e imágenes coinciden en `:8000`. Si se levantan a la vez con
`dev.js`, las siguientes pasan al siguiente puerto libre (`:8001`, …). `image_processing`
usa `8002` por defecto. En este equipo `8001` y `8002` están ocupados, así que
`image_processing` queda en `8003`. Para fijarlas a mano:

```bash
AUDIO_HOST_PORT=8000 IMAGE_API_HOST_PORT=8001 IMAGE_PROCESSING_HOST_PORT=8002 node dev.js
```

Todo se publica en **loopback** (`127.0.0.1`): no queda expuesto a la red. ComfyUI y
Redis no traen autenticación, por eso no deben exponerse.

## Autenticación (tokens)

Ambas son abiertas por defecto. Para protegerlas, define su token y pásalo como
`Authorization: Bearer <token>`:

| App | Variable |
|-----|----------|
| `audio_processing` | `AUDIO_API_TOKEN` (protege `/transcribe` y `/v1/audio/transcriptions`) |
| `image_generator` | `IMAGE_API_TOKEN` (protege `/generate`, `/edit` y `/jobs`) |
| `image_processing` | `IMAGE_PROCESSING_API_TOKEN` (protege `/remove-bg`) |

En SSE (`EventSource`) el token va como `?token=<token>` porque no admite cabeceras.

## Logs

- **Lanzador**: `logs/<app>.log` (salida de `docker compose up`).
- **Contenedores**: `node dev.js --logs` o `cd <app> && docker compose logs -f`.
- **Archivos de datos** generados por las apps no se versionan (ver `.gitignore`):
  `image_generator/api/outputs/`, `audio_processing/api/models/`,
  `image_processing/api/models/`.

## Build y datos persistentes

- Imágenes: `paimon-audio-processing:local`, `paimon-comfyui:local`,
  `paimon-image-api:local`, `paimon-image-processing:local`.
- Reconstruir: `node dev.js --build` o `docker compose up --build` en la app.
- Pesos/modelos y salidas van en **volúmenes**, no en la imagen:
  - audio: `audio_processing/api/models/` → `/models` (Whisper, HF).
  - imágenes: `image_generator/ComfyUI/{models,input,output}` y
    `image_generator/api/outputs/`.
  - procesamiento: `image_processing/api/models/` → `/models` (rembg).

## Healthchecks

- `audio_processing`: la API responde en `GET /health`.
- `image_generator`: la API en `/health`, ComfyUI en `/system_stats`, Redis con
  `redis-cli ping`. `api`/`worker` esperan (`depends_on … service_healthy`).
- `image_processing`: la API responde en `GET /health`.

## Problemas típicos

| Síntoma | Causa probable | Solución |
|---------|----------------|----------|
| `docker compose` no existe | Solo `docker-compose` v1 instalado | Instala el plugin Compose v2. |
| Una API no responde en su puerto | Conflicto de `:8000` | Usa `dev.js` (reasigna) o fija los `*_HOST_PORT`. |
| `image_generator` no arranca | ComfyUI aún cargando | Espera; la API no publica hasta que ComfyUI pasa el healthcheck (hasta 180 s). |
| Build falla en `image_generator` | Submódulo ComfyUI sin inicializar | `git submodule update --init --recursive`. |
| Primera transcripción lenta | Descarga de pesos de Whisper | Se cachean en `audio_processing/api/models/`; solo pasa la primera vez. |
| Módulo de audio reporta no disponible | Falta dependencia opcional | Instala `requirements-extras.txt`. |
| Primer `remove-bg` lento | Descarga del modelo de rembg | Se cachea en `image_processing/api/models/`; solo pasa la primera vez. |
| `remove-bg` devuelve 503 | `rembg` no instalado en el entorno | Usa la imagen Docker o `pip install "rembg[cpu]"`. |
| `remove-bg` mata el proceso (OOM) | `birefnet-general`/`bria-rmbg` usan ~8 GB | Usa `isnet-general-use` (default) o baja `LOCAL_REMBG_INTRA_OP_THREADS`. |

## Pruebas

```bash
cd audio_processing/api && pytest
cd image_generator/api && pytest
cd image_processing/api && pytest
```

Todas usan dobles (proveedor falso): no requieren red ni claves.

## Inicializar el repo

```bash
git submodule update --init --recursive   # trae ComfyUI
```
