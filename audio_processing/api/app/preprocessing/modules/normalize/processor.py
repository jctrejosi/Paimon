"""Módulo `normalize`: normalización de nivel (pico, RMS o LUFS)."""

from __future__ import annotations

import importlib.util
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from app.audio.types import AudioClip
from app.preprocessing.base import (
    Processor,
    ProcessorResult,
    ProcessorUnavailableError,
)

_MAX_GAIN = 100.0


class NormalizeParams(BaseModel):
    mode: Literal["peak", "rms", "lufs"] = "peak"
    target_db: float = Field(
        default=-1.0, description="Objetivo en dB (pico/RMS). Para LUFS se usa tal cual."
    )


class NormalizeProcessor(Processor):
    name = "normalize"
    description = "Ajusta el nivel del audio a un objetivo en dB (pico, RMS o LUFS)."
    params_model = NormalizeParams

    def process(self, clip: AudioClip, params: NormalizeParams) -> ProcessorResult:
        samples = clip.samples

        if params.mode == "lufs":
            gain = self._lufs_gain(clip, params.target_db)
        elif params.mode == "rms":
            rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
            gain = 0.0 if rms <= 0 else 10 ** (params.target_db / 20) / rms
        else:
            peak = float(np.max(np.abs(samples)))
            gain = 0.0 if peak <= 0 else 10 ** (params.target_db / 20) / peak

        if gain <= 0:
            # Audio en silencio: no hay nada que normalizar.
            return ProcessorResult(
                clips=[clip],
                metrics={"mode": params.mode, "silent": True, "gain_db": 0.0},
            )

        gain = min(gain, _MAX_GAIN)
        out = AudioClip(samples * gain, clip.sample_rate)
        peak = float(np.max(np.abs(out.samples)))
        rms = float(np.sqrt(np.mean(np.square(out.samples, dtype=np.float64))))
        return ProcessorResult(
            clips=[out],
            metrics={
                "mode": params.mode,
                "target_db": params.target_db,
                "gain_db": float(20 * np.log10(gain)),
                "peak": peak,
                "rms": rms,
            },
        )

    @staticmethod
    def _lufs_gain(clip: AudioClip, target_lufs: float) -> float:
        if importlib.util.find_spec("pyloudnorm") is None:
            raise ProcessorUnavailableError("normalize", ("pyloudnorm",))

        import pyloudnorm

        mono = clip.to_mono()
        meter = pyloudnorm.Meter(mono.sample_rate)
        loudness = meter.integrated_loudness(mono.samples[0].astype(np.float64))
        if not np.isfinite(loudness):
            return 0.0
        return float(10 ** ((target_lufs - loudness) / 20))
