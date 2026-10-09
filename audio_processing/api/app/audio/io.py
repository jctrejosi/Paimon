"""Entrada/salida de audio: decodificación (PyAV), codificación WAV y resampleo."""

from __future__ import annotations

import io
import wave

import numpy as np

from .types import AudioClip


def decode_bytes(data: bytes) -> AudioClip:
    """Decodifica bytes de cualquier formato soportado por ffmpeg/PyAV a `AudioClip`."""
    import av

    chunks: list[np.ndarray] = []
    sample_rate = 0

    with av.open(io.BytesIO(data), mode="r") as container:
        stream = next(iter(container.streams.audio), None)
        if stream is None:
            raise ValueError("El archivo no contiene ninguna pista de audio.")

        resampler = av.AudioResampler(format="flt")  # float32 entrelazado
        for frame in container.decode(stream):
            if not isinstance(frame, av.AudioFrame):
                continue
            for out in resampler.resample(frame):
                chunks.append(_to_array(out))
        for out in resampler.resample(None):  # vaciar el resampler
            chunks.append(_to_array(out))

        sample_rate = stream.codec_context.sample_rate

    if not chunks:
        raise ValueError("No se pudo decodificar audio del archivo.")

    samples = np.concatenate(chunks, axis=0).T  # (muestras, canales) -> (canales, muestras)
    return AudioClip(samples, int(sample_rate))


def _to_array(frame) -> np.ndarray:
    """Convierte una trama de PyAV a un array (muestras, canales)."""
    channels = frame.layout.nb_channels if frame.layout else 1
    return np.asarray(frame.to_ndarray()).reshape(frame.samples, channels)


def encode_wav(clip: AudioClip) -> bytes:
    """Codifica un `AudioClip` como WAV PCM de 16 bits."""
    pcm = (np.clip(clip.samples, -1.0, 1.0) * 32767.0).astype("<i2")
    interleaved = pcm.T  # (muestras, canales) para escribir entrelazado
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(clip.n_channels)
        writer.setsampwidth(2)
        writer.setframerate(clip.sample_rate)
        writer.writeframes(interleaved.tobytes())
    return buffer.getvalue()


def resample_samples(samples: np.ndarray, in_rate: int, out_rate: int) -> np.ndarray:
    """Remuestrea un array (canales, muestras) o (muestras,) usando soxr (fallback scipy)."""
    if in_rate == out_rate:
        return np.asarray(samples, dtype=np.float32)

    try:
        import soxr

        if samples.ndim == 1:
            return np.asarray(soxr.resample(samples, in_rate, out_rate), dtype=np.float32)
        return np.stack(
            [soxr.resample(channel, in_rate, out_rate) for channel in samples], axis=0
        ).astype(np.float32)
    except ImportError:
        from math import gcd

        from scipy.signal import resample_poly

        divisor = gcd(int(in_rate), int(out_rate))
        up, down = int(out_rate) // divisor, int(in_rate) // divisor
        axis = -1
        return np.asarray(
            resample_poly(samples, up, down, axis=axis), dtype=np.float32
        )
