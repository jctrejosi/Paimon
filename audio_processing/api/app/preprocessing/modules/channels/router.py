"""API propia del módulo `channels`."""

from app.preprocessing.router_factory import build_step_router

from .processor import ChannelsProcessor

router = build_step_router(ChannelsProcessor)
