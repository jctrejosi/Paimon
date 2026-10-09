# audio_processing

API de **transcripción de audio (voz → texto)** de Paimon. Recibe un archivo de
audio ya descargado y devuelve el texto. Es una herramienta independiente del bot
de WhatsApp: aquí no se implementa nada del bot.

Primera versión: **solo local** (CPU). El patrón de proveedores está preparado
para añadir backends cloud (OpenAI, Groq, …) más adelante.

## Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET`  | `/health` | Estado del servicio. |
| `GET`  | `/providers` | Proveedores disponibles y su estado. |
| `POST` | `/transcribe` | Transcribe un audio (`multipart/form-data`). |
| `POST` | `/v1/audio/transcriptions` | Compatible con la API de OpenAI. |

### `POST /transcribe`

Campos (`multipart/form-data`):

- `file` (obligatorio): archivo de audio.
- `language` (opcional): ISO-639-1 o `auto`. Si se omite, se usa el idioma por
  defecto (`AUDIO_DEFAULT_LANGUAGE`, por defecto `es`).
- `model`, `provider` (opcional): override.
- `verbose` (opcional, bool): incluye segmentos con marcas de tiempo.

```bash
curl -s -F file=@audio.ogg http://127.0.0.1:8000/transcribe | jq
```

Respuesta:

```json
{
  "id": "…",
  "provider": "local",
  "model": "base",
  "created": 1700000000,
  "text": "hola, ¿cómo estás?",
  "language": "es",
  "language_probability": 0.98,
  "duration": 3.2,
  "segments": []
}
```

### `POST /v1/audio/transcriptions`

Compatible con los SDK de OpenAI (`response_format`: `json`, `text`, `verbose_json`).
`prompt` y `temperature` se aceptan por compatibilidad pero no se usan todavía.

```bash
curl -s -F file=@audio.ogg -F response_format=text \
  http://127.0.0.1:8000/v1/audio/transcriptions
```

## Ejecución con Docker

```bash
cd audio_processing
AUDIO_API_TOKEN=mi-token docker compose up --build
```

- Escucha solo en loopback (`127.0.0.1:8000`).
- La primera transcripción descarga el modelo y lo cachea en `api/models/`
  (volumen). Las siguientes no lo re-descargan.

## Ejecución local (desarrollo)

```bash
cd audio_processing/api
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

## Pruebas

```bash
cd audio_processing/api
pytest
```

Usan un proveedor falso: no descargan el modelo ni usan red.

## Configuración

| Variable | Default | Uso |
|----------|---------|-----|
| `AUDIO_API_TOKEN` | *(vacío)* | Token Bearer opcional. |
| `AUDIO_PROVIDER` | `local` | Proveedor por defecto. |
| `AUDIO_MAX_UPLOAD_MB` | `25` | Tamaño máximo de subida. |
| `AUDIO_DEFAULT_LANGUAGE` | `es` | Idioma si la petición no especifica uno. |
| `LOCAL_WHISPER_MODEL` | `base` | Modelo: `tiny`/`base`/`small`/`medium`/… |
| `LOCAL_WHISPER_DEVICE` | `cpu` | Dispositivo. |
| `LOCAL_WHISPER_COMPUTE_TYPE` | `int8` | Precisión (rápido en CPU). |
| `WHISPER_MODEL_DIR` | `models` | Caché de pesos. |
