"""
Stage 2: health timeline service.

Pagination
----------
Cursor-based, on `(occurred_at, id)`. Offset pagination was rejected for a
specific reason: the timeline is sorted by a mutable column, so with OFFSET a
record inserted while a patient is scrolling shifts every subsequent page and
they see duplicates and gaps. A composite cursor keeps each page stable even
while new events arrive.

The cursor is opaque base64 rather than a raw tuple, so clients cannot construct
one to probe beyond their position.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from dedan_platform.db import ensure_aware, new_uuid, session_scope
from dedan_platform.models import EventStatus, HealthEvent, HealthEventType, utcnow

logger = logging.getLogger(__name__)

# Hard ceiling on page size. The API accepts a client-supplied limit, and without
# a cap a single request could ask for the entire history of a long-term patient.
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 25


class TimelineError(RuntimeError):
    """Timeline operation failed."""


def _encode_cursor(occurred_at: datetime, event_id: str) -> str:
    raw = json.dumps({"t": occurred_at.isoformat(), "i": event_id}).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> Tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        return ensure_aware(datetime.fromisoformat(data["t"])), str(data["i"])
    except (ValueError, KeyError, binascii.Error, TypeError) as exc:
        raise TimelineError("Invalid pagination cursor.") from exc


def _to_payload(event: HealthEvent) -> Dict[str, Any]:
    # SQLite returns naive datetimes; normalise so callers always get aware UTC.
    event.occurred_at = ensure_aware(event.occurred_at)
    event.created_at = ensure_aware(event.created_at)
    metadata: Dict[str, Any] = {}
    if event.metadata_json:
        try:
            metadata = json.loads(event.metadata_json)
        except json.JSONDecodeError:
            # A malformed metadata blob must not hide the event itself.
            logger.warning("timeline_metadata_unparseable", extra={"event": event.id})
            metadata = {}
    return {
        "event_id": event.id,
        "event_type": event.event_type,
        "title": event.title,
        "description": event.description,
        "status": event.status,
        "source": event.source,
        "occurred_at": event.occurred_at.isoformat(),
        "created_at": event.created_at.isoformat(),
        "conversation_id": event.conversation_id,
        "metadata": metadata,
    }


def record_event(
    user_id: str,
    event_type: str,
    title: str,
    description: Optional[str] = None,
    occurred_at: Optional[datetime] = None,
    status: str = EventStatus.COMPLETED,
    source: str = "dedan",
    metadata: Optional[Dict[str, Any]] = None,
    conversation_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Append one event to a user's timeline.

    `event_type` is validated against the closed vocabulary rather than stored
    blindly: an unknown type would be invisible to every filter in the UI.
    """
    if event_type not in HealthEventType.ALL:
        raise TimelineError(
            f"Unknown event_type '{event_type}'. Expected one of {list(HealthEventType.ALL)}."
        )
    if not (title or "").strip():
        raise TimelineError("A timeline event requires a title.")

    with session_scope() as session:
        event = HealthEvent(
            id=new_uuid(),
            user_id=user_id,
            event_type=event_type,
            title=title.strip()[:200],
            description=description,
            status=status,
            source=source,
            # Backdated records are legitimate (a result uploaded today for a
            # test taken last month), so an explicit timestamp is honoured.
            occurred_at=occurred_at or utcnow(),
            metadata_json=json.dumps(metadata) if metadata else None,
            conversation_id=conversation_id,
            correlation_id=correlation_id,
        )
        session.add(event)
        session.flush()
        return _to_payload(event)


def list_events(
    user_id: str,
    limit: int = DEFAULT_PAGE_SIZE,
    cursor: Optional[str] = None,
    event_type: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> Dict[str, Any]:
    """One page of the timeline, newest first.

    Args are all optional filters; they compose into a single indexed query rather
    than being applied in Python after a full fetch.
    """
    limit = max(1, min(int(limit or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))

    with session_scope() as session:
        stmt = select(HealthEvent).where(HealthEvent.user_id == user_id)

        if event_type:
            if event_type not in HealthEventType.ALL:
                raise TimelineError(f"Unknown event_type '{event_type}'.")
            stmt = stmt.where(HealthEvent.event_type == event_type)
        if status:
            stmt = stmt.where(HealthEvent.status == status)
        if date_from:
            stmt = stmt.where(HealthEvent.occurred_at >= ensure_aware(date_from))
        if date_to:
            stmt = stmt.where(HealthEvent.occurred_at <= ensure_aware(date_to))
        if cursor:
            c_time, c_id = _decode_cursor(cursor)
            # Strict lexicographic "older than the cursor" on the composite key.
            stmt = stmt.where(
                or_(
                    HealthEvent.occurred_at < c_time,
                    and_(
                        HealthEvent.occurred_at == c_time,
                        HealthEvent.id < c_id,
                    ),
                )
            )

        # Fetch one extra row to learn whether another page exists without a
        # second COUNT query.
        stmt = stmt.order_by(
            HealthEvent.occurred_at.desc(), HealthEvent.id.desc()
        ).limit(limit + 1)
        rows = list(session.scalars(stmt))

        has_more = len(rows) > limit
        page = rows[:limit]
        return {
            "events": [_to_payload(e) for e in page],
            "next_cursor": (
                _encode_cursor(page[-1].occurred_at, page[-1].id) if page and has_more else None
            ),
            "has_more": has_more,
            "limit": limit,
        }


def get_event(user_id: str, event_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single event, scoped to its owner.

    Scoping in the WHERE clause (not a fetch-then-compare) means a wrong-owner
    request never even loads the row.
    """
    with session_scope() as session:
        event = session.scalar(
            select(HealthEvent).where(
                HealthEvent.id == event_id, HealthEvent.user_id == user_id
            )
        )
        return _to_payload(event) if event else None


#: Appointment statuses that still mean "this visit will happen".
ACTIVE_APPOINTMENT_STATUSES = (EventStatus.SCHEDULED, EventStatus.CONFIRMED, EventStatus.RESCHEDULED)


class ProtectedEventError(RuntimeError):
    """The event is a safety record the patient cannot delete."""


#: System-generated safety records. A patient may remove what they added, but
#: not the record that DEDAN told them to seek emergency care.
PROTECTED_EVENT_TYPES = frozenset({HealthEventType.SAFETY_ALERT})


def delete_event(user_id: str, event_id: str) -> bool:
    with session_scope() as session:
        event = session.scalar(
            select(HealthEvent).where(
                HealthEvent.id == event_id, HealthEvent.user_id == user_id
            )
        )
        if event is None:
            return False
        if event.event_type in PROTECTED_EVENT_TYPES and event.source == "dedan":
            raise ProtectedEventError("Safety records cannot be deleted.")
        session.delete(event)
        return True


def update_appointment_event(
    session,
    user_id: str,
    appointment_id: str,
    status: str,
    occurred_at: Optional[datetime] = None,
) -> int:
    """Keep an appointment's timeline entry in step with the appointment.

    A cancelled appointment used to stay SCHEDULED on the timeline (and in the
    "upcoming" count), and a rescheduled one kept its old time. Runs in the
    caller's session, so the appointment and its timeline entry change in one
    transaction and cannot drift apart.
    """
    marker = json.dumps({"appointment_id": appointment_id})[1:-1]  # '"appointment_id": "<id>"'
    events = session.scalars(
        select(HealthEvent).where(
            HealthEvent.user_id == user_id,
            HealthEvent.event_type == HealthEventType.APPOINTMENT,
            HealthEvent.metadata_json.contains(marker),
        )
    ).all()
    for event in events:
        event.status = status
        if occurred_at is not None:
            event.occurred_at = occurred_at
    return len(events)


def summarise_timeline(user_id: str) -> Dict[str, Any]:
    """Counts per event type. Cheap aggregate, not a full scan into the client."""
    from sqlalchemy import func

    with session_scope() as session:
        rows = session.execute(
            select(HealthEvent.event_type, func.count(HealthEvent.id))
            .where(HealthEvent.user_id == user_id)
            .group_by(HealthEvent.event_type)
        ).all()
        counts = {event_type: count for event_type, count in rows}
        upcoming = session.scalar(
            select(func.count()).select_from(HealthEvent).where(
                HealthEvent.user_id == user_id,
                HealthEvent.status.in_(ACTIVE_APPOINTMENT_STATUSES),
                HealthEvent.occurred_at >= utcnow(),
            )
        )
    return {"total": sum(counts.values()), "by_type": counts, "upcoming": int(upcoming or 0)}
