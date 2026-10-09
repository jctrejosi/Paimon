"""Paquete de audio: tipos, I/O y validación."""

from .io import decode_bytes, encode_wav, resample_samples
from .types import AudioClip, Segment
from .upload import ALLOWED_EXTENSIONS, extension_of, max_bytes

__all__ = [
    "ALLOWED_EXTENSIONS",
    "AudioClip",
    "Segment",
    "decode_bytes",
    "encode_wav",
    "extension_of",
    "max_bytes",
    "resample_samples",
]
