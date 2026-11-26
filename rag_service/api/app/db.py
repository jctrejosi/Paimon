"""Base de datos del servicio RAG con **aislamiento por proyecto**.

Cada proyecto (chatbot-platform, tesis, etc.) tiene su propio espacio físico
dentro de la base interna del servicio:

- **PostgreSQL** (contenedor `paimon-rag-db`): un *schema* por proyecto, p. ej.
  `rag_chatbot_platform`, `rag_tesis`. El servicio traduce las tablas sin
  calificar al schema del proyecto mediante `schema_translate_map`.
- **SQLite** (desarrollo/tests): un archivo por proyecto bajo
  `PROJECT_DATA_DIR/<proyecto>.db`.

Dentro de cada proyecto, `bot_id` sigue separando sub-espacios (p. ej. cada
bot de chatbot-platform).
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import Settings
from .models import Base

_PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,49}$")


def validate_project(project: str) -> str:
    """Normaliza y valida el identificador de proyecto."""
    value = (project or "").strip().lower()
    if not _PROJECT_RE.fullmatch(value):
        raise ValueError(
            "proyecto inválido: usa minúsculas, números, guion o guion_bajo "
            "(máx. 50 caracteres)"
        )
    return value


def schema_name(project: str, prefix: str) -> str:
    """Nombre del schema PostgreSQL para un proyecto."""
    suffix = project.replace("-", "_")
    return f"{prefix}{suffix}"


@dataclass
class ProjectDatabase:
    project: str
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]


class DatabaseManager:
    """Crea y cachea una base (schema/archivo) independiente por proyecto."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._projects: dict[str, ProjectDatabase] = {}
        self._lock = asyncio.Lock()

    async def get(self, project: str) -> ProjectDatabase:
        project = validate_project(project)
        async with self._lock:
            existing = self._projects.get(project)
            if existing is not None:
                return existing
            database = await self._create(project)
            self._projects[project] = database
            return database

    async def _create(self, project: str) -> ProjectDatabase:
        if self._settings.is_postgres:
            schema = schema_name(project, self._settings.schema_prefix)
            engine = create_async_engine(
                self._settings.database_url,
                pool_pre_ping=True,
                # Todas las tablas sin schema se resuelven en el schema del proyecto.
                execution_options={"schema_translate_map": {None: schema}},
            )
            async with engine.begin() as conn:
                await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
                await conn.run_sync(Base.metadata.create_all)
        else:
            path = self._settings.project_data_dir / f"{project}.db"
            path.parent.mkdir(parents=True, exist_ok=True)
            engine = create_async_engine(
                f"sqlite+aiosqlite:///{Path(path).as_posix()}"
            )
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

        return ProjectDatabase(
            project=project,
            engine=engine,
            session_factory=async_sessionmaker(engine, expire_on_commit=False),
        )

    async def close(self) -> None:
        for database in self._projects.values():
            await database.engine.dispose()
        self._projects.clear()

    def known_projects(self) -> list[str]:
        return sorted(self._projects)
