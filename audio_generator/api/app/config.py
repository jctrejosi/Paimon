"""Configuración del servicio de síntesis de voz.

Todo se controla por variables de entorno (o un archivo `.env`). En esta primera
versión el único proveedor activo es Kokoro (local, CPU): funciona sin credenciales
ni red (salvo la descarga inicial del modelo, que se cachea). Los proveedores de
clonación (XTTS) y de producción con GPU (CosyVoice) se añadirán después detrás de
la misma interfaz.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["kokoro"]


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
    tts_api_token: str | None = None
    # Longitud máxima de texto a sintetizar, en caracteres.
    tts_max_text_length: int = 1000
    # Tamaño máximo de subida (audio de referencia), en MB.
    tts_max_upload_mb: float = 25.0
    # `cpu` o `cuda` (si hay GPU). Kokoro en CPU ya da tiempo real.
    tts_device: str = "cpu"

    # Proveedor usado si la petición no especifica uno.
    tts_provider: ProviderName = "kokoro"

    # Directorio donde se persisten las voces clonadas (volumen).
    voices_dir: Path = Path("voices")

    # --- Kokoro -----------------------------------------------------------
    # Código de idioma: 'e' = español, 'a' = en-US, 'b' = en-GB, 'f' = fr, ...
    kokoro_lang: str = "e"
    # Voz por defecto si la petición no especifica una.
    kokoro_default_voice: str = "ef_dora"
    # Repositorio de Hugging Face con los pesos.
    kokoro_repo_id: str = "hexgrad/Kokoro-82M"
    # Frecuencia de muestreo de salida de Kokoro.
    kokoro_sample_rate: int = 24000

    def is_provider_configured(self, name: str) -> bool:
        """Indica si un proveedor tiene lo mínimo para operar."""
        # Kokoro es local y no requiere credenciales.
        return name == "kokoro"


@lru_cache
def get_settings() -> Settings:
    return Settings()
