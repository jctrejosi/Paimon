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

    # --- Jobs asíncronos --------------------------------------------------
    # Cuántas generaciones simultáneas como máximo (1 = serie; ComfyUI en CPU
    # rinde mejor así).
    job_concurrency: int = 1
    # Ejecución: 'inline' (en el proceso de la API) o 'worker' (proceso aparte).
    job_execution: Literal["inline", "worker"] = "inline"
    # Cada cuánto (s) un worker refresca el latido de un job en curso.
    job_heartbeat_interval: float = 15.0
    # Un job 'running' sin latido reciente se considera huérfano pasado este tiempo.
    job_stale_after: float = 60.0
    # Margen (s) para dejar terminar los jobs en curso al apagar el ejecutor.
    job_shutdown_grace: float = 5.0
    # Número máximo de jobs retenidos.
    jobs_max: int = 100
    # Backend del estado de los jobs: 'memory' (efímero) o 'redis' (persistente).
    job_store: Literal["memory", "redis"] = "memory"
    # Conexión a Redis cuando JOB_STORE=redis.
    redis_url: str = "redis://127.0.0.1:6379/0"
    # Caducidad (segundos) de cada job en Redis.
    jobs_ttl: int = 86400
    # Cada cuánto (segundos) el flujo SSE re-consulta el estado como respaldo.
    job_stream_poll: float = 2.0
    # Timeout al entregar un webhook.
    webhook_timeout: float = 30.0

    # --- Límites de entrada -----------------------------------------------
    # Tamaño máximo del cuerpo de una petición, en bytes (32 MiB).
    max_request_bytes: int = 33_554_432
    # Tamaño máximo de una imagen de entrada ya decodificada, en bytes (20 MiB).
    max_image_bytes: int = 20_971_520

    # --- Métricas ---------------------------------------------------------
    # Expone /metrics; en el worker, un servidor en METRICS_PORT.
    metrics_enabled: bool = True
    metrics_port: int = 9100

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
