"""Parámetros del módulo de diarización (compartidos por todos los backends)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DiarizeParams(BaseModel):
    backend: Literal["auto", "pyannote", "ecapa"] = Field(
        default="auto",
        description="Backend a usar. 'auto' prefiere pyannote si está instalado; si no, 'ecapa'.",
    )

    # --- backend `pyannote` (modelos gated: requiere HF_TOKEN) ---
    model: str = Field(
        default="pyannote/speaker-diarization-3.1", description="(pyannote) Modelo a usar."
    )
    num_speakers: int | None = Field(default=None, ge=1, description="Nº exacto de hablantes.")
    min_speakers: int | None = Field(default=None, ge=1)
    max_speakers: int | None = Field(default=None, ge=1)

    # --- backend `ecapa` (speechbrain, sin credenciales) ---
    ecapa_model: str = Field(
        default="speechbrain/spkrec-ecapa-voxceleb",
        description="(ecapa) Modelo de embeddings de hablante.",
    )
    threshold: float = Field(
        default=0.5,
        gt=0.0,
        le=1.5,
        description="(ecapa) Distancia coseno por encima de la cual se separan hablantes.",
    )
    max_chunk_s: float = Field(
        default=1.5, gt=0.5, le=10.0, description="(ecapa) Duración máxima de cada tramo analizado."
    )
    min_chunk_s: float = Field(
        default=0.5, gt=0.1, le=5.0, description="(ecapa) Duración mínima de cada tramo analizado."
    )
