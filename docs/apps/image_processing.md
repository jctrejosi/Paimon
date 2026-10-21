# App — `image_processing`

Procesamiento **local** de imágenes de Paimon. Primera funcionalidad:
**quitar el fondo** (`remove-bg`).

- **Carpeta**: `image_processing/`
- **Código**: `image_processing/api/app/`
- **README detallado**: [`../../image_processing/README.md`](../../image_processing/README.md)

Recibe una imagen y devuelve otra con el fondo eliminado (PNG/WebP con canal
alfa) o compuesta sobre un color sólido. El motor es `rembg` sobre **ONNX Runtime
(CPU)**: la misma familia de modelos (U²-Net / IS-Net / BiRefNet) que usa ArtCraft
a través de fal, pero corriendo en la propia máquina.

## Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| `POST` | `/remove-bg` | Quita el fondo (`multipart/form-data`). |
| `GET`  | `/health` | Estado y proveedores configurados. |
| `GET`  | `/providers` | Proveedores y modelo por defecto. |
| `GET`  | `/models` | Modelos de `rembg` aceptados. |
| `GET`  | `/` | Índice de endpoints. |

Documentación interactiva en `/docs`.

## `POST /remove-bg`

| Campo | Default | Uso |
|-------|---------|-----|
| `file` | — | Imagen (obligatorio). |
| `model` | `isnet-general-use` | `u2net`, `isnet-general-use`, `birefnet-general`, … |
| `alpha_matting` | `false` | Bordes más finos (más lento). |
| `post_process_mask` | `false` | Limpieza morfológica de la máscara. |
| `background` | `transparent` | `transparent` o `#RRGGBB`. |
| `output_format` | `png` | `png` o `webp`, ambos con alfa. |
| `response_format` | `image` | `image` (bytes) o `json` (base64 + metadatos). |
| `provider` | `local` | Proveedor. |

Respuesta `image`: la imagen resultante, con cabeceras `X-Provider`, `X-Model` y
`X-Elapsed-Ms`. Respuesta `json`: metadatos (`width`, `height`, `elapsed_ms`, …)
más `image_base64`.

## Modelos

`isnet-general-use` es el default para este equipo: mejor calidad que `u2net` y
ligero (~0.9 GB, ~20 s). `birefnet-general` da más calidad pero usa ~8 GB y tarda
minutos; `u2net_human_seg` e `isnet-anime` están especializados. El primer uso
descarga los pesos en `image_processing/api/models/` y se cachean.

## Configuración

| Variable | Default | Uso |
|----------|---------|-----|
| `IMAGE_PROCESSING_API_TOKEN` | *(vacío)* | Token Bearer opcional. |
| `IMAGE_PROCESSING_PROVIDER` | `local` | Proveedor por defecto. |
| `IMAGE_PROCESSING_MAX_UPLOAD_MB` | `20` | Tamaño máximo de subida. |
| `MAX_IMAGE_PIXELS` | `40000000` | Tope de píxeles. |
| `DEFAULT_OUTPUT_FORMAT` | `png` | Formato por defecto. |
| `LOCAL_REMBG_MODEL` | `isnet-general-use` | Modelo por defecto. |
| `LOCAL_REMBG_ALPHA_MATTING` | `false` | Matting alfa por defecto. |
| `LOCAL_REMBG_MODEL_DIR` | `models` | Caché de pesos (`U2NET_HOME`). |

## Formatos

| Entrada | Notas |
|---------|-------|
| PNG, JPEG, WebP, AVIF, TIFF, GIF, BMP, ICO, PPM/PGM/PBM, TGA | Decodificados por Pillow. |
| HEIC/HEIF | Vía `pillow-heif` (fotos de iPhone). |
| Sin extensión o extensión rara | Se acepta si el contenido es una imagen. |

La entrada se normaliza a PNG antes del motor: orientación EXIF aplicada y primer
fotograma si es animada. Salida: PNG o WebP, ambos con canal alfa.

## Ejecución

```bash
cd image_processing
docker compose up --build           # API en 127.0.0.1:8002

# solo image_processing (alias: --removebg, --remove-bg, --image-processing)
IMAGE_PROCESSING_HOST_PORT=8003 node dev.js --processing --build
```

Si el puerto 8002 ya lo ocupa `image_generator`, el lanzador salta al siguiente
libre; en este equipo la API queda en `http://127.0.0.1:8003` (`/docs` para Swagger).
Sin Docker (venv local):

```bash
cd image_processing/api
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8003
```

## Validación en este equipo

Equipo: AMD Ryzen 5 3500U (8 hilos), 29 GB RAM, ONNX limitado a 2 hilos.
Imagen de prueba: `image_processing/test_data/ablandacarnes.png` (450×450).

| Modelo | Pico RSS | Tiempo HTTP | Resultado |
|--------|----------|-------------|-----------|
| `u2net` | 0.7 GB | ~7 s | Rápido, máscara más basta. |
| **`isnet-general-use`** | **0.9 GB** | **~24–27 s** | **Default.** Alfa suave (máx. 254), 45 % transparente. |
| `birefnet-general-lite` | 6.9 GB | ~68 s | |
| `birefnet-general` | 8 GB | ~216 s | Máscara casi idéntica a `isnet`. |
| `bria-rmbg` | 8.2 GB | ~166 s | |

Comparación `isnet-general-use` vs `birefnet-general` en esa imagen: 726 píxeles
de 202 500 (0.36 %) difieren con alfa > 128 y la diferencia media de alfa es 2.04;
visualmente son equivalentes. Por eso el default es `isnet` (10× más rápido y 9×
menos RAM). `isnet` deja un halo semitransparente de ~6 px de alfa alrededor del
objeto; al componer sobre un color, ese halo mezcla ligeramente con el color de
fondo (es composición alfa correcta, no un fallo).

También validado (contenedor Docker en `8003`): entrada **JPEG, WebP, AVIF, HEIC,
GIF, BMP, TIFF, sin extensión y con extensión rara** → HTTP `200` con la máscara
idéntica en todos los casos (45,2 % transparente) y 17–22 s en caliente. Salida
WebP con alfa, fondo `#RRGGBB`, `response_format=json` (base64 + metadatos) y los
errores `400` (modelo/color inválido, archivo vacío), `415` (extensión desconocida
sin imagen) y `422` (falta `file`).

> En un contenedor recién arrancado, la **primera** petición carga el modelo y
> puede tardar bastante más (se vio >180 s con el build recién terminado); las
> siguientes van a ~20 s.

## Pruebas

```bash
cd image_processing/api
pytest
```

Usan un proveedor falso: no instalan `rembg`, no descargan modelos ni usan red.

## Relación con ArtCraft

ArtCraft implementa el quita-fondo en la nube (su API o fal
`fal-ai/imageutils/rembg`). Aquí se replica el mismo enfoque de modelos, pero
**local-first**. Ver [`../reference/artcraft.md`](../reference/artcraft.md) para
la revisión completa.
