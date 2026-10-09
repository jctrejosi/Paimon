"""API propia del módulo `analyze` (también disponible como `POST /analyze`)."""

from app.preprocessing.router_factory import build_step_router

from .processor import AnalyzeProcessor

router = build_step_router(AnalyzeProcessor)
