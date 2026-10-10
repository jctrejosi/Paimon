"""Verificación real del módulo de diarización (backend `ecapa`).

Construye un audio con **dos hablantes** (dos clips reales de LibriSpeech de
distinto `speaker_id`, separados por un silencio) y comprueba que la diarización
detecta 2 hablantes y encuentra el cambio de turno en el punto correcto.

Uso:
    python diarize_check.py [--limit-clips ...] [--backend ecapa|pyannote|auto]
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

API_DIR = Path(__file__).resolve().parents[1] / "api"
sys.path.insert(0, str(API_DIR))

from app.audio import decode_bytes, resample_samples  # noqa: E402
from app.audio.types import AudioClip  # noqa: E402
from app.config import Settings  # noqa: E402
from app.preprocessing.modules.diarize.backends import BACKENDS  # noqa: E402

ROWS_API = "https://datasets-server.huggingface.co/rows"
TARGET_RATE = 16000
SILENCE_S = 0.4


def fetch_rows(offset: int, limit: int) -> list[dict]:
    query = urllib.parse.urlencode(
        {
            "dataset": "openslr/librispeech_asr",
            "config": "clean",
            "split": "validation",
            "offset": offset,
            "length": limit,
        }
    )
    with urllib.request.urlopen(f"{ROWS_API}?{query}", timeout=120) as response:  # noqa: S310
        return [row["row"] for row in json.load(response).get("rows", [])]


def load_clip(row: dict, cache: Path, name: str) -> AudioClip:
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{name}.flac"
    if not path.exists():
        urllib.request.urlretrieve(row["audio"][0]["src"], path)  # noqa: S310
    clip = decode_bytes(path.read_bytes())
    return AudioClip(resample_samples(clip.to_mono().samples, clip.sample_rate, TARGET_RATE), TARGET_RATE)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verificación real de la diarización.")
    parser.add_argument("--backend", default="ecapa")
    parser.add_argument("--cache", type=Path, default=Path(__file__).parent / ".cache")
    args = parser.parse_args()

    cls = BACKENDS[args.backend]
    if not cls.available():
        print(f"Backend '{args.backend}' no disponible (requiere {cls.required_packages}).")
        return 1

    # Dos clips de hablantes distintos (LibriSpeech va ordenado por hablante,
    # así que hay que saltar de offset para encontrar otro).
    first: dict | None = None
    second: dict | None = None
    for offset in (0, 400, 1200, 2600, 5200):
        for row in fetch_rows(offset=offset, limit=40):
            speaker = row.get("speaker_id")
            if speaker is None:
                continue
            if first is None:
                first = row
            elif speaker != first["speaker_id"]:
                second = row
                break
        if second is not None:
            break

    if first is None or second is None:
        print("No se encontraron dos hablantes distintos en el dataset.")
        return 1
    speakers = (first["speaker_id"], second["speaker_id"])

    clip_a = load_clip(first, args.cache, "spk_a")
    clip_b = load_clip(second, args.cache, "spk_b")
    silence = np.zeros(int(SILENCE_S * TARGET_RATE), dtype=np.float32)

    combined = np.concatenate([clip_a.samples[0], silence, clip_b.samples[0]])
    boundary_s = clip_a.duration + SILENCE_S / 2
    conversation = AudioClip(combined, TARGET_RATE)
    print(
        f"Audio de prueba: {conversation.duration:.1f}s | "
        f"hablante A={speakers[0]} (0-{clip_a.duration:.1f}s) | "
        f"hablante B={speakers[1]} ({clip_a.duration + SILENCE_S:.1f}s-final) | "
        f"cambio real ≈ {boundary_s:.1f}s"
    )

    settings = Settings()
    backend = cls(settings)
    result = backend.diarize(conversation, _params(args.backend))

    print("\nTramos detectados:")
    for segment in result.segments:
        print(f"  {segment.start:6.2f}s - {segment.end:6.2f}s  {segment.speaker}")
    print("\nMétricas:", result.metrics)

    detected = sorted({segment.speaker for segment in result.segments})
    ok_speakers = len(detected) == 2
    change_points = [segment.start for segment in result.segments[1:]]
    ok_boundary = any(abs(point - boundary_s) < 1.5 for point in change_points)

    print(
        f"\nResultado: {len(detected)} hablantes detectados (esperado 2) → "
        f"{'OK' if ok_speakers else 'FALLO'}"
    )
    print(
        f"Cambio de turno detectado cerca de {boundary_s:.1f}s → "
        f"{'OK' if ok_boundary else 'FALLO'}"
    )
    return 0 if (ok_speakers and ok_boundary) else 1


def _params(backend: str):
    from app.preprocessing.modules.diarize.params import DiarizeParams

    return DiarizeParams(backend=backend, num_speakers=2)


if __name__ == "__main__":
    raise SystemExit(main())
