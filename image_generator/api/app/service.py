"""Pipeline de generación compartido por las rutas síncronas y los jobs."""

from __future__ import annotations

import base64
import time
import uuid

from . import metrics
from .config import Settings
from .providers.base import ProviderError
from .providers.registry import ProviderManager
from .schemas import GenerateImage, GenerateRequest, GenerateResponse
from .storage import ImageStorage


def build_image_url(filename: str, base_url: str | None, settings: Settings) -> str:
    """Construye la URL de una imagen generada.

    Prioridad: `PUBLIC_BASE_URL` > URL base de la petición > ruta relativa.
    """
    if settings.public_base_url:
        return f"{settings.public_base_url.rstrip('/')}/images/{filename}"
    if base_url:
        return base_url.rstrip("/") + f"/images/{filename}"
    return f"/images/{filename}"


async def run_generation(
    settings: Settings,
    manager: ProviderManager,
    storage: ImageStorage,
    body: GenerateRequest,
    base_url: str | None,
) -> GenerateResponse:
    """Ejecuta la generación con el proveedor adecuado y arma la respuesta."""
    provider_name = body.provider or settings.image_provider
    provider = manager.get(provider_name)
    # La capacidad de edición se valida aquí, de forma uniforme para todo backend.
    provider.ensure_img2img(body)

    try:
        result = await provider.generate(body)
    except ProviderError:
        metrics.generations.labels(provider_name, "failed").inc()
        raise
    metrics.generations.labels(provider_name, "succeeded").inc()

    images: list[GenerateImage] = []
    for raw in result.images:
        if body.response_format == "b64_json":
            images.append(
                GenerateImage(
                    b64_json=base64.b64encode(raw.data).decode("ascii"),
                    mime_type=raw.mime_type,
                    seed=raw.seed,
                    revised_prompt=raw.revised_prompt,
                )
            )
        else:
            filename = storage.save(raw.data, raw.mime_type, prefix=provider_name)
            images.append(
                GenerateImage(
                    url=build_image_url(filename, base_url, settings),
                    mime_type=raw.mime_type,
                    seed=raw.seed,
                    revised_prompt=raw.revised_prompt,
                )
            )

    return GenerateResponse(
        id=str(uuid.uuid4()),
        provider=result.provider,
        model=result.model,
        created=int(time.time()),
        images=images,
        metadata=result.metadata,
    )
