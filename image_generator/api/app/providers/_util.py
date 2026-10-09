"""Utilidades compartidas por los proveedores externos."""

from __future__ import annotations

import base64
import mimetypes
from urllib.parse import urlparse

import httpx

from .base import ProviderError, RawImage


def raw_image_from_b64(data: str, *, mime_type: str = "image/png", **kwargs) -> RawImage:
    """Decodifica un base64 (con o sin prefijo data:) a un RawImage."""
    if data.startswith("data:"):
        header, _, data = data.partition(",")
        mime_type = header[5:].split(";")[0] or mime_type
    return RawImage(data=base64.b64decode(data), mime_type=mime_type, **kwargs)


def guess_mime(url: str, default: str = "image/png") -> str:
    path = urlparse(url).path
    return mimetypes.guess_type(path)[0] or default


async def fetch_url(client: httpx.AsyncClient, url: str, *, provider: str) -> RawImage:
    """Descarga una imagen desde una URL y la devuelve como RawImage."""
    try:
        resp = await client.get(url)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise ProviderError(
            f"No se pudo descargar la imagen generada: {exc}", provider=provider
        ) from exc
    mime = resp.headers.get("content-type", "").split(";")[0].strip()
    if not mime.startswith("image/"):
        mime = guess_mime(url)
    return RawImage(data=resp.content, mime_type=mime)


def closest_aspect_ratio(width: int, height: int, supported: dict[str, float]) -> str:
    """Devuelve la clave cuyo ratio sea más cercano al de width x height."""
    target = width / height if height else 1.0
    return min(supported, key=lambda key: abs(supported[key] - target))
