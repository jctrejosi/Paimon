"""Modelos de entrada/salida de la API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TranscribeRequest(BaseModel):
    """Entrada interna hacia un proveedor (ya resuelta por la API)."""

    data: bytes = Field(..., description="Contenido del archivo de audio.")
    filename: str | None = Field(default=None, description="Nombre original del archivo.")
    content_type: str | None = Field(default=None, description="MIME declarado por el cliente.")
    language: str | None = Field(
        default=None,
        description="Código ISO-639-1 forzado; None = autodetección.",
    )
    model: str | None = Field(default=None, description="Modelo específico del proveedor.")
    verbose: bool = Field(default=False, description="Incluir segmentos con marcas de tiempo.")


class SegmentOut(BaseModel):
    start: float
    end: float
    text: str


class TranscribeResponse(BaseModel):
    id: str
    provider: str
    model: str | None = None
    created: int
    text: str
    language: str | None = None
    language_probability: float | None = None
    duration: float | None = None
    segments: list[SegmentOut] = Field(default_factory=list)


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
