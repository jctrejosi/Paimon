"""Cálculo de WER (Word Error Rate) con normalización de texto.

La normalización quita mayúsculas, acentos y puntuación para comparar de forma
justa la referencia con la salida del ASR.
"""

from __future__ import annotations

import re
import unicodedata

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")
_DIACRITICS = ("Mn",)


def normalize(text: str) -> str:
    """Minúsculas, sin acentos, sin puntuación y con espacios colapsados."""
    lowered = text.lower()
    decomposed = unicodedata.normalize("NFD", lowered)
    without_accents = "".join(c for c in decomposed if unicodedata.category(c) not in _DIACRITICS)
    without_punct = _PUNCT.sub(" ", without_accents)
    return _SPACES.sub(" ", without_punct).strip()


def words(text: str) -> list[str]:
    normalized = normalize(text)
    return normalized.split() if normalized else []


def _levenshtein(reference: list[str], hypothesis: list[str]) -> int:
    """Distancia de edición a nivel de palabra."""
    if not reference:
        return len(hypothesis)
    if not hypothesis:
        return len(reference)

    previous = list(range(len(hypothesis) + 1))
    for i, ref_word in enumerate(reference, start=1):
        current = [i]
        for j, hyp_word in enumerate(hypothesis, start=1):
            cost = 0 if ref_word == hyp_word else 1
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            )
        previous = current
    return previous[-1]


def wer(reference: str, hypothesis: str) -> tuple[float, int, int]:
    """Devuelve (WER, errores, número de palabras de referencia)."""
    ref = words(reference)
    hyp = words(hypothesis)
    if not ref:
        return (0.0 if not hyp else 1.0), len(hyp), 0
    distance = _levenshtein(ref, hyp)
    return distance / len(ref), distance, len(ref)
