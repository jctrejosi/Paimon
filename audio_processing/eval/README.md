# eval — Banco de evaluación de WER

Mide el efecto del preprocesamiento en la transcripción, para **decidir presets
con datos** en lugar de a ojo.

## Cómo funciona

```
dataset.py / dataset_real.py   →  data*/  (WAV + manifest.jsonl con verdad-terreno)
evaluate.py                    →  tabla de WER por variante y condición
```

- `wer.py`: WER con normalización (minúsculas, sin acentos, sin puntuación).
- `variants.json`: define las variantes a comparar (`null` = sin preprocesar,
  `"clean"` = preset de la app, `[...]` = lista de pasos).
- `tts.py`: síntesis con espeak-ng vía `ctypes` (genera audio con texto conocido).

### Sets

| Script | Fuente | Para qué |
|---|---|---|
| `dataset.py` | Voz sintética en **español** (espeak-ng) | Probar el camino en español. Limitado: los artefactos del TTS suben el WER base. |
| `dataset_real.py` | **Voz real** desde la API `datasets-server` de Hugging Face (LibriSpeech) | Medir el efecto real del preprocesamiento (línea base limpia ≈ 0). |

Cada clip se guarda en 3 condiciones: `clean`, `snr15`, `snr5` (ruido rosa añadido).

## Uso

```bash
cd audio_processing/eval
python dataset.py                      # mini-set sintético (español)
python dataset_real.py --limit 6       # mini-set de voz real
python evaluate.py --data-dir data_real --language en \
  --variants none,minimal,clean,vad-only,denoise-spectral,denoise-noisereduce
```

## Resultados (LibriSpeech, 6 clips × 3 condiciones, faster-whisper `base`)

| variante | clean | 15 dB | 5 dB | global |
|---|---|---|---|---|
| `none` (sin preprocesar) | 0.092 | 0.100 | 0.155 | 0.116 |
| `minimal` | 0.100 | 0.106 | 0.155 | 0.120 |
| **`clean`** (con VAD) | **0.014** | 0.110 | 0.123 | **0.082** |
| `vad-only` | 0.033 | 0.110 | 0.157 | 0.100 |
| `denoise-spectral` | 0.088 | 0.092 | 0.176 | 0.119 |
| `denoise-noisereduce` | 0.073 | 0.099 | 0.134 | 0.102 |
| `denoise-dfn` | — | — | — | FAIL (no instalable) |

## Conclusiones

1. **`clean` es el mejor preset** por defecto (~29 % menos WER que sin preprocesar).
2. **El VAD es el factor dominante**: recortar silencio reduce mucho las
   alucinaciones (en limpio, 0.092 → 0.014).
3. **`minimal` (resample+highpass+normalize) no aporta** por sí solo.
4. **El denoise no debe activarse por defecto**: incluso `noisereduce` empeora
   respecto a la misma cadena sin denoise. Solo tiene sentido en audio muy ruidoso.
5. Si se usa denoise, **`noisereduce` es mejor que el `spectral` propio**
   (en 5 dB: 0.134 vs 0.176). Por eso el backend por defecto es `auto`.

## Motor: modelo y decodificación

`evaluate.py` acepta parámetros del decodificador para aislar su efecto (por
defecto usa un decoder "crudo": **sin VAD**):

```bash
python evaluate.py --data-dir data_real --language en --variants none --vad --model small
# flags: --vad / --no-vad, --beam-size N, --condition-on-previous-text, --model <nombre>
```

A/B sobre el set real (WER global, 6 clips × 3 condiciones):

| Configuración | WER global |
|---|---|
| `base`, sin VAD | 0.110 |
| `base` + VAD | 0.118 |
| `small`, sin VAD | 0.041 |
| **`small` + VAD** | **0.023** |

El **modelo manda**; el VAD **suma sobre un modelo bueno** (con `base` era neutro).
Coste en CPU: `small` ≈ 3× `base` (~14-18 s vs ~5-7 s por clip de ~6 s).

## Limitaciones

- Con voz sintética (español), los artefactos del TTS dominan y **ninguna variante
  mejora** — úsese solo para el camino en español, no para decidir.
- El set real es inglés (LibriSpeech). El efecto del preprocesamiento es
  independiente del idioma, pero conviene repetirlo con voz real en español.
- 6 clips es poco: las diferencias pequeñas (<0.02) no son significativas.

## Verificación de diarización

`diarize_check.py` construye un audio con **dos hablantes reales** (dos clips de
LibriSpeech de distinto `speaker_id`, separados por un silencio) y comprueba que
la diarización detecta 2 hablantes y encuentra el cambio de turno:

```bash
python diarize_check.py --backend ecapa   # sin credenciales (speechbrain)
```

Resultado con `ecapa`: 2 hablantes detectados y cambio de turno a ≲0.6 s del
real, sin credenciales. El backend `pyannote` (mejor calidad) requiere
`HF_TOKEN` porque sus modelos están *gated* en Hugging Face.
