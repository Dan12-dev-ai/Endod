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
    Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
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
    email: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32))
    locale: Mapped[str] = mapped_column(String(8), default="en", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), default="KE", nullable=False)
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
    # Catalog voice id, validated against `realtime.voices` at the API boundary
    # so an invalid id cannot be persisted.
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
