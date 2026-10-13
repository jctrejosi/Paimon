# App — `audio_processing`

API de **transcripción de audio (voz → texto)** y **preprocesamiento modular**.
Recibe un archivo de audio ya descargado, opcionalmente lo limpia (ruido, formato,
VAD, …) y devuelve el texto. No incluye nada del bot de WhatsApp: es una herramienta
aparte.

- **Carpeta**: `audio_processing/`
- **Código**: `audio_processing/api/app/`
- **README detallado**: [`../../audio_processing/README.md`](../../audio_processing/README.md)

## Componentes

| Pieza | Ubicación | Rol |
|-------|-----------|-----|
| Transcripción | `api/app/providers/` | `LocalWhisperProvider` (faster-whisper, CPU) detrás de una ABC; cloud a futuro. |
| Preprocesamiento | `api/app/preprocessing/` | Módulos tipo *pipes-and-filters* sobre un `AudioClip` común. |
| Núcleo de audio | `api/app/audio/` | Decodificación (PyAV), resample, validación de subidas. |
| Evaluación | `eval/` | Banco de WER para decidir presets con datos. |

Cada módulo de preprocesamiento es autocontenido: `processor.py` (lógica) y
`router.py` (su propia API); el registry los autodescubre. Añadir uno = crear su
carpeta.

## Endpoints

### Transcripción

| Método | Ruta | Descripción |
|--------|------|-------------|
| `POST` | `/transcribe` | Transcribe un audio (`multipart`); acepta `preprocess=`. |
| `POST` | `/v1/audio/transcriptions` | Compatible con la API de OpenAI. |
| `GET`  | `/health`, `/providers` | Estado y proveedores. |
| `GET`  | `/` | Índice de endpoints. |

### Preprocesamiento (una API por módulo)

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET`  | `/processors` | Módulos, disponibilidad y parámetros. |
| `GET`  | `/presets` | Presets y sus pasos. |
| `POST` | `/preprocess` | Aplica un preset o una lista de pasos. |
| `GET/POST` | `/preprocess/<módulo>` | API propia de cada módulo. |
| `POST` | `/analyze` | Atajo de `/preprocess/analyze`. |

## Módulos de preprocesamiento

| Módulo | Qué hace | Disponible con |
|--------|----------|----------------|
| `decode` | ogg/opus, mp3, m4a… → PCM/WAV. | base |
| `channels` | Downmix a mono. | base |
| `resample` | Remuestreo (por defecto 16 kHz). | base (`soxr`) |
| `highpass` | Filtro paso-alto (~80 Hz). | base (`scipy`) |
| `normalize` | Nivel `peak`, `rms` o `lufs`. | base |
| `analyze` | Métricas: pico, RMS, clipping, DC, silencio, bandas, SNR. | base |
| `vad` | Voz (Silero): recorta o separa tramos. | base |
| `denoise` | Reducción de ruido (`auto`/`spectral`/`noisereduce`/`deepfilternet`). | base (`noisereduce` opcional) |
| `dereverb` | Suprime reverberación (WPE). | extras (`nara_wpe`) |
| `diarize` | Etiqueta hablantes (`ecapa` sin credenciales o `pyannote` gated). | extras / `HF_TOKEN` |
| `separate` | Separa fuentes (Demucs); aísla la voz. | extras (`demucs`) |

Los módulos opcionales **no rompen nada** si faltan: se reportan como no disponibles
en `/processors` y responden `503`.

### Presets

- `raw`: sin pasos.
- `minimal`: `channels → resample → highpass → normalize`.
- `clean`: `minimal` + `vad`.
- `noisy`: `channels → denoise → resample → highpass → normalize → vad`.

## Configuración

Desde variables de entorno o un `.env` (no versionado):

| Variable | Default | Uso |
|----------|---------|-----|
| `AUDIO_API_TOKEN` | *(vacío)* | Token Bearer opcional (`/transcribe`). |
| `AUDIO_PROVIDER` | `local` | Proveedor de transcripción por defecto. |
| `AUDIO_MAX_UPLOAD_MB` | `25` | Tamaño máximo de subida. |
| `AUDIO_DEFAULT_LANGUAGE` | `es` | Idioma si no se especifica (`auto` = autodetección). |
| `LOCAL_WHISPER_MODEL` | `small` | Modelo: `tiny`/`base`/`small`/`medium`/`large-v3-turbo`. |
| `LOCAL_WHISPER_DEVICE` | `cpu` | Dispositivo. |
| `LOCAL_WHISPER_COMPUTE_TYPE` | `int8` | Precisión (rápido en CPU). |
| `LOCAL_WHISPER_VAD` | `true` | VAD (Silero) en la decodificación. |
| `LOCAL_WHISPER_BEAM_SIZE` | `5` | Ancho de búsqueda (1 = más rápido). |
| `LOCAL_WHISPER_CONDITION_ON_PREVIOUS_TEXT` | `false` | Condicionar al texto previo (False evita bucles). |
| `LOCAL_WHISPER_INITIAL_PROMPT` | *(vacío)* | Vocabulario/contexto para sesgar (jerga, nombres). |
| `WHISPER_MODEL_DIR` | `models` | Caché de pesos (volumen). |
| `HF_TOKEN` | *(vacío)* | Solo para diarización `pyannote` (modelos *gated*). |

## Ejecución

```bash
# Con Docker (recomendado)
cd audio_processing
docker compose up --build           # API en 127.0.0.1:8000

# O con el lanzador
node dev.js --audio
```

Con los módulos opcionales (imagen con extras):

```bash
docker build -t paimon-audio-processing:extras \
  --build-arg PIP_EXTRAS=requirements-extras.txt .
```

## Pruebas

```bash
cd audio_processing/api
pytest
```

No descargan modelos ni usan red: usan un proveedor falso y audio sintético.

## Evaluación (WER)

En `eval/` hay un banco que mide el efecto de cada preset con voz real
(LibriSpeech) y ruido a 15/5 dB. Conclusiones vigentes:

- **`clean` (cadena mínima + VAD) es el mejor preset**; el **VAD** es lo que más
  aporta en preprocesamiento y el **denoise no debe activarse por defecto**.
- En el **motor**, el modelo es el factor dominante (`base`→`small` bajó el WER de
  0.110 a 0.023 con VAD) y el **`initial_prompt`** con vocabulario es la palanca
  clave en español coloquial. Detalle en
  [`../audio_processing/transcription.md`](../audio_processing/transcription.md) y
  [`../../audio_processing/eval/README.md`](../../audio_processing/eval/README.md).
