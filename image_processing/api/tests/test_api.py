"""Pruebas de la API usando un proveedor falso (sin rembg ni red)."""

from __future__ import annotations

import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, features


def _image(png: bytes) -> dict:
    return {"file": ("sample.png", png, "image/png")}


def _sample(fmt: str, *, size: tuple[int, int] = (64, 64)) -> bytes:
    """Círculo sobre fondo claro codificado en `fmt` (RGB)."""
    image = Image.new("RGB", size, (240, 240, 240))
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 8, size[0] - 8, size[1] - 8), fill=(200, 30, 30))
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "local" in body["configured_providers"]


def test_list_providers(client: TestClient) -> None:
    from app.config import get_settings

    resp = client.get("/providers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["default_provider"] == "local"
    local = next(p for p in body["providers"] if p["name"] == "local")
    assert local["configured"] is True
    assert local["default"] is True
    assert local["model"] == get_settings().local_rembg_model


def test_list_models(client: TestClient) -> None:
    from app.config import get_settings

    resp = client.get("/models")
    assert resp.status_code == 200
    body = resp.json()
    assert "u2net" in body["models"]
    assert body["default"] == get_settings().local_rembg_model


def test_remove_bg_returns_png(client: TestClient, png: bytes) -> None:
    resp = client.post("/remove-bg", files=_image(png))
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "image/png"
    assert resp.headers["x-provider"] == "local"
    assert resp.content.startswith(b"\x89PNG")
    # La imagen devuelta tiene canal alfa.
    with Image.open(io.BytesIO(resp.content)) as image:
        assert image.mode in {"RGBA", "LA"}


def test_remove_bg_json(client: TestClient, png: bytes) -> None:
    resp = client.post("/remove-bg", files=_image(png), data={"response_format": "json"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider"] == "local"
    assert body["mime_type"] == "image/png"
    assert body["width"] == 64 and body["height"] == 64
    assert base64.b64decode(body["image_base64"]).startswith(b"\x89PNG")


def test_remove_bg_webp(client: TestClient, png: bytes) -> None:
    resp = client.post("/remove-bg", files=_image(png), data={"output_format": "webp"})
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "image/webp"
    assert resp.content[:4] == b"RIFF"


def test_remove_bg_with_background_color(client: TestClient, png: bytes) -> None:
    resp = client.post("/remove-bg", files=_image(png), data={"background": "#00ff00"})
    assert resp.status_code == 200, resp.text
    with Image.open(io.BytesIO(resp.content)) as image:
        rgba = image.convert("RGBA")
        # La esquina era fondo: debe quedar del color pedido y opaca.
        assert rgba.getpixel((0, 0)) == (0, 255, 0, 255)


def test_remove_bg_accepts_alpha_matting(client: TestClient, png: bytes) -> None:
    resp = client.post(
        "/remove-bg",
        files=_image(png),
        data={
            "alpha_matting": "true",
            "alpha_matting_foreground_threshold": "200",
            "alpha_matting_background_threshold": "20",
            "alpha_matting_erode_size": "5",
        },
    )
    assert resp.status_code == 200, resp.text


def test_remove_bg_empty_file(client: TestClient) -> None:
    resp = client.post("/remove-bg", files={"file": ("vacia.png", b"", "image/png")})
    assert resp.status_code == 400


def test_remove_bg_missing_file(client: TestClient) -> None:
    resp = client.post("/remove-bg")
    assert resp.status_code == 422


def test_remove_bg_unsupported_extension(client: TestClient) -> None:
    resp = client.post(
        "/remove-bg", files={"file": ("notas.txt", b"nope", "text/plain")}
    )
    assert resp.status_code == 415


@pytest.mark.parametrize(
    ("fmt", "ext", "mime"),
    [
        ("JPEG", "jpg", "image/jpeg"),
        ("JPEG", "jpeg", "image/jpeg"),
        ("WEBP", "webp", "image/webp"),
        ("BMP", "bmp", "image/bmp"),
        ("TIFF", "tiff", "image/tiff"),
        ("GIF", "gif", "image/gif"),
        ("PPM", "ppm", "image/x-portable-pixmap"),
    ],
)
def test_remove_bg_accepts_common_formats(
    client: TestClient, fmt: str, ext: str, mime: str
) -> None:
    resp = client.post("/remove-bg", files={"file": (f"foto.{ext}", _sample(fmt), mime)})
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "image/png"
    with Image.open(io.BytesIO(resp.content)) as image:
        assert image.size == (64, 64)


@pytest.mark.skipif(not features.check("avif"), reason="Pillow sin soporte AVIF")
def test_remove_bg_accepts_avif(client: TestClient) -> None:
    resp = client.post(
        "/remove-bg", files={"file": ("foto.avif", _sample("AVIF"), "image/avif")}
    )
    assert resp.status_code == 200, resp.text
    with Image.open(io.BytesIO(resp.content)) as image:
        assert image.size == (64, 64)


def test_remove_bg_accepts_heic(client: TestClient) -> None:
    from app.images import HEIF_SUPPORTED

    if not HEIF_SUPPORTED:
        pytest.skip("pillow-heif no instalado")
    resp = client.post(
        "/remove-bg", files={"file": ("foto.heic", _sample("HEIF"), "image/heic")}
    )
    assert resp.status_code == 200, resp.text
    with Image.open(io.BytesIO(resp.content)) as image:
        assert image.size == (64, 64)


def test_remove_bg_accepts_filename_without_extension(client: TestClient) -> None:
    resp = client.post(
        "/remove-bg",
        files={"file": ("blob", _sample("PNG"), "application/octet-stream")},
    )
    assert resp.status_code == 200, resp.text


def test_remove_bg_accepts_unknown_extension_with_valid_content(
    client: TestClient,
) -> None:
    resp = client.post(
        "/remove-bg",
        files={"file": ("foto.weird", _sample("PNG"), "application/octet-stream")},
    )
    assert resp.status_code == 200, resp.text


def test_remove_bg_applies_exif_orientation(client: TestClient) -> None:
    # 32x64 con orientación 6: al mostrarla debe verse 64x32.
    image = Image.new("RGB", (32, 64), (240, 240, 240))
    ImageDraw.Draw(image).rectangle((0, 0, 31, 31), fill=(200, 30, 30))
    exif = Image.Exif()
    exif[0x0112] = 6
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif)

    resp = client.post(
        "/remove-bg", files={"file": ("movil.jpg", buffer.getvalue(), "image/jpeg")}
    )
    assert resp.status_code == 200, resp.text
    with Image.open(io.BytesIO(resp.content)) as output:
        assert output.size == (64, 32)


def test_remove_bg_animated_gif_uses_first_frame(client: TestClient) -> None:
    frames = [_sample("PNG")]
    image = Image.open(io.BytesIO(frames[0])).convert("P")
    buffer = io.BytesIO()
    image.save(buffer, format="GIF", save_all=True, duration=100)

    resp = client.post(
        "/remove-bg", files={"file": ("animado.gif", buffer.getvalue(), "image/gif")}
    )
    assert resp.status_code == 200, resp.text


def test_remove_bg_invalid_image(client: TestClient) -> None:
    resp = client.post(
        "/remove-bg", files={"file": ("falsa.png", b"no soy una imagen", "image/png")}
    )
    assert resp.status_code == 400


def test_remove_bg_invalid_background(client: TestClient, png: bytes) -> None:
    resp = client.post("/remove-bg", files=_image(png), data={"background": "azul"})
    assert resp.status_code == 400


def test_remove_bg_unknown_provider(client: TestClient, png: bytes) -> None:
    resp = client.post("/remove-bg", files=_image(png), data={"provider": "nube"})
    assert resp.status_code == 404


def test_local_provider_rejects_unknown_model() -> None:
    from app.config import Settings
    from app.providers.base import ProviderError, RemoveBgRequest
    from app.providers.local_rembg import LocalRembgProvider

    provider = LocalRembgProvider(Settings())
    with pytest.raises(ProviderError) as excinfo:
        provider._remove_sync(RemoveBgRequest(data=b"x", model="no-existe"))
    assert excinfo.value.status_code == 400
    assert "Modelo inválido" in str(excinfo.value)
