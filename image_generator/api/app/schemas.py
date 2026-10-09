"""Modelos de entrada/salida de la API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ResponseFormat = Literal["url", "b64_json"]


class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="Descripción de la imagen a generar.")
    negative_prompt: str | None = Field(
        default=None, description="Lo que no debe aparecer (solo aplicable a ComfyUI/difusión)."
    )
    provider: str | None = Field(
        default=None, description="Proveedor a usar; si se omite, se usa el configurado por defecto."
    )
    model: str | None = Field(
        default=None, description="Modelo/checkpoint específico; por defecto el del proveedor."
    )
    count: int = Field(default=1, ge=1, le=8, description="Número de imágenes a generar.")
    width: int = Field(default=1024, ge=64, le=4096, description="Ancho en píxeles.")
    height: int = Field(default=1024, ge=64, le=4096, description="Alto en píxeles.")
    steps: int | None = Field(default=None, ge=1, le=150, description="Pasos de muestreo.")
    guidance_scale: float | None = Field(
        default=None, ge=0.0, le=30.0, description="CFG / escala de guiado."
    )
    seed: int | None = Field(default=None, description="Semilla; None = aleatoria.")
    response_format: ResponseFormat = Field(
        default="url", description="'url' (archivo servido por la API) o 'b64_json' inline."
    )
    extra: dict[str, Any] = Field(
        default_factory=dict, description="Parámetros específicos del proveedor (escape hatch)."
    )


class GenerateImage(BaseModel):
    b64_json: str | None = None
    url: str | None = None
    mime_type: str = "image/png"
    seed: int | None = None
    revised_prompt: str | None = None


class GenerateResponse(BaseModel):
    id: str
    provider: str
    model: str | None = None
    created: int
    images: list[GenerateImage]
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderInfo(BaseModel):
    name: str
    configured: bool
    default: bool = False
    model: str | None = None


class ProvidersResponse(BaseModel):
    default_provider: str
    providers: list[ProviderInfo]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    default_provider: str
    configured_providers: list[str]
