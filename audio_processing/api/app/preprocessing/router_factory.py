"""Fábrica del router que expone la API propia de cada módulo.

Cada módulo declara su router en `modules/<nombre>/router.py` llamando a
`build_step_router(MiProcessor)`. La API resultante es siempre la misma forma:

- `GET  /preprocess/<nombre>`  → información y parámetros del módulo.
- `POST /preprocess/<nombre>`  → aplica el módulo a un audio subido.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import ValidationError

from ..audio import encode_wav
from ..audio.types import AudioClip, Segment
from ..config import get_settings
from ..deps import decode_upload, read_upload
from .base import Processor
from .registry import get_processor
from .schemas import AudioOut, SegmentOut, StepInfo, StepResponse


def processor_info(cls: type[Processor]) -> StepInfo:
    return StepInfo(
        name=cls.name,
        description=cls.description,
        available=cls.available(),
        required_packages=list(cls.required_packages),
        params_schema=cls.params_model.model_json_schema(),
    )


def parse_params(cls: type[Processor], raw: str):
    """Valida el JSON de parámetros contra el modelo del módulo."""
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"params no es JSON válido: {exc}") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="params debe ser un objeto JSON.")
    try:
        return cls.params_model(**data)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc


def audios_out(clips: list[AudioClip]) -> list[AudioOut]:
    return [
        AudioOut(
            b64=base64.b64encode(encode_wav(clip)).decode("ascii"),
            sample_rate=clip.sample_rate,
            duration=clip.duration,
        )
        for clip in clips
    ]


def segments_out(segments: list[Segment]) -> list[SegmentOut]:
    return [
        SegmentOut(start=s.start, end=s.end, text=s.text, speaker=s.speaker)
        for s in segments
    ]


def build_step_router(cls: type[Processor]) -> APIRouter:
    router = APIRouter(prefix=f"/{cls.name}", tags=["preprocessing"])

    @router.get("", response_model=StepInfo, summary=f"Módulo '{cls.name}'")
    async def info() -> StepInfo:
        return processor_info(cls)

    @router.post("", response_model=StepResponse, summary=f"Aplica '{cls.name}'")
    async def apply(
        file: Annotated[UploadFile, File(description="Audio de entrada.")],
        params: Annotated[str, Form(description="Parámetros del módulo (JSON).")] = "{}",
        include_audio: Annotated[bool, Form(description="Incluir audio WAV en base64.")] = True,
    ) -> StepResponse:
        content = await read_upload(file)
        processor = get_processor(cls.name, get_settings())
        parsed = parse_params(cls, params)
        clip = decode_upload(content)
        started = time.perf_counter()
        result = await asyncio.to_thread(processor.process, clip, parsed)
        elapsed_ms = (time.perf_counter() - started) * 1000
        return StepResponse(
            processor=cls.name,
            params=parsed.model_dump(),
            elapsed_ms=elapsed_ms,
            audios=audios_out(result.clips) if include_audio else [],
            segments=segments_out(result.segments),
            metrics=result.metrics,
        )

    return router
