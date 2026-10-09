"""Evalúa presets de preprocesamiento midiendo WER sobre el mini-set.

Para cada preset y cada audio del manifiesto: preprocesa, transcribe con el
motor local y calcula el WER contra la referencia. Imprime una tabla por
condición de ruido.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1] / "api"
sys.path.insert(0, str(API_DIR))

from app.audio import decode_bytes, encode_wav  # noqa: E402
from app.config import Settings  # noqa: E402
from app.preprocessing.pipeline import Pipeline  # noqa: E402
from app.providers.local_whisper import LocalWhisperProvider  # noqa: E402
from app.schemas import TranscribeRequest  # noqa: E402

from wer import wer  # noqa: E402

# "none" = sin preprocesar (comportamiento actual de /transcribe).
PRESETS = ["none", "minimal", "clean", "noisy"]


def load_manifest(data_dir: Path, limit: int = 0) -> list[dict]:
    items = [
        json.loads(line)
        for line in (data_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return items[:limit] if limit else items


async def evaluate(args: argparse.Namespace) -> int:
    items = load_manifest(args.data_dir, args.limit)
    if not items:
        print(f"No hay audios en {args.data_dir}. Ejecuta antes dataset.py.")
        return 1

    settings = Settings(
        local_whisper_model=args.model,
        whisper_model_dir=args.model_dir,
    )
    provider = LocalWhisperProvider(settings)
    pipelines = {
        preset: Pipeline.from_spec(preset, settings)
        for preset in args.presets
        if preset != "none"
    }

    conditions: list[str] = []
    for item in items:
        if item["condition"] not in conditions:
            conditions.append(item["condition"])

    scores: dict[tuple[str, str], list[float]] = {}
    for preset in args.presets:
        for item in items:
            audio_bytes = (args.data_dir / item["audio"]).read_bytes()
            started = time.perf_counter()
            if preset == "none":
                payload = audio_bytes
            else:
                cleaned = pipelines[preset].apply(decode_bytes(audio_bytes))
                payload = encode_wav(cleaned.clips[0])

            result = await provider.transcribe(
                TranscribeRequest(data=payload, filename=item["audio"], language=args.language)
            )
            elapsed = time.perf_counter() - started

            score, errors, total = wer(item["text"], result.text)
            scores.setdefault((preset, item["condition"]), []).append(score)
            if args.verbose:
                print(
                    f"[{preset:7} {item['condition']:5}] wer={score:.2f} "
                    f"({errors}/{total}) {elapsed:.1f}s :: {result.text!r}"
                )

    # Tabla resumen
    header = f"{'preset':8}" + "".join(f"{cond:>10}" for cond in conditions) + f"{'global':>10}"
    print("\n" + header)
    print("-" * len(header))
    for preset in args.presets:
        row = f"{preset:8}"
        all_scores: list[float] = []
        for cond in conditions:
            values = scores.get((preset, cond), [])
            all_scores.extend(values)
            row += f"{sum(values) / len(values):>10.3f}" if values else f"{'-':>10}"
        row += f"{sum(all_scores) / len(all_scores):>10.3f}" if all_scores else f"{'-':>10}"
        print(row)
    print("\nWER (menor es mejor). Condiciones: " + ", ".join(conditions))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Evalúa presets midiendo WER.")
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).parent / "data")
    parser.add_argument("--model", default="base")
    parser.add_argument("--model-dir", type=Path, default=API_DIR / "models")
    parser.add_argument("--language", default="es")
    parser.add_argument("--presets", default=",".join(PRESETS))
    parser.add_argument("--limit", type=int, default=0, help="Limita el nº de audios (0 = todos).")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    args.presets = [p.strip() for p in args.presets.split(",") if p.strip()]

    raise SystemExit(asyncio.run(evaluate(args)))


if __name__ == "__main__":
    main()
