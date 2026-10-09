"""Jobs asíncronos: gestión (encolar/consultar) y ejecución.

`JobManager` es la cara que usa la API: crea el job, lo persiste y lo encola; no
ejecuta nada por sí mismo. La ejecución vive en `JobRunner` (ver `runner.py`),
que puede correr en este mismo proceso (modo inline) o en un worker aparte.

El estado se delega en un `JobStore` (memoria o Redis), el trabajo en una
`JobQueue` y las notificaciones en vivo en un `EventBus`.
"""

from __future__ import annotations

import time
import uuid

from .. import metrics
from ..config import Settings
from ..schemas import GenerateRequest, Job
from .backends import build_backends
from .events import EventBus, Subscription
from .queue import JobQueue
from .runner import JobRunner
from .store import TERMINAL_STATUSES, JobStore

__all__ = ["TERMINAL_STATUSES", "JobManager", "JobRunner", "build_backends"]


class JobManager:
    def __init__(
        self,
        settings: Settings,
        store: JobStore,
        bus: EventBus,
        queue: JobQueue,
        runner: JobRunner | None = None,
    ) -> None:
        self._settings = settings
        self._store = store
        self._bus = bus
        self._queue = queue
        # Solo en modo inline: permite cancelar la tarea local al instante.
        self._runner = runner

    # --- API pública ------------------------------------------------------
    async def submit(self, body: GenerateRequest) -> Job:
        now = time.time()
        job = Job(
            id=str(uuid.uuid4()),
            status="queued",
            provider=body.provider or self._settings.image_provider,
            created_at=now,
            updated_at=now,
            request=body,
            webhook_url=body.webhook_url,
        )
        await self._store.save(job)
        await self._queue.enqueue(job.id)
        await self._bus.publish(job.id, job.model_dump(mode="json"))
        metrics.jobs_submitted.labels(job.provider).inc()
        return job

    async def get(self, job_id: str) -> Job | None:
        return await self._store.get(job_id)

    async def list(self) -> list[Job]:
        return await self._store.list()

    async def cancel(self, job_id: str) -> Job | None:
        job = await self._store.get(job_id)
        if job is None:
            return None
        if job.status not in TERMINAL_STATUSES:
            job.status = "canceled"
            job.updated_at = time.time()
            await self._store.save(job)
            await self._bus.publish(job.id, job.model_dump(mode="json"))
            if self._runner is not None:
                self._runner.cancel_local(job_id)
        return job

    async def subscribe(self, job_id: str) -> Subscription:
        return await self._bus.subscribe(job_id)

    async def aclose(self) -> None:
        await self._store.aclose()
        await self._bus.aclose()
        await self._queue.aclose()
