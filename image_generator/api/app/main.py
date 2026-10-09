"""API HTTP de generación de imágenes de Paimon.

Expone una interfaz estable y agnóstica al backend; el proveedor (ComfyUI local
o uno externo de pago) se elige por petición o por configuración.
"""

from __future__ import annotations

import base64
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .providers.base import ProviderError
from .providers.registry import PROVIDER_CLASSES, ProviderManager
from .schemas import (
    GenerateImage,
    GenerateRequest,
    GenerateResponse,
    HealthResponse,
    ProviderInfo,
    ProvidersResponse,
)
from .storage import ImageStorage

settings = get_settings()
storage = ImageStorage(settings.output_dir)
manager = ProviderManager(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await manager.aclose()


app = FastAPI(
    title="Paimon Image Generator",
    version="0.1.0",
    description="Generación de imágenes con ComfyUI local o proveedores externos.",
    lifespan=lifespan,
)


def require_token(authorization: str | None = Header(default=None)) -> None:
    """Exige `Authorization: Bearer <token>` cuando hay token configurado."""
    expected = settings.image_api_token
    if not expected:
        return
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or token != expected:
        raise HTTPException(status_code=401, detail="Token de API inválido o ausente.")


@app.exception_handler(ProviderError)
async def provider_error_handler(_: Request, exc: ProviderError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc), "provider": exc.provider},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


def build_image_url(request: Request, filename: str) -> str:
    if settings.public_base_url:
        return f"{settings.public_base_url.rstrip('/')}/images/{filename}"
    return str(request.base_url).rstrip("/") + f"/images/{filename}"


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {
        "service": "paimon-image-generator",
        "endpoints": {
            "health": "/health",
            "providers": "/providers",
            "generate": "POST /generate",
            "images": "/images/{filename}",
        },
    }


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        default_provider=settings.image_provider,
        configured_providers=manager.configured_names(),
    )


@app.get("/providers", response_model=ProvidersResponse)
async def list_providers() -> ProvidersResponse:
    configured = set(manager.configured_names())
    return ProvidersResponse(
        default_provider=settings.image_provider,
        providers=[
            ProviderInfo(
                name=cls.name,
                configured=cls.is_configured(settings),
                default=(cls.name == settings.image_provider),
                model=cls.default_model(settings) if cls.name in configured else None,
            )
            for cls in PROVIDER_CLASSES
        ],
    )


@app.post("/generate", response_model=GenerateResponse, dependencies=[Depends(require_token)])
async def generate(request: Request, body: GenerateRequest) -> GenerateResponse:
    provider_name = body.provider or settings.image_provider
    provider = manager.get(provider_name)

    result = await provider.generate(body)

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
                    url=build_image_url(request, filename),
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


# Sirve las imágenes generadas. El directorio ya existe (ImageStorage lo crea).
app.mount("/images", StaticFiles(directory=str(storage.output_dir)), name="images")
