"""API propia del módulo `resample`."""

from app.preprocessing.router_factory import build_step_router

from .processor import ResampleProcessor

router = build_step_router(ResampleProcessor)
