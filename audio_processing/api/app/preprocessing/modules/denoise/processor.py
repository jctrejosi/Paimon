"""Módulo `denoise`: reducción de ruido.

Backends:
- `spectral` (por defecto, sin dependencias extra): sustracción espectral con
  estimación del perfil de ruido a partir de las tramas de menor energía.
- `noisereduce` (opcional): implementación madura de *spectral gating*.
- `deepfilternet` (opcional): red neuronal de mejora de voz. Requiere
  `deepfilternet`, que a su vez necesita `deepfilterlib` (solo hay wheels hasta
  Python 3.11 o compilar con Rust).
"""

from __future__ import annotations

import importlib.util
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from app.audio.io import resample_samples
from app.audio.types import AudioClip
from app.preprocessing.base import (
    Processor,
    ProcessorError,
    ProcessorResult,
    ProcessorUnavailableError,
)

_EPS = 1e-10
_MIN_FLOOR = 0.02
_DFN_RATE = 48000


class DenoiseParams(BaseModel):
    backend: Literal["auto", "spectral", "noisereduce", "deepfilternet"] = Field(
        default="auto",
        description="'auto' usa el mejor backend instalado (noisereduce > spectral).",
    )
    strength: float = Field(default=1.0, ge=0.0, le=1.0, description="Cuánto ruido se resta.")
    n_fft: int = Field(default=1024, ge=128, le=8192)
    noise_percentile: float = Field(
        default=20.0, ge=1.0, le=50.0, description="Percentil de tramas más silenciosas."
    )
    stationary: bool = Field(
        default=True, description="(backend noisereduce) Asumir ruido estacionario."
    )


class DenoiseProcessor(Processor):
    name = "denoise"
    description = "Reduce ruido de fondo (sustracción espectral, noisereduce o DeepFilterNet)."
    params_model = DenoiseParams

    def __init__(self, settings) -> None:
        super().__init__(settings)
        self._dfn = None

    def process(self, clip: AudioClip, params: DenoiseParams) -> ProcessorResult:
        mono = clip.to_mono()
        if mono.n_samples < params.n_fft:
            return ProcessorResult(clips=[mono], metrics={"skipped": "audio demasiado corto"})

        backend = self._resolve_backend(params.backend)
        if backend == "deepfilternet":
            samples = self._deepfilternet(mono)
        elif backend == "noisereduce":
            samples = self._noisereduce(mono, params)
        else:
            samples = self._spectral(mono, params)

        return ProcessorResult(
            clips=[AudioClip(samples, mono.sample_rate)],
            metrics={
                "backend": backend,
                "strength": params.strength,
                "input_rms": float(np.sqrt(np.mean(np.square(mono.samples, dtype=np.float64)))),
                "output_rms": float(np.sqrt(np.mean(np.square(samples, dtype=np.float64)))),
            },
        )

    @staticmethod
    def _resolve_backend(backend: str) -> str:
        """Resuelve `auto` al mejor backend instalado."""
        if backend != "auto":
            return backend
        if importlib.util.find_spec("noisereduce") is not None:
            return "noisereduce"
        return "spectral"

    @staticmethod
    def _spectral(mono: AudioClip, params: DenoiseParams) -> np.ndarray:
        from scipy.signal import istft, stft

        x = mono.samples[0].astype(np.float64)
        nperseg = min(params.n_fft, x.size)
        _, _, spectrum = stft(x, fs=mono.sample_rate, nperseg=nperseg, noverlap=nperseg // 2)
        magnitude = np.abs(spectrum)
        phase = np.angle(spectrum)

        # Perfil de ruido: media de las tramas con menos energía.
        frame_energy = magnitude.sum(axis=0)
        cutoff = np.percentile(frame_energy, params.noise_percentile)
        noise_frames = magnitude[:, frame_energy <= cutoff]
        if noise_frames.size:
            noise_profile = noise_frames.mean(axis=1, keepdims=True)
        else:
            noise_profile = np.zeros((magnitude.shape[0], 1))

        mask = 1.0 - params.strength * (noise_profile / (magnitude + _EPS))
        floor = max(_MIN_FLOOR, 1.0 - params.strength)
        mask = np.clip(mask, floor, 1.0)

        _, restored = istft(
            mask * magnitude * np.exp(1j * phase),
            fs=mono.sample_rate,
            nperseg=nperseg,
            noverlap=nperseg // 2,
        )
        restored = np.asarray(restored, dtype=np.float32)[: x.size]
        if restored.size < x.size:  # rellenar por si el STFT recorta el final
            restored = np.pad(restored, (0, x.size - restored.size))
        return restored

    @staticmethod
    def _noisereduce(mono: AudioClip, params: DenoiseParams) -> np.ndarray:
        if importlib.util.find_spec("noisereduce") is None:
            raise ProcessorUnavailableError("denoise", ("noisereduce",))

        import noisereduce

        reduced = noisereduce.reduce_noise(
            y=mono.samples[0],
            sr=mono.sample_rate,
            stationary=params.stationary,
            prop_decrease=params.strength,
        )
        return np.asarray(reduced, dtype=np.float32)[: mono.n_samples]

    def _deepfilternet(self, mono: AudioClip) -> np.ndarray:
        if importlib.util.find_spec("df") is None:
            raise ProcessorUnavailableError(self.name, ("deepfilternet",))

        import torch
        from df.enhance import enhance, init_df

        if self._dfn is None:
            self._dfn = init_df()
        model, state, _ = self._dfn

        target_rate = state.sr() if hasattr(state, "sr") else _DFN_RATE
        resampled = resample_samples(mono.samples, mono.sample_rate, target_rate)
        tensor = torch.from_numpy(np.ascontiguousarray(resampled)).float()
        try:
            with torch.no_grad():
                enhanced = enhance(model, state, tensor)
        except Exception as exc:  # se reenvía como error del módulo
            raise ProcessorError(
                f"DeepFilterNet falló al procesar el audio: {exc}", processor=self.name
            ) from exc

        output = enhanced.detach().cpu().numpy()
        return resample_samples(output, target_rate, mono.sample_rate)
