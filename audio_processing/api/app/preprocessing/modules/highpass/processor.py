"""Módulo `highpass`: filtro paso-alto para quitar retumbe y componente continua."""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, Field
from scipy.signal import butter, sosfilt, sosfiltfilt

from app.audio.types import AudioClip
from app.preprocessing.base import Processor, ProcessorError, ProcessorResult


class HighpassParams(BaseModel):
    cutoff: float = Field(default=80.0, gt=0, description="Frecuencia de corte en Hz.")
    order: int = Field(default=4, ge=1, le=12, description="Orden del filtro Butterworth.")


class HighpassProcessor(Processor):
    name = "highpass"
    description = "Filtro paso-alto (Butterworth) para eliminar ruido de baja frecuencia."
    params_model = HighpassParams

    def process(self, clip: AudioClip, params: HighpassParams) -> ProcessorResult:
        nyquist = clip.sample_rate / 2
        if params.cutoff >= nyquist:
            raise ProcessorError(
                f"La frecuencia de corte ({params.cutoff} Hz) debe ser menor que Nyquist "
                f"({nyquist} Hz).",
                processor=self.name,
                status_code=400,
            )

        sos = butter(
            params.order, params.cutoff, btype="highpass", fs=clip.sample_rate, output="sos"
        )
        try:
            filtered = sosfiltfilt(sos, clip.samples, axis=-1)
        except ValueError:
            # Audio demasiado corto para el filtrado en fase cero.
            filtered = sosfilt(sos, clip.samples, axis=-1)

        return ProcessorResult(
            clips=[AudioClip(np.asarray(filtered, dtype=np.float32), clip.sample_rate)],
            metrics={"cutoff": params.cutoff, "order": params.order},
        )
