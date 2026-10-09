"""Módulo `dereverb`: supresión de reverberación tardía con WPE.

Requiere la dependencia opcional `nara_wpe`. Útil en grabaciones con sala/eco;
en notas de voz limpias suele aportar poco.
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, Field

from app.audio.types import AudioClip
from app.preprocessing.base import Processor, ProcessorError, ProcessorResult

_NPERSEG = 512
_NOVERLAP = 256


class DereverbParams(BaseModel):
    taps: int = Field(default=10, ge=1, le=64, description="Longitud del filtro WPE.")
    delay: int = Field(default=3, ge=1, le=16, description="Retardo de predicción en tramas.")
    iterations: int = Field(default=3, ge=1, le=10)


class DereverbProcessor(Processor):
    name = "dereverb"
    description = "Suprime reverberación tardía (WPE) para 'secar' la voz."
    params_model = DereverbParams
    required_packages = ("nara_wpe",)

    def process(self, clip: AudioClip, params: DereverbParams) -> ProcessorResult:
        from nara_wpe.wpe import wpe
        from scipy.signal import istft, stft

        mono = clip.to_mono()
        samples = mono.samples[0]
        if samples.size <= _NPERSEG:
            return ProcessorResult(
                clips=[mono], metrics={"skipped": "audio demasiado corto para WPE"}
            )

        _, _, spectrum = stft(samples, nperseg=_NPERSEG, noverlap=_NOVERLAP)  # (F, T)
        # WPE espera (canales, tramas, frecuencias).
        signal = spectrum.T[np.newaxis].astype(np.complex128)

        try:
            processed = wpe(
                signal, taps=params.taps, delay=params.delay, iterations=params.iterations
            )
        except Exception as exc:  # se reenvía como error del módulo
            raise ProcessorError(f"WPE falló al procesar el audio: {exc}", processor=self.name) from exc

        _, restored = istft(processed[0].T, nperseg=_NPERSEG, noverlap=_NOVERLAP)
        restored = np.asarray(restored, dtype=np.float32)[: samples.size]
        if restored.size < samples.size:  # rellenar por si el STFT recorta el final
            restored = np.pad(restored, (0, samples.size - restored.size))

        return ProcessorResult(
            clips=[AudioClip(restored, mono.sample_rate)],
            metrics={
                "taps": params.taps,
                "delay": params.delay,
                "iterations": params.iterations,
            },
        )
