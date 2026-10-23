# Plan — `audio_generator` (síntesis y clonación de voz, texto → audio)

Estado: **borrador / investigación**. Motor: **multi-proveedor**, local-first.

## 1. Objetivo y alcance

Construir una **API que reciba texto y devuelva audio con la voz seleccionada**
(TTS), más una **API para crear voces**: subir audios de referencia (clonación
zero-shot) y, opcionalmente, entrenar con tu propia voz (fine-tuning).

**Estrategia de motor (clave):** en esta máquina no hay GPU, así que el "tiempo
real" se consigue con un modelo **ligero** (Kokoro-82M). La **clonación de voz** en
local se hace con **XTTS-v2** (zero-shot). El motor pesado (**CosyVoice 3.0**) se
reserva para el **servidor con GPU**, detrás de la misma interfaz. Ver
[`docs/reference/tts_alternatives.md`](../docs/reference/tts_alternatives.md).

### Dentro del alcance (v1)

- `POST /synthesize` con texto + voz seleccionada → archivo de audio (WAV).
- `POST /synthesize/stream` → audio **por chunks** (streaming de salida).
- `WS /synthesize/ws` → streaming **bidireccional** (texto por chunks → audio por
  chunks), para el caso "muy en tiempo real".
- `GET /voices` + `POST /voices` (clonar una voz desde un audio de referencia) +
  `DELETE /voices/{id}`: una **librería de voces** seleccionables.
- `POST /voices/train` → **job asíncrono** de fine-tuning (se activa cuando haya GPU).
- Endpoints de soporte `/health` y `/providers` (patrón Paimon).

### Fuera del alcance (por ahora)

- El bot de WhatsApp y su integración (enviar/recibir notas de voz).
- Traducción y conversión de voz (`inference_vc`): se dejan listas a nivel de contrato.
- Proveedores cloud (OpenAI TTS, ElevenLabs, etc.): listos a nivel de arquitectura.

## 2. Decisiones congeladas

| # | Decisión |
|---|----------|
| 1 | **Multi-proveedor** detrás de una ABC: `kokoro` (tiempo real), `xtts` (clonación), `cosyvoice` (GPU, futuro). |
| 2 | Proveedor por defecto local: **Kokoro-82M** (Apache-2.0, español, RTF ≪ 1). |
| 3 | Clonación de voz en v1 por **zero-shot** (XTTS-v2), no por fine-tuning. |
| 4 | Fine-tuning como **job asíncrono** (CosyVoice en GPU), fuera del camino crítico. |
| 5 | Nombre del módulo: **`audio_generator/`** (carpeta ya existente). |
| 6 | **Streaming es un requisito de primera clase**, no un extra. |

Resueltas posteriormente (a confirmar, ver §16):

| # | Decisión |
|---|----------|
| 2b | Voces por defecto de Kokoro (idioma `es` y qué voces exponer). |
| 3b | Formato de salida por defecto (WAV vs. PCM para streaming). |
| 4b | Persistencia de voces y audios (volumen `voices/`). |
| 5b | Si XTTS-v2 entra pese a su licencia **CPML no comercial**. |

## 3. Encaje en el proyecto

Reutilizamos el patrón ya validado en `image_generator/api` y `audio_processing`:

- `providers/base.py` con una ABC, `registry.py`, `config.py`, `schemas.py`, `main.py`.
- **Local por defecto**, cloud opcional. Token opcional/por `API_KEYS`.
- **Streaming**: SSE de `image_generator` como base + **WebSocket** bidireccional.
- **Entrenamiento**: patrón `jobs/` de `image_generator` (submit → poll → eventos).

> **Nota de nomenclatura:** en `plans/apps_future.md` (ítem 4) esto es
> `text_to_speech/`. Usamos `audio_generator/` (carpeta ya creada) y alineamos el
> roadmap (ver §16).

## 4. Motor local: elección y justificación

**Hardware real de esta máquina:** AMD Ryzen 5 3500U (4C/8T, Zen+ 2019), 29 GB RAM,
iGPU Vega (sin ROCm/NVIDIA utilizable). Un LLM de 0.5B (CosyVoice) o un DiT de 0.3B
(F5-TTS) dan RTF ≫ 1 en CPU: no sirven para tiempo real local.

| Rol | Motor | Por qué |
|-----|-------|---------|
| **Síntesis en tiempo real (ahora)** | **Kokoro-82M** | 82M params, Apache-2.0, español, RTF ≪ 1 en CPU |
| **Clonación zero-shot (ahora)** | **XTTS-v2** | ~6 s de referencia → voz clonada, español, corre en CPU (lento) |
| **Producción (servidor con GPU)** | **CosyVoice 3.0** | calidad, clonación + fine-tuning + instruct + streaming |

Comparativa completa y licencias en
[`docs/reference/tts_alternatives.md`](../docs/reference/tts_alternatives.md).

### 4.1 Nota de licencia

- **Kokoro**: Apache-2.0 → sin restricciones.
- **XTTS-v2**: **CPML (no comercial)** ⚠️ → solo para uso no comercial; a validar.
- **F5-TTS**: pesos CC-BY-NC ⚠️ → alternativa GPU con la misma limitación.
- **CosyVoice 3.0**: Apache-2.0 → ideal para producción en GPU.

## 5. Funcionalidades

### 5.1 Síntesis (`POST /synthesize`)

- Entrada: `text` + `voice_id` (+ `speed`, `instruct`, `format`).
- Salida: `audio/wav` (o `audio/pcm`) con la voz elegida.
- El `voice_id` pertenece a un proveedor (`kokoro`, `xtts`, `cosyvoice`…); la voz
  indica qué proveedor la genera.

### 5.2 Clonación zero-shot (`POST /voices`)

- Entrada: audio de referencia (~6 s) + nombre (+ `prompt_text` opcional).
- Acción: extrae el *speaker embedding* y guarda la voz (`voice_id`).
- Efecto: la voz queda **seleccionable** para sintetizar. Sin entrenamiento.

### 5.3 Entrenamiento / fine-tuning (`POST /voices/train`)

- Entrada: conjunto de audios + transcripciones (zip de pares `wav`+`txt`, o LibriTTS).
- Acción: prepara datos → entrena → exporta → registra el hablante.
- **Job asíncrono** (GPU-bound); en local queda deshabilitado (proveedor no configurado).

### 5.4 Streaming

- `POST /synthesize/stream`: texto completo → audio por chunks.
- `WS /synthesize/ws`: texto por chunks → audio por chunks (bi-streaming), para
  agentes de voz en tiempo real. Servido principalmente por **Kokoro** en local.

## 6. Contrato de la API

### `POST /synthesize`

```json
{
  "text": "Hola, ¿en qué puedo ayudarte?",
  "voice_id": "es-ef-01",
  "speed": 1.0,
  "format": "wav"
}
```

Respuesta `200`: `audio/wav` con cabeceras `X-Voice-Id`, `X-Provider`,
`X-Sample-Rate`, `X-Duration-Sec`. Alternativa `format: "json"` (base64 + metadatos).

### `POST /synthesize/stream`

Igual, pero respuesta `audio/pcm` por chunks o `text/event-stream` con eventos
`chunk` (base64) y `done` (metadatos).

### `WS /synthesize/ws`

- Cliente: `{ "type": "start", "voice_id": "..." }`, luego `{ "type": "text", "data": "..." }` (varios) y `{ "type": "end" }`.
- Servidor: `{ "type": "audio", "data": <base64 pcm>, "sample_rate": 24000 }` por chunk, y `{ "type": "done" }`.

### Voces

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/voices` | Lista de voces (con su `provider`). |
| `POST` | `/voices` | Crea una voz desde un audio de referencia (zero-shot). |
| `GET` | `/voices/{voice_id}` | Metadatos de una voz. |
| `DELETE` | `/voices/{voice_id}` | Elimina una voz clonada. |

### Entrenamiento (jobs)

| Método | Ruta | Descripción |
|--------|------|-------------|
| `POST` | `/voices/train` | Encola un fine-tuning; devuelve `job_id` (202). |
| `GET` | `/jobs/{job_id}` | Estado del job. |
| `GET` | `/jobs/{job_id}/events` | SSE con el progreso. |
| `DELETE` | `/jobs/{job_id}` | Cancela el job. |

### Soporte

- `GET /health` → estado + proveedores configurados + modelo cargado.
- `GET /providers` → lista de proveedores y su estado.
- `GET /` → índice de endpoints.

## 7. Modelo de datos

**Voz** (`voice_id`), con el proveedor explícito:

```json
{
  "voice_id": "clon-juan-01",
  "name": "Juan",
  "provider": "xtts",
  "kind": "zero_shot",
  "model": "XTTS-v2",
  "sample_rate": 24000,
  "language": "es",
  "created_at": "2026-10-23T12:00:00Z"
}
```

- `kind ∈ {builtin, zero_shot, finetuned}`.
- `builtin` = voces fijas de Kokoro/CosyVoice; `zero_shot` = embeddings guardados;
  `finetuned` = hablante entrenado (GPU).

**Job de entrenamiento** (espejo de `image_generator`): `{ id, status, provider,
stage, progress, voice_id }`.

## 8. Configuración (variables de entorno)

| Variable | Default | Uso |
|----------|---------|-----|
| `TTS_API_TOKEN` | *(vacío)* | Token Bearer opcional (además de `API_KEYS`). |
| `TTS_PROVIDER` | `kokoro` | Proveedor por defecto. |
| `TTS_MAX_TEXT_LENGTH` | `1000` | Longitud máxima de texto. |
| `TTS_MAX_UPLOAD_MB` | `25` | Tamaño máximo de subida. |
| `TTS_DEVICE` | `cpu` | `cpu` o `cuda` (si hay GPU). |
| `VOICES_DIR` | `voices` | Librería de voces (volumen). |
| `OUTPUT_DIR` | `outputs` | Audios generados (volumen). |
| `JOB_EXECUTION` | `inline` | `inline` o `worker`. |
| `JOB_STORE` | `memory` | `memory` o `redis`. |
| `JOB_STREAM_POLL` | `2.0` | Poll del SSE de jobs. |
| — Kokoro | | |
| `KOKORO_LANG` | `e` | Idioma (`e`=es). |
| `KOKORO_DEFAULT_VOICE` | *(primer voz es)* | Voz por defecto. |
| `KOKORO_MODEL` | `Kokoro-82M` | Modelo (descarga desde HF). |
| — XTTS-v2 | | |
| `XTTS_MODEL_DIR` | `models/xtts` | Pesos de XTTS (volumen). |
| `XTTS_LANGUAGE` | `es` | Idioma por defecto. |
| — CosyVoice (futuro/GPU) | | |
| `COSYVOICE_MODEL_DIR` | `models/cosyvoice` | Pesos de CosyVoice. |
| `COSYVOICE_MODEL` | `Fun-CosyVoice3-0.5B` | Modelo a usar. |

## 9. Estructura de archivos propuesta

```
audio_generator/
├── Dockerfile                # python:3.11-slim + torch CPU (+ espeak-ng, sox, ffmpeg)
├── docker-compose.yml        # loopback, volumen models/ + voices/ + outputs/
├── requirements.txt
├── requirements-gpu.txt      # (opcional) extras CUDA para el servidor
├── .dockerignore
├── .gitignore
└── api/
    ├── app/
    │   ├── __init__.py
    │   ├── config.py         # Settings (pydantic-settings)
    │   ├── schemas.py        # SynthesizeRequest, Voice, Job, Health...
    │   ├── main.py           # FastAPI: /synthesize, /voices, /jobs, WS
    │   ├── streaming.py      # chunked + WebSocket
    │   ├── voices.py         # librería de voces (persistencia)
    │   ├── jobs/             # (espejo image_generator) submit/runner/store/bus
    │   └── providers/
    │       ├── __init__.py
    │       ├── base.py       # TTSSynthesizer (ABC) + TTSProviderError
    │       ├── kokoro.py     # KPipeline (tiempo real, voces fijas)
    │       ├── xtts.py       # XTTS-v2 (clonación zero-shot)
    │       ├── cosyvoice.py  # (futuro/GPU)
    │       └── registry.py   # ProviderManager
    └── tests/
        ├── conftest.py
        ├── test_api.py       # proveedor falso (sin modelos/red)
        └── fixtures/sample.wav
```

Contrato del proveedor (`providers/base.py`):

```python
class TTSSynthesizer(ABC):
    name: ClassVar[str]

    @classmethod
    def is_configured(cls, settings) -> bool: ...

    @abstractmethod
    async def synthesize(self, request: SynthesizeRequest) -> SynthesisResult: ...

    @abstractmethod
    async def synthesize_stream(self, request: SynthesizeRequest) -> AsyncIterator[AudioChunk]: ...

    @abstractmethod
    async def list_voices(self) -> list[Voice]: ...

    # solo proveedores con clonación (xtts/cosyvoice); kokoro lanza NotImplemented
    @abstractmethod
    async def create_voice(self, audio: bytes, prompt_text: str, name: str) -> Voice: ...

    @abstractmethod
    async def delete_voice(self, voice_id: str) -> None: ...

    async def aclose(self) -> None: ...
```

- `supports_cloning: ClassVar[bool]` indica si el proveedor puede crear voces.
- `SynthesisResult` = audio + metadatos; `AudioChunk` = fragmento PCM + índice + flag final.

## 10. Concurrencia y despliegue

- Cada proveedor **no es thread-safe** para inferencia concurrente: lock + ejecución
  fuera del event loop (`anyio.to_thread`). Kokoro puede admitir un pequeño pool;
  XTTS/CosyVoice van en serie.
- Los modelos se cargan **una vez** en el lifespan y quedan en memoria.
- `Dockerfile`: base `python:3.11-slim` + `torch` CPU + `espeak-ng`, `sox`, `ffmpeg`.
  Usuario no-root. Para GPU (servidor), `requirements-gpu.txt`.
- `docker-compose.yml`: loopback, volúmenes `models/`, `voices/`, `outputs/`.
- `.gitignore`: `api/models/`, `api/voices/`, `api/outputs/`, `api/.env`.

## 11. Fases

- **Fase 0 — Viabilidad y medición (bloqueante)**
  - [ ] Instalar `kokoro` + `torch` CPU en esta máquina y cargar `Kokoro-82M`.
  - [ ] **Medir RTF** de Kokoro (español) en esta máquina; confirmar tiempo real.
  - [ ] Evaluar XTTS-v2 en CPU (RTF de clonación/síntesis) para acotar su uso.
  - [ ] Con los números, congelar la decisión de streaming (ver §16).
- **Fase 1 — Andamiaje**
  - [ ] `providers/base.py` (ABC), `registry.py`, `schemas.py`, `config.py`.
  - [ ] `main.py` con `/synthesize` (`FakeProvider`) + `/health` + `/providers`.
  - [ ] Tests con proveedor falso (sin modelos/red).
- **Fase 2 — Kokoro (tiempo real)**
  - [ ] `providers/kokoro.py`: `synthesize` + `list_voices` (voces fijas en español).
  - [ ] `Dockerfile` + `docker-compose.yml` + `.dockerignore`/`.gitignore`.
- **Fase 3 — Streaming**
  - [ ] `POST /synthesize/stream` (audio por chunks).
  - [ ] `WS /synthesize/ws` (bi-streaming).
  - [ ] Medición de latencia (first-byte / RTF).
- **Fase 4 — Clonación (XTTS-v2)**
  - [ ] `providers/xtts.py`: `create_voice` (zero-shot) + `synthesize` con voz clonada.
  - [ ] `voices.py` + `POST /voices` + `GET/DELETE /voices`.
- **Fase 5 — Entrenamiento y GPU (servidor)**
  - [ ] `jobs/` (espejo `image_generator`) + `POST /voices/train`.
  - [ ] `providers/cosyvoice.py` (o F5-TTS) detrás de la misma ABC.
- **Fase 6 — Validación**
  - [ ] Smoke test en español: síntesis Kokoro + clonación XTTS.
  - [ ] Probar streaming end-to-end; medir latencia.
  - [ ] Documentar uso en `audio_generator/README.md` y `docs/apps/audio_generator.md`.

## 12. Pruebas

- **Test unitario/HTTP con proveedor falso**: sin modelos/red; valida contrato,
  errores (sin `text` → 422), token, listado de voces y ciclo de jobs.
- **Smoke test local (Kokoro)**: sintetizar una frase en español y verificar audio
  no vacío y RTF < 1.
- **Smoke test de clonación (XTTS)**: `POST /voices` con `fixtures/sample.wav` y
  sintetizar con la voz creada.

## 13. Criterios de aceptación de v1

- `docker compose up` levanta la API en CPU, en loopback.
- `POST /synthesize` con `voice_id` de Kokoro devuelve un WAV audible en español.
- `POST /synthesize/stream`/`WS` entregan el primer chunk en tiempo real (RTF ≤ 1).
- `POST /voices` (XTTS) crea una voz clonada que luego sintetiza.
- Los tests con proveedor falso pasan sin red ni descarga de modelos.
- `/health`, `/providers` y `/voices` responden correctamente.

## 14. Riesgos y consideraciones

| Riesgo | Mitigación |
|--------|------------|
| "Tiempo real" no se cumple en esta CPU | Medir RTF en Fase 0 (Kokoro debería cumplir de sobra) |
| XTTS-v2 lento en CPU (RTF > 1) | Clonación como operación no-crítica; sintetizar con Kokoro cuando se pueda |
| **Licencia CPML de XTTS-v2 (no comercial)** | Confirmar uso; si no aplica, clonación solo en GPU (CosyVoice Apache-2.0) |
| Kokoro no clona voces | Cubrir clonación con XTTS/CosyVoice detrás de la misma ABC |
| Modelos no thread-safe | Lock + `to_thread`; cola por proveedor |
| Descargas de pesos (Kokoro ~90 MB, XTTS ~2 GB, CosyVoice ~GBs) | Cachear en volumen `models/`; documentar tamaños |
| Dependencias de G2P (espeak-ng) en la imagen | Instalar `espeak-ng` en el Dockerfile |
| Fine-tuning inviable en CPU | Job asíncrono solo cuando haya GPU |

## 15. Decisiones resueltas

1. **Nombre del módulo:** `audio_generator/`. ✅
2. **Estrategia:** multi-proveedor (Kokoro + XTTS + CosyVoice) tras una ABC. ✅
3. **Tiempo real local:** Kokoro-82M (Apache-2.0, español, RTF ≪ 1). ✅
4. **Clonación local:** XTTS-v2 zero-shot (con aviso de licencia). ✅
5. **Producción GPU:** CosyVoice 3.0, mismo contrato. ✅

## 16. Preguntas abiertas

1. **Licencia XTTS-v2 (CPML no comercial):** ¿el uso es no comercial? Si no, la
   clonación local se pospone y solo se activa en el servidor con CosyVoice (Apache-2.0).
2. ¿Persistimos los audios de referencia de las voces clonadas o solo el embedding?
3. ¿Qué voces de Kokoro en español exponemos por defecto (y nombres legibles)?
4. ¿Formato de salida por defecto: WAV (compatibilidad) o PCM (streaming eficiente)?
5. ¿Priorizamos Kokoro (tiempo real) antes que XTTS (clonación), o en paralelo?
6. Para el servidor con GPU: ¿CosyVoice 3.0 o F5-TTS como motor de clonación+calidad?
