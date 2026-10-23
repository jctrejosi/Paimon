"""Modelos de entrada/salida de la API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SynthesizeRequest(BaseModel):
    """Entrada de una síntesis (texto → audio)."""

    text: str = Field(..., description="Texto a sintetizar.")
    voice_id: str | None = Field(
        default=None, description="Voz a usar; None = la del proveedor por defecto."
    )
    provider: str | None = Field(
        default=None, description="Proveedor; None = el configurado."
    )
    speed: float = Field(default=1.0, ge=0.25, le=4.0, description="Velocidad de habla.")
    format: Literal["wav", "pcm"] = Field(
        default="wav", description="Formato de salida de `/synthesize`."
    )


class Voice(BaseModel):
    """Una voz disponible para sintetizar."""

    voice_id: str
    name: str
    provider: str
    kind: Literal["builtin", "zero_shot", "finetuned"] = "builtin"
    model: str | None = None
    sample_rate: int = 24000
    language: str | None = None


class VoiceList(BaseModel):
    voices: list[Voice]


class ProviderInfo(BaseModel):
    name: str
    configured: bool
    default: bool = False
    model: str | None = None
    supports_cloning: bool = False


class ProvidersResponse(BaseModel):
    default_provider: str
    providers: list[ProviderInfo]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    default_provider: str
    configured_providers: list[str]
