"""API HTTP de generación de imágenes de Paimon.

Expone una interfaz estable y agnóstica al backend; el proveedor (ComfyUI local
o uno externo de pago) se elige por petición o por configuración.

Generación síncrona: `POST /generate` y `POST /edit`.
Generación asíncrona: `POST /jobs`, con consulta por `GET /jobs/{id}` y
seguimiento en vivo por SSE (`GET /jobs/{id}/events`). Webhooks opcionales.
La ejecución es inline (en este proceso) o delegada a un worker (`JOB_EXECUTION`).
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import aclosing, asynccontextmanager, suppress

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import metrics
from .config import get_settings
from .jobs import TERMINAL_STATUSES, JobManager, JobRunner, build_backends
from .providers.base import ProviderError
from .providers.registry import PROVIDER_CLASSES, ProviderManager
from .schemas import (
    GenerateRequest,
    GenerateResponse,
    HealthResponse,
    Job,
    JobCreated,
    ProviderInfo,
    ProvidersResponse,
)
from .service import run_generation
from .storage import ImageStorage

settings = get_settings()
backends = build_backends(settings)
providers = ProviderManager(settings)
storage = ImageStorage(settings.output_dir)
# En modo inline la API ejecuta los jobs; en modo worker eso lo hace otro proceso.
runner = (
    JobRunner(settings, providers, storage, backends.store, backends.bus, backends.queue)
    if settings.job_execution == "inline"
    else None
)
jobs = JobManager(settings, backends.store, backends.bus, backends.queue, runner=runner)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if runner is not None:
        # Sanea jobs colgados y arranca el ejecutor en segundo plano.
        await runner.recover()
        runner.start()
    yield
    if runner is not None:
        await runner.aclose()
    await jobs.aclose()
    await providers.aclose()


app = FastAPI(
    title="Paimon Image Generator",
    version="0.4.0",
    description="Generación y edición de imágenes con ComfyUI local o proveedores externos.",
    lifespan=lifespan,
)


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    """Rechaza pronto cuerpos que declaren superar `MAX_REQUEST_BYTES`."""
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > settings.max_request_bytes:
        return JSONResponse(
            status_code=413,
            content={"detail": f"Cuerpo demasiado grande (máx. {settings.max_request_bytes} bytes)."},
        )
    return await call_next(request)


@app.middleware("http")
async def record_http_metrics(request: Request, call_next):
    if not settings.metrics_enabled or request.url.path == "/metrics":
        return await call_next(request)
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start
    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    metrics.http_requests.labels(request.method, path, response.status_code).inc()
    metrics.http_duration.labels(request.method, path).observe(duration)
    return response


def require_token(authorization: str | None = Header(default=None)) -> None:
    """Exige `Authorization: Bearer <token>` cuando hay token configurado."""
    expected = settings.image_api_token
    if not expected:
        return
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or token != expected:
        raise HTTPException(status_code=401, detail="Token de API inválido o ausente.")


def _sse_authorized(request: Request, authorization: str | None) -> bool:
    """Para SSE se admite el token por cabecera o por `?token=`.

    `EventSource` del navegador no permite cabeceras personalizadas.
    """
    expected = settings.image_api_token
    if not expected:
        return True
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() == "bearer" and token == expected:
        return True
    return request.query_params.get("token") == expected


@app.exception_handler(ProviderError)
async def provider_error_handler(_: Request, exc: ProviderError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc), "provider": exc.provider},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {
        "service": "paimon-image-generator",
        "execution": settings.job_execution,
        "endpoints": {
            "health": "/health",
            "providers": "/providers",
            "metrics": "/metrics",
            "generate": "POST /generate",
            "edit": "POST /edit",
            "jobs_create": "POST /jobs",
            "jobs_get": "GET /jobs/{id}",
            "jobs_events": "GET /jobs/{id}/events (SSE)",
            "images": "/images/{filename}",
        },
    }


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        default_provider=settings.image_provider,
        configured_providers=providers.configured_names(),
    )


@app.get("/metrics", include_in_schema=False)
async def metrics_endpoint() -> Response:
    if not settings.metrics_enabled:
        raise HTTPException(status_code=404, detail="Métricas deshabilitadas.")
    return Response(content=metrics.render(), media_type=metrics.content_type())


@app.get("/providers", response_model=ProvidersResponse)
async def list_providers() -> ProvidersResponse:
    configured = set(providers.configured_names())
    return ProvidersResponse(
        default_provider=settings.image_provider,
        providers=[
            ProviderInfo(
                name=cls.name,
                configured=cls.is_configured(settings),
                default=(cls.name == settings.image_provider),
                supports_img2img=cls.supports_img2img,
                model=cls.default_model(settings) if cls.name in configured else None,
            )
            for cls in PROVIDER_CLASSES
        ],
    )


@app.post("/generate", response_model=GenerateResponse, dependencies=[Depends(require_token)])
async def generate(request: Request, body: GenerateRequest) -> GenerateResponse:
    return await run_generation(settings, providers, storage, body, str(request.base_url))


@app.post("/edit", response_model=GenerateResponse, dependencies=[Depends(require_token)])
async def edit(request: Request, body: GenerateRequest) -> GenerateResponse:
    """Image-to-image / edición. Igual que `/generate` pero exige `image`."""
    if body.image is None:
        raise HTTPException(
            status_code=422,
            detail="El campo 'image' es obligatorio en /edit.",
        )
    return await run_generation(settings, providers, storage, body, str(request.base_url))


@app.post(
    "/jobs",
    response_model=JobCreated,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_token)],
)
async def create_job(body: GenerateRequest) -> JobCreated:
    job = await jobs.submit(body)
    return JobCreated(id=job.id, status=job.status, provider=job.provider)


@app.get("/jobs", response_model=list[Job], dependencies=[Depends(require_token)])
async def list_jobs() -> list[Job]:
    return await jobs.list()


@app.get("/jobs/{job_id}", response_model=Job, dependencies=[Depends(require_token)])
async def get_job(job_id: str) -> Job:
    job = await jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job no encontrado.")
    return job


@app.get("/jobs/{job_id}/events")
async def job_events(
    job_id: str, request: Request, authorization: str | None = Header(default=None)
) -> StreamingResponse:
    """Flujo SSE con el estado del job: un evento por transición, hasta el final.

    El store es la fuente de verdad; el bus solo despierta al flujo antes. Si un
    evento se pierde, la re-consulta periódica (`JOB_STREAM_POLL`) lo recupera.
    """
    if not _sse_authorized(request, authorization):
        raise HTTPException(status_code=401, detail="Token de API inválido o ausente.")

    if await jobs.get(job_id) is None:
        raise HTTPException(status_code=404, detail="Job no encontrado.")

    async def event_source():
        last: str | None = None
        subscription = await jobs.subscribe(job_id)
        async with aclosing(subscription):
            while True:
                job = await jobs.get(job_id)
                if job is None:
                    return
                payload = job.model_dump(mode="json")
                serialized = json.dumps(payload)
                if serialized != last:
                    yield f"data: {serialized}\n\n"
                    last = serialized
                if payload["status"] in TERMINAL_STATUSES:
                    return
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(subscription.get(), timeout=settings.job_stream_poll)

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.delete("/jobs/{job_id}", response_model=Job, dependencies=[Depends(require_token)])
async def cancel_job(job_id: str) -> Job:
    job = await jobs.cancel(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job no encontrado.")
    return job


# Sirve las imágenes generadas. El directorio ya existe (ImageStorage lo crea).
app.mount("/images", StaticFiles(directory=str(storage.output_dir)), name="images")
