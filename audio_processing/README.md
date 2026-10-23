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
├── eval/                       # banco de WER + verificación (ver eval/README.md)
└── api/
    ├── requirements-dev.txt    # pruebas y lint
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
Añadir un módulo nuevo es crear su carpeta; el registry lo descubre solo. Los
módulos con varios motores (p. ej. `denoise`, `diarize`) guardan sus backends en
`backends/`.

## Endpoints

Ambas APIs exponen una interfaz interactiva: **Swagger UI** en `/docs` (y Redoc
en `/redoc`). Si configuras `AUDIO_API_TOKEN`, usa el botón **Authorize** de
Swagger para probar las rutas protegidas.

### Transcripción

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/transcribe` | Transcribe un audio (`multipart`). Parámetro `preprocess=…`. |
| `POST` | `/v1/audio/transcriptions` | Compatible con la API de OpenAI. |
| `GET` | `/health`, `/providers` | Estado del servicio y proveedores. |
| `GET` | `/` | Índice de endpoints (fuera de OpenAPI). |

Campos de `POST /transcribe` (`multipart/form-data`):

| Campo | Default | Uso |
|---|---|---|
| `file` | — | Audio a transcribir (**único campo obligatorio**). |
| `language` | `AUDIO_DEFAULT_LANGUAGE` (`es`) | ISO-639-1; `auto` fuerza autodetección. |
| `model` | `LOCAL_WHISPER_MODEL` (`small`) | Modelo a usar; en el local **selecciona el modelo** (`base`/`small`/`medium`/...). |
| `provider` | `AUDIO_PROVIDER` (`local`) | Proveedor a usar. |
| `verbose` | `false` | Incluye `segments[]` con marcas de tiempo. |
| `vad` | `true` | VAD (Silero): recorta silencio, reduce alucinaciones. |
| `beam_size` | `5` | Ancho de búsqueda del decodificador (1 = más rápido). |
| `condition_on_previous_text` | `false` | Condicionar al texto previo (False evita bucles). |
| `initial_prompt` | *(vacío)* | Contexto para sesgar nombres/jerga (opcional). |
| `preprocess` | `none` | `none` o un preset (`raw`, `minimal`, `clean`, `noisy`). |

Respuesta `200` (JSON): `id`, `provider`, `model`, `created`, `preprocess`,
`text`, `language`, `language_probability`, `duration` y `segments[]`
(`start`, `end`, `text`; solo con `verbose`).

**`/v1/audio/transcriptions`**: acepta `file`, `model`, `language`,
`response_format` (`json` | `text` | `verbose_json`), `prompt` y `temperature`
(estos dos últimos por compatibilidad; aún no se usan). Usa siempre el
proveedor por defecto. `text` devuelve texto plano; `verbose_json` añade
`language`, `duration` y `segments[]`.

### Preprocesamiento (una API por módulo)

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/processors` | Lista de módulos, disponibilidad y parámetros. |
| `GET` | `/presets` | Presets disponibles y sus pasos. |
| `POST` | `/preprocess` | Aplica un **preset** o una lista de pasos. |
| `GET/POST` | `/preprocess/<módulo>` | **API propia** de cada módulo. |
| `POST` | `/analyze` | Atajo de `/preprocess/analyze`. |

- `GET /preprocess/<módulo>` → información del módulo: `description`, `available`,
  `required_packages` y `params_schema` (JSON Schema de sus parámetros).
- `POST /preprocess/<módulo>` → campos `file`, `params` (JSON del módulo) e
  `include_audio` (añadir el WAV resultante). Devuelve `audios[]` (WAV en base64 +
  `sample_rate` + `duration`), `segments[]`, `metrics` y `elapsed_ms`.
- `POST /preprocess` → campos `file`, `preset` **o** `steps` (lista JSON) e
  `include_audio`. Cada paso admite `"resample"`,
  `{"name": "resample", "params": {…}}` o `{"resample": {…}}`. Devuelve el
  informe por paso (`steps[]`) y el audio final.

### Formatos y límites

- Extensiones aceptadas: `.wav`, `.mp3`, `.m4a`, `.mp4`, `.aac`, `.ogg`, `.oga`,
  `.opus`, `.flac`, `.webm` (las notas de voz de WhatsApp son `.ogg`/opus).
- Tamaño máximo: `AUDIO_MAX_UPLOAD_MB` (25 MB por defecto) → `413` si se supera;
  `415` si la extensión no está soportada; `400` si está vacío o no se puede
  decodificar.
- Si `AUDIO_API_TOKEN` está definido, `/transcribe` y `/v1/audio/transcriptions`
  exigen `Authorization: Bearer <token>` (`401` si falta o no coincide); las
  rutas de preprocesamiento aún no lo exigen.

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
| `denoise` | Reduce ruido: `auto` (noisereduce > spectral), `spectral`, `noisereduce` o `deepfilternet`. | base (`noisereduce` opcional) |
| `dereverb` | Suprime reverberación tardía (WPE). | `nara_wpe` (extras) |
| `diarize` | Etiqueta hablantes (quién habla y cuándo). Backend `ecapa` (speechbrain) **sin credenciales** o `pyannote` (mejor calidad; modelos *gated*). | `speechbrain`+`scikit-learn` (extras) o `pyannote.audio`+`HF_TOKEN` |
| `separate` | Separa fuentes (Demucs); aísla la voz. | `demucs` (extras) |

Los módulos opcionales **no rompen nada** si faltan: se reportan como no
disponibles en `/processors` y responden `503` con un mensaje claro.

### Presets

- `raw`: sin pasos.
- `minimal`: `channels → resample → highpass → normalize`.
- `clean`: `minimal` + `vad`.
- `noisy`: `channels → denoise → resample → highpass → normalize → vad`.

### Diarización: backends `ecapa` y `pyannote`

El módulo `diarize` etiqueta quién habla y cuándo (devuelve `segments[]` con
`speaker`). Tiene dos motores intercambiables; `backend=auto` (por defecto) elige
el mejor instalado:

| Backend | Tecnología | Credenciales | Notas |
|---|---|---|---|
| `ecapa` | speechbrain (embeddings ECAPA) + clustering | **ninguna** | Recomendado para empezar; modelos públicos; CPU. |
| `pyannote` | pyannote.audio | `HF_TOKEN` | Mejor calidad, pero sus modelos son *gated*. |

**¿Qué es un modelo *gated* y qué es `HF_TOKEN`?** Los modelos *gated* de
Hugging Face no son de descarga libre: para usarlos hay que (1) crear una cuenta,
(2) aceptar las condiciones de uso en la página del modelo
(p. ej. [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1))
y (3) crear un *access token* (Settings → Access Tokens) y exportarlo como
`HF_TOKEN`. El token es como una contraseña personal: no se sube al repo; va como
variable de entorno (o en un `.env` local). El backend `ecapa` **no** requiere
nada de esto.

```bash
# Diarización sin credenciales (la 1ª vez descarga el modelo de speechbrain)
curl -s -F file=@audio.ogg -F 'params={"backend":"ecapa","num_speakers":2}' \
  http://127.0.0.1:8100/preprocess/diarize | jq '.segments'

# Con pyannote (requiere HF_TOKEN y aceptar las condiciones del modelo)
curl -s -F file=@audio.ogg -F 'params={"backend":"pyannote"}' \
  http://127.0.0.1:8100/preprocess/diarize | jq '.segments'
```

## Uso

```bash
# Limpieza mínima + transcripción
curl -s -F file=@audio.ogg -F preprocess=minimal \
  http://127.0.0.1:8100/transcribe | jq

# Un módulo suelto (devuelve WAV en base64 + métricas)
curl -s -F file=@audio.ogg -F 'params={"cutoff":120}' \
  http://127.0.0.1:8100/preprocess/highpass | jq '.metrics'

# Pipeline a medida
curl -s -F file=@audio.ogg \
  -F 'steps=[{"name":"denoise"},{"name":"resample","params":{"sample_rate":16000}}]' \
  http://127.0.0.1:8100/preprocess | jq '.steps[].name'
```

## Ejecución

```bash
cd audio_processing
AUDIO_API_TOKEN=mi-token docker compose up --build
```

El puerto del host se puede cambiar con `AUDIO_HOST_PORT` (por defecto `8000`);
`dev.js` lo ajusta automáticamente si está ocupado.

Módulos opcionales (imagen con extras):

```bash
docker build -t paimon-audio-processing:extras \
  --build-arg PIP_EXTRAS=requirements-extras.txt .
# o localmente: pip install -r requirements-extras.txt
```

## Configuración

Se leen de variables de entorno o de un archivo `.env` (no versionado):

| Variable | Default | Uso |
|---|---|---|
| `AUDIO_API_TOKEN` | *(vacío)* | Token Bearer opcional; protege `/transcribe` y `/v1/audio/transcriptions`. |
| `AUDIO_PROVIDER` | `local` | Proveedor de transcripción por defecto. |
| `AUDIO_MAX_UPLOAD_MB` | `25` | Tamaño máximo de subida. |
| `AUDIO_DEFAULT_LANGUAGE` | `es` | Idioma por defecto si la petición no especifica uno (`auto` = autodetección). |
| `LOCAL_WHISPER_MODEL` | `small` | Modelo: `tiny`/`base`/`small`/`medium`/`large-v3-turbo`. |
| `LOCAL_WHISPER_DEVICE` | `cpu` | Dispositivo. |
| `LOCAL_WHISPER_COMPUTE_TYPE` | `int8` | Precisión (rápido en CPU). |
| `LOCAL_WHISPER_VAD` | `true` | VAD (Silero) en la decodificación. |
| `LOCAL_WHISPER_BEAM_SIZE` | `5` | Ancho de búsqueda (1 = más rápido). |
| `LOCAL_WHISPER_CONDITION_ON_PREVIOUS_TEXT` | `false` | Condicionar al texto previo (False evita bucles). |
| `LOCAL_WHISPER_INITIAL_PROMPT` | *(vacío)* | Contexto/vocabulario para sesgar. |
| `WHISPER_MODEL_DIR` | `models` | Caché de pesos. |
| `HF_TOKEN` | *(vacío)* | Token de Hugging Face; solo lo usa la diarización `pyannote` (modelos *gated*). |

## Evaluación (WER)

En [`eval/`](eval/README.md) hay un banco para medir el efecto de cada preset con
voz real (LibriSpeech + ruido a 15/5 dB). Resultado principal:

- **`clean` (cadena mínima + VAD) es el mejor preset**: WER global 0.082 vs 0.116
  sin preprocesar. El **VAD** es lo que más aporta.
- `minimal` no mejora por sí solo; el **denoise no debe activarse por defecto**
  (empeora salvo en ruido severo). Si se usa, `noisereduce` > `spectral`.

### Ajuste del motor (modelo y decodificación)

A/B sobre el mismo set (6 clips × 3 condiciones), mismos datos:

| Configuración | WER global | clean | snr15 | snr5 |
|---|---|---|---|---|
| `base`, sin VAD | 0.110 | 0.081 | 0.100 | 0.148 |
| `base` + VAD | 0.118 | 0.092 | 0.100 | 0.162 |
| `small`, sin VAD | 0.041 | 0.000 | 0.000 | 0.122 |
| **`small` + VAD** | **0.023** | 0.000 | 0.014 | 0.056 |

Conclusiones (son los defaults actuales: `small` + `vad=true` +
`condition_on_previous_text=false`):

1. **El modelo es el factor dominante**: `base`→`small` baja el WER global de 0.110 a 0.041.
2. **El VAD ayuda cuando el modelo es bueno** (con `small`: 0.041 → 0.023), sobre todo en ruido.
3. **`condition_on_previous_text=false`** evita bucles (0.116 → 0.110 en limpio).
4. **Coste**: `small` es ~3× más lento que `base` en CPU (~14-18 s vs ~5-7 s por clip de ~6 s).
   Si priorizas latencia, baja a `base`; si priorizas calidad, sube a `medium`/`large-v3-turbo`.

### Notas de voz reales (español coloquial)

Medido sobre una nota de voz real de WhatsApp (12 s, opus):

| Configuración | WER |
|---|---|
| `small` (sin más) | 0.36 |
| `small` + `preprocess=minimal` | 0.32 |
| `small` + `preprocess=minimal` + `initial_prompt` | **0.05** |

- **`initial_prompt` con el vocabulario del dominio es la palanca clave** (nombres,
  jerga, palabras coloquiales). Pásalo como **lista separada por comas**.
- **No** uses la frase esperada completa: Whisper la trata como texto previo,
  "continúa" y **se salta el audio**. Lista de palabras, no párrafo.
- `preprocess=minimal` (mono + resample + highpass + normalize) ayuda en audio de
  teléfono (retumbe de baja frecuencia).

```bash
curl -s -F file=@nota.ogg \
  -F preprocess=minimal \
  -F 'initial_prompt=Mai, lavar trastes, aseo a esa cocina, ponerme a jartar' \
  http://localhost:8001/transcribe
```

## Pruebas

```bash
cd audio_processing/api
pytest
```

No descargan modelos ni usan red: usan un proveedor falso y audio sintético.
