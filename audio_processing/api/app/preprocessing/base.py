"""Contrato común a todos los módulos de preprocesamiento."""

from __future__ import annotations

import importlib.util
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from pydantic import BaseModel

from ..audio.types import AudioClip, Segment
from ..config import Settings


class ProcessorError(RuntimeError):
    """Error de un módulo concreto (parámetros, audio inválido, fallo interno)."""

    def __init__(self, message: str, *, processor: str, status_code: int = 502):
        super().__init__(message)
        self.processor = processor
        self.status_code = status_code


class ProcessorUnavailableError(ProcessorError):
    """El módulo existe pero le faltan dependencias opcionales."""

    def __init__(self, processor: str, packages: tuple[str, ...]):
        super().__init__(
            f"El módulo '{processor}' requiere: {', '.join(packages)} (no instalado).",
            processor=processor,
            status_code=503,
        )


class EmptyParams(BaseModel):
    """Parámetros por defecto (módulos sin opciones)."""


@dataclass
class ProcessorResult:
    """Salida de un módulo: clips resultantes, tramos y métricas."""

    clips: list[AudioClip] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


class Processor(ABC):
    """Un módulo de preprocesamiento: consume y produce `AudioClip`.

    Debe ser barato de construir; los modelos pesados se cargan de forma perezosa.
    """

    name: ClassVar[str]
    description: ClassVar[str] = ""
    params_model: ClassVar[type[BaseModel]] = EmptyParams
    # Paquetes opcionales; si falta alguno, el módulo se reporta como no disponible.
    required_packages: ClassVar[tuple[str, ...]] = ()

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @classmethod
    def available(cls) -> bool:
        for package in cls.required_packages:
            try:
                if importlib.util.find_spec(package) is None:
                    return False
            except (ImportError, ValueError):
                # El paquete padre no existe (p. ej. "pyannote.audio" sin "pyannote").
                return False
        return True

    @abstractmethod
    def process(self, clip: AudioClip, params: Any) -> ProcessorResult:
        """Aplica el módulo y devuelve el resultado.

        Cada implementación declara el tipo concreto de sus parámetros
        (`params: MiParams`).
        """
