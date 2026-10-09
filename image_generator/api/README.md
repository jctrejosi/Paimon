# Paimon Image Generator — API

Fachada HTTP sobre generadores de imágenes. Permite pedir una imagen **sin
saber** qué backend la produce: ComfyUI local (sin coste) o un proveedor externo
de pago (OpenAI, Stability AI, Replicate, fal.ai, Black Forest Labs).

El backend se elige **por petición** (`provider`) o, si se omite, por la
variable de entorno `IMAGE_PROVIDER`.

## Arranque rápido

```bash
cd image_generator/api
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # ajusta lo que necesites
uvicorn app.main:app --reload
```

Con Docker Compose (incluye el contenedor de ComfyUI):

```bash
cd image_generator
docker compose up --build
```

## Endpoints

| Método | Ruta | Descripción |
| ------ | ---- | ----------- |
| `GET`    | `/health` | Estado y proveedores configurados. |
| `GET`    | `/metrics` | Métricas Prometheus. |
| `GET`    | `/providers` | Catálogo de proveedores y si están configurados. |
| `POST`   | `/generate` | Genera una o varias imágenes (text-to-image). |
| `POST`   | `/edit` | Image-to-image / edición (exige `image`; `mask` opcional). |
| `POST`   | `/jobs` | Encola la generación y devuelve un `id` (202). |
| `GET`    | `/jobs` | Lista los jobs (más recientes primero). |
| `GET`    | `/jobs/{id}` | Estado y resultado de un job. |
| `GET`    | `/jobs/{id}/events` | Flujo de eventos SSE con los cambios del job. |
| `DELETE` | `/jobs/{id}` | Cancela un job en curso o en cola. |
| `GET`    | `/images/{filename}` | Sirve las imágenes generadas (`response_format=url`). |

Documentación interactiva en `/docs` (OpenAPI).

### Generar una imagen

```bash
curl -s http://127.0.0.1:8000/generate \
  -H 'Content-Type: application/json' \
  -d '{
        "prompt": "un faro al atardecer, estilo acuarela",
        "negative_prompt": "texto, borroso",
        "width": 1024, "height": 1024,
        "count": 1,
        "provider": "comfyui",
        "response_format": "url"
      }'
```

Respuesta:

```json
{
  "id": "…",
  "provider": "comfyui",
  "model": "v1-5-pruned-emaonly.safetensors",
  "created": 1730000000,
  "images": [{"url": "http://127.0.0.1:8000/images/comfyui-…png", "seed": 123}],
  "metadata": {"prompt_id": "…", "mode": "txt2img"}
}
```

Para forzar un proveedor externo basta con `"provider": "openai"` (o el que
corresponda) y tener su credencial configurada.

### Image-to-image / edición

`POST /edit` es igual que `/generate` pero **exige** `image` (base64 o data URL).
Si además envías `mask`, se hace **inpainting** (la zona blanca de la máscara es
la que se rehace). `strength` (0–1) controla cuánto se transforma la imagen
inicial.

```bash
curl -s http://127.0.0.1:8000/edit \
  -H 'Content-Type: application/json' \
  -d '{
        "prompt": "añade un gato sentado",
        "image": "data:image/png;base64,<...>",
        "mask":  "data:image/png;base64,<...>",
        "strength": 0.6
      }'
```

Solo algunos backends soportan edición (ver [Proveedores](#proveedores)). El
campo `supports_img2img` de `GET /providers` lo indica por proveedor.

### Jobs asíncronos

Para prompts lentos (ComfyUI en CPU puede tardar minutos) usa `/jobs`: se
devuelve un `id` de inmediato y el trabajo se ejecuta en segundo plano con
concurrencia limitada (`JOB_CONCURRENCY`).

```bash
# 1) Encolar
JOB=$(curl -s http://127.0.0.1:8000/jobs \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "fondo de pantalla abstracto", "webhook_url": "https://mi.app/hook"}')
JOB_ID=$(echo "$JOB" | python -c 'import sys,json;print(json.load(sys.stdin)["id"])')

# 2) Consultar
curl -s "http://127.0.0.1:8000/jobs/$JOB_ID"

# 3) Cancelar (si sigue en cola o en curso)
curl -s -X DELETE "http://127.0.0.1:8000/jobs/$JOB_ID"
```

Estados: `queued` → `running` → `succeeded` | `failed` | `canceled`. Si envías
`webhook_url`, al terminar se hace un `POST` con el objeto `Job` completo
(incluye el resultado) y `webhook_delivered` refleja si se entregó.

**Seguimiento en vivo (SSE).** En lugar de sondear, puedes suscribirte a
`GET /jobs/{id}/events`: el servidor emite un evento por cada cambio de estado y
cierra el flujo al llegar a un estado terminal.

```bash
curl -N http://127.0.0.1:8000/jobs/$JOB_ID/events
# data: {"id":"…","status":"queued",…}
# data: {"id":"…","status":"running",…}
# data: {"id":"…","status":"succeeded","result":{…}}
```

En el navegador, `EventSource` no admite cabeceras: pasa el token como
`?token=<token>` si activaste `IMAGE_API_TOKEN`.

```js
eventSource = new EventSource(`/jobs/${id}/events?token=${token}`);
eventSource.onmessage = (e) => {
  const job = JSON.parse(e.data);
  if (["succeeded", "failed", "canceled"].includes(job.status)) eventSource.close();
};
```

**Persistencia.** Por defecto el estado vive en memoria del proceso (`JOB_STORE=memory`):
se pierde al reiniciar y no se comparte entre réplicas. Para un servidor, usa
`JOB_STORE=redis`: el estado se guarda en Redis (con TTL vía `JOBS_TTL`), el
trabajo en una **cola** de Redis y los eventos se reparten por pub/sub. Así puedes
tener **varios procesos de API detrás de un balanceador** compartiendo el estado.

## Ejecución: inline o worker

Con `JOB_EXECUTION` eliges dónde se ejecuta la generación:

| Valor | Comportamiento |
| ----- | -------------- |
| `inline` (defecto) | La propia API ejecuta los jobs en segundo plano. Simple, un solo proceso. |
| `worker` | La API solo **encola**; uno o más **workers** dedicados consumen la cola. |

```bash
# Worker dedicado (fuera de Docker):
JOB_STORE=redis JOB_EXECUTION=worker python -m app.worker
```

Con `docker compose` ya hay un servicio `worker`; escala la ejecución con
`docker compose up --scale worker=3`. Los workers:

- toman trabajos de la cola de Redis (`paimon:jobs:queue`);
- mantienen un **latido** (`JOB_HEARTBEAT_INTERVAL`) mientras ejecutan;
- al arrancar, **sanean** los jobs huérfanos: un `running` sin latido reciente
  (worker caído, `JOB_STALE_AFTER`) o un `queued` con cola volátil pasa a `failed`.

La cancelación es **cooperativa**: si un job ya está generando, se respeta la
cancelación al terminar (no se puede interrumpir a mitad un proveedor externo).
En modo inline, además, se cancela la tarea local al instante.

## Métricas y operación

La API expone **`GET /metrics`** en formato Prometheus; el worker levanta su
propio servidor en `METRICS_PORT` (9100). Series principales:

| Métrica | Tipo | Etiquetas |
| ------- | ---- | --------- |
| `paimon_http_requests_total` | counter | `method`, `path`, `status` |
| `paimon_http_request_duration_seconds` | histogram | `method`, `path` |
| `paimon_generations_total` | counter | `provider`, `status` |
| `paimon_jobs_submitted_total` | counter | `provider` |
| `paimon_jobs_completed_total` | counter | `provider`, `status` |
| `paimon_job_duration_seconds` | histogram | `provider` |
| `paimon_jobs_running` | gauge | — |

El `docker-compose.yml` incluye **healthchecks** (`/health` de la API,
`/system_stats` de ComfyUI, `redis-cli ping`) y `depends_on` con
`condition: service_healthy`, de modo que api/worker no arrancan hasta que sus
dependencias están listas.

### Límites de entrada

- `MAX_REQUEST_BYTES` (32 MiB por defecto): las peticiones con un
  `Content-Length` mayor reciben `413`.
- `MAX_IMAGE_BYTES` (20 MiB por defecto): las imágenes de entrada
  (`image`/`mask`) que lo superan reciben `413` **antes** de decodificarse.

## Autenticación

Si defines `IMAGE_API_TOKEN`, exigen `Authorization: Bearer <token>` las rutas
`/generate`, `/edit` y todas las de `/jobs`. Útil cuando la API se expone más
allá de `localhost` o para no dejar abierta una ruta que consume crédito.

## Proveedores

| Proveedor | Activación | image-to-image | Paradigma |
| --------- | ---------- | :------------: | --------- |
| `comfyui` (defecto) | `COMFYUI_URL` | Sí (img2img + inpaint) | Local, workflow API + polling |
| `openai` | `OPENAI_API_KEY` | Sí (`gpt-image-1`/`dall-e-2`) | `/images/generations` y `/images/edits` |
| `stability` | `STABILITY_API_KEY` | No | endpoint unificado `stable-image` |
| `replicate` | `REPLICATE_API_TOKEN` | No | predicciones + polling |
| `fal` | `FAL_KEY` | No | `fal.run/{model}` |
| `bfl` | `BFL_API_KEY` | No | FLUX asíncrono + polling |

Un proveedor externo solo aparece como "configurado" cuando tiene su clave.
La fila "image-to-image" refleja lo soportado por esta capa; otros modelos
pueden hacerlo vía el campo `extra` de la petición.

## Configuración

Todas las variables están documentadas en [`.env.example`](.env.example). Lo
esencial:

| Variable | Por defecto | Descripción |
| -------- | ----------- | ----------- |
| `IMAGE_PROVIDER` | `comfyui` | Proveedor por defecto. |
| `IMAGE_API_TOKEN` | *(vacío)* | Activa autenticación Bearer. |
| `JOB_CONCURRENCY` | `1` | Generaciones simultáneas máximas. |
| `JOB_EXECUTION` | `inline` | `inline` (en la API) o `worker` (proceso aparte). |
| `JOBS_MAX` | `100` | Jobs retenidos en el store. |
| `JOB_STORE` | `memory` | `memory` (efímero) o `redis` (persistente). |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | Conexión a Redis cuando `JOB_STORE=redis`. |
| `JOBS_TTL` | `86400` | Caducidad (segundos) de cada job en Redis. |
| `JOB_STALE_AFTER` | `60.0` | Antigüedad de latido para considerar huérfano un job. |
| `MAX_REQUEST_BYTES` | `33554432` | Tamaño máximo del cuerpo de una petición. |
| `MAX_IMAGE_BYTES` | `20971520` | Tamaño máximo de una imagen de entrada. |
| `METRICS_ENABLED` | `true` | Expone `/metrics`. |
| `COMFYUI_URL` | `http://127.0.0.1:8188` | ComfyUI local. |
| `COMFYUI_CHECKPOINT` | `v1-5-pruned-emaonly.safetensors` | Checkpoint a usar. |
| `OPENAI_API_KEY` | *(vacío)* | Activa el proveedor OpenAI. |
| `STABILITY_API_KEY` | *(vacío)* | Activa Stability AI. |
| `REPLICATE_API_TOKEN` | *(vacío)* | Activa Replicate. |
| `FAL_KEY` | *(vacío)* | Activa fal.ai. |
| `BFL_API_KEY` | *(vacío)* | Activa Black Forest Labs. |

## Arquitectura

```
app/
├── main.py            # FastAPI: rutas, autenticación, middleware, /metrics
├── worker.py          # Entrypoint del worker (`python -m app.worker`)
├── config.py          # Settings (pydantic-settings / .env)
├── schemas.py         # Contratos de entrada/salida (incl. Job)
├── service.py         # Pipeline de generación compartido
├── metrics.py         # Métricas Prometheus
├── jobs/              # Jobs asíncronos
│   ├── __init__.py    # JobManager: encolar, consultar, cancelar (API)
│   ├── runner.py      # JobRunner: consume la cola y ejecuta
│   ├── store.py       # JobStore: memoria / Redis
│   ├── queue.py       # JobQueue: memoria / lista en Redis
│   ├── events.py      # EventBus: memoria / pub-sub Redis
│   └── backends.py    # Selección según la configuración
├── images.py          # Decodificación de imágenes de entrada
├── storage.py         # Persistencia de imágenes generadas
└── providers/
    ├── base.py        # ImageProvider (ABC) + tipos de resultado
    ├── registry.py    # Catálogo y ciclo de vida de proveedores
    ├── comfyui.py     # ComfyUI local (txt2img/img2img/inpaint + polling)
    ├── openai_provider.py
    ├── stability.py
    ├── replicate.py
    ├── fal.py
    └── bfl.py
workflows/
├── sd_txt2img.json    # Plantilla de ComfyUI: texto → imagen
├── sd_img2img.json    # Plantilla de ComfyUI: imagen → imagen
└── sd_inpaint.json    # Plantilla de ComfyUI: inpainting (imagen + máscara)
```

### Añadir un proveedor

1. Crea `app/providers/<nombre>.py` con una subclase de `ImageProvider`:
   implementa `is_configured`, `default_model` (opcional) y `generate`.
   Para soportar edición, define `supports_img2img = True` y usa `request.image`
   / `request.mask` (decodifícalas con `self.decode_image_field(...)`).
2. Añade su clase a `PROVIDER_CLASSES` en `providers/registry.py`.
3. Añade sus variables a `config.py` y `.env.example`.

No hay que tocar `main.py`: la selección y la validación son genéricas.

## Pruebas

```bash
cd image_generator/api
pip install -r requirements-dev.txt
pytest
```

Las pruebas usan un proveedor falso, por lo que no necesitan red ni claves.

## ComfyUI: nota sobre los workflows

Las plantillas de `workflows/` usan los nodos estándar de difusión. El proveedor
inyecta los parámetros buscando los nodos **por `class_type`**:

- el primer `CLIPTextEncode` recibe el prompt positivo y el segundo el negativo;
- `EmptyLatentImage` recibe `width`/`height`/`batch_size` (solo txt2img);
- `KSampler` recibe `seed`/`steps`/`cfg`/`denoise` (el `denoise` viene de
  `strength` en img2img);
- `SaveImage` recibe el `filename_prefix`.

El modo se elige según la petición: sin `image` → txt2img; con `image` →
img2img; con `image` + `mask` → inpainting.

Para usar un workflow propio en txt2img, apunta `COMFYUI_WORKFLOW` a un JSON en
formato API que respete esas convenciones (img2img/inpaint usan las plantillas
integradas).
