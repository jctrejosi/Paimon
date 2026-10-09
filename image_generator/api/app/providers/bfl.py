"""Proveedor Black Forest Labs (FLUX vía API asíncrona con polling)."""

from __future__ import annotations

import asyncio

import httpx

from ..config import Settings
from ..schemas import GenerateRequest
from ._util import fetch_url
from .base import ImageProvider, ProviderError, ProviderResult


class BFLProvider(ImageProvider):
    name = "bfl"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._client = httpx.AsyncClient(
            base_url=settings.bfl_base_url.rstrip("/"),
            timeout=settings.bfl_timeout,
            headers={"x-key": settings.bfl_api_key or ""},
        )

    @classmethod
    def is_configured(cls, settings: Settings) -> bool:
        return bool(settings.bfl_api_key)

    @classmethod
    def default_model(cls, settings: Settings) -> str | None:
        return settings.bfl_model

    async def generate(self, request: GenerateRequest) -> ProviderResult:
        model = request.model or self.settings.bfl_model
        body = {
            "prompt": request.prompt,
            "width": request.width,
            "height": request.height,
            "seed": request.seed,
        }
        body.update({k: v for k, v in request.extra.items() if k not in body})

        try:
            resp = await self._client.post(f"/{model}", json=body)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Error contactando BFL: {exc}", provider=self.name) from exc
        if resp.status_code >= 400:
            raise ProviderError(
                f"BFL rechazó la petición ({resp.status_code}): {resp.text}",
                provider=self.name,
            )

        submission = resp.json()
        result = await self._poll(submission)
        sample_url = (result.get("result") or {}).get("sample")
        if not sample_url:
            raise ProviderError("BFL no devolvió una imagen.", provider=self.name)

        image = await fetch_url(self._client, sample_url, provider=self.name)
        image.seed = result.get("result", {}).get("seed")
        return ProviderResult(
            provider=self.name,
            model=model,
            images=[image],
            metadata={"request_id": submission.get("id")},
        )

    async def _poll(self, submission: dict) -> dict:
        polling_url = submission.get("polling_url")
        if not polling_url:
            raise ProviderError("BFL no devolvió polling_url.", provider=self.name)

        deadline = asyncio.get_event_loop().time() + self.settings.bfl_timeout
        while True:
            try:
                resp = await self._client.get(polling_url)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise ProviderError(
                    f"Error consultando el resultado de BFL: {exc}", provider=self.name
                ) from exc
            payload = resp.json()
            status = payload.get("status")
            if status == "Ready":
                return payload
            if status in {"Error", "Failed", "Content Moderated", "Request Moderated"}:
                raise ProviderError(
                    f"BFL devolvió estado '{status}'.", provider=self.name
                )
            if asyncio.get_event_loop().time() > deadline:
                raise ProviderError(
                    "Timeout esperando el resultado de BFL.",
                    provider=self.name,
                    status_code=504,
                )
            await asyncio.sleep(1.0)

    async def aclose(self) -> None:
        await self._client.aclose()
