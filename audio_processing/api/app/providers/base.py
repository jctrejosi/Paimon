"""Interfaz común a todos los proveedores de transcripción."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar

from ..config import Settings
from ..schemas import TranscribeRequest


class ProviderError(RuntimeError):
    """Error de un proveedor concreto (audio inválido, fallo del motor, etc.)."""

    def __init__(self, message: str, *, provider: str, status_code: int = 502):
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code


class ProviderNotConfiguredError(ProviderError):
    def __init__(self, provider: str):
        super().__init__(
            f"El proveedor '{provider}' no está configurado.",
            provider=provider,
            status_code=400,
        )


@dataclass
class Segment:
    """Fragmento transcrito con marcas de tiempo (segundos)."""

    start: float
    end: float
    text: str


@dataclass
class TranscriptResult:
    """Resultado de una transcripción, antes de serializarse."""

    provider: str
    model: str | None
    text: str
    language: str | None = None
    language_probability: float | None = None
    duration: float | None = None
    segments: list[Segment] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class TranscriptionProvider(ABC):
    """Contrato que implementa cada backend de transcripción.

    Un proveedor debe ser barato de construir; los recursos pesados (p. ej. el
    modelo) se cargan de forma perezosa y se liberan en `aclose`.
    """

    name: ClassVar[str]

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @classmethod
    @abstractmethod
    def is_configured(cls, settings: Settings) -> bool:
        """¿Tiene lo mínimo para intentar transcribir?"""

    @classmethod
    def default_model(cls, settings: Settings) -> str | None:
        """Modelo por defecto del proveedor (para informar en /providers)."""
        return None

    @abstractmethod
    async def transcribe(self, request: TranscribeRequest) -> TranscriptResult:
        """Transcribe un audio y devuelve el texto y sus metadatos."""

    async def aclose(self) -> None:
        """Libera recursos. Por defecto no hace nada."""
