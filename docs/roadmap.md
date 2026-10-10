# Roadmap

Paimon se concibe como una colección de aplicativos independientes. Hoy existen
`audio_processing` e `image_generator`; el resto son ideas para el futuro.

El listado completo y su descripción están en
[`../plans/apps_future.md`](../plans/apps_future.md). Resumen:

| # | Módulo | Carpetas propuestas |
|---|--------|---------------------|
| 1 | Generación y edición de imágenes | `image_generation/` · `image_processing/` |
| 2 | Procesamiento de audio | `audio_processing/` |
| 3 | Procesamiento de vídeo | `video_processing/` · `video_generation/` |
| 4 | Reconocimiento y síntesis de voz | `speech_to_text/` · `text_to_speech/` |
| 5 | Procesamiento de documentos | `document_processing/` |
| 6 | Búsqueda semántica | `semantic_search/` · `embeddings/` |
| 7 | Procesamiento de texto con IA | `text_processing/` |
| 8 | Visión artificial | `computer_vision/` |
| 9 | Generación y procesamiento 3D | `three_d/` · `mesh_processing/` |
| 10 | Extracción y transformación de datos | `data_extraction/` · `data_processing/` |
| 11 | Herramientas musicales | `music_generation/` · `midi_processing/` |
| 12 | Automatización de flujos | `workflow_engine/` |

## Planes relacionados

- [`../plans/audio_processing.md`](../plans/audio_processing.md) — API de transcripción (implementado).
- [`../plans/audio_processing_pipeline.md`](../plans/audio_processing_pipeline.md) — pipeline de preprocesamiento (implementado).
- [`../plans/apps_future.md`](../plans/apps_future.md) — catálogo de ideas.

## Cómo añadir un aplicativo

1. Crear la carpeta de la app con su `api/` y su patrón de servicio (FastAPI + ABC de
   proveedores + `registry.py` + `config.py`).
2. Añadir su `Dockerfile` y `docker-compose.yml` (solo loopback).
3. Registrarla en `dev.js` (catálogo `PROJECTS`) con su `dir`, puerto y endpoints.
4. Documentarla en `docs/apps/` y, si procede, crear su plan en `plans/`.
