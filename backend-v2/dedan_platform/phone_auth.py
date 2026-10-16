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
* A password can only be set with a token from a verified code, and each
  verification can be used once (claimed atomically).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import threading
import time
from collections import deque
from datetime import timedelta
from typing import Any, Deque, Dict, Optional

from sqlalchemy import select, update

from dedan_platform import credentials, identity
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
OTP_MAX_PER_CLIENT_PER_HOUR = int(os.getenv("OTP_MAX_PER_CLIENT_PER_HOUR", "10"))
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


class _ClientWindow:
    """Code requests per client in the last hour (in-process)."""

    def __init__(self) -> None:
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def take(self, client: str, limit: int) -> Optional[int]:
        """Record one request; returns seconds to wait if over ``limit``."""
        now = time.time()
        with self._lock:
            hits = self._hits.setdefault(client or "unknown", deque())
            while hits and hits[0] <= now - 3600:
                hits.popleft()
            if len(hits) >= limit:
                return int(hits[0] + 3600 - now) + 1
            hits.append(now)
            if len(self._hits) > 50_000:
                for stale in list(self._hits)[:5_000]:
                    self._hits.pop(stale, None)
        return None


_client_window = _ClientWindow()


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


def request_code(phone_input: str, client: str = "unknown", provider: Optional[SmsProvider] = None) -> Dict[str, Any]:
    """Text a verification code to ``phone_input``."""
    phone = _phone_or_raise(phone_input)

    wait = _client_window.take(client, OTP_MAX_PER_CLIENT_PER_HOUR)
    if wait is not None:
        raise TooManyRequests("Too many code requests. Please try again later.", wait)

    now = utcnow()
    with session_scope() as session:
        recent = session.scalars(
            select(PhoneVerification.created_at)
            .where(PhoneVerification.phone == phone)
            .where(PhoneVerification.created_at > now - timedelta(hours=1))
            .order_by(PhoneVerification.created_at.desc())
        ).all()
    if recent:
        latest = recent[0] if recent[0].tzinfo else recent[0].replace(tzinfo=now.tzinfo)
        since = (now - latest).total_seconds()
        if since < OTP_RESEND_SECONDS:
            wait = int(OTP_RESEND_SECONDS - since) + 1
            raise TooManyRequests(f"Please wait {wait} seconds before requesting another code.", wait)
    if len(recent) >= OTP_MAX_PER_PHONE_PER_HOUR:
        raise TooManyRequests("Too many codes sent to this number. Please try again in an hour.", 3600)

    verification_id = new_uuid()
    code = f"{secrets.randbelow(1_000_000):06d}"
    text = (
        f"{BRAND_NAME} verification code: {code}. It expires in {OTP_TTL_MINUTES} minutes. "
        "Do not share it with anyone."
    )
    try:
        message_id = (provider or build_provider()).send(phone, text)
    except SmsProviderError as exc:
        logger.error("otp_send_failed to=%s: %s", mask(phone), exc)
        raise SmsUnavailable("We could not send the code right now. Please try again shortly.") from exc

    with session_scope() as session:
        session.add(PhoneVerification(
            id=verification_id,
            phone=phone,
            code_hash=_code_hash(verification_id, code),
            expires_at=now + timedelta(minutes=OTP_TTL_MINUTES),
            client=(client or "unknown")[:64],
            provider_message_id=message_id,
        ))
    logger.info("otp_sent to=%s", mask(phone))
    return {"expires_in": OTP_TTL_MINUTES * 60, "resend_after": OTP_RESEND_SECONDS}


def verify_code(phone_input: str, code: str) -> Dict[str, Any]:
    """Check ``code`` against the latest code sent to the phone."""
    phone = _phone_or_raise(phone_input)
    code = "".join(ch for ch in (code or "") if not ch.isspace())
    if len(code) != 6 or not code.isdigit():
        raise InvalidCode("Enter the 6-digit code from the SMS.")

    now = utcnow()
    outcome = "invalid"
    verification_id = None
    with session_scope() as session:
        row = session.scalar(
            select(PhoneVerification)
            .where(PhoneVerification.phone == phone)
            .where(PhoneVerification.verified_at.is_(None))
            .order_by(PhoneVerification.created_at.desc())
            .limit(1)
        )
        if row is None:
            outcome = "missing"
        else:
            expires_at = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=now.tzinfo)
            if expires_at <= now:
                outcome = "expired"
            elif row.attempts >= OTP_MAX_ATTEMPTS:
                outcome = "locked"
            elif hmac.compare_digest(row.code_hash, _code_hash(row.id, code)):
                row.verified_at = now
                outcome = "ok"
                verification_id = row.id
            else:
                # Committed by the scope (no exception raised inside it).
                row.attempts += 1
                outcome = "locked" if row.attempts >= OTP_MAX_ATTEMPTS else "wrong"

    if outcome == "missing":
        raise InvalidCode("No code was requested for this number. Please request a new one.")
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


def complete(
    verification_token: str,
    password: str,
    password_confirmation: Optional[str] = None,
    display_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Create the account (or reset its password) and sign the patient in."""
    try:
        payload = decode_token(verification_token)
    except AuthError as exc:
        raise InvalidVerification("Your verification has expired. Please verify your phone again.") from exc
    if payload.get("scope") != VERIFICATION_SCOPE:
        raise InvalidVerification("Your verification has expired. Please verify your phone again.")

    # Policy first, so a weak password does not burn the verification.
    credentials.validate_password(password, password_confirmation)

    now = utcnow()
    with session_scope() as session:
        phone = session.scalar(
            select(PhoneVerification.phone).where(PhoneVerification.id == payload["sub"])
        )
        # Atomic claim: of two concurrent requests with one token, one wins.
        claimed = session.execute(
            update(PhoneVerification)
            .where(PhoneVerification.id == payload["sub"])
            .where(PhoneVerification.verified_at.is_not(None))
            .where(PhoneVerification.used_at.is_(None))
            .values(used_at=now)
        ).rowcount
    if not claimed or not phone:
        raise InvalidVerification("This verification was already used. Please verify your phone again.")

    user = identity.find_user_by_phone(phone)
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

