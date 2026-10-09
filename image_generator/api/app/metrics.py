"""Métricas Prometheus.

Un único registro por proceso. La API lo expone en `/metrics`; el worker levanta
su propio servidor en `METRICS_PORT` (con `start_http_server`).
"""

from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client import start_http_server as _start_http_server

registry = CollectorRegistry()

http_requests = Counter(
    "paimon_http_requests_total",
    "Peticiones HTTP atendidas.",
    ["method", "path", "status"],
    registry=registry,
)
http_duration = Histogram(
    "paimon_http_request_duration_seconds",
    "Duración de las peticiones HTTP.",
    ["method", "path"],
    registry=registry,
)
generations = Counter(
    "paimon_generations_total",
    "Llamadas a un proveedor (síncronas y de jobs).",
    ["provider", "status"],
    registry=registry,
)
jobs_submitted = Counter(
    "paimon_jobs_submitted_total",
    "Jobs encolados.",
    ["provider"],
    registry=registry,
)
jobs_completed = Counter(
    "paimon_jobs_completed_total",
    "Jobs terminados.",
    ["provider", "status"],
    registry=registry,
)
job_duration = Histogram(
    "paimon_job_duration_seconds",
    "Duración de los jobs ejecutados.",
    ["provider"],
    registry=registry,
)
jobs_running = Gauge(
    "paimon_jobs_running",
    "Jobs en ejecución ahora mismo.",
    registry=registry,
)


def render() -> bytes:
    return generate_latest(registry)


def content_type() -> str:
    return CONTENT_TYPE_LATEST


def start_http_server(port: int) -> None:
    """Sirve `/metrics` en segundo plano (para el proceso worker)."""
    _start_http_server(port, registry=registry)
