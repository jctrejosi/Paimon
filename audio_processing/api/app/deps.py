"""Dependencias compartidas por los routers: token, subida y decodificación."""

from __future__ import annotations

from fastapi import Header, HTTPException, UploadFile

from .audio import ALLOWED_EXTENSIONS, AudioClip, decode_bytes, extension_of, max_bytes
from .config import get_settings

settings = get_settings()


def require_token(authorization: str | None = Header(default=None)) -> None:
    """Exige `Authorization: Bearer <token>` cuando hay token configurado."""
    expected = settings.audio_api_token
    if not expected:
        return
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or token != expected:
        raise HTTPException(status_code=401, detail="Token de API inválido o ausente.")


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
