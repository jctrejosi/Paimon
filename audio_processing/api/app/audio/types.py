"""Tipos comunes de audio usados por todo el servicio."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Segment:
    """Tramo temporal con texto y/o hablante opcionales (segundos)."""

    start: float
    end: float
    text: str | None = None
    speaker: str | None = None


@dataclass
class AudioClip:
    """Audio en memoria: float32, forma (canales, muestras), rango [-1, 1]."""

    samples: np.ndarray
    sample_rate: int

    def __post_init__(self) -> None:
        samples = np.asarray(self.samples, dtype=np.float32)
        if samples.ndim == 1:
            samples = samples[np.newaxis, :]
        self.samples = samples
        self.sample_rate = round(self.sample_rate)

    @property
    def n_channels(self) -> int:
        return int(self.samples.shape[0])

    @property
    def n_samples(self) -> int:
        return int(self.samples.shape[1])

    @property
    def duration(self) -> float:
        return self.n_samples / self.sample_rate if self.sample_rate else 0.0

    def to_mono(self) -> AudioClip:
        """Mezcla todos los canales en uno (media). Devuelve el mismo si ya es mono."""
        if self.n_channels == 1:
            return self
        return AudioClip(self.samples.mean(axis=0), self.sample_rate)
