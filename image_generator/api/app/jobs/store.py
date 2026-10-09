"""Almacenamiento del estado de los jobs.

Dos implementaciones tras una misma interfaz (`JobStore`):

* `MemoryJobStore`: en un diccionario, efímero. Por defecto.
* `RedisJobStore`: persistente y compartible entre procesos.
"""

from __future__ import annotations

from typing import Any, Protocol

from ..schemas import Job

TERMINAL_STATUSES: frozenset[str] = frozenset({"succeeded", "failed", "canceled"})


class JobStore(Protocol):
    async def save(self, job: Job) -> None: ...
    async def get(self, job_id: str) -> Job | None: ...
    async def list(self) -> list[Job]: ...
    async def delete(self, job_id: str) -> None: ...
    async def aclose(self) -> None: ...


class MemoryJobStore:
    def __init__(self, max_jobs: int = 100) -> None:
        self._jobs: dict[str, Job] = {}
        self._max = max_jobs

    async def save(self, job: Job) -> None:
        self._jobs[job.id] = job
        self._evict()

    async def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    async def list(self) -> list[Job]:
        return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    async def delete(self, job_id: str) -> None:
        self._jobs.pop(job_id, None)

    async def aclose(self) -> None:
        return None

    def _evict(self) -> None:
        """Descarta los jobs terminados más antiguos al superar el límite."""
        if len(self._jobs) <= self._max:
            return
        finished = sorted(
            (j for j in self._jobs.values() if j.status in TERMINAL_STATUSES),
            key=lambda j: j.updated_at,
        )
        for job in finished:
            if len(self._jobs) <= self._max:
                break
            self._jobs.pop(job.id, None)


class RedisJobStore:
    """Guarda cada job como JSON en Redis, con un índice ordenado por fecha.

    Se asume un cliente creado con `decode_responses=True`.
    """

    def __init__(self, client: Any, max_jobs: int = 100, ttl: int = 86400) -> None:
        self._client = client
        self._max = max_jobs
        self._ttl = ttl
        self._prefix = "paimon:job:"
        self._index = "paimon:jobs:index"

    def _key(self, job_id: str) -> str:
        return f"{self._prefix}{job_id}"

    async def save(self, job: Job) -> None:
        await self._client.set(self._key(job.id), job.model_dump_json(), ex=self._ttl)
        await self._client.zadd(self._index, {job.id: job.created_at})
        # Recorta el índice por rango para acotar la memoria.
        size = await self._client.zcard(self._index)
        if size > self._max:
            await self._client.zremrangebyrank(self._index, 0, size - self._max - 1)

    async def get(self, job_id: str) -> Job | None:
        raw = await self._client.get(self._key(job_id))
        return Job.model_validate_json(raw) if raw else None

    async def list(self) -> list[Job]:
        ids = await self._client.zrevrange(self._index, 0, self._max - 1)
        if not ids:
            return []
        raws = await self._client.mget([self._key(job_id) for job_id in ids])
        return [Job.model_validate_json(raw) for raw in raws if raw]

    async def delete(self, job_id: str) -> None:
        await self._client.delete(self._key(job_id))
        await self._client.zrem(self._index, job_id)

    async def aclose(self) -> None:
        await self._client.aclose()
