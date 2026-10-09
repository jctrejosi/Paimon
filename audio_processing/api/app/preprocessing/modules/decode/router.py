"""API propia del módulo `decode`."""

from app.preprocessing.router_factory import build_step_router

from .processor import DecodeProcessor

router = build_step_router(DecodeProcessor)
