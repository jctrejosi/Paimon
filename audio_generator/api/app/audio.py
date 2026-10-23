"""Utilidades de audio: conversión de muestras y empaquetado WAV."""

from __future__ import annotations

import io
import wave

import numpy as np


def samples_to_pcm(samples: np.ndarray, bits: int = 16) -> np.ndarray:
    """Convierte muestras a PCM entero (int16 por defecto).

    Acepta tanto float32 en [-1, 1] (la salida típica de Kokoro) como enteros ya
    en PCM, para no depender del dtype concreto del motor.
    """
    arr = np.asarray(samples)
    if np.issubdtype(arr.dtype, np.integer):
        return arr.astype("<i2")
    max_val = float(2 ** (bits - 1) - 1)
    return (np.clip(arr.astype(np.float32), -1.0, 1.0) * max_val).astype("<i2")


def pcm_to_wav(pcm: bytes, sample_rate: int, channels: int = 1) -> bytes:
    """Envuelve PCM int16 mono en un contenedor WAV."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(pcm)
    return buffer.getvalue()
