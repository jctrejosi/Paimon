"""Proveedor local basado en ComfyUI (API HTTP nativa).

Flujo: se toma una plantilla de workflow en formato "API" de ComfyUI, se
inyectan los parámetros, se encola con `POST /prompt`, se espera el resultado
en `GET /history/{id}` y se descargan los bytes con `GET /view`.
"""

from __future__ import annotations

import asyncio
import copy
import json
import mimetypes
import time
import uuid
from pathlib import Path

import httpx

from ..config import Settings
from ..schemas import GenerateRequest
from .base import ImageProvider, ProviderError, ProviderResult, RawImage

# Plantilla por defecto incluida en el paquete.
_DEFAULT_WORKFLOW = Path(__file__).resolve().parents[2] / "workflows" / "sd_txt2img.json"


class ComfyUIProvider(ImageProvider):
    name = "comfyui"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._client = httpx.AsyncClient(
            base_url=settings.comfyui_url.rstrip("/"),
            timeout=settings.comfyui_timeout,
        )
        self._template = self._load_template(settings)

    @classmethod
    def is_configured(cls, settings: Settings) -> bool:
        # ComfyUI no requiere credenciales; basta con tener URL.
        return bool(settings.comfyui_url)

    @classmethod
    def default_model(cls, settings: Settings) -> str | None:
        return settings.comfyui_checkpoint

    @staticmethod
    def _load_template(settings: Settings) -> dict:
        path = settings.comfyui_workflow or _DEFAULT_WORKFLOW
        path = Path(path)
        if not path.is_file():
            raise ProviderError(
                f"No se encontró la plantilla de workflow: {path}",
                provider="comfyui",
                status_code=500,
            )
        return json.loads(path.read_text(encoding="utf-8"))

    # --- construcción del grafo ------------------------------------------
    @staticmethod
    def _node_ids_by_class(workflow: dict, class_type: str) -> list[str]:
        return [
            node_id
            for node_id, node in workflow.items()
            if isinstance(node, dict) and node.get("class_type") == class_type
        ]

    def _apply_parameters(self, request: GenerateRequest, seed: int) -> dict:
        workflow = copy.deepcopy(self._template)

        checkpoint = request.model or self.settings.comfyui_checkpoint
        for node_id in self._node_ids_by_class(workflow, "CheckpointLoaderSimple"):
            workflow[node_id]["inputs"]["ckpt_name"] = checkpoint

        text_nodes = self._node_ids_by_class(workflow, "CLIPTextEncode")
        if text_nodes:
            # Convención de la plantilla: primero positivo, luego negativo.
            workflow[text_nodes[0]]["inputs"]["text"] = request.prompt
            if len(text_nodes) > 1:
                workflow[text_nodes[1]]["inputs"]["text"] = request.negative_prompt or ""

        for node_id in self._node_ids_by_class(workflow, "EmptyLatentImage"):
            workflow[node_id]["inputs"]["width"] = request.width
            workflow[node_id]["inputs"]["height"] = request.height
            workflow[node_id]["inputs"]["batch_size"] = request.count

        for node_id in self._node_ids_by_class(workflow, "KSampler"):
            inputs = workflow[node_id]["inputs"]
            inputs["seed"] = seed
            if request.steps is not None:
                inputs["steps"] = request.steps
            if request.guidance_scale is not None:
                inputs["cfg"] = request.guidance_scale

        for node_id in self._node_ids_by_class(workflow, "SaveImage"):
            workflow[node_id]["inputs"]["filename_prefix"] = "paimon"

        return workflow

    # --- ejecución --------------------------------------------------------
    async def generate(self, request: GenerateRequest) -> ProviderResult:
        seed = request.seed if request.seed is not None else int.from_bytes(
            uuid.uuid4().bytes[:4], "big"
        )
        client_id = str(uuid.uuid4())
        workflow = self._apply_parameters(request, seed)

        try:
            resp = await self._client.post(
                "/prompt", json={"prompt": workflow, "client_id": client_id}
            )
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"No se pudo contactar con ComfyUI en {self.settings.comfyui_url}: {exc}",
                provider=self.name,
            ) from exc

        if resp.status_code >= 400:
            raise ProviderError(
                f"ComfyUI rechazó el workflow ({resp.status_code}): {resp.text}",
                provider=self.name,
            )
        payload = resp.json()
        if "error" in payload:
            raise ProviderError(
                f"ComfyUI devolvió un error: {payload['error']}", provider=self.name
            )

        prompt_id = payload["prompt_id"]
        outputs = await self._wait_for_result(prompt_id)
        images = await self._download_images(outputs)

        return ProviderResult(
            provider=self.name,
            model=request.model or self.settings.comfyui_checkpoint,
            images=images,
            metadata={"prompt_id": prompt_id, "client_id": client_id},
        )

    async def _wait_for_result(self, prompt_id: str) -> dict:
        deadline = time.monotonic() + self.settings.comfyui_timeout
        while True:
            try:
                resp = await self._client.get(f"/history/{prompt_id}")
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise ProviderError(
                    f"Error consultando el historial de ComfyUI: {exc}", provider=self.name
                ) from exc

            history = resp.json()
            entry = history.get(prompt_id)
            if entry is not None:
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    raise ProviderError(
                        f"La ejecución en ComfyUI falló: {status}", provider=self.name
                    )
                return entry.get("outputs", {})

            if time.monotonic() > deadline:
                raise ProviderError(
                    f"Timeout esperando el resultado de ComfyUI ({prompt_id}).",
                    provider=self.name,
                    status_code=504,
                )
            await asyncio.sleep(self.settings.comfyui_poll_interval)

    async def _download_images(self, outputs: dict) -> list[RawImage]:
        images: list[RawImage] = []
        for node_output in outputs.values():
            for image in node_output.get("images", []):
                params = {
                    "filename": image["filename"],
                    "subfolder": image.get("subfolder", ""),
                    "type": image.get("type", "output"),
                }
                try:
                    resp = await self._client.get("/view", params=params)
                    resp.raise_for_status()
                except httpx.HTTPError as exc:
                    raise ProviderError(
                        f"No se pudo descargar la imagen {params['filename']}: {exc}",
                        provider=self.name,
                    ) from exc
                mime = mimetypes.guess_type(image["filename"])[0] or "image/png"
                images.append(RawImage(data=resp.content, mime_type=mime))

        if not images:
            raise ProviderError(
                "ComfyUI terminó sin producir imágenes (¿el workflow tiene SaveImage?).",
                provider=self.name,
                status_code=502,
            )
        return images

    async def aclose(self) -> None:
        await self._client.aclose()
