"""Construye el mini-set de evaluación: voz sintética + variantes con ruido.

Genera un WAV por (frase, condición de ruido) y un `manifest.jsonl` con la
transcripción de referencia (verdad-terreno).
"""

from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path

import numpy as np

from tts import synthesize

# Frases con texto conocido. Estilo parecido a un mensaje de voz de WhatsApp.
SENTENCES = [
    "Hola, ¿me puedes decir a qué hora abre la tienda mañana?",
    "Necesito confirmar la reserva para dos personas el viernes por la noche.",
    "El paquete llegó ayer pero la caja estaba un poco dañada.",
    "Recuerda enviar el informe antes de las cinco de la tarde.",
    "No entiendo muy bien cómo funciona este nuevo sistema de facturación.",
    "¿Podrías repetir la dirección completa, por favor?",
    "Estuvimos hablando con el técnico y nos explicó el problema con detalle.",
    "Mañana tenemos una reunión importante con el equipo de desarrollo.",
]

# Condiciones: (etiqueta, SNR en dB). None = sin ruido añadido.
CONDITIONS = [("clean", None), ("snr15", 15.0), ("snr5", 5.0)]


def pink_noise(size: int, rng: np.random.Generator) -> np.ndarray:
    """Ruido rosa (1/f): más parecido al ruido de fondo real que el blanco."""
    white = rng.standard_normal(size)
    spectrum = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(size, 1.0)
    shape = np.ones_like(freqs)
    shape[1:] = 1.0 / np.sqrt(freqs[1:])
    shape[0] = 0.0
    return np.fft.irfft(spectrum * shape, size)


def add_noise(signal: np.ndarray, snr_db: float, rng: np.random.Generator) -> np.ndarray:
    """Mezcla ruido rosa a la relación señal/ruido indicada (en dB)."""
    noise = pink_noise(signal.size, rng)
    signal_power = float(np.mean(np.square(signal)))
    noise_power = float(np.mean(np.square(noise)))
    if signal_power <= 0 or noise_power <= 0:
        return signal.astype(np.float32)
    scaled = noise * np.sqrt(signal_power / (10 ** (snr_db / 10.0)) / noise_power)
    mixed = signal + scaled
    peak = float(np.max(np.abs(mixed)))
    if peak > 1.0:  # evitar clipping
        mixed = mixed / peak
    return mixed.astype(np.float32)


def write_wav(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim == 2 and samples.shape[0] == 1:  # (1, n) -> (n,)
        samples = samples[0]
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(pcm.tobytes())


def main() -> None:
    parser = argparse.ArgumentParser(description="Genera el mini-set de evaluación.")
    parser.add_argument("--out", type=Path, default=Path(__file__).parent / "data")
    parser.add_argument("--voice", default="es")
    parser.add_argument("--rate", type=int, default=110, help="Velocidad de habla (menor = más inteligible para el ASR).")
    parser.add_argument("--seed", type=int, default=13)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed)
    manifest: list[dict] = []

    for index, sentence in enumerate(SENTENCES, start=1):
        samples, sample_rate = synthesize(sentence, voice=args.voice, rate=args.rate)
        for label, snr_db in CONDITIONS:
            audio = samples if snr_db is None else add_noise(samples, snr_db, rng)
            filename = f"s{index:02d}_{label}.wav"
            write_wav(args.out / filename, audio, sample_rate)
            manifest.append(
                {
                    "audio": filename,
                    "text": sentence,
                    "condition": label,
                    "snr_db": snr_db,
                    "sample_rate": sample_rate,
                    "duration": round(len(audio) / sample_rate, 3),
                }
            )

    manifest_path = args.out / "manifest.jsonl"
    manifest_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in manifest) + "\n",
        encoding="utf-8",
    )
    print(f"Generados {len(manifest)} audios en {args.out}")
    print(f"Manifiesto: {manifest_path}")


if __name__ == "__main__":
    main()
