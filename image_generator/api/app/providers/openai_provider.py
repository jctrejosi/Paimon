"""Proveedor OpenAI (modelos gpt-image-1 y dall-e-3)."""

from __future__ import annotations

import httpx

from ..config import Settings
from ..schemas import GenerateRequest
from ._util import closest_aspect_ratio, fetch_url, raw_image_from_b64
from .base import ImageProvider, ProviderError, ProviderResult, RawImage

# Tamaños soportados por modelo, expresados como (ancho, alto).
_SIZES = {
    "gpt-image-1": [(1024, 1024), (1536, 1024), (1024, 1536)],
    "dall-e-3": [(1024, 1024), (1792, 1024), (1024, 1792)],
    "dall-e-2": [(256, 256), (512, 512), (1024, 1024)],
}


class OpenAIProvider(ImageProvider):
    name = "openai"

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
        model = request.model or self.settings.openai_image_model
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

        try:
            resp = await self._client.post("/images/generations", json=body)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Error contactando OpenAI: {exc}", provider=self.name) from exc
        if resp.status_code >= 400:
            raise ProviderError(
                f"OpenAI rechazó la petición ({resp.status_code}): {resp.text}",
                provider=self.name,
            )

        data = resp.json().get("data", [])
        images: list[RawImage] = []
        for item in data:
            if item.get("b64_json"):
                images.append(
                    raw_image_from_b64(
                        item["b64_json"], revised_prompt=item.get("revised_prompt")
                    )
                )
            elif item.get("url"):
                images.append(
                    await fetch_url(self._client, item["url"], provider=self.name)
                )

        if not images:
            raise ProviderError("OpenAI no devolvió imágenes.", provider=self.name)
        return ProviderResult(provider=self.name, model=model, images=images)

    async def aclose(self) -> None:
        await self._client.aclose()
