"""
Notification read surface (spec §9).

Patients can see what was sent to them and why something was not. That is a
clinical-support requirement, not a nicety: the first question a patient asks
after a missed reminder is "did you send it, and what did it say?".

Ownership model
---------------
Every route resolves the recipient from the authenticated token via
`current_user_id`; none accepts a user id as a parameter. That mirrors the
`/users/me/...` convention the rest of the platform uses and keeps ownership
unrequestable (see `TestAuthorization.test_no_route_accepts_a_user_id`).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from dedan_platform.api_profile import current_user_id
from dedan_platform.db import ensure_aware, session_scope
from dedan_platform.models import Notification, NotificationStatus

logger = logging.getLogger(__name__)

router = APIRouter(tags=["notifications"])


def _serialise(job: Notification) -> Dict[str, Any]:
    """Render one notification.

    Deliberately does NOT expose `payload_json`, `destination` or `last_error`.
    The payload is logistics-only by construction but it is queue internals, and
    `destination` plus `last_error` (which can embed a provider response) would
    turn a read endpoint into a way to harvest a patient's address or to probe
    the mail provider. A patient needs status and timing, not that.
    """
    return {
        "notification_id": job.id,
        "appointment_id": job.appointment_id,
        "channel": job.channel,
        "template": job.template,
        "status": job.status,
        "scheduled_for": ensure_aware(job.scheduled_for).isoformat(),
        "sent_at": ensure_aware(job.sent_at).isoformat() if job.sent_at else None,
        "attempts": job.attempts,
        "created_at": ensure_aware(job.created_at).isoformat(),
        "updated_at": ensure_aware(job.updated_at).isoformat(),
    }


@router.get("/users/me/notifications")
def list_notifications(
    user_id: str = Depends(current_user_id),
    limit: int = Query(default=25, ge=1, le=100),
    status_filter: Optional[str] = Query(default=None, alias="status"),
) -> Dict[str, Any]:
    """Notifications addressed to the authenticated patient, newest first."""
    if status_filter is not None and status_filter not in NotificationStatus.ALL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown notification status '{status_filter}'.",
        )
    with session_scope() as session:
        stmt = select(Notification).where(Notification.user_id == user_id)
        if status_filter:
            stmt = stmt.where(Notification.status == status_filter)
        stmt = stmt.order_by(Notification.scheduled_for.desc()).limit(limit)
        items = [_serialise(job) for job in session.scalars(stmt)]

    return {
        "notifications": items,
        "count": len(items),
        # Summary counts over the whole owned set, not just this page, so the
        # UI can show "2 failed" without paginating the entire history first.
        "summary": _summary(user_id),
    }


@router.get("/users/me/notifications/{notification_id}")
def read_notification(
    notification_id: str, user_id: str = Depends(current_user_id)
) -> Dict[str, Any]:
    with session_scope() as session:
        job = session.scalar(
            select(Notification).where(
                Notification.id == notification_id, Notification.user_id == user_id
            )
        )
        if job is None:
            # 404, not 403: a correct id belonging to someone else must be
            # indistinguishable from one that does not exist.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found."
            )
        return _serialise(job)


def _summary(user_id: str) -> Dict[str, int]:
    from sqlalchemy import func

    with session_scope() as session:
        rows = session.execute(
            select(Notification.status, func.count(Notification.id))
            .where(Notification.user_id == user_id)
            .group_by(Notification.status)
        ).all()
    counts = {value: 0 for value in NotificationStatus.ALL}
    for value, count in rows:
        counts[value] = count
    return counts