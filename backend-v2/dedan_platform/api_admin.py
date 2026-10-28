"""The Endod super admin's API: ``/internal/admin/...`` on internal-api.

Only the super admin's own API calls it (over endod-bus, as
``endod-platform-api``), with ``X-Superadmin-Key`` (``SUPERADMIN_API_KEY``, compared
in constant time). The key is its own: refused while unset, shorter than 32
characters, or equal to PLATFORM_ADMIN_KEY, PHARMACY_API_KEY or one of the
platform's own secrets (ADMIN_API_KEY, which signs sessions, among them), so
neither the hospital service nor the pharmacy site can call these routes.

What it returns is account data only (name, Endod ID, phone, email, dates,
status, a count of linked hospitals) and counts. It never reads a health
table's row, never decrypts anything and never returns health data: the
queries below select plain columns of ``users``, ``profiles`` and
``credentials`` and count rows elsewhere.

* ``GET  /internal/admin/stats``: accounts, bookings and open prescriptions.
* ``GET  /internal/admin/users?query=``: search by name, phone, email or Endod ID.
* ``GET  /internal/admin/users/{dedan_id}``: one account.
* ``POST /internal/admin/users/{dedan_id}/suspend``: ``{"reason", "actor_email"}``;
  signs the patient out everywhere and refuses sign-in until reactivated.
* ``POST /internal/admin/users/{dedan_id}/reactivate``: ``{"reason", "actor_email"}``.
* ``GET  /internal/admin/cards/{dedan_id}?s=``: whether the card is valid.
* ``GET  /internal/admin/health``: database, Redis, the events worker, the
  dead-letter count and the outbox backlog (no secrets).
"""

from __future__ import annotations

import hmac
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select, text

from dedan_platform import cards, identity
from dedan_platform import partner_config as config
from dedan_platform.db import ensure_aware, session_scope
from dedan_platform.models import (
    Appointment, Credential, HospitalLink, HospitalRecord, OutboxEvent, Prescription, Profile, User,
    UserEvent, utcnow,
)

logger = logging.getLogger("dedan.admin")

#: The hospitals' and patients' time: "today" and "this week" are Addis Ababa's.
ADDIS = ZoneInfo("Africa/Addis_Ababa")
MIN_KEY_LENGTH = 32
SEARCH_LIMIT = 50
DEDAN_ID = r"^[Dd][Ee][0-9]{6}$"

#: A booking that counts: paid and with the hospital, or done. Not one still
#: waiting for payment, whose hold expired, or that was refused or cancelled.
COUNTED_BOOKING_STATES = ("awaiting_hospital", "awaiting_doctor", "confirmed", "completed")

#: The only fields an account answer ever has (tests assert nothing else appears).
ACCOUNT_FIELDS = (
    "dedan_id", "name", "phone", "email", "created_at", "last_sign_in_at", "status",
    "linked_hospitals", "suspended_at", "suspended_reason", "suspended_by",
)


def _key_usable(key: Optional[str]) -> bool:
    if not key or len(key) < MIN_KEY_LENGTH:
        return False
    # Its own key: never one the hospital service or the pharmacy site holds,
    # nor one of the platform's own secrets (ADMIN_API_KEY signs sessions).
    for other in _other_secrets():
        if other and hmac.compare_digest(other.encode(), key.encode()):
            return False
    return True


def _other_secrets():
    import os

    yield config.platform_admin_key()
    yield config.pharmacy_api_key()
    yield config.rx_signing_key()
    for name in ("ADMIN_API_KEY", "REALTIME_TOKEN_SECRET", "SESSION_SECRET", "CARD_SIGNING_SECRET"):
        yield (os.getenv(name) or "").strip()


def require_admin_key(x_superadmin_key: Optional[str] = Header(default=None)) -> None:
    """Constant-time check of ``X-Superadmin-Key``; refused outright when no usable key is set."""
    expected = config.superadmin_api_key()
    if not _key_usable(expected):
        raise HTTPException(status_code=503, detail="Not available.")
    if not x_superadmin_key or not hmac.compare_digest(x_superadmin_key.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Not authorised.")


router = APIRouter(prefix="/internal/admin", tags=["admin"], include_in_schema=False,
                   dependencies=[Depends(require_admin_key)])


# --- helpers -----------------------------------------------------------------------------

def _iso(value: Optional[datetime]) -> Optional[str]:
    return ensure_aware(value).isoformat() if value is not None else None


def _status(is_active: bool, suspended_at: Optional[datetime]) -> str:
    if not is_active:
        return "deactivated"
    return "suspended" if suspended_at is not None else "active"


def _name(display: Optional[str], first: Optional[str], middle: Optional[str], last: Optional[str]) -> Optional[str]:
    parts = [p.strip() for p in (first, middle, last) if p and p.strip()]
    return " ".join(parts) or (display.strip() if display and display.strip() else None)


#: Plain account columns only: no relationship is loaded, so nothing else is read.
_ACCOUNT_COLUMNS = (
    User.id, User.dedan_user_id, User.created_at, User.is_active, User.suspended_at, User.suspended_reason,
    User.suspended_by, Profile.display_name, Profile.first_name, Profile.middle_name, Profile.last_name,
    Profile.phone, Profile.email, Credential.last_login_at,
)


def _account_query():
    return (select(*_ACCOUNT_COLUMNS)
            .select_from(User)
            .outerjoin(Profile, Profile.user_id == User.id)
            .outerjoin(Credential, Credential.user_id == User.id))


def _account(row, linked: int) -> Dict[str, Any]:
    return {
        "dedan_id": row.dedan_user_id,
        "name": _name(row.display_name, row.first_name, row.middle_name, row.last_name),
        "phone": row.phone,
        "email": row.email,
        "created_at": _iso(row.created_at),
        "last_sign_in_at": _iso(row.last_login_at),
        "status": _status(row.is_active, row.suspended_at),
        "linked_hospitals": linked,
        "suspended_at": _iso(row.suspended_at),
        "suspended_reason": row.suspended_reason,
        "suspended_by": row.suspended_by,
    }


def _linked_counts(session, user_ids: List[str]) -> Dict[str, int]:
    if not user_ids:
        return {}
    rows = session.execute(
        select(HospitalLink.user_id, func.count(func.distinct(HospitalLink.hospital_id)))
        .where(HospitalLink.user_id.in_(user_ids)).group_by(HospitalLink.user_id))
    return {user_id: int(count) for user_id, count in rows}


def _dedan_id(value: str) -> str:
    try:
        return identity.validate_dedan_user_id(value)
    except identity.InvalidDedanId:
        raise HTTPException(status_code=404, detail="Account not found.") from None


def _like(value: str) -> str:
    """A LIKE pattern that matches ``value`` literally anywhere (bound, never spliced into SQL)."""
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


# --- stats --------------------------------------------------------------------------------

@router.get("/stats")
def stats() -> Dict[str, Any]:
    now = utcnow()
    local = now.astimezone(ADDIS)
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = day_start - timedelta(days=day_start.weekday())  # Monday
    day_end, week_end = day_start + timedelta(days=1), week_start + timedelta(days=7)

    def bookings(start: datetime, end: datetime):
        # In UTC: SQLite keeps no offset, so the bounds must be in the stored zone.
        start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
        return (select(func.count()).select_from(Appointment)
                .where(Appointment.hospital_id.is_not(None),
                       Appointment.hospital_state.in_(COUNTED_BOOKING_STATES),
                       Appointment.scheduled_at >= start, Appointment.scheduled_at < end))

    with session_scope() as session:
        total = session.scalar(select(func.count()).select_from(User)) or 0
        new_7d = session.scalar(select(func.count()).select_from(User)
                                .where(User.created_at >= now - timedelta(days=7))) or 0
        suspended = session.scalar(select(func.count()).select_from(User)
                                   .where(User.suspended_at.is_not(None))) or 0
        today = session.scalar(bookings(day_start, day_end)) or 0
        week = session.scalar(bookings(week_start, week_end)) or 0
        # Open as prescriptions.current_status works it out: not completed,
        # withdrawn, retracted or expired. Counted only: no row is loaded.
        open_rx = session.scalar(
            select(func.count()).select_from(Prescription)
            .join(HospitalRecord, HospitalRecord.id == Prescription.record_id)
            .where(Prescription.status == "open", Prescription.withdrawn_at.is_(None),
                   Prescription.expires_at > now, HospitalRecord.retracted_at.is_(None))) or 0
    return {
        "users_total": int(total),
        "users_new_7d": int(new_7d),
        "users_suspended": int(suspended),
        "bookings_today": int(today),
        "bookings_week": int(week),
        "open_prescriptions": int(open_rx),
        "timezone": "Africa/Addis_Ababa",
        "generated_at": now.isoformat(),
    }


# --- accounts -----------------------------------------------------------------------------

@router.get("/users")
def search_users(query: str = Query(default="", max_length=100)) -> Dict[str, Any]:
    """Newest first; with a query, accounts whose name, phone, email or Endod ID contains it."""
    value = query.strip()
    statement = _account_query()
    if value:
        pattern = _like(value)
        conditions = [
            User.dedan_user_id.ilike(pattern, escape="\\"),
            Profile.email.ilike(pattern, escape="\\"),
            Profile.phone.ilike(pattern, escape="\\"),
            Profile.display_name.ilike(pattern, escape="\\"),
            Profile.first_name.ilike(pattern, escape="\\"),
            Profile.last_name.ilike(pattern, escape="\\"),
            (func.coalesce(Profile.first_name, "") + " " + func.coalesce(Profile.last_name, ""))
            .ilike(pattern, escape="\\"),
        ]
        # "0911 234 567" finds "+251911234567".
        from dedan_platform.phone import normalise_ethiopian_mobile

        phone = normalise_ethiopian_mobile(value)
        if phone:
            conditions.append(Profile.phone == phone)
        statement = statement.where(or_(*conditions))
    statement = statement.order_by(User.created_at.desc(), User.id).limit(SEARCH_LIMIT)
    with session_scope() as session:
        rows = list(session.execute(statement))
        linked = _linked_counts(session, [row.id for row in rows])
    return {"items": [_account(row, linked.get(row.id, 0)) for row in rows], "limit": SEARCH_LIMIT}


def _read(session, dedan_id: str) -> Dict[str, Any]:
    row = session.execute(_account_query().where(User.dedan_user_id == dedan_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Account not found.")
    return _account(row, _linked_counts(session, [row.id]).get(row.id, 0))


@router.get("/users/{dedan_id}")
def read_user(dedan_id: str = Path(pattern=DEDAN_ID)) -> Dict[str, Any]:
    with session_scope() as session:
        return _read(session, _dedan_id(dedan_id))


class AccountAction(BaseModel):
    #: Why (kept on the account and in its audit trail).
    reason: str = Field(min_length=3, max_length=500)
    #: The admin who did it, as the super admin signed them in.
    actor_email: str = Field(min_length=3, max_length=254)

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("give a reason")
        return value

    @field_validator("actor_email")
    @classmethod
    def _actor(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("must be an email address")
        return value


def _locked_user(session, dedan_id: str) -> User:
    user = session.scalar(select(User).where(User.dedan_user_id == dedan_id).with_for_update())
    if user is None:
        raise HTTPException(status_code=404, detail="Account not found.")
    if not user.is_active:
        raise HTTPException(status_code=409, detail="This account is closed.")
    return user


def _audit(session, user: User, event_type: str, body: AccountAction) -> None:
    session.add(UserEvent(user_id=user.id, event_type=event_type,
                          payload=json.dumps({"by": body.actor_email, "reason": body.reason,
                                              "via": "endod-admin"}, ensure_ascii=False)))


@router.post("/users/{dedan_id}/suspend")
def suspend_user(body: AccountAction, dedan_id: str = Path(pattern=DEDAN_ID)) -> Dict[str, Any]:
    """Suspend the account: every session ends now and sign-in is refused until reactivated."""
    dedan_id = _dedan_id(dedan_id)
    with session_scope() as session:
        user = _locked_user(session, dedan_id)
        if user.suspended_at is not None:
            raise HTTPException(status_code=409, detail="This account is already suspended.")
        now = utcnow()
        user.suspended_at = now
        user.suspended_reason = body.reason
        user.suspended_by = body.actor_email
        # Signs the patient out: every token issued until now is refused
        # (credentials.tokens_valid_from), whatever happens to the suspension.
        user.sessions_revoked_at = now
        _audit(session, user, "account_suspended", body)
        session.flush()
        logger.info("admin_account_suspended user_id=%s by=%s", user.id, body.actor_email)
        return _read(session, dedan_id)


@router.post("/users/{dedan_id}/reactivate")
def reactivate_user(body: AccountAction, dedan_id: str = Path(pattern=DEDAN_ID)) -> Dict[str, Any]:
    """Lift the suspension: the patient can sign in again (old sessions stay ended)."""
    dedan_id = _dedan_id(dedan_id)
    with session_scope() as session:
        user = _locked_user(session, dedan_id)
        if user.suspended_at is None:
            raise HTTPException(status_code=409, detail="This account is not suspended.")
        user.suspended_at = None
        user.suspended_reason = None
        user.suspended_by = None
        _audit(session, user, "account_reactivated", body)
        session.flush()
        logger.info("admin_account_reactivated user_id=%s by=%s", user.id, body.actor_email)
        return _read(session, dedan_id)


# --- digital cards ------------------------------------------------------------------------

@router.get("/cards/{dedan_id}")
def read_card(dedan_id: str = Path(pattern=DEDAN_ID),
              s: str = Query(default="", max_length=64)) -> Dict[str, Any]:
    """Whether the card for this Endod ID is valid: with ``s`` (the signature in
    the card's QR link), that the signature is Endod's (cards.py); and that the
    account is open and not suspended. No health data, no name."""
    dedan_id = _dedan_id(dedan_id)
    with session_scope() as session:
        row = session.execute(select(User.created_at, User.is_active, User.suspended_at)
                              .where(User.dedan_user_id == dedan_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="No account has this Endod ID.")
    status = _status(row.is_active, row.suspended_at)
    signature_valid: Optional[bool] = None
    signing_available = True
    try:
        expected = cards.card_signature(dedan_id)
    except cards.CardError:
        signing_available = False
        expected = None
    if s:
        signature_valid = bool(expected) and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", s)) and \
            hmac.compare_digest(expected.encode("ascii"), s.encode("ascii", "replace"))
    account_ok = status == "active"
    return {
        "dedan_id": dedan_id,
        "issued_at": _iso(row.created_at),
        "account_status": status,
        "signing_available": signing_available,
        "signature_checked": bool(s),
        "signature_valid": signature_valid,
        "valid": account_ok and signing_available and signature_valid is not False,
    }


# --- health -------------------------------------------------------------------------------

def _redis_checks() -> Dict[str, Any]:
    from dedan_platform import eventbus

    result: Dict[str, Any] = {"redis": {"configured": False, "ok": None}, "dead_letters": None,
                              "events_worker": {"last_heartbeat": None, "ok": None}}
    try:
        client = eventbus.connect()
    except Exception as exc:  # noqa: BLE001 -- reported, never raised
        logger.warning("admin_health_redis_connect_failed %s", type(exc).__name__)
        result["redis"] = {"configured": True, "ok": False}
        return result
    if client is None:
        return result
    result["redis"]["configured"] = True
    try:
        client.ping()
        result["redis"]["ok"] = True
        result["dead_letters"] = int(client.xlen(eventbus.DEAD_LETTER))
        beat = client.get(eventbus.HEARTBEAT_KEY)
        if beat:
            when = ensure_aware(datetime.fromisoformat(beat))
            result["events_worker"] = {"last_heartbeat": when.isoformat(),
                                       "ok": utcnow() - when < timedelta(minutes=2)}
        else:
            result["events_worker"] = {"last_heartbeat": None, "ok": False}
    except Exception as exc:  # noqa: BLE001
        logger.warning("admin_health_redis_failed %s", type(exc).__name__)
        result["redis"]["ok"] = False
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass
    return result


@router.get("/health")
def health() -> Dict[str, Any]:
    checked = utcnow()
    database_ok = False
    outbox: Dict[str, Any] = {"backlog": None, "oldest_at": None}
    try:
        with session_scope() as session:
            session.execute(text("SELECT 1"))
            database_ok = True
            outbox["backlog"] = int(session.scalar(
                select(func.count()).select_from(OutboxEvent).where(OutboxEvent.published_at.is_(None))) or 0)
            outbox["oldest_at"] = _iso(session.scalar(
                select(func.min(OutboxEvent.created_at)).where(OutboxEvent.published_at.is_(None))))
    except Exception as exc:  # noqa: BLE001 -- reported, never raised
        logger.warning("admin_health_database_failed %s", type(exc).__name__)
    checks = _redis_checks()
    ok = database_ok and checks["redis"]["ok"] is not False and checks["events_worker"]["ok"] is not False
    return {
        "status": "ok" if ok else "degraded",
        "checked_at": checked.isoformat(),
        "database": {"ok": database_ok},
        **checks,
        "outbox": outbox,
    }

