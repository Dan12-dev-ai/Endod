"""One-off commands for encrypted health data (see crypto.py).

Run them where the master key is mounted, e.g. in the backend container::

    docker compose exec backend python -m dedan_platform.tools check
    docker compose exec backend python -m dedan_platform.tools encrypt-existing
    docker compose exec backend python -m dedan_platform.tools rotate-key --user DE123456

``encrypt-existing``
    Encrypts every clinical value still stored in plaintext (written before
    encryption), the record files stored in plaintext, and empties the
    payloads of outbox events already sent. In batches, each its own
    transaction; idempotent (run it again after an interruption). Each value
    is replaced only if it is still the one read, so a concurrent change is
    never overwritten. Plaintext stays readable meanwhile.

``check``
    Reports what is still in plaintext. Exits 1 if anything is, else 0.

``rotate-key --user <DEDAN ID or internal id>``
    Gives the patient a new data key and re-encrypts their values and files
    with it. The old key stays (inactive) to read anything written under it
    meanwhile; ``--purge-old`` then deletes it, but only once nothing uses it.

``decrypt-existing --yes``
    For a rollback to a release from before encryption only (deploy/README.md):
    writes every value and file back in plaintext. Run it with the services
    that write health data stopped, then deploy the older release at once.

Nothing these commands print or log contains health data or keys.
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Dict, Iterator, List, Optional, Tuple

from sqlalchemy import and_, func, select

from dedan_platform import crypto, eventbus, field_encryption, file_crypto, record_files
from dedan_platform.db import create_all, session_scope
from dedan_platform.models import OutboxEvent, RecordFile, RecordFileStatus, User, UserKey

logger = logging.getLogger("dedan.tools")

DEFAULT_BATCH = 500


def _columns() -> Iterator[Tuple[object, object]]:
    """(table, column) of every encrypted column."""
    for model in field_encryption.encrypted_models():
        table = model.__table__
        for name in model.__encrypted__:
            yield table, table.c[name]


def _plaintext(column):
    return and_(column.is_not(None), ~column.startswith(crypto.PREFIX, autoescape=True))


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
        for conn, rows in _batches(table, column, _plaintext(column), batch):
            keys: Dict[str, Tuple[int, bytes]] = {}
            for row_id, user_id, value in rows:
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
            report[f"{table.name}.{column.name}"] = int(conn.execute(
                select(func.count()).select_from(table).where(_plaintext(column))).scalar() or 0)
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


def _old_values(user_id: str, version: int) -> int:
    """How many of the user's values are not under ``version`` (plaintext included)."""
    count = 0
    with session_scope() as session:
        conn = session.connection()
        for table, column in _columns():
            for (value,) in conn.execute(select(column).where(table.c.user_id == user_id, column.is_not(None))):
                if crypto.key_version(value) != version:
                    count += 1
    for row_id in _stored_file_ids(user_id):
        with session_scope() as session:
            row = session.get(RecordFile, row_id)
            path = record_files.stored_path(row.record_id, row.file_id, row.copy_id) if row else None
        if path is not None and path.is_file():
            with open(path, "rb") as handle:
                if file_crypto.read_header(handle) != version:
                    count += 1
    return count


def rotate_key(identifier: str, purge_old: bool = False, batch: int = DEFAULT_BATCH, out=print) -> int:
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
                if crypto.key_version(value) == version:
                    continue
                plaintext = crypto.decrypt_field(conn, table=table.name, column=column.name, row_id=row_id,
                                                 user_id=owner, value=value)
                done += _replace(conn, table, column, row_id, value,
                                 _encrypt(conn, keys, table, column, row_id, owner, plaintext))
        if done:
            out(f"{table.name}.{column.name}: re-encrypted {done}")
    files = _rewrite_files(record_files.TO_ACTIVE_KEY, user_id)
    out(f"record files: re-encrypted {files['done']}, failed their check {files['failed']}")
    remaining = _old_values(user_id, version)
    if not purge_old:
        out(f"older key versions kept (inactive); {remaining} value(s) or file(s) still use them")
        return 0
    if remaining:
        out(f"older key versions NOT deleted: {remaining} value(s) or file(s) still use them; run again")
        return 1
    with session_scope() as session:
        deleted = session.execute(UserKey.__table__.delete().where(
            UserKey.user_id == user_id, UserKey.version != version)).rowcount
    out(f"deleted {deleted} older key version(s)")
    return 0


# --- decrypt-existing (rollback only) ----------------------------------------------------------------

def decrypt_existing(batch: int = DEFAULT_BATCH, out=print) -> Dict[str, int]:
    """Write every encrypted value and file back in plaintext (see the module doc)."""
    totals: Dict[str, int] = {}
    for table, column in _columns():
        done = 0
        for conn, rows in _batches(table, column, column.startswith(crypto.PREFIX, autoescape=True), batch):
            for row_id, user_id, value in rows:
                plaintext = crypto.decrypt_field(conn, table=table.name, column=column.name, row_id=row_id,
                                                 user_id=user_id, value=value)
                done += _replace(conn, table, column, row_id, value, plaintext)
        totals[f"{table.name}.{column.name}"] = done
        out(f"{table.name}.{column.name}: decrypted {done}")
    files = _rewrite_files(record_files.TO_PLAINTEXT)
    totals["record files"] = files["done"]
    out(f"record files: decrypted {files['done']}, failed their check {files['failed']}")
    return totals


# --- command line ------------------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(prog="python -m dedan_platform.tools", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    existing = commands.add_parser("encrypt-existing", help="encrypt what is still stored in plaintext")
    existing.add_argument("--batch", type=int, default=DEFAULT_BATCH)
    commands.add_parser("check", help="report what is still in plaintext (exit 1 if anything is)")
    rotate = commands.add_parser("rotate-key", help="give a patient a new data key and re-encrypt their data")
    rotate.add_argument("--user", required=True, help="DEDAN ID or internal user id")
    rotate.add_argument("--purge-old", action="store_true", help="then delete the old key versions, if unused")
    rotate.add_argument("--batch", type=int, default=DEFAULT_BATCH)
    decrypt = commands.add_parser("decrypt-existing",
                                  help="rollback only: write everything back in plaintext (services stopped)")
    decrypt.add_argument("--yes", action="store_true", help="confirm: health data will be stored in plaintext")
    decrypt.add_argument("--batch", type=int, default=DEFAULT_BATCH)
    args = parser.parse_args(argv)

    crypto.require_master_key()
    if args.command == "encrypt-existing":
        encrypt_existing(batch=max(1, args.batch))
        return 0
    if args.command == "check":
        create_all()
        return 1 if any(check().values()) else 0
    if args.command == "decrypt-existing":
        if not args.yes:
            print("decrypt-existing stores health data in plaintext; it is for a rollback only. Add --yes.")
            return 2
        create_all()
        decrypt_existing(batch=max(1, args.batch))
        return 0
    create_all()
    return rotate_key(args.user, purge_old=args.purge_old, batch=max(1, args.batch))


if __name__ == "__main__":  # pragma: no cover - operational entrypoint
    sys.exit(main())
