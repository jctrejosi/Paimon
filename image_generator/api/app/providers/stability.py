"""Proveedor Stability AI (endpoint unificado stable-image/generate)."""

from __future__ import annotations

from typing import Any

import httpx

from ..config import Settings
from ..schemas import GenerateRequest
from ._util import closest_aspect_ratio, raw_image_from_b64
from .base import ImageProvider, ProviderError, ProviderResult

# Modelo lógico -> segmento del endpoint (/v2beta/stable-image/generate/<x>).
_ENDPOINTS = {"core": "core", "sd3": "sd3", "sd3.5": "sd3", "ultra": "ultra"}

# Ratios que acepta la API.
_ASPECT_RATIOS = {
    "1:1": 1.0,
    "16:9": 16 / 9,
    "9:16": 9 / 16,
    "3:2": 3 / 2,
    "2:3": 2 / 3,
    "4:5": 4 / 5,
    "5:4": 5 / 4,
    "21:9": 21 / 9,
    "9:21": 9 / 21,
}


class StabilityProvider(ImageProvider):
    name = "stability"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._client = httpx.AsyncClient(
            base_url=settings.stability_base_url.rstrip("/"),
            timeout=settings.stability_timeout,
            headers={
                "Authorization": f"Bearer {settings.stability_api_key}",
                "Accept": "application/json",
            },
        )

    @classmethod
    def is_configured(cls, settings: Settings) -> bool:
        return bool(settings.stability_api_key)

    @classmethod
    def default_model(cls, settings: Settings) -> str | None:
        return settings.stability_image_model

    async def generate(self, request: GenerateRequest) -> ProviderResult:
        model = request.model or self.settings.stability_image_model
        endpoint = _ENDPOINTS.get(model, "core")

        data: dict[str, Any] = {
            "prompt": request.prompt,
            "output_format": "png",
            "aspect_ratio": closest_aspect_ratio(request.width, request.height, _ASPECT_RATIOS),
        }
        if request.negative_prompt:
            data["negative_prompt"] = request.negative_prompt
        if request.seed is not None:
            data["seed"] = request.seed
        data.update({k: str(v) for k, v in request.extra.items() if k not in data})

        # La API solo devuelve una imagen por llamada: se repite `count` veces.
        images = []
        for _ in range(request.count):
            try:
                resp = await self._client.post(
                    f"/v2beta/stable-image/generate/{endpoint}", data=data
                )
            except httpx.HTTPError as exc:
                raise ProviderError(
                    f"Error contactando Stability AI: {exc}", provider=self.name
                ) from exc
            if resp.status_code >= 400:
                raise ProviderError(
                    f"Stability AI rechazó la petición ({resp.status_code}): {resp.text}",
                    provider=self.name,
                )
            payload = resp.json()
            image_b64 = payload.get("image")
            if not image_b64:
                raise ProviderError(
                    "Stability AI no devolvió imagen.", provider=self.name
                )
            images.append(
                raw_image_from_b64(
                    image_b64,
                    seed=payload.get("seed"),
                )
            )

        return ProviderResult(provider=self.name, model=model, images=images)

    async def aclose(self) -> None:
        await self._client.aclose()
