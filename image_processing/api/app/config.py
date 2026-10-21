"""Configuración del servicio de procesamiento de imágenes.

Todo se controla por variables de entorno (o un archivo `.env`). En esta primera
versión el único proveedor es el local (`rembg` sobre ONNX Runtime, CPU): funciona
sin credenciales ni red, salvo la descarga inicial del modelo (que se cachea).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["local"]
OutputFormat = Literal["png", "webp"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Permite instanciar/tests sin que falten variables obligatorias.
        validate_default=True,
    )

    # --- Servicio ---------------------------------------------------------
    # Token opcional; si se define, `/remove-bg` lo exige como
    # `Authorization: Bearer <token>`.
    image_processing_api_token: str | None = None
    # Tamaño máximo de subida, en MB.
    image_processing_max_upload_mb: float = 20.0
    # Tope de píxeles (ancho × alto) para evitar bombas de descompresión.
    max_image_pixels: int = 40_000_000
    # Formato de salida por defecto cuando la petición no lo indica.
    default_output_format: OutputFormat = "png"

    # Proveedor usado si la petición no especifica uno.
    image_processing_provider: ProviderName = "local"

    # --- Motor local (rembg) ---------------------------------------------
    # isnet-general-use | birefnet-general | birefnet-general-lite | u2net | ...
    # `isnet-general-use` es el mejor equilibrio calidad/memoria en CPU para
    # este equipo (~0.9 GB, ~20 s). `birefnet-general` da más calidad pero usa
    # ~8 GB y tarda minutos.
    local_rembg_model: str = "isnet-general-use"
    # Matting alfa: bordes más finos a cambio de más cómputo.
    local_rembg_alpha_matting: bool = False
    # Limpieza morfológica de la máscara (quita islas pequeñas).
    local_rembg_post_process_mask: bool = False
    # Directorio donde se cachean los pesos (volumen en Docker).
    local_rembg_model_dir: Path = Path("models")

    # --- ONNX Runtime (CPU) -----------------------------------------------
    # Limitar hilos y desactivar el arena reduce mucho el pico de memoria
    # (birefnet-general pasaba de 13.5 GB a ~8 GB).
    local_rembg_intra_op_threads: int = 2
    local_rembg_inter_op_threads: int = 1
    local_rembg_cpu_mem_arena: bool = False
    local_rembg_enable_mem_pattern: bool = False

    def is_provider_configured(self, name: str) -> bool:
        """Indica si un proveedor tiene lo mínimo para operar."""
        # El motor local no requiere credenciales; los proveedores cloud se
        # añadirán aquí cuando se implementen.
        return name == "local"


@lru_cache
def get_settings() -> Settings:
    return Settings()
