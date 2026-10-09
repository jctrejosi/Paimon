"""Fixtures de prueba: proveedor falso, cliente HTTP y audio sintético."""

from __future__ import annotations

import io
import struct
import wave
from collections.abc import Iterator

import numpy as np
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


def make_wav(
    seconds: float = 1.0, rate: int = 16000, channels: int = 1, freq: float = 300.0
) -> bytes:
    """Genera un WAV PCM de 16 bits con un tono (audio sintético válido)."""
    n = int(seconds * rate)
    t = np.arange(n) / rate
    left = (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    if channels == 2:
        right = (0.1 * np.sin(2 * np.pi * (freq * 0.7) * t)).astype(np.float32)
        samples = np.stack([left, right], axis=1)
    else:
        samples = left
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(pcm.tobytes())
    return buffer.getvalue()


@pytest.fixture
def wav() -> bytes:
    """Un segundo de tono mono a 16 kHz."""
    return make_wav()


@pytest.fixture
def client() -> Iterator[TestClient]:
    get_settings.cache_clear()
    manager._instances["local"] = FakeProvider(get_settings())
    with TestClient(app) as test_client:
        yield test_client
    manager._instances.clear()


def read_wav_header(data: bytes) -> tuple[int, int]:
    """Devuelve (canales, sample_rate) de un WAV en bytes."""
    with wave.open(io.BytesIO(data), "rb") as reader:
        return reader.getnchannels(), reader.getframerate()


# Silencia el aviso de struct sin usar en linters estrictos.
_ = struct
