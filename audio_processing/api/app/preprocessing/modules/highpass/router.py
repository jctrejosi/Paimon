"""API propia del módulo `highpass`."""

from app.preprocessing.router_factory import build_step_router

from .processor import HighpassProcessor

router = build_step_router(HighpassProcessor)
