# Referencia — Alternativas de TTS local (evaluación para `audio_generator`)

Comparativa de motores TTS evaluados para **correr en esta máquina** (CPU AMD
Ryzen 5 3500U, 29 GB RAM, sin GPU NVIDIA/ROCm utilizable) y para el futuro
despliegue en servidor con GPU. Complementa a
[`cosyvoice.md`](cosyvoice.md) y alimenta la decisión del
[`plan audio_generator`](../../plans/audio_generator.md).

## 1. Resumen

Necesitamos tres capacidades que **ningún modelo individual cubre a la vez en CPU**:

1. **Tiempo real** (streaming, RTF ≤ 1) → solo modelos ligeros.
2. **Clonación de voz** (a partir de audios) → modelos zero-shot (más pesados).
3. **Español** → no todos lo soportan.

Por eso la solución es **multi-proveedor** detrás de una misma interfaz:

| Rol | Modelo | Por qué |
|-----|--------|---------|
| **Síntesis en tiempo real (CPU, ahora)** | **Kokoro-82M** | 82M params, Apache-2.0, español, RTF ≪ 1 en CPU |
| **Clonación de voz (CPU, ahora)** | **XTTS-v2** | zero-shot con ~6 s de audio, español, corre en CPU (lento) |
| **Producción (GPU, servidor)** | **CosyVoice 3.0** | mejor calidad, clonación + fine-tuning + instruct + streaming |

## 2. Tabla comparativa

| Modelo | Parámetros | Licencia | Clonación | Español | CPU tiempo real | Streaming | Veredicto |
|--------|-----------|----------|-----------|---------|-----------------|-----------|-----------|
| **Kokoro-82M** | 82M | Apache-2.0 (pesos y código) | ❌ voces fijas (+ mezcla de voces) | ✅ | ✅ RTF ≪ 1 | ✅ (generador por frases) | **Tiempo real local** |
| **Piper** | ~50–100M | MIT (repo **archivado** 2025-10) | ❌ (entrenar aparte) | ✅ | ✅ RTF ≪ 1 | ✅ | Alternativa a Kokoro |
| **XTTS-v2** | ~466M | **CPML (no comercial)** | ✅ zero-shot (6 s) | ✅ | ⚠️ RTF > 1 (2–4×) | ✅ | **Clonación local** |
| **F5-TTS** | 0.3B | código MIT, pesos **CC-BY-NC** | ✅ zero-shot | ⚠️ parcial | ❌ pesado | ⚠️ chunks | GPU-oriented |
| **CosyVoice 3.0** | 0.5B | Apache-2.0 | ✅ zero-shot + fine-tune | ✅ | ❌ en CPU | ✅ (GPU) | **Producción GPU** |
| **Chatterbox** | ~0.5B | ? | ✅ zero-shot | ✅ | ❌ GPU | — | Descartado (GPU) |
| **OpenVoice V2** | ligero | MIT (base MeloTTS) | ✅ tone-converter | ✅ (MeloTTS) | ⚠️ | ⚠️ | Opcional, menor calidad |

## 3. Detalle de los candidatos principales

### Kokoro-82M (`hexgrad/kokoro`)

- **Qué es:** TTS basado en StyleTTS 2, 82M parámetros, `pip install kokoro`.
- **Idiomas** (`lang_code`): `a`=en-US, `b`=en-GB, **`e`=es**, `f`=fr, `i`=it, `h`=hi,
  `j`=ja (`misaki[ja]`), `p`=pt-BR, `z`=zh (`misaki[zh]`).
- **Voces:** fijas por idioma (p. ej. `ef_*`, `em_*` para español) + permite cargar
  tensores de voz personalizados (`torch.load('voice.pt')`) y **mezclar voces**.
- **Rendimiento:** RTF ≪ 1 en CPU (diseñado para correr incluso en Raspberry Pi).
- **Salida:** generador por frases a **24 000 Hz** (encaja con streaming por chunks).
- **Dependencias:** `torch`, `soundfile`, `misaki`, `espeak-ng` (fallback G2P).
- **Licencia:** Apache-2.0 (pesos y código) → utilizable en producción.
- **No tiene clonación** desde audio. Para "mi propia voz" hay que usar otro motor.

### XTTS-v2 (`coqui/XTTS-v2`)

- **Qué es:** TTS multilingüe con clonación **zero-shot** (basta ~6 s de referencia).
- **Idiomas:** 17, incluido **español**.
- **Rendimiento CPU:** lento (GPT-based, ~466M); en esta máquina RTF > 1.
- **Streaming:** soportado, pero no aprovecha "tiempo real" en CPU.
- **Licencia:** **Coqui Public Model License (CPML)** → **no comercial**. ⚠️
- **Nota:** Coqui cerró; el modelo sigue en HuggingFace pero el ecosistema es
  mantenido por la comunidad (`coqui-ai/TTS`).

### Piper (`rhasspy/piper`)

- **Qué es:** TTS basado en VITS, ONNX, muy rápido en CPU, con voces en español.
- **Clonación:** no (voces fijas; entrenar requiere `piper-train`).
- **Licencia:** MIT, pero el repo fue **archivado** (2025-10-06) y el desarrollo
  continúa en `OHF-Voice/piper1-gpl` (GPL). ⚠️
- **Veredicto:** alternativa válida a Kokoro, pero Kokoro gana por calidad y licencia.

### F5-TTS (`SWivid/F5-TTS`)

- **Qué es:** TTS por Flow Matching + DiT, zero-shot, muy rápido en GPU (RTF 0.04).
- **Idiomas:** base enfocada en en/zh; el español es parcial (depende del checkpoint).
- **Rendimiento CPU:** pesado (DiT 0.3B) → no apto para tiempo real en esta máquina.
- **Licencia:** código MIT, pesos **CC-BY-NC** (dataset Emilia). ⚠️
- **Veredicto:** candidato **GPU** alternativo a CosyVoice para el servidor.

### CosyVoice 3.0 (`FunAudioLLM/CosyVoice`)

- Detalle completo en [`cosyvoice.md`](cosyvoice.md).
- **Rol:** producción en el servidor con GPU (clonación + fine-tuning + instruct +
  streaming + español). No corre en tiempo real en esta máquina.

## 4. Recomendación

- **Ahora (CPU, local):** arrancar con **Kokoro-82M** como proveedor por defecto de
  síntesis/streaming, y **XTTS-v2** como proveedor de clonación zero-shot (con aviso
  de licencia no comercial).
- **Después (GPU, servidor):** añadir **CosyVoice 3.0** (o F5-TTS) detrás de la misma
  ABC, sin tocar la API.
- La decisión exacta se valida en la **Fase 0** midiendo RTF real en esta máquina
  (Kokoro y XTTS), antes de congelar el diseño de streaming.

## 5. Enlaces

| Motor | Repo / modelo |
|-------|---------------|
| Kokoro | <https://github.com/hexgrad/kokoro> · <https://hf.co/hexgrad/Kokoro-82M> |
| Piper | <https://github.com/rhasspy/piper> (archivado) · <https://github.com/OHF-Voice/piper1-gpl> |
| XTTS-v2 | <https://huggingface.co/coqui/XTTS-v2> |
| F5-TTS | <https://github.com/SWivid/F5-TTS> |
| CosyVoice | <https://github.com/FunAudioLLM/CosyVoice> |
