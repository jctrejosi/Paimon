"""Configuración del servicio de generación de imágenes.

Todo se controla por variables de entorno (o un archivo `.env`). Ninguno de los
proveedores externos es obligatorio: si no hay credenciales, simplemente no se
ofrecen. ComfyUI es el proveedor por defecto porque corre local y sin coste.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["comfyui", "openai", "stability", "replicate", "fal", "bfl"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Permite instanciar/tests sin que falten variables obligatorias.
        validate_default=True,
    )

    # --- Servicio ---------------------------------------------------------
    # Token opcional; si se define, `/generate` lo exige como
    # `Authorization: Bearer <token>`.
    image_api_token: str | None = None
    # Directorio donde se guardan las imágenes servidas por URL.
    output_dir: Path = Path("outputs")
    # URL base pública para construir enlaces absolutos (útil detrás de proxy).
    public_base_url: str | None = None

    # Proveedor usado si la petición no especifica uno.
    image_provider: ProviderName = "comfyui"

    # --- ComfyUI ----------------------------------------------------------
    comfyui_url: str = "http://127.0.0.1:8188"
    # Checkpoint presente en ComfyUI/models/checkpoints.
    comfyui_checkpoint: str = "v1-5-pruned-emaonly.safetensors"
    # Plantilla de workflow (formato API de ComfyUI). None → plantilla integrada.
    comfyui_workflow: Path | None = None
    comfyui_timeout: float = 300.0
    comfyui_poll_interval: float = 0.5

    # --- OpenAI (gpt-image-1 / dall-e-3) ---------------------------------
    openai_api_key: str | None = None
    openai_image_model: str = "gpt-image-1"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_timeout: float = 180.0

    # --- Stability AI -----------------------------------------------------
    stability_api_key: str | None = None
    stability_image_model: str = "core"
    stability_base_url: str = "https://api.stability.ai"
    stability_timeout: float = 180.0

    # --- Replicate --------------------------------------------------------
    replicate_api_token: str | None = None
    replicate_model: str = "black-forest-labs/flux-schnell"
    replicate_timeout: float = 300.0

    # --- fal.ai -----------------------------------------------------------
    fal_key: str | None = None
    fal_model: str = "fal-ai/flux/schnell"
    fal_timeout: float = 180.0

    # --- Black Forest Labs (FLUX) ----------------------------------------
    bfl_api_key: str | None = None
    bfl_model: str = "flux-schnell"
    bfl_base_url: str = "https://api.bfl.ai/v1"
    bfl_timeout: float = 180.0

    def is_provider_configured(self, name: str) -> bool:
        """Indica si un proveedor tiene lo mínimo para operar."""
        if name == "comfyui":
            return bool(self.comfyui_url)
        if name == "openai":
            return bool(self.openai_api_key)
        if name == "stability":
            return bool(self.stability_api_key)
        if name == "replicate":
            return bool(self.replicate_api_token)
        if name == "fal":
            return bool(self.fal_key)
        if name == "bfl":
            return bool(self.bfl_api_key)
        return False


@lru_cache
def get_settings() -> Settings:
    return Settings()
