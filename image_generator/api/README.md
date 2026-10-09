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
| `GET`  | `/health` | Estado y proveedores configurados. |
| `GET`  | `/providers` | Catálogo de proveedores y si están configurados. |
| `POST` | `/generate` | Genera una o varias imágenes. |
| `GET`  | `/images/{filename}` | Sirve las imágenes generadas (`response_format=url`). |

Documentación interactiva en `/docs` (OpenAPI).

### Ejemplo

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
  "metadata": {"prompt_id": "…"}
}
```

Para forzar un proveedor externo basta con `"provider": "openai"` (o el que
corresponda) y tener su credencial configurada.

## Autenticación

Si defines `IMAGE_API_TOKEN`, la ruta `/generate` exige
`Authorization: Bearer <token>`. Útil cuando la API se expone más allá de
`localhost` o para no dejar abierta una ruta que consume crédito.

## Configuración

Todas las variables están documentadas en [`.env.example`](.env.example). Lo
esencial:

| Variable | Por defecto | Descripción |
| -------- | ----------- | ----------- |
| `IMAGE_PROVIDER` | `comfyui` | Proveedor por defecto. |
| `IMAGE_API_TOKEN` | *(vacío)* | Activa autenticación Bearer. |
| `COMFYUI_URL` | `http://127.0.0.1:8188` | ComfyUI local. |
| `COMFYUI_CHECKPOINT` | `v1-5-pruned-emaonly.safetensors` | Checkpoint a usar. |
| `OPENAI_API_KEY` | *(vacío)* | Activa el proveedor OpenAI. |
| `STABILITY_API_KEY` | *(vacío)* | Activa Stability AI. |
| `REPLICATE_API_TOKEN` | *(vacío)* | Activa Replicate. |
| `FAL_KEY` | *(vacío)* | Activa fal.ai. |
| `BFL_API_KEY` | *(vacío)* | Activa Black Forest Labs. |

Un proveedor externo solo aparece como "configurado" cuando tiene su clave.

## Arquitectura

```
app/
├── main.py            # FastAPI: rutas, autenticación, orquestación
├── config.py          # Settings (pydantic-settings / .env)
├── schemas.py         # Contratos de entrada/salida
├── storage.py         # Persistencia de imágenes generadas
└── providers/
    ├── base.py        # ImageProvider (ABC) + tipos de resultado
    ├── registry.py    # Catálogo y ciclo de vida de proveedores
    ├── comfyui.py     # ComfyUI local (workflow API + polling)
    ├── openai_provider.py
    ├── stability.py
    ├── replicate.py
    ├── fal.py
    └── bfl.py
workflows/
└── sd_txt2img.json    # Plantilla de workflow de ComfyUI por defecto
```

### Añadir un proveedor

1. Crea `app/providers/<nombre>.py` con una subclase de `ImageProvider`:
   implementa `is_configured`, `default_model` (opcional) y `generate`.
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

## ComfyUI: nota sobre el workflow

La plantilla por defecto (`workflows/sd_txt2img.json`) usa los nodos estándar de
difusión (checkpoint, CLIP, KSampler, VAE, SaveImage). El proveedor inyecta los
parámetros buscando los nodos **por `class_type`**:

- el primer `CLIPTextEncode` recibe el prompt positivo y el segundo el negativo;
- `EmptyLatentImage` recibe `width`/`height`/`batch_size`;
- `KSampler` recibe `seed`/`steps`/`cfg`.

Para usar un workflow propio, apunta `COMFYUI_WORKFLOW` a un JSON en formato API
que respete esas convenciones.
