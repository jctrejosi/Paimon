"""Dependencias compartidas por los routers: token, subida y decodificación."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, UploadFile
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .audio import ALLOWED_EXTENSIONS, AudioClip, decode_bytes, extension_of, max_bytes
from .api_key_auth import require_valid_token
from .config import get_settings

settings = get_settings()

# Esquema Bearer declarado para que Swagger UI muestre el botón "Authorize".
bearer_scheme = HTTPBearer(auto_error=False)


def require_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    """Exige una clave válida por `X-API-Key` o `Authorization: Bearer`."""
    if x_api_key and x_api_key.strip():
        require_valid_token(x_api_key)
    else:
        require_valid_token(credentials.credentials if credentials else None)


def validate_audio(content: bytes, filename: str | None) -> None:
    """Valida el archivo subido; lanza HTTPException si no es aceptable."""
    if not content:
        raise HTTPException(status_code=400, detail="El archivo de audio está vacío.")
    limit = max_bytes(settings.audio_max_upload_mb)
    if len(content) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"El archivo supera el límite de {settings.audio_max_upload_mb} MB.",
        )
    ext = extension_of(filename)
    if ext and ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"Extensión no soportada: {ext}.")


async def read_upload(file: UploadFile) -> bytes:
    """Lee y valida el archivo subido."""
    content = await file.read()
    validate_audio(content, file.filename)
    return content


def decode_upload(content: bytes) -> AudioClip:
    """Decodifica el audio subido; convierte errores de decodificación en 400."""
    try:
        return decode_bytes(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
