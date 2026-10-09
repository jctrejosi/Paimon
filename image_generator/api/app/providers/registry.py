"""Registro y ciclo de vida de los proveedores disponibles."""

from __future__ import annotations

from ..config import Settings
from .base import ImageProvider, ProviderError
from .bfl import BFLProvider
from .comfyui import ComfyUIProvider
from .fal import FalProvider
from .openai_provider import OpenAIProvider
from .replicate import ReplicateProvider
from .stability import StabilityProvider

# Orden = orden en el que se listan. Todos salvo ComfyUI son externos/opcionales.
PROVIDER_CLASSES: tuple[type[ImageProvider], ...] = (
    ComfyUIProvider,
    OpenAIProvider,
    StabilityProvider,
    ReplicateProvider,
    FalProvider,
    BFLProvider,
)

PROVIDER_NAMES: tuple[str, ...] = tuple(cls.name for cls in PROVIDER_CLASSES)
_BY_NAME = {cls.name: cls for cls in PROVIDER_CLASSES}


class ProviderManager:
    """Instancia proveedores bajo demanda y los reutiliza."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._instances: dict[str, ImageProvider] = {}

    def get(self, name: str) -> ImageProvider:
        cls = _BY_NAME.get(name)
        if cls is None:
            raise ProviderError(
                f"Proveedor desconocido: '{name}'. Disponibles: {', '.join(PROVIDER_NAMES)}.",
                provider=name,
                status_code=404,
            )
        if not cls.is_configured(self._settings):
            raise ProviderError(
                f"El proveedor '{name}' no está configurado (faltan credenciales).",
                provider=name,
                status_code=400,
            )
        if name not in self._instances:
            self._instances[name] = cls(self._settings)
        return self._instances[name]

    def configured_names(self) -> list[str]:
        return [c.name for c in PROVIDER_CLASSES if c.is_configured(self._settings)]

    async def aclose(self) -> None:
        for provider in self._instances.values():
            await provider.aclose()
        self._instances.clear()
