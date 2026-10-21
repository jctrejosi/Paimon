"""Fixtures de prueba: proveedor falso y cliente HTTP.

El proveedor falso evita instalar `rembg`/ONNX y descargar modelos: las pruebas
solo ejercitan el contrato de la API.
"""

from __future__ import annotations

import io
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.config import get_settings
from app.main import app, manager
from app.providers.base import RemoveBgProvider, RemoveBgRequest, RemoveBgResult


def make_png(width: int = 64, height: int = 64) -> bytes:
    """PNG RGBA sintético (círculo opaco sobre fondo blanco)."""
    image = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 8, width - 8, height - 8), fill=(200, 30, 30, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class FakeProvider(RemoveBgProvider):
    """Recorta un círculo (simula el sujeto) y respeta fondo/formato."""

    name = "local"

    @classmethod
    def is_configured(cls, settings) -> bool:
        return True

    @classmethod
    def default_model(cls, settings) -> str | None:
        return settings.local_rembg_model

    async def remove_background(self, request: RemoveBgRequest) -> RemoveBgResult:
        image = Image.open(io.BytesIO(request.data)).convert("RGBA")
        mask = Image.new("L", image.size, 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse(
            (image.width // 4, image.height // 4, 3 * image.width // 4, 3 * image.height // 4),
            fill=255,
        )
        image.putalpha(mask)

        if request.background:
            raw = request.background.lstrip("#")
            rgb = tuple(int(raw[i : i + 2], 16) for i in (0, 2, 4))
            canvas = Image.new("RGBA", image.size, (*rgb, 255))
            canvas.alpha_composite(image)
            image = canvas

        if request.output_format == "webp":
            fmt, mime = "WEBP", "image/webp"
        else:
            fmt, mime = "PNG", "image/png"

        buffer = io.BytesIO()
        image.save(buffer, format=fmt)
        return RemoveBgResult(
            provider=self.name,
            model=request.model or "fake-model",
            data=buffer.getvalue(),
            mime_type=mime,
            width=image.width,
            height=image.height,
        )


@pytest.fixture
def png() -> bytes:
    return make_png()


@pytest.fixture
def client() -> Iterator[TestClient]:
    get_settings.cache_clear()
    manager._instances["local"] = FakeProvider(get_settings())
    with TestClient(app) as test_client:
        yield test_client
    manager._instances.clear()
