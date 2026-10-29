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
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Dict, Optional, Tuple

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
#: Failures from one client against one sign-in identifier before that pair is
#: throttled. Keyed per client so knowing a patient's DEDAN ID does not let
#: anyone lock the patient out, and applied identically to identifiers that do
#: not exist so the response cannot reveal which accounts are real.
LOCKOUT_ATTEMPTS = int(os.getenv("PASSWORD_LOCKOUT_ATTEMPTS", "8"))
LOCKOUT_MINUTES = int(os.getenv("PASSWORD_LOCKOUT_MINUTES", "15"))
#: Account-wide ceiling across all clients in the same rolling window, against
#: guessing spread over many addresses. Much higher than the per-client limit.
ACCOUNT_LOCKOUT_ATTEMPTS = int(os.getenv("PASSWORD_ACCOUNT_LOCKOUT_ATTEMPTS", "50"))

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


class AccountSuspendedError(CredentialError):
    """An Endod admin suspended the account: no sign-in until it is reactivated."""


#: What a suspended patient is told (only after the correct password).
SUSPENDED_MESSAGE = "This account is suspended. Please contact Endod support."


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
    changed_at = utcnow()
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
            existing.password_changed_at = changed_at
        else:
            user.credential = Credential(
                password_hash=password_hash,
                password_salt=salt,
                iterations=iterations,
                password_changed_at=changed_at,
            )
        session.flush()


def tokens_valid_from(internal_user_id: str) -> Optional[int]:
    """Earliest token ``iat`` (unix seconds) still accepted for this account.

    Tokens issued before the last password change are rejected. Compared at
    whole-second precision because ``iat`` is whole seconds: a token minted in
    the same second as the change (e.g. the one returned by the change itself)
    stays valid.

    Tokens issued before an admin signed the account out
    (``User.sessions_revoked_at``) are rejected too, including those minted
    in that same second: nothing is handed out with a revocation.
    """
    with session_scope() as session:
        changed_at = session.scalar(
            select(Credential.password_changed_at).where(
                Credential.user_id == internal_user_id
            )
        )
        revoked_at = session.scalar(
            select(User.sessions_revoked_at).where(User.id == internal_user_id)
        )
    cutoffs = []
    if changed_at is not None:
        cutoffs.append(int(_aware(changed_at).timestamp()))
    if revoked_at is not None:
        cutoffs.append(int(_aware(revoked_at).timestamp()) + 1)
    return max(cutoffs) if cutoffs else None


def _aware(value: datetime) -> datetime:
    # SQLite returns naive datetimes; they were stored as UTC.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def has_credential(identifier: str) -> bool:
    """Whether an account exists *and* has a usable password set.

    Accepts a DEDAN ID or an email address, matching what the sign-in field
    offers the patient.
    """
    user = identity.resolve_user(identifier)
    if user is None or not user.is_active or user.credential is None:
        return False
    return True


class _LoginThrottle:
    """Failed sign-ins per key, in a sliding ``LOCKOUT_MINUTES`` window.

    Keys are built by `_throttle_keys`. In-process: a restart clears it and
    replicas do not share it.
    """

    def __init__(self) -> None:
        self._failures: Dict[Tuple[str, str], Deque[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: Tuple[str, str], now: float) -> Deque[float]:
        window_start = now - LOCKOUT_MINUTES * 60
        hits = self._failures.get(key)
        if hits is None:
            return deque()
        while hits and hits[0] <= window_start:
            hits.popleft()
        if not hits:
            self._failures.pop(key, None)
        return hits

    def remaining_minutes(self, key: Tuple[str, str], limit: int) -> Optional[int]:
        now = time.time()
        with self._lock:
            hits = self._recent(key, now)
            if len(hits) < limit:
                return None
            return int((hits[0] + LOCKOUT_MINUTES * 60 - now) // 60) + 1

    def fail(self, key: Tuple[str, str]) -> None:
        now = time.time()
        with self._lock:
            hits = self._recent(key, now)
            hits.append(now)
            self._failures[key] = hits
            if len(self._failures) > 50_000:
                # Bounded: drop the oldest entries rather than grow forever.
                for stale in list(self._failures)[:5_000]:
                    self._failures.pop(stale, None)

    def clear(self, key: Tuple[str, str]) -> None:
        with self._lock:
            self._failures.pop(key, None)


_throttle = _LoginThrottle()


def _throttle_keys(identifier: str, user: Optional[User], client: str) -> Dict[Tuple[str, str], int]:
    """Throttle buckets for one attempt, mapped to their limits.

    A known account is keyed by the account, not the name typed, so its DEDAN
    ID and email share one budget. An unknown name gets its own bucket with
    the same limit, so throttling looks identical for real and unknown
    accounts. The account-wide bucket (all clients) is a rolling window, so
    one slow client can never accumulate a permanent lockout.
    """
    client = client or "unknown"
    if user is None:
        return {(f"name:{(identifier or '').strip().lower()}", client): LOCKOUT_ATTEMPTS}
    return {
        (f"account:{user.id}", client): LOCKOUT_ATTEMPTS,
        (f"account:{user.id}", "*"): ACCOUNT_LOCKOUT_ATTEMPTS,
    }


def _locked_error(minutes: int) -> AccountLockedError:
    return AccountLockedError(f"Too many failed attempts. Try again in {minutes} minute(s).")


def _record_failure(user_id: str) -> None:
    """Count one failed attempt on the account, for audit.

    Runs in its own committed transaction: `session_scope` rolls back on any
    exception, so recording inside the scope that raises would discard it.
    """
    with session_scope() as session:
        credential = session.scalar(
            select(Credential).where(Credential.user_id == user_id)
        )
        if credential is None:
            return
        # Counted for audit only. Locking is done by the rolling-window
        # throttle: a counter with no window let one slow client lock a patient
        # out permanently.
        credential.failed_attempts = int(credential.failed_attempts or 0) + 1
        session.flush()


def authenticate(identifier: str, password: str, client: str = "unknown") -> Dict[str, Any]:
    """Verify a password and return the signed session token.

    `identifier` may be a DEDAN ID or an email address; `client` identifies the
    caller (its address) for throttling. Raises `CredentialError` subclasses
    carrying a uniform message, so the caller cannot distinguish "no such
    account" from "wrong password" -- including once throttled.
    """
    user = identity.resolve_user(identifier)
    if user is not None and user.credential is None:
        user = None
    buckets = _throttle_keys(identifier, user, client)
    for key, limit in buckets.items():
        remaining = _throttle.remaining_minutes(key, limit)
        if remaining is not None:
            raise _locked_error(remaining)

    if user is None:
        # Equalise timing before returning, so an unknown identifier is not
        # detectable by how quickly the request comes back, and count the
        # failure exactly as for a real account.
        _burn_equivalent_time()
        for key in buckets:
            _throttle.fail(key)
        raise CredentialError(INVALID_CREDENTIALS)

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
                raise _locked_error(int((locked_until - now).total_seconds() // 60) + 1)
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
        for key in buckets:
            _throttle.fail(key)
        _record_failure(user.id)
        # Identical to the unknown-account message, so the endpoint cannot be
        # used to discover which DEDAN IDs exist.
        raise CredentialError(INVALID_CREDENTIALS)

    # Success clears this client's bucket; the account-wide window is left to
    # expire so a sign-in cannot reset an ongoing distributed attack.
    _throttle.clear(next(iter(buckets)))
    if not user.is_active:
        # Only after the correct password: said earlier, this message revealed
        # that the account exists to anyone who typed its id.
        raise CredentialError("This account has been deactivated.")
    if user.suspended_at is not None:
        # Likewise only after the correct password.
        logger.info("credential_login_refused_suspended user_id=%s", internal_user_id)
        raise AccountSuspendedError(SUSPENDED_MESSAGE)

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
