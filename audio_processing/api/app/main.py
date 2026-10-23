"""API HTTP de transcripción y preprocesamiento de audio de Paimon.

Recibe un archivo de audio ya descargado, lo puede limpiar con el pipeline de
preprocesamiento modular y devuelve la transcripción en texto. El bot de
WhatsApp es otra herramienta y no se implementa aquí.
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse

from .audio import encode_wav
from .api_key_auth import APIKeyMiddleware
from .config import get_settings
from .deps import decode_upload, require_token, validate_audio
from .preprocessing.api import router as preprocessing_router
from .preprocessing.base import ProcessorError
from .preprocessing.pipeline import Pipeline
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
    version="0.2.0",
    description="Transcripción local (voz→texto) y preprocesamiento modular de audio.",
    lifespan=lifespan,
)

app.add_middleware(APIKeyMiddleware)

# API propia de cada módulo de preprocesamiento (/processors, /preprocess, ...).
app.include_router(preprocessing_router)


@app.exception_handler(ProviderError)
async def provider_error_handler(_: Request, exc: ProviderError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc), "provider": exc.provider},
    )


@app.exception_handler(ProcessorError)
async def processor_error_handler(_: Request, exc: ProcessorError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc), "processor": exc.processor},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


def resolve_language(language: str | None) -> str | None:
    """Aplica el idioma por defecto; `auto` fuerza autodetección (None).

    Un valor vacío (p. ej. Swagger sin rellenar) se trata como no especificado.
    Un código inválido se rechaza con 400 (antes fallaba dentro del motor con 502).
    """
    if not language:
        language = settings.audio_default_language
    if not language or language.strip().lower() == "auto":
        return None
    code = language.strip().lower()
    if not re.fullmatch(r"[a-z]{2,3}", code):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Idioma inválido: '{language}'. Usa un código ISO-639-1 "
                "(p. ej. 'es') o 'auto'."
            ),
        )
    return code


def to_response(result: TranscriptResult, preprocess: str | None = None) -> TranscribeResponse:
    return TranscribeResponse(
        id=str(uuid.uuid4()),
        provider=result.provider,
        model=result.model,
        created=int(time.time()),
        preprocess=preprocess,
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
            "processors": "/processors",
            "presets": "/presets",
            "pipeline": "POST /preprocess",
            "module": "POST /preprocess/{modulo}",
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
    language: Annotated[
        str, Form(description="ISO-639-1 o 'auto' (autodetección).")
    ] = settings.audio_default_language or "auto",
    model: Annotated[
        str, Form(description="Modelo a usar (base/small/medium/large-v3-turbo/...).")
    ] = settings.local_whisper_model,
    provider: Annotated[str, Form(description="Proveedor a usar.")] = settings.audio_provider,
    verbose: Annotated[bool, Form(description="Incluir segmentos con marcas de tiempo.")] = False,
    vad: Annotated[
        bool, Form(description="Recortar silencio con VAD (reduce alucinaciones).")
    ] = settings.local_whisper_vad,
    beam_size: Annotated[
        int, Form(description="Ancho de búsqueda del decodificador (5; 1 = más rápido).")
    ] = settings.local_whisper_beam_size,
    condition_on_previous_text: Annotated[
        bool, Form(description="Condicionar cada segmento al texto anterior (False evita bucles).")
    ] = settings.local_whisper_condition_on_previous_text,
    initial_prompt: Annotated[
        str, Form(description="Contexto para sesgar nombres/jerga (opcional).")
    ] = settings.local_whisper_initial_prompt or "",
    preprocess: Annotated[
        str, Form(description="'none' o un preset ('raw', 'minimal', 'clean', 'noisy').")
    ] = "none",
) -> TranscribeResponse:
    content = await file.read()
    validate_audio(content, file.filename)

    preset = (preprocess or "").strip()
    applied = preset if preset and preset.lower() != "none" else None
    if applied:
        clip = decode_upload(content)
        pipeline = Pipeline.from_spec(applied, settings)
        cleaned = await asyncio.to_thread(pipeline.apply, clip)
        if not cleaned.clips:
            raise HTTPException(status_code=400, detail="El preprocesamiento no produjo audio.")
        content = encode_wav(cleaned.clips[0])

    request = TranscribeRequest(
        data=content,
        filename=file.filename,
        content_type=file.content_type,
        language=resolve_language(language),
        model=model,
        verbose=verbose,
        vad=vad,
        beam_size=beam_size,
        condition_on_previous_text=condition_on_previous_text,
        initial_prompt=initial_prompt,
    )
    backend = manager.get(provider or settings.audio_provider)
    result = await backend.transcribe(request)
    return to_response(result, preprocess=applied)


@app.post("/v1/audio/transcriptions", dependencies=[Depends(require_token)])
async def openai_transcriptions(
    file: Annotated[UploadFile, File(description="Archivo de audio (compatible OpenAI).")],
    model: Annotated[
        str,
        Form(description="Modelo local; 'whisper-1' (OpenAI) usa el modelo por defecto."),
    ] = settings.local_whisper_model,
    language: Annotated[
        str, Form(description="ISO-639-1 (p. ej. 'es') o 'auto'.")
    ] = settings.audio_default_language or "auto",
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
        # Compatibilidad OpenAI: 'whisper-1' (o vacío) → modelo por defecto.
        model=None if not model or model == "whisper-1" else model,
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
