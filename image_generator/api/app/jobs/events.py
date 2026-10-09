"""Bus de eventos para notificaciones en vivo (SSE).

`MemoryEventBus` reparte en el proceso; `RedisEventBus` usa pub/sub para
funcionar aunque el productor y el consumidor vivan en procesos distintos.

El consumidor obtiene una `Subscription` y llama a `get()` para esperar el
siguiente aviso. El payload del evento es solo una señal: la fuente de verdad
sigue siendo el `JobStore`, de modo que un evento perdido no rompe el flujo.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any, Protocol


class Subscription(Protocol):
    async def get(self) -> dict[str, Any]: ...
    async def aclose(self) -> None: ...


class EventBus(Protocol):
    async def publish(self, job_id: str, payload: dict[str, Any]) -> None: ...
    async def subscribe(self, job_id: str) -> Subscription: ...
    async def aclose(self) -> None: ...


class MemoryEventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = {}

    async def publish(self, job_id: str, payload: dict[str, Any]) -> None:
        for queue in list(self._subscribers.get(job_id, ())):
            queue.put_nowait(payload)

    async def subscribe(self, job_id: str) -> Subscription:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.setdefault(job_id, set()).add(queue)
        return _MemorySubscription(queue, self, job_id)

    async def aclose(self) -> None:
        return None

    def _remove(self, job_id: str, queue: asyncio.Queue) -> None:
        subscribers = self._subscribers.get(job_id)
        if subscribers is not None:
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(job_id, None)


class _MemorySubscription:
    def __init__(self, queue: asyncio.Queue, bus: MemoryEventBus, job_id: str) -> None:
        self._queue = queue
        self._bus = bus
        self._job_id = job_id

    async def get(self) -> dict[str, Any]:
        return await self._queue.get()

    async def aclose(self) -> None:
        self._bus._remove(self._job_id, self._queue)


class RedisEventBus:
    """Publica y escucha en un canal por job (`paimon:events:<id>`)."""

    def __init__(self, client: Any) -> None:
        self._client = client

    @staticmethod
    def _channel(job_id: str) -> str:
        return f"paimon:events:{job_id}"

    async def publish(self, job_id: str, payload: dict[str, Any]) -> None:
        await self._client.publish(self._channel(job_id), json.dumps(payload))

    async def subscribe(self, job_id: str) -> Subscription:
        pubsub = self._client.pubsub()
        await pubsub.subscribe(self._channel(job_id))
        return _RedisSubscription(pubsub, self._channel(job_id))

    async def aclose(self) -> None:
        # El cliente lo comparte (y lo cierra) el store.
        return None


class _RedisSubscription:
    """Drena el pubsub en una cola interna para que `get()` sea cancelable."""

    def __init__(self, pubsub: Any, channel: str) -> None:
        self._pubsub = pubsub
        self._channel = channel
        self._queue: asyncio.Queue = asyncio.Queue()
        self._reader = asyncio.create_task(self._pump())

    async def _pump(self) -> None:
        async for message in self._pubsub.listen():
            if message.get("type") != "message":
                continue
            data = message["data"]
            if isinstance(data, bytes):
                data = data.decode()
            self._queue.put_nowait(json.loads(data))

    async def get(self) -> dict[str, Any]:
        return await self._queue.get()

    async def aclose(self) -> None:
        self._reader.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._reader
        await self._pubsub.unsubscribe(self._channel)
        await self._pubsub.aclose()
