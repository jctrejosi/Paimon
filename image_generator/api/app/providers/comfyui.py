"""Proveedor local basado en ComfyUI (API HTTP nativa).

Soporta tres modos según la petición:

* **txt2img** (sin `image`): plantilla `sd_txt2img.json`.
* **img2img** (`image`, sin `mask`): plantilla `sd_img2img.json`; `strength`
  controla el `denoise` del KSampler.
* **inpainting** (`image` + `mask`): plantilla `sd_inpaint.json`.

Flujo: se inyectan los parámetros en la plantilla, se encola con `POST /prompt`,
se espera el resultado en `GET /history/{id}` y se descargan los bytes con
`GET /view`.
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
from ..storage import extension_for
from .base import ImageProvider, ProviderError, ProviderResult, RawImage

_WORKFLOWS_DIR = Path(__file__).resolve().parents[2] / "workflows"
_TXT2IMG = _WORKFLOWS_DIR / "sd_txt2img.json"
_IMG2IMG = _WORKFLOWS_DIR / "sd_img2img.json"
_INPAINT = _WORKFLOWS_DIR / "sd_inpaint.json"


class ComfyUIProvider(ImageProvider):
    name = "comfyui"
    supports_img2img = True

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._client = httpx.AsyncClient(
            base_url=settings.comfyui_url.rstrip("/"),
            timeout=settings.comfyui_timeout,
        )
        # Un workflow propio (COMFYUI_WORKFLOW) solo sustituye al de txt2img.
        txt2img_path = Path(settings.comfyui_workflow) if settings.comfyui_workflow else _TXT2IMG
        self._templates = {
            "txt2img": self._load_template(txt2img_path),
            "img2img": self._load_template(_IMG2IMG),
            "inpaint": self._load_template(_INPAINT),
        }

    @classmethod
    def is_configured(cls, settings: Settings) -> bool:
        # ComfyUI no requiere credenciales; basta con tener URL.
        return bool(settings.comfyui_url)

    @classmethod
    def default_model(cls, settings: Settings) -> str | None:
        return settings.comfyui_checkpoint

    @staticmethod
    def _load_template(path: Path) -> dict:
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

    def _apply_parameters(self, workflow: dict, request: GenerateRequest, seed: int) -> dict:
        """Aplica los parámetros escalares sobre una copia del grafo."""
        workflow = copy.deepcopy(workflow)

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
            if request.image is not None:
                # Default: inpainting rehace al 100%; img2img respeta `strength`.
                default_denoise = 1.0 if request.mask is not None else 0.75
                inputs["denoise"] = (
                    request.strength if request.strength is not None else default_denoise
                )

        for node_id in self._node_ids_by_class(workflow, "SaveImage"):
            workflow[node_id]["inputs"]["filename_prefix"] = "paimon"

        return workflow

    async def _upload_image(self, decoded) -> str:
        """Sube una imagen a ComfyUI y devuelve el nombre con el que referenciarla."""
        ext = extension_for(decoded.mime_type)
        filename = f"paimon-{uuid.uuid4().hex}.{ext}"
        files = {"image": (filename, decoded.data, decoded.mime_type)}
        data = {"overwrite": "true", "type": "input"}
        try:
            resp = await self._client.post("/upload/image", files=files, data=data)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"No se pudo subir la imagen a ComfyUI: {exc}", provider=self.name
            ) from exc
        payload = resp.json()
        name = payload["name"]
        subfolder = payload.get("subfolder") or ""
        return f"{subfolder}/{name}" if subfolder else name

    async def _build_workflow(self, request: GenerateRequest, seed: int) -> tuple[dict, str]:
        if request.image is not None and request.mask is not None:
            mode = "inpaint"
        elif request.image is not None:
            mode = "img2img"
        else:
            mode = "txt2img"

        workflow = self._templates[mode]
        if request.image is not None:
            input_nodes = self._node_ids_by_class(workflow, "LoadImage")
            image_name = await self._upload_image(self.decode_image_field(request.image))
            # La plantilla de inpaint tiene dos LoadImage: imagen y máscara.
            reference = copy.deepcopy(workflow)
            reference[input_nodes[0]]["inputs"]["image"] = image_name
            if request.mask is not None and len(input_nodes) > 1:
                mask_name = await self._upload_image(self.decode_image_field(request.mask))
                reference[input_nodes[1]]["inputs"]["image"] = mask_name
            workflow = reference

        return self._apply_parameters(workflow, request, seed), mode

    # --- ejecución --------------------------------------------------------
    async def generate(self, request: GenerateRequest) -> ProviderResult:
        self.ensure_img2img(request)
        seed = (
            request.seed
            if request.seed is not None
            else int.from_bytes(uuid.uuid4().bytes[:4], "big")
        )
        client_id = str(uuid.uuid4())
        workflow, mode = await self._build_workflow(request, seed)

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
            metadata={"prompt_id": prompt_id, "client_id": client_id, "mode": mode},
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
