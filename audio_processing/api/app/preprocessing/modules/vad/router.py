"""API propia del módulo `vad`."""

from app.preprocessing.router_factory import build_step_router

from .processor import VadProcessor

router = build_step_router(VadProcessor)
