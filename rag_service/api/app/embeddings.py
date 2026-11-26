"""Proveedores de embeddings del servicio RAG.

Selección por `EMBEDDING_PROVIDER`:

- `fastembed` (defecto): modelos ONNX en CPU, local-first, sin credenciales.
  Descarga el modelo la primera vez (se cachea en `FASTEMBED_CACHE_DIR`).
- `openai`: cualquier endpoint compatible con la API de embeddings de OpenAI
  (`/embeddings`), p. ej. OpenAI o un vLLM local.
- `hashing`: vectorizador determinista offline (feature hashing) sin modelos;
  útil para tests y como fallback sin descargas.

Las importaciones pesadas son perezosas para que el servicio arranque sin la
dependencia instalada si no se usa ese proveedor.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
from abc import ABC, abstractmethod

import httpx

from .config import Settings

_WORD_RE = re.compile(r"[a-z0-9áéíóúñü]+", re.IGNORECASE)


class EmbeddingProvider(ABC):
    name: str
    model: str

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Devuelve un vector por texto, en el mismo orden."""

    async def aclose(self) -> None:  # pragma: no cover - por defecto no-op
        return None


class HashingEmbedding(EmbeddingProvider):
    """Feature hashing determinista: rápido, offline y sin dependencias."""

    name = "hashing"

    def __init__(self, dimensions: int = 512) -> None:
        self.dimensions = max(8, dimensions)
        self.model = f"hashing-{self.dimensions}"

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in _WORD_RE.findall(text.lower()):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm > 0:
            vector = [value / norm for value in vector]
        return vector

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]


class FastEmbedEmbedding(EmbeddingProvider):
    """Embeddings locales con fastembed (ONNX, CPU)."""

    name = "fastembed"

    def __init__(self, model: str, cache_dir: str) -> None:
        self.model = model
        self._cache_dir = cache_dir
        self._embedder = None
        self._lock = asyncio.Lock()

    def _load(self):
        if self._embedder is None:
            try:
                from fastembed import TextEmbedding
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError(
                    "EMBEDDING_PROVIDER=fastembed requiere el paquete 'fastembed' "
                    "(pip install fastembed) o usa otro proveedor."
                ) from exc
            self._embedder = TextEmbedding(
                model_name=self.model, cache_dir=self._cache_dir
            )
        return self._embedder

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        embedder = self._load()
        return [list(map(float, vector)) for vector in embedder.embed(texts)]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # Carga e inferencia son síncronas (CPU): no bloquear el event loop ni
        # cargar el modelo dos veces en ingestas concurrentes.
        async with self._lock:
            return await asyncio.to_thread(self._embed_sync, texts)


class OpenAIEmbedding(EmbeddingProvider):
    """Embeddings por HTTP en un endpoint compatible con OpenAI."""

    name = "openai"

    def __init__(self, settings: Settings) -> None:
        self.model = settings.embedding_model
        self._url = settings.embedding_base_url.rstrip("/") + "/embeddings"
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {settings.embedding_api_key}",
                "Content-Type": "application/json",
            },
            timeout=settings.embedding_timeout_seconds,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await self._client.post(
            self._url, json={"model": self.model, "input": texts}
        )
        response.raise_for_status()
        data = sorted(response.json()["data"], key=lambda item: item["index"])
        return [item["embedding"] for item in data]

    async def aclose(self) -> None:
        await self._client.aclose()


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    """Construye el proveedor configurado."""
    provider = settings.embedding_provider
    if provider == "openai":
        if not settings.embedding_api_key:
            raise RuntimeError(
                "EMBEDDING_PROVIDER=openai requiere EMBEDDING_API_KEY."
            )
        return OpenAIEmbedding(settings)
    if provider == "hashing":
        return HashingEmbedding(settings.hashing_dimensions)
    return FastEmbedEmbedding(
        model=settings.embedding_model,
        cache_dir=str(settings.fastembed_cache_dir),
    )


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Similitud coseno entre dos vectores (0 si alguno es nulo)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
