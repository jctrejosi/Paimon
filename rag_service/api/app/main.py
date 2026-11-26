"""Servicio RAG de Paimon.

Base de conocimiento central con embeddings: extracción → troceado →
vectorización → recuperación. Los consumidores (chatbot-platform y TESIS)
lo usan por HTTP y aíslan su contenido con `bot_id`.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api_key_auth import APIKeyMiddleware
from .config import Settings, get_settings
from .db import DatabaseManager
from .embeddings import build_embedding_provider
from .reranker import Reranker
from .routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        yield
    finally:
        await app.state.embedder.aclose()
        await app.state.reranker.aclose()
        await app.state.databases.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(
        title="Paimon RAG",
        version="0.1.0",
        description=(
            "Base de conocimiento central: ingesta de documentos, embeddings y "
            "búsqueda semántica aislada por proyecto (`X-RAG-Project`) y "
            "namespace (`bot_id`)."
        ),
        root_path=settings.rag_root_path,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.embedder = build_embedding_provider(settings)
    app.state.reranker = Reranker(settings)
    # Una base aislada por proyecto (schema PostgreSQL / archivo SQLite).
    app.state.databases = DatabaseManager(settings)

    # Toda la app (incluidas las dependencias) usa esta instancia de settings.
    app.dependency_overrides[get_settings] = lambda: settings

    app.add_middleware(APIKeyMiddleware)
    app.include_router(router)

    @app.get("/", include_in_schema=False)
    async def root() -> dict:
        return {
            "service": settings.app_name,
            "endpoints": {
                "health": "/health",
                "ingest": "POST /ingest",
                "ingest_text": "POST /ingest/text",
                "sources": "/sources",
                "source": "/sources/{id}",
                "download": "/sources/{id}/download",
                "search": "POST /search",
                "context": "/context",
                "embeddings": "POST /embeddings",
                "openai_embeddings": "POST /v1/embeddings",
                "conversations": "/conversations",
                "docs": "/docs",
            },
        }

    return app


app = create_app()
