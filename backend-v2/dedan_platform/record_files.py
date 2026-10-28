"""The platform's own copies of hospital record files (docs/history-events.md, section 2).

``record.published`` only lists a record's files; they are fetched here,
outside event handling (a background thread of the events worker), so a slow
or unreachable hospital API never holds up events:

    GET {HOSPITAL_API_URL}/platform/records/{record_id}/files/{file_id}
    X-Platform-Key: {PLATFORM_ADMIN_KEY}

Each download is checked before it is kept: the HTTP status, the declared
size (never reading past it), the SHA-256, and that the bytes really are the
declared type (PDF, JPEG, PNG or WebP, by their signature). A failure is
retried with exponential backoff; meanwhile, and after the last retry, the
record still shows, its file marked as still arriving (or unavailable).

Each download has a deadline (``DOWNLOAD_DEADLINE_SECONDS``), well inside
``STALE_DOWNLOAD``, the age after which a claimed download counts as abandoned
(its worker died) and is taken again: so two workers never fetch the same
file at once. Every claim counts as an attempt, a reclaimed one too. Nothing
a download does (a refused URL, a full disk, a database error) escapes it;
it fails that attempt only.

Each copy is encrypted as it is written, with the patient's data key
(file_crypto.py): the plaintext never touches the disk. ``sha256`` stays the
hash of the plaintext, checked while downloading and again on every read
(:func:`open_stored`).

Each stored copy has a path of its own,
``RECORD_FILES_DIR/<record_id>/<file_id>.<copy_id>`` (``copy_id``: 16 random
hex characters, kept on the row). A correction that replaces a file deletes
exactly the old copy, never one downloaded since. The ids are checked on the
way in and again here, so a path can never leave the directory.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Optional, Tuple

import httpx
from sqlalchemy import or_, select, update

from dedan_platform import crypto, file_crypto
from dedan_platform import partner_config as config
from dedan_platform.db import session_scope
from dedan_platform.models import RecordFile, RecordFileStatus, utcnow

logger = logging.getLogger(__name__)

_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_COPY = re.compile(r"^[0-9a-f]{16}$")
#: Tests replace this with an httpx.MockTransport.
_transport: Optional[httpx.BaseTransport] = None

MAX_ATTEMPTS = 12
BASE_BACKOFF_SECONDS = 30
MAX_BACKOFF_SECONDS = 6 * 3600
#: One download, from connecting to the last check, never runs longer.
DOWNLOAD_DEADLINE_SECONDS = 300.0
TIMEOUT = httpx.Timeout(30.0, connect=5.0)
#: A download claimed longer ago than this is assumed abandoned (a worker
#: died). Comfortably longer than the deadline plus one read timeout.
STALE_DOWNLOAD = timedelta(minutes=15)

_SIGNATURES = {
    "application/pdf": lambda head: head.startswith(b"%PDF-"),
    "image/jpeg": lambda head: head.startswith(b"\xff\xd8\xff"),
    "image/png": lambda head: head.startswith(b"\x89PNG\r\n\x1a\n"),
    "image/webp": lambda head: head[:4] == b"RIFF" and head[8:12] == b"WEBP",
}


class FileCheckFailed(RuntimeError):
    """The download was refused, cut short, too slow or not the file the hospital described."""


def files_dir() -> Path:
    return Path(config.record_files_dir())


def path_for(record_id: str, file_id: str, copy_id: Optional[str] = None) -> Path:
    """Where a stored copy lives (without ``copy_id``: its directory's entry for
    the file id). Refuses anything but two 32-hex ids and a 16-hex copy id."""
    if not (_HEX32.match(record_id or "") and _HEX32.match(file_id or "")):
        raise ValueError("record and file ids must be 32 lowercase hex characters")
    if copy_id is not None and not _COPY.match(copy_id):
        raise ValueError("copy ids must be 16 lowercase hex characters")
    base = files_dir().resolve()
    path = (base / record_id / (f"{file_id}.{copy_id}" if copy_id else file_id)).resolve()
    if base not in path.parents:
        raise ValueError("path escapes the records directory")
    return path


def stored_path(record_id: str, file_id: str, copy_id: Optional[str]) -> Optional[Path]:
    """The stored copy's path, or None when there is none (or an id is malformed)."""
    if not copy_id:
        return None
    try:
        return path_for(record_id, file_id, copy_id)
    except ValueError:
        return None


def forget_copy(record_id: str, file_id: str, copy_id: Optional[str]) -> None:
    """Delete one stored copy: exactly that one, and never the copy the
    file's row points to now."""
    if not copy_id:
        return
    with session_scope() as session:
        current = session.scalar(select(RecordFile.copy_id).where(
            RecordFile.record_id == record_id, RecordFile.file_id == file_id,
            RecordFile.status == RecordFileStatus.STORED))
    if current == copy_id:
        return
    try:
        path_for(record_id, file_id, copy_id).unlink(missing_ok=True)
    except (OSError, ValueError):
        logger.warning("record_file_delete_failed record=%s file=%s", record_id, file_id)


def _backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(MAX_BACKOFF_SECONDS, BASE_BACKOFF_SECONDS * 2 ** max(0, attempts - 1)))


_JOB_COLUMNS = (RecordFile.id, RecordFile.record_id, RecordFile.file_id, RecordFile.user_id, RecordFile.size,
                RecordFile.sha256, RecordFile.content_type, RecordFile.attempts)


def _claim() -> Optional[dict]:
    """Take one due file (atomically: two workers never fetch the same one),
    counting the attempt now, so a download whose worker died counts too.
    The attempt number is also the claim's token (see download_one)."""
    now = utcnow()
    due = or_(
        (RecordFile.status == RecordFileStatus.PENDING) & (RecordFile.next_attempt_at <= now),
        (RecordFile.status == RecordFileStatus.DOWNLOADING) & (RecordFile.updated_at <= now - STALE_DOWNLOAD),
    )
    with session_scope() as session:
        candidates = list(session.execute(select(RecordFile.id, RecordFile.attempts).where(due)
                                          .order_by(RecordFile.next_attempt_at).limit(5)))
        for row_id, attempts in candidates:
            # The same condition again: the loser of a race updates nothing.
            claimed = session.execute(update(RecordFile).where(
                RecordFile.id == row_id, RecordFile.attempts == attempts, due,
            ).values(status=RecordFileStatus.DOWNLOADING, attempts=attempts + 1, updated_at=now)
                .execution_options(synchronize_session=False)).rowcount
            if claimed == 1:
                row = session.execute(select(*_JOB_COLUMNS).where(RecordFile.id == row_id)).one()
                return dict(row._mapping)
    return None


def binding(record_id: str, file_id: str, user_id: str) -> file_crypto.FileBinding:
    return file_crypto.FileBinding(record_id=record_id, file_id=file_id, user_id=user_id)


def _active_key(user_id: str):
    """(version, data key) for the patient's new copies (its own short transaction)."""
    with session_scope() as session:
        return crypto.active_key(session, user_id)


def key_lookup(user_id: str, fresh: bool = False):
    """For file_crypto: the patient's data key of a given version (``fresh``:
    read from the database, not the cache)."""
    def key_for_version(version: int) -> bytes:
        with session_scope() as session:
            return crypto.data_key(session, user_id, version, fresh=fresh)
    return key_for_version


def _with_fresh_retry(user_id: str, attempt):
    """Run ``attempt(key_for_version)``; if the copy fails to decrypt, once
    more with keys read again from the database (a cached key may be stale,
    as decrypt_field does for values). A refused plaintext is not retried."""
    try:
        return attempt(key_lookup(user_id))
    except file_crypto.PlaintextRefused:
        raise
    except (file_crypto.FileCryptoError, crypto.DecryptionError):
        crypto.evict(user_id)
        return attempt(key_lookup(user_id, fresh=True))


def _encrypt_again(path: Path, *, record_id: str, file_id: str, user_id: str, version: int, data_key: bytes,
                   sha256: str, size: int) -> None:
    """Replace the copy at ``path`` by the same file encrypted under ``version``
    (checked in full first). The plaintext never touches the disk."""
    where = binding(record_id, file_id, user_id)
    temp_handle, temp_name = tempfile.mkstemp(prefix=".part-", dir=path.parent)
    temp = Path(temp_name)
    try:
        with open(path, "rb") as handle, os.fdopen(temp_handle, "wb") as out:
            def rewrite(keys):
                file_crypto.verify(handle, key_for_version=keys, binding=where, sha256=sha256, size=size)
                out.seek(0)
                out.truncate()
                encryptor = file_crypto.Encryptor(out, key=data_key, version=version, binding=where)
                for piece in file_crypto.plaintext_chunks(handle, key_for_version=keys, binding=where):
                    encryptor.write(piece)
                encryptor.close()
            _with_fresh_retry(user_id, rewrite)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _fetch(job: dict) -> Tuple[Path, int]:
    """Download into a temporary file next to the copies, encrypting as it
    arrives; return it, and the key version it is encrypted under, once
    checked. The temporary file is always removed unless returned."""
    deadline = time.monotonic() + DOWNLOAD_DEADLINE_SECONDS
    too_slow = f"took longer than {DOWNLOAD_DEADLINE_SECONDS:.0f}s"
    base_url, key = config.hospital_api_url(), config.platform_admin_key()
    url = f"{base_url}/platform/records/{job['record_id']}/files/{job['file_id']}"
    directory = path_for(job["record_id"], job["file_id"]).parent
    directory.mkdir(parents=True, exist_ok=True)
    digest, received, head = hashlib.sha256(), 0, b""
    version, data_key = _active_key(job["user_id"])
    handle, temp_name = tempfile.mkstemp(prefix=".part-", dir=directory)
    temp, kept = Path(temp_name), False
    try:
        with os.fdopen(handle, "wb") as out, httpx.Client(transport=_transport, timeout=TIMEOUT) as client:
            encryptor = file_crypto.Encryptor(out, key=data_key, version=version,
                                              binding=binding(job["record_id"], job["file_id"], job["user_id"]))
            with client.stream("GET", url, headers={"X-Platform-Key": key}) as response:
                if response.status_code != 200:
                    raise FileCheckFailed(f"hospital API answered HTTP {response.status_code}")
                for chunk in response.iter_bytes(64 * 1024):
                    if time.monotonic() > deadline:
                        raise FileCheckFailed(too_slow)
                    received += len(chunk)
                    if received > job["size"]:
                        raise FileCheckFailed("larger than the declared size")
                    if len(head) < 16:
                        head += chunk[:16 - len(head)]
                    digest.update(chunk)
                    encryptor.write(chunk)
            encryptor.close()
        if time.monotonic() > deadline:
            raise FileCheckFailed(too_slow)
        if received != job["size"]:
            raise FileCheckFailed(f"got {received} bytes, expected {job['size']}")
        if digest.hexdigest() != job["sha256"]:
            raise FileCheckFailed("sha256 does not match")
        if not _SIGNATURES[job["content_type"]](head):
            raise FileCheckFailed(f"content is not {job['content_type']}")
        kept = True
        return temp, version
    finally:
        if not kept:
            temp.unlink(missing_ok=True)


def _failed(job: dict, exc: BaseException) -> str:
    """Record a failed attempt (counted when it was claimed): retried later, or given up."""
    error = f"{type(exc).__name__}: {exc}"[:300]
    failed = job["attempts"] >= MAX_ATTEMPTS
    logger.warning("record_file_download_failed record=%s file=%s attempt=%d %s",
                   job["record_id"], job["file_id"], job["attempts"], error)
    try:
        with session_scope() as session:
            session.execute(update(RecordFile).where(
                RecordFile.id == job["id"], RecordFile.status == RecordFileStatus.DOWNLOADING,
                RecordFile.attempts == job["attempts"],
            ).values(status=RecordFileStatus.FAILED if failed else RecordFileStatus.PENDING, last_error=error,
                     next_attempt_at=utcnow() + _backoff(job["attempts"]), updated_at=utcnow())
                .execution_options(synchronize_session=False))
    except Exception:  # noqa: BLE001 -- the claim goes stale and is taken again
        logger.exception("record_file_failure_not_recorded record=%s file=%s", job["record_id"], job["file_id"])
    return "failed" if failed else "retry"


_warned_at = 0.0


def _warn_unconfigured() -> None:
    """Files cannot be fetched without the hospital service's address and key:
    say so (once an hour), rather than leave records waiting in silence."""
    global _warned_at
    if time.monotonic() - _warned_at >= 3600 or not _warned_at:
        _warned_at = time.monotonic()
        logger.warning("record_files_not_configured: set HOSPITAL_API_URL and PLATFORM_ADMIN_KEY; "
                       "record files are not being downloaded")


def download_one() -> Optional[str]:
    """Fetch one due file. Returns its outcome ("stored", "retry", "failed"),
    or None if none was due. A download's own failure never raises: it is
    recorded on its file."""
    if not (config.hospital_api_url() and config.platform_admin_key()):
        _warn_unconfigured()
        return None
    job = _claim()
    if job is None:
        return None
    if job["attempts"] > MAX_ATTEMPTS:
        # Taken again after its worker died during the last attempt.
        return _failed(job, FileCheckFailed("no attempts left"))
    copy_id = secrets.token_hex(8)
    try:
        temp, version = _fetch(job)
        moved = False
        try:
            stored = path_for(job["record_id"], job["file_id"], copy_id)
            # A path of its own: no other copy is touched, whatever happens next.
            os.replace(temp, stored)
            moved = True
        finally:
            if not moved:
                temp.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001 -- any failure fails this attempt only
        return _failed(job, exc)
    try:
        with session_scope() as session:
            # Stored under the key that is active now, not the one active when
            # the download began: the patient's keys are locked (as rotate-key
            # and purge-old-keys lock them) and, if a rotation came meanwhile,
            # the copy is encrypted again under the new key before it counts.
            # So a key's purge never strands a copy written under it.
            crypto.lock_user_keys(session, job["user_id"])
            active, active_key = crypto.active_key(session, job["user_id"])
            if active != version:
                _encrypt_again(stored, record_id=job["record_id"], file_id=job["file_id"], user_id=job["user_id"],
                               version=active, data_key=active_key, sha256=job["sha256"], size=job["size"])
            # Only if the file is still the one fetched, still this claim and
            # still this patient's (encrypted with their key): a correction may
            # have replaced, dropped or moved it meanwhile.
            done = session.execute(update(RecordFile).where(
                RecordFile.id == job["id"], RecordFile.status == RecordFileStatus.DOWNLOADING,
                RecordFile.sha256 == job["sha256"], RecordFile.attempts == job["attempts"],
                RecordFile.user_id == job["user_id"],
            ).values(status=RecordFileStatus.STORED, copy_id=copy_id, last_error=None, stored_at=utcnow(),
                     updated_at=utcnow()).execution_options(synchronize_session=False)).rowcount
    except Exception as exc:  # noqa: BLE001
        stored.unlink(missing_ok=True)
        return _failed(job, exc)
    if not done:
        stored.unlink(missing_ok=True)
        return "retry"
    logger.info("record_file_stored record=%s file=%s", job["record_id"], job["file_id"])
    return "stored"


def download_due(limit: int = 20, budget_seconds: float = 60.0) -> int:
    """Fetch due files, up to ``limit`` or the time budget. Returns how many were tried."""
    started, tried = time.monotonic(), 0
    while tried < limit and time.monotonic() - started < budget_seconds:
        if download_one() is None:
            break
        tried += 1
    return tried


def run_forever(stop: threading.Event, idle_seconds: float = 5.0) -> None:
    """The events worker's download thread."""
    while not stop.is_set():
        try:
            tried = download_due()
        except Exception:  # noqa: BLE001 -- keep downloading; each file is retried on its own
            logger.exception("record_file_round_failed")
            tried = 0
        if not tried:
            stop.wait(idle_seconds)


# --- reading, and encrypting copies stored before encryption -----------------------------------

@dataclass(frozen=True)
class StoredFile:
    """A stored copy and what is needed to open and check it."""

    path: Path
    record_id: str
    file_id: str
    user_id: str
    sha256: str
    size: int
    content_type: str
    filename: str


def stored_file(row: RecordFile) -> Optional[StoredFile]:
    """The row's stored copy (None when it has none on disk)."""
    path = stored_path(row.record_id, row.file_id, row.copy_id)
    if path is None or not path.is_file():
        return None
    return StoredFile(path=path, record_id=row.record_id, file_id=row.file_id, user_id=row.user_id,
                      sha256=row.sha256, size=row.size, content_type=row.content_type, filename=row.filename)


class StoredFileUnavailable(RuntimeError):
    """The stored copy fails its check (does not decrypt, or is not the announced file)."""


def open_stored(stored: StoredFile):
    """(plaintext stream, size) of a stored copy, verified in full (decryption
    and SHA-256) before anything is returned. Raises StoredFileUnavailable."""
    allow_plaintext = not crypto.enforced()
    try:
        return _with_fresh_retry(stored.user_id, lambda keys: file_crypto.open_verified(
            stored.path, key_for_version=keys, binding=binding(stored.record_id, stored.file_id, stored.user_id),
            sha256=stored.sha256, size=stored.size, allow_plaintext=allow_plaintext))
    except (file_crypto.FileCryptoError, crypto.CryptoError, OSError) as exc:
        logger.error("record_file_check_failed record=%s file=%s %s", stored.record_id, stored.file_id,
                     type(exc).__name__)
        raise StoredFileUnavailable(f"file {stored.file_id} of record {stored.record_id} failed its check") from None


#: rewrite_copy modes.
TO_ACTIVE_KEY, ONLY_PLAINTEXT, TO_PLAINTEXT = "active", "plaintext", "decrypt"


def rewrite_copy(row_id: str, mode: str = TO_ACTIVE_KEY) -> str:
    """Write a stored copy again as a new copy (new ``copy_id``), then switch
    the row to it and delete the old one. The old copy is checked in full
    (decryption and SHA-256) first.

    ``mode``: TO_ACTIVE_KEY (``rotate-key``: re-encrypt under the patient's
    active key), ONLY_PLAINTEXT (``encrypt-existing``: encrypt copies from
    before encryption only) or TO_PLAINTEXT (``decrypt-existing``, for a
    rollback). Returns "done", "unchanged" (nothing to do), "skipped" (not
    stored, or changed meanwhile) or "failed" (the copy fails its check).
    """
    with session_scope() as session:
        row = session.get(RecordFile, row_id)
        if row is None or row.status != RecordFileStatus.STORED:
            return "skipped"
        record_id, file_id, user_id, old_copy = row.record_id, row.file_id, row.user_id, row.copy_id
        sha256, size = row.sha256, row.size
    old_path = stored_path(record_id, file_id, old_copy)
    if old_path is None or not old_path.is_file():
        return "skipped"
    where = binding(record_id, file_id, user_id)
    with open(old_path, "rb") as handle:
        stored_version = file_crypto.read_header(handle)
        if mode == TO_PLAINTEXT:
            version = data_key = None
            if stored_version is None:
                return "unchanged"
        else:
            version, data_key = _active_key(user_id)
            if stored_version == version or (mode == ONLY_PLAINTEXT and stored_version is not None):
                return "unchanged"
        try:
            def check(lookup):
                file_crypto.verify(handle, key_for_version=lookup, binding=where, sha256=sha256, size=size)
                return lookup  # the keys that opened it, to read it again below
            keys = _with_fresh_retry(user_id, check)
        except (file_crypto.FileCryptoError, crypto.CryptoError):
            logger.error("record_file_check_failed record=%s file=%s", record_id, file_id)
            return "failed"
        new_copy = secrets.token_hex(8)
        new_path = path_for(record_id, file_id, new_copy)
        temp_handle, temp_name = tempfile.mkstemp(prefix=".part-", dir=new_path.parent)
        temp = Path(temp_name)
        try:
            with os.fdopen(temp_handle, "wb") as out:
                writer = out if data_key is None else file_crypto.Encryptor(out, key=data_key, version=version,
                                                                             binding=where)
                for piece in file_crypto.plaintext_chunks(handle, key_for_version=keys, binding=where):
                    writer.write(piece)
                if data_key is not None:
                    writer.close()
            os.replace(temp, new_path)
        finally:
            temp.unlink(missing_ok=True)
    with session_scope() as session:
        switched = session.execute(update(RecordFile).where(
            RecordFile.id == row_id, RecordFile.status == RecordFileStatus.STORED, RecordFile.copy_id == old_copy,
            RecordFile.user_id == user_id, RecordFile.sha256 == sha256,
        ).values(copy_id=new_copy, updated_at=utcnow()).execution_options(synchronize_session=False)).rowcount
    if not switched:
        new_path.unlink(missing_ok=True)
        return "skipped"
    old_path.unlink(missing_ok=True)
    return "done"
