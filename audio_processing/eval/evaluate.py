"""Evalúa variantes de preprocesamiento midiendo WER sobre un mini-set.

Para cada variante y cada audio del manifiesto: preprocesa, transcribe con el
motor local y calcula el WER contra la referencia. Imprime una tabla por
condición de ruido.

Las variantes se definen en `variants.json`:
  - `null`      → sin preprocesar (bytes originales)
  - `"clean"`   → nombre de un preset de la app
  - `[ ... ]`   → lista de pasos (mismo formato que `POST /preprocess`)
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
from app.preprocessing.base import ProcessorError  # noqa: E402
from app.preprocessing.pipeline import Pipeline  # noqa: E402
from app.providers.local_whisper import LocalWhisperProvider  # noqa: E402
from app.schemas import TranscribeRequest  # noqa: E402

from wer import wer  # noqa: E402

DEFAULT_VARIANTS_FILE = Path(__file__).parent / "variants.json"
FALLBACK_VARIANTS: dict[str, object] = {
    "none": None,
    "minimal": "minimal",
    "clean": "clean",
    "noisy": "noisy",
}


def load_variants(path: Path) -> dict:
    if not path.exists():
        return dict(FALLBACK_VARIANTS)
    return json.loads(path.read_text(encoding="utf-8"))


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
        print(f"No hay audios en {args.data_dir}. Ejecuta antes dataset.py / dataset_real.py.")
        return 1

    variants = load_variants(args.variants_file)
    unknown = [name for name in args.variants if name not in variants]
    if unknown:
        print(f"Variantes desconocidas: {unknown}. Disponibles: {sorted(variants)}")
        return 1

    settings = Settings(local_whisper_model=args.model, whisper_model_dir=args.model_dir)
    provider = LocalWhisperProvider(settings)

    pipelines: dict[str, Pipeline | None] = {}
    for name in args.variants:
        spec = variants[name]
        pipelines[name] = None if spec is None else Pipeline.from_spec(spec, settings)

    conditions: list[str] = []
    for item in items:
        if item["condition"] not in conditions:
            conditions.append(item["condition"])

    scores: dict[tuple[str, str], list[float]] = {}
    failed: set[str] = set()
    for name in args.variants:
        pipeline = pipelines[name]
        for item in items:
            audio_bytes = (args.data_dir / item["audio"]).read_bytes()
            started = time.perf_counter()
            try:
                if pipeline is None:
                    payload = audio_bytes
                else:
                    cleaned = pipeline.apply(decode_bytes(audio_bytes))
                    payload = encode_wav(cleaned.clips[0])
            except ProcessorError as exc:
                print(f"[{name}] no disponible: {exc}")
                failed.add(name)
                break

            result = await provider.transcribe(
                TranscribeRequest(
                    data=payload,
                    filename=item["audio"],
                    language=args.language,
                    vad=args.vad,
                    beam_size=args.beam_size,
                    condition_on_previous_text=args.condition_on_previous_text,
                    initial_prompt=args.initial_prompt,
                )
            )
            elapsed = time.perf_counter() - started

            score, errors, total = wer(item["text"], result.text)
            scores.setdefault((name, item["condition"]), []).append(score)
            if args.verbose:
                print(
                    f"[{name:18} {item['condition']:5}] wer={score:.3f} "
                    f"({errors}/{total}) {elapsed:.1f}s :: {result.text!r}"
                )

    header = f"{'variante':20}" + "".join(f"{cond:>10}" for cond in conditions) + f"{'global':>10}"
    print("\n" + header)
    print("-" * len(header))
    for name in args.variants:
        row = f"{name:20}"
        all_scores: list[float] = []
        for cond in conditions:
            values = scores.get((name, cond), [])
            all_scores.extend(values)
            row += f"{sum(values) / len(values):>10.3f}" if values else f"{'-':>10}"
        if name in failed:
            row += f"{'FAIL':>10}"
        else:
            row += f"{sum(all_scores) / len(all_scores):>10.3f}" if all_scores else f"{'-':>10}"
        print(row)
    print("\nWER (menor es mejor). Condiciones: " + ", ".join(conditions))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Evalúa variantes de preprocesamiento midiendo WER.")
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).parent / "data_real")
    parser.add_argument("--variants-file", type=Path, default=DEFAULT_VARIANTS_FILE)
    parser.add_argument("--model", default="base")
    parser.add_argument("--model-dir", type=Path, default=API_DIR / "models")
    parser.add_argument("--language", default="es")
    parser.add_argument(
        "--variants",
        default="none,minimal,clean,noisy",
        help="Nombres de variantes a evaluar (ver variants.json).",
    )
    parser.add_argument("--limit", type=int, default=0, help="Limita el nº de audios (0 = todos).")
    parser.add_argument("--verbose", action="store_true")
    # Parámetros de decodificación (por defecto igual que un decoder "crudo").
    parser.add_argument(
        "--vad", dest="vad", action="store_true", help="Activar VAD en la decodificación."
    )
    parser.add_argument(
        "--no-vad", dest="vad", action="store_false", help="Desactivar VAD (default)."
    )
    parser.set_defaults(vad=False)
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument("--condition-on-previous-text", action="store_true")
    parser.add_argument("--initial-prompt", default=None)
    args = parser.parse_args()
    args.variants = [name.strip() for name in args.variants.split(",") if name.strip()]

    raise SystemExit(asyncio.run(evaluate(args)))


if __name__ == "__main__":
    main()
