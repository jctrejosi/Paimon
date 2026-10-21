# image_processing

Procesamiento **local** de imágenes de Paimon. Primera funcionalidad: **quitar el
fondo** (`remove-bg`).

Recibe una imagen y devuelve otra con el fondo eliminado (PNG/WebP con canal alfa)
o compuesta sobre un color sólido. El motor es `rembg` sobre **ONNX Runtime (CPU)**:
la misma familia de modelos (U²-Net / IS-Net / BiRefNet) que usa ArtCraft a través
de fal, pero corriendo en la propia máquina, sin nube ni credenciales.

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/remove-bg` | Quita el fondo (`multipart/form-data`). |
| `GET` | `/health` | Estado y proveedores configurados. |
| `GET` | `/providers` | Proveedores y modelo por defecto. |
| `GET` | `/models` | Modelos de `rembg` aceptados. |
| `GET` | `/` | Índice de endpoints (fuera de OpenAPI). |

Documentación interactiva en `/docs`. En Swagger, `model` y `provider` son
**desplegables** con los valores válidos; deja `model` vacío para usar el modelo
por defecto.

### `POST /remove-bg`

Campos (`multipart/form-data`):

| Campo | Default | Uso |
|---|---|---|
| `file` | — | Imagen (obligatorio). |
| `model` | `isnet-general-use` | `u2net`, `isnet-general-use`, `birefnet-general`, `u2net_human_seg`, … Vacío = modelo por defecto. |
| `alpha_matting` | `false` | Bordes más finos (más lento). |
| `alpha_matting_foreground_threshold` | `240` | Umbral de primer plano. |
| `alpha_matting_background_threshold` | `10` | Umbral de fondo. |
| `alpha_matting_erode_size` | `10` | Erosión de la máscara. |
| `post_process_mask` | `false` | Limpieza morfológica de la máscara. |
| `background` | `transparent` | `transparent` o un color `#RRGGBB`. |
| `output_format` | `png` | `png` (alfa) o `webp` (alfa). |
| `response_format` | `image` | `image` (bytes) o `json` (base64 + metadatos). |
| `provider` | `local` | Proveedor a usar. |

Respuesta `response_format=image`: la imagen resultante, con cabeceras
`X-Provider`, `X-Model` y `X-Elapsed-Ms`. Se envía como **descarga**
(`Content-Disposition: attachment; filename="remove-bg.png"` o `.webp`), así que
el navegador y el botón *Download* de Swagger la guardan como archivo.

Respuesta `response_format=json`:

```json
{
  "id": "…",
  "provider": "local",
  "model": "u2net",
  "created": 1730000000,
  "mime_type": "image/png",
  "width": 1024,
  "height": 1024,
  "elapsed_ms": 850,
  "image_base64": "iVBORw0KGgo…"
}
```

### Ejemplos

```bash
# PNG transparente (descarga como remove-bg.png)
curl -s -OJ -F file=@foto.jpg http://127.0.0.1:8002/remove-bg

# ...o elige tú el nombre
curl -s -F file=@foto.jpg http://127.0.0.1:8002/remove-bg -o sin-fondo.png

# Fondo blanco, WebP
curl -s -F file=@foto.jpg -F background=#ffffff -F output_format=webp \
  http://127.0.0.1:8002/remove-bg -o sin-fondo.webp

# JSON con base64
curl -s -F file=@foto.jpg -F response_format=json \
  http://127.0.0.1:8002/remove-bg | jq -r .image_base64 | base64 -d > sin-fondo.png
```

### Formatos y límites

- **Entrada**: PNG, JPEG (`.jpg`, `.jpeg`, `.jpe`, `.jfif`), WebP, AVIF, HEIC/HEIF
  (fotos de iPhone), TIFF, GIF, BMP, ICO, PPM/PGM/PBM y TGA. También se aceptan
  archivos **sin extensión** o con extensión desconocida si el contenido decodifica
  como imagen: la validación es por contenido, no solo por nombre.
- La imagen se **normaliza a PNG** antes del motor: se aplica la orientación EXIF
  (fotos de cámara/móvil) y, si la entrada es animada, se usa el primer fotograma.
- Tamaño máximo: `IMAGE_PROCESSING_MAX_UPLOAD_MB` (20 MB) → `413`.
- Imágenes enormes: `MAX_IMAGE_PIXELS` (40 Mpx) → `413`.
- Extensión desconocida + contenido que no es imagen → `415`; archivo vacío o no
  decodificable → `400`.
- Si `IMAGE_PROCESSING_API_TOKEN` está definido, se exige
  `Authorization: Bearer <token>` en `/remove-bg`.
- HEIC/HEIF usa `pillow-heif` (incluido en `requirements.txt`); AVIF lo lee Pillow
  directamente. Si faltara `pillow-heif`, el resto de formatos sigue funcionando.

## Modelos

`isnet-general-use` es el **default para este equipo**: mucha mejor calidad que
`u2net` y sigue siendo ligero (~0.9 GB de pico y ~20 s por imagen en CPU).

| Modelo | Pico de RAM | Tiempo (CPU, 2 hilos) | Cuándo usarlo |
|---|---|---|---|
| `u2net` | ~0.7 GB | ~7 s | Máxima velocidad. |
| **`isnet-general-use`** | **~0.9 GB** | **~20 s** | **Recomendado**: mejor equilibrio. |
| `birefnet-general-lite` | ~6.9 GB | ~68 s | Bordes finos, si hay RAM. |
| `birefnet-general` | ~8 GB | ~2–3 min | Máxima calidad; una petición a la vez. |
| `bria-rmbg` | ~8.2 GB | ~2–3 min | Producto/recorte difícil; muy pesado. |
| `u2net_human_seg` | ~0.7 GB | ~7 s | Personas. |
| `isnet-anime` | ~0.9 GB | ~20 s | Ilustración/anime. |

> `birefnet-general` necesita ~8 GB; con los 8 hilos por defecto llegaba a
> 13.5 GB y el OOM killer mataba el proceso. El servicio limita ONNX a 2 hilos y
desactiva el arena; aun así, pídelo solo si hay RAM libre.

El primer uso de un modelo descarga sus pesos a `api/models/` (volumen en Docker)
y no se vuelven a descargar.

## Configuración

Variables de entorno (o `.env`, no versionado):

| Variable | Default | Uso |
|---|---|---|
| `IMAGE_PROCESSING_API_TOKEN` | *(vacío)* | Token Bearer opcional. |
| `IMAGE_PROCESSING_PROVIDER` | `local` | Proveedor por defecto. |
| `IMAGE_PROCESSING_MAX_UPLOAD_MB` | `20` | Tamaño máximo de subida. |
| `MAX_IMAGE_PIXELS` | `40000000` | Tope de píxeles por imagen. |
| `DEFAULT_OUTPUT_FORMAT` | `png` | Formato de salida por defecto. |
| `LOCAL_REMBG_MODEL` | `isnet-general-use` | Modelo por defecto. |
| `LOCAL_REMBG_ALPHA_MATTING` | `false` | Matting alfa por defecto. |
| `LOCAL_REMBG_POST_PROCESS_MASK` | `false` | Limpieza de máscara por defecto. |
| `LOCAL_REMBG_MODEL_DIR` | `models` | Caché de pesos (`U2NET_HOME`). |
| `LOCAL_REMBG_INTRA_OP_THREADS` | `2` | Hilos de inferencia (menos RAM). |
| `LOCAL_REMBG_INTER_OP_THREADS` | `1` | Hilos entre operadores. |
| `LOCAL_REMBG_CPU_MEM_ARENA` | `false` | Arena de memoria de ONNX. |
| `LOCAL_REMBG_ENABLE_MEM_PATTERN` | `false` | Patrón de memoria de ONNX. |

## Ejecución

```bash
cd image_processing
docker compose up --build           # API en 127.0.0.1:8002
```

O con el lanzador del repo:

```bash
node dev.js --processing            # solo image_processing
node dev.js --removebg              # alias
IMAGE_PROCESSING_HOST_PORT=8003 node dev.js --processing --build
```

Sin Docker:

```bash
cd image_processing/api
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt          # o requirements-dev.txt para tests
uvicorn app.main:app --reload --port 8002
```

Si el 8002 está ocupado por `image_generator`, usa otro puerto
(`IMAGE_PROCESSING_HOST_PORT=8003` con Docker, o `--port 8003` en local).

> La primera petición a un modelo descarga sus pesos (decenas de MB) y tarda más.
> En esta máquina (Ryzen 5 3500U, 2 hilos ONNX): `u2net` ~7 s,
> `isnet-general-use` ~24–27 s, `birefnet-general` ~3,5 min.

## Pruebas

```bash
cd image_processing/api
pytest
```

Usan un proveedor falso: no instalan `rembg`, no descargan modelos ni usan red.

## Notas de diseño

- **Proveedores**: `providers/base.py` define `RemoveBgProvider` (ABC) y
  `registry.py` los instancia bajo demanda, igual que `image_generator` y
  `audio_processing`. Añadir un backend cloud (p. ej. fal `rembg`) es implementar
  el contrato y registrarlo.
- **Concurrencia**: `rembg` es CPU-bound y bloqueante; se ejecuta en un hilo
  (`asyncio.to_thread`) y se serializa con un lock para no competir por CPU ni
  crear sesiones ONNX en paralelo.
- **Privacidad**: las imágenes no se persisten; solo se procesan en memoria.
