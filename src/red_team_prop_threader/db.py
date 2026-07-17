"""sqlalchemy engine factory and transaction-scoped session context manager."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
import contextlib

from sqlalchemy import event, create_engine
from sqlalchemy.orm import Session


if TYPE_CHECKING:
    from collections.abc import Generator

    from sqlalchemy import Engine


__all__ = ("build_engine", "session_scope")

_SQLITE_BUSY_TIMEOUT_MS = 5000


def build_engine(database_url: str) -> Engine:
    """Create a configured sqlalchemy engine for the given database URL.

    for sqlite, enables foreign_keys, WAL journal mode, and a busy timeout.
    for postgresql, creates a standard engine without extra configuration.

    Args:
        database_url: sqlalchemy-compatible database URL string.

    Returns:
        Engine: a configured sqlalchemy engine instance.
    """
    if database_url.startswith("sqlite"):
        engine = create_engine(database_url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
            cursor.close()

    else:
        engine = create_engine(database_url)

    return engine


@contextlib.contextmanager
def session_scope(engine: Engine) -> Generator[Session, None, None]:
    """Context manager that owns a single transaction scope.

    commits on success, rolls back on any exception, and always closes the
    session. public repository methods must not commit implicitly; use this
    manager at the call site to control transaction boundaries.

    Args:
        engine: the sqlalchemy engine to create a session from.

    Yields:
        Session: an open sqlalchemy session.

    Raises:
        Exception: any exception raised inside the block, after rollback.
    """
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
