"""Validación y utilidades de imagen (sin cargar el motor de fondo)."""

from __future__ import annotations

import io

from fastapi import HTTPException
from PIL import Image, ImageOps

# Extensiones conocidas. La verificación real es decodificar con Pillow: una
# extensión desconocida se acepta si el contenido es una imagen válida, así que
# esto solo sirve para dar un 415 claro a archivos que no son imágenes.
ALLOWED_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".jpe",
    ".jfif",
    ".webp",
    ".bmp",
    ".dib",
    ".tif",
    ".tiff",
    ".gif",
    ".avif",
    ".heic",
    ".heif",
    ".ico",
    ".ppm",
    ".pgm",
    ".pbm",
    ".pnm",
    ".tga",
}


def _register_optional_formats() -> bool:
    """Activa HEIC/HEIF si `pillow-heif` está instalado (fotos de iPhone).

    Devuelve `True` si el soporte quedó registrado. La dependencia es opcional:
    sin ella la API sigue funcionando con el resto de formatos.
    """
    try:
        from pillow_heif import register_heif_opener
    except ImportError:  # pragma: no cover - depende del entorno
        return False
    register_heif_opener()
    return True


HEIF_SUPPORTED = _register_optional_formats()


def extension_of(filename: str | None) -> str:
    """Extensión en minúsculas (con punto) o cadena vacía."""
    if not filename:
        return ""
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    index = name.rfind(".")
    return name[index:].lower() if index >= 0 else ""


def max_bytes(megabytes: float) -> int:
    return int(megabytes * 1024 * 1024)


def validate_image_upload(content: bytes, filename: str | None, *, max_mb: float) -> str:
    """Valida tamaño y archivo vacío; devuelve la extensión del nombre.

    La extensión no bloquea la subida: un nombre desconocido (o sin extensión)
    se acepta si el contenido decodifica como imagen.
    """
    if not content:
        raise HTTPException(status_code=400, detail="El archivo de imagen está vacío.")
    limit = max_bytes(max_mb)
    if len(content) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"La imagen supera el límite de {max_mb} MB.",
        )
    return extension_of(filename)


def verify_image(content: bytes, *, max_pixels: int) -> None:
    """Comprueba que los bytes son una imagen real y que no es desmesurada."""
    try:
        with Image.open(io.BytesIO(content)) as img:
            width, height = img.size
            if width * height > max_pixels:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"Imagen demasiado grande ({width}x{height}); "
                        f"máximo {max_pixels} píxeles."
                    ),
                )
            img.verify()
    except HTTPException:
        raise
    except Exception as exc:  # Pillow lanza tipos muy variados
        raise HTTPException(
            status_code=400, detail=f"El archivo no es una imagen válida: {exc}"
        ) from exc


def normalize_image(content: bytes) -> bytes:
    """Decodifica cualquier formato soportado y lo reencodea como PNG.

    Unifica la entrada del motor: primer fotograma (GIF/WebP animados),
    orientación EXIF aplicada y modo RGB/RGBA. Así `rembg` siempre recibe un
    PNG que sabe abrir, venga la imagen de un JPEG de cámara, un HEIC de iPhone,
    un AVIF, un TIFF o un GIF animado.
    """
    try:
        with Image.open(io.BytesIO(content)) as img:
            img.seek(0)  # animaciones: solo el primer fotograma
            img.load()
            normalized = ImageOps.exif_transpose(img)
            has_alpha = normalized.mode in {"RGBA", "LA", "PA"} or (
                "transparency" in normalized.info
            )
            normalized = normalized.convert("RGBA" if has_alpha else "RGB")
            buffer = io.BytesIO()
            normalized.save(buffer, format="PNG")
            return buffer.getvalue()
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"No se pudo decodificar la imagen: {exc}",
        ) from exc


def parse_background(value: str | None) -> str | None:
    """Normaliza `transparent`/vacío a `None` y un color a `#RRGGBB`.

    Acepta `#RGB`, `#RRGGBB` y sus variantes sin `#`.
    """
    if not value:
        return None
    raw = value.strip().lower()
    if raw in {"", "transparent", "none", "alpha"}:
        return None
    raw = raw.removeprefix("#")
    if len(raw) == 3 and all(c in "0123456789abcdef" for c in raw):
        raw = "".join(c * 2 for c in raw)
    if len(raw) != 6 or any(c not in "0123456789abcdef" for c in raw):
        raise HTTPException(
            status_code=400,
            detail=f"Color de fondo inválido: '{value}'. Usa '#RRGGBB' o 'transparent'.",
        )
    return f"#{raw}"
