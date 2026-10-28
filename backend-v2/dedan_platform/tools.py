"""One-off commands for encrypted health data (see crypto.py).

Run them where the master key is mounted, e.g. in the backend container.
The deploy order (deploy/README.md) is::

    docker compose exec backend python -m dedan_platform.tools encrypt-existing
    docker compose exec backend python -m dedan_platform.tools check     # exit 0
    docker compose exec backend python -m dedan_platform.tools enforce

``encrypt-existing``
    Encrypts every clinical value still stored in plaintext (written before
    encryption), the record files stored in plaintext, and empties the
    payloads of outbox events already sent. In batches, each its own
    transaction; idempotent (run it again after an interruption). Each value
    is replaced only if it is still the one read, so a concurrent change is
    never overwritten. Plaintext stays readable meanwhile.

    A value that only looks encrypted (starts with ``enc:v1:`` but is not a
    well-formed envelope) counts as plaintext.

``check``
    Reports what is still in plaintext. Exits 1 if anything is, else 0.

``enforce``
    Runs ``check`` and, only if nothing is left in plaintext, records
    ``encryption_enforced``: from then on every service refuses a stored value
    or file that is not encrypted (crypto.enforced), instead of reading it.

``rotate-key --user <DEDAN ID or internal id>``
    Gives the patient a new data key and re-encrypts their values and files
    with it. The old key stays (inactive) to read anything written under it
    meanwhile.

``purge-old-keys --user <DEDAN ID or internal id>``
    Deletes the patient's inactive key versions, once that is safe: the
    rotation is older than :data:`PURGE_GRACE` (longer than any request or
    download that could still be writing under the old key), no file of
    theirs is being downloaded or waiting to be, and no value or stored file
    uses an old version. The check and the delete are one transaction, with
    the patient's keys locked (as a download's storing step locks them).

``decrypt-existing --yes``
    For a rollback to a release from before encryption only (deploy/README.md):
    turns enforcement off, then writes every value and file back in
    plaintext. It refuses while backend, internal-api or events-worker are
    connected to the database (PostgreSQL's pg_stat_activity, by their
    application_name), so nothing writes ciphertext meanwhile; deploy the older
    release at once after it. It never deletes a key.

Nothing these commands print or log contains health data or keys.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import timedelta
from typing import Dict, Iterator, List, Optional, Tuple

from sqlalchemy import and_, func, select, text

from dedan_platform import crypto, eventbus, field_encryption, file_crypto, record_files
from dedan_platform.db import create_all, ensure_aware, session_scope
from dedan_platform.models import OutboxEvent, PlatformSetting, RecordFile, RecordFileStatus, User, UserKey, utcnow

logger = logging.getLogger("dedan.tools")

DEFAULT_BATCH = 500
#: Old keys are deleted only this long after the rotation: far longer than a
#: request, a transaction or a file download (record_files.DOWNLOAD_DEADLINE_SECONDS
#: plus its HTTP timeouts) that began before it and may still be writing under it.
PURGE_GRACE = timedelta(hours=24)


def _columns() -> Iterator[Tuple[object, object]]:
    """(table, column) of every encrypted column."""
    for model in field_encryption.encrypted_models():
        table = model.__table__
        for name in model.__encrypted__:
            yield table, table.c[name]


def _plaintext(column):
    return and_(column.is_not(None), ~column.startswith(crypto.PREFIX, autoescape=True))


def _needs_encryption(value: object) -> bool:
    """Plaintext, including a plaintext that merely starts with ``enc:v1:``."""
    return isinstance(value, str) and not crypto.parses(value)


def _count_plaintext(conn, table, column) -> int:
    count = int(conn.execute(select(func.count()).select_from(table).where(_plaintext(column))).scalar() or 0)
    # Values with the prefix: counted only if they are not a real envelope.
    for (value,) in conn.execute(select(column).where(column.startswith(crypto.PREFIX, autoescape=True))):
        count += _needs_encryption(value)
    return count


def _batches(table, column, where, batch: int) -> Iterator[Tuple[object, List[tuple]]]:
    """(connection, rows of (id, user_id, value)) in id order, one transaction per batch."""
    last_id = ""
    while True:
        with session_scope() as session:
            conn = session.connection()
            rows = conn.execute(select(table.c.id, table.c.user_id, column).where(where, table.c.id > last_id)
                                .order_by(table.c.id).limit(batch)).all()
            if not rows:
                return
            last_id = rows[-1][0]
            yield conn, rows


def _replace(conn, table, column, row_id: str, old: str, new: str) -> int:
    """Store ``new`` only if the value is still ``old`` (a concurrent change wins)."""
    return conn.execute(table.update().where(table.c.id == row_id, column == old)
                        .values({column.name: new})).rowcount


def _encrypt(conn, keys: Dict[str, Tuple[int, bytes]], table, column, row_id: str, user_id: str, plaintext: str) -> str:
    if user_id not in keys:
        keys[user_id] = crypto.active_key(conn, user_id)
    version, key = keys[user_id]
    return crypto.encrypt_value(plaintext, key=key, version=version,
                                aad=crypto.value_aad(table.name, column.name, row_id, user_id))


# --- encrypt-existing ----------------------------------------------------------------------------

def encrypt_existing(batch: int = DEFAULT_BATCH, out=print) -> Dict[str, int]:
    create_all()  # also fills prescription_items/dispenses.user_id (migrations)
    totals: Dict[str, int] = {}
    for table, column in _columns():
        name = f"{table.name}.{column.name}"
        done = without_owner = 0
        for conn, rows in _batches(table, column, column.is_not(None), batch):
            keys: Dict[str, Tuple[int, bytes]] = {}
            for row_id, user_id, value in rows:
                if not _needs_encryption(value):
                    continue
                if not user_id:
                    without_owner += 1
                    continue
                done += _replace(conn, table, column, row_id, value,
                                 _encrypt(conn, keys, table, column, row_id, user_id, value))
        totals[name] = done
        out(f"{name}: encrypted {done}" + (f", {without_owner} without an owner (left)" if without_owner else ""))
    files = _rewrite_files(record_files.ONLY_PLAINTEXT)
    totals["record files"] = files["done"]
    out(f"record files: encrypted {files['done']}, already encrypted {files['unchanged']}, "
        f"skipped {files['skipped']}, failed their check {files['failed']}")
    purged = eventbus.purge_sent_payloads()
    totals["outbox payloads"] = purged
    out(f"outbox_events: emptied {purged} sent payloads")
    return totals


def _rewrite_files(mode: str, user_id: Optional[str] = None) -> Dict[str, int]:
    outcomes = {"done": 0, "unchanged": 0, "skipped": 0, "failed": 0}
    for row_id in _stored_file_ids(user_id):
        outcomes[record_files.rewrite_copy(row_id, mode)] += 1
    return outcomes


def _stored_file_ids(user_id: Optional[str] = None) -> List[str]:
    with session_scope() as session:
        query = select(RecordFile.id).where(RecordFile.status == RecordFileStatus.STORED).order_by(RecordFile.id)
        if user_id is not None:
            query = query.where(RecordFile.user_id == user_id)
        return list(session.scalars(query))


# --- check ----------------------------------------------------------------------------------------

def check(out=print) -> Dict[str, int]:
    """What is still in plaintext (by table and column; files; sent outbox payloads)."""
    report: Dict[str, int] = {}
    with session_scope() as session:
        conn = session.connection()
        for table, column in _columns():
            report[f"{table.name}.{column.name}"] = _count_plaintext(conn, table, column)
        report["outbox_events.payload (sent)"] = int(conn.execute(select(func.count()).select_from(
            OutboxEvent.__table__).where(OutboxEvent.published_at.is_not(None),
                                         OutboxEvent.payload != eventbus.PURGED)).scalar() or 0)
        rows = list(session.scalars(select(RecordFile).where(RecordFile.status == RecordFileStatus.STORED)))
        plain_files = missing = 0
        for row in rows:
            path = record_files.stored_path(row.record_id, row.file_id, row.copy_id)
            if path is None or not path.is_file():
                missing += 1
                continue
            with open(path, "rb") as handle:
                if file_crypto.read_header(handle) is None:
                    plain_files += 1
    report["record files"] = plain_files
    for name, count in report.items():
        out(f"{'PLAINTEXT' if count else 'ok       '} {name}: {count}")
    if missing:
        out(f"note: {missing} stored record file(s) have no copy on disk")
    return report


# --- rotate-key ------------------------------------------------------------------------------------

def _resolve_user(identifier: str) -> Optional[str]:
    from dedan_platform import identity

    value = (identifier or "").strip()
    with session_scope() as session:
        try:
            dedan = identity.validate_dedan_user_id(value)
        except identity.InvalidDedanId:
            dedan = None
        user = session.scalar(select(User).where(User.dedan_user_id == dedan)) if dedan else None
        if user is None:
            user = session.get(User, value)
        return user.id if user is not None else None


def _old_values(conn, user_id: str, version: int) -> int:
    """How many of the user's values and stored files are encrypted under a
    version other than ``version``. Plaintext needs no key, so it is not counted."""
    count = 0
    for table, column in _columns():
        for (value,) in conn.execute(select(column).where(table.c.user_id == user_id, column.is_not(None))):
            if crypto.parses(value) and crypto.key_version(value) != version:
                count += 1
    for row in conn.execute(select(RecordFile.record_id, RecordFile.file_id, RecordFile.copy_id).where(
            RecordFile.user_id == user_id, RecordFile.status == RecordFileStatus.STORED)):
        path = record_files.stored_path(row[0], row[1], row[2])
        if path is not None and path.is_file():
            with open(path, "rb") as handle:
                stored_version = file_crypto.read_header(handle)
            if stored_version is not None and stored_version != version:
                count += 1
    return count


def rotate_key(identifier: str, batch: int = DEFAULT_BATCH, out=print) -> int:
    user_id = _resolve_user(identifier)
    if user_id is None:
        out("No such account.")
        return 2
    with session_scope() as session:
        version = crypto.rotate_user_key(session, user_id)
    out(f"user {user_id}: new data key version {version}")
    for table, column in _columns():
        done = 0
        for conn, rows in _batches(table, column, and_(table.c.user_id == user_id, column.is_not(None)), batch):
            keys: Dict[str, Tuple[int, bytes]] = {}
            for row_id, owner, value in rows:
                if crypto.parses(value) and crypto.key_version(value) == version:
                    continue
                plaintext = crypto.decrypt_field(conn, table=table.name, column=column.name, row_id=row_id,
                                                 user_id=owner, value=value)
                done += _replace(conn, table, column, row_id, value,
                                 _encrypt(conn, keys, table, column, row_id, owner, plaintext))
        if done:
            out(f"{table.name}.{column.name}: re-encrypted {done}")
    files = _rewrite_files(record_files.TO_ACTIVE_KEY, user_id)
    out(f"record files: re-encrypted {files['done']}, failed their check {files['failed']}")
    with session_scope() as session:
        remaining = _old_values(session.connection(), user_id, version)
    out(f"older key versions kept (inactive); {remaining} value(s) or file(s) still use them. "
        f"Delete them with purge-old-keys, no sooner than {int(PURGE_GRACE.total_seconds() // 3600)}h from now.")
    return 0


def purge_old_keys(identifier: str, out=print) -> int:
    """Delete the user's inactive key versions if it is safe (see the module doc).
    0 deleted (or nothing to delete), 1 refused, 2 no such account."""
    user_id = _resolve_user(identifier)
    if user_id is None:
        out("No such account.")
        return 2
    with session_scope() as session:
        conn = session.connection()
        crypto.lock_user_keys(conn, user_id)  # held to the delete: nothing is stored under a key meanwhile
        keys = conn.execute(select(UserKey.version, UserKey.active, UserKey.created_at).where(
            UserKey.user_id == user_id).order_by(UserKey.version.desc())).all()
        active = [k for k in keys if k.active]
        old = [k.version for k in keys if not k.active]
        if not active or not old:
            out("Nothing to delete.")
            return 0
        current = active[0]
        age = utcnow() - ensure_aware(current.created_at)
        if age < PURGE_GRACE:
            out(f"Refused: the rotation to version {current.version} is {age} old; wait until it is "
                f"{PURGE_GRACE} old, so nothing begun before it is still writing under an old key.")
            return 1
        in_flight = int(conn.execute(select(func.count()).select_from(RecordFile).where(
            RecordFile.user_id == user_id,
            RecordFile.status.in_([RecordFileStatus.PENDING, RecordFileStatus.DOWNLOADING]))).scalar() or 0)
        if in_flight:
            out(f"Refused: {in_flight} file(s) of this patient are being downloaded or waiting to be; run again later.")
            return 1
        remaining = _old_values(conn, user_id, current.version)
        if remaining:
            out(f"Refused: {remaining} value(s) or file(s) still use an old key; run rotate-key again first.")
            return 1
        with crypto.key_admin():
            deleted = conn.execute(UserKey.__table__.delete().where(
                UserKey.user_id == user_id, UserKey.active.is_(False))).rowcount
    crypto.evict(user_id)
    out(f"deleted {deleted} older key version(s): {old}")
    return 0


# --- enforce ------------------------------------------------------------------------------------------

def enforce(out=print) -> int:
    """Turn enforcement on, only if ``check`` finds no plaintext. 0 on, 1 refused."""
    report = check(out=out)
    if any(report.values()):
        out("Refused: plaintext is left (above). Run encrypt-existing, then enforce again.")
        return 1
    with session_scope() as session:
        row = session.get(PlatformSetting, crypto.ENFORCED_SETTING)
        if row is None:
            session.add(PlatformSetting(key=crypto.ENFORCED_SETTING, value="yes"))
        else:
            row.value, row.updated_at = "yes", utcnow()
    crypto.reset()
    out("encryption enforced: values and files that are not encrypted are now refused")
    return 0


def _unenforce() -> None:
    with session_scope() as session:
        session.execute(PlatformSetting.__table__.delete().where(
            PlatformSetting.key == crypto.ENFORCED_SETTING))
    crypto.reset()


# --- decrypt-existing (rollback only) ----------------------------------------------------------------

#: The services' application_name (DEDAN_DB_APPLICATION_NAME in deploy/docker-compose.yml).
SERVICE_APPLICATION_NAMES = ("endod-backend", "endod-internal-api", "endod-events-worker")


def _running_services() -> List[str]:
    """The services connected to the database now (PostgreSQL; SQLite cannot tell)."""
    with session_scope() as session:
        conn = session.connection()
        if conn.dialect.name != "postgresql":
            return []
        return sorted(conn.execute(text(
            "SELECT DISTINCT application_name FROM pg_stat_activity "
            "WHERE datname = current_database() AND pid <> pg_backend_pid() AND application_name = ANY(:names)"),
            {"names": list(SERVICE_APPLICATION_NAMES)}).scalars())


def decrypt_existing(batch: int = DEFAULT_BATCH, out=print) -> Optional[Dict[str, int]]:
    """Write every encrypted value and file back in plaintext (see the module
    doc). None, with nothing changed, if a service is still running."""
    running = _running_services()
    if running:
        out(f"Refused: {', '.join(running)} still connected to the database. Stop backend, internal-api and "
            "events-worker first (docker compose stop backend internal-api events-worker).")
        return None
    # First, or the plaintext written below would be refused.
    _unenforce()
    totals: Dict[str, int] = {}
    for table, column in _columns():
        done = 0
        for conn, rows in _batches(table, column, column.startswith(crypto.PREFIX, autoescape=True), batch):
            for row_id, user_id, value in rows:
                if not crypto.parses(value):
                    continue  # already plaintext
                plaintext = crypto.decrypt_field(conn, table=table.name, column=column.name, row_id=row_id,
                                                 user_id=user_id, value=value)
                done += _replace(conn, table, column, row_id, value, plaintext)
        totals[f"{table.name}.{column.name}"] = done
        out(f"{table.name}.{column.name}: decrypted {done}")
    files = _rewrite_files(record_files.TO_PLAINTEXT)
    totals["record files"] = files["done"]
    out(f"record files: decrypted {files['done']}, failed their check {files['failed']}")
    if files["failed"]:
        out("Some files failed their check and stay encrypted; the keys are kept (they are never deleted here).")
    return totals


# --- command line ------------------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(prog="python -m dedan_platform.tools", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    existing = commands.add_parser("encrypt-existing", help="encrypt what is still stored in plaintext")
    existing.add_argument("--batch", type=int, default=DEFAULT_BATCH)
    commands.add_parser("check", help="report what is still in plaintext (exit 1 if anything is)")
    commands.add_parser("enforce", help="after a clean check: refuse plaintext from now on")
    rotate = commands.add_parser("rotate-key", help="give a patient a new data key and re-encrypt their data")
    rotate.add_argument("--user", required=True, help="DEDAN ID or internal user id")
    rotate.add_argument("--batch", type=int, default=DEFAULT_BATCH)
    purge = commands.add_parser("purge-old-keys", help="delete a patient's old key versions, once safe")
    purge.add_argument("--user", required=True, help="DEDAN ID or internal user id")
    decrypt = commands.add_parser("decrypt-existing",
                                  help="rollback only: write everything back in plaintext (services stopped)")
    decrypt.add_argument("--yes", action="store_true", help="confirm: health data will be stored in plaintext")
    decrypt.add_argument("--batch", type=int, default=DEFAULT_BATCH)
    args = parser.parse_args(argv)

    crypto.require_master_key("tools")
    from dedan_platform import db

    if db.database_url().startswith("postgresql"):
        # Not one of the services decrypt-existing waits for, even when run
        # in the backend's container (which names its connections endod-backend).
        os.environ["DEDAN_DB_APPLICATION_NAME"] = "endod-tools"
        db.reset_engine()
    create_all()
    crypto.verify_master_key()
    if args.command == "encrypt-existing":
        encrypt_existing(batch=max(1, args.batch))
        return 0
    if args.command == "check":
        create_all()
        return 1 if any(check().values()) else 0
    if args.command == "enforce":
        create_all()
        return enforce()
    if args.command == "purge-old-keys":
        create_all()
        return purge_old_keys(args.user)
    if args.command == "decrypt-existing":
        if not args.yes:
            print("decrypt-existing stores health data in plaintext; it is for a rollback only. Add --yes.")
            return 2
        return 0 if decrypt_existing(batch=max(1, args.batch)) is not None else 1
    create_all()
    return rotate_key(args.user, batch=max(1, args.batch))


if __name__ == "__main__":  # pragma: no cover - operational entrypoint
    sys.exit(main())
