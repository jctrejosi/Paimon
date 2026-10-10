"""Backend de diarización con pyannote.audio.

Mejor calidad, pero sus modelos están **gated** en Hugging Face: hay que aceptar
las condiciones en la página del modelo y definir `HF_TOKEN`.
"""

from __future__ import annotations

from typing import Any

from app.audio.types import AudioClip, Segment
from app.preprocessing.base import ProcessorError

from .base import DiarizationBackend, DiarizationResult


class PyannoteBackend(DiarizationBackend):
    name = "pyannote"
    description = "pyannote.audio (modelos gated: requiere aceptar condiciones y HF_TOKEN)."
    required_packages = ("pyannote.audio",)

    def __init__(self, settings) -> None:
        super().__init__(settings)
        self._pipeline = None
        self._model_name: str | None = None

    def _get_pipeline(self, model: str):
        from pyannote.audio import Pipeline as PyannotePipeline

        if self._pipeline is None or self._model_name != model:
            self._pipeline = PyannotePipeline.from_pretrained(
                model, use_auth_token=self.settings.hf_token
            )
            self._model_name = model
        return self._pipeline

    def diarize(self, clip: AudioClip, params: Any) -> DiarizationResult:
        import torch

        pipeline = self._get_pipeline(params.model)
        mono = clip.to_mono()
        waveform = torch.from_numpy(mono.samples.copy())  # (1, muestras)

        kwargs: dict[str, int] = {}
        if params.num_speakers:
            kwargs["num_speakers"] = params.num_speakers
        if params.min_speakers:
            kwargs["min_speakers"] = params.min_speakers
        if params.max_speakers:
            kwargs["max_speakers"] = params.max_speakers

        try:
            diarization = pipeline({"waveform": waveform, "sample_rate": mono.sample_rate}, **kwargs)
        except Exception as exc:  # se reenvía como error del módulo
            hint = ""
            if "gated" in str(exc).lower() or "token" in str(exc).lower():
                hint = (
                    " Revisa que aceptaste las condiciones del modelo en Hugging Face "
                    "y que HF_TOKEN está definido."
                )
            raise ProcessorError(
                f"La diarización con pyannote falló: {exc}.{hint}", processor="diarize/pyannote"
            ) from exc

        segments = [
            Segment(start=turn.start, end=turn.end, speaker=str(speaker))
            for turn, _, speaker in diarization.itertracks(yield_label=True)
        ]
        return DiarizationResult(
            segments=segments,
            metrics={
                "backend": self.name,
                "model": params.model,
                "turns": len(segments),
                "speakers": len({segment.speaker for segment in segments}),
            },
        )
