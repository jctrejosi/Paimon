"""API propia del módulo `normalize`."""

from app.preprocessing.router_factory import build_step_router

from .processor import NormalizeProcessor

router = build_step_router(NormalizeProcessor)
