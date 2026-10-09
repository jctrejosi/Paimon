"""Pruebas de los backends de jobs (store y bus), sin servidor Redis."""

from __future__ import annotations

import asyncio

import pytest

from app.jobs.events import MemoryEventBus, RedisEventBus
from app.jobs.queue import MemoryJobQueue, RedisJobQueue
from app.jobs.store import MemoryJobStore, RedisJobStore
from app.schemas import GenerateRequest, Job, JobStatus


def _job(job_id: str, status: JobStatus = "queued", created: float = 1.0) -> Job:
    return Job(
        id=job_id,
        status=status,
        provider="comfyui",
        created_at=created,
        updated_at=created,
        request=GenerateRequest(prompt="x"),
    )


def _fake_redis():  # type: ignore[no-untyped-def]
    fakeredis = pytest.importorskip("fakeredis")
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


def test_memory_store_roundtrip() -> None:
    async def scenario() -> None:
        store = MemoryJobStore(max_jobs=10)
        await store.save(_job("a"))
        assert (await store.get("a")).id == "a"  # type: ignore[union-attr]
        assert [j.id for j in await store.list()] == ["a"]
        await store.delete("a")
        assert await store.get("a") is None

    asyncio.run(scenario())


def test_memory_store_evicts_oldest_finished() -> None:
    async def scenario() -> None:
        store = MemoryJobStore(max_jobs=2)
        await store.save(_job("a", status="succeeded", created=1.0))
        await store.save(_job("b", status="succeeded", created=2.0))
        await store.save(_job("c", status="queued", created=3.0))
        # "a" es el terminado más antiguo y debe salir; "c" sigue vivo.
        remaining = {j.id for j in await store.list()}
        assert remaining == {"b", "c"}

    asyncio.run(scenario())


def test_memory_bus_delivers() -> None:
    async def scenario() -> None:
        bus = MemoryEventBus()
        subscription = await bus.subscribe("j")
        await bus.publish("j", {"status": "running"})
        message = await asyncio.wait_for(subscription.get(), 1)
        assert message["status"] == "running"
        await subscription.aclose()

    asyncio.run(scenario())


def test_redis_store_roundtrip() -> None:
    client = _fake_redis()

    async def scenario() -> None:
        store = RedisJobStore(client, max_jobs=10, ttl=60)
        await store.save(_job("a", created=1.0))
        await store.save(_job("b", created=2.0))
        assert (await store.get("a")).id == "a"  # type: ignore[union-attr]
        # Ordenadas por fecha descendente.
        assert [j.id for j in await store.list()] == ["b", "a"]
        await store.delete("a")
        assert await store.get("a") is None
        await client.aclose()

    asyncio.run(scenario())


def test_redis_bus_delivers() -> None:
    client = _fake_redis()

    async def scenario() -> None:
        bus = RedisEventBus(client)
        subscription = await bus.subscribe("j")
        await asyncio.sleep(0.05)  # deja arrancar el lector del pubsub
        await bus.publish("j", {"status": "running"})
        message = await asyncio.wait_for(subscription.get(), 2)
        assert message["status"] == "running"
        await subscription.aclose()
        await client.aclose()

    asyncio.run(scenario())


def test_memory_queue_is_fifo() -> None:
    async def scenario() -> None:
        queue = MemoryJobQueue()
        await queue.enqueue("a")
        await queue.enqueue("b")
        assert await queue.dequeue(timeout=1) == "a"
        assert await queue.dequeue(timeout=1) == "b"
        assert await queue.dequeue(timeout=0.05) is None

    asyncio.run(scenario())


def test_redis_queue_is_fifo() -> None:
    client = _fake_redis()

    async def scenario() -> None:
        queue = RedisJobQueue(client)
        await queue.enqueue("a")
        await queue.enqueue("b")
        assert await queue.dequeue(timeout=1) == "a"
        assert await queue.dequeue(timeout=1) == "b"
        await client.aclose()

    asyncio.run(scenario())
