"""Proveedor OpenAI (modelos gpt-image-1 y dall-e-3).

Soporta generación (text-to-image) y edición (image-to-image con `/images/edits`,
disponible para `gpt-image-1` y `dall-e-2`).
"""

from __future__ import annotations

import httpx

from ..config import Settings
from ..schemas import GenerateRequest
from ..storage import extension_for
from ._util import closest_aspect_ratio, fetch_url, raw_image_from_b64
from .base import ImageProvider, ProviderError, ProviderResult, RawImage

# Tamaños soportados por modelo, expresados como (ancho, alto).
_SIZES = {
    "gpt-image-1": [(1024, 1024), (1536, 1024), (1024, 1536)],
    "dall-e-3": [(1024, 1024), (1792, 1024), (1024, 1792)],
    "dall-e-2": [(256, 256), (512, 512), (1024, 1024)],
}
# Modelos que admiten /images/edits.
_EDIT_MODELS = {"gpt-image-1", "dall-e-2"}


class OpenAIProvider(ImageProvider):
    name = "openai"
    supports_img2img = True

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._client = httpx.AsyncClient(
            base_url=settings.openai_base_url.rstrip("/"),
            timeout=settings.openai_timeout,
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        )

    @classmethod
    def is_configured(cls, settings: Settings) -> bool:
        return bool(settings.openai_api_key)

    @classmethod
    def default_model(cls, settings: Settings) -> str | None:
        return settings.openai_image_model

    def _closest_size(self, model: str, width: int, height: int) -> str:
        candidates = _SIZES.get(model, _SIZES["gpt-image-1"])
        ratios = {f"{w}x{h}": w / h for w, h in candidates}
        return closest_aspect_ratio(width, height, ratios)

    async def generate(self, request: GenerateRequest) -> ProviderResult:
        self.ensure_img2img(request)
        model = request.model or self.settings.openai_image_model
        if request.image is not None:
            return await self._edit(request, model)
        return await self._text_to_image(request, model)

    async def _text_to_image(self, request: GenerateRequest, model: str) -> ProviderResult:
        # dall-e-3 solo admite n=1; el resto sí acepta lotes.
        count = 1 if model == "dall-e-3" else request.count
        body = {
            "model": model,
            "prompt": request.prompt,
            "n": count,
            "size": self._closest_size(model, request.width, request.height),
        }
        # gpt-image-1 devuelve b64_json por defecto y no acepta response_format.
        if model != "gpt-image-1":
            body["response_format"] = "b64_json"
        body.update({k: v for k, v in request.extra.items() if k not in body})

        resp = await self._post("/images/generations", json=body)
        return await self._to_result(resp, model)

    async def _edit(self, request: GenerateRequest, model: str) -> ProviderResult:
        if request.image is None:
            raise ProviderError(
                "La edición requiere una imagen de entrada.",
                provider=self.name,
                status_code=400,
            )
        if model not in _EDIT_MODELS:
            raise ProviderError(
                f"El modelo '{model}' no soporta edición; usa gpt-image-1 o dall-e-2.",
                provider=self.name,
                status_code=400,
            )

        image = self.decode_image_field(request.image)
        files = {
            "image": (f"image.{extension_for(image.mime_type)}", image.data, image.mime_type)
        }
        if request.mask is not None:
            mask = self.decode_image_field(request.mask)
            files["mask"] = (
                f"mask.{extension_for(mask.mime_type)}",
                mask.data,
                mask.mime_type,
            )

        data = {
            "model": model,
            "prompt": request.prompt,
            "n": str(request.count),
            "size": self._closest_size(model, request.width, request.height),
        }
        if model != "gpt-image-1":
            data["response_format"] = "b64_json"
        data.update({k: str(v) for k, v in request.extra.items() if k not in data})

        resp = await self._post("/images/edits", data=data, files=files)
        return await self._to_result(resp, model)

    async def _post(self, path: str, **kwargs) -> httpx.Response:
        try:
            resp = await self._client.post(path, **kwargs)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Error contactando OpenAI: {exc}", provider=self.name) from exc
        if resp.status_code >= 400:
            raise ProviderError(
                f"OpenAI rechazó la petición ({resp.status_code}): {resp.text}",
                provider=self.name,
            )
        return resp

    async def _to_result(self, resp: httpx.Response, model: str) -> ProviderResult:
        images: list[RawImage] = []
        for item in resp.json().get("data", []):
            if item.get("b64_json"):
                images.append(
                    raw_image_from_b64(
                        item["b64_json"], revised_prompt=item.get("revised_prompt")
                    )
                )
            elif item.get("url"):
                images.append(await fetch_url(self._client, item["url"], provider=self.name))

        if not images:
            raise ProviderError("OpenAI no devolvió imágenes.", provider=self.name)
        return ProviderResult(provider=self.name, model=model, images=images)

    async def aclose(self) -> None:
        await self._client.aclose()
