"""Consultas a la base de datos del servicio RAG."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import Chunk, Conversation, Document, IngestionJob, Source


def _namespace_filter(bot_id: str | None):
    """FILTRO de namespace: un bot_id concreto o el espacio global (NULL)."""
    return Source.bot_id.is_(None) if bot_id is None else Source.bot_id == bot_id


async def list_sources(
    session: AsyncSession, bot_id: str | None = None, status: str | None = None
) -> list[Source]:
    stmt = select(Source).where(_namespace_filter(bot_id))
    if status:
        stmt = stmt.where(Source.status == status)
    stmt = stmt.order_by(Source.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_source(session: AsyncSession, source_id: uuid.UUID) -> Source | None:
    result = await session.execute(
        select(Source)
        .options(
            selectinload(Source.documents).selectinload(Document.chunks),
            selectinload(Source.jobs),
        )
        .where(Source.id == source_id)
    )
    return result.scalars().unique().one_or_none()


async def latest_job(
    session: AsyncSession, source_id: uuid.UUID
) -> IngestionJob | None:
    result = await session.execute(
        select(IngestionJob)
        .where(IngestionJob.source_id == source_id)
        .order_by(IngestionJob.created_at.desc())
        .limit(1)
    )
    return result.scalars().first()


async def candidate_chunks(
    session: AsyncSession, bot_id: str | None, limit: int
) -> list[dict]:
    """Chunks de un namespace con su embedding, listos para puntuar."""
    result = await session.execute(
        select(
            Chunk.id,
            Chunk.document_id,
            Chunk.chunk_index,
            Chunk.content,
            Chunk.embedding,
            Document.title,
        )
        .join(Document, Document.id == Chunk.document_id)
        .join(Source, Source.id == Document.source_id)
        .where(_namespace_filter(bot_id), Source.status == "completed")
        .order_by(Chunk.document_id, Chunk.chunk_index)
        .limit(limit)
    )
    return [
        {
            "chunk_id": row.id,
            "document_id": row.document_id,
            "chunk_index": row.chunk_index,
            "content": row.content,
            "embedding": row.embedding,
            "document_title": row.title,
        }
        for row in result.all()
    ]


async def add_conversation(session: AsyncSession, conversation: Conversation) -> None:
    session.add(conversation)
    await session.commit()


async def list_conversations(
    session: AsyncSession, user_id: str, limit: int = 50
) -> list[Conversation]:
    result = await session.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
