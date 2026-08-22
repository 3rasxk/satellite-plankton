"""SQLAlchemy engine/session setup. Backend-agnostic -- see src/config.py
for the DATABASE_URL / SQLite-fallback story."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from . import config

_connect_args = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(config.DATABASE_URL, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency -- one session per request."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables if they don't exist. Called once at app startup.
    Safe to call repeatedly (SQLAlchemy checks existence first)."""
    from . import db_models  # noqa: F401  (registers models on Base.metadata)

    Base.metadata.create_all(bind=engine)
