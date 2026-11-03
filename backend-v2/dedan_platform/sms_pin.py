"""The 4-digit PIN a patient texts with each command to the short code.

* Generated with ``secrets`` when a hospital enrols the patient (texted to
  them once), or chosen by the patient (``PIN <old> <new>`` by SMS, or in the
  app's settings); never a PIN like 0000 or 1234.
* Stored only as an HMAC under the server's signing secret, bound to the
  account: a copy of the database alone does not allow the 10,000 guesses.
* ``SMS_PIN_MAX_ATTEMPTS`` wrong PINs in a row (default 5) lock it for
  ``SMS_PIN_LOCK_MINUTES`` (default 60); a right PIN resets the count. The
  count is spent atomically, so parallel guesses cannot exceed it.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

from dedan_platform import sms_settings
from dedan_platform.db import ensure_aware
from dedan_platform.models import SmsPin, utcnow
from realtime.auth import AuthError, signing_secret

#: PINs too easy to guess.
_WEAK = frozenset({"1234", "4321", "1212", "1122", "2580", "0852", "1984", "2000", "1010", "6969", "0123",
                   "9876", "1004", "2001", "1111", "0000"})


class PinError(ValueError):
    """The new PIN is not acceptable (the message says why)."""


def _hash(user_id: str, pin: str) -> str:
    key = signing_secret().encode("utf-8")
    if not key:
        raise AuthError("No token signing secret configured.")
    return hmac.new(key, f"sms-pin:{user_id}:{pin}".encode("ascii"), hashlib.sha256).hexdigest()


def is_pin(value: Optional[str]) -> bool:
    return bool(value) and len(value) == 4 and value.isascii() and value.isdigit()


def acceptable(pin: str) -> bool:
    return is_pin(pin) and len(set(pin)) > 1 and pin not in _WEAK


def generate() -> str:
    while True:
        pin = f"{secrets.randbelow(10_000):04d}"
        if acceptable(pin):
            return pin


def set_pin(session: Session, user_id: str, pin: str) -> None:
    """Store ``pin`` (in the caller's transaction); unlocks the PIN."""
    if not acceptable(pin):
        raise PinError("Choose 4 digits that are not all the same and not a sequence like 1234.")
    row = session.get(SmsPin, user_id)
    now = utcnow()
    if row is None:
        session.add(SmsPin(user_id=user_id, pin_hash=_hash(user_id, pin), failed_attempts=0, created_at=now,
                           changed_at=now))
    else:
        row.pin_hash = _hash(user_id, pin)
        row.failed_attempts = 0
        row.locked_until = None
        row.changed_at = now
    session.flush()


def has_pin(session: Session, user_id: str) -> bool:
    return session.get(SmsPin, user_id) is not None


@dataclass(frozen=True)
class Check:
    #: "ok", "wrong", "locked" (just now, or still), "no_pin".
    outcome: str
    attempts_left: int = 0
    locked_until: Optional[datetime] = None
    #: True when this guess locked it (the patient is told once).
    just_locked: bool = False


def check(session: Session, user_id: str, pin: str) -> Check:
    """Check ``pin`` and count a wrong one (in the caller's transaction)."""
    row = session.get(SmsPin, user_id)
    if row is None:
        return Check("no_pin")
    now = utcnow()
    if row.locked_until is not None and ensure_aware(row.locked_until) > now:
        return Check("locked", locked_until=ensure_aware(row.locked_until))
    limit = max(1, sms_settings.number("SMS_PIN_MAX_ATTEMPTS"))
    if row.locked_until is not None:  # the lock has passed: a fresh count
        row.locked_until = None
        row.failed_attempts = 0
    if is_pin(pin) and hmac.compare_digest(row.pin_hash, _hash(user_id, pin)):
        row.failed_attempts = 0
        session.flush()
        return Check("ok")
    # Spent atomically in the database, so parallel guesses see each other.
    session.flush()
    session.execute(update(SmsPin).where(SmsPin.user_id == user_id)
                    .values(failed_attempts=SmsPin.failed_attempts + 1))
    session.refresh(row)
    if row.failed_attempts >= limit:
        until = now + timedelta(minutes=max(1, sms_settings.number("SMS_PIN_LOCK_MINUTES")))
        row.locked_until = until
        session.flush()
        return Check("locked", locked_until=until, just_locked=True)
    return Check("wrong", attempts_left=limit - row.failed_attempts)
