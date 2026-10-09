"""API HTTP de transcripción de audio de Paimon.

Expone una interfaz estable y agnóstica al backend: recibe un archivo de audio ya
descargado y devuelve la transcripción en texto. El proveedor (hoy solo el local)
se elige por petición o por configuración. El bot de WhatsApp es otra herramienta
y no se implementa aquí.
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse

from .audio import ALLOWED_EXTENSIONS, extension_of, max_bytes
from .config import get_settings
from .providers.base import ProviderError, TranscriptResult
from .providers.registry import PROVIDER_CLASSES, ProviderManager
from .schemas import (
    HealthResponse,
    ProviderInfo,
    ProvidersResponse,
    SegmentOut,
    TranscribeRequest,
    TranscribeResponse,
)

settings = get_settings()
manager = ProviderManager(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await manager.aclose()


app = FastAPI(
    title="Paimon Audio Processing",
    version="0.1.0",
    description="Transcripción de audio (voz→texto) con motor local.",
    lifespan=lifespan,
)


def require_token(authorization: str | None = Header(default=None)) -> None:
    """Exige `Authorization: Bearer <token>` cuando hay token configurado."""
    expected = settings.audio_api_token
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


def resolve_language(language: str | None) -> str | None:
    """Aplica el idioma por defecto; `auto` fuerza autodetección (None)."""
    if language is None:
        language = settings.audio_default_language
    if language and language.lower() in {"auto", ""}:
        return None
    return language


def validate_audio(content: bytes, filename: str | None) -> None:
    """Valida el archivo subido; lanza HTTPException si no es aceptable."""
    if not content:
        raise HTTPException(status_code=400, detail="El archivo de audio está vacío.")
    limit = max_bytes(settings.audio_max_upload_mb)
    if len(content) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"El archivo supera el límite de {settings.audio_max_upload_mb} MB.",
        )
    ext = extension_of(filename)
    if ext and ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"Extensión no soportada: {ext}.")


def to_response(result: TranscriptResult) -> TranscribeResponse:
    return TranscribeResponse(
        id=str(uuid.uuid4()),
        provider=result.provider,
        model=result.model,
        created=int(time.time()),
        text=result.text,
        language=result.language,
        language_probability=result.language_probability,
        duration=result.duration,
        segments=[
            SegmentOut(start=seg.start, end=seg.end, text=seg.text) for seg in result.segments
        ],
    )


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {
        "service": "paimon-audio-processing",
        "endpoints": {
            "health": "/health",
            "providers": "/providers",
            "transcribe": "POST /transcribe",
            "openai_compatible": "POST /v1/audio/transcriptions",
        },
    }


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        default_provider=settings.audio_provider,
        configured_providers=manager.configured_names(),
    )


@app.get("/providers", response_model=ProvidersResponse)
async def list_providers() -> ProvidersResponse:
    configured = set(manager.configured_names())
    return ProvidersResponse(
        default_provider=settings.audio_provider,
        providers=[
            ProviderInfo(
                name=cls.name,
                configured=cls.is_configured(settings),
                default=(cls.name == settings.audio_provider),
                model=cls.default_model(settings) if cls.name in configured else None,
            )
            for cls in PROVIDER_CLASSES
        ],
    )


@app.post(
    "/transcribe",
    response_model=TranscribeResponse,
    dependencies=[Depends(require_token)],
)
async def transcribe(
    file: Annotated[UploadFile, File(description="Archivo de audio a transcribir.")],
    language: Annotated[str | None, Form(description="ISO-639-1 o 'auto'.")] = None,
    model: Annotated[str | None, Form(description="Modelo específico del proveedor.")] = None,
    provider: Annotated[str | None, Form(description="Proveedor a usar.")] = None,
    verbose: Annotated[bool, Form(description="Incluir segmentos con tiempos.")] = False,
) -> TranscribeResponse:
    content = await file.read()
    validate_audio(content, file.filename)

    request = TranscribeRequest(
        data=content,
        filename=file.filename,
        content_type=file.content_type,
        language=resolve_language(language),
        model=model,
        verbose=verbose,
    )
    backend = manager.get(provider or settings.audio_provider)
    result = await backend.transcribe(request)
    return to_response(result)


@app.post("/v1/audio/transcriptions", dependencies=[Depends(require_token)])
async def openai_transcriptions(
    file: Annotated[UploadFile, File(description="Archivo de audio (compatible OpenAI).")],
    model: Annotated[str | None, Form()] = None,
    language: Annotated[str | None, Form()] = None,
    response_format: Annotated[str, Form()] = "json",
    prompt: Annotated[str | None, Form()] = None,
    temperature: Annotated[float, Form()] = 0.0,
):
    """Endpoint compatible con la API de transcripciones de OpenAI.

    Permite al bot usar cualquier SDK de OpenAI sin conocer nuestra API. `prompt`
    y `temperature` se aceptan por compatibilidad pero no se usan todavía.
    """
    if response_format not in {"json", "text", "verbose_json"}:
        raise HTTPException(
            status_code=400,
            detail=f"response_format no soportado: '{response_format}'.",
        )

    content = await file.read()
    validate_audio(content, file.filename)

    request = TranscribeRequest(
        data=content,
        filename=file.filename,
        content_type=file.content_type,
        language=resolve_language(language),
        model=model,
        verbose=response_format == "verbose_json",
    )
    result = await manager.get(settings.audio_provider).transcribe(request)

    if response_format == "text":
        return PlainTextResponse(result.text)

    payload: dict = {"text": result.text}
    if response_format == "verbose_json":
        payload.update(
            {
                "language": result.language,
                "duration": result.duration,
                "segments": [
                    {"start": seg.start, "end": seg.end, "text": seg.text}
                    for seg in result.segments
                ],
            }
        )
    return JSONResponse(payload)
