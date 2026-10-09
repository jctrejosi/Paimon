"""Módulo `decode`: conversión de formato a PCM.

Es el punto de entrada: convierte cualquier contenedor/códec soportado por
ffmpeg (ogg/opus, mp3, m4a, wav, flac, webm...) a PCM float32 en memoria.
Su API es útil por sí sola como "conversor de formatos".
"""

from __future__ import annotations

from app.audio.types import AudioClip
from app.preprocessing.base import EmptyParams, Processor, ProcessorResult


class DecodeParams(EmptyParams):
    """Sin parámetros."""


class DecodeProcessor(Processor):
    name = "decode"
    description = "Decodifica cualquier formato soportado a PCM/WAV (sin alterar el audio)."
    params_model = DecodeParams

    def process(self, clip: AudioClip, params: DecodeParams) -> ProcessorResult:
        return ProcessorResult(
            clips=[clip],
            metrics={
                "sample_rate": clip.sample_rate,
                "channels": clip.n_channels,
                "duration": clip.duration,
            },
        )
