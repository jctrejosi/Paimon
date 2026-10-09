"""Configuración del servicio de transcripción de audio.

Todo se controla por variables de entorno (o un archivo `.env`). En esta primera
versión el único proveedor activo es el local (`faster-whisper`, CPU): funciona
sin credenciales ni red (salvo la descarga inicial del modelo, que se cachea).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["local"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Permite instanciar/tests sin que falten variables obligatorias.
        validate_default=True,
    )

    # --- Servicio ---------------------------------------------------------
    # Token opcional; si se define, todas las rutas (salvo /health) lo exigen
    # como `Authorization: Bearer <token>`.
    audio_api_token: str | None = None
    # Tamaño máximo de subida, en MB.
    audio_max_upload_mb: float = 25.0
    # Idioma usado cuando la petición no especifica uno. `auto` fuerza la
    # autodetección de Whisper.
    audio_default_language: str | None = "es"

    # Proveedor usado si la petición no especifica uno.
    audio_provider: ProviderName = "local"

    # --- Motor local (faster-whisper) ------------------------------------
    # Tamaño/nombre del modelo: tiny | base | small | medium | large-v3 | ...
    local_whisper_model: str = "base"
    local_whisper_device: str = "cpu"
    # int8 es lo más rápido en CPU; usar "float32" si se prioriza precisión.
    local_whisper_compute_type: str = "int8"
    # Directorio donde se cachean los pesos descargados.
    whisper_model_dir: Path = Path("models")

    def is_provider_configured(self, name: str) -> bool:
        """Indica si un proveedor tiene lo mínimo para operar."""
        # El motor local no requiere credenciales; los proveedores cloud se
        # añadirán aquí cuando se implementen.
        return name == "local"


@lru_cache
def get_settings() -> Settings:
    return Settings()
