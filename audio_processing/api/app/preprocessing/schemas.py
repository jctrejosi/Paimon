"""Modelos de entrada/salida de la API de preprocesamiento."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AudioOut(BaseModel):
    """Audio resultante, codificado como WAV en base64."""

    b64: str
    mime_type: str = "audio/wav"
    sample_rate: int
    duration: float


class SegmentOut(BaseModel):
    start: float
    end: float
    text: str | None = None
    speaker: str | None = None


class StepInfo(BaseModel):
    name: str
    description: str
    available: bool
    required_packages: list[str] = Field(default_factory=list)
    params_schema: dict[str, Any] = Field(default_factory=dict)


class ProcessorsResponse(BaseModel):
    processors: list[StepInfo]


class PresetInfo(BaseModel):
    name: str
    steps: list[str]


class PresetsResponse(BaseModel):
    presets: list[PresetInfo]


class StepResponse(BaseModel):
    processor: str
    params: dict[str, Any]
    elapsed_ms: float
    audios: list[AudioOut] = Field(default_factory=list)
    segments: list[SegmentOut] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class StepReportOut(BaseModel):
    name: str
    params: dict[str, Any]
    elapsed_ms: float
    clips: int
    metrics: dict[str, Any] = Field(default_factory=dict)


class PipelineResponse(BaseModel):
    preset: str | None = None
    elapsed_ms: float | None = None
    steps: list[StepReportOut] = Field(default_factory=list)
    audios: list[AudioOut] = Field(default_factory=list)
    segments: list[SegmentOut] = Field(default_factory=list)
