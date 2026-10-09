"""Pruebas de la API usando un proveedor falso (sin red ni credenciales)."""

from __future__ import annotations

import base64
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app, manager
from app.providers.base import ImageProvider, ProviderResult, RawImage

# PNG 1x1 transparente válido.
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


class FakeProvider(ImageProvider):
    name = "comfyui"  # reutiliza el proveedor por defecto (siempre "configurado")

    @classmethod
    def is_configured(cls, settings) -> bool:
        return True

    async def generate(self, request) -> ProviderResult:
        return ProviderResult(
            provider=self.name,
            model="fake-model",
            images=[
                RawImage(data=_PNG, mime_type="image/png", seed=123)
                for _ in range(request.count)
            ],
            metadata={"echo": request.prompt},
        )


@pytest.fixture
def client() -> Iterator[TestClient]:
    get_settings.cache_clear()
    manager._instances["comfyui"] = FakeProvider(get_settings())
    with TestClient(app) as test_client:
        yield test_client
    manager._instances.clear()


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "comfyui" in body["configured_providers"]


def test_list_providers(client: TestClient) -> None:
    resp = client.get("/providers")
    assert resp.status_code == 200
    names = {p["name"] for p in resp.json()["providers"]}
    assert {"comfyui", "openai", "stability", "replicate", "fal", "bfl"} <= names
    comfy = next(p for p in resp.json()["providers"] if p["name"] == "comfyui")
    assert comfy["configured"] is True


def test_generate_url_format(client: TestClient) -> None:
    resp = client.post("/generate", json={"prompt": "un gato", "count": 2})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider"] == "comfyui"
    assert len(body["images"]) == 2
    url = body["images"][0]["url"]
    assert "/images/" in url

    # La imagen generada se sirve por la API.
    served = client.get(url.replace(str(client.base_url), ""))
    assert served.status_code == 200
    assert served.content == _PNG


def test_generate_b64_format(client: TestClient) -> None:
    resp = client.post(
        "/generate", json={"prompt": "un perro", "response_format": "b64_json"}
    )
    assert resp.status_code == 200, resp.text
    image = resp.json()["images"][0]
    assert image["b64_json"]
    assert base64.b64decode(image["b64_json"]) == _PNG


def test_unknown_provider(client: TestClient) -> None:
    resp = client.post("/generate", json={"prompt": "x", "provider": "inventado"})
    assert resp.status_code == 404


def test_validation_error(client: TestClient) -> None:
    resp = client.post("/generate", json={"prompt": ""})
    assert resp.status_code == 422
