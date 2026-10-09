"""Módulo `resample`: remuestreo a una frecuencia destino."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.audio.io import resample_samples
from app.audio.types import AudioClip
from app.preprocessing.base import Processor, ProcessorResult


class ResampleParams(BaseModel):
    sample_rate: int = Field(default=16000, ge=4000, le=192000)


class ResampleProcessor(Processor):
    name = "resample"
    description = "Remuestrea a la frecuencia indicada (por defecto 16 kHz, la de Whisper)."
    params_model = ResampleParams

    def process(self, clip: AudioClip, params: ResampleParams) -> ProcessorResult:
        out = AudioClip(
            resample_samples(clip.samples, clip.sample_rate, params.sample_rate),
            params.sample_rate,
        )
        return ProcessorResult(
            clips=[out],
            metrics={
                "input_sample_rate": clip.sample_rate,
                "sample_rate": out.sample_rate,
                "duration": out.duration,
            },
        )
