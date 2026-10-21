"""API HTTP de procesamiento de imágenes de Paimon.

Primera funcionalidad: **quitar el fondo** (`POST /remove-bg`). Recibe una imagen
por `multipart/form-data` y devuelve otra con el fondo eliminado (PNG/WebP con
alfa) o compuesto sobre un color sólido.

El motor es local (`rembg` sobre ONNX Runtime, CPU), el mismo tipo de modelos que
usa ArtCraft a través de fal, pero corriendo en la propia máquina.
"""

from __future__ import annotations

import base64
import time
import uuid
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, File, Form, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .config import get_settings
from .deps import read_image_upload, require_token
from .images import parse_background
from .providers.base import ProviderError, RemoveBgRequest
from .providers.local_rembg import SUPPORTED_MODELS
from .providers.registry import PROVIDER_CLASSES, ProviderManager
from .schemas import (
    HealthResponse,
    ModelsResponse,
    ProviderInfo,
    ProvidersResponse,
)

settings = get_settings()
manager = ProviderManager(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await manager.aclose()


app = FastAPI(
    title="Paimon Image Processing",
    version="0.1.0",
    description="Procesamiento local de imágenes. Primera función: quitar el fondo.",
    lifespan=lifespan,
)


@app.exception_handler(ProviderError)
async def provider_error_handler(_: Request, exc: ProviderError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc), "provider": exc.provider},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {
        "service": "paimon-image-processing",
        "endpoints": {
            "health": "/health",
            "providers": "/providers",
            "models": "/models",
            "remove_bg": "POST /remove-bg",
        },
    }


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        default_provider=settings.image_processing_provider,
        configured_providers=manager.configured_names(),
    )


@app.get("/providers", response_model=ProvidersResponse)
async def list_providers() -> ProvidersResponse:
    return ProvidersResponse(
        default_provider=settings.image_processing_provider,
        providers=[
            ProviderInfo(
                name=cls.name,
                configured=cls.is_configured(settings),
                default=(cls.name == settings.image_processing_provider),
                model=cls.default_model(settings),
            )
            for cls in PROVIDER_CLASSES
        ],
    )


@app.get("/models", response_model=ModelsResponse)
async def list_models() -> ModelsResponse:
    return ModelsResponse(
        default=settings.local_rembg_model,
        models=sorted(SUPPORTED_MODELS),
    )


@app.post("/remove-bg", response_model=None, dependencies=[Depends(require_token)])
async def remove_bg(
    file: Annotated[UploadFile, File(description="Imagen a la que quitar el fondo.")],
    model: Annotated[
        str | None,
        Form(description="Modelo de rembg (u2net, isnet-general-use, birefnet-general...)."),
    ] = None,
    alpha_matting: Annotated[
        bool, Form(description="Matting alfa: bordes más finos (más lento).")
    ] = settings.local_rembg_alpha_matting,
    alpha_matting_foreground_threshold: Annotated[
        int, Form(ge=0, le=255, description="Umbral de primer plano (matting alfa).")
    ] = 240,
    alpha_matting_background_threshold: Annotated[
        int, Form(ge=0, le=255, description="Umbral de fondo (matting alfa).")
    ] = 10,
    alpha_matting_erode_size: Annotated[
        int, Form(ge=0, le=100, description="Erosión de la máscara (matting alfa).")
    ] = 10,
    post_process_mask: Annotated[
        bool | None, Form(description="Limpieza morfológica de la máscara.")
    ] = None,
    background: Annotated[
        str,
        Form(description="'transparent' (alfa) o un color '#RRGGBB' para componer."),
    ] = "transparent",
    output_format: Annotated[Literal["png", "webp"], Form()] = settings.default_output_format,
    response_format: Annotated[Literal["image", "json"], Form()] = "image",
    provider: Annotated[str, Form(description="Proveedor a usar.")] = (
        settings.image_processing_provider
    ),
) -> Response:
    content = await read_image_upload(file)
    background_color = parse_background(background)

    request = RemoveBgRequest(
        data=content,
        model=model or None,
        alpha_matting=alpha_matting,
        alpha_matting_foreground_threshold=alpha_matting_foreground_threshold,
        alpha_matting_background_threshold=alpha_matting_background_threshold,
        alpha_matting_erode_size=alpha_matting_erode_size,
        post_process_mask=post_process_mask,
        background=background_color,
        output_format=output_format,
        provider=provider,
    )

    backend = manager.get(provider)
    start = time.perf_counter()
    result = await backend.remove_background(request)
    elapsed_ms = int((time.perf_counter() - start) * 1000)

    headers = {
        "X-Provider": result.provider,
        "X-Model": result.model,
        "X-Elapsed-Ms": str(elapsed_ms),
    }

    if response_format == "json":
        payload = {
            "id": str(uuid.uuid4()),
            "provider": result.provider,
            "model": result.model,
            "created": int(time.time()),
            "mime_type": result.mime_type,
            "width": result.width,
            "height": result.height,
            "elapsed_ms": elapsed_ms,
            "image_base64": base64.b64encode(result.data).decode("ascii"),
        }
        return JSONResponse(content=payload, headers=headers)

    extension = "webp" if result.mime_type == "image/webp" else "png"
    headers["Content-Disposition"] = f'inline; filename="remove-bg.{extension}"'
    return Response(content=result.data, media_type=result.mime_type, headers=headers)
