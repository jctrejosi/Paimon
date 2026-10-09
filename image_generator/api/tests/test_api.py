"""Pruebas de la API usando un proveedor falso (sin red ni credenciales)."""

from __future__ import annotations

import base64
import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.jobs.backends import build_backends
from app.main import app, jobs, providers, runner
from app.providers.base import ImageProvider, ProviderResult, RawImage
from app.schemas import GenerateRequest

# PNG 1x1 transparente válido.
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
_PNG_B64 = base64.b64encode(_PNG).decode("ascii")


class FakeProvider(ImageProvider):
    name = "comfyui"  # reutiliza el proveedor por defecto (siempre "configurado")
    supports_img2img = True

    last_request: GenerateRequest | None = None

    @classmethod
    def is_configured(cls, settings) -> bool:
        return True

    async def generate(self, request) -> ProviderResult:
        FakeProvider.last_request = request
        return ProviderResult(
            provider=self.name,
            model="fake-model",
            images=[
                RawImage(data=_PNG, mime_type="image/png", seed=123)
                for _ in range(request.count)
            ],
            metadata={"echo": request.prompt},
        )


class _FakeResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code


class FakeWebhookClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def post(self, url: str, json: dict) -> _FakeResponse:
        self.calls.append((url, json))
        return _FakeResponse(200)

    async def aclose(self) -> None:
        pass


@pytest.fixture
def client() -> Iterator[TestClient]:
    get_settings.cache_clear()
    providers._instances["comfyui"] = FakeProvider(get_settings())
    FakeProvider.last_request = None
    # Backends frescos, compartidos por el JobManager (API) y el JobRunner.
    backends = build_backends(get_settings())
    jobs._store, jobs._bus, jobs._queue = backends.store, backends.bus, backends.queue
    assert runner is not None
    runner._store, runner._bus, runner._queue = backends.store, backends.bus, backends.queue
    with TestClient(app) as test_client:
        yield test_client


def _wait_for_job(client: TestClient, job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    body: dict = {}
    while time.time() < deadline:
        body = client.get(f"/jobs/{job_id}").json()
        if body["status"] in {"succeeded", "failed", "canceled"}:
            return body
        time.sleep(0.05)
    raise AssertionError(f"El job {job_id} no terminó a tiempo: {body}")


def test_health(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert "comfyui" in body["configured_providers"]


def test_list_providers(client: TestClient) -> None:
    payload = client.get("/providers").json()
    names = {p["name"] for p in payload["providers"]}
    assert {"comfyui", "openai", "stability", "replicate", "fal", "bfl"} <= names
    comfy = next(p for p in payload["providers"] if p["name"] == "comfyui")
    assert comfy["configured"] is True
    assert comfy["supports_img2img"] is True


def test_generate_url_format(client: TestClient) -> None:
    resp = client.post("/generate", json={"prompt": "un gato", "count": 2})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider"] == "comfyui"
    assert len(body["images"]) == 2

    served = client.get(body["images"][0]["url"].replace(str(client.base_url), ""))
    assert served.status_code == 200
    assert served.content == _PNG


def test_generate_b64_format(client: TestClient) -> None:
    resp = client.post(
        "/generate", json={"prompt": "un perro", "response_format": "b64_json"}
    )
    assert resp.status_code == 200, resp.text
    image = resp.json()["images"][0]
    assert base64.b64decode(image["b64_json"]) == _PNG


def test_unknown_provider(client: TestClient) -> None:
    resp = client.post("/generate", json={"prompt": "x", "provider": "inventado"})
    assert resp.status_code == 404


def test_validation_error(client: TestClient) -> None:
    resp = client.post("/generate", json={"prompt": ""})
    assert resp.status_code == 422


def test_edit_requires_image(client: TestClient) -> None:
    resp = client.post("/edit", json={"prompt": "sin imagen"})
    assert resp.status_code == 422


def test_edit_with_image(client: TestClient) -> None:
    resp = client.post(
        "/edit",
        json={"prompt": "ponle un sombrero", "image": _PNG_B64, "strength": 0.5},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["images"]
    assert FakeProvider.last_request is not None
    assert FakeProvider.last_request.image == _PNG_B64
    assert FakeProvider.last_request.strength == 0.5


def test_edit_rejected_when_unsupported(client: TestClient) -> None:
    class NoEditProvider(FakeProvider):
        supports_img2img = False

    providers._instances["comfyui"] = NoEditProvider(get_settings())
    resp = client.post("/edit", json={"prompt": "x", "image": _PNG_B64})
    assert resp.status_code == 400
    assert "no soporta image-to-image" in resp.json()["detail"]


def test_job_lifecycle(client: TestClient) -> None:
    resp = client.post("/jobs", json={"prompt": "fondo de pantalla", "count": 1})
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["id"]
    assert resp.json()["status"] in {"queued", "running"}

    job = _wait_for_job(client, job_id)
    assert job["status"] == "succeeded"
    assert job["result"]["images"][0]["url"].startswith("/images/")

    listed = client.get("/jobs").json()
    assert any(j["id"] == job_id for j in listed)


def test_job_webhook_delivery(client: TestClient) -> None:
    fake = FakeWebhookClient()
    assert runner is not None
    runner._webhooks = fake  # type: ignore[assignment]

    resp = client.post(
        "/jobs",
        json={"prompt": "con webhook", "webhook_url": "https://example.test/hook"},
    )
    job_id = resp.json()["id"]
    job = _wait_for_job(client, job_id)

    assert job["status"] == "succeeded"
    assert job["webhook_delivered"] is True
    assert fake.calls and fake.calls[0][0] == "https://example.test/hook"
    assert fake.calls[0][1]["status"] == "succeeded"


def test_job_not_found(client: TestClient) -> None:
    assert client.get("/jobs/no-existe").status_code == 404


def test_job_events_stream(client: TestClient) -> None:
    resp = client.post("/jobs", json={"prompt": "con eventos"})
    job_id = resp.json()["id"]

    data_lines: list[str] = []
    with client.stream("GET", f"/jobs/{job_id}/events") as stream:
        assert stream.status_code == 200
        assert stream.headers["content-type"].startswith("text/event-stream")
        for line in stream.iter_lines():
            if line.startswith("data:"):
                data_lines.append(line)

    assert data_lines
    assert "succeeded" in data_lines[-1]


def test_cancel_job(client: TestClient) -> None:
    resp = client.post("/jobs", json={"prompt": "cancelar"})
    job_id = resp.json()["id"]
    cancelled = client.delete(f"/jobs/{job_id}").json()
    assert cancelled["status"] in {"canceled", "succeeded"}


def test_metrics_endpoint(client: TestClient) -> None:
    client.post("/generate", json={"prompt": "metricas"})
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "paimon_http_requests_total" in resp.text
    assert "paimon_generations_total" in resp.text


def test_request_too_large(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import main

    monkeypatch.setattr(main.settings, "max_request_bytes", 16)
    resp = client.post(
        "/generate", content=b"x" * 64, headers={"content-type": "application/json"}
    )
    assert resp.status_code == 413
