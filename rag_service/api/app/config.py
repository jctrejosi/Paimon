"""Configuración del servicio RAG de Paimon.

Todo se controla por variables de entorno (o un `.env`). Los consumidores
(chatbot-platform y TESIS/plant-service) le hablan por HTTP y aíslan su
contenido con el parámetro `bot_id` (namespace).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

EmbeddingProviderName = Literal["fastembed", "openai", "hashing"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        validate_default=True,
    )

    # --- Servicio ---------------------------------------------------------
    app_name: str = "paimon-rag"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    # Prefijo público cuando un proxy publica la API bajo un subpath (/rag).
    rag_root_path: str = ""
    rag_max_upload_mb: float = 50.0

    # --- Base de datos ----------------------------------------------------
    # SQLite por defecto (desarrollo/tests). En Docker se usa PostgreSQL.
    database_url: str = "sqlite+aiosqlite:///./rag.db"
    # Aislamiento por proyecto: schema de PostgreSQL o archivo SQLite.
    # Proyecto usado si la petición no envía `X-RAG-Project`.
    default_project: str = "default"
    schema_prefix: str = "rag_"
    project_data_dir: Path = Path("data/projects")
    upload_dir: Path = Path("uploads")

    # --- Troceado ---------------------------------------------------------
    chunk_size: int = 600
    chunk_overlap: int = 100
    embedding_batch_size: int = 32

    # --- Embeddings -------------------------------------------------------
    embedding_provider: EmbeddingProviderName = "fastembed"
    # Modelos locales de fastembed (CPU). Ej. multilingüe:
    #   intfloat/multilingual-e5-small | BAAI/bge-small-en-v1.5
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    # Solo proveedor `hashing` (dimensiones del vector). Los demás lo ignoran.
    hashing_dimensions: int = 512
    fastembed_cache_dir: Path = Path("models")
    # Proveedor `openai` (o cualquier endpoint compatible).
    embedding_api_key: str = ""
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_timeout_seconds: float = 30.0

    # --- Búsqueda / reranking --------------------------------------------
    default_top_k: int = 5
    # Máximo de chunks por namespace que se puntúan (cosine) por consulta.
    max_scan_chunks: int = 5000
    # Máximo de candidatos que se envían al reranker.
    max_rerank_candidates: int = 40
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    deepseek_timeout_seconds: float = 30.0

    @property
    def max_upload_bytes(self) -> int:
        return int(self.rag_max_upload_mb * 1024 * 1024)

    @property
    def rerank_enabled(self) -> bool:
        return bool(self.deepseek_api_key.strip())

    @property
    def is_postgres(self) -> bool:
        return self.database_url.split(":", 1)[0].split("+", 1)[0] in {
            "postgresql",
            "postgres",
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
