"""Booking a visit at an Endod partner hospital, paid from the patient's balance.

One transaction books it: the appointment, the payment and Endod's fee from
the wallet, the hospital's share (held until the visit happens), and the
``appointment.requested`` event to the hospital. So a patient is never charged
for a booking the hospital does not hear about, or the other way round.

The hospital then decides (events from the hospital service):

* in-person visits are confirmed at once (``appointment.confirmed``);
* video visits wait for a doctor; approval opens a video room;
* ``appointment.rejected`` / ``appointment.cancelled`` refund the patient in
  full (price and fee) and void the hospital's share;
* ``appointment.completed`` makes the hospital's share due.

The patient can cancel (and is refunded) until the visit starts; after that
it is the hospital's to close. Only the hospital confirms or completes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from dedan_platform import eventbus, identity, jitsi, partner_config, partners, wallet
from dedan_platform.appointments import (
    AppointmentError, AppointmentNotFound, _require_future, _require_no_overlap, _short_text, _to_payload,
    _transition, _validate_time_window, _zone, reminder_offsets_for,
)
from dedan_platform.db import ensure_aware, ensure_utc, new_uuid, session_scope
from dedan_platform.eventbus import PermanentEventError
from dedan_platform.models import (
    Appointment, EventStatus, HealthEventType, HospitalPayout, PayoutStatus, WalletEntryKind, utcnow,
)
from dedan_platform.timeline import record_event, update_appointment_event

logger = logging.getLogger(__name__)


class HospitalState:
    #: In-person: sent to the hospital, not acknowledged yet.
    AWAITING_HOSPITAL = "awaiting_hospital"
    #: Video: waiting for a doctor to approve.
    AWAITING_DOCTOR = "awaiting_doctor"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    OPEN = (AWAITING_HOSPITAL, AWAITING_DOCTOR, CONFIRMED)


#: Visit modes as the patient app names them, and as the hospital service does.
VIDEO, IN_PERSON = "telehealth", "in_person"
_EVENT_MODE = {IN_PERSON: "in_person", VIDEO: "video"}


class BookingError(AppointmentError):
    """The booking cannot be made (bad input, hospital not available)."""


def _mode(visit_mode: Optional[str]) -> str:
    mode = (visit_mode or IN_PERSON).strip().lower()
    if mode == "video":
        mode = VIDEO
    if mode not in (IN_PERSON, VIDEO):
        raise BookingError("visit_mode must be in_person or telehealth (video).")
    return mode


def _price_for(hospital, mode: str) -> int:
    if mode == VIDEO:
        if not hospital.video_enabled or hospital.price_video is None:
            raise BookingError("This hospital does not offer video visits.")
        return hospital.price_video
    return hospital.price_in_person


def quote(hospital_id: str, visit_mode: Optional[str]) -> Dict[str, Any]:
    """What a visit costs: the hospital's price plus Endod's fee (santim)."""
    hospital = partners.get(hospital_id)
    if hospital is None:
        raise BookingError("This hospital is not taking bookings through Endod right now.")
    mode = _mode(visit_mode)
    price = _price_for(hospital, mode)
    fee = wallet.service_fee(price)
    return {"hospital_id": hospital.id, "visit_mode": mode, "price": price, "service_fee": fee,
            "total": price + fee, "currency": "ETB"}


def _patient(user_id: str) -> Dict[str, Any]:
    """What the hospital is told about the patient: their Endod ID, name and
    (when it is an Ethiopian mobile) phone, so the hospital can reach them."""
    from dedan_platform.phone import normalise_ethiopian_mobile

    profile = identity.get_profile_payload(user_id)
    names = [profile.get("first_name"), profile.get("middle_name"), profile.get("last_name")]
    name = " ".join(n for n in names if n) or profile.get("display_name") or profile["dedan_user_id"]
    return {"dedan_id": profile["dedan_user_id"], "name": name[:160],
            "phone": normalise_ethiopian_mobile(profile.get("phone"))}


def _quietly(what: str, action, *args, **kwargs) -> None:
    """A side effect after the money has moved: logged on failure, never fatal."""
    try:
        action(*args, **kwargs)
    except Exception:  # noqa: BLE001
        logger.exception("after_payment_side_effect_failed what=%s", what)


def book(
    user_id: str,
    hospital_id: str,
    scheduled_at: datetime,
    visit_mode: Optional[str] = None,
    service: Optional[str] = None,
    time_window: Optional[str] = None,
    notes: Optional[str] = None,
    timezone_name: Optional[str] = None,
    duration_minutes: int = 30,
    correlation_id: Optional[str] = None,
    user_preferences: Optional[str] = None,
) -> Dict[str, Any]:
    """Book and pay. Raises BookingError, AppointmentError or wallet.InsufficientFunds."""
    hospital = partners.get(hospital_id)
    if hospital is None:
        raise BookingError("This hospital is not taking bookings through Endod right now.")
    mode = _mode(visit_mode)
    price = _price_for(hospital, mode)
    fee = wallet.service_fee(price)
    if scheduled_at.tzinfo is None:
        raise AppointmentError("scheduled_at must include a timezone offset.")
    scheduled_at = ensure_utc(scheduled_at)
    _require_future(scheduled_at)
    tz_name = timezone_name or hospital.timezone
    zone = _zone(tz_name)
    time_window = _validate_time_window(time_window, scheduled_at, zone)
    service = _short_text(service, "department", 40)
    offered = [s for s in (hospital.services or "").split(",") if s]
    if service and offered and service not in offered:
        raise BookingError("This hospital does not offer that service.")
    notes = _short_text(notes, "notes", 2000)
    duration = max(5, min(int(duration_minutes or 30), 480))
    patient = _patient(user_id)
    location = None if mode == VIDEO else \
        ", ".join(p for p in (hospital.name, hospital.address, hospital.city) if p)[:200]

    with session_scope() as session:
        _require_no_overlap(session, user_id, scheduled_at, duration, None)
        appointment = Appointment(
            id=new_uuid(), user_id=user_id, scheduled_at=scheduled_at, appointment_type="consultation",
            duration_minutes=duration, location=location, visit_mode=mode, department=service,
            time_window=time_window, facility_id=hospital.id, notes=notes, timezone=tz_name,
            correlation_id=correlation_id, hospital_id=hospital.id,
            hospital_state=HospitalState.AWAITING_DOCTOR if mode == VIDEO else HospitalState.AWAITING_HOSPITAL,
            price=price, service_fee=fee,
        )
        session.add(appointment)
        session.flush()
        if price:
            wallet.post(session, user_id, WalletEntryKind.PAYMENT, -price, appointment_id=appointment.id,
                        description=f"{'Video visit' if mode == VIDEO else 'Visit'}: {hospital.name}")
        if fee:
            wallet.post(session, user_id, WalletEntryKind.SERVICE_FEE, -fee, appointment_id=appointment.id,
                        description="Endod service fee")
        session.add(HospitalPayout(hospital_id=hospital.id, appointment_id=appointment.id, amount=price))
        eventbus.emit(session, "appointment.requested", {
            "appointment_id": appointment.id, "hospital_id": hospital.id, "patient": patient,
            "visit_mode": _EVENT_MODE[mode], "service": service,
            "scheduled_at": scheduled_at.isoformat(), "duration_minutes": duration,
            "notes": notes, "price": price,
        })
        offsets = reminder_offsets_for(appointment, user_preferences)
    # Built after the commit (objects stay loaded): no second session while
    # the booking's transaction holds its locks.
    payload = _to_payload(appointment)

    _quietly("timeline", record_event,
             user_id=user_id, event_type=HealthEventType.APPOINTMENT,
             title=f"{'Video visit' if mode == VIDEO else 'Visit'} at {hospital.name}", description=notes,
             occurred_at=scheduled_at, status=EventStatus.SCHEDULED,
             metadata={"appointment_id": payload["appointment_id"], "location": location,
                       "hospital_id": hospital.id},
             correlation_id=correlation_id)
    _quietly("inbox", _inbox, user_id, "appointment_booked",
             "Video visit requested" if mode == VIDEO else "Visit booked",
             f"Paid {wallet.birr(price + fee)} birr. "
             + ("A doctor will approve it; you will be told here." if mode == VIDEO else
                f"{hospital.name} has your booking."),
             payload["appointment_id"])
    return {"appointment": payload, "reminder_policy_count": len(offsets), "reminder_offsets": offsets,
            "payment": {"price": price, "service_fee": fee, "total": price + fee}}


def _inbox(user_id: str, kind: str, title: str, body: str, appointment_id: Optional[str]) -> None:
    from dedan_platform import inbox

    inbox.add_item(user_id, "appointments", kind, title, body=body, link_screen="appointment",
                   link_id=appointment_id)


def _refund(session: Session, appointment: Appointment, why: str) -> int:
    """Pay back the price and fee (once, whatever retries) and void the hospital's share."""
    amount = (appointment.price or 0) + (appointment.service_fee or 0)
    if amount:
        from dedan_platform.models import WalletEntry

        already = session.scalar(select(WalletEntry.id).where(
            WalletEntry.appointment_id == appointment.id, WalletEntry.kind == WalletEntryKind.REFUND))
        if already is None:
            wallet.post(session, appointment.user_id, WalletEntryKind.REFUND, amount,
                        appointment_id=appointment.id, description=why)
    payout = session.scalar(select(HospitalPayout).where(HospitalPayout.appointment_id == appointment.id)
                            .with_for_update())
    if payout is not None and payout.status == PayoutStatus.HELD:
        payout.status = PayoutStatus.VOID
        payout.updated_at = utcnow()
    return amount


def _close(session: Session, appointment: Appointment, state: str, reason: Optional[str]) -> None:
    appointment.hospital_state = state
    appointment.hospital_reason = (reason or "")[:300] or None
    if appointment.status not in (EventStatus.CANCELLED, EventStatus.COMPLETED, EventStatus.MISSED):
        _transition(appointment, EventStatus.CANCELLED)
    update_appointment_event(session, appointment.user_id, appointment.id, EventStatus.CANCELLED)


def cancel_by_patient(user_id: str, appointment_id: str, correlation_id: Optional[str] = None) -> Dict[str, Any]:
    with session_scope() as session:
        appointment = session.scalar(select(Appointment).where(
            Appointment.id == appointment_id, Appointment.user_id == user_id).with_for_update())
        if appointment is None:
            raise AppointmentNotFound("Appointment not found.")
        if appointment.hospital_state not in HospitalState.OPEN:
            raise AppointmentError("This visit is already closed.")
        if ensure_aware(appointment.scheduled_at) <= utcnow():
            raise AppointmentError("This visit has started. Please contact the hospital.")
        refunded = _refund(session, appointment, "Refund: you cancelled the visit")
        _close(session, appointment, HospitalState.CANCELLED, "Cancelled by you.")
        eventbus.emit(session, "appointment.cancelled", {
            "appointment_id": appointment.id, "hospital_id": appointment.hospital_id, "by": "patient"})
        session.flush()
    payload = _to_payload(appointment)

    from dedan_platform import notifications

    try:
        payload["reminders_cancelled"] = notifications.cancel_for_appointment(appointment_id)
    except Exception:  # noqa: BLE001 -- refunded already; a stray reminder is the lesser harm
        logger.exception("cancel_reminders_failed appointment=%s", appointment_id)
        payload["reminders_cancelled"] = 0
    _quietly("inbox", _inbox, user_id, "appointment_cancelled", "Visit cancelled",
             f"{wallet.birr(refunded)} birr is back in your balance.", appointment_id)
    return payload


# --- decisions from the hospital service ---------------------------------------------

class Decision(BaseModel):
    appointment_id: str = Field(min_length=1, max_length=64)
    hospital_id: str = Field(min_length=1, max_length=32)
    meeting_room: Optional[str] = Field(default=None, max_length=64, pattern=r"^[a-z0-9-]+$")
    doctor_name: Optional[str] = Field(default=None, max_length=120)
    reason: Optional[str] = Field(default=None, max_length=300)


def _decision(session: Session, payload: Dict[str, Any]):
    try:
        decision = Decision.model_validate(payload)
    except ValidationError as exc:
        raise PermanentEventError(str(exc).splitlines()[0]) from exc
    appointment = session.scalar(select(Appointment).where(
        Appointment.id == decision.appointment_id, Appointment.hospital_id == decision.hospital_id)
        .with_for_update())
    if appointment is None:
        raise PermanentEventError(f"no appointment {decision.appointment_id} at this hospital")
    return decision, appointment


def on_confirmed(session: Session, payload: Dict[str, Any]) -> None:
    decision, appointment = _decision(session, payload)
    if appointment.hospital_state not in (HospitalState.AWAITING_HOSPITAL, HospitalState.AWAITING_DOCTOR):
        return  # cancelled meanwhile (the hospital is told), or already confirmed
    was_video = appointment.hospital_state == HospitalState.AWAITING_DOCTOR
    appointment.hospital_state = HospitalState.CONFIRMED
    if appointment.status == EventStatus.SCHEDULED:
        _transition(appointment, EventStatus.CONFIRMED)
    if decision.meeting_room:
        appointment.meeting_room = decision.meeting_room
        appointment.meeting_url = f"https://{partner_config.jitsi_domain()}/{decision.meeting_room}"
    if decision.doctor_name:
        appointment.provider_name = decision.doctor_name
    update_appointment_event(session, appointment.user_id, appointment.id, EventStatus.CONFIRMED)
    if was_video:
        user_id, appointment_id = appointment.user_id, appointment.id
        body = f"{decision.doctor_name or 'A doctor'} will see you. Join from Appointments at the visit time."

        def approved() -> None:
            from dedan_platform import scheduler

            _inbox(user_id, "appointment_confirmed", "Video visit approved", body, appointment_id)
            # Reminders only once the visit is certain (none were set while it waited).
            scheduler.schedule_all_channels(user_id=user_id, appointment_id=appointment_id)

        eventbus.after_commit(session, approved)


def _hospital_closed(session: Session, payload: Dict[str, Any], state: str, title: str) -> None:
    decision, appointment = _decision(session, payload)
    if appointment.hospital_state not in HospitalState.OPEN:
        return
    refunded = _refund(session, appointment, f"Refund: {title.lower()}")
    _close(session, appointment, state, decision.reason)
    user_id, appointment_id = appointment.user_id, appointment.id
    reason = f" Reason: {decision.reason}" if decision.reason else ""
    body = f"{wallet.birr(refunded)} birr is back in your balance.{reason}"

    def side_effects() -> None:
        from dedan_platform import notifications

        notifications.cancel_for_appointment(appointment_id)
        _inbox(user_id, "appointment_cancelled", title, body, appointment_id)

    eventbus.after_commit(session, side_effects)


def on_rejected(session: Session, payload: Dict[str, Any]) -> None:
    _hospital_closed(session, payload, HospitalState.REJECTED, "Visit declined by the hospital")


def on_cancelled(session: Session, payload: Dict[str, Any]) -> None:
    _hospital_closed(session, payload, HospitalState.CANCELLED, "Visit cancelled by the hospital")


def on_completed(session: Session, payload: Dict[str, Any]) -> None:
    decision, appointment = _decision(session, payload)
    if appointment.hospital_state in (HospitalState.AWAITING_HOSPITAL, HospitalState.AWAITING_DOCTOR):
        # The confirmation has not been applied yet (it is being retried).
        raise eventbus.RetryLater(f"appointment {appointment.id} not confirmed here yet")
    if appointment.hospital_state == HospitalState.CANCELLED:
        # The patient cancelled (and was refunded) just as the hospital
        # completed the visit: flag the payout for a person to settle.
        payout = session.scalar(select(HospitalPayout).where(HospitalPayout.appointment_id == appointment.id)
                                .with_for_update())
        if payout is not None and payout.status in (PayoutStatus.VOID, PayoutStatus.HELD):
            payout.status = PayoutStatus.DISPUTED
            payout.updated_at = utcnow()
        logger.warning("ALERT completed_after_cancel appointment=%s", appointment.id)
        return
    if appointment.hospital_state != HospitalState.CONFIRMED:
        return
    appointment.hospital_state = HospitalState.COMPLETED
    if appointment.status in (EventStatus.CONFIRMED, EventStatus.RESCHEDULED):
        _transition(appointment, EventStatus.COMPLETED)
    update_appointment_event(session, appointment.user_id, appointment.id, EventStatus.COMPLETED)
    payout = session.scalar(select(HospitalPayout).where(HospitalPayout.appointment_id == appointment.id)
                            .with_for_update())
    if payout is not None and payout.status == PayoutStatus.HELD:
        payout.status = PayoutStatus.DUE
        payout.updated_at = utcnow()


HANDLERS = {
    "hospital.listed": partners.on_listed,
    "hospital.unlisted": partners.on_unlisted,
    "appointment.confirmed": on_confirmed,
    "appointment.rejected": on_rejected,
    "appointment.cancelled": on_cancelled,
    "appointment.completed": on_completed,
}


# --- joining a video visit -------------------------------------------------------------

def video_join(user_id: str, appointment_id: str) -> Dict[str, Any]:
    """Join details for the patient's own approved video visit, around its time."""
    with session_scope() as session:
        appointment = session.scalar(select(Appointment).where(
            Appointment.id == appointment_id, Appointment.user_id == user_id))
        if appointment is None:
            raise AppointmentNotFound("Appointment not found.")
        if appointment.hospital_state != HospitalState.CONFIRMED or not appointment.meeting_room:
            raise AppointmentError("This visit has no video room yet.")
        opens, closes = jitsi.join_window(ensure_aware(appointment.scheduled_at), appointment.duration_minutes)
        room = appointment.meeting_room
    if not opens <= utcnow() <= closes:
        raise AppointmentError("You can join from 30 minutes before the visit.")
    patient = _patient(user_id)
    return jitsi.join_details(room, patient["name"], moderator=False, closes_at=closes)


#: A booking the hospital never answered is refunded this long after its start.
UNANSWERED_AFTER = timedelta(hours=2)


def refund_unanswered() -> int:
    """Refund bookings the hospital never confirmed or declined, a while after
    their time (the hospital may have refused the request, or be offline).
    The hospital is told, in case the booking reaches it later."""
    cutoff = utcnow() - UNANSWERED_AFTER
    with session_scope() as session:
        ids = list(session.scalars(select(Appointment.id).where(
            Appointment.hospital_state.in_([HospitalState.AWAITING_HOSPITAL, HospitalState.AWAITING_DOCTOR]),
            Appointment.scheduled_at < cutoff,
        ).limit(100)))
    refunded = 0
    for appointment_id in ids:
        with session_scope() as session:
            appointment = session.scalar(select(Appointment).where(Appointment.id == appointment_id).with_for_update())
            if appointment is None or appointment.hospital_state not in (
                    HospitalState.AWAITING_HOSPITAL, HospitalState.AWAITING_DOCTOR):
                continue
            amount = _refund(session, appointment, "Refund: the hospital did not answer")
            _close(session, appointment, HospitalState.CANCELLED, "The hospital did not answer in time.")
            eventbus.emit(session, "appointment.cancelled", {
                "appointment_id": appointment.id, "hospital_id": appointment.hospital_id, "by": "patient"})
            user_id = appointment.user_id
        refunded += 1
        logger.warning("booking_unanswered_refunded appointment=%s", appointment_id)
        _quietly("inbox", _inbox, user_id, "appointment_cancelled", "Visit cancelled",
                 f"The hospital did not answer. {wallet.birr(amount)} birr is back in your balance.",
                 appointment_id)
    return refunded
