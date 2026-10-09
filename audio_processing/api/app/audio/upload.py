"""Validación de archivos de audio subidos."""

from __future__ import annotations

# Formatos que decodifica ffmpeg/PyAV. No es exhaustivo: si falta una extensión
# pero el contenido es decodificable, basta con añadirla aquí.
ALLOWED_EXTENSIONS = frozenset(
    {
        ".wav",
        ".mp3",
        ".m4a",
        ".mp4",
        ".aac",
        ".ogg",
        ".oga",
        ".opus",
        ".flac",
        ".webm",
    }
)


def extension_of(filename: str | None) -> str:
    """Devuelve la extensión (con punto, en minúsculas) o cadena vacía."""
    if not filename or "." not in filename:
        return ""
    _, _, ext = filename.rpartition(".")
    return f".{ext.lower()}" if ext else ""


def max_bytes(max_mb: float) -> int:
    return int(max_mb * 1024 * 1024)
