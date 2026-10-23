"""Pruebas de la API usando un proveedor falso (sin red ni modelos)."""

from __future__ import annotations

import base64

from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "kokoro" in body["configured_providers"]


def test_list_providers(client: TestClient) -> None:
    resp = client.get("/providers")
    assert resp.status_code == 200
    body = resp.json()
    names = {p["name"] for p in body["providers"]}
    assert names == {"kokoro"}
    kokoro = next(p for p in body["providers"] if p["name"] == "kokoro")
    assert kokoro["configured"] is True
    assert kokoro["default"] is True
    assert kokoro["supports_cloning"] is False


def test_synthesize_wav(client: TestClient) -> None:
    resp = client.post("/synthesize", json={"text": "hola mundo"})
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "audio/wav"
    assert resp.headers["x-provider"] == "kokoro"
    assert resp.headers["x-voice-id"] == "ef_dora"
    assert resp.content.startswith(b"RIFF")


def test_synthesize_pcm(client: TestClient) -> None:
    resp = client.post("/synthesize", json={"text": "hola", "format": "pcm"})
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "audio/pcm"
    assert resp.content


def test_synthesize_missing_text(client: TestClient) -> None:
    resp = client.post("/synthesize", json={})
    assert resp.status_code == 422


def test_synthesize_unknown_provider(client: TestClient) -> None:
    resp = client.post("/synthesize", json={"text": "hola", "provider": "inventado"})
    assert resp.status_code == 404


def test_synthesize_stream(client: TestClient) -> None:
    resp = client.post("/synthesize/stream", json={"text": "hola mundo"})
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "audio/pcm"
    assert resp.headers["x-provider"] == "kokoro"
    assert resp.content


def test_synthesize_ws(client: TestClient) -> None:
    with client.websocket_connect("/synthesize/ws") as ws:
        ws.send_json({"type": "start", "voice_id": "ef_dora"})
        ws.send_json({"type": "text", "data": "hola "})
        ws.send_json({"type": "text", "data": "mundo"})
        ws.send_json({"type": "end"})

        messages = []
        while True:
            message = ws.receive_json()
            messages.append(message)
            if message["type"] in {"done", "error"}:
                break

    types = [m["type"] for m in messages]
    assert "audio" in types
    assert types[-1] == "done"
    audio = next(m for m in messages if m["type"] == "audio")
    assert base64.b64decode(audio["data"])
    assert audio["sample_rate"] == 24000


def test_voices_list(client: TestClient) -> None:
    resp = client.get("/voices")
    assert resp.status_code == 200
    voices = resp.json()["voices"]
    assert any(v["voice_id"] == "ef_dora" for v in voices)


def test_create_voice_not_supported(client: TestClient, wav: bytes) -> None:
    # Kokoro no clona: debe rechazar con 400 claro, sin tocar el audio.
    resp = client.post(
        "/voices",
        files={"file": ("ref.wav", wav, "audio/wav")},
        data={"name": "Mi voz"},
    )
    assert resp.status_code == 400
    assert "no soporta clonación" in resp.json()["detail"]


def test_delete_voice_not_found(client: TestClient) -> None:
    resp = client.delete("/voices/no-existe")
    assert resp.status_code == 404
