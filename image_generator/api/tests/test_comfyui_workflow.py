"""Pruebas del grafo de ComfyUI (sin red) y del decodificador de imágenes."""

from __future__ import annotations

import asyncio
import base64

import pytest

from app.config import Settings
from app.images import ImageTooLarge, decode_image
from app.providers.base import ProviderError
from app.providers.comfyui import ComfyUIProvider
from app.schemas import GenerateRequest


@pytest.fixture
def provider():
    instance = ComfyUIProvider(Settings(comfyui_url="http://127.0.0.1:8188"))
    yield instance
    asyncio.run(instance.aclose())


def test_txt2img_build(provider: ComfyUIProvider) -> None:
    request = GenerateRequest(
        prompt="gato",
        negative_prompt="perro",
        width=768,
        height=512,
        count=2,
        steps=25,
        guidance_scale=8.5,
    )
    workflow = provider._apply_parameters(provider._templates["txt2img"], request, 42)

    assert workflow["6"]["inputs"]["text"] == "gato"
    assert workflow["7"]["inputs"]["text"] == "perro"
    assert workflow["5"]["inputs"]["width"] == 768
    assert workflow["5"]["inputs"]["height"] == 512
    assert workflow["5"]["inputs"]["batch_size"] == 2
    assert workflow["3"]["inputs"]["seed"] == 42
    assert workflow["3"]["inputs"]["steps"] == 25
    assert workflow["3"]["inputs"]["cfg"] == 8.5
    assert workflow["3"]["inputs"]["denoise"] == 1.0


def test_img2img_denoise_from_strength(provider: ComfyUIProvider) -> None:
    request = GenerateRequest(prompt="x", image="aGVsbG8=", strength=0.4)
    workflow = provider._apply_parameters(provider._templates["img2img"], request, 7)

    assert workflow["11"]["class_type"] == "VAEEncode"
    assert workflow["3"]["inputs"]["denoise"] == 0.4


def test_img2img_default_denoise(provider: ComfyUIProvider) -> None:
    request = GenerateRequest(prompt="x", image="aGVsbG8=")
    workflow = provider._apply_parameters(provider._templates["img2img"], request, 7)

    assert workflow["3"]["inputs"]["denoise"] == 0.75
    # img2img no crea un latente vacío; parte de la imagen.
    assert "5" not in workflow


def test_inpaint_build(provider: ComfyUIProvider) -> None:
    request = GenerateRequest(prompt="x", image="aGVsbG8=", mask="aGVsbG8=")
    workflow = provider._apply_parameters(provider._templates["inpaint"], request, 7)

    assert workflow["11"]["class_type"] == "VAEEncodeForInpaint"
    assert workflow["3"]["inputs"]["denoise"] == 1.0


def test_decode_image_data_url() -> None:
    decoded = decode_image("data:image/jpeg;base64,aGVsbG8=")
    assert decoded.data == b"hello"
    assert decoded.mime_type == "image/jpeg"


def test_decode_image_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        decode_image("no-es-base64!!!")


def test_provider_maps_bad_image_to_400(provider: ComfyUIProvider) -> None:
    with pytest.raises(ProviderError) as exc_info:
        provider.decode_image_field("no-es-base64!!!")
    assert exc_info.value.status_code == 400


def test_decode_rejects_image_over_limit() -> None:
    encoded = base64.b64encode(b"x" * 100).decode()
    with pytest.raises(ImageTooLarge):
        decode_image(encoded, max_bytes=10)


def test_provider_rejects_oversized_image() -> None:
    instance = ComfyUIProvider(Settings(max_image_bytes=10))
    encoded = base64.b64encode(b"x" * 100).decode()
    with pytest.raises(ProviderError) as exc_info:
        instance.decode_image_field(encoded)
    assert exc_info.value.status_code == 413
    asyncio.run(instance.aclose())
