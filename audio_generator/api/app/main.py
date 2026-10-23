"""API HTTP de síntesis de voz de Paimon.

Recibe un texto y devuelve audio con la voz seleccionada. Soporta salida por lotes
(WAV) y streaming (PCM por chunks y WebSocket bidireccional). El motor por defecto
es Kokoro (local, CPU, tiempo real); la clonación (XTTS) y la producción con GPU
(CosyVoice) se añadirán detrás de la misma interfaz de proveedores.
"""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .api_key_auth import APIKeyMiddleware
from .config import get_settings
from .deps import require_token, validate_audio_upload
from .providers.base import TTSProviderError
from .providers.registry import PROVIDER_CLASSES, ProviderManager
from .schemas import (
    HealthResponse,
    ProviderInfo,
    ProvidersResponse,
    SynthesizeRequest,
    Voice,
    VoiceList,
)
from .voices import VoiceStore

settings = get_settings()
manager = ProviderManager(settings)
store = VoiceStore(settings, manager)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await manager.aclose()


app = FastAPI(
    title="Paimon Audio Generator",
    version="0.1.0",
    description="Síntesis de voz local (texto→audio) con Kokoro.",
    lifespan=lifespan,
)

app.add_middleware(APIKeyMiddleware)


@app.exception_handler(TTSProviderError)
async def provider_error_handler(_: Request, exc: TTSProviderError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc), "provider": exc.provider},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


def resolve_provider(name: str | None) -> str:
    return name or settings.tts_provider


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {
        "service": "paimon-audio-generator",
        "endpoints": {
            "health": "/health",
            "providers": "/providers",
            "synthesize": "POST /synthesize",
            "synthesize_stream": "POST /synthesize/stream",
            "synthesize_ws": "WS /synthesize/ws",
            "voices": "GET /voices",
            "create_voice": "POST /voices",
            "get_voice": "GET /voices/{voice_id}",
            "delete_voice": "DELETE /voices/{voice_id}",
        },
    }


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        default_provider=settings.tts_provider,
        configured_providers=manager.configured_names(),
    )


@app.get("/providers", response_model=ProvidersResponse)
async def list_providers() -> ProvidersResponse:
    configured = set(manager.configured_names())
    return ProvidersResponse(
        default_provider=settings.tts_provider,
        providers=[
            ProviderInfo(
                name=cls.name,
                configured=cls.is_configured(settings),
                default=(cls.name == settings.tts_provider),
                model=cls.default_model(settings) if cls.name in configured else None,
                supports_cloning=cls.supports_cloning,
            )
            for cls in PROVIDER_CLASSES
        ],
    )


@app.post("/synthesize", dependencies=[Depends(require_token)])
async def synthesize(body: SynthesizeRequest) -> Response:
    provider = manager.get(resolve_provider(body.provider))
    result = await provider.synthesize(body)
    media_type = "audio/wav" if result.format == "wav" else "audio/pcm"
    return Response(
        content=result.audio,
        media_type=media_type,
        headers={
            "X-Voice-Id": result.voice_id,
            "X-Provider": result.provider,
            "X-Sample-Rate": str(result.sample_rate),
            "X-Channels": "1",
            "X-Duration-Sec": f"{result.duration_sec:.3f}",
        },
    )


@app.post("/synthesize/stream", dependencies=[Depends(require_token)])
async def synthesize_stream(body: SynthesizeRequest) -> StreamingResponse:
    provider = manager.get(resolve_provider(body.provider))

    async def chunks() -> AsyncIterator[bytes]:
        async for chunk in provider.synthesize_stream(body):
            yield chunk.data

    return StreamingResponse(
        chunks(),
        media_type="audio/pcm",
        headers={
            "X-Voice-Id": body.voice_id or "",
            "X-Provider": provider.name,
            # Kokoro es el único proveedor en v1; se generalizará al añadir más.
            "X-Sample-Rate": str(settings.kokoro_sample_rate),
            "X-Channels": "1",
        },
    )


@app.websocket("/synthesize/ws")
async def synthesize_ws(websocket: WebSocket) -> None:
    """Streaming bidireccional: texto por chunks → audio por chunks.

    Protocolo (JSON):
      cliente → {"type":"start","voice_id":...,"provider":...}
      cliente → {"type":"text","data":"..."}  (varias veces)
      cliente → {"type":"end"}
      servidor → {"type":"audio","data":<base64 pcm>,"sample_rate":24000}
      servidor → {"type":"done"}
    """
    await websocket.accept()
    text_parts: list[str] = []
    voice_id: str | None = None
    provider_name: str | None = None
    try:
        while True:
            message = await websocket.receive_json()
            msg_type = message.get("type")
            if msg_type == "start":
                voice_id = message.get("voice_id")
                provider_name = message.get("provider")
            elif msg_type == "text":
                text_parts.append(message.get("data", ""))
            elif msg_type == "end":
                break
    except WebSocketDisconnect:
        return

    text = "".join(text_parts).strip()
    if not text:
        await websocket.send_json({"type": "error", "detail": "Texto vacío."})
        return

    try:
        request = SynthesizeRequest(
            text=text, voice_id=voice_id, provider=provider_name, speed=1.0, format="pcm"
        )
        provider = manager.get(resolve_provider(provider_name))
        async for chunk in provider.synthesize_stream(request):
            await websocket.send_json(
                {
                    "type": "audio",
                    "data": base64.b64encode(chunk.data).decode("ascii"),
                    "sample_rate": chunk.sample_rate,
                }
            )
        await websocket.send_json({"type": "done"})
    except TTSProviderError as exc:
        await websocket.send_json({"type": "error", "detail": str(exc)})


@app.get("/voices", response_model=VoiceList, dependencies=[Depends(require_token)])
async def list_voices() -> VoiceList:
    return VoiceList(voices=await store.list())


@app.get("/voices/{voice_id}", response_model=Voice, dependencies=[Depends(require_token)])
async def get_voice(voice_id: str) -> Voice:
    voice = await store.get(voice_id)
    if voice is None:
        raise HTTPException(status_code=404, detail="Voz no encontrada.")
    return voice


@app.post(
    "/voices",
    response_model=Voice,
    status_code=201,
    dependencies=[Depends(require_token)],
)
async def create_voice(
    file: Annotated[UploadFile, File(description="Audio de referencia (~6 s).")],
    name: Annotated[str, Form(description="Nombre legible de la voz.")],
    prompt_text: Annotated[str | None, Form(description="Transcripción del audio.")] = None,
    provider: Annotated[str | None, Form(description="Proveedor que clona.")] = None,
) -> Voice:
    provider_name = resolve_provider(provider)
    backend = manager.get(provider_name)
    if not backend.supports_cloning:
        raise HTTPException(
            status_code=400,
            detail=f"El proveedor '{provider_name}' no soporta clonación de voz.",
        )
    content = await file.read()
    validate_audio_upload(content, file.filename)
    voice = await backend.create_voice(content, name, prompt_text)
    await store.add(voice)
    return voice


@app.delete("/voices/{voice_id}", status_code=204, dependencies=[Depends(require_token)])
async def delete_voice(voice_id: str) -> Response:
    if not await store.delete(voice_id):
        raise HTTPException(
            status_code=404,
            detail="Voz no encontrada (las voces integradas no se eliminan).",
        )
    return Response(status_code=204)
