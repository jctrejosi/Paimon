"""Dependencias compartidas por los routers: token y validación de subidas."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .api_key_auth import auth_required, is_valid_token
from .config import get_settings

settings = get_settings()

# Esquema Bearer declarado para que Swagger UI muestre el botón "Authorize".
bearer_scheme = HTTPBearer(auto_error=False)

# Extensiones de audio aceptadas para crear una voz clonada.
ALLOWED_AUDIO_EXTENSIONS = frozenset({".wav", ".mp3", ".m4a", ".ogg", ".opus", ".flac"})


def require_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    """Exige una clave válida por `X-API-Key` o `Authorization: Bearer`.

    El gateway inyecta `X-API-Key`; Swagger UI usa `Authorization: Bearer`.
    """
    if not auth_required():
        return
    token = (x_api_key or "").strip()
    if not token and credentials is not None:
        token = credentials.credentials or ""
    if not is_valid_token(token):
        raise HTTPException(status_code=401, detail="Token de API inválido o ausente.")


def validate_audio_upload(content: bytes, filename: str | None) -> None:
    """Valida un audio de referencia subido; lanza HTTPException si no vale."""
    if not content:
        raise HTTPException(status_code=400, detail="El archivo de audio está vacío.")
    limit = int(settings.tts_max_upload_mb * 1024 * 1024)
    if len(content) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"El archivo supera el límite de {settings.tts_max_upload_mb} MB.",
        )
    if filename:
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext and ext not in ALLOWED_AUDIO_EXTENSIONS:
            raise HTTPException(status_code=415, detail=f"Extensión no soportada: {ext}.")
