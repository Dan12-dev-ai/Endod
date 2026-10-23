"""Short texts to patients: booking decisions, refunds, follow-ups and queues.

They go through the notification queue (``notifications`` rows, delivered by
the notification worker), so every text is retried with backoff and sent at
most once: each has a deterministic ``idempotency_key`` (unique in the
database), and a row is only added in the same transaction as the change it
describes, after checking that the key is not already there.

Rules for the text itself:

* short (one or two SMS segments), in the account's language; a walk-in
  without an account gets Amharic, then English;
* never clinical: no diagnosis, test, medicine, department, doctor or
  hospital name. A lock-screen preview is visible to anyone holding the
  phone, and a hospital's name can reveal the kind of care. The app shows
  the details after sign-in.

Decided with the pharmacy contract (docs/pharmacy.md): a prescription's
code (``RX_CODE``) names the hospital that wrote it. It and a dispense
(``RX_DISPENSED``) are always Amharic, then English. A dispense never names
the pharmacy (typed by whoever is at the counter, so it could carry a phone
number or a link). Neither names a medicine.

One exception, not to a patient: a clinic's contact who booked an Endod demo
(``DEMO_BOOKED``/``DEMO_MOVED``, see hospital_onboarding) is texted the
facility's own name, like a walk-in (no account; Amharic, then English).

Who gets one: an account's phone only when it is verified and the patient
allows SMS (the same rule as appointment reminders, checked again just
before sending); a walk-in at the number the hospital took at check-in.
Nothing is queued when SMS is not one of this deployment's channels
(``REMINDER_CHANNELS``).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from dedan_platform.models import (
    Notification, NotificationChannel, NotificationStatus, Preferences, Profile, utcnow,
)
from dedan_platform.sms_provider import BRAND_NAME as BRAND

logger = logging.getLogger(__name__)

#: ``notifications.user_id`` for a walk-in without an account.
WALK_IN = "walk-in"

BOOKING_CONFIRMED = "sms_booking_confirmed"
BOOKING_DECLINED = "sms_booking_declined"
BOOKING_CANCELLED = "sms_booking_cancelled"
BOOKING_UNANSWERED = "sms_booking_unanswered"
REFUND = "sms_refund"
FOLLOW_UP_SET = "sms_follow_up_set"
FOLLOW_UP_REMINDER = "sms_follow_up_reminder"
QUEUE_NEAR = "sms_queue_near"
QUEUE_TURN = "sms_queue_turn"
DEMO_BOOKED = "sms_demo_booked"
DEMO_MOVED = "sms_demo_moved"
RX_CODE = "sms_rx_code"
RX_DISPENSED = "sms_rx_dispensed"

#: Always Amharic, then English (whatever the account's language).
_BILINGUAL = frozenset({RX_CODE, RX_DISPENSED})

_TEXTS: Dict[str, Dict[str, str]] = {
    BOOKING_CONFIRMED: {
        "en": "{brand}: your visit on {when} is confirmed. Details are in the app.",
        "am": "{brand}፦ በ{when} ያለዎት ቀጠሮ ተረጋግጧል። ዝርዝሩ በመተግበሪያው ውስጥ አለ።",
    },
    BOOKING_DECLINED: {
        "en": "{brand}: the hospital could not take your visit on {when}.{refund}",
        "am": "{brand}፦ ሆስፒታሉ በ{when} የያዙትን ቀጠሮ መቀበል አልቻለም።{refund}",
    },
    BOOKING_CANCELLED: {
        "en": "{brand}: the hospital cancelled your visit on {when}.{refund}",
        "am": "{brand}፦ ሆስፒታሉ በ{when} የነበረዎትን ቀጠሮ ሰርዟል።{refund}",
    },
    BOOKING_UNANSWERED: {
        "en": "{brand}: the hospital did not answer your booking for {when}.{refund}",
        "am": "{brand}፦ ሆስፒታሉ ለ{when} ለያዙት ቀጠሮ ምላሽ አልሰጠም።{refund}",
    },
    REFUND: {
        "en": "{brand}:{refund}",
        "am": "{brand}፦{refund}",
    },
    FOLLOW_UP_SET: {
        "en": "{brand}: your doctor set a follow-up visit for {date}. Open the Endod app to book it.",
        "am": "{brand}፦ ሐኪምዎ ለ{date} የክትትል ጉብኝት ወስነዋል። ለማስያዝ የEndod መተግበሪያን ይክፈቱ።",
    },
    FOLLOW_UP_REMINDER: {
        "en": "{brand} reminder: your follow-up visit is tomorrow, {date}. Book it in the app if you have not.",
        "am": "{brand} ማስታወሻ፦ የክትትል ጉብኝትዎ ነገ {date} ነው። ካላስያዙ በመተግበሪያው ያስይዙ።",
    },
    QUEUE_NEAR: {
        "en": "{brand}: ticket {ticket}, {ahead_text}. Please be ready.",
        "am": "{brand}፦ ቁጥር {ticket}፣ {ahead_text}። እባክዎ ይዘጋጁ።",
    },
    QUEUE_TURN: {
        "en": "{brand}: it is your turn now (ticket {ticket}). Please go in.",
        "am": "{brand}፦ ተራዎ ደርሷል (ቁጥር {ticket})። እባክዎ ይግቡ።",
    },
    DEMO_BOOKED: {
        "en": "{brand}: your demo for {hospital} is booked for {when}. We will call you then.",
        "am": "{brand}፦ ለ{hospital} የማሳያ ቀጠሮዎ ለ{when} ተይዟል። በዚያ ሰዓት እንደውልልዎታለን።",
    },
    DEMO_MOVED: {
        "en": "{brand}: your demo for {hospital} has moved to {when}. We will call you then.",
        "am": "{brand}፦ ለ{hospital} የማሳያ ቀጠሮዎ ወደ {when} ተዛውሯል። በዚያ ሰዓት እንደውልልዎታለን።",
    },
    RX_CODE: {
        "en": "{brand}: prescription code {code} from {hospital}. Show it with your phone number at the pharmacy.",
        "am": "{brand}፦ ከ{hospital} የመድኃኒት ማዘዣ ኮድ {code}። በፋርማሲው ከስልክ ቁጥርዎ ጋር ያሳዩት።",
    },
    RX_DISPENSED: {
        "en": "{brand}: medicine from your prescription was given at a pharmacy. Details in the {brand} app.",
        "am": "{brand}፦ ከማዘዣዎ መድኃኒት በፋርማሲ ተሰጥቷል። ዝርዝሩ በ{brand} መተግበሪያ ውስጥ ነው።",
    },
}

TEMPLATES = frozenset(_TEXTS)


def handles(job: Dict[str, Any]) -> bool:
    return job.get("template") in TEMPLATES


def _language(value: Optional[str]) -> str:
    return value if value in ("en", "am") else "en"


def _refund_text(amount: Any, language: str) -> str:
    try:
        santim = int(amount or 0)
    except (TypeError, ValueError):
        santim = 0
    if santim <= 0:
        return ""
    birr = f"{santim / 100:,.2f}"
    if language == "am":
        return f" {birr} ብር ወደ Endod ሂሳብዎ ተመልሷል።"
    return f" {birr} birr is back in your Endod balance."


def _ahead_text(ahead: Any, language: str) -> str:
    count = int(ahead or 0)
    if language == "am":
        return "ከእርስዎ በፊት 1 ሰው አለ" if count == 1 else f"ከእርስዎ በፊት {count} ሰዎች አሉ"
    return f"{count} {'person' if count == 1 else 'people'} ahead of you"


def _render_one(template: str, params: Dict[str, Any], language: str) -> str:
    when = params.get("when", "")
    if isinstance(when, dict):  # per language (a demo's time)
        when = when.get(language) or when.get("en", "")
    values = {"brand": BRAND, "when": when, "date": params.get("date", ""),
              "hospital": params.get("hospital", ""),
              "ticket": params.get("ticket", ""), "code": params.get("code", ""),
              "refund": _refund_text(params.get("amount"), language),
              "ahead_text": _ahead_text(params.get("ahead"), language)}
    return _TEXTS[template][language].format(**values)


def render(job: Dict[str, Any]) -> str:
    """The text for a queued job (its payload holds the template's values)."""
    payload = job.get("payload") or {}
    params = payload.get("params") or {}
    template = job["template"]
    if payload.get("walk_in") or template in _BILINGUAL:
        # No account (so no known language), or a text the contract wants in
        # both: Amharic first, then English.
        return f"{_render_one(template, params, 'am')}\n{_render_one(template, params, 'en')}"
    return _render_one(template, params, _language(payload.get("language")))


# --- recipients ---------------------------------------------------------------------------

def sms_in_use() -> bool:
    from dedan_platform import scheduler

    return NotificationChannel.SMS in scheduler.reminder_channels()


def account_recipient(session: Session, user_id: str) -> Optional[Tuple[str, str]]:
    """(phone, language) for an account that can be texted now, else None.

    Read in the caller's session: handlers run inside a transaction, and a
    second session could wait on its locks."""
    if not sms_in_use():
        return None
    profile = session.scalar(select(Profile).where(Profile.user_id == user_id))
    prefs = session.scalar(select(Preferences).where(Preferences.user_id == user_id))
    if profile is None or not profile.phone or profile.phone_verified_at is None:
        return None
    if prefs is not None and not prefs.sms_notifications:
        return None
    return profile.phone, _language(getattr(prefs, "language", None))


# --- queueing -----------------------------------------------------------------------------

def enqueue(
    session: Session,
    *,
    user_id: str,
    destination: str,
    template: str,
    key: str,
    params: Dict[str, Any],
    language: Optional[str] = None,
    walk_in: bool = False,
    fire_at: Optional[datetime] = None,
) -> bool:
    """Queue one text in the caller's transaction. False when this key was
    already queued (a redelivered event, a retry): nothing is added then.

    A text with this key that was cancelled (a follow-up cancelled, then set
    again) is queued again; one sent, failed or skipped is never repeated.
    """
    if template not in TEMPLATES:
        raise ValueError(f"unknown SMS template {template!r}")
    payload = {"params": params, "language": _language(language), "walk_in": walk_in}
    when = fire_at or utcnow()
    existing = session.scalar(select(Notification).where(Notification.idempotency_key == key))
    if existing is not None:
        if existing.status != NotificationStatus.CANCELLED:
            return False
        existing.status = NotificationStatus.PENDING
        existing.user_id = user_id
        existing.scheduled_for = when
        existing.attempts = 0
        existing.last_error = None
        existing.destination = destination
        existing.payload_json = json.dumps(payload, ensure_ascii=False)
        existing.updated_at = utcnow()
        return True
    session.add(Notification(
        user_id=user_id, appointment_id=None, channel=NotificationChannel.SMS, template=template,
        destination=destination, idempotency_key=key, status=NotificationStatus.PENDING,
        scheduled_for=when, payload_json=json.dumps(payload, ensure_ascii=False),
    ))
    session.flush()
    return True


def to_account(session: Session, user_id: str, template: str, key: str, params: Dict[str, Any],
               fire_at: Optional[datetime] = None) -> bool:
    """Queue a text to an account, when it can be texted (see account_recipient)."""
    recipient = account_recipient(session, user_id)
    if recipient is None:
        return False
    phone, language = recipient
    return enqueue(session, user_id=user_id, destination=phone, template=template, key=key,
                   params=params, language=language, fire_at=fire_at)


def cancel_prefix(session: Session, prefix: str, keep_key: Optional[str] = None) -> int:
    """Cancel unsent texts whose key starts with ``prefix`` (except ``keep_key``)."""
    query = update(Notification).where(
        Notification.idempotency_key.startswith(prefix, autoescape=True),
        Notification.status.in_(list(NotificationStatus.CLAIMABLE)),
    )
    if keep_key:
        query = query.where(Notification.idempotency_key != keep_key)
    return session.execute(query.values(status=NotificationStatus.CANCELLED, updated_at=utcnow())).rowcount


# --- checked just before sending ----------------------------------------------------------

def stale_reason(job: Dict[str, Any]) -> Optional[str]:
    """Why a queued text must no longer be sent, or None."""
    from dedan_platform import identity, scheduler
    from dedan_platform.db import session_scope
    from dedan_platform.models import FollowUp, QueueEntry

    payload = job.get("payload") or {}
    params = payload.get("params") or {}
    template = job.get("template")
    if template in (FOLLOW_UP_SET, FOLLOW_UP_REMINDER):
        with session_scope() as session:
            follow_up = session.get(FollowUp, params.get("follow_up_id") or "")
            if follow_up is None or follow_up.cancelled_at is not None:
                return "follow_up_cancelled"
            if follow_up.follow_up_on != params.get("day"):
                return "follow_up_moved"
            if follow_up.user_id != job.get("user_id"):
                return "follow_up_moved_to_another_patient"
    if template in (QUEUE_NEAR, QUEUE_TURN):
        with session_scope() as session:
            entry = session.get(QueueEntry, params.get("entry_id") or "")
            wanted = "waiting" if template == QUEUE_NEAR else "called"
            if entry is not None and entry.status != wanted:
                return "queue_moved_on"
    if template == RX_CODE:
        from dedan_platform import prescriptions

        if not prescriptions.code_still_usable(params.get("rx_id") or ""):
            return "prescription_closed"
    if payload.get("walk_in"):
        return None
    try:
        profile = identity.get_profile_payload(job["user_id"])
    except identity.UserNotFound:
        return "account_not_found"
    if scheduler.current_destination(NotificationChannel.SMS, profile) != job.get("destination"):
        return "destination_changed_or_opted_out"
    return None
