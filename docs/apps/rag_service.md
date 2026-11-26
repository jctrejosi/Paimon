# rag_service — base de conocimiento y embeddings

Servicio central de Paimon para **RAG** (Retrieval-Augmented Generation):
ingesta de documentos, extracción de texto, troceado, **embeddings** y
**búsqueda semántica** por HTTP.

Es el dueño único de la base de conocimiento; los demás proyectos lo consumen con
un **espacio físico aislado por proyecto** (schema de PostgreSQL o archivo
SQLite):

| Consumidor | `X-RAG-Project` | Namespace (`bot_id`) |
|---|---|---|
| `chatbot-platform` (knowledge-service) | `chatbot-platform` | id del bot de WhatsApp |
| TESIS / `plant-service` | `tesis` | `plant-service` |

Cada proyecto se crea automáticamente al primer uso (`rag_<proyecto>`). El
header `X-RAG-Project` (o `?project=`) elige el espacio; sin él se usa
`DEFAULT_PROJECT`.

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/ingest` | Sube un archivo y lo procesa (`file`, `bot_id`, `title`, `cloudinary_url`). |
| `POST` | `/ingest/text` | Carga texto (`title`, `text`, `bot_id`). |
| `GET` | `/sources` | Lista fuentes (`?bot_id=&status=`). |
| `GET` | `/sources/{id}` | Detalle: documentos, chunks y último job. |
| `GET` | `/sources/{id}/download` | Descarga el original (o redirige a Cloudinary). |
| `DELETE` | `/sources/{id}` | Elimina fuente y todo su contenido. |
| `POST` | `/search` | Búsqueda semántica. `?bot_id=` |
| `GET` | `/context` | Contexto concatenado para un prompt. |
| `POST` | `/embeddings` · `/v1/embeddings` | Generación de embeddings (propio / compatible OpenAI). |

Todas las rutas aceptan `X-RAG-Project` (o `?project=`) para elegir el espacio
físico del proyecto.
| `GET` | `/health` | Estado y proveedor de embeddings. |

La API es **compatible** con la del antiguo `knowledge-service`, así un
consumidor solo cambia su URL base.

## Embeddings

`EMBEDDING_PROVIDER`:

- `fastembed` (defecto): modelo ONNX en CPU. Local-first; el modelo se descarga
  la primera vez y se cachea en `FASTEMBED_CACHE_DIR`.
- `openai`: endpoint compatible con `/embeddings` (OpenAI, vLLM…).
- `hashing`: vectorizador determinista sin modelos (tests/fallback).

## Persistencia

PostgreSQL en Docker (`paimon-rag-db`) o SQLite en desarrollo. Los vectores se
guardan como JSON y la similitud coseno se calcula en el servicio, por lo que el
mismo código funciona en ambos motores. El **reranking** con DeepSeek es
opcional (`DEEPSEEK_API_KEY`).

## Puertos y ejecución

- Host: `127.0.0.1:8104` (`RAG_HOST_PORT`), interno `:8000`.
- Tras el edge compartido: prefijo `/rag` (`RAG_ROOT_PATH=/rag`).

```bash
node dev.js --rag          # con PostgreSQL (docker compose)
cd rag_service/api && .venv/bin/uvicorn app.main:app --port 8104   # SQLite
```

## Pruebas

```bash
cd rag_service/api
.venv/bin/pytest
```

Usan SQLite en memoria y `EMBEDDING_PROVIDER=hashing`: sin red ni descargas.
