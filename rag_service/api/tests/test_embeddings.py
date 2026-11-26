from __future__ import annotations

import pytest

from app.embeddings import HashingEmbedding, build_embedding_provider, cosine_similarity
from app.config import Settings


async def test_hashing_is_deterministic() -> None:
    provider = HashingEmbedding(64)
    first = (await provider.embed(["tomate temperatura"]))[0]
    second = (await provider.embed(["tomate temperatura"]))[0]
    assert first == second
    assert len(first) == 64


async def test_similar_texts_score_higher() -> None:
    provider = HashingEmbedding(128)
    query, similar, other = await provider.embed(
        ["temperatura del tomate", "el tomate necesita temperatura", "lechuga"]
    )
    assert cosine_similarity(query, similar) > cosine_similarity(query, other)


def test_cosine_handles_mismatched_dimensions() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0


def test_build_provider_selects_hashing() -> None:
    provider = build_embedding_provider(Settings(embedding_provider="hashing"))
    assert provider.name == "hashing"


def test_openai_without_key_is_rejected() -> None:
    with pytest.raises(RuntimeError):
        build_embedding_provider(Settings(embedding_provider="openai"))
