"""
Stage 1 data model: identity, profile, preferences, consent.

Domain separation (spec §19-§22)
--------------------------------
These are deliberately **separate tables**, not one wide `users` table:

    User (identity)   1──1  Profile        personal data
                       1──1  Preferences    experience settings
                       1──1  HealthProfile  health data (separate on purpose)
                       1──1  Consent        legal basis for processing
                       1──*  UserEvent      audit trail

Why this matters beyond tidiness: identity and health data have different
access rules and different retention requirements. Merging them means a routine
profile read can accidentally expose a medication list, and makes it impossible
to delete health data on request while keeping the account.

Identifier model (spec §20)
---------------------------
    internal_user_id  UUID hex  -- primary key, never exposed in a URL
    dedan_user_id     DE######  -- human-readable, immutable, server-generated

The DEDAN ID is generated from a cryptographic random source and checked for
collision inside the insert, so it is unique *by construction* rather than by
hope. It is explicitly NOT the primary key: sequential public ids would let one
patient enumerate another's account by incrementing.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from dedan_platform.db import Base, new_uuid

# Public-ID prefix and length. Fixed so support can recognise an id at a glance
# and so the format check below is unambiguous.
DEDAN_ID_PREFIX = "DE"
DEDAN_ID_DIGITS = 6


def utcnow() -> datetime:
    """Timezone-aware UTC now.

    Naive datetimes are used elsewhere in this repository; using aware datetimes
    here is deliberate so reminders scheduled across a timezone boundary compare
    correctly (a naive local time silently shifts across DST).
    """
    return datetime.now(timezone.utc)


def generate_dedan_user_id() -> str:
    """Generate a candidate human-readable DEDAN ID.

    Uses `secrets`, not `random`: a predictable sequence would let someone
    enumerate other people's IDs from their own.
    """
    return f"{DEDAN_ID_PREFIX}{secrets.randbelow(10 ** DEDAN_ID_DIGITS):0{DEDAN_ID_DIGITS}d}"


class User(Base):
    """Identity record. Contains no health information at all."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    dedan_user_id: Mapped[str] = mapped_column(String(8), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    # Soft delete: health records must be retained for audit even when the
    # account closes, so the row is deactivated rather than dropped.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    credential: Mapped[Optional["Credential"]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    profile: Mapped[Optional["Profile"]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    preferences: Mapped[Optional["Preferences"]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    health_profile: Mapped[Optional["HealthProfile"]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    consent: Mapped[Optional["Consent"]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        # Server-generated uniqueness is enforced by the database, not only by
        # application code: a race between two concurrent signups must not be
        # able to produce duplicate public IDs.
        UniqueConstraint("dedan_user_id", name="uq_users_dedan_user_id"),
    )


class Credential(Base):
    """Password verifier for one account.

    Separate table, and separate again from `Profile`, for the same reason health
    data is: a routine profile read must never be able to return a password
    hash by accident, and support must be able to reset access without touching
    personal data.

    Only a PBKDF2-HMAC-SHA256 digest is stored -- never the password itself. The
    per-user salt and iteration count are columns rather than constants so the
    work factor can be raised later and old rows re-hashed on next successful
    login, instead of locking every existing account to today's parameters.
    """

    __tablename__ = "credentials"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True,
        nullable=False,
    )
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    password_salt: Mapped[str] = mapped_column(String(64), nullable=False)
    iterations: Mapped[int] = mapped_column(Integer, default=200_000, nullable=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: When the password was last set. Tokens issued before this are rejected,
    #: so changing a password signs out every other session. Not `updated_at`:
    #: that also moves on failed logins and transparent re-hashes.
    password_changed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped["User"] = relationship(back_populates="credential")

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_credentials_user_id"),
    )


class Profile(Base):
    """Personal, non-clinical contact data."""

    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True,
        nullable=False,
    )
    # Display name only. Never an email: an email in a general profile is a
    # correlator that defeats pseudonymisation of the health record.
    display_name: Mapped[Optional[str]] = mapped_column(String(120))
    # The onboarding form asks for these separately; `display_name` is derived
    # from them unless the patient sets it explicitly.
    first_name: Mapped[Optional[str]] = mapped_column(String(60))
    middle_name: Mapped[Optional[str]] = mapped_column(String(60))
    last_name: Mapped[Optional[str]] = mapped_column(String(60))
    email: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32))
    #: Set when the patient proved they hold `phone` with an SMS code. Only a
    #: verified phone can be used to sign in, and it is unique among verified
    #: phones (see `migrations.ensure_unique_phone_index`).
    phone_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    locale: Mapped[str] = mapped_column(String(8), default="en", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), default="ET", nullable=False)
    # Used to find nearby care. Optional; never shared beyond this account.
    address_line: Mapped[Optional[str]] = mapped_column(String(200))
    city: Mapped[Optional[str]] = mapped_column(String(100))
    region: Mapped[Optional[str]] = mapped_column(String(100))
    postal_code: Mapped[Optional[str]] = mapped_column(String(20))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped["User"] = relationship(back_populates="profile")


class Preferences(Base):
    """Experience settings. Deliberately separate from profile data.

    Reading preferences must never require reading anything sensitive, so these
    are not columns on `profiles`.
    """

    __tablename__ = "preferences"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True,
        nullable=False,
    )
    language: Mapped[str] = mapped_column(String(8), default="en", nullable=False)
    # Unused since live voice left the patient app; kept so existing rows load.
    voice_preference: Mapped[Optional[str]] = mapped_column(String(64))
    voice_gender: Mapped[Optional[str]] = mapped_column(String(8))
    theme: Mapped[str] = mapped_column(String(16), default="system", nullable=False)
    email_notifications: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sms_notifications: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    push_notifications: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Comma-separated ISO-8601 offsets (hours before the appointment). Stored as
    # text rather than hard-coded offsets so the policy is configurable per
    # deployment and per user without a migration.
    reminder_offsets: Mapped[str] = mapped_column(
        String(64), default="604800,86400,3600", nullable=False
    )
    preferred_contact_window: Mapped[Optional[str]] = mapped_column(String(64))
    #: What the patient wants from DEDAN (onboarding), comma-separated ids.
    onboarding_goals: Mapped[Optional[str]] = mapped_column(String(200))
    #: How far to search for care, in kilometres.
    care_search_radius_km: Mapped[Optional[int]] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped["User"] = relationship(back_populates="preferences")


class HealthProfile(Base):
    """Health context, kept apart from account data (spec §22).

    Only collects what the triage conversation actually consumes. Nothing is
    stored "in case it is useful later" -- speculative collection of health data
    is both a privacy harm and a liability.
    """

    __tablename__ = "health_profiles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True,
        nullable=False,
    )
    date_of_birth: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    sex: Mapped[Optional[str]] = mapped_column(String(16))
    #: When the exact date of birth is not given (onboarding asks for a
    #: range), e.g. "21-40". Age-dependent safety rules use it as a fallback.
    age_range: Mapped[Optional[str]] = mapped_column(String(16))
    # JSON columns rather than a fixed schema: the clinical vocabulary differs
    # per condition, and a rigid table would need a migration per new field.
    allergies: Mapped[Optional[str]] = mapped_column(Text)
    medications: Mapped[Optional[str]] = mapped_column(Text)
    conditions: Mapped[Optional[str]] = mapped_column(Text)
    emergency_contact_name: Mapped[Optional[str]] = mapped_column(String(120))
    emergency_contact_phone: Mapped[Optional[str]] = mapped_column(String(32))
    blood_type: Mapped[Optional[str]] = mapped_column(String(8))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped["User"] = relationship(back_populates="health_profile")


class Consent(Base):
    """First-class consent record (spec §27).

    Each purpose is tracked independently with its own timestamp, because
    "consent to analytics" and "consent to share data with a clinician" are
    different decisions and revoking one must not revoke the other.
    """

    __tablename__ = "consents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True,
        nullable=False,
    )
    treatment_processing: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    analytics: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    research: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    marketing: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    data_sharing_with_clinicians: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    granted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    policy_version: Mapped[str] = mapped_column(String(16), default="1.0", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped["User"] = relationship(back_populates="consent")


class UserEvent(Base):
    """Append-only audit trail for identity and profile changes (spec §31).

    `payload` deliberately holds only non-sensitive facts (which field changed),
    never the value of a health field: an audit log is read far more widely than
    the data it protects, so copying clinical detail into it widens exposure.
    """

    __tablename__ = "user_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True, nullable=False,
    )
    correlation_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    payload: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        Index("ix_user_events_user_time", "user_id", "occurred_at"),
    )


# ===========================================================================
# Stage 2: health timeline
# ===========================================================================

class HealthEventType:
    """Event vocabulary.

    A closed set rather than free text: the timeline UI filters on it, and an
    unconstrained string would silently fragment the data ("lab" vs "laboratory").
    Adding a type is a deliberate, reviewable act.
    """

    AI_CONVERSATION = "AI_CONVERSATION"
    APPOINTMENT = "APPOINTMENT"
    LAB_RESULT = "LAB_RESULT"
    IMAGING = "IMAGING"
    MEDICATION = "MEDICATION"
    PRESCRIPTION = "PRESCRIPTION"
    CONSULTATION = "CONSULTATION"
    FOLLOW_UP = "FOLLOW_UP"
    DOCUMENT = "DOCUMENT"
    OTHER = "OTHER"

    # Consultation-lifecycle vocabulary.
    #
    # A live consultation is a care journey with stages, not a single event, so
    # it needs types the original ten did not have. These are the stages:
    #   ASSESSMENT      DEDAN's understanding was written down
    #   LIVE_DISCUSSION a realtime humanoid consultation happened
    #   SYMPTOM_REPORT  the patient described symptoms
    #   SAFETY_ALERT    a red flag escalated and care was prioritised
    #   CARE_NAVIGATION DEDAN routed the patient to a facility
    #   TREATMENT       treatment was received or recorded
    #   NOTIFICATION    a reminder/notification was sent or scheduled
    #
    # Note what is deliberately ABSENT: there is no `DIAGNOSIS` type. A confirmed
    # diagnosis is an act of an authorised clinician or clinical system, and the
    # timeline must never be able to record one that DEDAN asserted.
    ASSESSMENT = "ASSESSMENT"
    LIVE_DISCUSSION = "LIVE_DISCUSSION"
    SYMPTOM_REPORT = "SYMPTOM_REPORT"
    SAFETY_ALERT = "SAFETY_ALERT"
    CARE_NAVIGATION = "CARE_NAVIGATION"
    TREATMENT = "TREATMENT"
    NOTIFICATION = "NOTIFICATION"

    ALL = (
        AI_CONVERSATION, APPOINTMENT, LAB_RESULT, IMAGING, MEDICATION,
        PRESCRIPTION, CONSULTATION, FOLLOW_UP, DOCUMENT, OTHER,
        ASSESSMENT, LIVE_DISCUSSION, SYMPTOM_REPORT, SAFETY_ALERT,
        CARE_NAVIGATION, TREATMENT, NOTIFICATION,
    )

    #: Types whose `status` may carry urgency, so the UI can escalate them
    #: without hard-coding strings.
    URGENT_TYPES = (SAFETY_ALERT, CARE_NAVIGATION, LIVE_DISCUSSION)


class EventStatus:
    """Lifecycle shared by timeline events."""

    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    RESCHEDULED = "RESCHEDULED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"

    ALL = (SCHEDULED, CONFIRMED, RESCHEDULED, CANCELLED, COMPLETED, MISSED)


class HealthEvent(Base):
    """One entry in a user's health timeline (spec §11-§13).

    Generic by design: a lab result and an AI conversation share `title`,
    `description` and `occurred_at`, and put their structured payload in
    `metadata`. A single wide table with nullable columns for every clinical
    concept was rejected -- it would need a migration per new field and would
    make "list everything" a full scan of mostly-NULL rows.

    `metadata` is a JSON text column rather than a native JSON type so the same
    model works on SQLite (tests) and PostgreSQL (production) unchanged.
    """

    __tablename__ = "health_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default=EventStatus.COMPLETED, nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="dedan", nullable=False)
    # `occurred_at` is when it happened clinically; `created_at` is when we
    # learned of it. They differ for backfilled records (a lab result uploaded
    # today for a test taken last month) and conflating them misorders a history.
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True, nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False,
    )
    metadata_json: Mapped[Optional[str]] = mapped_column(Text)
    # Link back to the originating conversation/appointment, so the timeline can
    # deep-link instead of showing an orphan summary.
    conversation_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    correlation_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)

    __table_args__ = (
        # The timeline's main access pattern is "this user's events, newest
        # first". A composite index makes that a range scan instead of a sort,
        # which is what keeps the timeline fast at a million events.
        Index("ix_health_events_user_occurred", "user_id", "occurred_at"),
        Index("ix_health_events_user_type_occurred", "user_id", "event_type", "occurred_at"),
    )


class Appointment(Base):
    """A scheduled clinical appointment (spec §14).

    Separate from `HealthEvent` rather than stored only as one, because an
    appointment has state that transitions, a reminder schedule, and a
    reschedule history that a generic timeline row cannot express.
    """

    __tablename__ = "appointments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False,
    )
    provider_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    organization_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    appointment_type: Mapped[str] = mapped_column(String(64), default="consultation", nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False,
    )
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=EventStatus.SCHEDULED, index=True, nullable=False,
    )
    location: Mapped[Optional[str]] = mapped_column(String(200))
    meeting_url: Mapped[Optional[str]] = mapped_column(String(500))
    #: "in_person" or "telehealth" (None on rows from before the column).
    visit_mode: Mapped[Optional[str]] = mapped_column(String(16))
    department: Mapped[Optional[str]] = mapped_column(String(120))
    #: "exact" or an arrival window ("morning", "afternoon", "evening").
    time_window: Mapped[Optional[str]] = mapped_column(String(16))
    #: A facility in the care directory (care_navigation.DIRECTORY).
    facility_id: Mapped[Optional[str]] = mapped_column(String(64))
    #: The clinician as the patient named them; there is no provider registry.
    provider_name: Mapped[Optional[str]] = mapped_column(String(120))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    reminder_offsets: Mapped[Optional[str]] = mapped_column(String(64))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow,
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    correlation_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)

    # --- Booked at an Endod partner hospital (hospital_bookings.py) ---
    #: The partner hospital (its id in the hospital service). None for a
    #: patient's own appointment entry.
    hospital_id: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    #: Where the hospital is with it: see hospital_bookings.HospitalState.
    hospital_state: Mapped[Optional[str]] = mapped_column(String(20))
    #: What the patient paid, in santim: the hospital's price and Endod's fee.
    price: Mapped[Optional[int]] = mapped_column(Integer)
    service_fee: Mapped[Optional[int]] = mapped_column(Integer)
    #: The video room on Endod's Jitsi server, once a doctor approved.
    meeting_room: Mapped[Optional[str]] = mapped_column(String(64))
    hospital_reason: Mapped[Optional[str]] = mapped_column(String(300))
    #: The patient's payment for it (booking_payments.PaymentState); None on
    #: rows paid from the old Endod balance.
    payment_status: Mapped[Optional[str]] = mapped_column(String(24))
    #: While awaiting payment: when the hold on the slot ends.
    payment_due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    #: While awaiting payment: Chapa's checkout page ("Pay now").
    payment_url: Mapped[Optional[str]] = mapped_column(String(500))

    __table_args__ = (
        # Supports the "upcoming appointments" query, which is by far the most
        # frequent read on this table.
        Index("ix_appointments_user_scheduled", "user_id", "scheduled_at"),
    )


# ===========================================================================
# Stage 3: notification queue
# ===========================================================================

class NotificationStatus:
    """Delivery lifecycle (spec §18)."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SENT = "SENT"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    CANCELLED = "CANCELLED"
    #: A policy decision, not a delivery outcome: the reminder was eligible by
    #: policy but deliberately not queued (its window had already passed, the
    #: recipient opted out, or there was no consented destination). Persisting
    #: this is what makes "why did my patient not get a reminder?" answerable
    #: instead of guessable, and it keeps a silently-dropped reminder from
    #: looking like a healthy queue.
    SKIPPED = "SKIPPED"

    ALL = (PENDING, PROCESSING, SENT, FAILED, RETRYING, CANCELLED, SKIPPED)

    #: Terminal states: no further worker pass will change them.
    TERMINAL = (SENT, FAILED, CANCELLED, SKIPPED)

    #: States a worker pass may claim.
    CLAIMABLE = (PENDING, RETRYING)


#: Why a notification was not queued. Recorded on the SKIPPED row so an
#: operator can distinguish a policy decision from a bug without reading logs.
SKIP_REASON_WINDOW_PASSED = "reminder_window_passed"
SKIP_REASON_OPTED_OUT = "channel_opted_out"
SKIP_REASON_NO_DESTINATION = "no_consented_destination"


class NotificationChannel:
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    WHATSAPP = "whatsapp"
    IN_APP = "in_app"

    ALL = (EMAIL, SMS, PUSH, WHATSAPP, IN_APP)


class Notification(Base):
    """A queued outbound notification (spec §16, §18).

    This table IS the queue. For a single-node deployment a durable table beats
    adding Redis or a message broker: it survives a restart (which is the whole
    point of not sending duplicates), it is inspectable when a patient asks why
    they were or were not emailed, and it needs no new infrastructure. Swapping in
    a broker later means replacing `claim_due_jobs`, not the rest of the flow.

    The unique constraint on `idempotency_key` is what makes enqueueing safe to
    retry: a second insert for the same logical notification is rejected by the
    database rather than sending a second email.
    """

    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    #: First-class link to the appointment this job exists for.
    #:
    #: This used to be recoverable only by substring-matching `payload_json`.
    #: That is a full table scan on a JSON text blob, and it is *wrong* the
    #: moment an appointment id appears inside another id or inside free text.
    #: Cancelling or re-arming reminders is a safety operation -- sending a
    #: patient to a clinic for an appointment that no longer exists -- so it
    #: must be an exact, indexed lookup rather than a hopeful substring match.
    appointment_id: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    channel: Mapped[str] = mapped_column(String(16), default=NotificationChannel.EMAIL, nullable=False)
    template: Mapped[str] = mapped_column(String(64), nullable=False)
    # Recipient captured at enqueue time. Storing it means a later email-address
    # change does not retroactively redirect an already-scheduled reminder.
    destination: Mapped[Optional[str]] = mapped_column(String(255))
    # Deterministic key derived from (appointment, offset). UNIQUE, so duplicate
    # enqueue is impossible.
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=NotificationStatus.PENDING, index=True, nullable=False,
    )
    # Awaiting this time. Indexed because the worker's only query is "what is due".
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    #: Reference handed back by the transport when it accepted the message.
    #:
    #: Distinguishes "we submitted this" from "the provider has a record of
    #: this", which is the strongest delivery evidence available without a
    #: signed provider webhook. Absent for transports that return no id.
    provider_message_id: Mapped[Optional[str]] = mapped_column(String(128))
    #: Strictly non-clinical payload. Email subjects are visible in inboxes and
    #: notification previews, so clinical detail must never travel here.
    payload_json: Mapped[Optional[str]] = mapped_column(Text)
    correlation_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False,
    )
    #: Last write to this row. Distinct from `created_at` so reconciliation can
    #: find jobs that have been stuck in PROCESSING for longer than they should
    #: be without inferring it from the row's age.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_notifications_idempotency_key"),
        # The worker's hot query: due jobs, oldest first.
        Index("ix_notifications_due", "status", "scheduled_for"),
        # Cancellation and re-arming both filter by (appointment, still-open
        # status); the composite keeps that from degrading into a scan as the
        # table grows.
        Index("ix_notifications_appointment_status", "appointment_id", "status"),
    )


class PhoneVerification(Base):
    """One SMS code sent to a phone number.

    The code itself is never stored: only an HMAC of it, keyed by the token
    signing secret and bound to this row's id, so a leaked table does not
    reveal live codes. A verification moves through three states:
    sent (`verified_at` empty) -> verified -> used (`used_at` set once the
    account is created or its password reset), and can be used only once.
    """

    __tablename__ = "phone_verifications"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    #: E.164, e.g. "+251911234567".
    phone: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    #: Caller address, for abuse investigation.
    client: Mapped[Optional[str]] = mapped_column(String(64))
    #: Reference returned by the SMS provider, when it gives one.
    provider_message_id: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False,
    )

    __table_args__ = (
        # Rate limiting counts recent codes per phone.
        Index("ix_phone_verifications_phone_created", "phone", "created_at"),
        Index("ix_phone_verifications_client_created", "client", "created_at"),
    )


class InboxItem(Base):
    """A message in the patient's in-app inbox (the notifications screen).

    Distinct from `Notification`, which is the *delivery queue* for email and
    SMS: an inbox item is something to read in the app, with read and
    dismissed state, and exists whether or not anything was sent externally.
    """

    __tablename__ = "inbox_items"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    #: Filter group shown in the app: appointments | records | messages | security.
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    #: What happened, e.g. "appointment_booked", "password_changed".
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[Optional[str]] = mapped_column(Text)
    #: Where tapping the item should take the patient, e.g. "appointment".
    link_screen: Mapped[Optional[str]] = mapped_column(String(32))
    link_id: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False,
    )
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    dismissed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_inbox_items_user_created", "user_id", "created_at"),
    )


# ===========================================================================
# Endod partner hospitals, payments and events with the hospital service
# ===========================================================================


class PartnerHospital(Base):
    """A hospital that joined Endod through the hospital portal.

    A copy of its listing, kept in step by ``hospital.listed`` /
    ``hospital.unlisted`` events, so patients can browse and book even while
    the hospital service is unreachable.
    """

    __tablename__ = "partner_hospitals"

    #: The hospital's id in the hospital service.
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    code: Mapped[str] = mapped_column(String(12), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    name_am: Mapped[Optional[str]] = mapped_column(String(160))
    #: "public" or "private".
    ownership: Mapped[str] = mapped_column(String(8), nullable=False, default="public")
    city: Mapped[Optional[str]] = mapped_column(String(100))
    address: Mapped[Optional[str]] = mapped_column(String(200))
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    ambulance_phone: Mapped[Optional[str]] = mapped_column(String(20))
    emergency: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    #: Comma-separated care_navigation department keys.
    services: Mapped[Optional[str]] = mapped_column(String(200))
    open_hours: Mapped[Optional[str]] = mapped_column(String(80))
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Africa/Addis_Ababa")
    video_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: Santim.
    price_in_person: Mapped[int] = mapped_column(Integer, nullable=False)
    price_video: Mapped[Optional[int]] = mapped_column(Integer)
    #: False once unlisted (kept for existing appointments' names and phones).
    listed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: The hospital service's announcement version last applied.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class WalletEntryKind:
    DEPOSIT = "deposit"
    PAYMENT = "payment"
    SERVICE_FEE = "service_fee"
    REFUND = "refund"
    #: Chapa refunded or reversed a deposit: the money is taken back (the
    #: balance may go below zero until it is settled).
    REVERSAL = "reversal"
    ALL = (DEPOSIT, PAYMENT, SERVICE_FEE, REFUND, REVERSAL)


class Wallet(Base):
    """A patient's Endod balance: money deposited for health payments.

    It cannot be withdrawn; it pays hospitals (through Endod) and comes back
    as refunds. ``balance`` is the sum of the ledger, kept on the row so a
    payment can lock it and check it in one step.
    """

    __tablename__ = "wallets"

    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True,
    )
    #: Santim.
    balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class WalletEntry(Base):
    """One movement of money in a wallet (never edited or deleted)."""

    __tablename__ = "wallet_entries"
    __table_args__ = (
        # A payment, fee or refund happens once per appointment, whatever retries.
        UniqueConstraint("appointment_id", "kind", name="uq_wallet_entry_appointment_kind"),
        UniqueConstraint("deposit_id", "kind", name="uq_wallet_entry_deposit_kind"),
        Index("ix_wallet_entries_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    #: Santim; positive adds to the balance, negative takes from it.
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    appointment_id: Mapped[Optional[str]] = mapped_column(String(32))
    deposit_id: Mapped[Optional[str]] = mapped_column(String(32))
    description: Mapped[Optional[str]] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class DepositStatus:
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    #: Paid, then refunded or reversed at Chapa (the credit was taken back).
    REVERSED = "reversed"
    ALL = (PENDING, SUCCEEDED, FAILED, REVERSED)


class Deposit(Base):
    """Money a patient is adding through Chapa."""

    __tablename__ = "deposits"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False,
    )
    #: Our reference at Chapa (unique per attempt).
    tx_ref: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default=DepositStatus.PENDING)
    checkout_url: Mapped[Optional[str]] = mapped_column(String(500))
    #: Chapa's own reference, once paid.
    provider_reference: Mapped[Optional[str]] = mapped_column(String(100))
    failure: Mapped[Optional[str]] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    #: When the worker last asked Chapa about it (so re-checks take turns).
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class BookingPaymentStatus:
    #: Checkout started; Chapa has not confirmed a payment.
    PENDING = "pending"
    #: Chapa confirmed the exact amount, in birr.
    PAID = "paid"
    #: The hold ended (expired or cancelled) with no confirmed payment.
    EXPIRED = "expired"
    #: Chapa reported a payment of another amount or currency: never accepted.
    MISMATCH = "mismatch"
    #: Paid, then refunded or reversed at Chapa without an Endod refund (a
    #: chargeback or a refund from the dashboard): the booking is cancelled.
    REVERSED = "reversed"
    ALL = (PENDING, PAID, EXPIRED, MISMATCH, REVERSED)


class BookingPayment(Base):
    """One Chapa payment for one partner-hospital booking (booking_payments.py)."""

    __tablename__ = "booking_payments"
    __table_args__ = (Index("ix_booking_payments_status_created", "status", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False,
    )
    #: One payment per booking.
    appointment_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    #: Our reference at Chapa.
    tx_ref: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    #: Santim: the hospital's price plus Endod's fee.
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="ETB")
    status: Mapped[str] = mapped_column(String(12), nullable=False, default=BookingPaymentStatus.PENDING)
    checkout_url: Mapped[Optional[str]] = mapped_column(String(500))
    #: Chapa's own reference, once paid.
    provider_reference: Mapped[Optional[str]] = mapped_column(String(100))
    #: What Chapa reported when it did not match (santim), for whoever sorts it out.
    reported_amount: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    #: The hold on the slot ends here.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    #: When the worker last asked Chapa about it (so re-checks take turns).
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class RefundStatus:
    #: To be sent to Chapa (again after a failed attempt: see next_attempt_at).
    PENDING = "pending"
    #: Chapa accepted it; waiting for Chapa to say the payer has it.
    SUBMITTED = "submitted"
    SUCCEEDED = "succeeded"
    #: Chapa refused or reversed it, or could not be reached for too long:
    #: Endod refunds it by hand from the Chapa dashboard.
    MANUAL = "manual_refund_needed"
    ALL = (PENDING, SUBMITTED, SUCCEEDED, MANUAL)


class BookingRefund(Base):
    """Money going back to the patient through Chapa: at most one per payment."""

    __tablename__ = "booking_refunds"
    __table_args__ = (Index("ix_booking_refunds_status_next", "status", "next_attempt_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    #: One refund per payment, whatever retries or races.
    payment_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    appointment_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False,
    )
    #: Santim.
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=RefundStatus.PENDING)
    #: Sent to Chapa as the refund's unique reference, so a retry cannot refund twice.
    reference: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    #: Chapa's id for the refund (``ref_id``), once accepted.
    chapa_ref_id: Mapped[Optional[str]] = mapped_column(String(100))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: A request to Chapa may have been accepted without our hearing so (a lost
    #: answer, a timeout, a crash mid-call): Chapa is asked before anything else.
    maybe_accepted: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    #: Set while a call to Chapa is under way; still set later means its answer was lost.
    in_flight_since: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[Optional[str]] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class PayoutStatus:
    """What Endod owes a hospital for one appointment."""

    #: Paid by the patient; the visit has not happened yet.
    HELD = "held"
    #: The visit took place: Endod owes the hospital.
    DUE = "due"
    #: Refunded to the patient: nothing is owed.
    VOID = "void"
    PAID = "paid"
    #: The hospital completed a visit the patient had cancelled (and been
    #: refunded) at the same moment: for a person to settle.
    DISPUTED = "disputed"
    ALL = (HELD, DUE, VOID, PAID, DISPUTED)


class HospitalPayout(Base):
    """The hospital's share of one appointment payment (Endod pays it out)."""

    __tablename__ = "hospital_payouts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    hospital_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    appointment_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    #: Santim (the hospital's price; Endod's fee is not included).
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(8), nullable=False, default=PayoutStatus.HELD)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class OutboxEvent(Base):
    """An event waiting to be sent to the hospital service (see eventbus.py)."""

    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_unpublished", "published_at", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class ProcessedEvent(Base):
    """An event from the hospital service already handled."""

    __tablename__ = "processed_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


# ===========================================================================
# Patient history from partner hospitals (docs/history-events.md)
# ===========================================================================

class HospitalLink(Base):
    """A hospital's patient record linked to an Endod account (contract section 1)."""

    __tablename__ = "hospital_links"
    __table_args__ = (UniqueConstraint("hospital_id", "patient_id", name="uq_hospital_links_patient"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    hospital_id: Mapped[str] = mapped_column(String(32), nullable=False)
    #: The hospital's own id for the patient.
    patient_id: Mapped[str] = mapped_column(String(64), nullable=False)
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class HospitalRecord(Base):
    """A clinical record published by a partner hospital (contract section 2).

    Only the highest ``version`` is kept. A retracted record stays (for the
    audit trail) but is never shown or shared.
    """

    __tablename__ = "hospital_records"
    __table_args__ = (Index("ix_hospital_records_user_occurred", "user_id", "occurred_at"),)

    #: The hospital's record id (32 hex).
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    hospital_id: Mapped[str] = mapped_column(String(32), nullable=False)
    hospital_name: Mapped[str] = mapped_column(String(160), nullable=False)
    visit_id: Mapped[Optional[str]] = mapped_column(String(32))
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    details_json: Mapped[Optional[str]] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_by: Mapped[Optional[str]] = mapped_column(String(160))
    source: Mapped[str] = mapped_column(String(8), nullable=False, default="portal")
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    retracted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    retracted_reason: Mapped[Optional[str]] = mapped_column(String(300))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class RecordFileStatus:
    #: Not downloaded yet (or a retry is due).
    PENDING = "pending"
    #: A worker is downloading it.
    DOWNLOADING = "downloading"
    STORED = "stored"
    #: Gave up after the last retry.
    FAILED = "failed"
    #: No longer part of the record (a correction dropped it).
    REMOVED = "removed"


class RecordFile(Base):
    """A file attached to a hospital record, and the platform's copy of it."""

    __tablename__ = "record_files"
    __table_args__ = (
        UniqueConstraint("record_id", "file_id", name="uq_record_files_record_file"),
        Index("ix_record_files_due", "status", "next_attempt_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    record_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    #: The hospital's file id (32 hex).
    file_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(200), nullable=False)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default=RecordFileStatus.PENDING)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(String(300))
    stored_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    #: The stored copy's own name (16 hex), so each copy has a path of its
    #: own: removing an old copy can never remove a newer one. Set when STORED.
    copy_id: Mapped[Optional[str]] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class FollowUp(Base):
    """A follow-up visit a hospital doctor set (contract section 3)."""

    __tablename__ = "follow_ups"
    __table_args__ = (UniqueConstraint("hospital_id", "visit_id", name="uq_follow_ups_visit"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    hospital_id: Mapped[str] = mapped_column(String(32), nullable=False)
    hospital_name: Mapped[str] = mapped_column(String(160), nullable=False)
    visit_id: Mapped[str] = mapped_column(String(32), nullable=False)
    #: YYYY-MM-DD (the hospital's calendar day).
    follow_up_on: Mapped[str] = mapped_column(String(10), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(String(500))
    doctor_name: Mapped[Optional[str]] = mapped_column(String(120))
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    #: When the hospital sent the newest change applied (the envelope time),
    #: so a change delivered late never overwrites a newer one.
    event_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class QueueEntry(Base):
    """The latest known state of one place in a hospital queue (contract section 4)."""

    __tablename__ = "queue_entries"

    #: The hospital's entry id (32 hex).
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    #: Null for a walk-in without an Endod account.
    user_id: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    hospital_id: Mapped[str] = mapped_column(String(32), nullable=False)
    hospital_name: Mapped[str] = mapped_column(String(160), nullable=False)
    doctor_name: Mapped[Optional[str]] = mapped_column(String(120))
    day: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    ticket: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    ahead: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class RecordShare(Base):
    """Records the patient shared with a partner hospital (contract section 5)."""

    __tablename__ = "record_shares"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    hospital_id: Mapped[str] = mapped_column(String(32), nullable=False)
    hospital_name: Mapped[str] = mapped_column(String(160), nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    #: When ``records.unshared`` was queued (revoked, or expired).
    unshared_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)


class RecordShareItem(Base):
    """One record in a share: a hospital record or a self-reported one."""

    __tablename__ = "record_share_items"
    __table_args__ = (UniqueConstraint("share_id", "record_id", name="uq_record_share_items"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    share_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("record_shares.id", ondelete="CASCADE"), index=True, nullable=False)
    #: "hospital" (hospital_records.id) or "self" (health_events.id).
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    record_id: Mapped[str] = mapped_column(String(32), nullable=False)


# ===========================================================================
# Prescriptions at pharmacies (docs/pharmacy.md)
# ===========================================================================

class Prescription(Base):
    """A hospital prescription's dispensing entry (contract section 1).

    One per prescription record; a correction keeps it (same rx_id, QR and
    code). Only when a correction moves the record to another patient is the
    entry withdrawn and a new one issued, so the first patient's QR and code
    never open the second patient's prescription.
    """

    __tablename__ = "prescriptions"

    #: rx_id (32 hex): what the QR token signs.
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    record_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("hospital_records.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    #: The 6-digit code, kept for the entry's life (lookups by code + phone).
    code: Mapped[str] = mapped_column(String(6), index=True, nullable=False)
    #: The same code while the entry is active, else null: unique, so no two
    #: active prescriptions share a code.
    active_code: Mapped[Optional[str]] = mapped_column(String(6), unique=True)
    #: "open" or "completed"; "expired" and "retracted" are worked out on read.
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="open")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Set when the record moved to another patient or stopped being a prescription.
    withdrawn_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    #: Bumped by every dispense before anything is read: the row lock.
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class PrescriptionItem(Base):
    """One medicine on a prescription, matched to the record's items by index."""

    __tablename__ = "prescription_items"
    __table_args__ = (UniqueConstraint("rx_id", "item_index", name="uq_prescription_items_index"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    rx_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("prescriptions.id", ondelete="CASCADE"), index=True, nullable=False)
    item_index: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_text: Mapped[Optional[str]] = mapped_column(String(40))
    quantity_total: Mapped[Optional[float]] = mapped_column(Float)
    given_total: Mapped[Optional[float]] = mapped_column(Float)
    #: A pharmacist marked it given ("complete"), whatever the count.
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: "not_given" | "partly_given" | "given"
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="not_given")
    #: A correction dropped this item (its given amount is kept, should it return).
    removed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PrescriptionDispense(Base):
    """Medicine given at a pharmacy (contract section 2, ``/pharmacy/dispense``)."""

    __tablename__ = "prescription_dispenses"

    #: dispense_id (32 hex), sent to the hospital.
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    rx_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("prescriptions.id", ondelete="CASCADE"), index=True, nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    #: As the pharmacist typed it (not verified).
    pharmacy_name: Mapped[str] = mapped_column(String(120), nullable=False)
    pharmacist_name: Mapped[Optional[str]] = mapped_column(String(120))
    #: [{"item_index", "amount", "complete"}]
    items_json: Mapped[str] = mapped_column(Text, nullable=False)
    #: The pharmacy site's Idempotency-Key: a repeat returns ``response_json``.
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(36), unique=True)
    response_json: Mapped[Optional[str]] = mapped_column(Text)


class ThrottleHit(Base):
    """One attempt counted against a rate limit (see throttle.py). In the
    database, so every process and replica shares the limits."""

    __tablename__ = "throttle_hits"
    __table_args__ = (Index("ix_throttle_hits_bucket_at", "bucket", "at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
    bucket: Mapped[str] = mapped_column(String(120), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True, nullable=False)
