"""What partner hospitals send about a patient (docs/history-events.md).

Handlers for the hospital service's events, run by the events worker in the
event's transaction (see eventbus): links (section 1), clinical records and
their files (2), follow-ups (3) and queue places (4). Each is idempotent and
safe to receive out of order:

* a record keeps its highest ``version``; a retraction hides it for good;
* a follow-up keeps the newest change, by the time the hospital sent it;
* a queue place keeps its highest ``seq``; texts are deduplicated per entry
  and notice (``patient_sms``), so a retried event never texts twice.

Inbox items open their own session, so they are written after the commit
(``eventbus.after_commit``); texts and timeline entries are written in the
event's own transaction.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Literal, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dedan_platform import eventbus, identity, patient_sms
from dedan_platform.db import ensure_aware, ensure_utc
from dedan_platform.eventbus import PermanentEventError, RetryLater
from dedan_platform.models import (
    Appointment, EventStatus, FollowUp, HealthEvent, HealthEventType, HospitalLink, HospitalRecord,
    PartnerHospital, Profile, QueueEntry, RecordFile, RecordFileStatus, User, utcnow,
)
from dedan_platform.phone import normalise_ethiopian_mobile

logger = logging.getLogger(__name__)

HEX32 = r"^[0-9a-f]{32}$"
DEFAULT_ZONE = "Africa/Addis_Ababa"

CATEGORIES = ("diagnosis", "prescription", "lab_result", "imaging", "visit_note", "document")
FILE_TYPES = ("application/pdf", "image/jpeg", "image/png", "image/webp")
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_FILES = 10

#: What the patient's inbox calls each kind of record.
_CATEGORY_NOUN = {
    "diagnosis": "diagnosis", "prescription": "prescription", "lab_result": "lab result",
    "imaging": "imaging result", "visit_note": "visit note", "document": "document",
}


def _parse(model, payload: Dict[str, Any]):
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise PermanentEventError(str(exc).splitlines()[0] + ": " + str(exc.errors()[0].get("loc"))) from exc


def _user_by_dedan(session: Session, dedan_id: Optional[str]) -> Optional[User]:
    try:
        normalised = identity.validate_dedan_user_id(dedan_id or "")
    except identity.InvalidDedanId:
        return None
    return session.scalar(select(User).where(User.dedan_user_id == normalised))


def _full_name(profile: Optional[Profile], fallback: str) -> str:
    if profile is None:
        return fallback
    names = [profile.first_name, profile.middle_name, profile.last_name]
    return (" ".join(n for n in names if n) or profile.display_name or fallback)[:160]


def _zone(session: Session, hospital_id: str) -> ZoneInfo:
    hospital = session.get(PartnerHospital, hospital_id)
    try:
        return ZoneInfo(hospital.timezone if hospital is not None else DEFAULT_ZONE)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_ZONE)


def _inbox_later(session: Session, user_id: str, kind: str, title: str, body: Optional[str],
                 link_screen: Optional[str], link_id: Optional[str]) -> None:
    def write() -> None:
        from dedan_platform import inbox

        inbox.add_item(user_id, "records", kind, title, body=body, link_screen=link_screen, link_id=link_id)

    eventbus.after_commit(session, write)


# --- 1. linking -------------------------------------------------------------------------------

class LinkRequest(BaseModel):
    request_id: str = Field(pattern=HEX32)
    hospital_id: str = Field(min_length=1, max_length=32)
    patient_id: str = Field(min_length=1, max_length=64)
    dedan_id: str = Field(min_length=1, max_length=16)
    card_signature: Optional[str] = Field(default=None, max_length=128)
    phone: Optional[str] = Field(default=None, max_length=32)


def _card_verifies(dedan_id: str, signature: Optional[str]) -> bool:
    if not signature:
        return False
    from dedan_platform import cards

    try:
        return cards.verify_card(dedan_id, signature) is not None
    except cards.CardError:
        logger.error("link_card_check_unavailable: no signing secret")
        return False


def on_link_requested(session: Session, payload: Dict[str, Any]) -> None:
    """Reply ``patient.linked`` when the card signature or the phone proves
    the patient, else ``patient.link_refused`` with nothing but the reason."""
    request = _parse(LinkRequest, payload)
    echo = {"request_id": request.request_id, "hospital_id": request.hospital_id,
            "patient_id": request.patient_id}
    user = _user_by_dedan(session, request.dedan_id)
    if user is None or not user.is_active:
        eventbus.emit(session, "patient.link_refused", {**echo, "dedan_id": request.dedan_id, "reason": "not_found"})
        return
    profile = session.scalar(select(Profile).where(Profile.user_id == user.id))
    # Only a phone the patient proved they hold (an SMS code) identifies them,
    # and only such a phone is given to the hospital.
    verified_phone = profile is not None and profile.phone_verified_at is not None
    account_phone = normalise_ethiopian_mobile(profile.phone) if verified_phone else None
    verified = _card_verifies(user.dedan_user_id, request.card_signature)
    if not verified and request.phone and account_phone is not None:
        verified = normalise_ethiopian_mobile(request.phone) == account_phone
    if not verified:
        eventbus.emit(session, "patient.link_refused",
                      {**echo, "dedan_id": user.dedan_user_id, "reason": "not_verified"})
        return

    link = session.scalar(select(HospitalLink).where(
        HospitalLink.hospital_id == request.hospital_id, HospitalLink.patient_id == request.patient_id)
        .with_for_update())
    is_new = link is None or link.user_id != user.id
    if link is None:
        session.add(HospitalLink(user_id=user.id, hospital_id=request.hospital_id, patient_id=request.patient_id))
    elif link.user_id != user.id:
        # Reception corrected a wrong link: the hospital patient is this account now.
        link.user_id = user.id
        link.linked_at = utcnow()
    eventbus.emit(session, "patient.linked", {
        **echo, "dedan_id": user.dedan_user_id, "name": _full_name(profile, user.dedan_user_id),
        "phone": account_phone,
    })
    if is_new:
        hospital = session.get(PartnerHospital, request.hospital_id)
        name = hospital.name if hospital is not None else "A hospital"
        _inbox_later(session, user.id, "hospital_linked", f"{name} linked your records to Endod",
                     "New records from this hospital will appear in your history.", "history", None)


def may_act_for(session: Session, hospital_id: str, user_id: str) -> bool:
    """Whether a hospital may send anything about this patient: it linked
    them (section 1), or they booked it through Endod."""
    if session.scalar(select(HospitalLink.id).where(
            HospitalLink.hospital_id == hospital_id, HospitalLink.user_id == user_id).limit(1)) is not None:
        return True
    return session.scalar(select(Appointment.id).where(
        Appointment.hospital_id == hospital_id, Appointment.user_id == user_id).limit(1)) is not None


def booking_patient_id(dedan_id: str) -> str:
    """The link's patient id for a patient who came through an Endod booking
    (the hospital's own id is not known to Endod yet)."""
    return f"endod:{dedan_id}"


def link_booking(session: Session, user_id: str, hospital_id: str) -> None:
    """Link a patient to a hospital they booked through Endod (contract section
    1: an Endod booking already identifies the patient). Idempotent; no notice."""
    if session.scalar(select(HospitalLink.id).where(
            HospitalLink.hospital_id == hospital_id, HospitalLink.user_id == user_id).limit(1)) is not None:
        return
    user = session.get(User, user_id)
    if user is None:
        return
    try:
        with session.begin_nested():
            session.add(HospitalLink(user_id=user_id, hospital_id=hospital_id,
                                     patient_id=booking_patient_id(user.dedan_user_id)))
    except IntegrityError:
        pass  # a concurrent booking linked them first


def _require_link(session: Session, hospital_id: str, user: User, what: str) -> None:
    if not may_act_for(session, hospital_id, user.id):
        raise PermanentEventError(f"{what} for {user.dedan_user_id}, who is not linked to hospital {hospital_id}")


# --- 2. clinical records --------------------------------------------------------------------

class FileMeta(BaseModel):
    file_id: str = Field(pattern=HEX32)
    filename: str = Field(min_length=1, max_length=200)
    content_type: str
    size: int = Field(gt=0, le=MAX_FILE_BYTES, strict=True)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("content_type")
    @classmethod
    def _allowed_type(cls, value: str) -> str:
        if value not in FILE_TYPES:
            raise ValueError(f"content_type must be one of {FILE_TYPES}")
        return value


class Published(BaseModel):
    record_id: str = Field(pattern=HEX32)
    version: int = Field(ge=0, strict=True)
    hospital_id: str = Field(min_length=1, max_length=32)
    hospital_name: str = Field(min_length=1, max_length=160)
    dedan_id: str = Field(min_length=1, max_length=16)
    visit_id: Optional[str] = Field(default=None, pattern=HEX32)
    category: Literal["diagnosis", "prescription", "lab_result", "imaging", "visit_note", "document"]
    title: str = Field(min_length=1, max_length=200)
    details: Dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime
    recorded_by: Optional[str] = Field(default=None, max_length=160)
    source: Literal["portal", "import"] = "portal"
    files: List[FileMeta] = Field(default_factory=list, max_length=MAX_FILES)

    @field_validator("occurred_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("occurred_at needs a UTC offset")
        return value


class Retracted(BaseModel):
    record_id: str = Field(pattern=HEX32)
    hospital_id: str = Field(min_length=1, max_length=32)
    dedan_id: Optional[str] = Field(default=None, max_length=16)
    reason: Optional[str] = Field(default=None, max_length=300)


def _text(value: Any, limit: int) -> Optional[str]:
    """A short display string from whatever the hospital sent (or None)."""
    if value is None or isinstance(value, (dict, list)):
        return None
    if isinstance(value, bool):
        value = "yes" if value else "no"
    text = str(value).strip()
    return text[:limit] or None


def _choice(value: Any, allowed: tuple) -> Optional[str]:
    return value if isinstance(value, str) and value in allowed else None


def _items(value: Any, fields: Dict[str, int], limit: int, extra=None,
           keep_index: bool = False) -> List[Dict[str, Any]]:
    """The hospital's items, cleaned; empty or malformed ones are dropped.
    With ``keep_index``, each keeps its position in the hospital's list as
    ``item_index``, so dropping one never shifts the others (prescriptions:
    pharmacies and the hospital refer to medicines by that index)."""
    if not isinstance(value, list):
        return []
    out = []
    for position, item in enumerate(value[:limit]):
        if not isinstance(item, dict):
            continue
        clean = {key: _text(item.get(key), size) for key, size in fields.items()}
        if extra:
            clean.update(extra(item))
        if any(v is not None for v in clean.values()):
            if keep_index:
                clean["item_index"] = position
            out.append(clean)
    return out


def clean_details(category: str, details: Dict[str, Any]) -> Dict[str, Any]:
    """Only the documented keys of ``details`` (unknown ones are ignored),
    as bounded strings: the app renders these, so nothing else gets through."""
    d = details if isinstance(details, dict) else {}
    long, short = 4000, 200
    if category == "diagnosis":
        return {"condition": _text(d.get("condition"), short), "code": _text(d.get("code"), 20),
                "status": _choice(d.get("status"), ("active", "resolved", "chronic")),
                "notes": _text(d.get("notes"), long)}
    if category == "prescription":
        return {"items": _items(d.get("items"), {"drug": short, "dose": 80, "route": 40, "frequency": 80,
                                                 "duration": 80, "quantity": 40, "notes": 500}, 50,
                                keep_index=True),
                "notes": _text(d.get("notes"), long)}
    if category == "lab_result":
        return {"items": _items(d.get("items"), {"test": short, "value": 80, "unit": 40, "reference_range": 80},
                                200, extra=lambda item: {"flag": _choice(item.get("flag"),
                                                                         ("low", "normal", "high", "critical"))}),
                "specimen": _text(d.get("specimen"), short), "notes": _text(d.get("notes"), long)}
    if category == "imaging":
        return {"modality": _text(d.get("modality"), 80), "body_part": _text(d.get("body_part"), short),
                "findings": _text(d.get("findings"), long), "impression": _text(d.get("impression"), long)}
    if category == "visit_note":
        vitals = d.get("vitals") if isinstance(d.get("vitals"), dict) else {}
        return {"complaint": _text(d.get("complaint"), long), "findings": _text(d.get("findings"), long),
                "plan": _text(d.get("plan"), long),
                "vitals": {key: _text(vitals.get(key), 40)
                           for key in ("bp", "pulse", "temp", "weight", "height", "spo2")}}
    return {"description": _text(d.get("description"), long)}


def _forget_file_later(session: Session, file: RecordFile) -> None:
    """Delete the stored copy ``file`` points to now, once this change commits.

    Each stored copy has its own path (``copy_id``), so this removes exactly
    the old one, never a newer copy downloaded meanwhile."""
    record_id, file_id, copy_id = file.record_id, file.file_id, file.copy_id

    def remove() -> None:
        from dedan_platform import record_files

        record_files.forget_copy(record_id, file_id, copy_id)

    eventbus.after_commit(session, remove)


def on_record_published(session: Session, payload: Dict[str, Any]) -> None:
    published = _parse(Published, payload)
    user = _user_by_dedan(session, published.dedan_id)
    if user is None:
        raise PermanentEventError(f"no Endod account {published.dedan_id}")
    _require_link(session, published.hospital_id, user, "a record")
    row = session.get(HospitalRecord, published.record_id, with_for_update=True)
    if row is not None and row.hospital_id != published.hospital_id:
        raise PermanentEventError("record_id belongs to another hospital")
    if row is not None and row.version >= published.version:
        return  # this version, or an older one, arriving late
    is_new = row is None
    if row is None:
        row = HospitalRecord(id=published.record_id, hospital_id=published.hospital_id,
                             version=published.version, received_at=utcnow())
        session.add(row)
    row.user_id = user.id
    row.hospital_name = published.hospital_name
    row.visit_id = published.visit_id
    row.category = published.category
    row.title = published.title
    row.details_json = json.dumps(clean_details(published.category, published.details), ensure_ascii=False)
    row.occurred_at = ensure_utc(published.occurred_at)
    row.recorded_by = published.recorded_by
    row.source = published.source
    row.version = published.version
    row.updated_at = utcnow()
    cleaned = json.loads(row.details_json)
    session.flush()
    if published.category == "prescription" or not is_new:
        # Its dispensing entry (docs/pharmacy.md): issued, corrected, or
        # withdrawn when a correction made it something else.
        from dedan_platform import prescriptions

        prescriptions.on_prescription_stored(session, row, cleaned)

    existing = {f.file_id: f for f in session.scalars(
        select(RecordFile).where(RecordFile.record_id == published.record_id).with_for_update())}
    for meta in published.files:
        current = existing.pop(meta.file_id, None)
        if current is None:
            session.add(RecordFile(record_id=published.record_id, file_id=meta.file_id, user_id=user.id,
                                   filename=meta.filename, content_type=meta.content_type, size=meta.size,
                                   sha256=meta.sha256, status=RecordFileStatus.PENDING, next_attempt_at=utcnow()))
            continue
        current.user_id = user.id
        current.filename = meta.filename
        changed = (current.sha256, current.size, current.content_type) != (meta.sha256, meta.size, meta.content_type)
        if changed or current.status == RecordFileStatus.REMOVED:
            if current.status == RecordFileStatus.STORED:
                _forget_file_later(session, current)
            current.sha256, current.size, current.content_type = meta.sha256, meta.size, meta.content_type
            current.copy_id = None
            current.status = RecordFileStatus.PENDING
            current.attempts = 0
            current.next_attempt_at = utcnow()
            current.last_error = None
            current.stored_at = None
        current.updated_at = utcnow()
    for dropped in existing.values():
        if dropped.status != RecordFileStatus.REMOVED:
            if dropped.status == RecordFileStatus.STORED:
                _forget_file_later(session, dropped)
            dropped.copy_id = None
            dropped.status = RecordFileStatus.REMOVED
            dropped.updated_at = utcnow()

    if is_new:
        noun = _CATEGORY_NOUN[published.category]
        if published.source == "import":
            _imported_notice_later(session, user.id, published.hospital_id, published.hospital_name)
        else:
            _inbox_later(session, user.id, f"hospital_{published.category}",
                         f"New {noun} from {published.hospital_name}", published.title, "history", published.record_id)


def _imported_notice_later(session: Session, user_id: str, hospital_id: str, hospital_name: str) -> None:
    """One unread notice per hospital for a batch of imported records, not one per record."""

    def write() -> None:
        from dedan_platform import inbox
        from dedan_platform.db import session_scope
        from dedan_platform.models import InboxItem

        with session_scope() as s:
            pending = s.scalar(select(InboxItem.id).where(
                InboxItem.user_id == user_id, InboxItem.kind == "hospital_records_imported",
                InboxItem.link_id == hospital_id, InboxItem.read_at.is_(None), InboxItem.dismissed_at.is_(None)))
        if pending is None:
            inbox.add_item(user_id, "records", "hospital_records_imported",
                           f"{hospital_name} added your earlier records",
                           "Open your history to see them.", "history", hospital_id)

    eventbus.after_commit(session, write)


def on_record_retracted(session: Session, payload: Dict[str, Any]) -> None:
    retracted = _parse(Retracted, payload)
    row = session.get(HospitalRecord, retracted.record_id, with_for_update=True)
    if row is None:
        raise RetryLater(f"record {retracted.record_id} not received yet")
    if row.hospital_id != retracted.hospital_id:
        raise PermanentEventError("record_id belongs to another hospital")
    if row.retracted_at is not None:
        return
    # Kept (the hospital entered it in error; the trail stays), never shown or shared again.
    row.retracted_at = utcnow()
    row.retracted_reason = retracted.reason
    row.updated_at = utcnow()
    from dedan_platform import prescriptions

    prescriptions.on_record_retracted(session, row)


# --- 3. follow-ups -----------------------------------------------------------------------------

class FollowUpEvent(BaseModel):
    visit_id: str = Field(pattern=HEX32)
    hospital_id: str = Field(min_length=1, max_length=32)
    hospital_name: str = Field(min_length=1, max_length=160)
    dedan_id: str = Field(min_length=1, max_length=16)
    follow_up_on: date
    note: Optional[str] = Field(default=None, max_length=500)
    doctor_name: Optional[str] = Field(default=None, max_length=120)
    cancelled: bool = False


#: Local time of the day-before reminder.
REMINDER_HOUR = 9


def _follow_up_marker(follow_up: FollowUp) -> str:
    return json.dumps({"follow_up_id": follow_up.id})[1:-1]


def _drop_follow_up_from(session: Session, follow_up: FollowUp, user_id: str) -> None:
    """The hospital moved this follow-up to another patient (it was set on the
    wrong one): it leaves the first account entirely, with its texts."""
    session.execute(delete(HealthEvent).where(
        HealthEvent.user_id == user_id, HealthEvent.event_type == HealthEventType.FOLLOW_UP,
        HealthEvent.metadata_json.contains(_follow_up_marker(follow_up))).execution_options(synchronize_session=False))
    patient_sms.cancel_prefix(session, f"sms:followup:{follow_up.id}:")


def _follow_up_timeline(session: Session, follow_up: FollowUp, zone: ZoneInfo, cancelled: bool) -> None:
    event = session.scalar(select(HealthEvent).where(
        HealthEvent.user_id == follow_up.user_id, HealthEvent.event_type == HealthEventType.FOLLOW_UP,
        HealthEvent.metadata_json.contains(_follow_up_marker(follow_up))))
    when = datetime.combine(date.fromisoformat(follow_up.follow_up_on), time(REMINDER_HOUR), zone)
    if cancelled:
        if event is not None:
            event.status = EventStatus.CANCELLED
        return
    if event is None:
        event = HealthEvent(user_id=follow_up.user_id, event_type=HealthEventType.FOLLOW_UP, source="hospital")
        session.add(event)
    event.title = f"Follow-up at {follow_up.hospital_name}"[:200]
    event.description = follow_up.note
    event.status = EventStatus.SCHEDULED
    event.occurred_at = ensure_utc(when)
    event.metadata_json = json.dumps({"follow_up_id": follow_up.id, "hospital_id": follow_up.hospital_id,
                                      "visit_id": follow_up.visit_id, "doctor_name": follow_up.doctor_name})


def _sms_date(day: date) -> str:
    return f"{day:%d/%m/%Y}"


def on_follow_up(session: Session, payload: Dict[str, Any]) -> None:
    event = _parse(FollowUpEvent, payload)
    user = _user_by_dedan(session, event.dedan_id)
    if user is None:
        raise PermanentEventError(f"no Endod account {event.dedan_id}")
    _require_link(session, event.hospital_id, user, "a follow-up")
    sent_at = eventbus.event_time(session)
    row = session.scalar(select(FollowUp).where(
        FollowUp.hospital_id == event.hospital_id, FollowUp.visit_id == event.visit_id).with_for_update())
    if row is not None and row.event_at is not None and sent_at is not None \
            and sent_at < ensure_aware(row.event_at):
        return  # an older change delivered late
    zone = _zone(session, event.hospital_id)
    day = event.follow_up_on.isoformat()
    if row is None:
        row = FollowUp(user_id=user.id, hospital_id=event.hospital_id, visit_id=event.visit_id,
                       hospital_name=event.hospital_name, follow_up_on=day)
        session.add(row)
        session.flush()
        was_active, old_day = False, None
    elif row.user_id != user.id:
        _drop_follow_up_from(session, row, row.user_id)
        was_active, old_day = False, None  # new to this patient: told and reminded afresh
    else:
        was_active, old_day = row.cancelled_at is None, row.follow_up_on
    row.user_id = user.id
    row.hospital_name = event.hospital_name
    row.event_at = sent_at or row.event_at
    row.updated_at = utcnow()
    # Per patient too, so texts already sent to someone else never stop this
    # patient's (a follow-up moved to another patient).
    prefix = f"sms:followup:{row.id}:{user.id}:"

    if event.cancelled:
        if row.cancelled_at is None:
            row.cancelled_at = utcnow()
        patient_sms.cancel_prefix(session, prefix)
        _follow_up_timeline(session, row, zone, cancelled=True)
        if was_active:
            _inbox_later(session, user.id, "follow_up_cancelled", f"Follow-up at {event.hospital_name} cancelled",
                         f"The follow-up on {day} is no longer needed.", "history", None)
        return

    row.follow_up_on = day
    row.note = event.note
    row.doctor_name = event.doctor_name
    row.cancelled_at = None
    _follow_up_timeline(session, row, zone, cancelled=False)
    if was_active and old_day == day:
        return  # the same follow-up again (a note changed): no new texts
    today = datetime.now(zone).date()
    set_key, reminder_key = f"{prefix}set:{day}", f"{prefix}reminder:{day}"
    patient_sms.cancel_prefix(session, f"{prefix}set:", keep_key=set_key)
    patient_sms.cancel_prefix(session, f"{prefix}reminder:", keep_key=reminder_key)
    if event.follow_up_on < today:
        return  # set for a day already past: on record, nothing to remind
    params = {"follow_up_id": row.id, "day": day, "date": _sms_date(event.follow_up_on)}
    patient_sms.to_account(session, user.id, patient_sms.FOLLOW_UP_SET, set_key, params)
    remind_at = datetime.combine(event.follow_up_on - timedelta(days=1), time(REMINDER_HOUR), zone)
    if remind_at > datetime.now(zone):
        patient_sms.to_account(session, user.id, patient_sms.FOLLOW_UP_REMINDER, reminder_key, params,
                               fire_at=ensure_utc(remind_at))
    who = f" with {event.doctor_name}" if event.doctor_name else ""
    _inbox_later(session, user.id, "follow_up_set", f"Follow-up at {event.hospital_name} on {day}",
                 f"Your doctor asked to see you again{who}. Book it from your history or Home.",
                 "follow_up", row.id)


# --- 4. queues ---------------------------------------------------------------------------------

class QueueUpdate(BaseModel):
    entry_id: str = Field(pattern=HEX32)
    hospital_id: str = Field(min_length=1, max_length=32)
    hospital_name: str = Field(min_length=1, max_length=160)
    doctor_name: Optional[str] = Field(default=None, max_length=120)
    day: date
    ticket: int = Field(ge=0, strict=True)
    status: Literal["waiting", "called", "done", "skipped", "cancelled"]
    ahead: int = Field(ge=0, strict=True)
    dedan_id: Optional[str] = Field(default=None, max_length=16)
    phone: Optional[str] = Field(default=None, max_length=32)
    patient_name: Optional[str] = Field(default=None, max_length=160)
    notify: Optional[Literal["near", "turn"]] = None
    seq: int = Field(ge=0, strict=True)


def on_queue_updated(session: Session, payload: Dict[str, Any]) -> None:
    update = _parse(QueueUpdate, payload)
    user = _user_by_dedan(session, update.dedan_id) if update.dedan_id else None
    if user is not None and not may_act_for(session, update.hospital_id, user.id):
        # Not linked to this hospital: a walk-in. Nothing shows in that
        # account; a text goes only to the phone the hospital took.
        user = None
    row = session.get(QueueEntry, update.entry_id, with_for_update=True)
    if row is not None and row.hospital_id != update.hospital_id:
        raise PermanentEventError("entry_id belongs to another hospital")
    newer = row is None or update.seq > row.seq
    if newer:
        if row is None:
            row = QueueEntry(id=update.entry_id, hospital_id=update.hospital_id, seq=update.seq)
            session.add(row)
        # The walk-in's phone and name are not kept: only what the app shows.
        row.user_id = user.id if user is not None else None
        row.hospital_name = update.hospital_name
        row.doctor_name = update.doctor_name
        row.day = update.day.isoformat()
        row.ticket = update.ticket
        row.status = update.status
        row.ahead = update.ahead
        row.seq = update.seq
        row.updated_at = utcnow()
    if update.notify is None:
        return
    # A notice delivered after a newer update still counts while it is true.
    wanted = "waiting" if update.notify == "near" else "called"
    if not newer and row.status != wanted:
        return
    template = patient_sms.QUEUE_NEAR if update.notify == "near" else patient_sms.QUEUE_TURN
    key = f"sms:queue:{update.entry_id}:{update.notify}"
    params = {"entry_id": update.entry_id, "ticket": update.ticket, "ahead": update.ahead}
    if user is not None:
        patient_sms.to_account(session, user.id, template, key, params)
        return
    phone = normalise_ethiopian_mobile(update.phone)
    if phone is None or not patient_sms.sms_in_use():
        return
    patient_sms.enqueue(session, user_id=patient_sms.WALK_IN, destination=phone, template=template, key=key,
                        params=params, walk_in=True)


HANDLERS = {
    "patient.link_requested": on_link_requested,
    "record.published": on_record_published,
    "record.retracted": on_record_retracted,
    "visit.follow_up": on_follow_up,
    "queue.updated": on_queue_updated,
}
