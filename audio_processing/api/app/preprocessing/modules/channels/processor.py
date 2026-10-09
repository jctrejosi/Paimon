"""Módulo `channels`: conversión de canales."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.audio.types import AudioClip
from app.preprocessing.base import Processor, ProcessorResult


class ChannelsParams(BaseModel):
    mode: Literal["mono", "first"] = "mono"


class ChannelsProcessor(Processor):
    name = "channels"
    description = "Reduce a mono (media de canales) o toma el primer canal."
    params_model = ChannelsParams

    def process(self, clip: AudioClip, params: ChannelsParams) -> ProcessorResult:
        if clip.n_channels == 1:
            out = clip
        elif params.mode == "first":
            out = AudioClip(clip.samples[:1], clip.sample_rate)
        else:
            out = clip.to_mono()

        return ProcessorResult(
            clips=[out],
            metrics={"input_channels": clip.n_channels, "channels": out.n_channels},
        )
