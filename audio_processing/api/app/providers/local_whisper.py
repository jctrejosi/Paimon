"""Proveedor local basado en faster-whisper (CTranslate2), pensado para CPU.

El modelo se carga una sola vez (de forma perezosa) y permanece en memoria. Como
`WhisperModel` no es seguro frente a usos concurrentes, serializamos las
transcripciones con un lock y las sacamos del event loop con `asyncio.to_thread`
(la inferencia es bloqueante y consume CPU).
"""

from __future__ import annotations

import asyncio
import io

from ..config import Settings
from ..schemas import TranscribeRequest
from .base import ProviderError, Segment, TranscriptionProvider, TranscriptResult


class LocalWhisperProvider(TranscriptionProvider):
    name = "local"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._model = None
        self._lock = asyncio.Lock()

    @classmethod
    def is_configured(cls, settings: Settings) -> bool:
        # El motor local no requiere credenciales.
        return True

    @classmethod
    def default_model(cls, settings: Settings) -> str | None:
        return settings.local_whisper_model

    def _load_model(self):
        # Import perezoso: evita depender de faster-whisper en pruebas que usan
        # un proveedor falso.
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:  # pragma: no cover - depende del entorno
            raise ProviderError(
                "faster-whisper no está instalado en este entorno.",
                provider=self.name,
                status_code=500,
            ) from exc

        return WhisperModel(
            self.settings.local_whisper_model,
            device=self.settings.local_whisper_device,
            compute_type=self.settings.local_whisper_compute_type,
            download_root=str(self.settings.whisper_model_dir),
        )

    def _transcribe_sync(self, request: TranscribeRequest) -> TranscriptResult:
        if self._model is None:
            self._model = self._load_model()

        try:
            segments_iter, info = self._model.transcribe(
                io.BytesIO(request.data),
                language=request.language,
                task="transcribe",
            )
            segments = [
                Segment(start=seg.start, end=seg.end, text=seg.text) for seg in segments_iter
            ]
        except Exception as exc:  # se reenvía como error de proveedor
            raise ProviderError(
                f"Fallo al transcribir el audio: {exc}", provider=self.name
            ) from exc

        text = "".join(seg.text for seg in segments).strip()
        return TranscriptResult(
            provider=self.name,
            model=request.model or self.settings.local_whisper_model,
            text=text,
            language=getattr(info, "language", None),
            language_probability=getattr(info, "language_probability", None),
            duration=getattr(info, "duration", None),
            segments=segments if request.verbose else [],
        )

    async def transcribe(self, request: TranscribeRequest) -> TranscriptResult:
        # Serializa el acceso al modelo y evita bloquear el event loop.
        async with self._lock:
            return await asyncio.to_thread(self._transcribe_sync, request)

    async def aclose(self) -> None:
        self._model = None
