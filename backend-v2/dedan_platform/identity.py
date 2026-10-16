"""
Stage 1: identity and profile services.

Owns account creation, the DEDAN ID, and the read/update surface for each
profile domain.

DEDAN ID uniqueness
-------------------
Six digits from a cryptographic source leaves ~10^6 values, so collisions are a
matter of *when*, not *if*. Naive retry loops also fail under concurrency:
two signups that pick the same number both succeed at the SELECT and one fails
at the INSERT. So the insert is retried on an IntegrityError specific to this
row, which is correct whether the collision came from a race or from history.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from dedan_platform.db import new_uuid, session_scope
from dedan_platform.phone import normalise_ethiopian_mobile
from dedan_platform.models import (
    Consent, HealthProfile, Preferences, Profile, User, UserEvent,
    generate_dedan_user_id, utcnow,
)
from realtime.voices import SUPPORTED_LANGUAGES, VoiceUnavailableError, get_voice

logger = logging.getLogger(__name__)

# Public ID shape, used for validation on input as well as generation.
DEDAN_ID_RE = re.compile(r"^DE\d{6}$")

# Bounded retry for the (astronomically unlikely) case that every candidate ID in
# a run collides. Without a cap a pathological table could spin forever.
_ID_ALLOCATION_ATTEMPTS = 12


class IdentityError(RuntimeError):
    """Base class for identity/profile failures."""


class InvalidDedanId(IdentityError):
    """A supplied DEDAN ID does not match the documented format."""


class EmailInUse(IdentityError):
    """Another account already uses this email address."""


class PhoneInUse(IdentityError):
    """Another account already signs in with this verified phone."""


class UserNotFound(IdentityError):
    """No account for the supplied identifier."""


def validate_dedan_user_id(value: str) -> str:
    """Validate and normalise a human-readable DEDAN ID.

    Accepts a lowercase prefix so a user typing `de482731` is not rejected for a
    cosmetic reason; everything else is refused rather than "corrected", because
    guessing at an identifier is how the wrong patient's record gets opened.
    """
    if not value or not DEDAN_ID_RE.match(value.strip().upper()):
        raise InvalidDedanId("DEDAN ID must look like DE123456.")
    return value.strip().upper()


def _record_event(
    session: Session,
    user_id: str,
    event_type: str,
    correlation_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    """Append an audit row. Never allowed to break the operation it records."""
    try:
        session.add(UserEvent(
            user_id=user_id,
            event_type=event_type,
            correlation_id=correlation_id,
            payload=json.dumps(payload) if payload else None,
        ))
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("audit_write_failed: %s", type(exc).__name__)


def create_user(
    display_name: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    locale: str = "en",
    timezone_name: str = "UTC",
    country_code: str = "ET",
    phone_verified: bool = False,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Create an account with its full domain set and a unique DEDAN ID.

    ``phone_verified`` is only for callers that have just proved the patient
    holds ``phone`` (`phone_auth`); a verified phone can be used to sign in.

    Every supporting record is created up front so no later code path has to
    handle a half-provisioned account (a missing `Preferences` row would
    otherwise surface as a 500 the first time someone changes their voice).
    """
    with session_scope() as session:
        if email:
            email = _normalise_email(email)
            if _email_taken(session, email):
                raise EmailInUse("An account with this email address already exists.")
        user = _allocate_user(session)
        user.profile = Profile(
            display_name=display_name, email=email, phone=phone,
            first_name=(first_name or "").strip()[:60] or None,
            last_name=(last_name or "").strip()[:60] or None,
            phone_verified_at=utcnow() if phone and phone_verified else None,
            locale=locale, timezone=timezone_name, country_code=country_code,
        )
        # A patient who signed up by phone has no other channel, so appointment
        # reminders (transactional, not marketing) go by SMS unless they turn
        # them off in settings.
        user.preferences = Preferences(
            language=_language_from_locale(locale),
            sms_notifications=bool(phone and phone_verified)
        )
        user.health_profile = HealthProfile()
        # Consent starts fully withdrawn: nothing is assumed on the user's behalf.
        user.consent = Consent()

        _record_event(session, user.id, "user_created", payload={"locale": locale})
        _flush_checking_email(session)
        return {
            "internal_user_id": user.id,
            "dedan_user_id": user.dedan_user_id,
            "created_at": user.created_at.isoformat(),
        }


def _allocate_user(session: Session) -> User:
    """Insert a user, retrying until a free DEDAN ID is found.

    The retry is driven by the database's uniqueness constraint rather than a
    prior SELECT, which is what makes it safe under concurrent signups.
    """
    last_error: Optional[Exception] = None
    for _ in range(_ID_ALLOCATION_ATTEMPTS):
        candidate = generate_dedan_user_id()
        user = User(id=new_uuid(), dedan_user_id=candidate)
        session.add(user)
        try:
            session.flush()
            return user
        except IntegrityError as exc:
            # Only the ID collision is retried; anything else is a real fault.
            session.rollback()
            if "dedan_user_id" not in str(exc):
                raise
            last_error = exc
    raise IdentityError(
        "Could not allocate a unique DEDAN ID; please retry."
    ) from last_error


# Relationships must be loaded *inside* the session. Returning a `User` from a
# closed session raises DetachedInstanceError on the first attribute access,
# which is exactly what a naive `session.get()` return does.
_USER_LOAD_OPTIONS = (
    selectinload(User.profile),
    selectinload(User.preferences),
    selectinload(User.health_profile),
    selectinload(User.consent),
    # Loaded so the credential verifier is readable after the session closes.
    # `selectinload`, not a lazy `raiseload`, so an account with no password
    # (provisioned by support tooling, say) still loads instead of raising.
    selectinload(User.credential),
)


def _load_user(stmt):
    for option in _USER_LOAD_OPTIONS:
        stmt = stmt.options(option)
    return stmt


def get_user_by_internal_id(internal_user_id: str) -> Optional[User]:
    """Fetch an account with every domain eagerly loaded.

    Callers may safely read `user.profile` after this returns.
    """
    with session_scope() as session:
        return session.scalar(_load_user(select(User).where(User.id == internal_user_id)))


def get_user_by_dedan_id(dedan_user_id: str) -> Optional[User]:
    """Look up by public ID. Used by support tooling, never for authorization."""
    normalised = validate_dedan_user_id(dedan_user_id)
    with session_scope() as session:
        return session.scalar(
            _load_user(select(User).where(User.dedan_user_id == normalised))
        )


def find_user_by_email(email: str) -> Optional[User]:
    """Look up by email address, case-insensitively.

    The portal's sign-in field accepts "DE482731 or user@example.com", so this is
    the second half of that promise. Emails are normalised to lowercase on write
    (`credentials.validate_email`); the comparison is lowered here as well so an
    address stored before normalisation is still reachable.
    """
    value = (email or "").strip().lower()
    if not value:
        return None
    with session_scope() as session:
        matches = session.scalars(
            _load_user(
                select(User)
                .join(User.profile)
                .where(func.lower(Profile.email) == value)
            )
        ).unique().all()
    # Accounts created before emails were unique may share one. Signing in by
    # that email would pick an arbitrary account, so require the DEDAN ID.
    if len(matches) != 1:
        if matches:
            logger.warning("ambiguous_email_login count=%d", len(matches))
        return None
    return matches[0]


def find_user_by_phone(phone_e164: str) -> Optional[User]:
    """The account that signs in with this verified phone, if exactly one does."""
    if not phone_e164:
        return None
    with session_scope() as session:
        matches = session.scalars(
            _load_user(
                select(User)
                .join(User.profile)
                .where(Profile.phone == phone_e164)
                .where(Profile.phone_verified_at.is_not(None))
            )
        ).unique().all()
    if len(matches) != 1:
        if matches:
            logger.warning("ambiguous_phone_login count=%d", len(matches))
        return None
    return matches[0]


def set_verified_phone(internal_user_id: str, phone_e164: str) -> Dict[str, Any]:
    """Record that this account proved it holds ``phone_e164``."""
    with session_scope() as session:
        user = session.scalar(_load_user(select(User).where(User.id == internal_user_id)))
        if user is None:
            raise UserNotFound("Account not found.")
        user.profile.phone = phone_e164
        user.profile.phone_verified_at = utcnow()
        _record_event(session, user.id, "phone_verified")
        _flush_checking_email(session)
        return _profile_payload(user)


def resolve_user(identifier: str) -> Optional[User]:
    """Resolve a sign-in identifier: DEDAN ID, verified phone, or email.

    Tries the public ID first, then the email. Both branches load the full domain
    graph so callers can read `user.profile` and `user.credential` safely once
    the session closes.
    """
    value = (identifier or "").strip()
    if not value:
        return None
    user = None
    if DEDAN_ID_RE.match(value.upper()):
        try:
            user = get_user_by_dedan_id(value)
        except InvalidDedanId:  # pragma: no cover - guarded by the regex above
            user = None
    if user is None:
        phone = normalise_ethiopian_mobile(value)
        if phone:
            return find_user_by_phone(phone)
        user = find_user_by_email(value)
    return user


def _profile_payload(user: User, include_health: bool = False) -> Dict[str, Any]:
    """Serialise one account.

    `include_health` exists so the *shape* of a health payload is opt-in: a
    routine profile read cannot leak a medication list by forgetting to redact.
    """
    profile = user.profile
    prefs = user.preferences
    consent = user.consent
    payload: Dict[str, Any] = {
        "internal_user_id": user.id,
        "dedan_user_id": user.dedan_user_id,
        "created_at": user.created_at.isoformat(),
        "is_active": user.is_active,
        "display_name": getattr(profile, "display_name", None),
        "first_name": getattr(profile, "first_name", None),
        "middle_name": getattr(profile, "middle_name", None),
        "last_name": getattr(profile, "last_name", None),
        "address_line": getattr(profile, "address_line", None),
        "city": getattr(profile, "city", None),
        "region": getattr(profile, "region", None),
        "postal_code": getattr(profile, "postal_code", None),
        "email": getattr(profile, "email", None),
        "phone": getattr(profile, "phone", None),
        "phone_verified": getattr(profile, "phone_verified_at", None) is not None,
        "locale": getattr(profile, "locale", "en"),
        "timezone": getattr(profile, "timezone", "UTC"),
        "country_code": getattr(profile, "country_code", "ET"),
        "preferences": {
            "language": getattr(prefs, "language", "en"),
            "voice_preference": getattr(prefs, "voice_preference", None),
            "voice_gender": getattr(prefs, "voice_gender", None),
            "theme": getattr(prefs, "theme", "system"),
            "email_notifications": getattr(prefs, "email_notifications", True),
            "sms_notifications": getattr(prefs, "sms_notifications", False),
            "push_notifications": getattr(prefs, "push_notifications", True),
            "reminder_offsets": getattr(prefs, "reminder_offsets", "604800,86400,3600"),
            "preferred_contact_window": getattr(prefs, "preferred_contact_window", None),
            "onboarding_goals": _split_list(getattr(prefs, "onboarding_goals", None)),
            "care_search_radius_km": getattr(prefs, "care_search_radius_km", None),
        },
        "consent": {
            "treatment_processing": getattr(consent, "treatment_processing", False),
            "analytics": getattr(consent, "analytics", False),
            "research": getattr(consent, "research", False),
            "marketing": getattr(consent, "marketing", False),
            "data_sharing_with_clinicians": getattr(
                consent, "data_sharing_with_clinicians", False),
            "granted_at": (
                getattr(consent, "granted_at", None).isoformat()
                if getattr(consent, "granted_at", None) else None
            ),
            "revoked_at": (
                getattr(consent, "revoked_at", None).isoformat()
                if getattr(consent, "revoked_at", None) else None
            ),
            "policy_version": getattr(consent, "policy_version", "1.0"),
        },
    }
    if include_health:
        hp = user.health_profile
        dob = getattr(hp, "date_of_birth", None)
        payload["health_profile"] = {
            "sex": getattr(hp, "sex", None),
            "date_of_birth": dob.date().isoformat() if dob else None,
            "age_range": getattr(hp, "age_range", None),
            "age_years": age_years(hp),
            "allergies": _split_list(getattr(hp, "allergies", None)),
            "medications": _split_list(getattr(hp, "medications", None)),
            "conditions": _split_list(getattr(hp, "conditions", None)),
            "blood_type": getattr(hp, "blood_type", None),
            "emergency_contact_name": getattr(hp, "emergency_contact_name", None),
            "emergency_contact_phone": getattr(hp, "emergency_contact_phone", None),
        }
    return payload


def _split_list(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def get_profile_payload(internal_user_id: str) -> Dict[str, Any]:
    user = get_user_by_internal_id(internal_user_id)
    if user is None:
        raise UserNotFound("Account not found.")
    return _profile_payload(user, include_health=False)


def get_health_profile_payload(internal_user_id: str) -> Dict[str, Any]:
    """Health profile.

    Gated by treatment consent by the caller, not here -- this function is the
    data access layer; the API decides whether the caller is entitled to ask.
    """
    user = get_user_by_internal_id(internal_user_id)
    if user is None:
        raise UserNotFound("Account not found.")
    payload = _profile_payload(user, include_health=True)
    return payload.get("health_profile", {})


_PROFILE_FIELDS = {
    "display_name", "email", "phone", "locale", "timezone", "country_code",
    "first_name", "middle_name", "last_name",
    "address_line", "city", "region", "postal_code",
}

#: Optional free-text fields: (max length).
_PROFILE_TEXT_LIMITS = {
    "first_name": 60, "middle_name": 60, "last_name": 60,
    "address_line": 200, "city": 100, "region": 100, "postal_code": 20,
}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")
#: Shared with registration so a number accepted at signup is accepted on
#: edit. 32 is the column size.
_PHONE_RE = re.compile(r"^\+?[0-9 ().-]{6,32}$")


def normalise_phone(value: Any) -> Optional[str]:
    """``None`` for an empty value; otherwise a validated phone string."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str) or not _PHONE_RE.match(value.strip()):
        raise IdentityError("Enter a valid phone number.")
    # Ethiopian mobiles are stored in E.164, the form verification uses, so
    # re-saving "0911 234 567" keeps a verified "+251911234567" verified.
    return normalise_ethiopian_mobile(value) or value.strip()


def _normalise_email(value: Any) -> str:
    email = value.strip().lower() if isinstance(value, str) else ""
    if not _EMAIL_RE.match(email) or len(email) > 254:
        raise IdentityError("Enter a valid email address.")
    return email


def _email_taken(session: Session, email: str, exclude_user_id: Optional[str] = None) -> bool:
    query = select(Profile.user_id).where(func.lower(Profile.email) == email)
    if exclude_user_id:
        query = query.where(Profile.user_id != exclude_user_id)
    return session.scalar(query.limit(1)) is not None


def _flush_checking_email(session: Session) -> None:
    """Flush, turning a lost race on a unique index into `EmailInUse` or
    `PhoneInUse`."""
    try:
        session.flush()
    except IntegrityError as exc:
        # The database's own message only: `str(exc)` also contains the SQL,
        # whose INSERT names both columns, so it cannot tell them apart.
        message = str(getattr(exc, "orig", exc)).lower()
        if "phone" in message:
            raise PhoneInUse("An account already signs in with this phone number.") from exc
        if "email" in message:
            raise EmailInUse("An account with this email address already exists.") from exc
        raise


def _derived_name(profile) -> Optional[str]:
    """First, middle and last name joined, within the display-name column."""
    parts = (profile.first_name, profile.middle_name, profile.last_name)
    return " ".join(p for p in parts if p)[:120].rstrip() or None


def _validate_profile_changes(changes: Dict[str, Any]) -> Dict[str, Any]:
    """Type- and range-check a profile patch.

    The route accepts an arbitrary JSON object, so without this a wrong type
    (`{"email": {}}`) became a 500 and an oversized value was a 500 on
    PostgreSQL. Values are normalised on the way in.
    """
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    clean: Dict[str, Any] = {}
    for field, value in changes.items():
        if field in {"display_name", "email", "phone", *_PROFILE_TEXT_LIMITS} and (
            value is None or (isinstance(value, str) and not value.strip())
        ):
            clean[field] = None
            continue
        if not isinstance(value, str):
            raise IdentityError(f"'{field}' must be text.")
        value = value.strip()
        if field == "display_name":
            if not 1 <= len(value) <= 120:
                raise IdentityError("Display name must be 1-120 characters.")
        elif field == "email":
            value = _normalise_email(value)
        elif field == "phone":
            value = normalise_phone(value)
        elif field == "locale":
            if not re.fullmatch(r"[a-z]{2}(?:-[A-Za-z]{2})?", value):
                raise IdentityError("Locale must look like 'en' or 'am-ET'.")
        elif field == "timezone":
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise IdentityError("Unknown timezone.") from exc
        elif field in _PROFILE_TEXT_LIMITS:
            if len(value) > _PROFILE_TEXT_LIMITS[field]:
                raise IdentityError(f"'{field}' must be at most {_PROFILE_TEXT_LIMITS[field]} characters.")
        elif field == "country_code":
            if not re.fullmatch(r"[A-Za-z]{2}", value):
                raise IdentityError("Country code must be two letters, e.g. 'ET'.")
            value = value.upper()
        clean[field] = value
    return clean


def update_profile(
    internal_user_id: str,
    changes: Dict[str, Any],
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Patch the profile, recording only *which* fields changed."""
    unknown = set(changes) - _PROFILE_FIELDS
    if unknown:
        raise IdentityError(f"Unsupported profile fields: {sorted(unknown)}")
    changes = _validate_profile_changes(changes)
    with session_scope() as session:
        user = session.scalar(
            _load_user(select(User).where(User.id == internal_user_id))
        )
        if user is None:
            raise UserNotFound("Account not found.")
        # Another account's email would make sign-in by email ambiguous and
        # route that account's reminder emails to this one.
        current_email = (user.profile.email or "").lower()
        if (
            changes.get("email")
            and changes["email"] != current_email
            and _email_taken(session, changes["email"], user.id)
        ):
            raise EmailInUse("Another account already uses this email address.")
        # A new number is unproven: typing someone else's number must not
        # let it sign in to this account.
        if "phone" in changes and changes["phone"] != user.profile.phone:
            user.profile.phone_verified_at = None
        derived_before = _derived_name(user.profile)
        for field, value in changes.items():
            setattr(user.profile, field, value)
        # The display name follows the name parts only while it *is* the name
        # parts (or empty): a nickname the patient chose is never overwritten,
        # and clearing the parts clears a derived name instead of leaving it.
        if (
            "display_name" not in changes
            and {"first_name", "middle_name", "last_name"} & set(changes)
            and (user.profile.display_name or None) in (None, derived_before)
        ):
            user.profile.display_name = _derived_name(user.profile)
        _record_event(
            session, user.id, "profile_updated", correlation_id,
            # Field names only: an audit log must not become a second copy of
            # the personal data it exists to protect.
            {"fields": sorted(changes)},
        )
        _flush_checking_email(session)
        return _profile_payload(user)


_PREFERENCE_FIELDS = {
    "language", "voice_preference", "voice_gender", "theme",
    "email_notifications", "sms_notifications", "push_notifications",
    "reminder_offsets", "preferred_contact_window",
    "onboarding_goals", "care_search_radius_km",
}

THEMES = ("system", "light", "dark")
DEFAULT_REMINDER_OFFSETS = "604800,86400,3600"


def _language_from_locale(locale: Optional[str]) -> str:
    """App language from a locale such as "am-ET": its language part, if supported."""
    lang = str(locale or "").replace("_", "-").split("-")[0].strip().lower()
    return lang if lang in SUPPORTED_LANGUAGES else "en"
VOICE_GENDERS = ("female", "male", "neutral")
#: Reminder offsets are seconds before the appointment: at most 5, up to 30 days.
MAX_REMINDER_OFFSETS = 5
MAX_REMINDER_OFFSET_SECONDS = 30 * 86400


def _clean_reminder_offsets(raw: Any) -> str:
    """Positive whole seconds, as a list or comma-separated text, stored as text.

    Empty (None, "", []) means "use the defaults", as it always has.
    """
    if raw is None or raw == [] or (isinstance(raw, str) and not raw.strip()):
        return DEFAULT_REMINDER_OFFSETS
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.split(",") if p.strip()]
    elif isinstance(raw, list):
        parts = raw
    else:
        raise IdentityError("reminder_offsets must be a list of seconds before the appointment.")
    offsets = []
    for part in parts:
        try:
            value = int(part) if not isinstance(part, bool) else None
        except (TypeError, ValueError):
            value = None
        if value is None or not 0 < value <= MAX_REMINDER_OFFSET_SECONDS:
            raise IdentityError("Each reminder offset must be 1 second to 30 days, in seconds.")
        offsets.append(value)
    offsets = sorted(set(offsets), reverse=True)
    if not offsets or len(offsets) > MAX_REMINDER_OFFSETS:
        raise IdentityError(f"Give 1 to {MAX_REMINDER_OFFSETS} reminder offsets.")
    return ",".join(str(o) for o in offsets)


#: What onboarding offers ("What are you looking for?").
ONBOARDING_GOALS = ("symptoms", "hospitals", "appointments", "treatment", "history")


def update_preferences(
    internal_user_id: str,
    changes: Dict[str, Any],
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Patch preferences, validating the voice against the realtime catalog.

    Validating here rather than at read time means an invalid voice id can never
    be persisted, so the live-voice handshake cannot later fail on a value this
    service accepted.
    """
    unknown = set(changes) - _PREFERENCE_FIELDS
    if unknown:
        raise IdentityError(f"Unsupported preference fields: {sorted(unknown)}")

    if "language" in changes and changes["language"] not in SUPPORTED_LANGUAGES:
        raise IdentityError(
            f"Unsupported language '{changes['language']}'. "
            f"Supported: {list(SUPPORTED_LANGUAGES)}"
        )
    if changes.get("voice_preference"):
        try:
            get_voice(changes["voice_preference"])
        except VoiceUnavailableError as exc:
            raise IdentityError(str(exc)) from exc
    if "onboarding_goals" in changes:
        goals = changes["onboarding_goals"] or []
        if isinstance(goals, str):
            goals = [g.strip() for g in goals.split(",") if g.strip()]
        if (
            not isinstance(goals, list)
            or not all(isinstance(g, str) for g in goals)
            or not set(goals) <= set(ONBOARDING_GOALS)
        ):
            raise IdentityError(f"onboarding_goals must be a list of {list(ONBOARDING_GOALS)}.")
        changes = {**changes, "onboarding_goals": ",".join(dict.fromkeys(goals)) or None}
    for field in ("email_notifications", "sms_notifications", "push_notifications"):
        if field in changes and not isinstance(changes[field], bool):
            raise IdentityError(f"{field} must be true or false.")
    if "theme" in changes and changes["theme"] not in THEMES:
        raise IdentityError(f"theme must be one of {list(THEMES)}.")
    if "voice_gender" in changes and changes["voice_gender"] not in (None, *VOICE_GENDERS):
        raise IdentityError(f"voice_gender must be one of {list(VOICE_GENDERS)}.")
    if "preferred_contact_window" in changes:
        window = changes["preferred_contact_window"]
        if window is not None and (not isinstance(window, str) or len(window) > 64):
            raise IdentityError("preferred_contact_window must be text of at most 64 characters.")
    if "reminder_offsets" in changes:
        changes = {**changes, "reminder_offsets": _clean_reminder_offsets(changes["reminder_offsets"])}
    if "care_search_radius_km" in changes:
        radius = changes["care_search_radius_km"]
        if radius is not None and (not isinstance(radius, int) or isinstance(radius, bool) or not 1 <= radius <= 200):
            raise IdentityError("care_search_radius_km must be a whole number from 1 to 200.")

    with session_scope() as session:
        user = session.scalar(
            _load_user(select(User).where(User.id == internal_user_id))
        )
        if user is None:
            raise UserNotFound("Account not found.")
        for field, value in changes.items():
            setattr(user.preferences, field, value)
        _record_event(
            session, user.id, "preferences_updated", correlation_id,
            {"fields": sorted(changes)},
        )
        session.flush()
        return _profile_payload(user)


_HEALTH_FIELDS = {
    "sex", "allergies", "medications", "conditions", "blood_type",
    "emergency_contact_name", "emergency_contact_phone",
    "date_of_birth", "age_range",
}

SEX_VALUES = ("female", "male", "other", "undisclosed")
#: Accepted spellings, normalised to SEX_VALUES (the column holds 16 chars).
_SEX_ALIASES = {"prefer_not_to_say": "undisclosed", "not_stated": "undisclosed"}
#: Onboarding age buckets.
AGE_RANGES = ("0-20", "21-40", "41-60", "61-80", "81+")
#: Other spellings accepted on input (the Next.js onboarding buttons).
_AGE_RANGE_ALIASES = {"1-20": "0-20", "81-100": "81+", "80+": "81+"}
BLOOD_TYPES = ("A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-")


def age_years(health_profile) -> Optional[int]:
    """Age from the date of birth, else the middle of the age range."""
    dob = getattr(health_profile, "date_of_birth", None)
    if dob is not None:
        today = utcnow().date()
        born = dob.date()
        return today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    age_range = getattr(health_profile, "age_range", None)
    if age_range:
        low, _, high = age_range.rstrip("+").partition("-")
        return (int(low) + int(high)) // 2 if high else int(low) + 5
    return None


def _validate_health_changes(changes: Dict[str, Any]) -> Dict[str, Any]:
    """Type- and range-check health fields, which used to be stored as given."""
    from datetime import date

    clean = dict(changes)
    if "sex" in clean and clean["sex"] is not None:
        sex = str(clean["sex"]).strip().lower().replace(" ", "_")
        sex = _SEX_ALIASES.get(sex, sex)
        if sex not in SEX_VALUES:
            raise IdentityError(f"sex must be one of {list(SEX_VALUES)}.")
        clean["sex"] = sex
    if clean.get("age_range") is not None:
        # The onboarding buttons use en dashes ("21–40").
        spelled = str(clean["age_range"]).strip().replace("–", "-").replace("—", "-")
        clean["age_range"] = _AGE_RANGE_ALIASES.get(spelled, spelled)
    if "age_range" in clean and clean["age_range"] is not None and clean["age_range"] not in AGE_RANGES:
        raise IdentityError(f"age_range must be one of {list(AGE_RANGES)}.")
    if "blood_type" in clean and clean["blood_type"] is not None:
        blood = str(clean["blood_type"]).strip().upper()
        if blood not in BLOOD_TYPES:
            raise IdentityError(f"blood_type must be one of {list(BLOOD_TYPES)}.")
        clean["blood_type"] = blood
    if "date_of_birth" in clean and clean["date_of_birth"] is not None:
        raw = str(clean["date_of_birth"]).strip()
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
                raise ValueError(raw)
            born = date.fromisoformat(raw)
        except ValueError as exc:
            raise IdentityError("date_of_birth must be a date like 1990-05-17.") from exc
        today = utcnow().date()
        if born > today or today.year - born.year > 130:
            raise IdentityError("date_of_birth is not a plausible date of birth.")
        clean["date_of_birth"] = datetime(born.year, born.month, born.day, tzinfo=timezone.utc)
    for field, limit in (("emergency_contact_name", 120), ("emergency_contact_phone", 32)):
        if clean.get(field) is not None and len(str(clean[field])) > limit:
            raise IdentityError(f"{field} must be at most {limit} characters.")
    return clean


def update_health_profile(
    internal_user_id: str,
    changes: Dict[str, Any],
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Patch the health profile. Requires treatment consent, enforced by callers."""
    unknown = set(changes) - _HEALTH_FIELDS
    if unknown:
        raise IdentityError(f"Unsupported health fields: {sorted(unknown)}")
    changes = _validate_health_changes(changes)
    with session_scope() as session:
        user = session.scalar(
            _load_user(select(User).where(User.id == internal_user_id))
        )
        if user is None:
            raise UserNotFound("Account not found.")
        for field, value in changes.items():
            # List-valued fields are normalised so the CSV round-trip is stable.
            if field in ("allergies", "medications", "conditions") and isinstance(value, list):
                value = ", ".join(str(v).strip() for v in value if str(v).strip())
            setattr(user.health_profile, field, value)
        # Field names only, never values: these are the most sensitive fields in
        # the system and must not be duplicated into a log table.
        _record_event(
            session, user.id, "health_profile_updated", correlation_id,
            {"fields": sorted(changes)},
        )
        session.flush()
        return _profile_payload(user, include_health=True)["health_profile"]


_CONSENT_FIELDS = {
    "treatment_processing", "analytics", "research", "marketing",
    "data_sharing_with_clinicians",
}


def update_consent(
    internal_user_id: str,
    changes: Dict[str, Any],
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Grant or revoke consent per purpose.

    Purposes are independent on purpose: revoking analytics must not silently
    revoke consent to treatment, which would strand a patient mid-care.
    """
    unknown = set(changes) - _CONSENT_FIELDS
    if unknown:
        raise IdentityError(f"Unsupported consent fields: {sorted(unknown)}")

    with session_scope() as session:
        user = session.scalar(
            _load_user(select(User).where(User.id == internal_user_id))
        )
        if user is None:
            raise UserNotFound("Account not found.")
        consent = user.consent
        for field, value in changes.items():
            # Strictly true/false: bool("false") is True, and consent must
            # never be granted by a string.
            if not isinstance(value, bool):
                raise IdentityError(f"{field} must be true or false.")
            setattr(consent, field, value)

        now = utcnow()
        if any(bool(v) for v in changes.values()):
            consent.granted_at = consent.granted_at or now
        # Revocation is recorded per-user rather than per-purpose because the
        # model keeps independent booleans; the timestamp marks the last change.
        if any(v is False for v in changes.values()):
            consent.revoked_at = now

        _record_event(
            session, user.id, "consent_updated", correlation_id,
            {"fields": sorted(changes)},
        )
        session.flush()
        return _profile_payload(user)["consent"]
