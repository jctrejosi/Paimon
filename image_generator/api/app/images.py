"""Decodificación de imágenes de entrada (image-to-image / edición)."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass

_DEFAULT_MIME = "image/png"


class ImageTooLarge(ValueError):
    """La imagen de entrada supera el límite configurado."""


@dataclass
class DecodedImage:
    data: bytes
    mime_type: str = _DEFAULT_MIME


def decode_image(
    value: str, default_mime: str = _DEFAULT_MIME, *, max_bytes: int | None = None
) -> DecodedImage:
    """Acepta un data URL (`data:image/png;base64,...`) o base64 en crudo.

    Si se indica `max_bytes`, rechaza el payload por su longitud *antes* de
    decodificarlo (base64 ocupa ~4/3), evitando asignar memoria de más.
    """
    if max_bytes is not None:
        max_chars = (max_bytes * 4) // 3 + 1024
        if len(value) > max_chars:
            raise ImageTooLarge(f"la imagen supera el límite de {max_bytes} bytes.")

    mime = default_mime
    payload = value
    if value.startswith("data:"):
        header, sep, payload = value.partition(",")
        if not sep:
            raise ValueError("data URL mal formado.")
        mime = header[5:].split(";")[0] or default_mime
    try:
        data = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("no es base64 válido ni un data URL.") from exc
    if not data:
        raise ValueError("la imagen decodificada está vacía.")
    if max_bytes is not None and len(data) > max_bytes:
        raise ImageTooLarge(f"la imagen supera el límite de {max_bytes} bytes.")
    return DecodedImage(data=data, mime_type=mime)
