"""
Additive schema migrations (spec §10, §13).

Why this exists
---------------
`db.create_all()` emits `CREATE TABLE IF NOT EXISTS` and nothing else. It can
create a table that does not exist yet, but it cannot add a column to a table
that already does. That is not a theoretical limit: the deployed
`dedan_platform.db` predates several columns below, so on any real database the
new columns would simply be ignored -- the model would declare them, the ORM
would select them, and every query would fail with "no such column".

Introducing Alembic for a handful of additive columns would add a dependency,
a directory of version files, and a `downgrade` story this project would not
actually use. So this module does the narrow job that is genuinely needed:

* **additive only** -- `ADD COLUMN`, backfill, `CREATE INDEX`. Nothing is
  dropped or retyped, so no data is at risk and no rollback path is required.
* **idempotent** -- every step is guarded by inspection of the live schema, so
  running it twice, on an empty database, or on a current database are all
  no-ops.
* **engine-portable** -- SQLite (tests, local) and PostgreSQL (production).

SQLite constraints worth knowing
--------------------------------
`ALTER TABLE ... ADD COLUMN` on SQLite rejects a **non-constant** default
(`DEFAULT CURRENT_TIMESTAMP` raises "Cannot add a column with non-constant
default") and rejects `NOT NULL` without a constant default. So a column being
backfilled is added nullable and then populated, rather than added with a
server-side default. Rows written afterwards always carry the value because the
ORM sets it on every insert, so the nullable-in-SQLite legacy column is never
actually left empty.

When the project adopts Alembic, each entry here becomes one revision and this
module is deleted.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from sqlalchemy import inspect, text

from dedan_platform.db import get_engine

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ColumnMigration:
    table: str
    column: str
    ddl_type: str
    #: SQL expression used to populate pre-existing rows, may bind `:now`.
    #: None means "no backfill needed" (a genuinely new, optional column).
    backfill: Optional[str] = None

    @property
    def add_column(self) -> str:
        return f"ALTER TABLE {self.table} ADD COLUMN {self.column} {self.ddl_type}"


#: Applied before indexes, because an index cannot be created over a column
#: that does not exist yet.
_COLUMN_MIGRATIONS: Tuple[ColumnMigration, ...] = (
    # Linked appointment, so cancelling/re-arming reminders is an indexed exact
    # lookup rather than a substring scan over the JSON payload.
    ColumnMigration("notifications", "appointment_id", "VARCHAR(32)"),
    # Transport-level receipt, distinguishing "we submitted this" from "the
    # provider has a record of this".
    ColumnMigration("notifications", "provider_message_id", "VARCHAR(128)"),
    # Distinguishes "never touched" from "last touched", which is what a
    # stuck-PROCESSING reconciliation query needs. Backfilled because rows that
    # predate the column would otherwise look infinitely stale.
    #
    # `TIMESTAMP WITH TIME ZONE` rather than `DATETIME`: PostgreSQL has no
    # DATETIME type, so the old DDL failed on every production database.
    # SQLite accepts any type name.
    ColumnMigration(
        "notifications", "updated_at", "TIMESTAMP WITH TIME ZONE", backfill=":now",
    ),
    # Tokens issued before this instant are rejected (password change signs
    # out other sessions). NULL for existing rows means "no cutoff yet".
    ColumnMigration("credentials", "password_changed_at", "TIMESTAMP WITH TIME ZONE"),
)

#: (index name, table, columns). Created only if absent.
_INDEX_MIGRATIONS: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    (
        "ix_notifications_appointment_id",
        "notifications",
        ("appointment_id",),
    ),
    (
        "ix_notifications_appointment_status",
        "notifications",
        ("appointment_id", "status"),
    ),
)


def _inspector(engine):
    return inspect(engine)


def _existing_columns(engine, table: str) -> set:
    try:
        return {col["name"] for col in _inspector(engine).get_columns(table)}
    except Exception:
        # Table absent: create_all() has not run yet.
        return set()


def _existing_indexes(engine, table: str) -> set:
    try:
        return {
            idx["name"] for idx in _inspector(engine).get_indexes(table)
            if idx.get("name")
        }
    except Exception:
        return set()


def _table_exists(engine, table: str) -> bool:
    try:
        return _inspector(engine).has_table(table)
    except Exception:
        return False


def pending_migrations(engine=None) -> List[str]:
    """Statements that would be applied. Read-only; safe to call at any time.

    Index statements are evaluated against the schema as it is *now*, so on a
    database missing a column the index is simply not reported yet. That is
    correct -- it cannot be created -- and `apply_migrations` re-evaluates after
    the columns land so it is created in the same run.
    """
    engine = engine or get_engine()
    statements: List[str] = []

    for migration in _COLUMN_MIGRATIONS:
        if not _table_exists(engine, migration.table):
            # create_all() owns table creation; it emits the full definition.
            continue
        if migration.column in _existing_columns(engine, migration.table):
            continue
        statements.append(migration.add_column)

    statements.extend(_pending_index_statements(engine))
    return statements


def _pending_index_statements(engine) -> List[str]:
    statements: List[str] = []
    for name, table, columns in _INDEX_MIGRATIONS:
        if not _table_exists(engine, table):
            continue
        if name in _existing_indexes(engine, table):
            continue
        present = _existing_columns(engine, table)
        if not all(column in present for column in columns):
            continue
        joined = ", ".join(columns)
        statements.append(f"CREATE INDEX {name} ON {table} ({joined})")
    return statements


def _pending_backfills(engine, now) -> List[Tuple[str, str, str]]:
    """(statement, table, column) for rows still missing the column value."""
    pending: List[Tuple[str, str, str]] = []
    for migration in _COLUMN_MIGRATIONS:
        if migration.backfill is None:
            continue
        if not _table_exists(engine, migration.table):
            continue
        if migration.column not in _existing_columns(engine, migration.table):
            continue
        statement = (
            f"UPDATE {migration.table} SET {migration.column} = :now "
            f"WHERE {migration.column} IS NULL"
        )
        pending.append((statement, migration.table, migration.column))
    return pending


def _has_nulls(engine, table: str, column: str) -> bool:
    """True when at least one row is missing this column's value."""
    from sqlalchemy import text as sa_text

    try:
        with engine.connect() as conn:
            count = conn.execute(sa_text(
                f"SELECT COUNT(*) FROM {table} WHERE {column} IS NULL"
            )).scalar()
        return bool(count)
    except Exception:
        return True  # Unknown: attempt the backfill rather than skip it.


def _execute(engine, statement: str, params: Optional[dict] = None) -> None:
    with engine.begin() as conn:
        conn.execute(text(statement), params or {})


def apply_migrations(engine=None, now=None) -> List[str]:
    """Apply pending additive migrations. Returns what was applied.

    Runs in three phases -- add columns, backfill, then create indexes -- because
    each phase's preconditions are established by the previous one.

    Idempotent, and safe to call concurrently from several API processes at
    startup: every step is guarded by schema inspection, and the residual race
    (two processes both deciding a column is missing) resolves to one winning
    ALTER and one duplicate-column error, which is absorbed rather than crashing
    startup.
    """
    from datetime import datetime, timezone

    engine = engine or get_engine()
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    applied: List[str] = []

    for migration in _COLUMN_MIGRATIONS:
        if not _table_exists(engine, migration.table):
            continue
        if migration.column in _existing_columns(engine, migration.table):
            continue
        try:
            _execute(engine, migration.add_column)
            applied.append(migration.add_column)
            logger.info("schema_migration_applied", extra={"statement": migration.add_column})
        except Exception as exc:  # noqa: BLE001
            if _is_race(exc):
                logger.info("schema_migration_raced", extra={"statement": migration.add_column})
                continue
            logger.error(
                "schema_migration_failed",
                extra={"statement": migration.add_column, "error": str(exc)},
            )
            raise

    # Backfill only after every column exists, so a partially-migrated database
    # is still repaired by a single subsequent run.
    for statement, table, column in _pending_backfills(engine, now):
        # Skip the write when nothing is actually missing, so a healthy database
        # does not run an UPDATE on every process start.
        if not _has_nulls(engine, table, column):
            continue
        _execute(engine, statement, {"now": now})
        applied.append(statement)
        logger.info("schema_backfill_applied", extra={"statement": statement})

    # Re-evaluated after the columns land, so an index over a just-added column
    # is created in this same run rather than waiting for the next startup.
    for statement in _pending_index_statements(engine):
        try:
            _execute(engine, statement)
            applied.append(statement)
            logger.info("schema_migration_applied", extra={"statement": statement})
        except Exception as exc:  # noqa: BLE001
            if _is_race(exc):
                logger.info("schema_migration_raced", extra={"statement": statement})
                continue
            logger.error(
                "schema_migration_failed", extra={"statement": statement, "error": str(exc)}
            )
            raise

    backfill_appointment_links()
    return applied


def _is_race(exc: Exception) -> bool:
    """True when the failure means another process got there first."""
    message = str(exc).lower()
    return "duplicate column" in message or "already exists" in message


def backfill_appointment_links(limit: int = 5000) -> int:
    """Populate `notifications.appointment_id` for rows enqueued before the column.

    Rows written before this column existed carry the appointment id only inside
    `payload_json`. Leaving them NULL would mean those reminders can never be
    cancelled by the new indexed lookup -- an appointment cancelled today could
    still fire a reminder that was queued last month.

    Parsed in Python rather than with `json_extract`, which needs the SQLite
    JSON1 extension and is not guaranteed to be compiled in.
    """
    import json

    from sqlalchemy import text as sa_text

    from dedan_platform.db import get_engine

    engine = get_engine()
    if not _table_exists(engine, "notifications"):
        return 0
    if "appointment_id" not in _existing_columns(engine, "notifications"):
        return 0

    try:
        with engine.connect() as conn:
            rows = conn.execute(sa_text(
                "SELECT id, payload_json FROM notifications "
                "WHERE appointment_id IS NULL AND payload_json IS NOT NULL LIMIT :limit"
            ), {"limit": limit}).fetchall()
    except Exception:
        logger.warning("appointment_link_backfill_read_failed")
        return 0

    linked = 0
    for job_id, payload_json in rows:
        try:
            appointment_id = json.loads(payload_json).get("appointment_id")
        except Exception:
            continue
        if not appointment_id:
            continue
        try:
            with engine.begin() as conn:
                conn.execute(sa_text(
                    "UPDATE notifications SET appointment_id = :aid WHERE id = :id"
                ), {"aid": appointment_id, "id": job_id})
            linked += 1
        except Exception:
            continue
    if linked:
        logger.info("appointment_links_backfilled", extra={"count": linked})
    return linked


def describe() -> Dict[str, List[str]]:
    """Human-readable status, for the operations runbook."""
    engine = get_engine()
    pending = set(pending_migrations(engine))
    everything: List[str] = [m.add_column for m in _COLUMN_MIGRATIONS]
    everything += [
        f"CREATE INDEX {name} ON {table} ({', '.join(columns)})"
        for name, table, columns in _INDEX_MIGRATIONS
    ]
    everything += [
        m.backfill and f"UPDATE {m.table} SET {m.column} = :now WHERE {m.column} IS NULL"
        for m in _COLUMN_MIGRATIONS
    ]
    return {
        "applied": [stmt for stmt in everything if stmt and stmt not in pending],
        "pending": sorted(pending),
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    applied = apply_migrations()
    if applied:
        print(f"Applied {len(applied)} migration step(s):")
        for statement in applied:
            print(f"  + {statement}")
    else:
        print("Schema is up to date; no migrations pending.")
    return 0


if __name__ == "__main__":  # pragma: no cover - operational entrypoint
    raise SystemExit(main())