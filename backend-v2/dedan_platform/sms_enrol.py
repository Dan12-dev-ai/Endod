"""SMS-only patients: a hospital enrols a patient without a smartphone (docs/sms.md).

Two events from the hospital service, each answered over the bus (run by the
events worker in the event's transaction, like linking in patient_history):

1. ``patient.sms_enrol_requested`` ``{request_id, hospital_id, patient_id, phone}``:
   a 6-digit code is texted to the phone (Amharic, then English: no account,
   so no known language). Reply ``patient.sms_enrol_code_sent``, or
   ``patient.sms_enrol_refused`` (``invalid_phone``, ``rate_limited``,
   ``sms_unavailable``). Nothing else about the patient is sent before the
   code proves the phone is theirs.
2. ``patient.sms_enrol_verify`` ``{request_id, hospital_id, patient_id, code,
   name, language}``: reception typed the code the patient read out. Right:
   the phone's account is linked to the hospital patient, or, when the phone
   has none, an SMS-only account is created (verified phone, no password,
   ``users.sms_only``) with a new Endod ID; the patient is texted their card
   number and a 4-digit PIN for the short code (sms_pin.py). Reply
   ``patient.sms_enrolled`` ``{..., dedan_id, name, phone, created}``. Wrong:
   ``patient.sms_enrol_refused`` with ``wrong_code`` and ``attempts_left``,
   or ``expired``, ``too_many_attempts``, ``superseded`` (a newer request
   for this patient), ``no_code``, ``not_allowed`` (a closed or suspended
   account).

Codes are stored as an HMAC bound to the request (phone_auth's), expire after
``SMS_ENROL_CODE_TTL_MINUTES`` (10) and allow ``SMS_ENROL_MAX_ATTEMPTS`` (5)
guesses; sending is limited per phone (a cooldown and an hourly cap) and per
hospital. Every enrolment is audited (``user_events``: ``sms_enrolled``,
with the hospital and whether the account was created).

A patient who later signs up in the app with the same phone (an SMS code,
phone_auth.complete) takes this account over: the phone already signs in to
it, so no second account is made, and ``sms_only`` is cleared.

PIN and card texts are sent once the transaction has committed, straight to
the provider (never through the notification queue, so the PIN is stored
nowhere in clear). If that send fails, reception enrols the patient again:
the account is found by its phone and a new PIN is texted.
"""

from __future__ import annotations

import hmac
import json
import logging
import secrets
from datetime import timedelta
from typing import Any, Dict, Optional, Tuple

from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from dedan_platform import eventbus, identity, sms_pin, sms_settings
from dedan_platform.db import ensure_aware
from dedan_platform.eventbus import RetryLater
from dedan_platform.models import (
    HospitalLink, PartnerHospital, Preferences, Profile, SmsEnrolment, User, UserEvent, utcnow,
)
from dedan_platform.phone import mask, normalise_ethiopian_mobile
from dedan_platform.sms_provider import BRAND_NAME as BRAND, SmsProvider, SmsProviderError, build_provider

logger = logging.getLogger(__name__)

HEX32 = r"^[0-9a-f]{32}$"
ZONE = "Africa/Addis_Ababa"

#: Tests replace it with a fake; None means the configured provider.
provider: Optional[SmsProvider] = None


def _provider() -> SmsProvider:
    return provider or build_provider()


class EnrolRequest(BaseModel):
    request_id: str = Field(pattern=HEX32)
    hospital_id: str = Field(min_length=1, max_length=32)
    patient_id: str = Field(min_length=1, max_length=64)
    phone: str = Field(min_length=1, max_length=32)


class EnrolVerify(BaseModel):
    request_id: str = Field(pattern=HEX32)
    hospital_id: str = Field(min_length=1, max_length=32)
    patient_id: str = Field(min_length=1, max_length=64)
    code: str = Field(min_length=1, max_length=12)
    name: Optional[str] = Field(default=None, max_length=160)
    language: Optional[str] = Field(default=None, max_length=8)


def _code_hash(request_id: str, code: str) -> str:
    from dedan_platform.phone_auth import _code_hash as code_hash

    return code_hash(request_id, code)


def _language(value: Optional[str]) -> str:
    return value if value in ("am", "en") else "am"


# --- texts --------------------------------------------------------------------------------

def code_text(code: str, minutes: int) -> str:
    """The verification code: Amharic, then English (no account language yet)."""
    return (f"{BRAND}፦ የማረጋገጫ ኮድ {code}። ለሆስፒታሉ መቀበያ ብቻ ይንገሩ። በ{minutes} ደቂቃ ያልፋል።\n"
            f"{BRAND} code {code}: tell it only to the hospital reception to join Endod by SMS. "
            f"Expires in {minutes} min.")


def welcome_text(card: str, pin: Optional[str], language: str) -> str:
    """The card number and, for a new PIN, the PIN and how to use and change it.
    Mentions the short code only while patients can text it (sms_settings)."""
    live = sms_settings.inbound_live()
    short = sms_settings.short_code()
    if pin is None:
        if language == "am":
            return f"{BRAND}፦ አንድ ሆስፒታል መዝገብዎን ከEndod መለያዎ ጋር አገናኝቷል። የካርድ ቁጥርዎ {card} ነው።"
        return f"{BRAND}: a hospital linked your records to your Endod account. Your card number is {card}."
    if language == "am":
        head = f"{BRAND}፦ የEndod ካርድ ቁጥርዎ {card} ነው። የSMS ፒንዎ {pin} ነው፤ ለማንም አይንገሩ።"
        if live:
            return (f"{head} ውጤትና ቀጠሮዎን ለማግኘት HELP ብለው ወደ {short} ይላኩ። "
                    f"ፒኑን ለመቀየር PIN {pin} እና አዲሱን ፒን ይላኩ።")
        return f"{head} ውጤትዎን በSMS ለማግኘት ይጠቀሙበታል። አዲስ ፒን ከፈለጉ ሆስፒታሉን ይጠይቁ።"
    head = f"{BRAND}: your Endod card number is {card}. Your SMS PIN is {pin}; keep it secret."
    if live:
        return (f"{head} Text HELP to {short} for your results and visits. "
                f"To change the PIN, text PIN {pin} and a new PIN.")
    return (f"{head} You will use it to get your results by SMS. "
            "Ask at the hospital if you need a new one.")


def _send_later(session: Session, phone: str, text: str, what: str) -> None:
    def send() -> None:
        try:
            _provider().send(phone, text)
            logger.info("sms_enrol_%s_sent to=%s", what, mask(phone))
        except SmsProviderError as exc:
            # The text holds a PIN: never queued for a retry (it would be
            # stored in clear). Reception enrols the patient again for a new one.
            logger.error("sms_enrol_%s_failed to=%s: %s", what, mask(phone), exc)

    eventbus.after_commit(session, send)


# --- 1. the code --------------------------------------------------------------------------

def _refuse(session: Session, echo: Dict[str, Any], reason: str, attempts_left: Optional[int] = None) -> None:
    eventbus.emit(session, "patient.sms_enrol_refused", {**echo, "reason": reason, "attempts_left": attempts_left})


def _limited(session: Session, phone: str, hospital_id: str) -> bool:
    now = utcnow()
    hour_ago = now - timedelta(hours=1)
    recent = session.scalars(select(SmsEnrolment.created_at).where(
        SmsEnrolment.phone == phone, SmsEnrolment.created_at > hour_ago)
        .order_by(SmsEnrolment.created_at.desc())).all()
    if recent and (now - ensure_aware(recent[0])).total_seconds() < sms_settings.number("SMS_ENROL_RESEND_SECONDS"):
        return True
    if len(recent) >= sms_settings.number("SMS_ENROL_MAX_PER_PHONE_PER_HOUR"):
        return True
    by_hospital = session.scalar(select(func.count()).select_from(SmsEnrolment).where(
        SmsEnrolment.hospital_id == hospital_id, SmsEnrolment.created_at > hour_ago)) or 0
    return by_hospital >= sms_settings.number("SMS_ENROL_MAX_PER_HOSPITAL_PER_HOUR")


def on_enrol_requested(session: Session, payload: Dict[str, Any]) -> None:
    from dedan_platform.patient_history import _parse

    request = _parse(EnrolRequest, payload)
    echo = {"request_id": request.request_id, "hospital_id": request.hospital_id,
            "patient_id": request.patient_id}
    if session.get(SmsEnrolment, request.request_id) is not None:
        return  # this request again (sent twice): its code went out already
    phone = normalise_ethiopian_mobile(request.phone)
    if phone is None:
        _refuse(session, echo, "invalid_phone")
        return
    if _limited(session, phone, request.hospital_id):
        _refuse(session, echo, "rate_limited")
        return
    now = utcnow()
    minutes = max(1, sms_settings.number("SMS_ENROL_CODE_TTL_MINUTES"))
    code = f"{secrets.randbelow(1_000_000):06d}"
    row = SmsEnrolment(id=request.request_id, hospital_id=request.hospital_id, patient_id=request.patient_id,
                       phone=phone, code_hash=_code_hash(request.request_id, code),
                       expires_at=now + timedelta(minutes=minutes), attempts=0, created_at=now)
    try:
        # Sent now: the hospital is told only once it went. If this
        # transaction then failed, the event is retried and a new code sent
        # (only the newest counts).
        _provider().send(phone, code_text(code, minutes))
    except SmsProviderError as exc:
        logger.error("sms_enrol_code_failed to=%s: %s", mask(phone), exc)
        _refuse(session, echo, "sms_unavailable")
        return
    session.add(row)
    logger.info("sms_enrol_code_sent to=%s hospital=%s", mask(phone), request.hospital_id)
    eventbus.emit(session, "patient.sms_enrol_code_sent", {**echo, "expires_at": row.expires_at.isoformat()})


# --- 2. the check, and the account ---------------------------------------------------------

def _names(name: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    parts = (name or "").split()
    if not parts:
        return None, None
    return parts[0], " ".join(parts[1:]) or None


def _phone_owner(session: Session, phone: str) -> Optional[User]:
    """The account that signs in with this verified phone (unique among verified phones)."""
    return session.scalar(select(User).join(Profile, Profile.user_id == User.id).where(
        Profile.phone == phone, Profile.phone_verified_at.is_not(None)).limit(1))


def _link(session: Session, user: User, hospital_id: str, patient_id: str) -> bool:
    """Link the hospital patient to ``user`` (as patient.linked does). True when new."""
    link = session.scalar(select(HospitalLink).where(
        HospitalLink.hospital_id == hospital_id, HospitalLink.patient_id == patient_id).with_for_update())
    if link is None:
        session.add(HospitalLink(user_id=user.id, hospital_id=hospital_id, patient_id=patient_id))
        return True
    if link.user_id != user.id:
        link.user_id = user.id
        link.linked_at = utcnow()
        return True
    return False


def _enrolled_event(session: Session, echo: Dict[str, Any], user: User, phone: str, created: bool) -> None:
    from dedan_platform.patient_history import _full_name

    profile = session.scalar(select(Profile).where(Profile.user_id == user.id))
    eventbus.emit(session, "patient.sms_enrolled", {
        **echo, "dedan_id": user.dedan_user_id, "name": _full_name(profile, user.dedan_user_id),
        "phone": phone, "created": created})


def on_enrol_verify(session: Session, payload: Dict[str, Any]) -> None:
    from dedan_platform.patient_history import _inbox_later, _parse

    request = _parse(EnrolVerify, payload)
    echo = {"request_id": request.request_id, "hospital_id": request.hospital_id,
            "patient_id": request.patient_id}
    row = session.get(SmsEnrolment, request.request_id, with_for_update=True)
    if row is None or (row.hospital_id, row.patient_id) != (request.hospital_id, request.patient_id):
        _refuse(session, echo, "no_code")
        return
    if row.verified_at is not None:
        user = session.get(User, row.user_id) if row.user_id else None
        if user is not None:  # verified already (the hospital asked twice): the same answer
            _enrolled_event(session, echo, user, row.phone, created=False)
        else:
            _refuse(session, echo, "no_code")
        return
    newest = session.scalar(select(SmsEnrolment.id).where(
        SmsEnrolment.hospital_id == row.hospital_id, SmsEnrolment.patient_id == row.patient_id)
        .order_by(SmsEnrolment.created_at.desc(), SmsEnrolment.id.desc()).limit(1))
    if newest != row.id:
        _refuse(session, echo, "superseded")
        return
    now = utcnow()
    if ensure_aware(row.expires_at) <= now:
        _refuse(session, echo, "expired")
        return
    limit = max(1, sms_settings.number("SMS_ENROL_MAX_ATTEMPTS"))
    spent = session.execute(update(SmsEnrolment).where(
        SmsEnrolment.id == row.id, SmsEnrolment.attempts < limit).values(attempts=SmsEnrolment.attempts + 1)).rowcount
    if not spent:
        _refuse(session, echo, "too_many_attempts", 0)
        return
    session.refresh(row)
    code = "".join(ch for ch in request.code if not ch.isspace())
    if not (len(code) == 6 and code.isdigit() and hmac.compare_digest(row.code_hash, _code_hash(row.id, code))):
        left = max(0, limit - row.attempts)
        _refuse(session, echo, "wrong_code" if left else "too_many_attempts", left)
        return

    user = _phone_owner(session, row.phone)
    if user is not None and (not user.is_active or user.suspended_at is not None):
        # Closed, or suspended by an Endod admin: no new link (as for patient.link_requested).
        row.verified_at = now
        _refuse(session, echo, "not_allowed")
        return
    created = user is None
    if created:
        first, last = _names(request.name)
        try:
            user = identity.new_account(
                session, display_name=(request.name or "").strip()[:120] or None, first_name=first,
                last_name=last, phone=row.phone, phone_verified=True, locale=_language(request.language),
                timezone_name=ZONE, country_code="ET", sms_only=True,
                audit={"via": "sms_enrol", "hospital_id": row.hospital_id},
            )
        except identity.PhoneInUse as exc:
            raise RetryLater("an account was just created for this phone") from exc
    language = session.scalar(select(Preferences.language).where(Preferences.user_id == user.id))
    language = language if language in ("am", "en") else _language(request.language)
    is_new_link = _link(session, user, row.hospital_id, row.patient_id)
    # A new PIN for a new account, for an SMS-only one enrolled again (how a
    # forgotten PIN is replaced), and for an app account that has none yet.
    pin = None
    if created or user.sms_only or not sms_pin.has_pin(session, user.id):
        pin = sms_pin.generate()
        sms_pin.set_pin(session, user.id, pin)
    row.verified_at = now
    row.user_id = user.id
    session.add(UserEvent(user_id=user.id, event_type="sms_enrolled", payload=json.dumps(
        {"hospital_id": row.hospital_id, "created": created, "new_pin": pin is not None})))
    _enrolled_event(session, echo, user, row.phone, created)
    _send_later(session, row.phone, welcome_text(user.dedan_user_id, pin, language), "welcome")
    if is_new_link and not created:
        hospital = session.get(PartnerHospital, row.hospital_id)
        name = hospital.name if hospital is not None else "A hospital"
        _inbox_later(session, user.id, "hospital_linked", f"{name} linked your records to Endod",
                     "New records from this hospital will appear in your history.", "history", None)
    logger.info("sms_enrolled user_id=%s hospital=%s created=%s", user.id, row.hospital_id, created)


HANDLERS = {
    "patient.sms_enrol_requested": on_enrol_requested,
    "patient.sms_enrol_verify": on_enrol_verify,
}
