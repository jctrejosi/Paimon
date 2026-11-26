"""Fixtures de prueba: app con SQLite en memoria y embeddings deterministas."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app


@dataclass
class Env:
    client: AsyncClient
    app: Any


@pytest.fixture(autouse=True)
def _no_api_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Las pruebas ejercitan las rutas, no la autenticación."""
    monkeypatch.setenv("API_AUTH_REQUIRED", "0")
    monkeypatch.delenv("API_KEYS", raising=False)


@pytest_asyncio.fixture
async def env(tmp_path) -> Env:
    settings = Settings(
        database_url="sqlite+aiosqlite://",
        embedding_provider="hashing",
        hashing_dimensions=256,
        chunk_size=300,
        chunk_overlap=50,
        deepseek_api_key="",
        project_data_dir=tmp_path / "projects",
        upload_dir=tmp_path / "uploads",
    )
    app = create_app(settings)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield Env(client=client, app=app)

    await app.state.embedder.aclose()
    await app.state.reranker.aclose()
    await app.state.databases.close()
