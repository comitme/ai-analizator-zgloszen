"""Engine and session factory.

The only place that knows we are on SQLite. Swapping to PostgreSQL is a change of
``DATABASE_URL`` - that portability comes from SQLAlchemy, not from any cleverness
here, and the README says so plainly.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from .schema import Base

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def init_engine(database_url: str, *, echo: bool = False) -> Engine:
    """Create the engine and tables. Idempotent within a process."""
    global _engine, _SessionFactory

    if database_url.startswith("sqlite:///") and ":memory:" not in database_url:
        # Make sure the parent directory exists before SQLite tries to open the file.
        Path(database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)

    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    _engine = create_engine(database_url, echo=echo, connect_args=connect_args, future=True)
    _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False)
    Base.metadata.create_all(_engine)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Engine not initialised - call init_engine() during startup.")
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commit on success, roll back on any exception."""
    if _SessionFactory is None:
        raise RuntimeError("Engine not initialised - call init_engine() during startup.")
    session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
