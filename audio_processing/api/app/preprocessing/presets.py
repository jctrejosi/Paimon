"""Presets de encadenado de módulos."""

from __future__ import annotations

# Cada paso es (nombre del módulo, parámetros). El orden importa.
PRESETS: dict[str, list[tuple[str, dict]]] = {
    "raw": [],
    "minimal": [
        ("channels", {"mode": "mono"}),
        ("resample", {"sample_rate": 16000}),
        ("highpass", {"cutoff": 80.0}),
        ("normalize", {"mode": "peak", "target_db": -1.0}),
    ],
    "clean": [
        ("channels", {"mode": "mono"}),
        ("resample", {"sample_rate": 16000}),
        ("highpass", {"cutoff": 80.0}),
        ("normalize", {"mode": "peak", "target_db": -1.0}),
        ("vad", {}),
    ],
    "noisy": [
        ("channels", {"mode": "mono"}),
        ("denoise", {"backend": "auto", "strength": 1.0}),
        ("resample", {"sample_rate": 16000}),
        ("highpass", {"cutoff": 80.0}),
        ("normalize", {"mode": "peak", "target_db": -1.0}),
        ("vad", {}),
    ],
}


def preset_names() -> list[str]:
    return list(PRESETS)
