# Paimon RAG

Servicio central de **Retrieval-Augmented Generation**: recibe documentos,
extrae su texto, lo trocea, genera **embeddings** y los almacena para ofrecer
**búsqueda semántica multi-namespace** por HTTP.

Es el dueño único de la base de conocimiento de Paimon. Los demás proyectos
apuntan a él:

- **chatbot-platform** (`knowledge-service`): usa `/ingest`, `/sources`,
  `/search` con `bot_id = <bot de WhatsApp>`.
- **TESIS / plant-service**: carga catálogos de plantas con
  `bot_id = plant-service` y consulta `/search` o `/context`.

## Cómo funciona

```text
archivo/texto ──extracción──> texto ──chunking──> fragments ──embeddings──> vector store
                                                                                │
consulta ──embedding──> similitud coseno ──(reranker DeepSeek opcional)──> fragmentos
```

### Aislamiento por proyecto

Cada **proyecto** guarda su RAG en un espacio **físicamente separado** dentro de
la base interna del servicio:

- **PostgreSQL** (contenedor `paimon-rag-db`): un *schema* por proyecto
  (`rag_chatbot_platform`, `rag_tesis`, `rag_default`…), creado al primer uso.
- **SQLite** (desarrollo/tests): un archivo por proyecto
  (`data/projects/<proyecto>.db`).

El proyecto se indica por petición con el header **`X-RAG-Project`** (o query
`?project=`); si no se envía se usa `DEFAULT_PROJECT` (`default`). Dentro de cada
proyecto, `bot_id` sigue separando sub-espacios (p. ej. un `bot_id` por bot de
WhatsApp).

| Consumidor | `X-RAG-Project` | `bot_id` |
|---|---|---|
| chatbot-platform | `chatbot-platform` | id del bot |
| TESIS / plant-service | `tesis` | `plant-service` |
- **Embeddings** (`EMBEDDING_PROVIDER`):
  - `fastembed` (defecto): modelos ONNX en CPU, local-first. Descarga el modelo
    la primera vez y lo cachea.
  - `openai`: cualquier endpoint compatible con `/embeddings`.
  - `hashing`: vectorizador determinista offline, sin modelos (tests/fallback).
- **Persistencia**: PostgreSQL (docker compose) o SQLite (desarrollo/tests).
  Los vectores se guardan como JSON y la similitud se calcula en el servicio,
  así el mismo código funciona en ambos motores.
- **Reranking** opcional con DeepSeek (`DEEPSEEK_API_KEY`).

### Extracción de documentos

Portado del `knowledge-service` del chatbot (pipeline completo):

- **PDF**: PyMuPDF (word-level) → pdfplumber (tablas) → **OCR Tesseract** para
  PDFs escaneados, eligiendo el resultado de mayor calidad.
- **Office**: DOCX (`python-docx`), PPTX (`python-pptx`), XLSX (`openpyxl`),
  XLS legacy (`xlrd`), ODF (`odt`/`ods`/`odp`).
- **RTF**, **CSV/TSV**, **ZIP** (incluye ZIP anidado) y texto/código (md, html,
  json, yaml, xml, py, js, sql…).
- **LibreOffice headless** como comodín universal (`.doc`, `.ppt`, `.pages`,
  `.epub`, `.msg`, `.mht`…), si está instalado.

La imagen Docker instala LibreOffice + Tesseract (eng/spa) por defecto. Para una
imagen más ligera sin esos formatos: `docker build --build-arg INSTALL_EXTRAS=0 .`

## Endpoints

Compatible con la API del antiguo `knowledge-service`.

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/ingest` | Sube y procesa un archivo (`file`, `bot_id`, `title`, `cloudinary_url`). |
| `POST` | `/ingest/text` | Carga texto directamente (`title`, `text`, `bot_id`). |
| `GET` | `/sources` | Lista fuentes (`?bot_id=&status=`). |
| `GET` | `/sources/{id}` | Detalle con documentos, chunks y último job. |
| `GET` | `/sources/{id}/download` | Descarga el original (o redirige a Cloudinary). |
| `DELETE` | `/sources/{id}` | Elimina fuente, documentos, chunks y jobs. |
| `POST` | `/search` | Búsqueda semántica (`query`, `top_k`, `min_similarity`, `use_reranker`). `?bot_id=`. |
| `GET` | `/context` | Contexto concatenado listo para un prompt (`?q=&bot_id=&top_k=`). |
| `POST` | `/embeddings` | Genera embeddings (`{texts: [...]}`). |
| `POST` | `/v1/embeddings` | Generación de embeddings compatible con OpenAI (`{input}`). |
| `POST` | `/conversations` · `GET /conversations/{user_id}` | Historial (paridad). |
| `GET` | `/health` | Estado, proveedor de embeddings y reranker. |

### Ejemplos

```bash
# Cargar un documento para el bot "abc" del proyecto chatbot-platform
curl -s -X POST -H "X-API-Key: $KEY" -H "X-RAG-Project: chatbot-platform" \
  -F file=@catalogo.pdf -F bot_id=abc \
  http://127.0.0.1:8104/ingest | jq

# Cargar un catálogo de plantas del proyecto tesis
curl -s -X POST -H "X-API-Key: $KEY" -H "X-RAG-Project: tesis" \
  -H 'Content-Type: application/json' \
  -d '{"title":"Catálogo","text":"...","bot_id":"plant-service"}' \
  http://127.0.0.1:8104/ingest/text | jq

# Buscar
curl -s -X POST -H "X-API-Key: $KEY" -H "X-RAG-Project: tesis" \
  -H 'Content-Type: application/json' \
  -d '{"query":"temperatura del tomate","top_k":5,"use_reranker":true}' \
  "http://127.0.0.1:8104/search?bot_id=plant-service" | jq

# Embeddings (servicio de embeddings)
curl -s -X POST -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"texts":["temperatura del tomate"]}' \
  http://127.0.0.1:8104/embeddings | jq '.dimensions'
```

## Configuración

Se lee de variables de entorno o de un `.env` (no versionado). Las claves de API
compartidas (`API_KEYS`, `API_AUTH_REQUIRED`, `API_PUBLIC_DOCS`) viven en el
`.env` de la raíz de Paimon, igual que en el resto de apps.

| Variable | Default | Uso |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./rag.db` | Base de datos (compose usa PostgreSQL). |
| `DEFAULT_PROJECT` | `default` | Proyecto cuando la petición no envía `X-RAG-Project`. |
| `SCHEMA_PREFIX` | `rag_` | Prefijo de los schemas PostgreSQL por proyecto. |
| `PROJECT_DATA_DIR` | `data/projects` | Directorio de archivos SQLite por proyecto. |
| `EMBEDDING_PROVIDER` | `fastembed` | `fastembed` \| `openai` \| `hashing`. |
| `EMBEDDING_MODEL` | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Modelo de embeddings (multilingüe). Alternativas: `intfloat/multilingual-e5-large`, `jinaai/jina-embeddings-v2-base-es`. |
| `EMBEDDING_API_KEY` | *(vacío)* | Necesaria con `openai`. |
| `EMBEDDING_BASE_URL` | `https://api.openai.com/v1` | Endpoint compatible OpenAI. |
| `FASTEMBED_CACHE_DIR` | `models` | Caché de modelos (volumen). |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `600` / `100` | Troceado. |
| `MAX_SCAN_CHUNKS` | `5000` | Chunks por namespace que se puntúan en cada consulta. |
| `DEFAULT_TOP_K` | `5` | Resultados por defecto. |
| `DEEPSEEK_API_KEY` | *(vacío)* | Activa el reranking. |
| `RAG_ROOT_PATH` | *(vacío)* | Prefijo público (`/rag`) cuando se publica tras el edge. |
| `RAG_MAX_UPLOAD_MB` | `50` | Tamaño máximo de subida. |
| `INSTALL_EXTRAS` | `1` | Build-arg: instala LibreOffice + Tesseract (`0` = imagen ligera). |

## Ejecución

```bash
# Con Docker (base de datos incluida)
cd rag_service
node ../dev.js --rag          # o: docker compose up --build

# Local con SQLite
cd rag_service/api
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn app.main:app --port 8104
```

## Pruebas

```bash
cd rag_service/api
.venv/bin/pytest
```

Las pruebas usan SQLite en memoria y `EMBEDDING_PROVIDER=hashing`: no descargan
modelos ni requieren red.
