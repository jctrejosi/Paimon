"""Módulo `diarize`: ¿quién habla y cuándo? (pyannote.audio).

Requiere la dependencia opcional `pyannote.audio` y, para los modelos gated de
Hugging Face, un token en `HF_TOKEN`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.audio.types import AudioClip, Segment
from app.preprocessing.base import Processor, ProcessorError, ProcessorResult


class DiarizeParams(BaseModel):
    model: str = "pyannote/speaker-diarization-3.1"
    num_speakers: int | None = Field(default=None, ge=1)
    min_speakers: int | None = Field(default=None, ge=1)
    max_speakers: int | None = Field(default=None, ge=1)


class DiarizeProcessor(Processor):
    name = "diarize"
    description = "Diarización (pyannote): etiqueta el hablante de cada tramo."
    params_model = DiarizeParams
    required_packages = ("pyannote.audio",)

    def __init__(self, settings) -> None:
        super().__init__(settings)
        self._pipeline = None
        self._model_name: str | None = None

    def process(self, clip: AudioClip, params: DiarizeParams) -> ProcessorResult:
        import torch
        from pyannote.audio import Pipeline as PyannotePipeline

        if self._pipeline is None or self._model_name != params.model:
            self._pipeline = PyannotePipeline.from_pretrained(
                params.model, use_auth_token=self.settings.hf_token
            )
            self._model_name = params.model

        mono = clip.to_mono()
        waveform = torch.from_numpy(mono.samples.copy())  # (1, muestras)
        try:
            diarization = self._pipeline({"waveform": waveform, "sample_rate": mono.sample_rate})
        except Exception as exc:  # se reenvía como error del módulo
            raise ProcessorError(
                f"La diarización falló: {exc}", processor=self.name
            ) from exc

        segments = [
            Segment(start=turn.start, end=turn.end, speaker=str(speaker))
            for turn, _, speaker in diarization.itertracks(yield_label=True)
        ]
        return ProcessorResult(
            clips=[mono],
            segments=segments,
            metrics={
                "turns": len(segments),
                "speakers": len({segment.speaker for segment in segments}),
            },
        )
