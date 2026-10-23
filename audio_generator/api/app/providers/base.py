"""Interfaz común a todos los proveedores de síntesis de voz."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import ClassVar

from ..config import Settings
from ..schemas import SynthesizeRequest, Voice


class TTSProviderError(RuntimeError):
    """Error de un proveedor concreto (texto inválido, fallo del motor, etc.)."""

    def __init__(self, message: str, *, provider: str, status_code: int = 502):
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code


@dataclass
class SynthesisResult:
    """Audio completo generado, antes de serializarse."""

    provider: str
    voice_id: str
    audio: bytes
    sample_rate: int
    duration_sec: float
    format: str = "wav"


@dataclass
class AudioChunk:
    """Fragmento de audio PCM (int16, mono) para streaming."""

    data: bytes
    index: int
    final: bool
    sample_rate: int


class TTSSynthesizer(ABC):
    """Contrato que implementa cada backend de síntesis.

    Un proveedor debe ser barato de construir; los recursos pesados (el modelo)
    se cargan de forma perezosa y se liberan en `aclose`.
    """

    name: ClassVar[str]
    supports_cloning: ClassVar[bool] = False

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @classmethod
    @abstractmethod
    def is_configured(cls, settings: Settings) -> bool:
        """¿Tiene lo mínimo para intentar sintetizar?"""

    @classmethod
    def default_model(cls, settings: Settings) -> str | None:
        """Modelo por defecto del proveedor (para informar en /providers)."""
        return None

    @abstractmethod
    async def synthesize(self, request: SynthesizeRequest) -> SynthesisResult:
        """Sintetiza el texto completo y devuelve el audio."""

    @abstractmethod
    async def synthesize_stream(self, request: SynthesizeRequest) -> AsyncIterator[AudioChunk]:
        """Sintetiza y va devolviendo el audio por fragmentos."""
        # `if False` solo marca el método como generador asíncrono (para el
        # tipado); las subclases lo implementan de verdad.
        if False:  # pragma: no cover
            yield AudioChunk(data=b"", index=0, final=True, sample_rate=0)

    @abstractmethod
    async def list_voices(self) -> list[Voice]:
        """Lista las voces disponibles del proveedor."""

    async def create_voice(self, audio: bytes, name: str, prompt_text: str | None) -> Voice:
        """Crea una voz clonada. Solo disponible si `supports_cloning`."""
        raise TTSProviderError(
            f"El proveedor '{self.name}' no soporta clonación de voz.",
            provider=self.name,
            status_code=400,
        )

    async def delete_voice(self, voice_id: str) -> None:
        """Elimina una voz clonada. Solo disponible si `supports_cloning`."""
        raise TTSProviderError(
            f"El proveedor '{self.name}' no soporta clonación de voz.",
            provider=self.name,
            status_code=400,
        )

    async def aclose(self) -> None:
        """Libera recursos. Por defecto no hace nada."""
