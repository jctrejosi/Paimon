"""API propia del módulo `diarize`."""

from app.preprocessing.router_factory import build_step_router

from .processor import DiarizeProcessor

router = build_step_router(DiarizeProcessor)
