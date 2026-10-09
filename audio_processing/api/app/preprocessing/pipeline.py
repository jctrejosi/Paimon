"""Composición de módulos en un pipeline."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from pydantic import ValidationError

from ..audio.types import AudioClip, Segment
from ..config import Settings
from .base import ProcessorError
from .presets import PRESETS
from .registry import get_processor


@dataclass
class StepReport:
    name: str
    params: dict
    elapsed_ms: float
    clips: int
    metrics: dict = field(default_factory=dict)


@dataclass
class PipelineResult:
    clips: list[AudioClip] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    steps: list[StepReport] = field(default_factory=list)


def normalize_spec(spec: str | list) -> tuple[str | None, list[tuple[str, dict]]]:
    """Acepta un preset ('clean') o una lista de pasos y devuelve (preset, pasos).

    Formatos de paso admitidos:
      - "resample"                        (nombre suelto, sin parámetros)
      - {"name": "resample", "params": {...}}
      - {"resample": {"sample_rate": 8000}}
    """
    if isinstance(spec, str):
        name = spec.strip()
        if name not in PRESETS:
            raise ProcessorError(
                f"Preset desconocido: '{name}'. Disponibles: {', '.join(PRESETS)}.",
                processor="pipeline",
                status_code=400,
            )
        return name, list(PRESETS[name])

    steps: list[tuple[str, dict]] = []
    for item in spec:
        if isinstance(item, str):
            steps.append((item, {}))
        elif isinstance(item, dict):
            if "name" in item:
                steps.append((item["name"], item.get("params") or {}))
            elif len(item) == 1:
                (name, params), = item.items()
                steps.append((name, params or {}))
            else:
                raise ProcessorError(
                    f"Paso inválido: {item!r}.", processor="pipeline", status_code=400
                )
        else:
            raise ProcessorError(
                f"Paso inválido: {item!r}.", processor="pipeline", status_code=400
            )
    return None, steps


class Pipeline:
    """Encadena módulos: la salida de uno alimenta al siguiente."""

    def __init__(self, steps: list[tuple[str, dict]], settings: Settings) -> None:
        self.steps = steps
        self.settings = settings

    @classmethod
    def from_spec(cls, spec: str | list, settings: Settings) -> Pipeline:
        _, steps = normalize_spec(spec)
        return cls(steps, settings)

    def apply(self, clip: AudioClip) -> PipelineResult:
        current = [clip]
        result = PipelineResult(clips=current)
        for name, params in self.steps:
            processor = get_processor(name, self.settings)
            try:
                parsed = processor.params_model(**params)
            except ValidationError as exc:
                raise ProcessorError(
                    f"Parámetros inválidos para '{name}': {exc.errors()}",
                    processor=name,
                    status_code=422,
                ) from exc

            started = time.perf_counter()
            step = processor.process(current[0], parsed)
            elapsed_ms = (time.perf_counter() - started) * 1000

            result.steps.append(
                StepReport(
                    name=name,
                    params=parsed.model_dump(),
                    elapsed_ms=elapsed_ms,
                    clips=len(step.clips),
                    metrics=step.metrics,
                )
            )
            result.segments.extend(step.segments)
            if step.clips:
                current = step.clips

        result.clips = current
        return result
