"""Pruebas de la API usando un proveedor falso (sin red ni credenciales)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _audio() -> dict:
    # El contenido no se decodifica: el proveedor es falso.
    return {"file": ("sample.wav", b"RIFF....WAVE", "audio/wav")}


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "local" in body["configured_providers"]


def test_list_providers(client: TestClient) -> None:
    resp = client.get("/providers")
    assert resp.status_code == 200
    body = resp.json()
    names = {p["name"] for p in body["providers"]}
    assert names == {"local"}
    local = next(p for p in body["providers"] if p["name"] == "local")
    assert local["configured"] is True
    assert local["default"] is True


def test_transcribe(client: TestClient) -> None:
    resp = client.post("/transcribe", files=_audio())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["text"] == "hola mundo"
    assert body["provider"] == "local"
    assert body["language"] == "es"


def test_transcribe_verbose(client: TestClient) -> None:
    resp = client.post("/transcribe", files=_audio(), data={"verbose": "true"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["segments"]


def test_transcribe_language_auto(client: TestClient) -> None:
    resp = client.post("/transcribe", files=_audio(), data={"language": "auto"})
    assert resp.status_code == 200, resp.text
    # El proveedor falso cae a 'es' cuando no hay idioma resuelto.
    assert resp.json()["language"] == "es"


def test_transcribe_empty_file(client: TestClient) -> None:
    resp = client.post("/transcribe", files={"file": ("vacio.wav", b"", "audio/wav")})
    assert resp.status_code == 400


def test_transcribe_missing_file(client: TestClient) -> None:
    resp = client.post("/transcribe")
    assert resp.status_code == 422


def test_transcribe_unsupported_extension(client: TestClient) -> None:
    resp = client.post("/transcribe", files={"file": ("notas.txt", b"nope", "text/plain")})
    assert resp.status_code == 415


def test_unknown_provider(client: TestClient) -> None:
    resp = client.post("/transcribe", files=_audio(), data={"provider": "inventado"})
    assert resp.status_code == 404


def test_openai_json(client: TestClient) -> None:
    resp = client.post("/v1/audio/transcriptions", files=_audio())
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"text": "hola mundo"}


def test_openai_text(client: TestClient) -> None:
    resp = client.post(
        "/v1/audio/transcriptions",
        files=_audio(),
        data={"response_format": "text"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.text == "hola mundo"


def test_openai_verbose_json(client: TestClient) -> None:
    resp = client.post(
        "/v1/audio/transcriptions",
        files=_audio(),
        data={"response_format": "verbose_json"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["text"] == "hola mundo"
    assert body["segments"]


def test_openai_invalid_format(client: TestClient) -> None:
    resp = client.post(
        "/v1/audio/transcriptions",
        files=_audio(),
        data={"response_format": "srt"},
    )
    assert resp.status_code == 400


def test_transcribe_with_preprocess(client: TestClient, wav: bytes) -> None:
    resp = client.post(
        "/transcribe",
        files={"file": ("a.wav", wav, "audio/wav")},
        data={"preprocess": "minimal"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["preprocess"] == "minimal"
    assert body["text"] == "hola mundo"


def test_transcribe_without_preprocess(client: TestClient) -> None:
    resp = client.post("/transcribe", files=_audio(), data={"preprocess": "none"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["preprocess"] is None


class _FakeWhisperModel:
    """Captura los kwargs con los que se llama a `transcribe`."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def transcribe(self, audio, **kwargs):
        self.calls.append(kwargs)
        info = type("Info", (), {"language": "es", "language_probability": 1.0, "duration": 1.0})()
        return [], info


def test_defaults_enable_vad_and_disable_condition() -> None:
    from app.config import Settings

    settings = Settings()
    assert settings.local_whisper_model == "small"
    assert settings.local_whisper_vad is True
    assert settings.local_whisper_condition_on_previous_text is False


def test_transcribe_accepts_decode_params(client: TestClient) -> None:
    resp = client.post(
        "/transcribe",
        files=_audio(),
        data={
            "vad": "false",
            "beam_size": "1",
            "condition_on_previous_text": "true",
            "initial_prompt": "Paimon",
        },
    )
    assert resp.status_code == 200, resp.text


def test_local_whisper_passes_decode_params() -> None:
    from app.config import Settings
    from app.providers.local_whisper import LocalWhisperProvider
    from app.schemas import TranscribeRequest

    settings = Settings(
        local_whisper_vad=True,
        local_whisper_beam_size=2,
        local_whisper_condition_on_previous_text=False,
        local_whisper_initial_prompt="contexto",
    )
    provider = LocalWhisperProvider(settings)
    model = _FakeWhisperModel()
    provider._models[settings.local_whisper_model] = model

    provider._transcribe_sync(TranscribeRequest(data=b"RIFF....WAVE", language="es"))
    assert model.calls[0]["vad_filter"] is True
    assert model.calls[0]["beam_size"] == 2
    assert model.calls[0]["condition_on_previous_text"] is False
    assert model.calls[0]["initial_prompt"] == "contexto"

    # Un valor explícito en la petición gana sobre el de la configuración.
    provider._transcribe_sync(
        TranscribeRequest(data=b"RIFF....WAVE", language="es", vad=False, beam_size=1)
    )
    assert model.calls[1]["vad_filter"] is False
    assert model.calls[1]["beam_size"] == 1
