"""Registro y ciclo de vida de los proveedores disponibles."""

from __future__ import annotations

from ..config import Settings
from .base import ProviderError, TranscriptionProvider
from .local_whisper import LocalWhisperProvider

# Orden = orden en el que se listan. Hoy solo el local; los proveedores cloud
# (OpenAI, Groq, ...) se añadirán aquí cuando se implementen.
PROVIDER_CLASSES: tuple[type[TranscriptionProvider], ...] = (LocalWhisperProvider,)

PROVIDER_NAMES: tuple[str, ...] = tuple(cls.name for cls in PROVIDER_CLASSES)
_BY_NAME = {cls.name: cls for cls in PROVIDER_CLASSES}


class ProviderManager:
    """Instancia proveedores bajo demanda y los reutiliza."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._instances: dict[str, TranscriptionProvider] = {}

    def get(self, name: str) -> TranscriptionProvider:
        cls = _BY_NAME.get(name)
        if cls is None:
            raise ProviderError(
                f"Proveedor desconocido: '{name}'. Disponibles: {', '.join(PROVIDER_NAMES)}.",
                provider=name,
                status_code=404,
            )
        if not cls.is_configured(self._settings):
            raise ProviderError(
                f"El proveedor '{name}' no está configurado.",
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
