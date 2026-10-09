"""Ejecutor de jobs: consume la cola y corre las generaciones.

Se usa de dos formas:

* **inline**: la propia API lo arranca como tarea de fondo (`JOB_EXECUTION=inline`).
* **worker**: un proceso dedicado (`python -m app.worker`, `JOB_EXECUTION=worker`).

Mantiene un latido (`heartbeat_at`) mientras un job corre, de modo que la
recuperación puede detectar workers caídos. La cancelación es cooperativa: si un
job ya está en ejecución, se respeta la cancelación al terminar la generación.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress

import httpx

from .. import metrics
from ..config import Settings
from ..providers.base import ProviderError
from ..providers.registry import ProviderManager
from ..schemas import Job, JobStatus
from ..service import run_generation
from ..storage import ImageStorage
from .events import EventBus
from .queue import JobQueue
from .store import TERMINAL_STATUSES, JobStore

logger = logging.getLogger("paimon.jobs")


class JobRunner:
    def __init__(
        self,
        settings: Settings,
        manager: ProviderManager,
        storage: ImageStorage,
        store: JobStore,
        bus: EventBus,
        queue: JobQueue,
    ) -> None:
        self._settings = settings
        self._providers = manager
        self._storage = storage
        self._store = store
        self._bus = bus
        self._queue = queue
        # Se (re)crean en start() para quedar atados al bucle correcto.
        self._semaphore: asyncio.Semaphore | None = None
        self._stopping: asyncio.Event | None = None
        self._tasks: dict[str, asyncio.Task] = {}
        self._loop_task: asyncio.Task | None = None
        self._webhooks: httpx.AsyncClient | None = None

    # --- ciclo de vida ----------------------------------------------------
    def start(self) -> None:
        if self._loop_task is not None:
            return
        self._stopping = asyncio.Event()
        self._semaphore = asyncio.Semaphore(max(1, self._settings.job_concurrency))
        self._webhooks = httpx.AsyncClient(timeout=self._settings.webhook_timeout)
        self._loop_task = asyncio.create_task(self._run_forever())

    async def aclose(self) -> None:
        if self._stopping is not None:
            self._stopping.set()
        # Cancelamos el bucle de consumo (deja de tomar trabajos nuevos)…
        if self._loop_task is not None:
            self._loop_task.cancel()
            await asyncio.gather(self._loop_task, return_exceptions=True)
            self._loop_task = None
        # …y damos un margen a los jobs en curso antes de cancelarlos.
        if self._tasks:
            _done, pending = await asyncio.wait(
                set(self._tasks.values()), timeout=self._settings.job_shutdown_grace
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        if self._webhooks is not None:
            await self._webhooks.aclose()
            self._webhooks = None

    async def recover(self) -> None:
        """Sanea jobs que quedaron colgados de una ejecución anterior."""
        now = time.time()
        for job in await self._store.list():
            if job.status == "running" and (
                job.heartbeat_at is None
                or now - job.heartbeat_at > self._settings.job_stale_after
            ):
                await self._mark(job, "failed", "Interrumpido: worker caído (sin latido).")
            elif job.status == "queued" and not self._queue.durable:
                await self._mark(job, "failed", "Interrumpido por reinicio (cola volátil).")

    def cancel_local(self, job_id: str) -> None:
        """Cancela la tarea local si el job se está ejecutando en este proceso."""
        task = self._tasks.get(job_id)
        if task is not None:
            task.cancel()

    # --- bucle ------------------------------------------------------------
    async def _run_forever(self) -> None:
        logger.info("Ejecutor de jobs escuchando la cola…")
        assert self._stopping is not None
        while not self._stopping.is_set():
            job_id = await self._queue.dequeue(timeout=1.0)
            if job_id is None:
                continue
            assert self._semaphore is not None
            await self._semaphore.acquire()
            task = asyncio.create_task(self._guarded(job_id))
            self._tasks[job_id] = task
            task.add_done_callback(lambda _t, jid=job_id: self._tasks.pop(jid, None))

    async def _guarded(self, job_id: str) -> None:
        try:
            await self._execute(job_id)
        finally:
            assert self._semaphore is not None
            self._semaphore.release()

    # --- ejecución --------------------------------------------------------
    async def _execute(self, job_id: str) -> None:
        job = await self._store.get(job_id)
        if job is None or job.status in TERMINAL_STATUSES:
            return

        metrics.jobs_running.inc()
        started = time.time()
        heartbeat: asyncio.Task | None = None
        try:
            job.status = "running"
            job.heartbeat_at = time.time()
            job.updated_at = job.heartbeat_at
            await self._persist_and_publish(job)
            heartbeat = asyncio.create_task(self._heartbeat_loop(job_id))

            result = await run_generation(
                self._settings, self._providers, self._storage, job.request, base_url=None
            )

            # Si el cliente canceló mientras generábamos, respetamos la cancelación.
            latest = await self._store.get(job_id)
            if latest is not None and latest.status == "canceled":
                return

            job.result = result
            job.status = "succeeded"
        except asyncio.CancelledError:
            job.status = "canceled"
            job.updated_at = time.time()
            await self._persist_and_publish(job)
            raise
        except ProviderError as exc:
            job.status = "failed"
            job.error = str(exc)
        except Exception as exc:
            job.status = "failed"
            job.error = f"Error inesperado: {exc}"
            logger.exception("Job %s falló inesperadamente", job.id)
        finally:
            if heartbeat is not None:
                heartbeat.cancel()
                with suppress(asyncio.CancelledError):
                    await heartbeat
            metrics.jobs_running.dec()

        job.heartbeat_at = None
        job.updated_at = time.time()
        await self._persist_and_publish(job)
        metrics.jobs_completed.labels(job.provider, job.status).inc()
        metrics.job_duration.labels(job.provider).observe(time.time() - started)
        await self._deliver_webhook(job)

    async def _heartbeat_loop(self, job_id: str) -> None:
        while True:
            await asyncio.sleep(self._settings.job_heartbeat_interval)
            job = await self._store.get(job_id)
            if job is None or job.status in TERMINAL_STATUSES:
                return
            job.heartbeat_at = time.time()
            await self._store.save(job)

    async def _mark(self, job: Job, status: JobStatus, error: str | None = None) -> None:
        job.status = status
        job.error = error
        job.updated_at = time.time()
        await self._persist_and_publish(job)

    async def _persist_and_publish(self, job: Job) -> None:
        await self._store.save(job)
        await self._bus.publish(job.id, job.model_dump(mode="json"))

    async def _deliver_webhook(self, job: Job) -> None:
        if not job.webhook_url or self._webhooks is None:
            return
        try:
            resp = await self._webhooks.post(job.webhook_url, json=job.model_dump(mode="json"))
            job.webhook_delivered = resp.status_code < 400
        except httpx.HTTPError as exc:
            logger.warning("Webhook del job %s falló: %s", job.id, exc)
            job.webhook_delivered = False
        # Persistimos el resultado de la entrega (sin volver a publicar).
        await self._store.save(job)
