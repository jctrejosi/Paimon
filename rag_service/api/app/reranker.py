"""Reranking semántico opcional con DeepSeek.

Tras recuperar candidatos por similitud de embeddings, el modelo reordena los
fragmentos por relevancia. Es opcional: si no hay `DEEPSEEK_API_KEY` o falla la
llamada, se conserva el orden vectorial.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from .config import Settings

logger = logging.getLogger("paimon-rag.reranker")


class Reranker:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: httpx.AsyncClient | None = None

    @property
    def configured(self) -> bool:
        return self._settings.rerank_enabled

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._settings.deepseek_base_url.rstrip("/"),
                headers={
                    "Authorization": f"Bearer {self._settings.deepseek_api_key}"
                },
                timeout=self._settings.deepseek_timeout_seconds,
            )
        return self._client

    async def rerank(
        self, query: str, chunks: list[dict[str, Any]], top_k: int = 5
    ) -> list[dict[str, Any]]:
        if not chunks:
            return []
        if len(chunks) <= 1 or not self.configured:
            return chunks[:top_k]

        previews = ""
        for index, chunk in enumerate(chunks):
            preview = str(chunk.get("content", ""))[:300].replace("\n", " ").strip()
            previews += f"[{index}] {preview}\n\n"

        prompt = (
            "Evalúa cuáles de los siguientes fragmentos responden mejor a la "
            "consulta del usuario.\n\n"
            f'Consulta: "{query}"\n\nFragmentos:\n{previews}\n'
            "Devuelve ÚNICAMENTE un array JSON con los índices de los fragmentos "
            "ordenados por relevancia (más relevante primero). Ejemplo: [2, 0, 1, 3]"
        )

        try:
            response = await self._get_client().post(
                "/chat/completions",
                json={
                    "model": self._settings.deepseek_model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Eres un asistente que evalúa relevancia de "
                                "documentos. Responde ÚNICAMENTE con un array "
                                "JSON de índices numéricos, sin texto adicional."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 200,
                },
            )
            response.raise_for_status()
            answer = response.json()["choices"][0]["message"]["content"]
            order = _parse_order(answer, len(chunks))
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            logger.warning("Reranker no disponible, se usa el orden vectorial: %s", exc)
            return chunks[:top_k]

        reranked: list[dict[str, Any]] = []
        seen: set[int] = set()
        for rank, index in enumerate(order):
            if index in seen or not (0 <= index < len(chunks)):
                continue
            seen.add(index)
            item = dict(chunks[index])
            item["rerank_score"] = round(1.0 - rank / max(len(order), 1), 4)
            item["rerank_position"] = rank + 1
            reranked.append(item)

        return reranked[:top_k] or chunks[:top_k]

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def _parse_order(answer: str, num_chunks: int) -> list[int]:
    text = (answer or "").strip()
    for prefix in ("```json", "```"):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
    if text.endswith("```"):
        text = text[:-3].strip()

    try:
        order = json.loads(text)
        if isinstance(order, list):
            return [
                int(item)
                for item in order
                if isinstance(item, (int, float)) or str(item).isdigit()
            ]
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    return [int(n) for n in re.findall(r"\d+", text) if int(n) < num_chunks]
