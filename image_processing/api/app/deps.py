"""Dependencias compartidas por los routers: token y lectura de la subida."""

from __future__ import annotations

from typing import Annotated

from fastapi import Header, HTTPException, UploadFile

from .api_key_auth import require_valid_key
from .config import get_settings
from .images import (
    ALLOWED_EXTENSIONS,
    normalize_image,
    validate_image_upload,
    verify_image,
)

settings = get_settings()


def require_token(
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    """Exige una clave válida por `X-API-Key` o `Authorization: Bearer`."""
    require_valid_key(authorization, x_api_key)


async def read_image_upload(file: UploadFile) -> bytes:
    """Lee, valida, normaliza y verifica la imagen subida.

    Devuelve un PNG (RGB/RGBA) con la orientación EXIF ya aplicada y el primer
    fotograma si la entrada era animada. La validación es por contenido: si la
    extensión es desconocida pero los bytes decodifican como imagen, se acepta.
    """
    content = await file.read()
    extension = validate_image_upload(
        content, file.filename, max_mb=settings.image_processing_max_upload_mb
    )
    try:
        verify_image(content, max_pixels=settings.max_image_pixels)
    except HTTPException as exc:
        # Extensión desconocida + contenido que no es imagen ⇒ 415 (no 400):
        # es más útil decir "formato no soportado" que "imagen inválida".
        if exc.status_code == 400 and extension and extension not in ALLOWED_EXTENSIONS:
            accepted = ", ".join(sorted(ALLOWED_EXTENSIONS))
            raise HTTPException(
                status_code=415,
                detail=f"Extensión no soportada: {extension}. Aceptadas: {accepted}.",
            ) from exc
        raise
    return normalize_image(content)
