"""Lógica del servicio RAG: ingesta, recuperación y utilidades."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from . import repository
from .chunking import chunk_text
from .config import Settings
from .embeddings import EmbeddingProvider, cosine_similarity
from .extraction import ExtractionError, extract_file_bytes
from .models import Chunk, Conversation, Document, IngestionJob, Source
from .reranker import Reranker

logger = logging.getLogger("paimon-rag.service")


class RagService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        embedder: EmbeddingProvider,
        reranker: Reranker,
        project: str,
    ) -> None:
        self.session = session
        self.settings = settings
        self.embedder = embedder
        self.reranker = reranker
        self.project = project

    # ── Ingesta ───────────────────────────────────────────────────────────

    async def ingest_file(
        self,
        *,
        bot_id: str | None,
        filename: str,
        data: bytes,
        title: str | None = None,
        description: str | None = None,
        cloudinary_url: str | None = None,
    ) -> Source:
        if not filename:
            raise HTTPException(status_code=400, detail="archivo sin nombre")
        if not data:
            raise HTTPException(status_code=400, detail="el archivo está vacío")
        if len(data) > self.settings.max_upload_bytes:
            raise HTTPException(
                status_code=413,
                detail=(
                    "el archivo supera el límite de "
                    f"{self.settings.rag_max_upload_mb} MB"
                ),
            )

        try:
            extraction = extract_file_bytes(data, filename)
        except ExtractionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        # Guarda el original (best-effort) para el endpoint de descarga.
        stored_path = self._store_upload(filename, data)
        ext = Path(filename).suffix.lower()

        return await self._ingest_text(
            bot_id=bot_id,
            text=extraction.text,
            title=title or Path(filename).name,
            description=description,
            source_type="file",
            original_filename=filename,
            file_type=ext,
            file_size_bytes=len(data),
            file_path=stored_path,
            cloudinary_url=cloudinary_url,
            page_count=extraction.page_count,
        )

    async def ingest_text(
        self,
        *,
        bot_id: str | None,
        title: str,
        text: str,
        description: str | None = None,
    ) -> Source:
        if not text or not text.strip():
            raise HTTPException(status_code=422, detail="el texto está vacío")
        return await self._ingest_text(
            bot_id=bot_id,
            text=text,
            title=title,
            description=description,
            source_type="text",
        )

    async def _ingest_text(
        self,
        *,
        bot_id: str | None,
        text: str,
        title: str,
        description: str | None,
        source_type: str,
        original_filename: str | None = None,
        file_type: str | None = None,
        file_size_bytes: int | None = None,
        file_path: str | None = None,
        cloudinary_url: str | None = None,
        page_count: int | None = None,
    ) -> Source:
        text = text.strip()
        chunks = chunk_text(
            text,
            strategy="sections",
            chunk_size=self.settings.chunk_size,
            overlap=self.settings.chunk_overlap,
        )
        if not chunks:
            raise HTTPException(
                status_code=422, detail="no se generaron fragmentos del contenido"
            )

        # Embeddings fuera de la transacción de escritura (llamadas costosas).
        embeddings = await self._embed_batches(chunks)

        now = datetime.now(UTC)
        source = Source(
            id=uuid.uuid4(),
            bot_id=bot_id,
            source_type=source_type,
            title=title[:500],
            description=description,
            original_filename=original_filename,
            file_type=file_type,
            file_size_bytes=file_size_bytes,
            file_path=file_path,
            cloudinary_url=cloudinary_url,
            status="completed",
            meta={
                "chunk_size": self.settings.chunk_size,
                "chunk_overlap": self.settings.chunk_overlap,
                "embedding_provider": self.embedder.name,
                "embedding_model": self.embedder.model,
            },
        )
        document = Document(
            id=uuid.uuid4(),
            title=title[:500],
            content=text,
            page_count=page_count,
            char_count=len(text),
        )
        document.chunks = [
            Chunk(
                id=uuid.uuid4(),
                chunk_index=index,
                content=content,
                char_count=len(content),
                embedding=embeddings[index],
                embedding_model=self.embedder.model,
            )
            for index, content in enumerate(chunks)
        ]
        source.documents = [document]
        job = IngestionJob(
            id=uuid.uuid4(),
            status="completed",
            progress=100,
            step_log=[
                {
                    "timestamp": now.isoformat(),
                    "step": "completed",
                    "message": f"{len(chunks)} fragmentos vectorizados",
                }
            ],
            started_at=now,
            completed_at=now,
        )
        source.jobs = [job]

        self.session.add(source)
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return source

    async def _embed_batches(self, chunks: list[str]) -> list[list[float]]:
        batch_size = max(1, self.settings.embedding_batch_size)
        vectors: list[list[float]] = []
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            batch_vectors = await self.embedder.embed(batch)
            if len(batch_vectors) != len(batch):
                raise HTTPException(
                    status_code=502,
                    detail="el proveedor de embeddings devolvió un número incorrecto de vectores",
                )
            vectors.extend(batch_vectors)
        return vectors

    def _store_upload(self, filename: str, data: bytes) -> str | None:
        try:
            project_dir = self.settings.upload_dir / self.project
            project_dir.mkdir(parents=True, exist_ok=True)
            safe_name = Path(filename).name or "upload.bin"
            path = project_dir / f"{uuid.uuid4().hex}_{safe_name}"
            path.write_bytes(data)
            return str(path)
        except OSError as exc:  # best-effort: la ingesta sigue sin el original
            logger.warning("No se pudo guardar el archivo original: %s", exc)
            return None

    # ── Embeddings ────────────────────────────────────────────────────────

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await self.embedder.embed(texts)

    # ── Consulta / administración ─────────────────────────────────────────

    async def list_sources(
        self, bot_id: str | None, status: str | None = None
    ) -> list[Source]:
        return await repository.list_sources(self.session, bot_id, status)

    async def get_source(self, source_id: uuid.UUID) -> Source:
        source = await repository.get_source(self.session, source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="Fuente no encontrada")
        return source

    async def delete_source(self, source_id: uuid.UUID) -> Source:
        source = await self.get_source(source_id)
        file_path = source.file_path
        await self.session.delete(source)
        await self.session.commit()
        if file_path:
            self._remove_file(file_path)
        return source

    @staticmethod
    def _remove_file(path: str) -> None:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass

    # ── Recuperación ──────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        *,
        bot_id: str | None,
        top_k: int,
        min_similarity: float,
        use_reranker: bool,
    ) -> list[dict[str, Any]]:
        query_vector = (await self.embedder.embed([query]))[0]
        candidates = await repository.candidate_chunks(
            self.session, bot_id, self.settings.max_scan_chunks
        )

        scored: list[dict[str, Any]] = []
        for candidate in candidates:
            embedding = candidate.get("embedding")
            similarity = cosine_similarity(query_vector, embedding or [])
            if similarity < min_similarity:
                continue
            item = dict(candidate)
            item["similarity"] = round(similarity, 4)
            scored.append(item)

        scored.sort(key=lambda item: item["similarity"], reverse=True)
        if not scored:
            return []

        if use_reranker and self.reranker.configured:
            pool = scored[: self.settings.max_rerank_candidates]
            if len(pool) > 1:
                scored = await self.reranker.rerank(query, pool, top_k=top_k)
            else:
                scored = pool
        else:
            scored = scored[:top_k]

        return [_serialize_result(item) for item in scored[:top_k]]

    async def build_context(
        self, query: str, *, bot_id: str | None, top_k: int
    ) -> tuple[str, int]:
        results = await self.search(
            query,
            bot_id=bot_id,
            top_k=top_k,
            min_similarity=0.0,
            use_reranker=False,
        )
        if not results:
            return "", 0
        blocks = [
            f"[{item['document_title'] or 'documento'}]\n{item['content']}"
            for item in results
        ]
        return "\n\n---\n\n".join(blocks), len(blocks)

    # ── Conversaciones (paridad con knowledge-service) ────────────────────

    async def log_conversation(
        self,
        *,
        bot_id: str | None,
        user_id: str,
        user_name: str | None,
        message: str,
        response: str,
        chunks_used: list[str],
    ) -> Conversation:
        conversation = Conversation(
            id=uuid.uuid4(),
            bot_id=bot_id,
            user_id=user_id,
            user_name=user_name,
            message=message,
            response=response,
            chunks_used=chunks_used,
        )
        await repository.add_conversation(self.session, conversation)
        return conversation

    async def list_conversations(
        self, user_id: str, limit: int
    ) -> list[Conversation]:
        return await repository.list_conversations(self.session, user_id, limit)


def _serialize_result(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "chunk_id": str(item["chunk_id"]),
        "content": item["content"],
        "chunk_index": item["chunk_index"],
        "document_id": str(item["document_id"]),
        "document_title": item.get("document_title"),
        "similarity": item.get("similarity"),
        "rerank_score": item.get("rerank_score"),
        "rerank_position": item.get("rerank_position"),
    }


# ── Serializadores para respuestas HTTP ─────────────────────────────────

def source_to_dict(source: Source) -> dict[str, Any]:
    return {
        "id": str(source.id),
        "source_type": source.source_type,
        "title": source.title,
        "description": source.description,
        "status": source.status,
        "error_message": source.error_message,
        "original_filename": source.original_filename,
        "file_type": source.file_type,
        "file_size_bytes": source.file_size_bytes,
        "file_available": bool(
            (source.file_path and Path(source.file_path).exists())
            or source.cloudinary_url
        ),
        "cloudinary_url": source.cloudinary_url,
        "created_at": source.created_at.isoformat() if source.created_at else None,
        "updated_at": source.updated_at.isoformat() if source.updated_at else None,
    }


def source_detail_to_dict(
    source: Source, job: IngestionJob | None
) -> dict[str, Any]:
    documents = []
    for document in source.documents:
        documents.append(
            {
                "id": str(document.id),
                "title": document.title,
                "page_count": document.page_count,
                "char_count": document.char_count,
                "chunks": [
                    {
                        "id": str(chunk.id),
                        "index": chunk.chunk_index,
                        "content_preview": chunk.content[:200],
                        "char_count": chunk.char_count,
                        "has_embedding": chunk.embedding is not None,
                    }
                    for chunk in document.chunks
                ],
            }
        )

    payload = source_to_dict(source)
    payload["metadata"] = source.meta
    return {
        "source": payload,
        "documents": documents,
        "last_job": (
            {
                "id": str(job.id),
                "status": job.status,
                "progress": job.progress,
                "error_message": job.error_message,
                "log": job.step_log,
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "completed_at": (
                    job.completed_at.isoformat() if job.completed_at else None
                ),
            }
            if job
            else None
        ),
    }
