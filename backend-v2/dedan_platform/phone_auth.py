"""
Phone sign-up and password reset with SMS verification codes.

Flow (matches the Next.js pages signup -> verify-otp -> set-password):

1. `request_code(phone)` texts a 6-digit code. The answer is the same whether
   or not an account exists for the phone, so it cannot be used to discover
   who is registered.
2. `verify_code(phone, code)` checks it and returns a short-lived, single-use
   verification token.
3. `complete(token, password)` creates the account, or resets the password if
   the phone already has one, and signs the patient in.

Protections
-----------
* Codes come from `secrets`, are stored only as an HMAC bound to their row,
  expire after `OTP_TTL_MINUTES`, and allow `OTP_MAX_ATTEMPTS` guesses.
* Sending is limited per phone (cooldown and hourly cap) and per client, so the
  endpoint cannot be used to run up the SMS bill or flood someone's phone.
  The limits are counted in the database, so every replica shares them.
* Only the newest code for a phone can be verified, and each guess spends an
  attempt atomically, so parallel guesses cannot exceed the limit.
* A password can only be set with a token from a verified code, and each
  verification can be used once (claimed atomically).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import delete, func, select, update

from dedan_platform import credentials, identity, inbox
from dedan_platform.db import new_uuid, session_scope
from dedan_platform.models import PhoneVerification, utcnow
from dedan_platform.phone import mask, normalise_ethiopian_mobile
from dedan_platform.sms_provider import SmsProvider, SmsProviderError, build_provider
from realtime.auth import AuthError, decode_token, issue_token, signing_secret

logger = logging.getLogger(__name__)

OTP_TTL_MINUTES = int(os.getenv("OTP_TTL_MINUTES", "5"))
OTP_MAX_ATTEMPTS = int(os.getenv("OTP_MAX_ATTEMPTS", "5"))
OTP_RESEND_SECONDS = int(os.getenv("OTP_RESEND_SECONDS", "60"))
OTP_MAX_PER_PHONE_PER_HOUR = int(os.getenv("OTP_MAX_PER_PHONE_PER_HOUR", "5"))
OTP_MAX_PER_CLIENT_PER_HOUR = int(os.getenv("OTP_MAX_PER_CLIENT_PER_HOUR", "30"))
#: How long a verified code may be used to set the password.
VERIFICATION_TOKEN_TTL_SECONDS = int(os.getenv("PHONE_VERIFICATION_TTL", "900"))
VERIFICATION_SCOPE = "phone_verification"
BRAND_NAME = os.getenv("SMS_BRAND_NAME", "Endod Health")


class PhoneAuthError(RuntimeError):
    """Base class; the message is safe to show the patient."""


class InvalidPhone(PhoneAuthError):
    pass


class TooManyRequests(PhoneAuthError):
    def __init__(self, message: str, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class InvalidCode(PhoneAuthError):
    pass


class InvalidVerification(PhoneAuthError):
    pass


class SmsUnavailable(PhoneAuthError):
    pass


class PhoneInUse(PhoneAuthError):
    pass


class AccountDeactivated(PhoneAuthError):
    pass


def _code_hash(verification_id: str, code: str) -> str:
    key = signing_secret().encode("utf-8")
    if not key:
        raise AuthError("No token signing secret configured.")
    return hmac.new(key, f"{verification_id}:{code}".encode("ascii"), hashlib.sha256).hexdigest()


def _phone_or_raise(value: Optional[str]) -> str:
    phone = normalise_ethiopian_mobile(value)
    if phone is None:
        raise InvalidPhone("Enter a valid Ethiopian mobile number, e.g. 0911 234 567.")
    return phone


def _aware(value: datetime, like: datetime) -> datetime:
    # SQLite returns naive datetimes; they were stored as UTC.
    return value if value.tzinfo else value.replace(tzinfo=like.tzinfo)


def _delete(verification_id: str) -> None:
    with session_scope() as session:
        session.execute(delete(PhoneVerification).where(PhoneVerification.id == verification_id))


def _limit_violation(phone: str, client: str, own_id: str, now: datetime) -> Optional[TooManyRequests]:
    """Check the limits *after* recording this request.

    Counting rows that already include this one means simultaneous requests,
    from any process or replica, see each other in the database: none of them
    can slip through a check that ran before the others were recorded.
    """
    hour_ago = now - timedelta(hours=1)
    with session_scope() as session:
        phone_times = session.scalars(
            select(PhoneVerification.created_at)
            .where(PhoneVerification.phone == phone)
            .where(PhoneVerification.created_at > hour_ago)
            .where(PhoneVerification.id != own_id)
            .order_by(PhoneVerification.created_at.desc())
        ).all()
        client_count = session.scalar(
            select(func.count())
            .select_from(PhoneVerification)
            .where(PhoneVerification.client == client)
            .where(PhoneVerification.created_at > hour_ago)
        ) or 0
    if phone_times:
        since = (now - _aware(phone_times[0], now)).total_seconds()
        if since < OTP_RESEND_SECONDS:
            wait = int(OTP_RESEND_SECONDS - since) + 1
            return TooManyRequests(f"Please wait {wait} seconds before requesting another code.", wait)
    if len(phone_times) >= OTP_MAX_PER_PHONE_PER_HOUR:
        return TooManyRequests("Too many codes sent to this number. Please try again in an hour.", 3600)
    if client_count > OTP_MAX_PER_CLIENT_PER_HOUR:
        return TooManyRequests("Too many code requests. Please try again later.", 3600)
    return None


def request_code(phone_input: str, client: str = "unknown", provider: Optional[SmsProvider] = None) -> Dict[str, Any]:
    """Text a verification code to ``phone_input``.

    The code is recorded before it is sent, so a code the patient receives can
    always be verified, and the limits are checked against the database (shared
    by every replica) including this request.
    """
    phone = _phone_or_raise(phone_input)
    client = (client or "unknown")[:64]
    now = utcnow()
    verification_id = new_uuid()
    code = f"{secrets.randbelow(1_000_000):06d}"

    with session_scope() as session:
        session.add(PhoneVerification(
            id=verification_id,
            phone=phone,
            code_hash=_code_hash(verification_id, code),
            expires_at=now + timedelta(minutes=OTP_TTL_MINUTES),
            client=client,
        ))
    violation = _limit_violation(phone, client, verification_id, now)
    if violation is not None:
        _delete(verification_id)
        raise violation

    text = (
        f"{BRAND_NAME} verification code: {code}. It expires in {OTP_TTL_MINUTES} minutes. "
        "Do not share it with anyone."
    )
    try:
        message_id = (provider or build_provider()).send(phone, text)
    except SmsProviderError as exc:
        # Removed so a provider outage does not use up the patient's cooldown.
        _delete(verification_id)
        logger.error("otp_send_failed to=%s: %s", mask(phone), exc)
        raise SmsUnavailable("We could not send the code right now. Please try again shortly.") from exc

    if message_id:
        with session_scope() as session:
            session.execute(
                update(PhoneVerification)
                .where(PhoneVerification.id == verification_id)
                .values(provider_message_id=message_id)
            )
    logger.info("otp_sent to=%s", mask(phone))
    return {"expires_in": OTP_TTL_MINUTES * 60, "resend_after": OTP_RESEND_SECONDS}


def verify_code(phone_input: str, code: str) -> Dict[str, Any]:
    """Check ``code`` against the newest code sent to the phone.

    Only the newest code counts: requesting a new code retires the earlier
    ones, even if they have not expired.
    """
    phone = _phone_or_raise(phone_input)
    code = "".join(ch for ch in (code or "") if not ch.isspace())
    if len(code) != 6 or not code.isdigit():
        raise InvalidCode("Enter the 6-digit code from the SMS.")

    now = utcnow()
    verification_id = None
    with session_scope() as session:
        row = session.scalar(
            select(PhoneVerification)
            .where(PhoneVerification.phone == phone)
            .order_by(PhoneVerification.created_at.desc())
            .limit(1)
        )
        if row is None:
            outcome = "missing"
        elif row.verified_at is not None:
            outcome = "used"
        elif _aware(row.expires_at, now) <= now:
            outcome = "expired"
        else:
            # Spend an attempt atomically *before* comparing, so parallel
            # guesses cannot exceed the limit by racing each other.
            spent = session.execute(
                update(PhoneVerification)
                .where(PhoneVerification.id == row.id)
                .where(PhoneVerification.attempts < OTP_MAX_ATTEMPTS)
                .where(PhoneVerification.verified_at.is_(None))
                .values(attempts=PhoneVerification.attempts + 1)
            ).rowcount
            if not spent:
                outcome = "locked"
            elif hmac.compare_digest(row.code_hash, _code_hash(row.id, code)):
                marked = session.execute(
                    update(PhoneVerification)
                    .where(PhoneVerification.id == row.id)
                    .where(PhoneVerification.verified_at.is_(None))
                    .values(verified_at=now)
                ).rowcount
                outcome = "ok" if marked else "used"
                verification_id = row.id
            else:
                outcome = "locked" if row.attempts + 1 >= OTP_MAX_ATTEMPTS else "wrong"

    if outcome == "missing":
        raise InvalidCode("No code was requested for this number. Please request a new one.")
    if outcome == "used":
        raise InvalidCode("This code was already used. Please request a new one.")
    if outcome == "expired":
        raise InvalidCode("The code has expired. Please request a new one.")
    if outcome == "locked":
        raise InvalidCode("Too many incorrect attempts. Please request a new code.")
    if outcome != "ok":
        raise InvalidCode("Incorrect code. Please try again.")

    return {
        "verification_token": issue_token(
            verification_id, expires_in=VERIFICATION_TOKEN_TTL_SECONDS, scope=VERIFICATION_SCOPE
        ),
        "expires_in": VERIFICATION_TOKEN_TTL_SECONDS,
        # Safe to reveal now: the caller has proved they hold the phone.
        "account_exists": identity.find_user_by_phone(phone) is not None,
    }


def _verified_phone(verification_token: str) -> Tuple[str, str]:
    """(phone, verification id) for a still-unused verification token, or raise."""
    try:
        payload = decode_token(verification_token)
    except AuthError as exc:
        raise InvalidVerification("Your verification has expired. Please verify your phone again.") from exc
    if payload.get("scope") != VERIFICATION_SCOPE:
        raise InvalidVerification("Your verification has expired. Please verify your phone again.")
    with session_scope() as session:
        row = session.get(PhoneVerification, payload["sub"])
        if row is None or row.verified_at is None or row.used_at is not None:
            raise InvalidVerification("This verification was already used. Please verify your phone again.")
        return row.phone, row.id


def _claim(verification_id: str) -> None:
    """Mark a verification used. Of two concurrent claims, exactly one wins."""
    with session_scope() as session:
        claimed = session.execute(
            update(PhoneVerification)
            .where(PhoneVerification.id == verification_id)
            .where(PhoneVerification.verified_at.is_not(None))
            .where(PhoneVerification.used_at.is_(None))
            .values(used_at=utcnow())
        ).rowcount
    if not claimed:
        raise InvalidVerification("This verification was already used. Please verify your phone again.")


def complete(
    verification_token: str,
    password: str,
    password_confirmation: Optional[str] = None,
    display_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Create the account (or reset its password) and sign the patient in.

    Only an account whose phone is *verified* is treated as the phone's owner.
    An account that merely typed the number into its profile is not: a
    mistyped or recycled number would otherwise let whoever holds it reset
    that account's password. Such patients link the phone while signed in
    (`link_to_account`).
    """
    phone, verification_id = _verified_phone(verification_token)
    # Policy first, so a weak password does not burn the verification.
    credentials.validate_password(password, password_confirmation)

    user = identity.find_user_by_phone(phone)
    if user is not None and not user.is_active:
        raise AccountDeactivated("This account has been deactivated. Please contact support.")
    _claim(verification_id)

    created = user is None
    if created:
        try:
            result = identity.create_user(
                display_name=(display_name or "").strip() or None,
                phone=phone,
                phone_verified=True,
                locale="en",
                timezone_name="Africa/Addis_Ababa",
                country_code="ET",
            )
        except identity.PhoneInUse as exc:
            raise PhoneInUse("An account was just created for this number. Please sign in.") from exc
        internal_user_id = result["internal_user_id"]
    else:
        internal_user_id = user.id

    # For an existing account this is a password reset; it also signs out the
    # account's other sessions (credentials.password_changed_at).
    credentials.set_credential(internal_user_id, password)
    if not created:
        inbox.add_item(
            internal_user_id, "security", "password_reset", "Your password was reset by phone",
            body="If this wasn't you, contact support immediately.",
        )
    user = identity.get_user_by_internal_id(internal_user_id)
    logger.info("phone_auth_complete user_id=%s created=%s", internal_user_id, created)
    return {
        "access_token": issue_token(
            user.dedan_user_id, expires_in=credentials.SESSION_TTL_SECONDS, scope="portal"
        ),
        "token_type": "DEDAN",
        "expires_in": credentials.SESSION_TTL_SECONDS,
        "dedan_user_id": user.dedan_user_id,
        "created": created,
        "profile": identity.get_profile_payload(internal_user_id),
    }


def link_to_account(internal_user_id: str, verification_token: str) -> Dict[str, Any]:
    """Attach a verified phone to the signed-in account.

    How a patient who registered by email (or typed their phone into the
    profile) gains phone sign-in without creating a second account.
    """
    phone, verification_id = _verified_phone(verification_token)
    owner = identity.find_user_by_phone(phone)
    if owner is not None and owner.id != internal_user_id:
        raise PhoneInUse("This number already signs in to another account.")
    _claim(verification_id)
    try:
        profile = identity.set_verified_phone(internal_user_id, phone)
        inbox.add_item(internal_user_id, "security", "phone_verified", "Phone number verified",
                       body="You can now sign in with this number.")
        return profile
    except identity.PhoneInUse as exc:
        raise PhoneInUse("This number already signs in to another account.") from exc
