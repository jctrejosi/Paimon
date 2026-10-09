"""Selección de los backends de jobs según la configuración."""

from __future__ import annotations

from typing import Any, NamedTuple

from ..config import Settings
from .events import EventBus, MemoryEventBus, RedisEventBus
from .queue import JobQueue, MemoryJobQueue, RedisJobQueue
from .store import JobStore, MemoryJobStore, RedisJobStore


class JobBackends(NamedTuple):
    store: JobStore
    bus: EventBus
    queue: JobQueue


def build_backends(settings: Settings) -> JobBackends:
    if settings.job_store == "redis":
        client = _redis_client(settings.redis_url)
        return JobBackends(
            store=RedisJobStore(client, settings.jobs_max, settings.jobs_ttl),
            bus=RedisEventBus(client),
            queue=RedisJobQueue(client),
        )
    return JobBackends(
        store=MemoryJobStore(settings.jobs_max),
        bus=MemoryEventBus(),
        queue=MemoryJobQueue(),
    )


def _redis_client(url: str) -> Any:
    try:
        from redis.asyncio import Redis
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise RuntimeError(
            "JOB_STORE=redis requiere el paquete 'redis' (pip install redis)."
        ) from exc
    # decode_responses: los backends asumen str, no bytes.
    return Redis.from_url(url, decode_responses=True)
