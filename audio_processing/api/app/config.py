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
    # tiny | base | small | medium | large-v3 | large-v3-turbo | ...
    # `small` es el mejor punto calidad/latencia medido en eval/ (ver README).
    local_whisper_model: str = "small"
    local_whisper_device: str = "cpu"
    # int8 es lo más rápido en CPU; usar "float32" si se prioriza precisión.
    local_whisper_compute_type: str = "int8"
    # Directorio donde se cachean los pesos descargados.
    whisper_model_dir: Path = Path("models")

    # --- Parámetros de decodificación (faster-whisper) --------------------
    # VAD (Silero) para recortar silencio: reduce alucinaciones y cómputo.
    local_whisper_vad: bool = True
    # Ancho de búsqueda del decodificador (5 = por defecto; 1 = más rápido).
    local_whisper_beam_size: int = 5
    # False evita bucles de repetición entre segmentos (mejor en notas cortas).
    local_whisper_condition_on_previous_text: bool = False
    # Texto de contexto para sesgar nombres/jerga (None = sin prompt).
    local_whisper_initial_prompt: str | None = None

    # --- Módulos opcionales de preprocesamiento ---------------------------
    # Token de Hugging Face para modelos gated (p. ej. diarización con pyannote).
    hf_token: str | None = None

    def is_provider_configured(self, name: str) -> bool:
        """Indica si un proveedor tiene lo mínimo para operar."""
        # El motor local no requiere credenciales; los proveedores cloud se
        # añadirán aquí cuando se implementen.
        return name == "local"


@lru_cache
def get_settings() -> Settings:
    return Settings()
