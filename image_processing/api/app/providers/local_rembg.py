"""Proveedor local de quita-fondo basado en `rembg` (ONNX Runtime, CPU).

`rembg` es la misma familia de modelos que usa ArtCraft a través de fal
(`fal-ai/imageutils/rembg`): U^2-Net / IS-Net / BiRefNet sobre ONNX. Aquí corre
en la propia máquina, sin nube ni credenciales.

El primer uso de un modelo descarga sus pesos a `LOCAL_REMBG_MODEL_DIR`
(`U2NET_HOME`) y los reutiliza después.
"""

from __future__ import annotations

import asyncio
import os
import threading
from io import BytesIO

from ..config import Settings
from .base import ProviderError, RemoveBgProvider, RemoveBgRequest, RemoveBgResult

# Modelos que rembg puede cargar. Si tu versión soporta otros, añádelos aquí.
SUPPORTED_MODELS = {
    "u2net",
    "u2netp",
    "u2net_human_seg",
    "u2net_cloth_seg",
    "silueta",
    "isnet-general-use",
    "isnet-anime",
    "birefnet-general",
    "birefnet-general-lite",
    "birefnet-portrait",
    "birefnet-dis",
    "birefnet-hrsod",
    "birefnet-codis",
    "birefnet-massive",
}


class LocalRembgProvider(RemoveBgProvider):
    name = "local"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._sessions: dict[str, object] = {}
        # Las sesiones ONNX no se crean en paralelo; además serializamos la
        # inferencia (CPU) para no competir por los mismos núcleos.
        self._lock = threading.Lock()

    @classmethod
    def is_configured(cls, settings: Settings) -> bool:
        # El motor local siempre está "configurado"; si falta la dependencia se
        # responde 503 con un mensaje claro al usarlo.
        return True

    @classmethod
    def default_model(cls, settings: Settings) -> str | None:
        return settings.local_rembg_model

    async def remove_background(self, request: RemoveBgRequest) -> RemoveBgResult:
        # rembg es CPU-bound y bloqueante: fuera del event loop.
        return await asyncio.to_thread(self._remove_sync, request)

    def _remove_sync(self, request: RemoveBgRequest) -> RemoveBgResult:
        model = request.model or self.settings.local_rembg_model
        if model not in SUPPORTED_MODELS:
            raise ProviderError(
                f"Modelo inválido: '{model}'. Disponibles: "
                f"{', '.join(sorted(SUPPORTED_MODELS))}.",
                provider=self.name,
                status_code=400,
            )

        model_dir = self.settings.local_rembg_model_dir
        model_dir.mkdir(parents=True, exist_ok=True)
        # rembg lee U2NET_HOME al importarse: hay que fijarlo antes del import.
        os.environ.setdefault("U2NET_HOME", str(model_dir))

        try:
            from rembg import new_session, remove
        except ImportError as exc:  # pragma: no cover - depende del entorno
            raise ProviderError(
                "El motor local 'rembg' no está instalado. Instala "
                "`pip install \"rembg[cpu]\"` (ver requirements.txt).",
                provider=self.name,
                status_code=503,
            ) from exc

        alpha_matting = request.alpha_matting
        if alpha_matting is None:
            alpha_matting = self.settings.local_rembg_alpha_matting
        post_process_mask = request.post_process_mask
        if post_process_mask is None:
            post_process_mask = self.settings.local_rembg_post_process_mask

        with self._lock:
            session = self._sessions.get(model)
            if session is None:
                try:
                    session = new_session(model, sess_opts=self._session_options())
                except Exception as exc:
                    raise ProviderError(
                        f"No se pudo cargar el modelo '{model}': {exc}",
                        provider=self.name,
                        status_code=400,
                    ) from exc
                self._sessions[model] = session

            try:
                png_bytes = remove(
                    request.data,
                    session=session,
                    alpha_matting=alpha_matting,
                    alpha_matting_foreground_threshold=(
                        request.alpha_matting_foreground_threshold
                    ),
                    alpha_matting_background_threshold=(
                        request.alpha_matting_background_threshold
                    ),
                    alpha_matting_erode_size=request.alpha_matting_erode_size,
                    post_process_mask=post_process_mask,
                )
            except Exception as exc:
                raise ProviderError(
                    f"Fallo al quitar el fondo: {exc}",
                    provider=self.name,
                    status_code=500,
                ) from exc

        return self._encode(
            png_bytes,
            model=model,
            background=request.background,
            output_format=request.output_format,
        )

    def _session_options(self):
        """Opciones de ONNX Runtime orientadas a poca memoria en CPU.

        Con los valores por defecto (8 hilos y arena activa), `birefnet-general`
        llegaba a 13.5 GB y el OOM killer mataba el proceso. Limitar los hilos
        y desactivar el arena lo deja en ~8 GB (o ~0.9 GB con `isnet`).
        """
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = self.settings.local_rembg_intra_op_threads
        options.inter_op_num_threads = self.settings.local_rembg_inter_op_threads
        options.enable_cpu_mem_arena = self.settings.local_rembg_cpu_mem_arena
        options.enable_mem_pattern = self.settings.local_rembg_enable_mem_pattern
        return options

    def _encode(
        self,
        png_bytes: bytes,
        *,
        model: str,
        background: str | None,
        output_format: str,
    ) -> RemoveBgResult:
        try:
            from PIL import Image
        except ImportError as exc:  # pragma: no cover - depende del entorno
            raise ProviderError(
                "Falta Pillow para codificar la imagen.",
                provider=self.name,
                status_code=503,
            ) from exc

        image = Image.open(BytesIO(png_bytes))
        image.load()
        image = image.convert("RGBA")

        if background:
            rgb = _hex_to_rgb(background)
            canvas = Image.new("RGBA", image.size, (*rgb, 255))
            canvas.alpha_composite(image)
            image = canvas

        buffer = BytesIO()
        if output_format == "webp":
            image.save(buffer, format="WEBP", quality=92, method=6)
            mime_type = "image/webp"
        else:
            image.save(buffer, format="PNG", optimize=True)
            mime_type = "image/png"

        return RemoveBgResult(
            provider=self.name,
            model=model,
            data=buffer.getvalue(),
            mime_type=mime_type,
            width=image.width,
            height=image.height,
        )


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    raw = value.lstrip("#")
    if len(raw) == 3:
        raw = "".join(c * 2 for c in raw)
    return tuple(int(raw[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
