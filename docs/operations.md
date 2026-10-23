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

## Autenticación (claves de API)

Las tres APIs exigen una clave en **todas** las rutas salvo `/health`. La fuente
principal es un único archivo `.env` en la raíz de Paimon:

```dotenv
API_KEYS=clave1,clave2
API_AUTH_REQUIRED=1
API_PUBLIC_DOCS=0
```

Los tres compose lo cargan con `env_file: ../.env`, así que basta con editar ahí
y recrear los servicios.

El cliente envía la clave de cualquiera de estas dos formas:

```bash
curl -H 'X-API-Key: clave1' https://paimon.jcti.xyz/audio/health
curl -H 'Authorization: Bearer clave1' https://paimon.jcti.xyz/image/docs
```

Varias claves separadas por comas permiten revocar una sin afectar al resto.
Genera cada una con `openssl rand -hex 32`.

| Ajuste | Efecto |
|---|---|
| `API_AUTH_REQUIRED=0` | Desactiva la comprobación (solo desarrollo local). |
| `API_PUBLIC_DOCS=1` | Deja `/docs`, `/redoc` y `/openapi.json` sin clave. |
| `API_ALLOW_QUERY_TOKEN=1` | Acepta también `?token=` (solo `image_generator`, por SSE). |

Si `API_AUTH_REQUIRED=1` y `API_KEYS` está vacío, las APIs responden `503` en
lugar de quedar abiertas (fail-closed).

### Tokens heredados

Siguen funcionando y se aceptan **además** de `API_KEYS`; viven en el `.env` de
cada servicio:

| App | Variable |
|-----|----------|
| `audio_processing` | `AUDIO_API_TOKEN` |
| `image_generator` | `IMAGE_API_TOKEN` |
| `image_processing` | `IMAGE_PROCESSING_API_TOKEN` |

En SSE (`EventSource`) la clave va como `?token=<clave>` porque no admite
cabeceras.

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
