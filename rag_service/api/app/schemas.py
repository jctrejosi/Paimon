"""Esquemas de entrada/salida del servicio RAG."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)
    min_similarity: float = 0.0
    use_reranker: bool = False


class TextIngestRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    text: str = Field(min_length=1)
    bot_id: str | None = None
    description: str | None = None


class ConversationRequest(BaseModel):
    user_id: str
    user_name: str | None = ""
    bot_id: str | None = None
    message: str
    response: str
    chunks_used: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    service: str
    database: str
    embedding_provider: str
    embedding_model: str
    rerank_enabled: bool


class EmbeddingsRequest(BaseModel):
    texts: list[str] = Field(min_length=1)


class OpenAIEmbeddingsRequest(BaseModel):
    """Formato compatible con POST /v1/embeddings de OpenAI."""

    input: str | list[str]
    model: str | None = None
