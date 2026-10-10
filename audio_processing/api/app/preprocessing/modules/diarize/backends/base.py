"""Contrato común a los backends de diarización."""

from __future__ import annotations

import importlib.util
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from app.audio.types import AudioClip, Segment
from app.config import Settings


@dataclass
class DiarizationResult:
    """Tramos etiquetados por hablante y métricas del backend."""

    segments: list[Segment] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


class DiarizationBackend(ABC):
    """Un backend concreto de diarización.

    Debe ser barato de construir; los modelos se cargan de forma perezosa.
    """

    name: ClassVar[str]
    description: ClassVar[str] = ""
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
                return False
        return True

    @abstractmethod
    def diarize(self, clip: AudioClip, params: Any) -> DiarizationResult:
        """Devuelve los tramos con `speaker` asignado."""
