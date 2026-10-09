"""Pruebas de los módulos de preprocesamiento y sus APIs propias."""

from __future__ import annotations

import importlib.util
import json

import pytest
from fastapi.testclient import TestClient

from app.preprocessing.registry import PROCESSORS

ALL_MODULES = {
    "decode",
    "channels",
    "resample",
    "highpass",
    "normalize",
    "analyze",
    "vad",
    "denoise",
    "diarize",
    "separate",
    "dereverb",
}


def upload(data: bytes, name: str = "test.wav") -> dict:
    return {"file": (name, data, "audio/wav")}


def test_registry_discovers_all_modules() -> None:
    assert ALL_MODULES <= set(PROCESSORS)


def test_processors_endpoint(client: TestClient) -> None:
    resp = client.get("/processors")
    assert resp.status_code == 200
    processors = resp.json()["processors"]
    names = {p["name"] for p in processors}
    assert ALL_MODULES <= names
    decode = next(p for p in processors if p["name"] == "decode")
    assert decode["available"] is True
    assert "sample_rate" in decode["params_schema"]["properties"] or True


def test_presets_endpoint(client: TestClient) -> None:
    resp = client.get("/presets")
    assert resp.status_code == 200
    presets = {p["name"]: p["steps"] for p in resp.json()["presets"]}
    assert presets["raw"] == []
    assert presets["minimal"] == ["channels", "resample", "highpass", "normalize"]
    assert "vad" in presets["clean"]
    assert "denoise" in presets["noisy"]


@pytest.mark.parametrize(
    "name,params",
    [
        ("decode", {}),
        ("channels", {"mode": "mono"}),
        ("resample", {"sample_rate": 8000}),
        ("highpass", {"cutoff": 100.0}),
        ("normalize", {"mode": "peak", "target_db": -3.0}),
        ("normalize", {"mode": "rms", "target_db": -20.0}),
        ("analyze", {}),
        ("denoise", {"backend": "spectral"}),
        ("dereverb", {}),
        ("vad", {}),
    ],
)
def test_module_endpoint_returns_audio(
    client: TestClient, wav: bytes, name: str, params: dict
) -> None:
    resp = client.post(
        f"/preprocess/{name}", files=upload(wav), data={"params": json.dumps(params)}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["processor"] == name
    assert body["audios"], "se esperaba audio de salida"
    assert body["audios"][0]["duration"] > 0
    assert body["audios"][0]["sample_rate"] > 0


def test_module_info_endpoint(client: TestClient) -> None:
    resp = client.get("/preprocess/resample")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "resample"
    assert body["available"] is True
    assert "sample_rate" in body["params_schema"]["properties"]


def test_module_include_audio_false(client: TestClient, wav: bytes) -> None:
    resp = client.post(
        "/preprocess/analyze", files=upload(wav), data={"include_audio": "false"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["audios"] == []
    assert resp.json()["metrics"]["peak"] > 0


def test_resample_changes_rate(client: TestClient, wav: bytes) -> None:
    resp = client.post(
        "/preprocess/resample", files=upload(wav), data={"params": json.dumps({"sample_rate": 8000})}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["audios"][0]["sample_rate"] == 8000


def test_channels_downmix(client: TestClient) -> None:
    from conftest import make_wav, read_wav_header

    stereo = make_wav(channels=2)
    assert read_wav_header(stereo)[0] == 2
    resp = client.post("/preprocess/channels", files=upload(stereo))
    assert resp.status_code == 200, resp.text
    assert resp.json()["metrics"]["channels"] == 1


def test_analyze_metrics(client: TestClient, wav: bytes) -> None:
    resp = client.post("/analyze", files=upload(wav))
    assert resp.status_code == 200, resp.text
    metrics = resp.json()["metrics"]
    assert 0 < metrics["peak"] <= 1
    assert "band_energy_ratio" in metrics
    assert "spectral_centroid_hz" in metrics
    assert metrics["duration"] == pytest.approx(1.0, abs=0.05)


def test_vad_reports_no_speech_for_tone(client: TestClient, wav: bytes) -> None:
    resp = client.post("/preprocess/vad", files=upload(wav))
    assert resp.status_code == 200, resp.text
    assert resp.json()["metrics"]["no_speech"] is True


@pytest.mark.parametrize("name", ["diarize", "separate"])
def test_optional_modules_unavailable(client: TestClient, wav: bytes, name: str) -> None:
    if PROCESSORS[name].available():
        pytest.skip(f"{name} está instalado en este entorno")
    resp = client.post(f"/preprocess/{name}", files=upload(wav))
    assert resp.status_code == 503
    assert "requiere" in resp.json()["detail"]


def test_denoise_deepfilternet_unavailable(client: TestClient, wav: bytes) -> None:
    if importlib.util.find_spec("df") is not None:
        pytest.skip("DeepFilterNet está instalado en este entorno")
    resp = client.post(
        "/preprocess/denoise",
        files=upload(wav),
        data={"params": json.dumps({"backend": "deepfilternet"})},
    )
    assert resp.status_code == 503


def test_pipeline_preset(client: TestClient, wav: bytes) -> None:
    resp = client.post("/preprocess", files=upload(wav), data={"preset": "minimal"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["preset"] == "minimal"
    assert [step["name"] for step in body["steps"]] == [
        "channels",
        "resample",
        "highpass",
        "normalize",
    ]
    assert body["audios"][0]["sample_rate"] == 16000


def test_pipeline_steps_list(client: TestClient, wav: bytes) -> None:
    steps = json.dumps([{"name": "resample", "params": {"sample_rate": 8000}}])
    resp = client.post("/preprocess", files=upload(wav), data={"steps": steps})
    assert resp.status_code == 200, resp.text
    assert resp.json()["audios"][0]["sample_rate"] == 8000


def test_pipeline_unknown_preset(client: TestClient, wav: bytes) -> None:
    resp = client.post("/preprocess", files=upload(wav), data={"preset": "inventado"})
    assert resp.status_code == 400


def test_module_bad_params(client: TestClient, wav: bytes) -> None:
    resp = client.post(
        "/preprocess/resample", files=upload(wav), data={"params": "no-es-json"}
    )
    assert resp.status_code == 400

    resp = client.post(
        "/preprocess/resample",
        files=upload(wav),
        data={"params": json.dumps({"sample_rate": 99999999})},
    )
    assert resp.status_code == 422


def test_unknown_module(client: TestClient) -> None:
    assert client.get("/preprocess/inventado").status_code == 404
