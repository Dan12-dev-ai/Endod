"""Paying for each partner-hospital booking through Chapa, and refunds.

There is no stored Endod balance. Booking a paid visit (hospital_bookings.book)
holds the slot (the appointment is ``awaiting_payment``) and opens a Chapa
checkout for the price plus Endod's fee, where the patient pays with telebirr,
CBE Birr, M-Pesa, a bank or a card.

* ``settle`` asks Chapa's verify endpoint about the payment. Only Chapa's
  answer counts: the webhook, the callback and the patient's return to the app
  just trigger it (a forged notification or a hand-made return URL confirms
  nothing). The exact amount in birr must match. The payment row is locked and
  moves from ``pending`` once, so the booking is confirmed (and
  ``appointment.requested`` emitted) once, however many notifications arrive.
* An unpaid hold ends after ``HOLD`` (``expire_holds``, the events worker): the
  slot is freed and the appointment is ``payment_expired``. A payment Chapa
  confirms after that is refunded automatically.
* A refund (the hospital declined or cancelled, the patient cancelled, the
  hospital never answered, or a late payment) is one ``BookingRefund`` row per
  payment, sent to Chapa's refund API by the events worker
  (``process_refunds``), retried with backoff, and followed until Chapa says
  the money reached the payer. When Chapa refuses it, reverses it or cannot be
  reached for long, it becomes ``manual_refund_needed``: logged as an ALERT and
  audited, for Endod to refund from the Chapa dashboard.

Money is in santim (integers).
"""

from __future__ import annotations

import json
import logging
import time
from datetime import timedelta
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from dedan_platform import chapa
from dedan_platform.db import ensure_aware, session_scope
from dedan_platform.models import (
    Appointment, BookingPayment, BookingPaymentStatus, BookingRefund, Preferences, RefundStatus, UserEvent, utcnow,
)

logger = logging.getLogger(__name__)

#: How long a booking waits for its payment before the slot is freed.
HOLD = timedelta(minutes=30)
#: Bookings one patient may have waiting for payment at once.
MAX_OPEN_HOLDS = 3
#: Waits between attempts to send a refund Chapa could not take; then it is manual.
REFUND_BACKOFF = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=15), timedelta(hours=1),
                  timedelta(hours=4), timedelta(hours=12))
#: How often a refund Chapa accepted is checked, and for how long before a person looks.
REFUND_CHECK_EVERY = timedelta(minutes=30)
REFUND_FOLLOW_FOR = timedelta(days=14)
#: Each claim on a refund by a worker (so two workers never send it at once).
REFUND_LEASE = timedelta(minutes=10)
#: Seconds a worker round may spend asking Chapa.
BUDGET = 15


class PaymentState:
    """``Appointment.payment_status``: what the patient is shown."""

    AWAITING = "awaiting_payment"
    PAID = "paid"
    EXPIRED = "expired"
    REFUND_PENDING = "refund_pending"
    REFUNDED = "refunded"


class PaymentNotFound(LookupError):
    pass


# --- texts ---------------------------------------------------------------------------------

def birr(santim: int) -> str:
    return f"{(santim or 0) / 100:,.2f}"


def refund_sentence(santim: int, language: str = "en") -> str:
    """Where refunded money goes (no balance any more), in the patient's language."""
    if language == "am":
        return f"{birr(santim)} ብር ወደ ከፈሉበት የክፍያ መንገድ ተመላሽ ይደረጋል (ጥቂት ቀናት ሊወስድ ይችላል)።"
    return f"{birr(santim)} birr is being refunded to your payment method (it can take a few days)."


_TITLES = {
    "Visit cancelled": "ቀጠሮው ተሰርዟል",
    "Visit declined by the hospital": "ሆስፒታሉ ቀጠሮውን አልተቀበለም",
    "Visit cancelled by the hospital": "ሆስፒታሉ ቀጠሮውን ሰርዟል",
    "Payment refunded": "ክፍያው ተመላሽ ይደረጋል",
    "Payment needs checking": "ክፍያው መረጋገጥ ያስፈልገዋል",
}


def title_in(title: str, language: str) -> str:
    return _TITLES.get(title, title) if language == "am" else title


def language_of(user_id: str) -> str:
    try:
        with session_scope() as session:
            value = session.scalar(select(Preferences.language).where(Preferences.user_id == user_id))
    except Exception:  # noqa: BLE001 -- a message in English beats no message
        return "en"
    return value if value in ("en", "am") else "en"


def _inbox(user_id: str, title: str, body: str, appointment_id: Optional[str], kind: str) -> None:
    from dedan_platform import inbox

    inbox.add_item(user_id, "appointments", kind, title, body=body, link_screen="appointment",
                   link_id=appointment_id)


def _quietly(what: str, action: Callable[..., Any], *args: Any) -> None:
    try:
        action(*args)
    except Exception:  # noqa: BLE001 -- after the money moved: logged, never fatal
        logger.exception("payment_side_effect_failed what=%s", what)


def _run(actions: List[Callable[[], None]]) -> None:
    for action in actions:
        _quietly("after_commit", action)


# --- holds -------------------------------------------------------------------------------

def require_hold_room(session: Session, user_id: str) -> None:
    from dedan_platform.hospital_bookings import HospitalState, TooManyHolds

    open_holds = session.scalar(select(func.count()).select_from(Appointment).where(
        Appointment.user_id == user_id, Appointment.hospital_state == HospitalState.AWAITING_PAYMENT))
    if open_holds >= MAX_OPEN_HOLDS:
        raise TooManyHolds(f"You have {open_holds} bookings waiting for payment. Pay for one, or let it "
                           "expire, before booking another.")


def new_payment(session: Session, appointment: Appointment, amount: int) -> BookingPayment:
    payment = BookingPayment(user_id=appointment.user_id, appointment_id=appointment.id, tx_ref=chapa.new_tx_ref(),
                             amount=amount, currency="ETB", expires_at=appointment.payment_due_at)
    session.add(payment)
    session.flush()
    return payment


def open_checkout(appointment_id: str, tx_ref: str, amount: int, user_id: str) -> str:
    """Chapa's checkout page for the booking's payment. Raises ChapaError."""
    from dedan_platform import identity, partner_config

    profile = identity.get_profile_payload(user_id)
    base = partner_config.public_app_url()
    checkout = chapa.initialize(
        tx_ref, amount, profile.get("first_name") or "", profile.get("last_name") or "", profile.get("phone"),
        return_url=f"{base}/interview?section=appointment&payment={tx_ref}",
        callback_url=f"{base}/api/payments/chapa/callback",
        description="Health visit booking",
    )
    with session_scope() as session:
        payment = session.scalar(select(BookingPayment).where(BookingPayment.tx_ref == tx_ref).with_for_update())
        appointment = session.get(Appointment, appointment_id, with_for_update=True)
        payment.checkout_url = checkout
        if appointment.payment_status == PaymentState.AWAITING:
            appointment.payment_url = checkout
    return checkout


def close_hold(session: Session, payment: BookingPayment, appointment: Appointment, state: str,
               reason: str) -> None:
    """End an unpaid hold: the slot is freed (the appointment is cancelled).
    The hospital never heard of it, so it is not told."""
    from dedan_platform.appointments import TERMINAL_STATUSES, _transition
    from dedan_platform.models import EventStatus

    if payment.status == BookingPaymentStatus.PENDING:
        payment.status = BookingPaymentStatus.EXPIRED
    appointment.hospital_state = state
    appointment.hospital_reason = reason[:300]
    appointment.payment_status = PaymentState.EXPIRED
    appointment.payment_url = None
    if appointment.status not in TERMINAL_STATUSES:
        _transition(appointment, EventStatus.CANCELLED)


def expire_holds(budget_seconds: float = BUDGET) -> int:
    """End holds whose time is up. Chapa is asked first (within a time budget),
    in case a payment arrived without its notification."""
    from dedan_platform.hospital_bookings import HospitalState

    now = utcnow()
    with session_scope() as session:
        refs = list(session.scalars(select(BookingPayment.tx_ref).where(
            BookingPayment.status == BookingPaymentStatus.PENDING, BookingPayment.expires_at < now,
        ).order_by(BookingPayment.expires_at).limit(50)))
    expired, started = 0, time.monotonic()
    for tx_ref in refs:
        if time.monotonic() - started < budget_seconds:
            try:
                settle(tx_ref)
            except chapa.ChapaError as exc:
                logger.warning("hold_check_failed tx_ref=%s %s", tx_ref, exc)
        with session_scope() as session:
            payment = session.scalar(select(BookingPayment).where(BookingPayment.tx_ref == tx_ref).with_for_update())
            if payment is None or payment.status != BookingPaymentStatus.PENDING:
                continue
            appointment = session.get(Appointment, payment.appointment_id, with_for_update=True)
            if appointment is not None and appointment.hospital_state == HospitalState.AWAITING_PAYMENT:
                close_hold(session, payment, appointment, HospitalState.PAYMENT_EXPIRED,
                           "The payment was not completed in time.")
            else:
                payment.status = BookingPaymentStatus.EXPIRED
        expired += 1
        logger.info("booking_hold_expired tx_ref=%s", tx_ref)
    return expired


# --- confirming a payment -----------------------------------------------------------------

def _payload(payment: BookingPayment) -> Dict[str, Any]:
    return {
        "tx_ref": payment.tx_ref,
        "status": payment.status,
        "appointment_id": payment.appointment_id,
        "amount": payment.amount,
        "currency": payment.currency,
        "expires_at": ensure_aware(payment.expires_at).isoformat(),
        "paid_at": ensure_aware(payment.paid_at).isoformat() if payment.paid_at else None,
    }


def settle(tx_ref: str) -> Optional[Dict[str, Any]]:
    """Check a booking's payment with Chapa and act on it, once.

    Returns the payment, or None when ``tx_ref`` is not a booking payment.
    Raises ChapaError when Chapa gave no answer (nothing changes then).
    """
    from dedan_platform import hospital_bookings
    from dedan_platform.hospital_bookings import HospitalState

    with session_scope() as session:
        payment = session.scalar(select(BookingPayment).where(BookingPayment.tx_ref == tx_ref))
        if payment is None:
            return None
        if payment.status in (BookingPaymentStatus.PAID, BookingPaymentStatus.MISMATCH):
            return _payload(payment)  # settled for good: nothing to ask Chapa
        payment_id, user_id = payment.id, payment.user_id
    record = chapa.verify(tx_ref)
    # Read before taking the locks (it opens a session of its own).
    patient = hospital_bookings._patient(user_id) if record["paid"] else None
    with session_scope() as session:
        payment = session.get(BookingPayment, payment_id, with_for_update=True, populate_existing=True)
        payment.last_checked_at = utcnow()
        if not record["paid"] or payment.status in (BookingPaymentStatus.PAID, BookingPaymentStatus.MISMATCH):
            return _payload(payment)
        appointment = session.get(Appointment, payment.appointment_id, with_for_update=True, populate_existing=True)
        exact = record["amount"] == payment.amount and record.get("currency") == payment.currency
        if not exact:
            # Never accept another amount or currency (a tampered checkout, or
            # a mistake): the booking is not made, and a person refunds what
            # was actually charged.
            logger.error("ALERT booking_payment_mismatch tx_ref=%s expected=%s %s got=%s %s", tx_ref,
                         payment.amount, payment.currency, record["amount"], record.get("currency"))
            payment.status = BookingPaymentStatus.MISMATCH
            payment.reported_amount = record["amount"]
            if appointment.hospital_state == HospitalState.AWAITING_PAYMENT:
                close_hold(session, payment, appointment, HospitalState.PAYMENT_EXPIRED,
                           "The payment did not match the price.")
            refund = request_refund(session, payment, record["amount"] or 0, "Payment did not match the price")
            mark_manual(session, refund, f"amount mismatch: Chapa reported {record['amount']} "
                                         f"{record.get('currency')}")
            appointment.payment_status = PaymentState.REFUND_PENDING
            body_en = ("Your payment did not match the price, so the visit was not booked. Endod will refund "
                       "it to your payment method (it can take a few days).")
            body_am = ("ክፍያዎ ከዋጋው ጋር ስላልተዛመደ ቀጠሮው አልተያዘም። እንዶድ ወደ ከፈሉበት የክፍያ መንገድ ተመላሽ ያደርጋል "
                       "(ጥቂት ቀናት ሊወስድ ይችላል)።")
            notice = ("Payment needs checking", body_en, body_am, "payment_mismatch")
        else:
            payment.status = BookingPaymentStatus.PAID
            payment.paid_at = utcnow()
            payment.provider_reference = (record.get("reference") or "")[:100] or None
            if appointment.hospital_state == HospitalState.AWAITING_PAYMENT:
                hospital_bookings.on_paid(session, appointment, patient)
                notice = None
            else:
                # The hold ended (expired, or the patient cancelled it) before
                # Chapa confirmed: the slot may be gone, so the money goes back.
                logger.warning("booking_paid_after_hold tx_ref=%s appointment=%s", tx_ref, appointment.id)
                request_refund(session, payment, payment.amount, "Paid after the booking hold ended")
                appointment.payment_status = PaymentState.REFUND_PENDING
                notice = ("Payment refunded",
                          "Your payment arrived after the booking hold ended, so the visit was not booked. "
                          + refund_sentence(payment.amount, "en"),
                          "ክፍያዎ የቀጠሮው ጊዜ ካለፈ በኋላ ስለደረሰ ቀጠሮው አልተያዘም። " + refund_sentence(payment.amount, "am"),
                          "payment_refunded")
        result = _payload(payment)
        actions = list(session.info.get("after_commit", []))
        appointment_id = appointment.id
    _run(actions)
    if notice is not None:
        language = language_of(user_id)
        _quietly("inbox", _inbox, user_id, title_in(notice[0], language),
                 notice[2] if language == "am" else notice[1], appointment_id, notice[3])
    return result


def status_for(user_id: str, tx_ref: str) -> Dict[str, Any]:
    """The patient's own payment (back from Chapa): checked with Chapa while
    not settled, with the booking as it now stands."""
    from dedan_platform.appointments import _to_payload

    with session_scope() as session:
        payment = session.scalar(select(BookingPayment).where(
            BookingPayment.tx_ref == tx_ref, BookingPayment.user_id == user_id))
        if payment is None:
            raise PaymentNotFound("Payment not found.")
        settled = payment.status in (BookingPaymentStatus.PAID, BookingPaymentStatus.MISMATCH)
    if not settled:
        try:
            settle(tx_ref)
        except chapa.ChapaError as exc:
            logger.warning("payment_status_check_failed tx_ref=%s %s", tx_ref, exc)
    with session_scope() as session:
        payment = session.scalar(select(BookingPayment).where(BookingPayment.tx_ref == tx_ref))
        appointment = session.get(Appointment, payment.appointment_id)
        return {**_payload(payment), "appointment": _to_payload(appointment)}


def recheck(budget_seconds: float = BUDGET) -> int:
    """Ask Chapa about payments whose notification may have been missed: open
    holds a few minutes old, and (less often) holds that ended in the last day,
    in case the patient still paid (then refunded)."""
    now = utcnow()
    with session_scope() as session:
        refs = list(session.scalars(select(BookingPayment.tx_ref).where(or_(
            and_(BookingPayment.status == BookingPaymentStatus.PENDING,
                 BookingPayment.created_at < now - timedelta(minutes=2),
                 or_(BookingPayment.last_checked_at.is_(None),
                     BookingPayment.last_checked_at < now - timedelta(minutes=5))),
            and_(BookingPayment.status == BookingPaymentStatus.EXPIRED,
                 BookingPayment.expires_at > now - timedelta(days=1),
                 or_(BookingPayment.last_checked_at.is_(None),
                     BookingPayment.last_checked_at < now - timedelta(minutes=30))),
        )).order_by(BookingPayment.created_at.desc()).limit(20)))
    checked, started = 0, time.monotonic()
    for tx_ref in refs:
        if time.monotonic() - started > budget_seconds:
            break
        try:
            settle(tx_ref)
            checked += 1
        except chapa.ChapaError as exc:
            logger.warning("payment_recheck_failed tx_ref=%s %s", tx_ref, exc)
            with session_scope() as session:
                payment = session.scalar(select(BookingPayment).where(BookingPayment.tx_ref == tx_ref))
                if payment is not None:
                    payment.last_checked_at = utcnow()
    return checked


# --- refunds -------------------------------------------------------------------------------

def request_refund(session: Session, payment: BookingPayment, amount: int, reason: str) -> BookingRefund:
    """The refund of ``payment`` (made once: a second request returns the first).
    Sent to Chapa by the events worker. Call with the payment row locked."""
    existing = session.scalar(select(BookingRefund).where(BookingRefund.payment_id == payment.id))
    if existing is not None:
        return existing
    refund = BookingRefund(payment_id=payment.id, appointment_id=payment.appointment_id, user_id=payment.user_id,
                           amount=amount, reason=reason[:200], reference=f"endod-rf-{payment.id}"[:64],
                           status=RefundStatus.PENDING, next_attempt_at=utcnow())
    session.add(refund)
    session.flush()
    logger.info("refund_requested payment=%s amount=%s reason=%s", payment.tx_ref, amount, reason)
    return refund


def mark_manual(session: Session, refund: BookingRefund, why: str) -> None:
    """Endod must refund this one by hand (Chapa dashboard): said loudly."""
    refund.status = RefundStatus.MANUAL
    refund.last_error = why[:300]
    refund.next_attempt_at = None
    refund.updated_at = utcnow()
    tx_ref = session.scalar(select(BookingPayment.tx_ref).where(BookingPayment.id == refund.payment_id))
    logger.error("ALERT manual_refund_needed refund=%s tx_ref=%s amount=%s appointment=%s why=%s",
                 refund.id, tx_ref, refund.amount, refund.appointment_id, why)
    session.add(UserEvent(user_id=refund.user_id, event_type="payment.manual_refund_needed", payload=json.dumps({
        "refund_id": refund.id, "tx_ref": tx_ref, "amount": refund.amount, "appointment_id": refund.appointment_id,
    })))


def _set_appointment(session: Session, appointment_id: str, state: str) -> None:
    appointment = session.get(Appointment, appointment_id)
    if appointment is not None:
        appointment.payment_status = state


def _attempt(refund_id: str) -> bool:
    """One step for one refund: send it, or check on it. True if Chapa was asked."""
    now = utcnow()
    with session_scope() as session:
        refund = session.get(BookingRefund, refund_id, with_for_update=True)
        if refund is None or refund.status not in (RefundStatus.PENDING, RefundStatus.SUBMITTED):
            return False
        if refund.next_attempt_at is not None and ensure_aware(refund.next_attempt_at) > now:
            return False  # another worker has it, or it is not time yet
        # Claimed for a while: a crash mid-call leaves it to be tried again
        # later (with the same reference, which Chapa will not pay twice).
        refund.next_attempt_at = now + REFUND_LEASE
        if refund.status == RefundStatus.PENDING:
            refund.attempts += 1
        refund.updated_at = now
        status, attempts, ref_id = refund.status, refund.attempts, refund.chapa_ref_id
        amount, reason, reference = refund.amount, refund.reason, refund.reference
        created = ensure_aware(refund.created_at)
        tx_ref = session.scalar(select(BookingPayment.tx_ref).where(BookingPayment.id == refund.payment_id))
    if status == RefundStatus.PENDING:
        try:
            accepted = chapa.refund(tx_ref, amount, reason, reference)
        except chapa.RefundRefused as exc:
            with session_scope() as session:
                mark_manual(session, session.get(BookingRefund, refund_id, with_for_update=True), str(exc))
            return True
        except chapa.ChapaError as exc:
            with session_scope() as session:
                refund = session.get(BookingRefund, refund_id, with_for_update=True)
                if attempts > len(REFUND_BACKOFF):
                    mark_manual(session, refund, f"Chapa unavailable after {attempts} attempts: {exc}")
                else:
                    refund.last_error = str(exc)[:300]
                    refund.next_attempt_at = utcnow() + REFUND_BACKOFF[attempts - 1]
                    refund.updated_at = utcnow()
                    logger.warning("refund_retry refund=%s attempt=%s %s", refund_id, attempts, exc)
            return True
        with session_scope() as session:
            refund = session.get(BookingRefund, refund_id, with_for_update=True)
            refund.chapa_ref_id = accepted.get("ref_id")
            refund.last_error = None
            refund.updated_at = utcnow()
            if refund.chapa_ref_id:
                refund.status, refund.next_attempt_at = RefundStatus.SUBMITTED, utcnow() + REFUND_CHECK_EVERY
            else:  # accepted, but nothing to follow it by: taken as done
                refund.status, refund.completed_at, refund.next_attempt_at = RefundStatus.SUCCEEDED, utcnow(), None
                _set_appointment(session, refund.appointment_id, PaymentState.REFUNDED)
            logger.info("refund_accepted refund=%s tx_ref=%s ref_id=%s", refund_id, tx_ref, refund.chapa_ref_id)
        return True
    # Submitted: has the money reached the payer?
    try:
        state = chapa.verify_refund(ref_id)
    except chapa.ChapaError as exc:
        state, error = "unknown", str(exc)
    else:
        error = None
    with session_scope() as session:
        refund = session.get(BookingRefund, refund_id, with_for_update=True)
        refund.updated_at = utcnow()
        if state in ("refunded", "success", "successful", "completed"):
            refund.status, refund.completed_at, refund.next_attempt_at = RefundStatus.SUCCEEDED, utcnow(), None
            _set_appointment(session, refund.appointment_id, PaymentState.REFUNDED)
            logger.info("refund_succeeded refund=%s tx_ref=%s", refund_id, tx_ref)
        elif state in ("reversed", "failed", "cancelled", "canceled", "rejected"):
            mark_manual(session, refund, f"Chapa {state} the refund {ref_id}")
        elif utcnow() - created > REFUND_FOLLOW_FOR:
            mark_manual(session, refund, f"Chapa still says {state} for refund {ref_id} after "
                                         f"{REFUND_FOLLOW_FOR.days} days")
        else:
            refund.last_error = error[:300] if error else None
            refund.next_attempt_at = utcnow() + REFUND_CHECK_EVERY
    return True


def process_refunds(budget_seconds: float = BUDGET) -> int:
    """Send due refunds to Chapa and follow the ones it accepted (the events worker)."""
    now = utcnow()
    with session_scope() as session:
        ids = list(session.scalars(select(BookingRefund.id).where(
            BookingRefund.status.in_([RefundStatus.PENDING, RefundStatus.SUBMITTED]),
            or_(BookingRefund.next_attempt_at.is_(None), BookingRefund.next_attempt_at <= now),
        ).order_by(BookingRefund.next_attempt_at).limit(20)))
    done, started = 0, time.monotonic()
    for refund_id in ids:
        if time.monotonic() - started > budget_seconds:
            break
        try:
            done += int(_attempt(refund_id))
        except chapa.ChapaNotConfigured:
            logger.error("ALERT refunds_waiting chapa_not_configured")
            break
    return done


def refund_payload(session: Session, appointment_id: str) -> Optional[Dict[str, Any]]:
    refund = session.scalar(select(BookingRefund).where(BookingRefund.appointment_id == appointment_id))
    if refund is None:
        return None
    return {"amount": refund.amount, "status": refund.status}
