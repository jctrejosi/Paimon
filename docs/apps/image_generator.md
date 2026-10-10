# App — `image_generator`

Fachada HTTP sobre generadores de imágenes: permite pedir una imagen sin saber qué
backend la produce — **ComfyUI local** (sin coste) o un **proveedor externo** de pago
(OpenAI, Stability AI, Replicate, fal.ai, Black Forest Labs).

- **Carpeta**: `image_generator/`
- **Código**: `image_generator/api/app/`
- **Backend local**: `image_generator/ComfyUI/` (submódulo git)
- **README detallado**: [`../../image_generator/api/README.md`](../../image_generator/api/README.md)

El backend se elige **por petición** (`provider`) o, si se omite, por `IMAGE_PROVIDER`.

## Stack (docker compose)

| Servicio | Contenedor | Puerto | Rol |
|----------|-----------|--------|-----|
| `comfyui` | `paimon-comfyui` | 8188 | Backend local de difusión (Stable Diffusion en CPU). |
| `redis` | `paimon-redis` | 6379 | Estado de jobs, cola y pub/sub para SSE. |
| `api` | `paimon-image-api` | 8000 | Fachada HTTP; encola trabajos. |
| `worker` | — | 9100 | Consume la cola y ejecuta la generación (métricas Prometheus). |

`api` y `worker` no arrancan hasta que `comfyui` y `redis` pasan su healthcheck.

## Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/health` | Estado y proveedores configurados. |
| `GET` | `/metrics` | Métricas Prometheus. |
| `GET` | `/providers` | Catálogo de proveedores y si están configurados. |
| `POST` | `/generate` | Genera una o varias imágenes (text-to-image). |
| `POST` | `/edit` | Image-to-image / edición (exige `image`; `mask` opcional). |
| `POST` | `/jobs` | Encola la generación y devuelve un `id` (202). |
| `GET` | `/jobs`, `/jobs/{id}` | Lista / consulta jobs. |
| `GET` | `/jobs/{id}/events` | Flujo de eventos SSE con los cambios del job. |
| `DELETE` | `/jobs/{id}` | Cancela un job en curso o en cola. |
| `GET` | `/images/{filename}` | Sirve las imágenes generadas. |

Documentación interactiva en `/docs` (OpenAPI).

## Proveedores

| Proveedor | Activación | image-to-image | Paradigma |
|-----------|------------|:--------------:|-----------|
| `comfyui` (defecto) | `COMFYUI_URL` | Sí (img2img + inpaint) | Local, workflow API + polling |
| `openai` | `OPENAI_API_KEY` | Sí | `/images/generations` y `/images/edits` |
| `stability` | `STABILITY_API_KEY` | No | endpoint unificado `stable-image` |
| `replicate` | `REPLICATE_API_TOKEN` | No | predicciones + polling |
| `fal` | `FAL_KEY` | No | `fal.run/{model}` |
| `bfl` | `BFL_API_KEY` | No | FLUX asíncrono + polling |

Un proveedor externo solo aparece como "configurado" cuando tiene su clave.

## Jobs asíncronos

`POST /jobs` devuelve un `id` de inmediato y el trabajo corre en segundo plano
(ComfyUI en CPU puede tardar minutos). Estados:
`queued → running → succeeded | failed | canceled`. Se puede seguir en vivo con
`GET /jobs/{id}/events` (SSE) o recibir un `webhook_url` al terminar.

**Ejecución** (`JOB_EXECUTION`):

| Valor | Comportamiento |
|-------|----------------|
| `inline` | La API ejecuta los jobs en segundo plano (un solo proceso). |
| `worker` | La API solo encola; el/los `worker` consumen la cola (por defecto en compose). |

## Configuración esencial

| Variable | Default | Descripción |
|----------|---------|-------------|
| `IMAGE_PROVIDER` | `comfyui` | Proveedor por defecto. |
| `IMAGE_API_TOKEN` | *(vacío)* | Activa autenticación Bearer. |
| `JOB_CONCURRENCY` | `1` | Generaciones simultáneas máximas. |
| `JOB_EXECUTION` | `inline` | `inline` o `worker`. |
| `JOB_STORE` | `memory` | `memory` (efímero) o `redis` (persistente). |
| `COMFYUI_URL` | `http://127.0.0.1:8188` | ComfyUI local. |
| `COMFYUI_CHECKPOINT` | `v1-5-pruned-emaonly.safetensors` | Checkpoint a usar. |
| `IMAGE_API_HOST_PORT` | `8000` | Puerto de host de la API (lo usa `dev.js`). |

El resto de variables está en el `.env.example` de la app.

## Ejecución

```bash
# Con Docker (incluye ComfyUI)
cd image_generator
docker compose up --build           # API en 127.0.0.1:8000, ComfyUI en :8188

# O con el lanzador
node dev.js --image
```

Ejemplo:

```bash
curl -s http://127.0.0.1:8000/generate \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"un faro al atardecer, estilo acuarela","width":1024,"height":1024,
       "provider":"comfyui","response_format":"url"}'
```

## Pruebas

```bash
cd image_generator/api
pip install -r requirements-dev.txt
pytest
```

Usan un proveedor falso: no necesitan red ni claves.

## Nota sobre `ComfyUI`

`image_generator/ComfyUI` es un **submódulo git**. Hay que inicializarlo antes de
construir la imagen:

```bash
git submodule update --init --recursive
```
