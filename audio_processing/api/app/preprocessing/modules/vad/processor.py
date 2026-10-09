"""Módulo `vad`: detección de actividad de voz con Silero (incluido en faster-whisper).

Recorta silencios (`trim`) o separa el audio en tramos de voz (`split`).
"""

from __future__ import annotations

from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from app.audio.io import resample_samples
from app.audio.types import AudioClip, Segment
from app.preprocessing.base import Processor, ProcessorResult

_VAD_RATE = 16000
_MIN_SAMPLES = 512


class VadParams(BaseModel):
    threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    min_speech_duration_ms: int = Field(default=250, ge=0)
    min_silence_duration_ms: int = Field(default=100, ge=0)
    speech_pad_ms: int = Field(default=200, ge=0)
    mode: Literal["trim", "split"] = "trim"


class VadProcessor(Processor):
    name = "vad"
    description = "Detecta voz (Silero) y recorta silencios o separa tramos."
    params_model = VadParams

    def process(self, clip: AudioClip, params: VadParams) -> ProcessorResult:
        mono = clip.to_mono()
        samples = mono.samples[0]
        if samples.size < _MIN_SAMPLES:
            return ProcessorResult(clips=[mono], metrics={"no_speech": True, "reason": "corto"})

        if mono.sample_rate != _VAD_RATE:
            samples = resample_samples(samples, mono.sample_rate, _VAD_RATE)

        from faster_whisper.vad import VadOptions, get_speech_timestamps

        options = VadOptions(
            threshold=params.threshold,
            min_speech_duration_ms=params.min_speech_duration_ms,
            min_silence_duration_ms=params.min_silence_duration_ms,
            speech_pad_ms=params.speech_pad_ms,
        )
        stamps = get_speech_timestamps(
            np.asarray(samples, dtype=np.float32), options, sampling_rate=_VAD_RATE
        )

        total = mono.n_samples
        speech = sum(st["end"] - st["start"] for st in stamps)
        metrics = {
            "speech_ratio": float(speech / total) if total else 0.0,
            "regions": len(stamps),
            "no_speech": not stamps,
        }

        if not stamps:
            # Sin voz detectada: devolvemos el audio original en vez de vaciarlo.
            return ProcessorResult(clips=[mono], metrics=metrics)

        rate_scale = mono.sample_rate / _VAD_RATE
        segments = [
            Segment(
                start=st["start"] * rate_scale / mono.sample_rate,
                end=st["end"] * rate_scale / mono.sample_rate,
            )
            for st in stamps
        ]

        regions = [self._slice(mono, seg) for seg in segments]
        if params.mode == "split":
            clips = regions
        else:
            clips = [AudioClip(np.concatenate([c.samples[0] for c in regions]), mono.sample_rate)]

        metrics["output_duration"] = sum(c.duration for c in clips)
        return ProcessorResult(clips=clips, segments=segments, metrics=metrics)

    @staticmethod
    def _slice(clip: AudioClip, segment: Segment) -> AudioClip:
        start = max(0, round(segment.start * clip.sample_rate))
        end = min(clip.n_samples, round(segment.end * clip.sample_rate))
        return AudioClip(clip.samples[:, start:end], clip.sample_rate)
