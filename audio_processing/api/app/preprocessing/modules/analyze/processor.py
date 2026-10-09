"""Módulo `analyze`: métricas de calidad del audio.

No transforma el audio (lo devuelve tal cual). Sirve para **decidir** qué aplicar
(por ejemplo, si conviene un denoise) y para diagnosticar audios problemáticos.
"""

from __future__ import annotations

import numpy as np

from app.audio.types import AudioClip
from app.preprocessing.base import EmptyParams, Processor, ProcessorResult

_EPS = 1e-12
_BANDS_HZ = ((0, 300), (300, 1000), (1000, 3000), (3000, 8000), (8000, 24000))


class AnalyzeParams(EmptyParams):
    """Sin parámetros."""


class AnalyzeProcessor(Processor):
    name = "analyze"
    description = "Métricas de calidad (nivel, pico, clipping, DC, silencio, bandas y SNR)."
    params_model = AnalyzeParams

    def process(self, clip: AudioClip, params: AnalyzeParams) -> ProcessorResult:
        mono = clip.to_mono().samples[0]
        peak = float(np.max(np.abs(mono))) if mono.size else 0.0
        rms = float(np.sqrt(np.mean(np.square(mono, dtype=np.float64)))) if mono.size else 0.0
        dc_offset = float(np.mean(mono)) if mono.size else 0.0
        clipping_ratio = float(np.mean(np.abs(mono) >= 0.999)) if mono.size else 0.0

        silence_ratio, snr_db = self._frame_stats(mono, clip.sample_rate)

        metrics = {
            "duration": clip.duration,
            "sample_rate": clip.sample_rate,
            "channels": clip.n_channels,
            "samples": clip.n_samples,
            "peak": peak,
            "peak_db": self._db(peak),
            "rms": rms,
            "rms_db": self._db(rms),
            "dc_offset": dc_offset,
            "clipping_ratio": clipping_ratio,
            "silence_ratio": silence_ratio,
            "estimated_snr_db": snr_db,
            "spectral_centroid_hz": self._spectral_centroid(mono, clip.sample_rate),
            "band_energy_ratio": self._band_energies(mono, clip.sample_rate),
        }
        return ProcessorResult(clips=[clip], metrics=metrics)

    @staticmethod
    def _db(value: float) -> float:
        return float(20 * np.log10(value + _EPS))

    @staticmethod
    def _frame_stats(mono: np.ndarray, sample_rate: int) -> tuple[float, float]:
        frame = max(1, int(0.02 * sample_rate))  # tramas de 20 ms
        n_frames = mono.size // frame
        if n_frames < 2:
            return 0.0, 0.0
        frames = mono[: n_frames * frame].reshape(n_frames, frame)
        frame_db = 20 * np.log10(np.sqrt(np.mean(np.square(frames, dtype=np.float64))) + _EPS)
        silence_ratio = float(np.mean(frame_db < -40.0))
        snr_db = float(np.percentile(frame_db, 95) - np.percentile(frame_db, 10))
        return silence_ratio, snr_db

    @staticmethod
    def _spectral_centroid(mono: np.ndarray, sample_rate: int) -> float:
        if mono.size < 2:
            return 0.0
        spectrum = np.abs(np.fft.rfft(mono))
        freqs = np.fft.rfftfreq(mono.size, 1.0 / sample_rate)
        total = spectrum.sum()
        return float((freqs * spectrum).sum() / total) if total > 0 else 0.0

    @staticmethod
    def _band_energies(mono: np.ndarray, sample_rate: int) -> dict[str, float]:
        if mono.size < 2:
            return {}
        power = np.abs(np.fft.rfft(mono)) ** 2
        freqs = np.fft.rfftfreq(mono.size, 1.0 / sample_rate)
        nyquist = sample_rate / 2
        total = power.sum()
        ratios: dict[str, float] = {}
        for low, high in _BANDS_HZ:
            if low >= nyquist:
                continue
            high = min(high, nyquist)
            mask = (freqs >= low) & (freqs < high)
            ratios[f"{low}-{int(high)}"] = float(power[mask].sum() / total) if total > 0 else 0.0
        return ratios
