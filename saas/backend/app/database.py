"""
Purpose: Create the SQLAlchemy engine, session factory and schema bootstrap helpers.
Input/Output: API routes and worker jobs request sessions from this module to read and write database state.
Invariants: Session handling stays centralized so API and worker use the same DB configuration.
Debug: If DB connectivity fails, inspect the effective database URL and engine-specific connection options here.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


settings = get_settings()


class Base(DeclarativeBase):
    pass


def _ensure_sqlite_directory_exists(database_url: str) -> None:
    """Prepare the parent directory for SQLite URLs before SQLAlchemy connects."""

    sqlite_prefix = "sqlite:///"
    if not database_url.startswith(sqlite_prefix):
        return

    database_path = database_url.removeprefix(sqlite_prefix)
    if not database_path or database_path == ":memory:":
        return

    # Unraid bind mounts can appear slightly later than the process starts, so we create the directory proactively.
    Path(database_path).expanduser().parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_directory_exists(settings.database_url)


engine = create_engine(
    settings.database_url,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


def get_db_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def create_database() -> None:
    from app import models  # noqa: F401

    _ensure_sqlite_directory_exists(settings.database_url)
    Base.metadata.create_all(bind=engine)
