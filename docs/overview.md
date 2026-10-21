# Visión general

Paimon es un **monorepo de aplicativos de IA local-first**. Cada aplicativo es una
herramienta **independiente** que recibe una entrada y devuelve una salida, y que se
puede usar sola o encadenar con otras. La idea es construir piezas pequeñas y
reutilizables (transcripción de audio, generación de imágenes, y a futuro documentos,
vídeo, etc.) en lugar de un único servicio monolítico.

Ver [`roadmap.md`](roadmap.md) para los módulos previstos.

## Principios

- **Local-first**: por defecto todo se ejecuta en la máquina. Los proveedores cloud
  externos existen, pero son opcionales y van detrás de la misma interfaz.
- **CPU, sin GPU asumida**: el host no tiene GPU NVIDIA/ROCm, así que se priorizan
  modelos y runtimes eficientes en CPU.
- **Aislado**: cada app se despliega con su propio `docker compose` y se publica
  **solo en loopback** (`127.0.0.1`); sin autenticación por defecto (token opcional).
- **Patrón de servicio común**: FastAPI + una ABC de proveedores + `registry.py` +
  `config.py` por variables de entorno. Añadir un proveedor no toca el núcleo.

## Estructura del repo

```
Paimon/
├── dev.js                    # lanzador único de los aplicativos (Docker Compose)
├── docs/                     # esta documentación
├── plans/                    # planes y roadmap (diseño a nivel de proyecto)
├── audio_processing/         # app: transcripción + preprocesamiento de audio
│   ├── api/                  #   código de la API (FastAPI) + tests
│   ├── eval/                 #   banco de evaluación de WER
│   └── Dockerfile / docker-compose.yml
├── image_generator/          # app: generación y edición de imágenes
│   ├── api/                  #   fachada HTTP (FastAPI) + worker + tests
│   ├── ComfyUI/              #   submódulo: backend local de difusión
│   └── Dockerfile / docker-compose.yml
└── image_processing/         # app: procesamiento de imágenes (quita-fondo)
    ├── api/                  #   código de la API (FastAPI) + tests
    └── Dockerfile / docker-compose.yml
```

> `image_generator/ComfyUI` es un **submódulo git** (ver `.gitmodules`). Hay que
> inicializarlo (`git submodule update --init --recursive`) antes de construir.

## Aplicativos actuales

| App | Carpeta | Qué hace | Puerto por defecto |
|-----|---------|----------|--------------------|
| **audio_processing** | `audio_processing/` | Transcripción (voz→texto) y preprocesamiento modular de audio. | API `8000` |
| **image_generator** | `image_generator/` | Generación/edición de imágenes (ComfyUI local o proveedores cloud). | API `8000`, ComfyUI `8188`, Redis `6379` |
| **image_processing** | `image_processing/` | Procesamiento de imágenes local (quita-fondo). | API `8002` (`8003` si está ocupado) |

Detalle en [`apps/audio_processing.md`](apps/audio_processing.md),
[`apps/image_generator.md`](apps/image_generator.md) y
[`apps/image_processing.md`](apps/image_processing.md).

## Requisitos

- **Docker** con **Compose v2** (`docker compose`, no `docker-compose`).
- **Node.js** (solo para el lanzador `dev.js`; las apps no lo necesitan).
- ~CPU suficiente para correr Whisper y Stable Diffusion (puede ser lento sin GPU).

## Convenciones de nombres

- Carpetas de app en `snake_case` (p. ej. `audio_processing/`).
- Dentro de cada app, la capa de servicio vive en `api/` con `app/` como paquete.
- Cada app expone `/health` (estado) y `/` (índice de endpoints), y publica una
  imagen Docker propia (`paimon-<app>:local`).
