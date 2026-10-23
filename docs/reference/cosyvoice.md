# Referencia — CosyVoice (`FunAudioLLM/CosyVoice`)

Revisión del repositorio público **CosyVoice** para construir el módulo
`audio_generator` de Paimon (texto → voz + clonación de voz).

| Dato | Valor |
|------|-------|
| Repositorio | <https://github.com/FunAudioLLM/CosyVoice> |
| URL alternativa | <https://github.com/QwenAudio/CosyVoice> (mismo equipo, Alibaba Qwen) |
| Commit revisado | `074ca6d` (2026-05-26) |
| Licencia | Apache-2.0 |
| Stack | Python 3.10, PyTorch 2.3.1, ONNX Runtime, FastAPI/gRPC, vLLM/TensorRT-LLM, Matcha-TTS (submódulo) |
| Clon local | `reference/CosyVoice/` (**ignorado por git**, clon superficial sin submódulos) |
| Tamaño del clon | ~1.5 MiB (código; sin submódulos ni pesos de modelos) |

## 1. Qué es

CosyVoice es un sistema **TTS multi-idioma basado en LLM** de Alibaba
(equipo FunAudioLLM). Cubre síntesis de voz, **clonación zero-shot** (imitar una
voz con pocos segundos de referencia), conversión de voz, control por
instrucciones (emoción, dialecto, velocidad) y **fine-tuning** (entrenar con tu
propia voz). Tiene **tres generaciones**:

| Generación | Tamaño | Idiomas | Destacado |
|------------|--------|---------|-----------|
| CosyVoice 1.0 | 300M | zh / en / ja / yue / ko | SFT, zero-shot, cross-lingual, instruct, voice conversion |
| CosyVoice 2.0 | 0.5B | zh / en / ja / yue / ko | Streaming (25 Hz), instruct2, bi-streaming |
| **Fun-CosyVoice 3.0** | 0.5B | **9 idiomas (incl. español)**, 18+ dialectos chinos | Bi-streaming (texto→audio, ~150 ms), instruct, inpainting de pronunciación |

> **Clave para Paimon:** el proyecto es hispanohablante y CosyVoice 1.0/2.0 **no
> soportan español** (solo zh/en/ja/yue/ko). El español llega con **CosyVoice 3.0**
> (`Fun-CosyVoice3-0.5B`), que además es el modelo recomendado en el README.

## 2. Arquitectura del repositorio

| Carpeta | Rol |
|---------|-----|
| `cosyvoice/cli/` | API de alto nivel: `AutoModel` (`cosyvoice.py`), `frontend.py` (tokenizador, normalización de texto, embeddings), `model.py` (cablea LLM + Flow + HiFiGAN). |
| `cosyvoice/llm/` | El LLM autoregresivo (basado en **Qwen2**): genera tokens de habla. |
| `cosyvoice/flow/` | Modelo de **Flow Matching** (+ variante **DiT** en CosyVoice3) que convierte tokens → mel. |
| `cosyvoice/hifigan/` | **Vocoder** HiFi-GAN (mel → forma de onda). |
| `cosyvoice/tokenizer/` | Tokenizador de habla (códice) y assets. |
| `cosyvoice/bin/` | Scripts: `train.py`, `average_model.py`, `export_jit.py`, `export_onnx.py`. |
| `cosyvoice/dataset/`, `transformer/`, `utils/`, `vllm/` | Datasets, bloques de atención, utilidades y soporte vLLM. |
| `runtime/python/fastapi/` | Servidor FastAPI de ejemplo (`server.py`) con `StreamingResponse` de PCM int16. |
| `runtime/python/grpc/` | Servidor gRPC (misma funcionalidad, `--max_conc`). |
| `runtime/triton_trtllm/` | Despliegue con **TensorRT-LLM** (aceleración NVIDIA ~4×). |
| `examples/libritts/` | Scripts de **entrenamiento** (cosyvoice/cosyvoice2/cosyvoice3). |
| `examples/grpo/`, `examples/magicdata-read/` | Entrenamiento RL (GRPO) y lectura de datos MagicData. |
| `third_party/Matcha-TTS` | **Submódulo** (Flow Matching). Requerido para inferencia y entrenamiento. |
| `tools/` | `extract_embedding.py`, `extract_speech_token.py`, `make_parquet_list.py` (preparación de datos). |
| `docker/`, `webui.py`, `example.py`, `vllm_example.py` | Imagen, demo web Gradio y ejemplos de uso. |

**Clave para Paimon:** CosyVoice ya trae un servidor FastAPI, pero es un ejemplo
acoplado a su propio CLI (carga el modelo en `__main__`, sin auth, sin patrón de
proveedores, sin jobs). Lo reusamos como **inspiración del contrato de streaming**,
no como código a copiar tal cual.

## 3. API de inferencia (`AutoModel`)

El punto de entrada es `cosyvoice.cli.cosyvoice.AutoModel(model_dir=...)`, que
detecta la generación por el `cosyvoice*.yaml` y devuelve `CosyVoice`, `CosyVoice2`
o `CosyVoice3`. Métodos relevantes:

| Método | Qué hace | Parámetros clave |
|--------|----------|------------------|
| `inference_sft(tts_text, spk_id, ...)` | Sintetizar con un hablante **pretrained** (`spk_id`). | `stream`, `speed` |
| `inference_zero_shot(tts_text, prompt_text, prompt_wav, ...)` | **Clonar voz al vuelo** con un audio de referencia. | `stream`, `speed`, `zero_shot_spk_id` |
| `inference_cross_lingual(tts_text, prompt_wav, ...)` | Sintetizar en otro idioma con una voz de referencia. | `stream`, `speed` |
| `inference_vc(source_wav, prompt_wav, ...)` | **Conversión de voz** (timbre de `prompt_wav` al contenido de `source_wav`). | `stream`, `speed` |
| `inference_instruct` / `inference_instruct2` | Control por instrucciones (emoción, dialecto, velocidad, `<laughter>`, `[breath]`…). | `stream`, `speed` |
| `add_zero_shot_spk(prompt_text, prompt_wav, spk_id)` + `save_spkinfo()` | **Guardar una voz clonada** (embedding) en la librería para reusarla por `spk_id`. | — |
| `list_available_spks()` | Listar hablantes disponibles. | — |

- `stream=True` activa la **generación por chunks** (bi-streaming: texto por chunks
  de entrada + audio por chunks de salida).
- Cada `yield` devuelve un dict con `tts_speech` (tensor) a `sample_rate`
  (22 050 Hz en v1; 24 000 Hz en v2/v3).

## 4. Modelos y recursos

Se descargan desde ModelScope o HuggingFace (IDs):

| Modelo | ModelScope | HuggingFace |
|--------|-----------|-------------|
| Fun-CosyVoice3-0.5B-2512 | `FunAudioLLM/Fun-CosyVoice3-0.5B-2512` | `FunAudioLLM/Fun-CosyVoice3-0.5B-2512` |
| CosyVoice2-0.5B | `iic/CosyVoice2-0.5B` | `FunAudioLLM/CosyVoice2-0.5B` |
| CosyVoice-300M(-SFT/-Instruct) | `iic/CosyVoice-300M*` | `FunAudioLLM/CosyVoice-300M*` |
| CosyVoice-ttsfrd | `iic/CosyVoice-ttsfrd` | `FunAudioLLM/CosyVoice-ttsfrd` |

Cada modelo incluye `llm.pt`, `flow.pt`, `hift.pt`, `campplus.onnx` (embedding de
hablante), `speech_tokenizer_v{1,2,3}.onnx` (códice de audio), `spk2info.pt` (lista
SFT) y el `cosyvoice*.yaml`. CosyVoice2/3 referencian además el tokenizador
**Qwen2** (`CosyVoice-BlankEN`). El `ttsfrd` (normalización de texto) es opcional y
trae un wheel binario `cp310`; sin él se usa `wetext`.

## 5. Entrenamiento (fine-tuning)

En `examples/libritts/` hay el pipeline completo para **fine-tuning con tu voz**,
en formato **LibriTTS** (`wav.scp` / `text` / `utt2spk` / `spk2utt`):

1. Preparar datos (`prepare_data.py`).
2. Extraer embeddings de hablante (`campplus.onnx`).
3. Extraer tokens de habla (`speech_tokenizer*.onnx`).
4. Generar `parquet` (`make_parquet_list.py`).
5. Entrenar por etapas **llm / flow / hifigan** (`torchrun` + DDP/DeepSpeed, multi-GPU).
6. Promediar checkpoints y exportar JIT/ONNX.

> **Clave para Paimon:** este fine-tuning es **pesado y multi-GPU** (el script
> asume `CUDA_VISIBLE_DEVICES="0,1,2,3"` y un dataset de cientos de horas). Para
> "entrenar con mi voz" en un equipo modesto, la vía práctica es la **clonación
> zero-shot** (guardar el embedding con `add_zero_shot_spk`) y dejar el fine-tuning
> como un **job asíncrono opcional** con hardware acorde.

## 6. Despliegue y hardware

- El README despliega con `docker run --runtime=nvidia` (GPU NVIDIA).
- Aceleración: **vLLM** (CosyVoice2/3) y **TensorRT-LLM** (Triton) para el LLM.
- La latencia "~150 ms" y el streaming en tiempo real del README están medidos **en
  GPU**. En CPU, `load_jit/load_trt/fp16/vllm` se desactivan automáticamente
  (`torch.cuda.is_available() is False`) y se cae a `fp32`, con un RTF muy superior
  a 1 (más lento que el tiempo real).

## 7. Qué nos sirve para Paimon

1. **Contrato de síntesis**: los modos (`sft`, `zero_shot`, `cross_lingual`,
   `instruct`, `vc`) son el catálogo natural de nuestra API (`/synthesize`).
2. **Librería de voces**: `add_zero_shot_spk` + `save_spkinfo` es exactamente el
   patrón de "subo audios → queda una voz seleccionable".
3. **Clonación zero-shot**: con pocos segundos de referencia, sin entrenar.
4. **Streaming por chunks** (`stream=True` + generador de texto de entrada): es la
   base del endpoint de tiempo real (WebSocket / chunked).
5. **Fine-tuning** (`examples/libritts`): referencia para el job de entrenamiento.

## 8. Reusar / no reusar

| Reusar (contratos e ideas) | No reusar (código) |
|----------------------------|--------------------|
| Modos de inferencia (`AutoModel`) como backend | Su `runtime/python/fastapi/server.py` (ejemplo sin auth/patrón) |
| `add_zero_shot_spk` / `save_spkinfo` para la librería de voces | Su manejo de modelos vía ModelScope (preferimos pesos en volumen) |
| `stream=True` + `StreamingResponse` PCM | Su `webui.py` (Gradio) |
| Pipeline de entrenamiento `examples/libritts` (como job) | Requisitos `requirements.txt` con CUDA 12.1 fijado |

## 9. Cómo revisarlo

El clon vive en `reference/CosyVoice/` (ignorado por git). Puntos de entrada:

```bash
# Uso y modos de inferencia
reference/CosyVoice/example.py
reference/CosyVoice/vllm_example.py

# API de alto nivel (AutoModel)
reference/CosyVoice/cosyvoice/cli/cosyvoice.py
reference/CosyVoice/cosyvoice/cli/frontend.py

# Servidor FastAPI / gRPC de ejemplo
reference/CosyVoice/runtime/python/fastapi/server.py
reference/CosyVoice/runtime/python/grpc/server.py

# Entrenamiento (fine-tuning)
reference/CosyVoice/examples/libritts/cosyvoice3/run.sh
reference/CosyVoice/tools/

# Requisitos y submodulos
reference/CosyVoice/requirements.txt
reference/CosyVoice/.gitmodules
```

Para re-clonarlo completo (con el submódulo `Matcha-TTS`):

```bash
git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git reference/CosyVoice
# o, si ya está el clon:
cd reference/CosyVoice && git submodule update --init --recursive
```
