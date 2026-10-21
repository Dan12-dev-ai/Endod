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

Files live at ``RECORD_FILES_DIR/<record_id>/<file_id>``. Both ids are 32
lowercase hex characters (checked on the way in and again here), so a path
can never leave the directory.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
import threading
import time
from datetime import timedelta
from pathlib import Path
from typing import Optional

import httpx
from sqlalchemy import or_, select, update

from dedan_platform import partner_config as config
from dedan_platform.db import session_scope
from dedan_platform.models import RecordFile, RecordFileStatus, utcnow

logger = logging.getLogger(__name__)

_HEX32 = re.compile(r"^[0-9a-f]{32}$")
#: Tests replace this with an httpx.MockTransport.
_transport: Optional[httpx.BaseTransport] = None

MAX_ATTEMPTS = 12
BASE_BACKOFF_SECONDS = 30
MAX_BACKOFF_SECONDS = 6 * 3600
#: A download claimed longer ago than this is assumed abandoned (a worker died).
STALE_DOWNLOAD = timedelta(minutes=10)
TIMEOUT = httpx.Timeout(30.0, connect=5.0)

_SIGNATURES = {
    "application/pdf": lambda head: head.startswith(b"%PDF-"),
    "image/jpeg": lambda head: head.startswith(b"\xff\xd8\xff"),
    "image/png": lambda head: head.startswith(b"\x89PNG\r\n\x1a\n"),
    "image/webp": lambda head: head[:4] == b"RIFF" and head[8:12] == b"WEBP",
}


class FileCheckFailed(RuntimeError):
    """The download was refused, cut short or not the file the hospital described."""


def files_dir() -> Path:
    return Path(config.record_files_dir())


def path_for(record_id: str, file_id: str) -> Path:
    """Where a file's copy lives. Refuses anything but two 32-hex ids."""
    if not (_HEX32.match(record_id or "") and _HEX32.match(file_id or "")):
        raise ValueError("record and file ids must be 32 lowercase hex characters")
    base = files_dir().resolve()
    path = (base / record_id / file_id).resolve()
    if base not in path.parents:
        raise ValueError("path escapes the records directory")
    return path


def delete_copy(record_id: str, file_id: str) -> None:
    try:
        path_for(record_id, file_id).unlink(missing_ok=True)
    except (OSError, ValueError):
        logger.warning("record_file_delete_failed record=%s file=%s", record_id, file_id)


def _backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(MAX_BACKOFF_SECONDS, BASE_BACKOFF_SECONDS * 2 ** max(0, attempts - 1)))


def _claim() -> Optional[dict]:
    """Take one due file (atomically: two workers never fetch the same one)."""
    now = utcnow()
    due = or_(
        (RecordFile.status == RecordFileStatus.PENDING) & (RecordFile.next_attempt_at <= now),
        (RecordFile.status == RecordFileStatus.DOWNLOADING) & (RecordFile.updated_at <= now - STALE_DOWNLOAD),
    )
    with session_scope() as session:
        candidates = list(session.scalars(select(RecordFile).where(due).order_by(RecordFile.next_attempt_at).limit(5)))
        for row in candidates:
            # The same condition again: the loser of a race updates nothing.
            claimed = session.execute(update(RecordFile).where(RecordFile.id == row.id, due).values(
                status=RecordFileStatus.DOWNLOADING, updated_at=now)
                .execution_options(synchronize_session=False)).rowcount
            if claimed == 1:
                return {"id": row.id, "record_id": row.record_id, "file_id": row.file_id, "size": row.size,
                        "sha256": row.sha256, "content_type": row.content_type, "attempts": row.attempts}
    return None


def _fetch(job: dict) -> Path:
    """Download into a temporary file next to the destination; return it once checked."""
    base_url, key = config.hospital_api_url(), config.platform_admin_key()
    url = f"{base_url}/platform/records/{job['record_id']}/files/{job['file_id']}"
    destination = path_for(job["record_id"], job["file_id"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest, received, head = hashlib.sha256(), 0, b""
    handle, temp_name = tempfile.mkstemp(prefix=".part-", dir=destination.parent)
    try:
        with os.fdopen(handle, "wb") as out, httpx.Client(transport=_transport, timeout=TIMEOUT) as client:
            with client.stream("GET", url, headers={"X-Platform-Key": key}) as response:
                if response.status_code != 200:
                    raise FileCheckFailed(f"hospital API answered HTTP {response.status_code}")
                for chunk in response.iter_bytes(64 * 1024):
                    received += len(chunk)
                    if received > job["size"]:
                        raise FileCheckFailed("larger than the declared size")
                    if len(head) < 16:
                        head += chunk[:16 - len(head)]
                    digest.update(chunk)
                    out.write(chunk)
        if received != job["size"]:
            raise FileCheckFailed(f"got {received} bytes, expected {job['size']}")
        if digest.hexdigest() != job["sha256"]:
            raise FileCheckFailed("sha256 does not match")
        if not _SIGNATURES[job["content_type"]](head):
            raise FileCheckFailed(f"content is not {job['content_type']}")
        return Path(temp_name)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def download_one() -> Optional[str]:
    """Fetch one due file. Returns its outcome ("stored", "retry", "failed"), or None if none was due."""
    if not (config.hospital_api_url() and config.platform_admin_key()):
        return None
    job = _claim()
    if job is None:
        return None
    attempts = job["attempts"] + 1
    try:
        temp = _fetch(job)
    except (FileCheckFailed, httpx.HTTPError, OSError) as exc:
        error = f"{type(exc).__name__}: {exc}"[:300]
        failed = attempts >= MAX_ATTEMPTS
        with session_scope() as session:
            session.execute(update(RecordFile).where(
                RecordFile.id == job["id"], RecordFile.status == RecordFileStatus.DOWNLOADING,
            ).values(status=RecordFileStatus.FAILED if failed else RecordFileStatus.PENDING, attempts=attempts,
                     last_error=error, next_attempt_at=utcnow() + _backoff(attempts), updated_at=utcnow())
                .execution_options(synchronize_session=False))
        logger.warning("record_file_download_failed record=%s file=%s attempt=%d %s",
                       job["record_id"], job["file_id"], attempts, error)
        return "failed" if failed else "retry"
    with session_scope() as session:
        # Only if the file is still the one we fetched (a correction may have
        # replaced or dropped it meanwhile).
        done = session.execute(update(RecordFile).where(
            RecordFile.id == job["id"], RecordFile.status == RecordFileStatus.DOWNLOADING,
            RecordFile.sha256 == job["sha256"],
        ).values(status=RecordFileStatus.STORED, attempts=attempts, last_error=None, stored_at=utcnow(),
                 updated_at=utcnow()).execution_options(synchronize_session=False)).rowcount
        if done:
            os.replace(temp, path_for(job["record_id"], job["file_id"]))
    if not done:
        temp.unlink(missing_ok=True)
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
