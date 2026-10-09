"""Proveedor Replicate (hosting de muchos modelos: FLUX, SDXL, etc.)."""

from __future__ import annotations

import asyncio

import httpx

from ..config import Settings
from ..schemas import GenerateRequest
from ._util import fetch_url
from .base import ImageProvider, ProviderError, ProviderResult, RawImage


class ReplicateProvider(ImageProvider):
    name = "replicate"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._client = httpx.AsyncClient(
            base_url="https://api.replicate.com/v1",
            timeout=settings.replicate_timeout,
            headers={
                "Authorization": f"Bearer {settings.replicate_api_token}",
                "Prefer": "wait",
            },
        )

    @classmethod
    def is_configured(cls, settings: Settings) -> bool:
        return bool(settings.replicate_api_token)

    @classmethod
    def default_model(cls, settings: Settings) -> str | None:
        return settings.replicate_model

    async def generate(self, request: GenerateRequest) -> ProviderResult:
        model = request.model or self.settings.replicate_model
        model_input = {
            "prompt": request.prompt,
            "width": request.width,
            "height": request.height,
            "num_outputs": request.count,
        }
        if request.negative_prompt:
            model_input["negative_prompt"] = request.negative_prompt
        if request.seed is not None:
            model_input["seed"] = request.seed
        # `extra` permite ajustar nombres de campos específicos del modelo.
        model_input.update(request.extra)

        try:
            resp = await self._client.post(
                f"/models/{model}/predictions", json={"input": model_input}
            )
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Error contactando Replicate: {exc}", provider=self.name
            ) from exc
        if resp.status_code >= 400:
            raise ProviderError(
                f"Replicate rechazó la petición ({resp.status_code}): {resp.text}",
                provider=self.name,
            )

        prediction = await self._poll(resp.json())
        output = prediction.get("output")
        urls = output if isinstance(output, list) else [output]
        images: list[RawImage] = []
        for url in urls:
            if isinstance(url, str) and url.startswith("http"):
                images.append(await fetch_url(self._client, url, provider=self.name))

        if not images:
            raise ProviderError("Replicate no devolvió imágenes.", provider=self.name)
        return ProviderResult(
            provider=self.name,
            model=model,
            images=images,
            metadata={"prediction_id": prediction.get("id")},
        )

    async def _poll(self, prediction: dict) -> dict:
        get_url = (prediction.get("urls") or {}).get("get")
        if prediction.get("status") in {"succeeded", "failed", "canceled"}:
            return prediction
        if not get_url:
            raise ProviderError(
                "Replicate no devolvió una URL de seguimiento.", provider=self.name
            )

        deadline = asyncio.get_event_loop().time() + self.settings.replicate_timeout
        while True:
            try:
                resp = await self._client.get(get_url)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise ProviderError(
                    f"Error consultando la predicción de Replicate: {exc}",
                    provider=self.name,
                ) from exc
            prediction = resp.json()
            status = prediction.get("status")
            if status == "succeeded":
                return prediction
            if status in {"failed", "canceled"}:
                raise ProviderError(
                    f"La predicción de Replicate falló: {prediction.get('error')}",
                    provider=self.name,
                )
            if asyncio.get_event_loop().time() > deadline:
                raise ProviderError(
                    "Timeout esperando la predicción de Replicate.",
                    provider=self.name,
                    status_code=504,
                )
            await asyncio.sleep(1.0)

    async def aclose(self) -> None:
        await self._client.aclose()
