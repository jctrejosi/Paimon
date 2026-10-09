"""Pruebas del ejecutor de jobs (JobRunner), sin red ni Redis."""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.config import Settings
from app.jobs.events import MemoryEventBus
from app.jobs.queue import MemoryJobQueue
from app.jobs.runner import JobRunner
from app.jobs.store import MemoryJobStore
from app.providers.base import ImageProvider, ProviderResult, RawImage
from app.schemas import GenerateRequest, Job, JobStatus
from app.storage import ImageStorage


class _Provider(ImageProvider):
    name = "comfyui"

    @classmethod
    def is_configured(cls, settings: Settings) -> bool:
        return True

    async def generate(self, request: GenerateRequest) -> ProviderResult:
        return ProviderResult(
            provider=self.name, model="fake", images=[RawImage(data=b"png")]
        )


class _Manager:
    """Doble mínimo de ProviderManager."""

    def __init__(self) -> None:
        self._provider = _Provider(Settings())

    def get(self, name: str) -> ImageProvider:
        return self._provider


def _job(job_id: str, status: JobStatus = "queued") -> Job:
    return Job(
        id=job_id,
        status=status,
        provider="comfyui",
        created_at=1.0,
        updated_at=1.0,
        request=GenerateRequest(prompt="x"),
    )


def test_runner_executes_queued_job(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = MemoryJobStore(10)
        runner = JobRunner(
            Settings(job_concurrency=1),
            _Manager(),  # type: ignore[arg-type]
            ImageStorage(tmp_path),
            store,
            MemoryEventBus(),
            MemoryJobQueue(),
        )
        runner.start()
        await store.save(_job("1"))
        await runner._queue.enqueue("1")

        for _ in range(100):
            await asyncio.sleep(0.02)
            job = await store.get("1")
            if job is not None and job.status == "succeeded":
                break
        final = await store.get("1")
        assert final is not None and final.status == "succeeded"
        assert final.result is not None and final.result.images
        await runner.aclose()
        await store.aclose()

    asyncio.run(scenario())


def test_runner_cancelled_while_queued_is_skipped(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = MemoryJobStore(10)
        queue = MemoryJobQueue()
        runner = JobRunner(
            Settings(job_concurrency=1),
            _Manager(),  # type: ignore[arg-type]
            ImageStorage(tmp_path),
            store,
            MemoryEventBus(),
            queue,
        )
        # No arrancamos el bucle; el job ya está cancelado cuando llegue.
        job = _job("1")
        job.status = "canceled"
        await store.save(job)
        await runner._execute("1")
        assert (await store.get("1")).status == "canceled"  # type: ignore[union-attr]
        await store.aclose()

    asyncio.run(scenario())


def test_recover_marks_stale_and_volatile(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = MemoryJobStore(10)
        runner = JobRunner(
            Settings(job_stale_after=10.0),
            _Manager(),  # type: ignore[arg-type]
            ImageStorage(tmp_path),
            store,
            MemoryEventBus(),
            MemoryJobQueue(),  # cola volátil
        )
        stale = _job("running", status="running")
        stale.heartbeat_at = 1.0  # muy antiguo
        await store.save(stale)
        await store.save(_job("queued"))
        await runner.recover()

        assert (await store.get("running")).status == "failed"  # type: ignore[union-attr]
        assert (await store.get("queued")).status == "failed"  # type: ignore[union-attr]
        await store.aclose()

    asyncio.run(scenario())
