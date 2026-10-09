"""Descubrimiento y acceso a los módulos de preprocesamiento."""

from __future__ import annotations

import importlib
import pkgutil

from ..config import Settings
from . import modules
from .base import Processor, ProcessorError, ProcessorUnavailableError


def _discover() -> dict[str, type[Processor]]:
    """Importa cada carpeta de `modules/` y recoge su atributo `PROCESSOR`."""
    found: dict[str, type[Processor]] = {}
    for info in pkgutil.iter_modules(modules.__path__):
        module = importlib.import_module(f"{modules.__name__}.{info.name}")
        processor = getattr(module, "PROCESSOR", None)
        if isinstance(processor, type) and issubclass(processor, Processor):
            found[processor.name] = processor
    return dict(sorted(found.items()))


PROCESSORS: dict[str, type[Processor]] = _discover()


def get_processor(name: str, settings: Settings) -> Processor:
    cls = PROCESSORS.get(name)
    if cls is None:
        raise ProcessorError(
            f"Módulo desconocido: '{name}'. Disponibles: {', '.join(PROCESSORS)}.",
            processor=name,
            status_code=404,
        )
    if not cls.available():
        raise ProcessorUnavailableError(name, cls.required_packages)
    return cls(settings)


def module_router(name: str):
    """Devuelve el APIRouter propio de un módulo (definido en su `router.py`)."""
    return importlib.import_module(f"{modules.__name__}.{name}.router").router
