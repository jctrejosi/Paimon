"""Dependencias compartidas por los routers: token y validación de subidas."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException
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
) -> None:
    """Exige una clave válida (`API_KEYS` o el token heredado del servicio)."""
    if not auth_required():
        return
    if credentials is None or not is_valid_token(credentials.credentials):
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
