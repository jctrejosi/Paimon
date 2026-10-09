"""API propia del módulo `denoise`."""

from app.preprocessing.router_factory import build_step_router

from .processor import DenoiseProcessor

router = build_step_router(DenoiseProcessor)
