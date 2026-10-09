"""Router agregado de preprocesamiento.

Monta la API propia de cada módulo bajo `/preprocess/<nombre>` y añade los
endpoints de conjunto: listado, presets y ejecución de un pipeline.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ..config import get_settings
from ..deps import decode_upload, read_upload
from .pipeline import Pipeline, normalize_spec
from .presets import PRESETS
from .registry import PROCESSORS, module_router
from .router_factory import audios_out, processor_info, segments_out
from .schemas import (
    PipelineResponse,
    PresetInfo,
    PresetsResponse,
    ProcessorsResponse,
    StepReportOut,
)

router = APIRouter()


@router.get("/processors", response_model=ProcessorsResponse, tags=["preprocessing"])
async def list_processors() -> ProcessorsResponse:
    return ProcessorsResponse(processors=[processor_info(c) for c in PROCESSORS.values()])


@router.get("/presets", response_model=PresetsResponse, tags=["preprocessing"])
async def list_presets() -> PresetsResponse:
    return PresetsResponse(
        presets=[
            PresetInfo(name=name, steps=[step[0] for step in steps])
            for name, steps in PRESETS.items()
        ]
    )


@router.post("/preprocess", response_model=PipelineResponse, tags=["preprocessing"])
async def preprocess(
    file: Annotated[UploadFile, File(description="Audio de entrada.")],
    preset: Annotated[str, Form(description="Preset a aplicar ('raw', 'minimal', ...).")] = "",
    steps: Annotated[str, Form(description="Lista de pasos en JSON (si no hay preset).")] = "[]",
    include_audio: Annotated[bool, Form(description="Incluir audio WAV en base64.")] = True,
) -> PipelineResponse:
    content = await read_upload(file)

    if preset:
        spec: str | list = preset
    else:
        try:
            spec = json.loads(steps or "[]")
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"steps no es JSON válido: {exc}") from exc

    preset_name, parsed_steps = normalize_spec(spec)
    pipeline = Pipeline(parsed_steps, get_settings())

    clip = decode_upload(content)
    started = time.perf_counter()
    result = await asyncio.to_thread(pipeline.apply, clip)
    elapsed_ms = (time.perf_counter() - started) * 1000

    return PipelineResponse(
        preset=preset_name,
        elapsed_ms=elapsed_ms,
        steps=[
            StepReportOut(
                name=report.name,
                params=report.params,
                elapsed_ms=report.elapsed_ms,
                clips=report.clips,
                metrics=report.metrics,
            )
            for report in result.steps
        ],
        audios=audios_out(result.clips) if include_audio else [],
        segments=segments_out(result.segments),
    )


# API propia de cada módulo: /preprocess/<nombre>
for _name in PROCESSORS:
    router.include_router(module_router(_name), prefix="/preprocess")

# Alias de conveniencia: /analyze
router.include_router(module_router("analyze"))
