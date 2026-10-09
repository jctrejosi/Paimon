"""Cola de trabajos pendientes.

* `MemoryJobQueue`: `asyncio.Queue` en proceso (volátil).
* `RedisJobQueue`: lista en Redis; permite repartir el trabajo entre varios
  workers y sobrevive a reinicios.

`durable` indica si los elementos encolados sobreviven a un reinicio, lo que la
recuperación usa para decidir si un job 'queued' sigue siendo válido.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol


class JobQueue(Protocol):
    durable: bool

    async def enqueue(self, job_id: str) -> None: ...
    async def dequeue(self, timeout: float) -> str | None: ...
    async def aclose(self) -> None: ...


class MemoryJobQueue:
    durable = False

    def __init__(self) -> None:
        self._queue: asyncio.Queue = asyncio.Queue()

    async def enqueue(self, job_id: str) -> None:
        self._queue.put_nowait(job_id)

    async def dequeue(self, timeout: float) -> str | None:
        try:
            return await asyncio.wait_for(self._queue.get(), timeout)
        except TimeoutError:
            return None

    async def aclose(self) -> None:
        return None


class RedisJobQueue:
    durable = True

    def __init__(self, client: Any, key: str = "paimon:jobs:queue") -> None:
        self._client = client
        self._key = key

    async def enqueue(self, job_id: str) -> None:
        await self._client.lpush(self._key, job_id)

    async def dequeue(self, timeout: float) -> str | None:
        item = await self._client.brpop(self._key, timeout=max(1, int(timeout)))
        if item is None:
            return None
        return item[1]

    async def aclose(self) -> None:
        # El cliente lo comparte (y lo cierra) el store.
        return None
