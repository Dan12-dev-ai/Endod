"""Rate limits counted in the database, so every process and replica shares them.

The same approach as the SMS-code limits in phone_auth: an attempt is
recorded *before* the limit is checked, and the check counts rows that
include it. Simultaneous attempts, from any process, therefore see each
other: none can slip through a check that ran before the others were
recorded.

* :func:`begin` records one attempt in each bucket and raises :class:`Limited`
  (taking the attempt back) when any bucket is over its limit.
* :func:`forget` takes attempts back: for limits that count failures only, the
  caller forgets an attempt that succeeded.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Dict, List

from sqlalchemy import delete, func, select

from dedan_platform.db import ensure_aware, new_uuid, session_scope
from dedan_platform.models import ThrottleHit, utcnow

WINDOW = timedelta(hours=1)


class Limited(Exception):
    """Over a limit; ``retry_after`` is in seconds."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("Too many attempts. Try again later.")
        self.retry_after = retry_after


def begin(limits: Dict[str, int], window: timedelta = WINDOW) -> List[str]:
    """Count one attempt in each bucket (``{bucket: limit}``); returns the
    attempts' ids. Raises :class:`Limited` when a bucket already held
    ``limit`` attempts in the window (this attempt is then not counted)."""
    now = utcnow()
    ids: List[str] = []
    with session_scope() as session:
        # Old attempts are never needed again.
        session.execute(delete(ThrottleHit).where(ThrottleHit.at < now - 2 * window))
        for bucket in limits:
            hit_id = new_uuid()
            session.add(ThrottleHit(id=hit_id, bucket=bucket[:120], at=now))
            ids.append(hit_id)
    retry_after = 0
    with session_scope() as session:
        for bucket, limit in limits.items():
            since = now - window
            count = session.scalar(select(func.count()).select_from(ThrottleHit).where(
                ThrottleHit.bucket == bucket[:120], ThrottleHit.at > since)) or 0
            if count > limit:
                oldest = session.scalar(select(func.min(ThrottleHit.at)).where(
                    ThrottleHit.bucket == bucket[:120], ThrottleHit.at > since))
                wait = int((ensure_aware(oldest) + window - now).total_seconds()) + 1 if oldest else 60
                retry_after = max(retry_after, wait, 1)
    if retry_after:
        forget(ids)
        raise Limited(retry_after)
    return ids


def forget(ids: List[str]) -> None:
    """Take attempts back (they succeeded, and only failures count)."""
    if not ids:
        return
    with session_scope() as session:
        session.execute(delete(ThrottleHit).where(ThrottleHit.id.in_(ids)))
