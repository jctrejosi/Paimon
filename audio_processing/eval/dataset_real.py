"""Mini-set con **voz real** + variantes con ruido.

Trae N clips con transcripción conocida desde la API `datasets-server` de Hugging
Face (no requiere descargar el dataset completo). Al ser voz real, la línea base
en limpio debería dar un WER muy bajo: sirve para medir el efecto real del
preprocesamiento, sin artefactos de TTS.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

from dataset import CONDITIONS, add_noise, write_wav

API_DIR = Path(__file__).resolve().parents[1] / "api"
sys.path.insert(0, str(API_DIR))

from app.audio import decode_bytes, resample_samples  # noqa: E402

ROWS_API = "https://datasets-server.huggingface.co/rows"
TARGET_RATE = 16000
DEFAULT_DATASET = "openslr/librispeech_asr"


def fetch_rows(dataset: str, config: str, split: str, offset: int, limit: int) -> list[dict]:
    """Pide filas (audio + texto) a la API de datasets-server."""
    query = urllib.parse.urlencode(
        {
            "dataset": dataset,
            "config": config,
            "split": split,
            "offset": offset,
            "length": limit,
        }
    )
    with urllib.request.urlopen(f"{ROWS_API}?{query}", timeout=120) as response:  # noqa: S310
        payload = json.load(response)
    return [row["row"] for row in payload.get("rows", [])]


def download(url: str, path: Path) -> Path:
    if not path.exists():
        urllib.request.urlretrieve(url, path)  # noqa: S310 - URL de la API de HF
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Genera el mini-set con voz real.")
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--config", default="clean")
    parser.add_argument("--split", default="validation")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=6, help="Nº de clips reales.")
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "data_real")
    parser.add_argument("--cache", type=Path, default=Path(__file__).parent / ".cache")
    parser.add_argument("--seed", type=int, default=13)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    args.cache.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed)
    manifest: list[dict] = []

    for index, row in enumerate(
        fetch_rows(args.dataset, args.config, args.split, args.offset, args.limit), start=1
    ):
        source_path = download(row["audio"][0]["src"], args.cache / f"real_{index:02d}.flac")
        source = decode_bytes(source_path.read_bytes())
        mono = resample_samples(source.to_mono().samples, source.sample_rate, TARGET_RATE)

        for label, snr_db in CONDITIONS:
            audio = mono if snr_db is None else add_noise(mono, snr_db, rng)
            filename = f"real{index:02d}_{label}.wav"
            write_wav(args.out / filename, audio, TARGET_RATE)
            manifest.append(
                {
                    "audio": filename,
                    "text": row["text"],
                    "condition": label,
                    "snr_db": snr_db,
                    "sample_rate": TARGET_RATE,
                    "duration": round(np.size(audio) / TARGET_RATE, 3),
                }
            )

    (args.out / "manifest.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in manifest) + "\n",
        encoding="utf-8",
    )
    print(f"Generados {len(manifest)} audios reales en {args.out}")


if __name__ == "__main__":
    main()
