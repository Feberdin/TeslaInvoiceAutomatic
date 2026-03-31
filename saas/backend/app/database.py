"""
Purpose: Create the SQLAlchemy engine, session factory and schema bootstrap helpers.
Input/Output: API routes and worker jobs request sessions from this module to read and write database state.
Invariants: Session handling stays centralized so API and worker use the same DB configuration.
Debug: If DB connectivity fails, inspect the effective database URL and engine-specific connection options here.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


settings = get_settings()


class Base(DeclarativeBase):
    pass


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

    Base.metadata.create_all(bind=engine)

