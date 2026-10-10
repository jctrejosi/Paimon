"""Módulo `diarize`: ¿quién habla y cuándo?

Delega en un backend (ver `backends/`):

- `ecapa`: embeddings ECAPA (speechbrain) + clustering. **Sin credenciales.**
- `pyannote`: mejor calidad, pero sus modelos están *gated* → `HF_TOKEN`.

Con `backend="auto"` se usa pyannote si está instalado; si no, `ecapa`.
"""

from __future__ import annotations

from typing import Any

from app.audio.types import AudioClip
from app.preprocessing.base import (
    Processor,
    ProcessorError,
    ProcessorResult,
    ProcessorUnavailableError,
)

from .backends import BACKENDS
from .backends.base import DiarizationBackend
from .params import DiarizeParams


class DiarizeProcessor(Processor):
    name = "diarize"
    description = (
        "Diarización (quién habla): backend 'ecapa' (speechbrain, sin credenciales) "
        "o 'pyannote' (modelos gated: requiere HF_TOKEN)."
    )
    params_model = DiarizeParams
    # La disponibilidad depende del backend elegido: ver `backends/`.
    required_packages = ()

    def __init__(self, settings) -> None:
        super().__init__(settings)
        self._instances: dict[str, DiarizationBackend] = {}

    @classmethod
    def available(cls) -> bool:
        return any(backend.available() for backend in BACKENDS.values())

    def process(self, clip: AudioClip, params: Any) -> ProcessorResult:
        backend = self._get_backend(self._resolve(params.backend))
        result = backend.diarize(clip, params)
        return ProcessorResult(
            clips=[clip.to_mono()], segments=result.segments, metrics=result.metrics
        )

    @staticmethod
    def _resolve(name: str) -> str:
        """Resuelve `auto` al mejor backend instalado."""
        if name != "auto":
            return name
        for candidate in ("pyannote", "ecapa"):
            if BACKENDS[candidate].available():
                return candidate
        raise ProcessorError(
            "Ningún backend de diarización está disponible: instala 'speechbrain' y "
            "'scikit-learn' (backend 'ecapa', sin credenciales) o 'pyannote.audio' "
            "junto con HF_TOKEN (mejor calidad).",
            processor="diarize",
            status_code=503,
        )

    def _get_backend(self, name: str) -> DiarizationBackend:
        cls = BACKENDS.get(name)
        if cls is None:
            raise ProcessorError(
                f"Backend de diarización desconocido: '{name}'. "
                f"Disponibles: {', '.join(BACKENDS)}.",
                processor=self.name,
                status_code=400,
            )
        if not cls.available():
            raise ProcessorUnavailableError(f"{self.name}/{name}", cls.required_packages)
        if name not in self._instances:
            self._instances[name] = cls(self.settings)
        return self._instances[name]
