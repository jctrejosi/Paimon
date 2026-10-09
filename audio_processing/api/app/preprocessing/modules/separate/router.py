"""API propia del módulo `separate`."""

from app.preprocessing.router_factory import build_step_router

from .processor import SeparateProcessor

router = build_step_router(SeparateProcessor)
