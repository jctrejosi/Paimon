"""Proceso worker: consume la cola de jobs y ejecuta las generaciones.

Se arranca con `python -m app.worker`. Comparte estado con la API a través de
Redis (`JOB_STORE=redis`), de modo que puedes escalar ejecución con varias
réplicas de worker. Expone `/metrics` en `METRICS_PORT`.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from . import metrics
from .config import get_settings
from .jobs import JobRunner, build_backends
from .providers.registry import ProviderManager
from .storage import ImageStorage

logger = logging.getLogger("paimon.worker")


async def _run() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    backends = build_backends(settings)
    providers = ProviderManager(settings)
    storage = ImageStorage(settings.output_dir)
    runner = JobRunner(
        settings, providers, storage, backends.store, backends.bus, backends.queue
    )

    if settings.metrics_enabled:
        metrics.start_http_server(settings.metrics_port)
        logger.info("Métricas en http://0.0.0.0:%s/metrics", settings.metrics_port)

    if settings.job_store != "redis":
        logger.warning(
            "JOB_STORE=%s: el worker no compartirá estado con la API. "
            "Usa JOB_STORE=redis en un despliegue con worker.",
            settings.job_store,
        )

    await runner.recover()
    runner.start()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # pragma: no cover - Windows
            pass

    logger.info("Worker listo (concurrencia=%s).", settings.job_concurrency)
    await stop.wait()

    logger.info("Parando worker…")
    await runner.aclose()
    await providers.aclose()
    await backends.store.aclose()


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:  # pragma: no cover - parada manual
        pass


if __name__ == "__main__":
    main()
