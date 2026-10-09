"""Proveedor fal.ai (queue HTTP síncrona sobre fal.run)."""

from __future__ import annotations

import httpx

from ..config import Settings
from ..schemas import GenerateRequest
from ._util import fetch_url
from .base import ImageProvider, ProviderError, ProviderResult, RawImage


class FalProvider(ImageProvider):
    name = "fal"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._client = httpx.AsyncClient(
            base_url="https://fal.run",
            timeout=settings.fal_timeout,
            headers={"Authorization": f"Key {settings.fal_key}"},
        )

    @classmethod
    def is_configured(cls, settings: Settings) -> bool:
        return bool(settings.fal_key)

    @classmethod
    def default_model(cls, settings: Settings) -> str | None:
        return settings.fal_model

    async def generate(self, request: GenerateRequest) -> ProviderResult:
        model = request.model or self.settings.fal_model
        body = {
            "prompt": request.prompt,
            "image_size": {"width": request.width, "height": request.height},
            "num_images": request.count,
        }
        if request.negative_prompt:
            body["negative_prompt"] = request.negative_prompt
        if request.seed is not None:
            body["seed"] = request.seed
        body.update({k: v for k, v in request.extra.items() if k not in body})

        try:
            resp = await self._client.post(f"/{model}", json=body)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Error contactando fal.ai: {exc}", provider=self.name) from exc
        if resp.status_code >= 400:
            raise ProviderError(
                f"fal.ai rechazó la petición ({resp.status_code}): {resp.text}",
                provider=self.name,
            )

        payload = resp.json()
        seed = payload.get("seed")
        images: list[RawImage] = []
        for item in payload.get("images", []):
            url = item.get("url") if isinstance(item, dict) else item
            if url:
                image = await fetch_url(self._client, url, provider=self.name)
                image.seed = seed
                images.append(image)

        if not images:
            raise ProviderError("fal.ai no devolvió imágenes.", provider=self.name)
        return ProviderResult(provider=self.name, model=model, images=images)

    async def aclose(self) -> None:
        await self._client.aclose()
