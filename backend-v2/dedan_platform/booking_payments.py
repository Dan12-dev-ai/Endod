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
  the money reached the payer. Before anything is retried after an unknown
  outcome, and whenever Chapa refuses, the payment is looked up at Chapa: a
  refund that already went through is adopted, never repeated. When Chapa
  refuses a first request, reverses a refund, or cannot be reached for long,
  it becomes ``manual_refund_needed``: an ALERT (saying whether a refund may
  already exist) and an audit row, for Endod to settle from the Chapa dashboard.
* A paid booking whose payment Chapa reverses or refunds without us (a
  chargeback) is cancelled, the hospital told and its payout stopped.
* Rows are always locked appointment first, then payment (``lock_booking``).

Money is in santim (integers).
"""

from __future__ import annotations

import json
import logging
import time
from datetime import timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

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
    #: Chapa reversed the payment (a chargeback): the booking was cancelled.
    REVERSED = "reversed"


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


# --- locks ---------------------------------------------------------------------------------

def lock_booking(session: Session, *, tx_ref: Optional[str] = None, payment_id: Optional[str] = None,
                 appointment_id: Optional[str] = None) -> Tuple[Optional[Appointment], Optional[BookingPayment]]:
    """Lock a booking's appointment, then its payment: the one order every
    writer uses (hospital decisions, cancels, confirmations, expiry, refunds),
    so two of them can never wait on each other."""
    if appointment_id is None:
        query = select(BookingPayment.appointment_id)
        query = query.where(BookingPayment.tx_ref == tx_ref) if tx_ref else query.where(BookingPayment.id == payment_id)
        appointment_id = session.scalar(query)
        if appointment_id is None:
            return None, None
    appointment = session.scalar(select(Appointment).where(Appointment.id == appointment_id)
                                 .with_for_update().execution_options(populate_existing=True))
    payment = session.scalar(select(BookingPayment).where(BookingPayment.appointment_id == appointment_id)
                             .with_for_update().execution_options(populate_existing=True))
    return appointment, payment


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
        appointment, payment = lock_booking(session, appointment_id=appointment_id)
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


def _expire_one(tx_ref: str, check_with_chapa: bool) -> bool:
    from dedan_platform.hospital_bookings import HospitalState

    if check_with_chapa:
        try:
            settle(tx_ref)
        except chapa.ChapaError as exc:
            logger.warning("hold_check_failed tx_ref=%s %s", tx_ref, exc)
    with session_scope() as session:
        appointment, payment = lock_booking(session, tx_ref=tx_ref)
        if payment is None or payment.status != BookingPaymentStatus.PENDING:
            return False
        if appointment is not None and appointment.hospital_state == HospitalState.AWAITING_PAYMENT:
            close_hold(session, payment, appointment, HospitalState.PAYMENT_EXPIRED,
                       "The payment was not completed in time.")
        else:
            payment.status = BookingPaymentStatus.EXPIRED
    logger.info("booking_hold_expired tx_ref=%s", tx_ref)
    return True


def expire_holds(budget_seconds: float = BUDGET) -> int:
    """End holds whose time is up. Chapa is asked first (within a time budget),
    in case a payment arrived without its notification. Each hold is handled
    on its own: one failing never keeps the others held."""
    now = utcnow()
    with session_scope() as session:
        refs = list(session.scalars(select(BookingPayment.tx_ref).where(
            BookingPayment.status == BookingPaymentStatus.PENDING, BookingPayment.expires_at < now,
        ).order_by(BookingPayment.expires_at).limit(50)))
    expired, started = 0, time.monotonic()
    for tx_ref in refs:
        try:
            expired += int(_expire_one(tx_ref, time.monotonic() - started < budget_seconds))
        except Exception:  # noqa: BLE001 -- the next round tries it again
            logger.exception("hold_expiry_failed tx_ref=%s", tx_ref)
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


_SETTLED = (BookingPaymentStatus.MISMATCH, BookingPaymentStatus.REVERSED)


def settle(tx_ref: str, recheck_paid: bool = False) -> Optional[Dict[str, Any]]:
    """Check a booking's payment with Chapa and act on it, once.

    Returns the payment, or None when ``tx_ref`` is not a booking payment.
    Raises ChapaError when Chapa gave no answer (nothing changes then). A paid
    payment is asked about again only with ``recheck_paid`` (Chapa notified a
    refund or reversal), to catch chargebacks.
    """
    from dedan_platform import hospital_bookings
    from dedan_platform.hospital_bookings import HospitalState

    with session_scope() as session:
        payment = session.scalar(select(BookingPayment).where(BookingPayment.tx_ref == tx_ref))
        if payment is None:
            return None
        if payment.status in _SETTLED or (payment.status == BookingPaymentStatus.PAID and not recheck_paid):
            return _payload(payment)  # settled for good: nothing to ask Chapa
        user_id = payment.user_id
    record = chapa.verify(tx_ref)
    if record.get("reversed"):
        return _on_reversed(tx_ref)
    # Read before taking the locks (it opens a session of its own).
    patient = hospital_bookings._patient(user_id) if record["paid"] else None
    notice = None
    with session_scope() as session:
        appointment, payment = lock_booking(session, tx_ref=tx_ref)
        payment.last_checked_at = utcnow()
        if not record["paid"] or payment.status in _SETTLED + (BookingPaymentStatus.PAID,):
            return _payload(payment)
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
                                         f"{record.get('currency')}; no refund was sent", may_exist=False)
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
                if not hospital_bookings.on_paid(session, appointment, patient, payment):
                    notice = ("Payment refunded",
                              "Your payment arrived too close to the visit time, so the visit was not booked. "
                              + refund_sentence(payment.amount, "en"),
                              "ክፍያዎ ለቀጠሮው ሰዓት በጣም ተቃርቦ ስለደረሰ ቀጠሮው አልተያዘም። "
                              + refund_sentence(payment.amount, "am"),
                              "payment_refunded")
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
        _notify(user_id, appointment_id, *notice)
    return result


def _notify(user_id: str, appointment_id: str, title: str, body_en: str, body_am: str, kind: str) -> None:
    language = language_of(user_id)
    _quietly("inbox", _inbox, user_id, title_in(title, language), body_am if language == "am" else body_en,
             appointment_id, kind)


def _on_reversed(tx_ref: str) -> Dict[str, Any]:
    """Chapa reports the payment refunded or reversed (status ``refunded`` or
    ``reversed``; webhooks ``charge.refunded`` / ``charge.reversed``).

    If Endod asked for that refund, it is done. Otherwise the money went back
    without us (a chargeback, or a refund from the dashboard): an unpaid
    booking cannot stand, so it is cancelled, the hospital told, its payout
    stopped, and the patient told; loudly logged and audited."""
    from dedan_platform import hospital_bookings
    from dedan_platform.models import HospitalPayout, PayoutStatus

    notice = None
    with session_scope() as session:
        appointment, payment = lock_booking(session, tx_ref=tx_ref)
        payment.last_checked_at = utcnow()
        refund = session.scalar(select(BookingRefund).where(BookingRefund.payment_id == payment.id)
                                .with_for_update())
        if refund is not None:
            if refund.status != RefundStatus.SUCCEEDED:
                _succeed(refund, appointment, "Chapa shows the payment refunded")
            return _payload(payment)
        if payment.status != BookingPaymentStatus.PAID:
            # Never confirmed here (pending, expired, mismatched): nothing was booked on it.
            if payment.status == BookingPaymentStatus.PENDING:
                payment.status = BookingPaymentStatus.EXPIRED
            return _payload(payment)
        payment.status = BookingPaymentStatus.REVERSED
        appointment.payment_status = PaymentState.REVERSED
        payout = session.scalar(select(HospitalPayout).where(HospitalPayout.appointment_id == appointment.id)
                                .with_for_update())
        if payout is not None and payout.status == PayoutStatus.HELD:
            payout.status, payout.updated_at = PayoutStatus.VOID, utcnow()
        elif payout is not None and payout.status in (PayoutStatus.DUE, PayoutStatus.PAID):
            payout.status, payout.updated_at = PayoutStatus.DISPUTED, utcnow()
        cancelled = hospital_bookings.on_reversed(session, appointment)
        logger.error("ALERT booking_payment_reversed tx_ref=%s appointment=%s amount=%s cancelled=%s", tx_ref,
                     appointment.id, payment.amount, cancelled)
        session.add(UserEvent(user_id=payment.user_id, event_type="payment.reversed", payload=json.dumps({
            "tx_ref": tx_ref, "appointment_id": appointment.id, "amount": payment.amount,
            "booking_cancelled": cancelled})))
        notice = ("Booking cancelled: payment reversed",
                  "Your payment for this visit was reversed through Chapa, so the booking is cancelled. "
                  "Book again if you still need the visit.",
                  "ለዚህ ቀጠሮ የከፈሉት ገንዘብ በቻፓ በኩል ስለተመለሰ ቀጠሮው ተሰርዟል። አሁንም ጉብኝቱ ካስፈለገዎት እንደገና ያስይዙ።",
                  "payment_reversed")
        result, user_id, appointment_id = _payload(payment), payment.user_id, appointment.id
        actions = list(session.info.get("after_commit", []))
    _run(actions)
    if notice is not None:
        _notify(user_id, appointment_id, *notice)
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
        settled = payment.status in _SETTLED + (BookingPaymentStatus.PAID,)
    if not settled:
        try:
            settle(tx_ref)
        except chapa.ChapaError as exc:
            logger.warning("payment_status_check_failed tx_ref=%s %s", tx_ref, exc)
    with session_scope() as session:
        payment = session.scalar(select(BookingPayment).where(BookingPayment.tx_ref == tx_ref))
        appointment = session.get(Appointment, payment.appointment_id)
        return {**_payload(payment), "appointment": _to_payload(appointment)}


#: Chapa documents no expiry for a checkout page, so a hold that ended is
#: asked about for this long (a payment made later is refunded) ...
LATE_PAYMENT_WINDOW = timedelta(days=7)
#: ... less often as it ages: (age up to, check every).
LATE_CHECKS = ((timedelta(hours=1), timedelta(minutes=5)), (timedelta(days=1), timedelta(minutes=30)),
               (LATE_PAYMENT_WINDOW, timedelta(hours=6)))


def _late_check_due(expires_at, last_checked_at, now) -> bool:
    age = now - ensure_aware(expires_at)
    for up_to, every in LATE_CHECKS:
        if age <= up_to:
            return last_checked_at is None or now - ensure_aware(last_checked_at) >= every
    return False


def recheck(budget_seconds: float = BUDGET) -> int:
    """Ask Chapa about payments whose notification may have been missed: open
    holds a few minutes old, and holds that ended unpaid, for as long as their
    checkout could still be paid (then refunded), less often as they age."""
    now = utcnow()
    with session_scope() as session:
        pending = list(session.scalars(select(BookingPayment.tx_ref).where(
            BookingPayment.status == BookingPaymentStatus.PENDING,
            BookingPayment.created_at < now - timedelta(minutes=2),
            or_(BookingPayment.last_checked_at.is_(None),
                BookingPayment.last_checked_at < now - timedelta(minutes=5)),
        ).order_by(BookingPayment.created_at.desc()).limit(20)))
        ended = session.execute(select(BookingPayment.tx_ref, BookingPayment.expires_at,
                                       BookingPayment.last_checked_at).where(
            BookingPayment.status == BookingPaymentStatus.EXPIRED,
            BookingPayment.expires_at > now - LATE_PAYMENT_WINDOW,
            or_(BookingPayment.last_checked_at.is_(None),
                BookingPayment.last_checked_at < now - timedelta(minutes=5)),
        ).order_by(BookingPayment.last_checked_at.asc()).limit(200)).all()
    late = [ref for ref, expires_at, checked in ended if _late_check_due(expires_at, checked, now)][:20]
    checked, started = 0, time.monotonic()
    for tx_ref in pending + late:
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
    Sent to Chapa by the events worker. Call with the booking locked (lock_booking)."""
    existing = session.scalar(select(BookingRefund).where(BookingRefund.payment_id == payment.id))
    if existing is not None:
        return existing
    refund = BookingRefund(payment_id=payment.id, appointment_id=payment.appointment_id, user_id=payment.user_id,
                           amount=amount, reason=reason[:200], reference=f"endod-rf-{payment.id}"[:64],
                           status=RefundStatus.PENDING, next_attempt_at=utcnow(), maybe_accepted=False)
    session.add(refund)
    session.flush()
    logger.info("refund_requested payment=%s amount=%s reason=%s", payment.tx_ref, amount, reason)
    return refund


def mark_manual(session: Session, refund: BookingRefund, why: str, may_exist: bool) -> None:
    """Endod must look at this one by hand (Chapa dashboard): said loudly,
    with whether Chapa may already have accepted a refund for it."""
    refund.status = RefundStatus.MANUAL
    refund.last_error = why[:300]
    refund.next_attempt_at = None
    refund.in_flight_since = None
    refund.updated_at = utcnow()
    tx_ref = session.scalar(select(BookingPayment.tx_ref).where(BookingPayment.id == refund.payment_id))
    hint = ("a refund MAY ALREADY HAVE BEEN ACCEPTED by Chapa" if may_exist
            else "Chapa has accepted no refund for it")
    logger.error("ALERT manual_refund_needed refund=%s tx_ref=%s amount=%s appointment=%s refund_may_exist=%s "
                 "why=%s -- %s; check the Chapa dashboard before refunding",
                 refund.id, tx_ref, refund.amount, refund.appointment_id, "yes" if may_exist else "no", why, hint)
    session.add(UserEvent(user_id=refund.user_id, event_type="payment.manual_refund_needed", payload=json.dumps({
        "refund_id": refund.id, "tx_ref": tx_ref, "amount": refund.amount, "appointment_id": refund.appointment_id,
        "refund_may_already_exist": may_exist,
    })))


def _succeed(refund: BookingRefund, appointment: Optional[Appointment], why: str) -> None:
    refund.status, refund.completed_at, refund.next_attempt_at = RefundStatus.SUCCEEDED, utcnow(), None
    refund.in_flight_since, refund.updated_at = None, utcnow()
    if appointment is not None:
        appointment.payment_status = PaymentState.REFUNDED
    logger.info("refund_succeeded refund=%s %s", refund.id, why)


def _locked_refund(session: Session, refund_id: str) -> Tuple[Optional[Appointment], BookingRefund]:
    """The refund and its appointment, locked appointment first (as everywhere)."""
    appointment_id = session.scalar(select(BookingRefund.appointment_id).where(BookingRefund.id == refund_id))
    appointment = session.scalar(select(Appointment).where(Appointment.id == appointment_id).with_for_update()
                                 .execution_options(populate_existing=True))
    refund = session.scalar(select(BookingRefund).where(BookingRefund.id == refund_id).with_for_update()
                            .execution_options(populate_existing=True))
    return appointment, refund


def _money_back_at_chapa(tx_ref: str) -> bool:
    """Whether Chapa shows the payment refunded (or reversed): the money is
    back with the payer, whoever asked. Raises ChapaError on no answer."""
    return bool(chapa.verify(tx_ref).get("reversed"))


#: An unconfirmed refund (Chapa refused a retry that may have duplicated an
#: accepted one) is watched this long before a person looks.
REFUND_UNCONFIRMED_FOR = timedelta(days=3)


def _attempt(refund_id: str) -> bool:
    """One step for one refund: send it, or check on it. True if Chapa was asked."""
    now = utcnow()
    with session_scope() as session:
        _appointment, refund = _locked_refund(session, refund_id)
        if refund is None or refund.status not in (RefundStatus.PENDING, RefundStatus.SUBMITTED):
            return False
        if refund.next_attempt_at is not None and ensure_aware(refund.next_attempt_at) > now:
            return False  # another worker has it, or it is not time yet
        if refund.in_flight_since is not None:
            # The last call's answer was never recorded (lost, or the worker died).
            refund.maybe_accepted = True
        # Claimed for a while: a crash mid-call leaves it to be tried again
        # later, with the same reference (and Chapa asked first).
        refund.next_attempt_at = now + REFUND_LEASE
        refund.in_flight_since = now
        refund.updated_at = now
        status, ref_id, maybe = refund.status, refund.chapa_ref_id, bool(refund.maybe_accepted)
        amount, reason, reference = refund.amount, refund.reason, refund.reference
        created, updated_attempts = ensure_aware(refund.created_at), refund.attempts
        tx_ref = session.scalar(select(BookingPayment.tx_ref).where(BookingPayment.id == refund.payment_id))
    if status == RefundStatus.SUBMITTED:
        return _follow(refund_id, tx_ref, ref_id, created)
    try:
        if maybe and _money_back_at_chapa(tx_ref):
            with session_scope() as session:
                appointment, refund = _locked_refund(session, refund_id)
                _succeed(refund, appointment, "Chapa shows the payment refunded (an earlier request went through)")
            return True
        accepted = chapa.refund(tx_ref, amount, reason, reference)
    except chapa.ChapaNotConfigured:
        _release(refund_id, "Chapa is not configured")
        return False
    except chapa.RefundRefused as exc:
        return _refused(refund_id, tx_ref, str(exc), maybe)
    except chapa.ChapaError as exc:
        with session_scope() as session:
            _appointment, refund = _locked_refund(session, refund_id)
            refund.attempts = updated_attempts + 1
            refund.in_flight_since = None
            # No answer is not a "no": the request may have gone through.
            refund.maybe_accepted = True
            if refund.attempts > len(REFUND_BACKOFF):
                mark_manual(session, refund, f"Chapa unavailable after {refund.attempts} attempts: {exc}",
                            may_exist=True)
            else:
                refund.last_error = str(exc)[:300]
                refund.next_attempt_at = utcnow() + REFUND_BACKOFF[refund.attempts - 1]
                refund.updated_at = utcnow()
                logger.warning("refund_retry refund=%s attempt=%s %s", refund_id, refund.attempts, exc)
        return True
    with session_scope() as session:
        _appointment, refund = _locked_refund(session, refund_id)
        refund.chapa_ref_id = accepted.get("ref_id")
        refund.last_error, refund.in_flight_since = None, None
        refund.status, refund.next_attempt_at = RefundStatus.SUBMITTED, utcnow() + REFUND_CHECK_EVERY
        refund.updated_at = utcnow()
        logger.info("refund_accepted refund=%s tx_ref=%s ref_id=%s", refund_id, tx_ref, refund.chapa_ref_id)
    return True


def _release(refund_id: str, why: str) -> None:
    """Not tried (no Chapa key): stays pending, attempt not counted, back soon."""
    with session_scope() as session:
        _appointment, refund = _locked_refund(session, refund_id)
        refund.in_flight_since = None
        refund.last_error = why
        refund.next_attempt_at = utcnow() + NOT_CONFIGURED_WAIT
        refund.updated_at = utcnow()


def _refused(refund_id: str, tx_ref: str, message: str, maybe: bool) -> bool:
    """Chapa said no. A refusal can mean an earlier request of ours (same
    reference) already went through, so Chapa is asked about the payment
    before a person is: never a second refund by hand for one Chapa has."""
    try:
        back: Optional[bool] = _money_back_at_chapa(tx_ref)
        lookup_error = None
    except chapa.ChapaError as exc:
        back, lookup_error = None, str(exc)
    with session_scope() as session:
        appointment, refund = _locked_refund(session, refund_id)
        refund.in_flight_since = None
        refund.updated_at = utcnow()
        if back:
            _succeed(refund, appointment, "Chapa shows the payment refunded (refused as a repeat)")
        elif back is None:
            # Could not look: ask again later, as for any outage.
            refund.attempts += 1
            if refund.attempts > len(REFUND_BACKOFF):
                mark_manual(session, refund, f"{message}; Chapa could not be asked about the payment "
                                             f"({lookup_error})", may_exist=maybe)
            else:
                refund.last_error = f"{message}; lookup failed: {lookup_error}"[:300]
                refund.next_attempt_at = utcnow() + REFUND_BACKOFF[refund.attempts - 1]
        elif not maybe:
            # Our only request, answered no, and the payment is not refunded.
            mark_manual(session, refund, message, may_exist=False)
        else:
            # Perhaps a repeat of a request Chapa accepted and is still
            # processing: watch the payment before a person looks.
            refund.status = RefundStatus.SUBMITTED
            refund.last_error = f"{message}; checking whether an earlier request went through"[:300]
            refund.next_attempt_at = utcnow() + REFUND_CHECK_EVERY
            logger.warning("refund_unconfirmed refund=%s tx_ref=%s %s", refund_id, tx_ref, message)
    return True


def _follow(refund_id: str, tx_ref: str, ref_id: Optional[str], created) -> bool:
    """A refund Chapa accepted (``ref_id``), or may have (none): has the money
    reached the payer?"""
    error = None
    try:
        state = chapa.verify_refund(ref_id) if ref_id else ("refunded" if _money_back_at_chapa(tx_ref) else "unknown")
    except chapa.ChapaError as exc:
        state, error = "unknown", str(exc)
    with session_scope() as session:
        appointment, refund = _locked_refund(session, refund_id)
        refund.in_flight_since = None
        refund.updated_at = utcnow()
        if state in ("refunded", "success", "successful", "completed"):
            _succeed(refund, appointment, f"tx_ref={tx_ref} ref_id={ref_id}")
        elif ref_id and state in ("reversed", "failed", "cancelled", "canceled", "rejected"):
            mark_manual(session, refund, f"Chapa {state} the refund {ref_id}: the money did not reach the payer",
                        may_exist=False)
        elif not ref_id and utcnow() - created > REFUND_UNCONFIRMED_FOR:
            mark_manual(session, refund, f"Chapa refused a repeated request and shows no refund after "
                                         f"{REFUND_UNCONFIRMED_FOR.days} days ({refund.last_error})", may_exist=True)
        elif ref_id and utcnow() - created > REFUND_FOLLOW_FOR:
            mark_manual(session, refund, f"Chapa still says {state} for refund {ref_id} after "
                                         f"{REFUND_FOLLOW_FOR.days} days", may_exist=True)
        else:
            if error:
                refund.last_error = error[:300]
            refund.next_attempt_at = utcnow() + REFUND_CHECK_EVERY
    return True


#: With no Chapa key, refunds wait (not counted as attempts) and are tried this often.
NOT_CONFIGURED_WAIT = timedelta(minutes=5)


def process_refunds(budget_seconds: float = BUDGET) -> int:
    """Send due refunds to Chapa and follow the ones it accepted (the events worker)."""
    from dedan_platform import partner_config

    now = utcnow()
    with session_scope() as session:
        ids = list(session.scalars(select(BookingRefund.id).where(
            BookingRefund.status.in_([RefundStatus.PENDING, RefundStatus.SUBMITTED]),
            or_(BookingRefund.next_attempt_at.is_(None), BookingRefund.next_attempt_at <= now),
        ).order_by(BookingRefund.next_attempt_at).limit(20)))
    if not ids:
        return 0
    if not partner_config.chapa_secret_key():
        # Nothing is tried, so nothing is counted against the refunds.
        logger.warning("refunds_waiting chapa_not_configured due=%s: set CHAPA_SECRET_KEY", len(ids))
        return 0
    done, started = 0, time.monotonic()
    for refund_id in ids:
        if time.monotonic() - started > budget_seconds:
            break
        try:
            done += int(_attempt(refund_id))
        except Exception:  # noqa: BLE001 -- one refund failing never holds up the rest
            logger.exception("refund_step_failed refund=%s", refund_id)
    return done
