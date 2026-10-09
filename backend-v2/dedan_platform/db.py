"""
Database foundation for the DEDAN core platform.

Design rules (from the platform spec)
--------------------------------------
* **SQLAlchemy 2.0 declarative** so the same models run on SQLite (tests, local)
  and PostgreSQL (production) without branching.
* **UUID primary keys**, never the human-readable DEDAN ID. A sequential integer
  key leaks volume and is enumerable; the public ID must be server-generated,
  immutable and non-sequential.
* **One engine per process**, created lazily. Importing this module must never
  open a connection, so tests can point `DEDAN_DATABASE_URL` at a temp file
  before anything imports it.
* **No PHI in this module.** Tables carry structure; the health-specific payload
  lives in the profile domain so account data and health data stay separable.

Connection pooling is configured only for real databases -- SQLite does not pool
and passing pool_size to it raises.
"""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DEFAULT_DATABASE_URL = "sqlite:///./dedan_platform.db"


class Base(DeclarativeBase):
    """Declarative base for every platform table."""


def new_uuid() -> str:
    """Canonical internal identifier.

    A UUID4 hex string: unguessable and non-sequential, so a user cannot
    enumerate another's records by incrementing an id.
    """
    return uuid.uuid4().hex


def database_url() -> str:
    """Resolve the connection URL. Env wins, so tests can override."""
    return os.getenv("DEDAN_DATABASE_URL", DEFAULT_DATABASE_URL).strip() or DEFAULT_DATABASE_URL


_engine: Optional[Engine] = None
_SessionFactory: Optional[sessionmaker] = None


def _build_engine() -> Engine:
    url = database_url()
    is_sqlite = url.startswith("sqlite")

    kwargs: dict = {"future": True, "pool_pre_ping": True}
    if is_sqlite:
        # SQLite has no server-side pool and rejects pool_size/max_overflow.
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        # Sized for a stateless API tier: enough connections to serve a worker
        # without exhausting the database's connection limit at scale.
        kwargs.update(
            pool_size=int(os.getenv("DEDAN_DB_POOL_SIZE", "10")),
            max_overflow=int(os.getenv("DEDAN_DB_MAX_OVERFLOW", "20")),
            pool_recycle=int(os.getenv("DEDAN_DB_POOL_RECYCLE", "1800")),
        )

    engine = create_engine(url, **kwargs)

    if is_sqlite:
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):
            """Enable FK enforcement and WAL.

            SQLite disables foreign keys by default, so without this the
            relational constraints the whole model relies on are silently not
            applied. WAL lets the notification worker read while a request writes,
            which is what stops reminders from blocking on writes.
            """
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


def get_engine() -> Engine:
    """Process-wide engine, created on first use."""
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(
            bind=get_engine(), autoflush=False, expire_on_commit=False, future=True
        )
    return _SessionFactory


def reset_engine() -> None:
    """Dispose the engine. Used by tests that swap the database URL."""
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionFactory = None


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commit on success, roll back on any error."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_all() -> None:
    """Create tables that do not yet exist, then apply pending migrations.

    `create_all` can only emit `CREATE TABLE IF NOT EXISTS`; it cannot add a
    column to a table that already exists. Without the migration step below, a
    new column declared on a model would be silently absent from every deployed
    database that predates it -- the ORM would select a column that is not
    there, and every query against the model would fail.

    Both steps are idempotent, so this stays safe to call on every startup.
    """
    # Imported for their side effect of registering mappers on `Base.metadata`.
    from dedan_platform import models  # noqa: F401

    Base.metadata.create_all(bind=get_engine())

    # Imported here rather than at module scope: `migrations` needs
    # `get_engine` from this module, and a top-level import would be circular.
    from dedan_platform import migrations  # noqa: PLC0415

    migrations.apply_migrations()


def ensure_utc(value):
    """Coerce a datetime to UTC *before* it is written to the database.

    SQLite's DATETIME stores the wall-clock value and silently discards the UTC
    offset: writing `09:00+03:00` stores `09:00`, which `ensure_aware` then reads
    back as `09:00Z` -- three hours later than the appointment the patient
    actually booked. Every reminder for that appointment would fire three hours
    late, and the error is invisible because the value looks well-formed.

    PostgreSQL's `timestamptz` does not have this problem, so the bug only
    surfaces on SQLite -- which is exactly where the tests and local development
    run, and therefore where it hides longest.

    Normalising on the way in makes the stored value mean the same thing on both
    engines, and is what `ensure_aware` assumes when reading a naive value back.
    """
    from datetime import timezone as _tz

    if value is None:
        return None
    if value.tzinfo is None:
        # Callers are expected to reject naive input before this point (a naive
        # appointment time is ambiguous). If one reaches here it is already UTC
        # by the storage convention, so it is left alone rather than guessed at.
        return value
    return value.astimezone(_tz.utc)


def ensure_aware(value):
    """Coerce a datetime from the database to timezone-aware UTC.

    SQLite does not persist timezone information: a `DateTime(timezone=True)`
    column round-trips a value that was written as aware UTC back as *naive*.
    Comparing that to an aware `utcnow()` raises
    "can't subtract offset-naive and offset-aware datetimes".

    PostgreSQL preserves the offset, so this is a no-op there. Normalising at the
    boundary keeps every comparison in the service layer correct on both engines,
    rather than requiring each call site to remember which database it is on.

    The returned value is only correct because every write goes through
    `ensure_utc` first; without that, a value written in a non-UTC zone comes
    back shifted by its original offset.
    """
    from datetime import datetime, timezone as _tz

    if value is None:
        return None
    if value.tzinfo is None:
        # Values were written as UTC, so a naive value *is* UTC.
        return value.replace(tzinfo=_tz.utc)
    return value.astimezone(_tz.utc)
