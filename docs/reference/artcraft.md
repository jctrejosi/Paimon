# Referencia — ArtCraft (`storytold/artcraft`)

Revisión del repositorio público **ArtCraft** para inspirar el módulo
`image_processor` de Paimon y ver qué aporta en audio.

| Dato | Valor |
|------|-------|
| Repositorio | <https://github.com/storytold/artcraft> |
| Commit revisado | `40e0479` (2026-10-20) |
| Licencia | MIT / Apache-2.0 (dual) |
| Stack | Rust (`egui` nativo + `crates`), React/TypeScript (Tauri), FFmpeg, rodio |
| Clon local | `reference/artcraft/` (**ignorado por git**) |
| Tamaño | ~108 MB (clon superficial `--depth 1`) |

## 1. Qué es

ArtCraft se describe como **"the IDE for artists"**: un entorno de escritorio/web
para crear y editar imagen, vídeo, audio, mallas 3D y mundos con IA. Es sobre todo
un **agregador/orquestador de modelos en la nube** (su propia API
`api.storyteller.ai`, fal, Grok, Midjourney, Sora, World Labs), no un toolkit de
procesamiento local de imagen.

## 2. Arquitectura

| Carpeta | Rol |
|---------|-----|
| `artcraft-native/` | App de escritorio en **Rust puro con egui** (sin Tauri/webview). Páginas `create_image`, `create_audio`, `create_video`; playback de vídeo con FFmpeg y audio con rodio. |
| `frontend/` | App React/TS sobre **Tauri** (la app principal). Una carpeta por feature en `apps/artcraft/app/src/pages/` (`PageImage`, `PageDraw`, `PageRemoveBackground`, `PageImageTo3DObject`, `PageVideoEditor`, …). |
| `crates/api_clients/` | Clientes de las APIs: `artcraft` (propia), `fal_client`, `grok_*`, `midjourney_client`, `openai_sora_client`, `worldlabs_*`, `kinovi_web_client`, `gmicloud_client`. |
| `crates/desktop/artcraft/` | Comandos Tauri de enqueue/edición (`image_edit`, `image_inpaint`, `image_bg_removal`, `image_to_3d`, …). |
| `crates/schema`, `crates/lib`, `crates/testing` | Enums/modelos compartidos, utilidades (HTTP, caching, cookies, JWT) y testing. |
| `_docs/artcraft_omni_api.md` | API "Omni" para generación programática con API key. |

**Clave para Paimon:** la generación/edición se ejecuta en **servicios cloud**. En
local solo viven la UI, la subida de media, la reproducción (FFmpeg/rodio), la
forma de onda y el editor de escena/canvas.

## 3. Funcionalidades de imagen

### Generación

- **Text to Image** (prompt → imagen).
- **Image to Video** (animar una imagen).
- **Image to 3D Object** (imagen → malla texturizada).
- **Image to 3D World** (mood boards → mundos; Marble / Gaussian splats).
- **Angles** (nuevos ángulos de cámara desde una foto).
- **Storyboard** y **Moodboard**.

### Edición

- **Prompted Image Editing** (describir el cambio).
- **Canvas Image Editing**: dibujo, **máscaras** e **inpainting**.
- **Remove Background**.
- **Background Change** (cambiar el fondo de un vídeo con una referencia).
- **Image Watermark Remover** (marcado *SOON*).
- **Image Editor** (canvas 2D: composición por capas, recortes).
- **3D Stage** (composición 2D/3D, *kitbashing*, *scene blocking*, posing, identity transfer).

### Modelos

- Imagen: **Nano Banana** (1/2/Pro), **GPT Image** (1.5/2/2.5), **FLUX** (dev/schnell/1.1 pro), **Seedream** (4/4.5/5).
- Inpainting: variantes de **FLUX Pro 1**, **FLUX dev juggernaut** y **Nano Banana Kontext**.
- Quita-fondo: endpoint propio de ArtCraft **o** `rembg` de fal.ai.

> Nota: el "upscaler" aparece solo como opción (`use_upscaler`) dentro del *style
> transfer* de vídeo; **no** hay una función de *upscale* de imagen independiente.

## 4. Funcionalidades de audio

- **Create Audio** (generación musical/sonido):
  - Modelos: **Suno Music**, **Suno Remix**, **Suno Sounds**, **Suno Sample**,
    **Seed Audio 1.0**.
  - Parámetros: prompt, *style prompt*, instrumental, conservar letra, loopable,
    **BPM** 40–240, **tonalidad** (13 opciones), *sample rate*, velocidad 0.5–2×,
    volumen 0.5–2×, **pitch** −12…+12 semitonos.
  - Referencias: audio (hasta **600 s**) e imagen.
- **Reproducción local**: rodio + symphonia (play/pause/seek/volumen).
- **Forma de onda**: decodifica el archivo y calcula 256 picos normalizados.
- **Audio como referencia de vídeo**: `reference_audio_urls` en la API Omni.

**Lo que NO tiene** (y nosotros sí): transcripción (STT), TTS, reducción de
ruido, diarización, separación de fuentes, conversión/normalización de audio.

## 5. Local vs. nube

| Capacidad | Dónde corre |
|-----------|-------------|
| Generación de imagen/vídeo/audio/3D | Nube (ArtCraft, fal, Grok, Midjourney, Sora, World Labs) |
| Inpainting, quita-fondo | Nube (ArtCraft o fal `rembg`) |
| Subida de referencias (media tokens) | Local → nube |
| Reproducción de vídeo/audio, waveform | **Local** (FFmpeg, rodio) |
| Canvas/escena/editor | **Local** (UI) |

## 6. Qué nos sirve para Paimon

### Para `image_processor`

1. **Taxonomía de operaciones**: quitar fondo, inpainting con máscara, cambiar
   fondo, quitar marca de agua, nuevos ángulos, composición por capas, *upscale*.
   Es un buen checklist de alcance.
2. **Patrón upload-token + job**: subir la imagen una vez, referenciarla por token
   y encolar el trabajo (enqueue → poll → resultado). Encaja con el sistema de
   `jobs` que ya tiene `image_generator`.
3. **Estimación de coste por operación** antes de ejecutar.
4. **Editor 2D**: conceptos de capas, pincel de máscara y región de inpainting.
5. **Forma de onda** (aunque es audio): útil si el `image_processor` acaba con UI.

**Cuidado:** su código es Rust/egui/Tauri y está acoplado a su API cloud. Para
Paimon conviene implementar equivalentes **local-first** (p. ej. `rembg`/BiRefNet
para fondo, Real-ESRGAN para upscale, LaMa/SD inpainting, OpenCV/Pillow para
composición), no portar su capa de red.

### Para audio

- La **generación musical/sonido** (Suno/Seed Audio) encaja con el módulo futuro
  **11. Herramientas musicales** (`music_generation/`), **no** con
  `audio_processing`, que ya es más completo en *procesamiento* (denoise, VAD,
  diarización, separación con Demucs).
- La **extracción de picos para waveform** es una utilidad pequeña y reutilizable.
- El **audio como referencia de vídeo** será relevante para el futuro módulo de
  vídeo.

## 7. Reusar / no reusar

| Reusar (ideas) | No reusar (código) |
|----------------|--------------------|
| Catálogo de operaciones de imagen | Implementación Rust/Tauri/egui |
| Flujo upload → token → job → poll | Dependencia de `api.storyteller.ai` |
| Estimación de coste previa | Modelos cloud de pago |
| Máscara/inpainting por capas | Playback FFmpeg/rodio (solo reproducción) |
| Waveform de 256 picos | — |

## 8. Cómo revisarlo

El clon vive en `reference/artcraft/` (ignorado por git). Puntos de entrada:

```bash
# Funcionalidades y catálogo de modelos
reference/artcraft/README.md
reference/artcraft/ROADMAP.md

# Lista de apps/features de la UI
reference/artcraft/frontend/apps/artcraft/app/src/config/appMenu.tsx

# Páginas por feature
reference/artcraft/frontend/apps/artcraft/app/src/pages/

# App nativa Rust (imagen/audio/vídeo)
reference/artcraft/artcraft-native/src/pages/
reference/artcraft/artcraft-native/src/backend/

# Clientes de API
reference/artcraft/crates/api_clients/

# API Omni
reference/artcraft/_docs/artcraft_omni_api.md
```

Para volver a clonarlo desde cero:

```bash
git clone --depth 1 https://github.com/storytold/artcraft.git reference/artcraft
```
