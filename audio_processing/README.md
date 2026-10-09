# audio_processing

API de **transcripción de audio (voz → texto)** y **preprocesamiento modular** de
Paimon. Recibe un archivo de audio ya descargado, opcionalmente lo limpia
(ruido, formato, VAD, ...) y devuelve el texto. El bot de WhatsApp es otra
herramienta: aquí no se implementa nada del bot.

- **Transcripción**: local-first (faster-whisper en CPU); los proveedores cloud
  se añadirán detrás de la misma interfaz.
- **Preprocesamiento**: cada técnica es un **módulo independiente** con su
  **API propia**; además se pueden **encadenar** en un pipeline.

## Estructura

```
audio_processing/
├── Dockerfile / docker-compose.yml
├── requirements.txt            # base (transcripción + cadena mínima)
├── requirements-extras.txt     # módulos opcionales pesados
└── api/
    ├── app/
    │   ├── audio/              # núcleo: AudioClip, decode/encode, resample
    │   ├── deps.py             # token, validación y decodificación de subidas
    │   ├── providers/          # transcripción (local; cloud a futuro)
    │   ├── preprocessing/
    │   │   ├── base.py         # Processor (ABC) + ProcessorResult
    │   │   ├── pipeline.py     # encadenado de módulos
    │   │   ├── presets.py       # raw | minimal | clean | noisy
    │   │   ├── registry.py     # autodescubre los módulos
    │   │   ├── router_factory.py # genera la API propia de cada módulo
    │   │   ├── api.py          # router agregado (/processors, /preprocess, ...)
    │   │   └── modules/        # 👈 UNA CARPETA POR MÓDULO
    │   │       ├── decode/     #   processor.py (lógica) + router.py (API)
    │   │       ├── channels/
    │   │       ├── resample/
    │   │       ├── highpass/
    │   │       ├── normalize/
    │   │       ├── analyze/
    │   │       ├── vad/
    │   │       ├── denoise/
    │   │       ├── dereverb/
    │   │       ├── diarize/
    │   │       └── separate/
    │   ├── schemas.py  config.py  main.py
    └── tests/
```

Cada módulo es autocontenido: `processor.py` (la lógica) y `router.py` (su API).
Añadir un módulo nuevo es crear su carpeta; el registry lo descubre solo.

## Endpoints

### Transcripción

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/transcribe` | Transcribe un audio (`multipart`). Parámetro `preprocess=…`. |
| `POST` | `/v1/audio/transcriptions` | Compatible con la API de OpenAI. |
| `GET` | `/health`, `/providers` | Estado del servicio y proveedores. |

### Preprocesamiento (una API por módulo)

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/processors` | Lista de módulos, disponibilidad y parámetros. |
| `GET` | `/presets` | Presets disponibles y sus pasos. |
| `POST` | `/preprocess` | Aplica un **preset** o una lista de pasos. |
| `GET/POST` | `/preprocess/<módulo>` | **API propia** de cada módulo. |
| `POST` | `/analyze` | Atajo de `/preprocess/analyze`. |

## Módulos

| Módulo | Qué hace | Disponible con |
|---|---|---|
| `decode` | Decodifica ogg/opus, mp3, m4a... a PCM/WAV. | base |
| `channels` | Downmix a mono (o primer canal). | base |
| `resample` | Remuestrea (por defecto 16 kHz). | base (`soxr`) |
| `highpass` | Filtro paso-alto (~80 Hz) contra retumbe. | base (`scipy`) |
| `normalize` | Normaliza nivel: `peak`, `rms` o `lufs`. | base (`lufs`→`pyloudnorm`) |
| `analyze` | Métricas: pico, RMS, clipping, DC, silencio, bandas, SNR. | base |
| `vad` | Voz (Silero, incluido en faster-whisper): recorta o separa tramos. | base |
| `denoise` | Reduce ruido: `spectral` (propio) o `deepfilternet`. | `spectral` en base |
| `dereverb` | Suprime reverberación tardía (WPE). | `nara_wpe` (extras) |
| `diarize` | Etiqueta hablantes (pyannote). | `pyannote.audio` + `HF_TOKEN` |
| `separate` | Separa fuentes (Demucs); aísla la voz. | `demucs` (extras) |

Los módulos opcionales **no rompen nada** si faltan: se reportan como no
disponibles en `/processors` y responden `503` con un mensaje claro.

### Presets

- `raw`: sin pasos.
- `minimal`: `channels → resample → highpass → normalize`.
- `clean`: `minimal` + `vad`.
- `noisy`: `channels → denoise → resample → highpass → normalize → vad`.

## Uso

```bash
# Limpieza mínima + transcripción
curl -s -F file=@audio.ogg -F preprocess=minimal \
  http://127.0.0.1:8000/transcribe | jq

# Un módulo suelto (devuelve WAV en base64 + métricas)
curl -s -F file=@audio.ogg -F 'params={"cutoff":120}' \
  http://127.0.0.1:8000/preprocess/highpass | jq '.metrics'

# Pipeline a medida
curl -s -F file=@audio.ogg \
  -F 'steps=[{"name":"denoise"},{"name":"resample","params":{"sample_rate":16000}}]' \
  http://127.0.0.1:8000/preprocess | jq '.steps[].name'
```

## Ejecución

```bash
cd audio_processing
AUDIO_API_TOKEN=mi-token docker compose up --build
```

Módulos opcionales (imagen con extras):

```bash
docker build -t paimon-audio-processing:extras \
  --build-arg PIP_EXTRAS=requirements-extras.txt .
# o localmente: pip install -r requirements-extras.txt
```

## Configuración

| Variable | Default | Uso |
|---|---|---|
| `AUDIO_API_TOKEN` | *(vacío)* | Token Bearer opcional. |
| `AUDIO_PROVIDER` | `local` | Proveedor de transcripción por defecto. |
| `AUDIO_MAX_UPLOAD_MB` | `25` | Tamaño máximo de subida. |
| `AUDIO_DEFAULT_LANGUAGE` | `es` | Idioma si la petición no especifica uno. |
| `LOCAL_WHISPER_MODEL` | `base` | Modelo: `tiny`/`base`/`small`/... |
| `LOCAL_WHISPER_DEVICE` | `cpu` | Dispositivo. |
| `LOCAL_WHISPER_COMPUTE_TYPE` | `int8` | Precisión (rápido en CPU). |
| `WHISPER_MODEL_DIR` | `models` | Caché de pesos. |
| `HF_TOKEN` | *(vacío)* | Token de Hugging Face (diarización). |

## Pruebas

```bash
cd audio_processing/api
pytest
```

No descargan modelos ni usan red: usan un proveedor falso y audio sintético.
