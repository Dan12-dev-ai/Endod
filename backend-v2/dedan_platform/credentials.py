"""
Password credentials for the web portal.

Why this module exists
----------------------
The platform had a complete, authorization-aware REST API (`/users/me/**` all
resolve the caller through a verified token) but **no way for anyone to obtain a
token**: there was no signup, no login, and no issuer. The portal therefore could
not talk to its own backend at all.

This module is the missing credential half. It is deliberately small:

  * **Standard library only** -- `hashlib.pbkdf2_hmac` and `secrets`. No new
    dependency is added to a project that pins its runtime carefully.
  * **The token scheme is not reinvented.** Signatures come from
    `realtime.auth.issue_token`, the same issuer the websocket path already
    trusts, so one credential works for both the REST API and live voice.

Deliberate security properties
------------------------------
* Passwords are never stored, logged, or echoed. Only a PBKDF2-HMAC-SHA256 digest
  with a per-user salt is persisted.
* Login failures are **uniform**. A wrong password and an unknown account return
  the same message and take a comparable amount of time, so the endpoint cannot
  be used to enumerate registered DEDAN IDs. The unknown-account path still runs
  a real KDF derivation against a dummy verifier rather than returning early.
* Repeated failures lock the account for a cooldown window, which bounds online
  guessing without needing a shared rate-limit store.
* The password never reaches the audit trail; `_record_event` payloads here carry
  outcome booleans, never the credential.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import select

from dedan_platform import identity
from dedan_platform.db import session_scope
from dedan_platform.models import Credential, User, utcnow
from realtime.auth import AuthError, issue_token

logger = logging.getLogger(__name__)

#: PBKDF2 work factor. High enough to be expensive to brute-force offline, low
#: enough that a login stays interactive on modest hardware.
DEFAULT_ITERATIONS = int(os.getenv("PASSWORD_ITERATIONS", "200000"))

#: Digest length in bytes; the base64 encoding below therefore yields 43 chars,
#: comfortably inside the 128-char column.
DK_LEN = 32
SALT_BYTES = 16

#: Cooldown applied after `MAX_FAILED_ATTEMPTS` consecutive failures.
LOCKOUT_ATTEMPTS = int(os.getenv("PASSWORD_LOCKOUT_ATTEMPTS", "8"))
LOCKOUT_MINUTES = int(os.getenv("PASSWORD_LOCKOUT_MINUTES", "15"))

#: Session lifetime. Longer than the realtime token because a portal session must
#: survive a consultation break; the token is still short enough to bound the
#: damage from a stolen browser.
SESSION_TTL_SECONDS = int(os.getenv("PORTAL_TOKEN_TTL", str(12 * 3600)))

#: One uniform message for every credential failure.
INVALID_CREDENTIALS = "Incorrect DEDAN ID or password."

#: Minimum length. Length is the single strongest predictor of password strength,
#: so it is enforced here rather than relying on composition rules that push
#: users toward predictable substitutions. 10 matches the portal's own copy, so
#: the user is never told a password is acceptable and then rejected.
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 200

#: Compared against a throwaway verifier so that "no such account" costs the same
#: as "wrong password". Without this, response timing alone reveals which DEDAN
#: IDs are registered.
_DUMMY_SALT = "0" * 32
_DUMMY_HASH = hashlib.pbkdf2_hmac(
    "sha256", b"dedan-timing-equaliser", _DUMMY_SALT.encode("ascii"), DEFAULT_ITERATIONS, DK_LEN
).hex()

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")


class CredentialError(RuntimeError):
    """Base class for credential failures surfaced to the API layer."""


class PasswordPolicyError(CredentialError):
    """The supplied password does not meet the policy."""


class AccountLockedError(CredentialError):
    """Too many consecutive failures; the account is in its cooldown window."""


class DuplicateAccountError(CredentialError):
    """A credential already exists for that account."""


# --- hashing -----------------------------------------------------------------


def hash_password(password: str, *, salt: Optional[str] = None, iterations: Optional[int] = None) -> Tuple[str, str, int]:
    """Derive `(hash, salt, iterations)` for a password.

    The salt comes from `secrets`, so two users with the same password get
    different digests and one rainbow table cannot cover the whole user base.
    """
    if salt is None:
        salt = secrets.token_hex(SALT_BYTES)
    rounds = int(iterations or DEFAULT_ITERATIONS)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("ascii"), rounds, DK_LEN
    )
    return digest.hex(), salt, rounds


def verify_password(password: str, password_hash: str, salt: str, iterations: int) -> bool:
    """Constant-time password check."""
    candidate, _, _ = hash_password(password, salt=salt, iterations=iterations)
    return hmac.compare_digest(candidate, password_hash)


def _burn_equivalent_time() -> None:
    """Perform a KDF derivation nobody asked for.

    Called on the "account not found" path so a missing account and a wrong
    password take the same time. Skipping it would turn response latency into a
    DEDAN-ID oracle.
    """
    hashlib.pbkdf2_hmac("sha256", b"dedan-timing-equaliser", _DUMMY_SALT.encode("ascii"), DEFAULT_ITERATIONS, DK_LEN)


# --- policy ------------------------------------------------------------------


def validate_password(password: str, password_confirmation: Optional[str] = None) -> None:
    """Enforce the password policy, raising `PasswordPolicyError` on failure."""
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError("Password is too long.")
    if password_confirmation is not None and password != password_confirmation:
        raise PasswordPolicyError("Passwords do not match.")
    if password.lower() == password or password.upper() == password:
        # Not a composition rule for its own sake -- an all-lowercase random
        # string is still strong -- but an all-one-case password is overwhelmingly
        # a predictable one, so it is worth rejecting.
        raise PasswordPolicyError("Password must mix upper and lower case letters.")


def validate_email(email: str) -> str:
    value = (email or "").strip().lower()
    if not EMAIL_RE.match(value) or len(value) > 254:
        raise PasswordPolicyError("Enter a valid email address.")
    return value


# --- persistence -------------------------------------------------------------


def set_credential(internal_user_id: str, password: str) -> None:
    """Create or replace the verifier for an account."""
    password_hash, salt, iterations = hash_password(password)
    with session_scope() as session:
        user = session.scalar(select(User).where(User.id == internal_user_id))
        if user is None:
            raise identity.UserNotFound("Account not found.")
        existing = session.scalar(
            select(Credential).where(Credential.user_id == internal_user_id)
        )
        if existing is not None:
            existing.password_hash = password_hash
            existing.password_salt = salt
            existing.iterations = iterations
            existing.failed_attempts = 0
            existing.locked_until = None
        else:
            user.credential = Credential(
                password_hash=password_hash,
                password_salt=salt,
                iterations=iterations,
            )
        session.flush()


def has_credential(identifier: str) -> bool:
    """Whether an account exists *and* has a usable password set.

    Accepts a DEDAN ID or an email address, matching what the sign-in field
    offers the patient.
    """
    user = identity.resolve_user(identifier)
    if user is None or not user.is_active or user.credential is None:
        return False
    return True


def _record_failure(user_id: str) -> Optional[datetime]:
    """Count one failed attempt and apply the lockout. Returns `locked_until`.

    This runs in its own committed transaction and never raises, because
    `session_scope` rolls back on any exception. Recording the failure and then
    raising inside the same scope therefore discarded the counter, so the
    lockout never engaged and unlimited online guessing was possible against a
    six-digit public id. Bookkeeping must be committed *before* the error
    propagates.
    """
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        credential = session.scalar(
            select(Credential).where(Credential.user_id == user_id)
        )
        if credential is None:
            return None
        credential.failed_attempts = int(credential.failed_attempts or 0) + 1
        locked_until = None
        if credential.failed_attempts >= LOCKOUT_ATTEMPTS:
            locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
            credential.locked_until = locked_until
            credential.failed_attempts = 0
            logger.warning("credential_lockout user_id=%s", user_id)
        session.flush()
        return locked_until


def authenticate(identifier: str, password: str) -> Dict[str, Any]:
    """Verify a password and return the signed session token.

    `identifier` may be a DEDAN ID or an email address. Raises
    `CredentialError` subclasses carrying a uniform message, so the caller
    cannot distinguish "no such account" from "wrong password".
    """
    user = identity.resolve_user(identifier)

    if user is None or user.credential is None:
        # Equalise timing before returning, so an unknown identifier is not
        # detectable by how quickly the request comes back.
        _burn_equivalent_time()
        raise CredentialError(INVALID_CREDENTIALS)

    if not user.is_active:
        _burn_equivalent_time()
        raise CredentialError("This account has been deactivated.")

    with session_scope() as session:
        credential = session.scalar(
            select(Credential).where(Credential.user_id == user.id)
        )
        if credential is None:
            _burn_equivalent_time()
            raise CredentialError(INVALID_CREDENTIALS)

        now = datetime.now(timezone.utc)
        if credential.locked_until is not None:
            locked_until = credential.locked_until
            if locked_until.tzinfo is None:
                locked_until = locked_until.replace(tzinfo=timezone.utc)
            if locked_until > now:
                remaining = int((locked_until - now).total_seconds() // 60) + 1
                raise AccountLockedError(
                    f"Too many failed attempts. Try again in {remaining} minute(s)."
                )
            # Cooldown elapsed: give the account another chance.
            credential.locked_until = None
            credential.failed_attempts = 0

        matched = verify_password(
            password, credential.password_hash, credential.password_salt, credential.iterations
        )

        if matched:
            credential.failed_attempts = 0
            credential.locked_until = None
            credential.last_login_at = now

            # Re-hash opportunistically when the stored work factor is behind the
            # configured one, so raising PASSWORD_ITERATIONS does not strand old
            # accounts on a weaker digest.
            if int(credential.iterations or 0) < DEFAULT_ITERATIONS:
                new_hash, new_salt, iterations = hash_password(password)
                credential.password_hash = new_hash
                credential.password_salt = new_salt
                credential.iterations = iterations
                logger.info("credential_rehash user_id=%s", user.id)

            subject = user.dedan_user_id
            internal_user_id = user.id

    if not matched:
        _record_failure(user.id)
        # Identical to the unknown-account message, so the endpoint cannot be
        # used to discover which DEDAN IDs exist.
        raise CredentialError(INVALID_CREDENTIALS)

    token = issue_token(subject, expires_in=SESSION_TTL_SECONDS, scope="portal")
    logger.info("credential_login user_id=%s", internal_user_id)
    return {
        "access_token": token,
        "token_type": "DEDAN",
        "expires_in": SESSION_TTL_SECONDS,
        "dedan_user_id": subject,
    }


def change_password(internal_user_id: str, current_password: str, new_password: str, confirmation: Optional[str] = None) -> None:
    """Change a password, requiring the current one.

    Re-authenticating before a change is what stops a hijacked session from
    quietly taking over the account permanently.
    """
    with session_scope() as session:
        user = session.scalar(select(User).where(User.id == internal_user_id))
        if user is None or user.credential is None:
            raise CredentialError("No password is set for this account.")
        if not verify_password(current_password, user.credential.password_hash, user.credential.password_salt, user.credential.iterations):
            raise CredentialError("Current password is incorrect.")
    validate_password(new_password, confirmation)
    set_credential(internal_user_id, new_password)
