"""Backends de diarización disponibles.

- `ecapa`: embeddings ECAPA (speechbrain) + clustering aglomerativo. **Sin credenciales.**
- `pyannote`: pipeline de pyannote.audio. Mejor calidad, pero sus modelos están
  *gated* en Hugging Face: requieren aceptar condiciones y un `HF_TOKEN`.
"""

from .base import DiarizationBackend, DiarizationResult
from .ecapa_backend import EcapaBackend
from .pyannote_backend import PyannoteBackend

BACKENDS: dict[str, type[DiarizationBackend]] = {
    cls.name: cls for cls in (PyannoteBackend, EcapaBackend)
}

__all__ = ["BACKENDS", "DiarizationBackend", "DiarizationResult"]
