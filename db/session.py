"""
Engine + session management. One engine per process, pooled, reused
everywhere via get_session(). Never construct a new engine per-call.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://qrc:qrc@localhost:5432/quant_research_copilot",
)

# QueuePool defaults are fine for a project this size, but sized
# explicitly here so the choice is visible rather than implicit.
engine = create_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,   # avoids "server closed the connection" after idle
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@contextmanager
def get_session() -> Iterator[Session]:
    """
    Context-managed session with an explicit transaction boundary:
    commits on clean exit, rolls back on exception, always closes.
    Use this for anything that needs 'extraction + its critic review
    commit atomically' style guarantees — do the whole unit of work
    inside one `with get_session() as session:` block.
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
