"""Persistencia simple de imágenes generadas en disco."""

from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime
from pathlib import Path

_EXT_BY_MIME = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}


def extension_for(mime_type: str) -> str:
    return _EXT_BY_MIME.get(mime_type, "png")


class ImageStorage:
    """Guarda imágenes en `output_dir` con nombres únicos y seguros."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save(self, data: bytes, mime_type: str, *, prefix: str = "img") -> str:
        """Escribe `data` y devuelve el nombre de archivo relativo."""
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        token = secrets.token_hex(4)
        ext = extension_for(mime_type)
        filename = f"{prefix}-{stamp}-{token}.{ext}"
        path = self.output_dir / filename
        # Escritura atómica: evita servir archivos a medio escribir.
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        return filename
