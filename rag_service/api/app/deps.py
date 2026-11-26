"""Dependencias compartidas de la API (proyecto → base aislada → servicio)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings, get_settings
from .db import validate_project
from .service import RagService

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_project(
    settings: SettingsDep,
    x_rag_project: Annotated[str | None, Header(alias="X-RAG-Project")] = None,
    project: Annotated[str | None, Query()] = None,
) -> str:
    """Proyecto de la petición: header `X-RAG-Project`, query `project` o default."""
    value = x_rag_project or project or settings.default_project
    try:
        return validate_project(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


ProjectDep = Annotated[str, Depends(get_project)]


async def get_session(request: Request, project: ProjectDep) -> AsyncIterator[AsyncSession]:
    """Sesión sobre la base aislada del proyecto (schema/archivo propio)."""
    database = await request.app.state.databases.get(project)
    async with database.session_factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_rag_service(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    project: ProjectDep,
) -> RagService:
    return RagService(
        session=session,
        settings=settings,
        embedder=request.app.state.embedder,
        reranker=request.app.state.reranker,
        project=project,
    )


ServiceDep = Annotated[RagService, Depends(get_rag_service)]
