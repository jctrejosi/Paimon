"""Síntesis de voz con espeak-ng vía ctypes (sin depender del binario CLI).

Permite generar audio con **transcripción conocida** para medir WER. Requiere la
librería compartida `libespeak-ng` (habitual en Linux); si no está, las funciones
lanzan `RuntimeError` con un mensaje claro.
"""

from __future__ import annotations

import ctypes
from ctypes import CFUNCTYPE, POINTER, c_char_p, c_int, c_short, c_size_t, c_uint, c_void_p

import numpy as np

# Constantes de espeak-ng (speak_lib.h)
_AUDIO_OUTPUT_SYNCHRONOUS = 2
_ESPEAK_CHARS_UTF8 = 1
_ESPEAK_RATE = 1
_ESPEAK_VOLUME = 2

_LIB_NAMES = ("libespeak-ng.so.1", "libespeak-ng.so", "libespeak.so.1")

_lib = None
_lib_error: str | None = None


def _load():
    """Carga libespeak-ng y declara las firmas de las funciones que usamos."""
    global _lib, _lib_error
    if _lib is not None or _lib_error is not None:
        return _lib

    last_error = ""
    for name in _LIB_NAMES:
        try:
            lib = ctypes.CDLL(name)
        except OSError as exc:  # pragma: no cover - depende del sistema
            last_error = str(exc)
            continue

        lib.espeak_Initialize.argtypes = [c_int, c_int, c_char_p, c_int]
        lib.espeak_Initialize.restype = c_int
        callback_type = CFUNCTYPE(c_int, POINTER(c_short), c_int, c_void_p)
        lib.espeak_SetSynthCallback.argtypes = [callback_type]
        lib.espeak_SetSynthCallback.restype = c_int
        lib.espeak_SetVoiceByName.argtypes = [c_char_p]
        lib.espeak_SetVoiceByName.restype = c_int
        lib.espeak_SetParameter.argtypes = [c_int, c_int, c_int]
        lib.espeak_SetParameter.restype = c_int
        lib.espeak_Synth.argtypes = [
            c_char_p,
            c_size_t,
            c_uint,
            c_int,
            c_uint,
            c_uint,
            POINTER(c_uint),
            c_void_p,
        ]
        lib.espeak_Synth.restype = c_int
        _lib = (lib, callback_type)
        return _lib

    _lib_error = (
        "No se encontró la librería espeak-ng "
        f"({', '.join(_LIB_NAMES)}). Último error: {last_error}"
    )
    raise RuntimeError(_lib_error)


def available() -> bool:
    """Indica si espeak-ng está disponible."""
    try:
        _load()
    except RuntimeError:
        return False
    return True


def synthesize(text: str, voice: str = "es", rate: int = 150, volume: int = 100):
    """Sintetiza `text` y devuelve (muestras float32 mono, sample_rate)."""
    lib, callback_type = _load()

    sample_rate = lib.espeak_Initialize(_AUDIO_OUTPUT_SYNCHRONOUS, 0, None, 0)
    if sample_rate <= 0:
        raise RuntimeError("espeak_Initialize falló.")

    chunks: list[bytes] = []

    def _callback(wav, count, _events):
        if count > 0 and wav:
            chunks.append(ctypes.string_at(wav, count * ctypes.sizeof(c_short)))
        return 0

    callback = callback_type(_callback)
    lib.espeak_SetSynthCallback(callback)
    if lib.espeak_SetVoiceByName(voice.encode("utf-8")) != 0:
        raise RuntimeError(f"Voz de espeak-ng no disponible: {voice!r}")
    lib.espeak_SetParameter(_ESPEAK_RATE, int(rate), 0)
    lib.espeak_SetParameter(_ESPEAK_VOLUME, int(volume), 0)

    code = lib.espeak_Synth(text.encode("utf-8"), 0, 0, _ESPEAK_CHARS_UTF8, 0, 0, None, None)
    lib.espeak_SetSynthCallback(callback_type())  # limpia el callback

    if code != 0:
        raise RuntimeError(f"espeak_Synth devolvió el código {code}.")

    pcm = b"".join(chunks)
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    return samples, int(sample_rate)
