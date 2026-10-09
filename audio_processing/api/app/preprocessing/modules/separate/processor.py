"""Módulo `separate`: separación de fuentes con Demucs.

Útil cuando la voz convive con música u otras fuentes. Requiere la dependencia
opcional `demucs` (y `torch`).
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, Field

from app.audio.io import resample_samples
from app.audio.types import AudioClip
from app.preprocessing.base import Processor, ProcessorError, ProcessorResult

_EPS = 1e-8


class SeparateParams(BaseModel):
    model: str = "htdemucs"
    stems: list[str] = Field(default_factory=lambda: ["vocals"])


class SeparateProcessor(Processor):
    name = "separate"
    description = "Separa fuentes (Demucs): aísla la voz de la música u otras fuentes."
    params_model = SeparateParams
    required_packages = ("demucs",)

    def __init__(self, settings) -> None:
        super().__init__(settings)
        self._model = None
        self._model_name: str | None = None

    def process(self, clip: AudioClip, params: SeparateParams) -> ProcessorResult:
        import torch
        from demucs.apply import apply_model
        from demucs.pretrained import get_model

        if self._model is None or self._model_name != params.model:
            self._model = get_model(params.model)
            self._model.eval()
            self._model_name = params.model
        model = self._model

        target_rate = model.samplerate
        wav = clip.samples
        if wav.shape[0] == 1:  # Demucs trabaja en estéreo
            wav = np.repeat(wav, 2, axis=0)
        if wav.shape[0] > 2:
            wav = wav[:2]
        wav = resample_samples(wav, clip.sample_rate, target_rate)

        reference = wav.mean(axis=0)
        normalized = (wav - reference.mean()) / (reference.std() + _EPS)
        tensor = torch.from_numpy(np.ascontiguousarray(normalized))
        try:
            with torch.no_grad():
                sources = apply_model(model, tensor[None], device="cpu", progress=False)[0]
        except Exception as exc:  # se reenvía como error del módulo
            raise ProcessorError(
                f"Demucs falló al separar las fuentes: {exc}", processor=self.name
            ) from exc

        sources = sources * reference.std() + reference.mean()
        clips: list[AudioClip] = []
        found: list[str] = []
        for name, source in zip(model.sources, sources):
            if name not in params.stems:
                continue
            restored = resample_samples(source.cpu().numpy(), target_rate, clip.sample_rate)
            clips.append(AudioClip(restored, clip.sample_rate))
            found.append(name)

        if not clips:
            raise ProcessorError(
                f"Ninguna fuente solicitada existe en el modelo ({model.sources}).",
                processor=self.name,
                status_code=400,
            )
        return ProcessorResult(clips=clips, metrics={"stems": found})
