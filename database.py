from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .models import Base


def _build_engine() -> Engine:
    url = settings.database_url
    kwargs: dict = {"pool_pre_ping": True, "future": True}

    if url.startswith("sqlite"):
        # The LangGraph worker runs in background threads, so the connection
        # must not be pinned to the creating thread.
        db_path = url.split("sqlite:///")[-1]
        if db_path and db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(db_path)) or ".", exist_ok=True)
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    else:
        kwargs["pool_size"] = 10
        kwargs["max_overflow"] = 20

    return create_engine(url, echo=settings.sqlalchemy_echo, **kwargs)


engine: Engine = _build_engine()


@event.listens_for(engine, "connect")
def _configure_sqlite(dbapi_connection, _record):  # pragma: no cover - backend specific
    """WAL keeps the API and the orchestration worker from blocking each other."""
    if engine.dialect.name != "sqlite":
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def session_scope() -> Session:
    """Session for background workers; the caller must close it."""
    return SessionLocal()


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
