"""Modelos de entrada/salida de la API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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


class ModelsResponse(BaseModel):
    default: str
    models: list[str]


class RemoveBgJsonResponse(BaseModel):
    """Respuesta de `/remove-bg` cuando `response_format=json`."""

    id: str
    provider: str
    model: str
    created: int
    mime_type: str
    width: int
    height: int
    elapsed_ms: int
    image_base64: str = Field(..., description="Imagen resultante codificada en base64.")
