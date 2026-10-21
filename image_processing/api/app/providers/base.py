"""Interfaz común a los proveedores de quita-fondo."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from ..config import Settings


class ProviderError(RuntimeError):
    """Error de un proveedor concreto (modelo, decodificación, etc.)."""

    def __init__(self, message: str, *, provider: str, status_code: int = 502):
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code


@dataclass
class RemoveBgRequest:
    """Petición ya resuelta por la API, lista para el proveedor."""

    data: bytes
    model: str | None = None
    alpha_matting: bool | None = None
    alpha_matting_foreground_threshold: int = 240
    alpha_matting_background_threshold: int = 10
    alpha_matting_erode_size: int = 10
    # `None` = fondo transparente; si no, color `#RRGGBB`.
    background: str | None = None
    output_format: str = "png"
    post_process_mask: bool | None = None
    provider: str = "local"


@dataclass
class RemoveBgResult:
    provider: str
    model: str
    data: bytes
    mime_type: str = "image/png"
    width: int = 0
    height: int = 0


class RemoveBgProvider(ABC):
    """Contrato que implementa cada backend de quita-fondo."""

    name: ClassVar[str]

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @classmethod
    @abstractmethod
    def is_configured(cls, settings: Settings) -> bool:
        """¿Tiene lo mínimo para intentar procesar?"""

    @classmethod
    def default_model(cls, settings: Settings) -> str | None:
        """Modelo por defecto (para informar en /providers)."""
        return None

    @abstractmethod
    async def remove_background(self, request: RemoveBgRequest) -> RemoveBgResult:
        """Devuelve la imagen con el fondo eliminado."""

    async def aclose(self) -> None:
        """Libera recursos. Por defecto no hace nada."""
