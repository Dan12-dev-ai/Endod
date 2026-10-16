"""
Stage 3: appointments and the reminder engine.

The rule this module enforces (spec §16)
----------------------------------------
Creating an appointment must NOT send email. It publishes a *domain event*; a
separate notification service turns that into queued jobs. Synchronous mail in a
request handler means a slow SMTP server blocks a patient-facing request, and an
email failure fails the booking -- so a patient cannot schedule a clinic
appointment because a mail server was down.

Idempotency
-----------
Reminder jobs carry a deterministic `idempotency_key`. A worker that restarts
mid-send re-reads the same key and finds the job already `SENT`, so no patient is
emailed twice. Without this, at-least-once delivery plus a retry loop equals
duplicate clinical emails.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from dedan_platform.db import ensure_aware, ensure_utc, new_uuid, session_scope
from dedan_platform.models import Appointment, EventStatus, HealthEventType, utcnow
from dedan_platform.timeline import record_event, update_appointment_event

logger = logging.getLogger(__name__)

# Status transitions. A closed map rather than free assignment, so an
# appointment cannot jump from SCHEDULED straight to COMPLETED without ever
# being confirmed -- a mistake that would silently suppress reminders.
ALLOWED_TRANSITIONS: Dict[str, set] = {
    EventStatus.SCHEDULED: {
        EventStatus.CONFIRMED, EventStatus.RESCHEDULED,
        EventStatus.CANCELLED, EventStatus.MISSED,
    },
    EventStatus.CONFIRMED: {
        EventStatus.RESCHEDULED, EventStatus.CANCELLED,
        EventStatus.COMPLETED, EventStatus.MISSED,
    },
    EventStatus.RESCHEDULED: {
        # A rescheduled appointment can be moved again; without this every
        # second reschedule failed with "RESCHEDULED to RESCHEDULED".
        EventStatus.RESCHEDULED,
        EventStatus.CONFIRMED, EventStatus.CANCELLED,
        EventStatus.COMPLETED, EventStatus.MISSED,
    },
    EventStatus.COMPLETED: set(),
    EventStatus.CANCELLED: set(),
    EventStatus.MISSED: set(),
}

# Fallback reminder offsets (seconds before the appointment) when a user has no
# preference: 7 days, 24 hours, 1 hour.
DEFAULT_REMINDER_OFFSETS = (604800, 86400, 3600)


class AppointmentError(RuntimeError):
    """Appointment operation failed."""


class AppointmentNotFound(AppointmentError):
    """No such appointment for this patient (404, whatever the operation)."""


VISIT_MODES = ("in_person", "telehealth")
#: Arrival windows, as local [start, end) hours in the appointment's timezone.
TIME_WINDOWS = {"exact": None, "morning": (8, 12), "afternoon": (12, 17), "evening": (17, 21)}


def _facility_payload(facility_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not facility_id:
        return None
    from dedan_platform.care_navigation import get_facility

    facility = get_facility(facility_id)
    if facility is None:
        return {"id": facility_id, "name": None}
    return {
        "id": facility.id, "name": facility.name, "address": facility.address,
        "city": facility.city, "country": facility.country, "phone": facility.phone,
    }


def _to_payload(appointment: Appointment) -> Dict[str, Any]:
    # Normalise on the way out so callers always get an aware timestamp.
    appointment.scheduled_at = ensure_aware(appointment.scheduled_at)
    appointment.created_at = ensure_aware(appointment.created_at)
    appointment.updated_at = ensure_aware(appointment.updated_at)
    return {
        "appointment_id": appointment.id,
        "user_id": appointment.user_id,
        "provider_id": appointment.provider_id,
        "organization_id": appointment.organization_id,
        "appointment_type": appointment.appointment_type,
        "scheduled_at": appointment.scheduled_at.isoformat(),
        "duration_minutes": appointment.duration_minutes,
        "status": appointment.status,
        "location": appointment.location,
        "meeting_url": appointment.meeting_url,
        # Older rows have no mode: a meeting link means a video visit.
        "visit_mode": appointment.visit_mode or ("telehealth" if appointment.meeting_url else "in_person"),
        "department": appointment.department,
        "time_window": appointment.time_window or "exact",
        "facility": _facility_payload(appointment.facility_id),
        "provider_name": appointment.provider_name,
        "notes": appointment.notes,
        "timezone": appointment.timezone,
        "created_at": appointment.created_at.isoformat(),
        "updated_at": appointment.updated_at.isoformat(),
    }


def parse_reminder_offsets(raw: Optional[str]) -> List[int]:
    """Every syntactically valid offset the policy names, open or not.

    Kept separate from `reminder_offsets_for` so a caller can tell the
    difference between "the policy never asked for a 24-hour reminder" and "it
    did, but the window had already closed". Collapsing both into one filtered
    list made a late booking silently lose its 24-hour reminder with nothing
    recorded, so no one could later explain the absence.
    """
    if not raw:
        return list(DEFAULT_REMINDER_OFFSETS)
    parsed: List[int] = []
    for chunk in str(raw).split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            value = int(chunk)
        except ValueError:
            logger.warning("reminder_offset_not_an_integer", extra={"value": chunk})
            continue
        if value > 0:
            parsed.append(value)
    return sorted(set(parsed))


def reminder_offsets_for(appointment: Appointment, user_preferences: Optional[str]) -> List[int]:
    """The reminder offsets whose window is still open for this appointment.

    Precedence: per-appointment override, then the user's stored preference,
    then the deployment default. Hard-coding any of these in business logic is
    what the spec forbids, so all three are data.

    Returns an **empty list** when every offset's window has already closed --
    an appointment 30 minutes away has no open 24h or 1h window. That is a real
    answer, not a failure, and it is deliberately not backfilled with the
    defaults: doing so reported three reminders scheduled for an appointment
    where zero were queued, which made the API lie to the caller about work it
    had actually done. The scheduler records the closed windows as SKIPPED so a
    non-delivery remains explainable.
    """
    raw = appointment.reminder_offsets or user_preferences
    offsets = parse_reminder_offsets(raw)
    horizon = (ensure_aware(appointment.scheduled_at) - utcnow()).total_seconds()
    # A reminder due after the appointment has started is useless and would fire
    # immediately; drop it rather than emailing at a nonsensical time.
    return [offset for offset in offsets if offset < horizon]


#: Clock skew allowed between the patient's device and the server.
_PAST_TOLERANCE = timedelta(minutes=5)


#: Status changes the patient is told about in the app inbox.
_STATUS_MESSAGES = {
    EventStatus.CONFIRMED: ("appointment_confirmed", "Appointment confirmed"),
    EventStatus.CANCELLED: ("appointment_cancelled", "Appointment cancelled"),
}


def _notify(user_id: str, kind: str, title: str, payload: Dict[str, Any]) -> None:
    """Inbox item for an appointment change (never fails the change)."""
    from dedan_platform import inbox
    from dedan_platform.email_provider import format_appointment_time

    when = format_appointment_time({
        "scheduled_at": payload.get("scheduled_at"), "timezone": payload.get("timezone"),
    })
    place = f" at {payload['location']}" if payload.get("location") else ""
    inbox.add_item(
        user_id, "appointments", kind, title, body=f"{when}{place}.",
        link_screen="appointment", link_id=payload.get("appointment_id"),
    )


def _lock_booking(session: Session, keys: List[str]) -> None:
    """Serialise bookings that could clash, until this transaction ends.

    Without it, two simultaneous requests for the same patient or provider
    could both find the slot free and both insert. On PostgreSQL this takes a
    transaction-scoped advisory lock per key (in a fixed order, so two
    requests cannot deadlock). SQLite serialises writers itself but not the
    preceding read, so it is suitable for single-user development only.
    """
    if session.bind is None or session.bind.dialect.name != "postgresql":
        return
    from sqlalchemy import text

    for key in sorted(set(keys)):
        lock_id = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big", signed=True)
        session.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": lock_id})


def _require_no_overlap(
    session: Session,
    user_id: str,
    start: datetime,
    duration_minutes: int,
    provider_id: Optional[str],
    exclude_id: Optional[str] = None,
) -> None:
    """Refuse a booking that overlaps another active one.

    Two kinds of clash: the patient cannot be in two appointments at once, and
    a provider cannot be booked twice for the same time. Both used to be
    accepted.
    """
    _lock_booking(session, [f"patient:{user_id}"] + ([f"provider:{provider_id}"] if provider_id else []))
    end = start + timedelta(minutes=duration_minutes)
    window_start = start - timedelta(minutes=480)  # longest allowed duration
    owner = Appointment.user_id == user_id
    if provider_id:
        owner = or_(owner, Appointment.provider_id == provider_id)
    query = select(Appointment).where(
        owner,
        Appointment.status.not_in(list(TERMINAL_STATUSES)),
        Appointment.scheduled_at < end,
        Appointment.scheduled_at > window_start,
    )
    if exclude_id:
        query = query.where(Appointment.id != exclude_id)
    for other in session.scalars(query):
        other_start = ensure_aware(other.scheduled_at)
        other_end = other_start + timedelta(minutes=other.duration_minutes or 30)
        if other_start < end and start < other_end:
            if other.user_id == user_id:
                raise AppointmentError("You already have an appointment at that time.")
            raise AppointmentError("That time is no longer available. Please choose another.")


def _require_future(when: datetime) -> None:
    if when < utcnow() - _PAST_TOLERANCE:
        raise AppointmentError("Appointments must be scheduled in the future.")


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise AppointmentError(
            f"Unknown timezone {name!r}; use an IANA name such as Africa/Addis_Ababa."
        ) from exc


def _validate_time_window(window: Optional[str], when: datetime, zone: ZoneInfo) -> str:
    """The window name, after checking the start time falls inside it."""
    window = (window or "exact").strip().lower()
    if window not in TIME_WINDOWS:
        raise AppointmentError(f"time_window must be one of {list(TIME_WINDOWS)}.")
    hours = TIME_WINDOWS[window]
    if hours:
        local = when.astimezone(zone)
        if not hours[0] <= local.hour < hours[1]:
            raise AppointmentError(
                f"A {window} appointment must start between {hours[0]:02d}:00 "
                f"and {hours[1]:02d}:00 local time."
            )
    return window


def _short_text(value: Optional[str], field: str, limit: int) -> Optional[str]:
    if value is None or not value.strip():
        return None
    value = value.strip()
    if len(value) > limit:
        raise AppointmentError(f"{field} must be at most {limit} characters.")
    return value


def _validate_visit(
    visit_mode: Optional[str],
    meeting_url: Optional[str],
    facility_id: Optional[str],
    location: Optional[str],
) -> Dict[str, Any]:
    """Mode, facility and place, consistent with each other."""
    meeting_url = _validate_meeting_url(meeting_url)
    mode = (visit_mode or ("telehealth" if meeting_url else "in_person")).strip().lower()
    if mode not in VISIT_MODES:
        raise AppointmentError(f"visit_mode must be one of {list(VISIT_MODES)}.")
    if mode == "in_person" and meeting_url:
        raise AppointmentError("meeting_url is only for telehealth visits.")
    location = _short_text(location, "location", 200)
    if facility_id:
        from dedan_platform.care_navigation import get_facility

        facility = get_facility(facility_id)
        if facility is None:
            raise AppointmentError("Unknown facility_id.")
        if mode == "telehealth":
            raise AppointmentError("A telehealth visit is not at a facility; leave facility_id empty.")
        if location is None:
            location = f"{facility.name}, {facility.address}, {facility.city}"[:200]
    return {"visit_mode": mode, "meeting_url": meeting_url, "facility_id": facility_id or None,
            "location": location}


def _validate_meeting_url(url: Optional[str]) -> Optional[str]:
    """Only https links. A stored `javascript:` URL would run in any page or
    email that renders it as a link."""
    if url is None or not url.strip():
        return None
    url = url.strip()
    # 500 is the column size; longer would pass here and fail at the database.
    if not url.lower().startswith("https://") or len(url) > 500:
        raise AppointmentError("meeting_url must be an https:// link.")
    return url


def create_appointment(
    user_id: str,
    scheduled_at: datetime,
    appointment_type: str = "consultation",
    provider_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    duration_minutes: int = 30,
    location: Optional[str] = None,
    meeting_url: Optional[str] = None,
    notes: Optional[str] = None,
    timezone_name: str = "UTC",
    reminder_offsets: Optional[str] = None,
    user_preferences: Optional[str] = None,
    correlation_id: Optional[str] = None,
    visit_mode: Optional[str] = None,
    department: Optional[str] = None,
    time_window: Optional[str] = None,
    facility_id: Optional[str] = None,
    provider_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist an appointment and publish the scheduling event.

    Returns the appointment plus the reminder jobs that were enqueued. No email is
    sent here -- that is the notification worker's job.
    """
    if scheduled_at.tzinfo is None:
        # A naive timestamp is ambiguous and would be interpreted as UTC, which
        # schedules the appointment at the wrong local hour for most of the world.
        raise AppointmentError("scheduled_at must include a timezone offset.")

    # Convert to UTC before persisting. SQLite drops the offset and stores the
    # wall-clock value, so writing 09:00+03:00 as-is would come back as 09:00Z
    # and quietly shift every reminder for that appointment three hours late.
    scheduled_at = ensure_utc(scheduled_at)
    _require_future(scheduled_at)
    zone = _zone(timezone_name)
    time_window = _validate_time_window(time_window, scheduled_at, zone)
    visit = _validate_visit(visit_mode, meeting_url, facility_id, location)
    meeting_url, location = visit["meeting_url"], visit["location"]
    department = _short_text(department, "department", 120)
    provider_name = _short_text(provider_name, "provider_name", 120)

    duration = max(5, min(int(duration_minutes or 30), 480))
    with session_scope() as session:
        _require_no_overlap(session, user_id, scheduled_at, duration, provider_id)
        appointment = Appointment(
            id=new_uuid(),
            user_id=user_id,
            scheduled_at=scheduled_at,
            appointment_type=appointment_type,
            provider_id=provider_id,
            organization_id=organization_id,
            duration_minutes=duration,
            location=location,
            meeting_url=meeting_url,
            visit_mode=visit["visit_mode"],
            department=department,
            time_window=time_window,
            facility_id=visit["facility_id"],
            provider_name=provider_name,
            notes=notes,
            timezone=timezone_name,
            reminder_offsets=reminder_offsets,
            correlation_id=correlation_id,
        )
        session.add(appointment)
        session.flush()
        payload = _to_payload(appointment)
        offsets = reminder_offsets_for(appointment, user_preferences)

    # Timeline entry, so the appointment appears in history (spec §28).
    record_event(
        user_id=user_id,
        event_type=HealthEventType.APPOINTMENT,
        title=f"{appointment_type.title()} appointment",
        description=notes,
        occurred_at=scheduled_at,
        status=EventStatus.SCHEDULED,
        metadata={
            "appointment_id": payload["appointment_id"],
            "location": location,
            "meeting_url": meeting_url,
            "provider_id": provider_id,
        },
        correlation_id=correlation_id,
    )

    _notify(user_id, "appointment_booked", "Appointment booked", payload)
    return {
        "appointment": payload,
        # Count of reminders the *policy* calls for. Nothing is enqueued here:
        # the API/worker layer does that, so a mail outage can never fail a
        # booking. Naming it "policy" avoids implying rows already exist.
        "reminder_policy_count": len(offsets),
        "reminder_offsets": offsets,
    }


#: Statuses after which no reminder may still be deliverable. Reaching any of
#: these means the appointment will not happen at its booked time, so an
#: unsuppressed reminder would send the patient to a clinic for a visit that
#: does not exist -- or, after COMPLETED, tell them to prepare for a
#: consultation that is already over.
TERMINAL_STATUSES = frozenset({
    EventStatus.CANCELLED, EventStatus.COMPLETED, EventStatus.MISSED,
})


def _transition(appointment: Appointment, target: str) -> None:
    if target not in ALLOWED_TRANSITIONS.get(appointment.status, set()):
        raise AppointmentError(
            f"Cannot move an appointment from {appointment.status} to {target}."
        )
    appointment.status = target
    if target == EventStatus.CANCELLED:
        appointment.cancelled_at = utcnow()


def update_status(
    user_id: str,
    appointment_id: str,
    target_status: str,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Move an appointment through its lifecycle, validating the transition.

    Suppression of reminders lives here, not in the HTTP route, because it is a
    safety invariant rather than a UI behaviour: anything that reaches a
    terminal state -- the portal's cancel button, an admin action, a future
    caller -- must stop reminders, and none of them can be trusted to remember
    to. When this lived in the route, a status change made by any other path
    leaked reminders to a patient.
    """
    if target_status not in EventStatus.ALL:
        raise AppointmentError(f"Unknown status '{target_status}'.")
    if target_status == EventStatus.RESCHEDULED:
        # Needs a new time and fresh reminders; only `reschedule` does both.
        raise AppointmentError("To reschedule, use the reschedule endpoint with the new time.")

    with session_scope() as session:
        appointment = session.scalar(
            select(Appointment).where(
                Appointment.id == appointment_id, Appointment.user_id == user_id
            )
        )
        if appointment is None:
            raise AppointmentNotFound("Appointment not found.")
        _transition(appointment, target_status)
        update_appointment_event(session, user_id, appointment_id, target_status)
        session.flush()
        payload = _to_payload(appointment)

    cancelled_reminders = 0
    if target_status in TERMINAL_STATUSES:
        # Imported lazily: `notifications` imports this module for
        # reconciliation, so a module-level import here would be circular.
        from dedan_platform import notifications

        cancelled_reminders = notifications.cancel_for_appointment(appointment_id)

    # Completion is a health-history fact, not just a booking state change.
    if target_status == EventStatus.COMPLETED:
        record_event(
            user_id=user_id,
            event_type=HealthEventType.CONSULTATION,
            title=f"{payload['appointment_type'].title()} completed",
            occurred_at=utcnow(),
            status=EventStatus.COMPLETED,
            # The patient marked their own booking completed, and its place
            # and type are what they typed: an unverified record.
            source="appointment",
            # Read by the records screen (dedan_platform.records).
            metadata={
                "appointment_id": appointment_id,
                "record": {
                    "facility_name": payload.get("location"),
                    "department": payload.get("department")
                    or payload["appointment_type"].replace("_", " ").title(),
                    "medications": [],
                },
            },
            correlation_id=correlation_id,
        )
    payload["reminders_cancelled"] = cancelled_reminders
    if target_status in _STATUS_MESSAGES:
        kind, title = _STATUS_MESSAGES[target_status]
        _notify(user_id, kind, title, payload)
    return payload


def reschedule(
    user_id: str,
    appointment_id: str,
    new_time: datetime,
    correlation_id: Optional[str] = None,
    time_window: Optional[str] = None,
) -> Dict[str, Any]:
    """Move an appointment to a new time, cancelling its obsolete reminders.

    ``time_window`` replaces the arrival window when given. Otherwise the old
    window is kept if the new time still falls inside it, and becomes "exact"
    if it does not.

    The cancel is part of this call rather than the caller's job. Rescheduling
    used to cancel in the route and re-arm nowhere, so a rescheduled appointment
    ended up with zero reminders -- the patient was told the new time and then
    heard nothing. Re-arming is left to the caller (`scheduler`) because
    scheduling is a policy action, while *not sending a stale reminder* is a
    safety invariant.
    """
    if new_time.tzinfo is None:
        raise AppointmentError("new_time must include a timezone offset.")
    new_time = ensure_utc(new_time)
    _require_future(new_time)
    from dedan_platform import notifications

    with session_scope() as session:
        appointment = session.scalar(
            select(Appointment).where(
                Appointment.id == appointment_id, Appointment.user_id == user_id
            )
        )
        if appointment is None:
            raise AppointmentNotFound("Appointment not found.")
        _require_no_overlap(
            session, user_id, new_time, appointment.duration_minutes or 30,
            appointment.provider_id, exclude_id=appointment.id,
        )
        # Rows booked before timezones were validated may hold a name that
        # is not a zone; they read as UTC rather than becoming unmovable.
        try:
            zone = _zone(appointment.timezone or "UTC")
        except AppointmentError:
            zone = ZoneInfo("UTC")
        if time_window is not None:
            appointment.time_window = _validate_time_window(time_window, new_time, zone)
        else:
            try:
                appointment.time_window = _validate_time_window(appointment.time_window, new_time, zone)
            except AppointmentError:
                appointment.time_window = "exact"
        _transition(appointment, EventStatus.RESCHEDULED)
        appointment.scheduled_at = new_time
        update_appointment_event(
            session, user_id, appointment_id, EventStatus.RESCHEDULED, occurred_at=new_time
        )
        session.flush()
        payload = _to_payload(appointment)

    # Suppress reminders for the *old* time before anything can fire them.
    # Cancelled rows keep their idempotency key, which embeds the appointment
    # instant, so re-arming against the new time creates new rows rather than
    # colliding with these.
    payload["reminders_cancelled"] = notifications.cancel_for_appointment(appointment_id)
    _notify(user_id, "appointment_rescheduled", "Appointment moved", payload)
    return payload


def get_appointment(user_id: str, appointment_id: str) -> Optional[Dict[str, Any]]:
    with session_scope() as session:
        appointment = session.scalar(
            select(Appointment).where(
                Appointment.id == appointment_id, Appointment.user_id == user_id
            )
        )
        return _to_payload(appointment) if appointment else None


def list_appointments(
    user_id: str,
    upcoming_only: bool = False,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Appointments for one user: newest first, or soonest first when
    ``upcoming_only`` (active ones in the future)."""
    limit = max(1, min(int(limit or 50), 200))
    with session_scope() as session:
        stmt = select(Appointment).where(Appointment.user_id == user_id)
        if upcoming_only:
            stmt = stmt.where(
                Appointment.scheduled_at >= utcnow(),
                Appointment.status.notin_(list(TERMINAL_STATUSES)),
            ).order_by(Appointment.scheduled_at.asc())
        else:
            stmt = stmt.order_by(Appointment.scheduled_at.desc())
        stmt = stmt.limit(limit)
        return [_to_payload(a) for a in session.scalars(stmt)]
