"""Interfaz común a todos los proveedores de generación de imágenes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar

from ..config import Settings
from ..schemas import GenerateRequest


class ProviderError(RuntimeError):
    """Error de un proveedor concreto (red, credenciales, validación, etc.)."""

    def __init__(self, message: str, *, provider: str, status_code: int = 502):
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code


class ProviderNotConfiguredError(ProviderError):
    def __init__(self, provider: str):
        super().__init__(
            f"El proveedor '{provider}' no está configurado (faltan credenciales).",
            provider=provider,
            status_code=400,
        )


@dataclass
class RawImage:
    """Imagen generada, en memoria, antes de persistirse o serializarse."""

    data: bytes
    mime_type: str = "image/png"
    seed: int | None = None
    revised_prompt: str | None = None


@dataclass
class ProviderResult:
    provider: str
    model: str | None
    images: list[RawImage]
    metadata: dict = field(default_factory=dict)


class ImageProvider(ABC):
    """Contrato que implementa cada backend de generación.

    Un proveedor debe ser barato de construir y mantener recursos (p. ej. un
    cliente HTTP) que se liberan en `aclose`.
    """

    name: ClassVar[str]

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @classmethod
    @abstractmethod
    def is_configured(cls, settings: Settings) -> bool:
        """¿Tiene credenciales/URL suficientes para intentar generar?"""

    @classmethod
    def default_model(cls, settings: Settings) -> str | None:
        """Modelo por defecto del proveedor (para informar en /providers)."""
        return None

    @abstractmethod
    async def generate(self, request: GenerateRequest) -> ProviderResult:
        """Genera una o varias imágenes y devuelve los bytes."""

    async def aclose(self) -> None:
        """Libera recursos. Por defecto no hace nada."""
