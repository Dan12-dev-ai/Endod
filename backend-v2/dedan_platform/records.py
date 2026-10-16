"""
Medical records: past visits with where, what was found and what was given.

Stored as CONSULTATION events on the health timeline (so they appear in the
history too), with a documented metadata shape the records screen reads:

    {"record": {"facility_name", "department", "diagnosis",
                "medications": [{"name", "dose"}], "follow_up_days",
                "follow_up_note"}}

Only records written by a clinician or a facility integration are
"verified". Records a patient enters, and visits a patient marks completed on
their own booking (whose facility and department are what the patient typed),
are kept but marked unverified.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from dedan_platform.db import ensure_aware, session_scope
from dedan_platform.models import EventStatus, HealthEvent, HealthEventType, utcnow
from dedan_platform.timeline import record_event

#: Sources whose records count as verified: trusted actors only.
VERIFIED_SOURCES = frozenset({"clinician", "facility"})
#: Accepted visit dates (a typo such as year 0001 is rejected, not stored).
EARLIEST_VISIT = datetime(1900, 1, 1, tzinfo=timezone.utc)
MAX_MEDICATIONS = 20


class RecordError(ValueError):
    pass


def _text(value: Any, field: str, limit: int, required: bool = False) -> Optional[str]:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise RecordError(f"{field} is required.")
        return None
    if not isinstance(value, str):
        raise RecordError(f"{field} must be text.")
    value = value.strip()
    if len(value) > limit:
        raise RecordError(f"{field} must be at most {limit} characters.")
    return value


def _validate(body: Dict[str, Any]) -> Dict[str, Any]:
    medications = body.get("medications") or []
    if not isinstance(medications, list) or len(medications) > MAX_MEDICATIONS:
        raise RecordError(f"medications must be a list of at most {MAX_MEDICATIONS}.")
    clean_meds = []
    for med in medications:
        if isinstance(med, str):
            med = {"name": med}
        if not isinstance(med, dict):
            raise RecordError("Each medication must be a name or {name, dose}.")
        clean_meds.append({
            "name": _text(med.get("name"), "medication name", 120, required=True),
            "dose": _text(med.get("dose"), "medication dose", 80),
        })
    follow_up = body.get("follow_up_days")
    if follow_up is not None and (
        not isinstance(follow_up, int) or isinstance(follow_up, bool) or not 0 < follow_up <= 730
    ):
        raise RecordError("follow_up_days must be a whole number from 1 to 730.")
    return {
        "facility_name": _text(body.get("facility_name"), "facility_name", 160, required=True),
        "department": _text(body.get("department"), "department", 120),
        "diagnosis": _text(body.get("diagnosis"), "diagnosis", 300),
        "medications": clean_meds,
        "follow_up_days": follow_up,
        "follow_up_note": _text(body.get("follow_up_note"), "follow_up_note", 500),
    }


def add_record(
    user_id: str,
    body: Dict[str, Any],
    occurred_at: datetime,
    source: str = "patient",
) -> Dict[str, Any]:
    """Store one visit record."""
    try:
        occurred_at = ensure_aware(occurred_at)
    except (OverflowError, ValueError) as exc:
        raise RecordError("occurred_at is not a valid date.") from exc
    if occurred_at < EARLIEST_VISIT:
        raise RecordError("occurred_at is too far in the past.")
    if occurred_at > utcnow() + timedelta(minutes=5):
        raise RecordError("A record is for a visit that has already happened.")
    record = _validate(body)
    event = record_event(
        user_id=user_id,
        event_type=HealthEventType.CONSULTATION,
        title=record["department"] or record["facility_name"],
        description=record["diagnosis"],
        occurred_at=occurred_at,
        status=EventStatus.COMPLETED,
        source=source,
        metadata={"record": record},
    )
    return _to_record(event)


def _to_record(event: Dict[str, Any]) -> Dict[str, Any]:
    record = (event.get("metadata") or {}).get("record") or {}
    occurred = datetime.fromisoformat(event["occurred_at"])
    follow_up_days = record.get("follow_up_days")
    due = occurred + timedelta(days=follow_up_days) if follow_up_days else None
    return {
        "record_id": event["event_id"],
        "occurred_at": event["occurred_at"],
        "facility_name": record.get("facility_name"),
        "department": record.get("department"),
        "diagnosis": record.get("diagnosis") or event.get("description"),
        "medications": record.get("medications") or [],
        "follow_up_days": follow_up_days,
        "follow_up_due": due.isoformat() if due else None,
        "follow_up_note": record.get("follow_up_note"),
        "verified": event.get("source") in VERIFIED_SOURCES,
        "source": event.get("source"),
    }


def list_records(user_id: str, limit: int = 100) -> Dict[str, Any]:
    """Records newest first, with the summary counts the records screen shows.

    ``limit`` caps the list only; the summary covers every record. Only
    CONSULTATION events that carry a ``record`` are records -- older
    completion events and other consultation entries are timeline-only.
    """
    from dedan_platform.timeline import _to_payload

    limit = max(1, min(limit, 200))
    with session_scope() as session:
        events = [
            _to_payload(e) for e in session.scalars(
                select(HealthEvent)
                .where(HealthEvent.user_id == user_id,
                       HealthEvent.event_type == HealthEventType.CONSULTATION)
                .order_by(HealthEvent.occurred_at.desc(), HealthEvent.id.desc())
            )
        ]
    records = [_to_record(e) for e in events if (e.get("metadata") or {}).get("record")]
    now = utcnow()
    facilities = {r["facility_name"].lower() for r in records if r["facility_name"]}
    medicines = {m["name"].lower() for r in records for m in r["medications"] if m.get("name")}
    return {
        "records": records[:limit],
        "summary": {
            "total_visits": len(records),
            "verified_records": sum(1 for r in records if r["verified"]),
            "facilities_visited": len(facilities),
            "medications_used": len(medicines),
            "active_follow_ups": sum(
                1 for r in records
                if r["follow_up_due"] and datetime.fromisoformat(r["follow_up_due"]) >= now
            ),
        },
    }
