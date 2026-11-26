"""Rutas HTTP del servicio RAG (compatibles con knowledge-service)."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, Query, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import text

from .deps import ServiceDep, SettingsDep
from .schemas import (
    ConversationRequest,
    EmbeddingsRequest,
    HealthResponse,
    OpenAIEmbeddingsRequest,
    SearchRequest,
    TextIngestRequest,
)
from .service import source_detail_to_dict, source_to_dict

router = APIRouter()


# ─── Estado ────────────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse, tags=["health"])
async def health(request: Request, settings: SettingsDep) -> HealthResponse:
    db_status = "connected"
    try:
        database = await request.app.state.databases.get(settings.default_project)
        async with database.session_factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"

    return HealthResponse(
        status="ok" if db_status == "connected" else "degraded",
        service=settings.app_name,
        database=db_status,
        embedding_provider=settings.embedding_provider,
        embedding_model=settings.embedding_model,
        rerank_enabled=settings.rerank_enabled,
    )


# ─── Ingesta ───────────────────────────────────────────────────────────────

@router.post("/ingest", status_code=status.HTTP_201_CREATED, tags=["ingest"])
async def ingest_file(
    service: ServiceDep,
    file: UploadFile = File(...),
    bot_id: str | None = Form(None),
    title: str | None = Form(None),
    description: str | None = Form(None),
    cloudinary_url: str | None = Form(None),
) -> dict:
    """Sube un documento, lo extrae, trocea y vectoriza (síncrono)."""
    data = await file.read()
    source = await service.ingest_file(
        bot_id=bot_id,
        filename=file.filename or "upload.bin",
        data=data,
        title=title,
        description=description,
        cloudinary_url=cloudinary_url,
    )
    job_id = str(source.jobs[0].id) if source.jobs else None
    return {
        "source_id": str(source.id),
        "job_id": job_id,
        "filename": file.filename,
        "status": source.status,
        "error_message": source.error_message,
        "message": "Ingesta completada.",
    }


@router.post("/ingest/text", status_code=status.HTTP_201_CREATED, tags=["ingest"])
async def ingest_text(service: ServiceDep, payload: TextIngestRequest) -> dict:
    source = await service.ingest_text(
        bot_id=payload.bot_id,
        title=payload.title,
        text=payload.text,
        description=payload.description,
    )
    job_id = str(source.jobs[0].id) if source.jobs else None
    return {
        "source_id": str(source.id),
        "job_id": job_id,
        "filename": None,
        "status": source.status,
        "error_message": source.error_message,
        "message": "Ingesta completada.",
    }


# ─── Fuentes ───────────────────────────────────────────────────────────────

@router.get("/sources", tags=["sources"])
async def list_sources(
    service: ServiceDep,
    status_filter: str | None = Query(None, alias="status"),
    bot_id: str | None = None,
) -> list[dict]:
    sources = await service.list_sources(bot_id, status_filter)
    return [source_to_dict(source) for source in sources]


@router.get("/sources/{source_id}", tags=["sources"])
async def get_source(source_id: uuid.UUID, service: ServiceDep) -> dict:
    from . import repository

    source = await service.get_source(source_id)
    job = await repository.latest_job(service.session, source_id)
    return source_detail_to_dict(source, job)


@router.get("/sources/{source_id}/download", tags=["sources"])
async def download_source(source_id: uuid.UUID, service: ServiceDep):
    source = await service.get_source(source_id)
    if source.file_path and Path(source.file_path).exists():
        return FileResponse(
            source.file_path,
            media_type=source.file_type or "application/octet-stream",
            filename=source.original_filename or Path(source.file_path).name,
        )
    if source.cloudinary_url:
        return RedirectResponse(url=source.cloudinary_url)
    return Response(
        status_code=404,
        content='{"detail":"El archivo original no está disponible"}',
        media_type="application/json",
    )


@router.delete("/sources/{source_id}", tags=["sources"])
async def delete_source(source_id: uuid.UUID, service: ServiceDep) -> dict:
    source = await service.delete_source(source_id)
    return {
        "ok": True,
        "deleted": {
            "id": str(source_id),
            "original_filename": source.original_filename,
        },
    }


# ─── Embeddings ────────────────────────────────────────────────────────────

@router.post("/embeddings", tags=["embeddings"])
async def embeddings(payload: EmbeddingsRequest, service: ServiceDep) -> dict:
    """Genera embeddings para una lista de textos."""
    vectors = await service.embed(payload.texts)
    return {
        "model": service.embedder.model,
        "dimensions": len(vectors[0]) if vectors else 0,
        "embeddings": vectors,
    }


@router.post("/v1/embeddings", tags=["embeddings"])
async def openai_embeddings(
    payload: OpenAIEmbeddingsRequest, service: ServiceDep
) -> dict:
    """Endpoint compatible con OpenAI para generar embeddings."""
    texts = [payload.input] if isinstance(payload.input, str) else payload.input
    vectors = await service.embed(texts)
    return {
        "object": "list",
        "model": service.embedder.model,
        "data": [
            {"object": "embedding", "index": index, "embedding": vector}
            for index, vector in enumerate(vectors)
        ],
    }


# ─── Búsqueda ──────────────────────────────────────────────────────────────

@router.post("/search", tags=["search"])
async def search(
    payload: SearchRequest,
    service: ServiceDep,
    bot_id: str | None = None,
) -> dict:
    results = await service.search(
        payload.query,
        bot_id=bot_id,
        top_k=payload.top_k,
        min_similarity=payload.min_similarity,
        use_reranker=payload.use_reranker,
    )
    return {"query": payload.query, "results": results}


@router.get("/context", tags=["search"])
async def context(
    service: ServiceDep,
    q: str,
    bot_id: str | None = None,
    top_k: int = 3,
) -> dict:
    text_out, used = await service.build_context(q, bot_id=bot_id, top_k=top_k)
    return {"query": q, "context": text_out, "chunks_used": used}


# ─── Conversaciones (paridad) ──────────────────────────────────────────────

@router.post("/conversations", status_code=status.HTTP_201_CREATED, tags=["conversations"])
async def log_conversation(payload: ConversationRequest, service: ServiceDep) -> dict:
    conversation = await service.log_conversation(
        bot_id=payload.bot_id,
        user_id=payload.user_id,
        user_name=payload.user_name,
        message=payload.message,
        response=payload.response,
        chunks_used=payload.chunks_used,
    )
    return {"id": str(conversation.id), "status": "logged"}


@router.get("/conversations/{user_id}", tags=["conversations"])
async def get_conversations(
    user_id: str, service: ServiceDep, limit: int = 50
) -> list[dict]:
    rows = await service.list_conversations(user_id, limit)
    return [
        {
            "id": str(row.id),
            "user_id": row.user_id,
            "user_name": row.user_name,
            "message": row.message,
            "response": row.response,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]
