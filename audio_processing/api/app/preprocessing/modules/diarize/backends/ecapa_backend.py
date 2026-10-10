"""Backend de diarización con embeddings ECAPA (speechbrain) + clustering.

No requiere credenciales: los modelos de speechbrain son públicos. Flujo:

1. Detección de voz (Silero, vía faster-whisper) para localizar los tramos.
2. Recorte en trozos de duración acotada.
3. Embedding de hablante por trozo (ECAPA, 192 dims).
4. Clustering aglomerativo con distancia coseno (nº fijo de hablantes o umbral).
5. Fusión de tramos consecutivos del mismo hablante.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from app.audio.io import resample_samples
from app.audio.types import AudioClip, Segment
from app.preprocessing.base import ProcessorError

from .base import DiarizationBackend, DiarizationResult

_TARGET_RATE = 16000


class EcapaBackend(DiarizationBackend):
    name = "ecapa"
    description = "Embeddings ECAPA (speechbrain) + clustering. Sin credenciales."
    required_packages = ("speechbrain", "torch", "sklearn")

    def __init__(self, settings) -> None:
        super().__init__(settings)
        self._classifier = None
        self._model_name: str | None = None

    def diarize(self, clip: AudioClip, params: Any) -> DiarizationResult:
        mono = clip.to_mono()
        regions = self._speech_regions(mono, params)
        if not regions:
            return DiarizationResult(
                metrics={"backend": self.name, "turns": 0, "speakers": 0, "no_speech": True}
            )

        embeddings = self._embeddings(mono, regions, params.ecapa_model)
        if embeddings.shape[0] < 2:
            return self._result(regions, np.zeros(len(regions), dtype=int), mono, params, degraded=True)

        labels = self._cluster(embeddings, params)
        return self._result(regions, labels, mono, params)

    # --- etapas -----------------------------------------------------------
    @staticmethod
    def _speech_regions(mono: AudioClip, params: Any) -> list[tuple[int, int]]:
        """Tramos de voz (en muestras del clip original), troceados."""
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        samples = mono.samples[0]
        analysis = (
            resample_samples(samples, mono.sample_rate, _TARGET_RATE)
            if mono.sample_rate != _TARGET_RATE
            else samples
        )
        # Sin padding y con cortes de silencio cortos: una pausa breve entre
        # hablantes debe separar sus tramos (el VAD de faster-whisper usa 2 s
        # por defecto, pensado para trocear transcripción, no para diarizar).
        options = VadOptions(threshold=0.5, min_silence_duration_ms=200, speech_pad_ms=0)
        stamps = get_speech_timestamps(
            np.asarray(analysis, dtype=np.float32), options, sampling_rate=_TARGET_RATE
        )

        scale = mono.sample_rate / _TARGET_RATE
        max_samples = int(params.max_chunk_s * mono.sample_rate)
        min_samples = int(params.min_chunk_s * mono.sample_rate)

        regions: list[tuple[int, int]] = []
        for stamp in stamps:
            start = int(stamp["start"] * scale)
            end = int(stamp["end"] * scale)
            cursor = start
            while cursor < end:
                chunk_end = min(cursor + max_samples, end)
                if chunk_end - cursor >= min_samples:
                    regions.append((cursor, chunk_end))
                cursor = chunk_end
        return regions

    def _embeddings(
        self, mono: AudioClip, regions: list[tuple[int, int]], model: str
    ) -> np.ndarray:
        import torch

        classifier = self._get_classifier(model)
        vectors: list[np.ndarray] = []
        for start, end in regions:
            chunk = np.ascontiguousarray(mono.samples[0][start:end])
            with torch.no_grad():
                embedding = classifier.encode_batch(torch.from_numpy(chunk)[None, :])
            vectors.append(embedding.detach().cpu().numpy().reshape(-1))
        return np.vstack(vectors) if vectors else np.empty((0, 0))

    def _get_classifier(self, model: str):
        from speechbrain.inference.speaker import EncoderClassifier

        if self._classifier is None or self._model_name != model:
            # Se cachea junto al resto de modelos (volumen `models/`).
            savedir = Path(self.settings.whisper_model_dir) / "speechbrain" / model.replace("/", "--")
            try:
                self._classifier = EncoderClassifier.from_hparams(
                    source=model, savedir=str(savedir), run_opts={"device": "cpu"}
                )
            except Exception as exc:  # se reenvía como error del módulo
                raise ProcessorError(
                    f"No se pudo cargar el modelo ECAPA '{model}': {exc}",
                    processor="diarize/ecapa",
                    status_code=503,
                ) from exc
            self._model_name = model
        return self._classifier

    @staticmethod
    def _cluster(embeddings: np.ndarray, params: Any) -> np.ndarray:
        from sklearn.cluster import AgglomerativeClustering

        if params.num_speakers and params.num_speakers > 1:
            model = AgglomerativeClustering(
                n_clusters=min(params.num_speakers, embeddings.shape[0]),
                metric="cosine",
                linkage="average",
            )
        else:
            model = AgglomerativeClustering(
                n_clusters=None,
                distance_threshold=params.threshold,
                metric="cosine",
                linkage="average",
            )
        return model.fit_predict(embeddings)

    @staticmethod
    def _result(
        regions: list[tuple[int, int]],
        labels: np.ndarray,
        mono: AudioClip,
        params: Any,
        degraded: bool = False,
    ) -> DiarizationResult:
        """Fusiona tramos consecutivos del mismo hablante."""
        rate = mono.sample_rate
        segments: list[Segment] = []
        for (start, end), label in zip(regions, labels):
            speaker = f"SPEAKER_{int(label):02d}"
            previous = segments[-1] if segments else None
            if (
                previous is not None
                and previous.speaker == speaker
                and start / rate - previous.end <= 0.5
            ):
                previous.end = end / rate
            else:
                segments.append(Segment(start=start / rate, end=end / rate, speaker=speaker))

        return DiarizationResult(
            segments=segments,
            metrics={
                "backend": EcapaBackend.name,
                "model": params.ecapa_model,
                "turns": len(segments),
                "speakers": len({segment.speaker for segment in segments}),
                "threshold": params.threshold,
                "degraded": degraded,
            },
        )
