"""Fixtures de prueba: proveedor falso, cliente HTTP y audio sintético.

Desactivamos la autenticación para que las pruebas de contrato no dependan de
claves: el middleware lee `API_AUTH_REQUIRED` en cada petición, así que basta con
fijarlo antes de importar la app.
"""

from __future__ import annotations

import io
import os
import wave
from collections.abc import Iterator

import numpy as np
import pytest
from fastapi.testclient import TestClient

# Desactiva la autenticación para el conjunto de pruebas (antes de importar app).
os.environ["API_AUTH_REQUIRED"] = "0"

from app.audio import pcm_to_wav  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.main import app, manager  # noqa: E402
from app.providers.base import (  # noqa: E402
    AudioChunk,
    SynthesisResult,
    TTSSynthesizer,
)
from app.schemas import Voice  # noqa: E402

SAMPLE_RATE = 24000


class FakeProvider(TTSSynthesizer):
    """Reutiliza el proveedor por defecto ('kokoro') y devuelve silencio."""

    name = "kokoro"
    supports_cloning = False

    @classmethod
    def is_configured(cls, settings) -> bool:
        return True

    @classmethod
    def default_model(cls, settings) -> str | None:
        return "Kokoro-82M"

    async def synthesize(self, request) -> SynthesisResult:
        pcm = b"\x00\x00" * 1000
        return SynthesisResult(
            provider=self.name,
            voice_id=request.voice_id or "ef_dora",
            audio=pcm if request.format == "pcm" else pcm_to_wav(pcm, SAMPLE_RATE),
            sample_rate=SAMPLE_RATE,
            duration_sec=1000 / SAMPLE_RATE,
            format=request.format,
        )

    async def synthesize_stream(self, request):
        half = b"\x00\x00" * 500
        yield AudioChunk(data=half, index=0, final=False, sample_rate=SAMPLE_RATE)
        yield AudioChunk(data=half, index=1, final=True, sample_rate=SAMPLE_RATE)

    async def list_voices(self):
        return [
            Voice(
                voice_id="ef_dora",
                name="Dora (e)",
                provider=self.name,
                kind="builtin",
                model="Kokoro-82M",
                sample_rate=SAMPLE_RATE,
                language="e",
            )
        ]


def make_wav(seconds: float = 1.0, rate: int = 16000) -> bytes:
    """Genera un WAV PCM de 16 bits con un tono (audio sintético válido)."""
    n = int(seconds * rate)
    t = np.arange(n) / rate
    samples = (0.3 * np.sin(2 * np.pi * 300.0 * t)).astype(np.float32)
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(pcm.tobytes())
    return buffer.getvalue()


@pytest.fixture
def wav() -> bytes:
    """Un segundo de tono mono a 16 kHz (para el endpoint de clonación)."""
    return make_wav()


@pytest.fixture
def client() -> Iterator[TestClient]:
    get_settings.cache_clear()
    manager._instances["kokoro"] = FakeProvider(get_settings())
    with TestClient(app) as test_client:
        yield test_client
    manager._instances.clear()
