"""Pruebas de la API del servicio RAG."""

from __future__ import annotations

from tests.conftest import Env

TOMATO_TEXT = """CULTIVO DE TOMATE (Solanum lycopersicum)

Temperatura
La germinación del tomate requiere entre 20 y 28 °C, con un óptimo de 25 °C.
Durante la fase vegetativa conviene mantener 22 °C.

Riego
El riego del tomate debe ser frecuente y moderado, con un umbral de humedad
del 40 % y riegos de 20 segundos cada 8 horas.
"""

LETTUCE_TEXT = """CULTIVO DE LECHUGA (Lactuca sativa)

Temperatura
La lechuga prefiere temperaturas frescas entre 15 y 22 °C.

Riego
Requiere humedad constante del sustrato, con un umbral del 55 %.
"""

OTHER_TEXT = """DOCUMENTO INTERNO BETA

Este texto contiene la palabra clave betaword para probar el aislamiento
de namespaces entre bots.
"""


async def _ingest_text(env: Env, *, title: str, text: str, bot_id: str | None) -> dict:
    response = await env.client.post(
        "/ingest/text",
        json={"title": title, "text": text, "bot_id": bot_id},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_health(env: Env) -> None:
    response = await env.client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["embedding_provider"] == "hashing"


async def test_ingest_list_and_detail(env: Env) -> None:
    created = await _ingest_text(
        env, title="Catálogo tomate", text=TOMATO_TEXT, bot_id="plant-service"
    )
    assert created["status"] == "completed"
    assert created["source_id"]

    listed = await env.client.get("/sources", params={"bot_id": "plant-service"})
    assert listed.status_code == 200
    sources = listed.json()
    assert len(sources) == 1
    assert sources[0]["id"] == created["source_id"]
    assert sources[0]["status"] == "completed"

    detail = await env.client.get(f"/sources/{created['source_id']}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["source"]["title"] == "Catálogo tomate"
    assert body["documents"][0]["chunks"]
    assert body["last_job"]["status"] == "completed"


async def test_search_returns_relevant_chunk(env: Env) -> None:
    await _ingest_text(env, title="Tomate", text=TOMATO_TEXT, bot_id="plant-service")
    await _ingest_text(env, title="Lechuga", text=LETTUCE_TEXT, bot_id="plant-service")

    response = await env.client.post(
        "/search",
        params={"bot_id": "plant-service"},
        json={
            "query": "lycopersicum temperatura",
            "top_k": 3,
            "min_similarity": -1.0,
            "use_reranker": False,
        },
    )
    assert response.status_code == 200, response.text
    results = response.json()["results"]
    assert results
    assert "tomate" in results[0]["content"].lower()
    assert results[0]["similarity"] is not None


async def test_namespace_isolation(env: Env) -> None:
    await _ingest_text(env, title="Tomate", text=TOMATO_TEXT, bot_id="plant-service")
    other = await _ingest_text(env, title="Beta", text=OTHER_TEXT, bot_id="otro-bot")

    # El namespace de plant-service no ve el documento del otro bot.
    response = await env.client.post(
        "/search",
        params={"bot_id": "plant-service"},
        json={"query": "betaword", "top_k": 5, "min_similarity": -1.0},
    )
    contents = " ".join(item["content"] for item in response.json()["results"])
    assert "betaword" not in contents.lower()

    # El namespace correcto sí lo encuentra.
    found = await env.client.post(
        "/search",
        params={"bot_id": "otro-bot"},
        json={"query": "betaword", "top_k": 5, "min_similarity": -1.0},
    )
    assert any("betaword" in item["content"].lower() for item in found.json()["results"])

    # El detalle del documento ajeno no aparece listado en el namespace propio.
    listed = await env.client.get("/sources", params={"bot_id": "plant-service"})
    assert all(item["id"] != other["source_id"] for item in listed.json())


async def test_upload_and_delete(env: Env) -> None:
    response = await env.client.post(
        "/ingest",
        files={"file": ("catalogo.txt", TOMATO_TEXT.encode("utf-8"), "text/plain")},
        data={"bot_id": "plant-service", "title": "Catálogo subido"},
    )
    assert response.status_code == 201, response.text
    source_id = response.json()["source_id"]

    detail = await env.client.get(f"/sources/{source_id}")
    assert detail.json()["source"]["original_filename"] == "catalogo.txt"
    assert detail.json()["source"]["file_available"] is True

    download = await env.client.get(f"/sources/{source_id}/download")
    assert download.status_code == 200
    assert download.content == TOMATO_TEXT.encode("utf-8")

    deleted = await env.client.delete(f"/sources/{source_id}")
    assert deleted.status_code == 200
    assert deleted.json()["ok"] is True

    gone = await env.client.get(f"/sources/{source_id}")
    assert gone.status_code == 404


async def test_empty_upload_is_rejected(env: Env) -> None:
    response = await env.client.post(
        "/ingest",
        files={"file": ("vacio.txt", b"   ", "text/plain")},
        data={"bot_id": "plant-service"},
    )
    assert response.status_code == 422


async def test_context_endpoint(env: Env) -> None:
    await _ingest_text(env, title="Tomate", text=TOMATO_TEXT, bot_id="plant-service")
    response = await env.client.get(
        "/context", params={"q": "riego tomate", "bot_id": "plant-service", "top_k": 2}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["chunks_used"] >= 1
    assert "tomate" in body["context"].lower()


async def test_project_isolation(env: Env) -> None:
    # Proyecto por defecto (tesis)
    await _ingest_text(env, title="Tomate", text=TOMATO_TEXT, bot_id="plant-service")
    # Proyecto chatbot-platform (header X-RAG-Project)
    other = await env.client.post(
        "/ingest/text",
        headers={"X-RAG-Project": "chatbot-platform"},
        json={"title": "Beta", "text": OTHER_TEXT, "bot_id": "bot-a"},
    )
    assert other.status_code == 201, other.text

    # La búsqueda del proyecto default no ve los datos del otro proyecto.
    response = await env.client.post(
        "/search",
        params={"bot_id": "plant-service"},
        json={"query": "betaword", "top_k": 5, "min_similarity": -1.0},
    )
    contents = " ".join(item["content"] for item in response.json()["results"])
    assert "betaword" not in contents.lower()

    # En el proyecto correcto sí aparece.
    found = await env.client.post(
        "/search",
        headers={"X-RAG-Project": "chatbot-platform"},
        params={"bot_id": "bot-a"},
        json={"query": "betaword", "top_k": 5, "min_similarity": -1.0},
    )
    assert any(
        "betaword" in item["content"].lower() for item in found.json()["results"]
    )

    # Cada proyecto tiene su propio archivo SQLite.
    project_files = {p.name for p in (env.app.state.settings.project_data_dir).glob("*.db")}
    assert "default.db" in project_files
    assert "chatbot-platform.db" in project_files


async def test_invalid_project_is_rejected(env: Env) -> None:
    response = await env.client.get(
        "/sources", headers={"X-RAG-Project": "../malicioso"}
    )
    assert response.status_code == 400


async def test_embeddings_endpoint(env: Env) -> None:
    response = await env.client.post(
        "/embeddings", json={"texts": ["tomate", "lechuga"]}
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["embeddings"]) == 2
    assert body["dimensions"] == len(body["embeddings"][0])

    openai_format = await env.client.post(
        "/v1/embeddings", json={"input": "tomate", "model": "x"}
    )
    assert openai_format.status_code == 200
    data = openai_format.json()["data"]
    assert data[0]["object"] == "embedding"
    assert data[0]["index"] == 0


async def test_conversations(env: Env) -> None:
    created = await env.client.post(
        "/conversations",
        json={
            "user_id": "u1",
            "user_name": "Prueba",
            "bot_id": "plant-service",
            "message": "hola",
            "response": "buenas",
            "chunks_used": [],
        },
    )
    assert created.status_code == 201
    listed = await env.client.get("/conversations/u1")
    assert listed.status_code == 200
    assert listed.json()[0]["message"] == "hola"
