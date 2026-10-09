"""Fixtures de prueba: proveedor falso y cliente HTTP (sin red ni modelo real)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app, manager
from app.providers.base import Segment, TranscriptionProvider, TranscriptResult


class FakeProvider(TranscriptionProvider):
    """Reutiliza el proveedor por defecto ('local') y devuelve texto fijo."""

    name = "local"

    @classmethod
    def is_configured(cls, settings) -> bool:
        return True

    async def transcribe(self, request) -> TranscriptResult:
        return TranscriptResult(
            provider=self.name,
            model=request.model or "fake-model",
            text="hola mundo",
            language=request.language or "es",
            language_probability=0.99,
            duration=1.5,
            segments=[Segment(start=0.0, end=1.5, text="hola mundo")],
            metadata={"filename": request.filename, "verbose": request.verbose},
        )


@pytest.fixture
def client() -> Iterator[TestClient]:
    get_settings.cache_clear()
    manager._instances["local"] = FakeProvider(get_settings())
    with TestClient(app) as test_client:
        yield test_client
    manager._instances.clear()
