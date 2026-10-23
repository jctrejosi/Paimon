"""Proveedor local basado en Kokoro-82M (StyleTTS 2), pensado para CPU.

Kokoro es un modelo TTS de 82M parámetros que corre en tiempo real en CPU (RTF < 1
incluso en equipos modestos). El modelo se carga una sola vez (perezoso) y
permanece en memoria. Como la inferencia es bloqueante y consume CPU, se serializa
con un lock y se saca del event loop con `asyncio.to_thread`.

Kokoro no clona voces: expone un conjunto de voces fijas por idioma.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import numpy as np

from ..audio import pcm_to_wav, samples_to_pcm
from ..config import Settings
from ..schemas import SynthesizeRequest, Voice
from .base import AudioChunk, SynthesisResult, TTSProviderError, TTSSynthesizer

# Voces integradas de Kokoro por idioma (`lang_code`). Para español hay 3 voces.
# Ver: https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md
KOKORO_VOICES: dict[str, list[tuple[str, str]]] = {
    "e": [("ef_dora", "Dora"), ("em_alex", "Alex"), ("em_santa", "Santa")],
}


class KokoroProvider(TTSSynthesizer):
    name = "kokoro"
    supports_cloning = False

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        # Un pipeline por idioma (se cargan bajo demanda y se cachean).
        self._pipelines: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def is_configured(cls, settings: Settings) -> bool:
        # El motor local no requiere credenciales.
        return True

    @classmethod
    def default_model(cls, settings: Settings) -> str | None:
        return settings.kokoro_repo_id

    def _load_pipeline(self, lang_code: str) -> Any:
        # Import perezoso: evita depender de kokoro/torch en pruebas que usan un
        # proveedor falso.
        try:
            from kokoro import KPipeline
        except ImportError as exc:  # pragma: no cover - depende del entorno
            raise TTSProviderError(
                "El paquete 'kokoro' no está instalado en este entorno.",
                provider=self.name,
                status_code=500,
            ) from exc

        try:
            return KPipeline(
                lang_code=lang_code,
                repo_id=self.settings.kokoro_repo_id,
                device=self.settings.tts_device,
            )
        except Exception as exc:
            raise TTSProviderError(
                f"Fallo al cargar Kokoro: {exc}", provider=self.name
            ) from exc

    def _pipeline(self, lang_code: str) -> Any:
        if lang_code not in self._pipelines:
            self._pipelines[lang_code] = self._load_pipeline(lang_code)
        return self._pipelines[lang_code]

    def _resolve_voice(self, request: SynthesizeRequest) -> str:
        return request.voice_id or self.settings.kokoro_default_voice

    def _synthesize_sync(self, request: SynthesizeRequest, lang_code: str) -> list[np.ndarray]:
        """Ejecuta Kokoro (bloqueante) y devuelve los fragmentos de audio."""
        pipeline = self._pipeline(lang_code)
        try:
            generator = pipeline(
                request.text,
                voice=self._resolve_voice(request),
                speed=request.speed,
                split_pattern=r"\n+",
            )
            chunks = []
            for result in generator:
                audio = getattr(result, "audio", None)
                if audio is None:
                    continue
                chunks.append(audio.detach().cpu().numpy())
            return chunks
        except Exception as exc:
            raise TTSProviderError(
                f"Fallo al sintetizar con Kokoro: {exc}", provider=self.name
            ) from exc

    def _to_pcm(self, chunks: list[np.ndarray]) -> bytes:
        if not chunks:
            return b""
        samples = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
        return samples_to_pcm(samples).tobytes()

    async def synthesize(self, request: SynthesizeRequest) -> SynthesisResult:
        async with self._lock:
            chunks = await asyncio.to_thread(
                self._synthesize_sync, request, self.settings.kokoro_lang
            )
        pcm = self._to_pcm(chunks)
        sample_rate = self.settings.kokoro_sample_rate
        duration = len(pcm) / 2 / sample_rate
        if request.format == "pcm":
            audio, fmt = pcm, "pcm"
        else:
            audio, fmt = pcm_to_wav(pcm, sample_rate), "wav"
        return SynthesisResult(
            provider=self.name,
            voice_id=self._resolve_voice(request),
            audio=audio,
            sample_rate=sample_rate,
            duration_sec=duration,
            format=fmt,
        )

    async def synthesize_stream(self, request: SynthesizeRequest) -> AsyncIterator[AudioChunk]:
        # Calcula todos los fragmentos bajo el lock y libera antes de emitir.
        async with self._lock:
            chunks = await asyncio.to_thread(
                self._synthesize_sync, request, self.settings.kokoro_lang
            )
        sample_rate = self.settings.kokoro_sample_rate
        total = len(chunks)
        if total == 0:
            yield AudioChunk(data=b"", index=0, final=True, sample_rate=sample_rate)
            return
        for i, samples in enumerate(chunks):
            data = samples_to_pcm(samples).tobytes()
            yield AudioChunk(
                data=data, index=i, final=(i == total - 1), sample_rate=sample_rate
            )

    async def list_voices(self) -> list[Voice]:
        lang = self.settings.kokoro_lang
        return [
            Voice(
                voice_id=voice_id,
                name=f"{name} ({lang})",
                provider=self.name,
                kind="builtin",
                model=self.settings.kokoro_repo_id,
                sample_rate=self.settings.kokoro_sample_rate,
                language=lang,
            )
            for voice_id, name in KOKORO_VOICES.get(lang, [])
        ]

    async def aclose(self) -> None:
        self._pipelines.clear()
