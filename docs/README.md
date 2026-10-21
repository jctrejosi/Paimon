# Documentación de Paimon

Índice de la documentación del repo. Para el diseño a nivel de proyecto (planes,
decisiones y roadmap) ver [`../plans/`](../plans/README.md).

| Documento | Contenido |
|-----------|-----------|
| [`overview.md`](overview.md) | Qué es Paimon, estructura del repo, convenciones y requisitos. |
| [`launcher.md`](launcher.md) | El lanzador `dev.js`: uso, flags, puertos y logs. |
| [`apps/audio_processing.md`](apps/audio_processing.md) | App de transcripción y preprocesamiento de audio. |
| [`apps/image_generator.md`](apps/image_generator.md) | App de generación y edición de imágenes. |
| [`apps/image_processing.md`](apps/image_processing.md) | App de procesamiento de imágenes (quita-fondo). |
| [`operations.md`](operations.md) | Operación común: puertos, tokens, logs, build y problemas típicos. |
| [`roadmap.md`](roadmap.md) | Módulos previstos a futuro. |
| [`reference/artcraft.md`](reference/artcraft.md) | Revisión del repo público ArtCraft (referencia para `image_processor`). |

### Detalle técnico

| Documento | Contenido |
|-----------|-----------|
| [`audio_processing/`](audio_processing/README.md) | **Algoritmo de transcripción** paso a paso, preprocesamiento modular y proveedores (con diagramas). |

## Arranque en 30 segundos

```bash
# levanta los dos aplicativos (Docker Compose)
node dev.js

# o uno solo
node dev.js --audio
node dev.js --image
node dev.js --processing
```

Cada app tiene además su propio `README.md` dentro de la capa de código (p. ej.
`audio_processing/README.md` e `image_generator/api/README.md`), con el detalle fino
de endpoints y configuración.
