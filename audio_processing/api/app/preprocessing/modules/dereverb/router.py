"""API propia del módulo `dereverb`."""

from app.preprocessing.router_factory import build_step_router

from .processor import DereverbProcessor

router = build_step_router(DereverbProcessor)
