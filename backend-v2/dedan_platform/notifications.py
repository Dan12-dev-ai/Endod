"""
Stage 3: notification engine (spec §16, §18).

Flow
----
    Appointment created
        -> enqueue_reminders()      (rows in `notifications`, PENDING)
        -> NotificationWorker       (polls for due jobs, claims, delivers)
        -> EmailProvider            (SMTP / provider API)
        -> SENT | RETRYING | FAILED

Guarantees this implements
-------------------------
* **Idempotent.** `idempotency_key` is deterministic per (appointment, offset)
  and UNIQUE in the database, so a re-scheduled or duplicated enqueue cannot
  produce a second email.
* **Retryable.** Failures back off exponentially and are capped, so a mail
  provider outage does not become an unbounded retry storm.
* **Recoverable.** A worker that dies mid-delivery leaves the job `PROCESSING`;
  `recover_stale_jobs` returns those to `PENDING` on startup.
* **Channel-agnostic.** Adding SMS or WhatsApp means a new provider, not a
  change to appointment logic.

Email hygiene
-------------
Subjects are generic ("DEDAN Health — Appointment Reminder") and the payload
carries no diagnosis, per spec §17. Clinical detail in a subject line is
disclosed to anyone who can see the phone's notification preview.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from dedan_platform.db import ensure_aware, get_session_factory, new_uuid, session_scope
from dedan_platform.models import (
    Appointment, EventStatus, Notification, NotificationChannel, NotificationStatus, utcnow,
    SKIP_REASON_NO_DESTINATION, SKIP_REASON_OPTED_OUT, SKIP_REASON_WINDOW_PASSED,
)

logger = logging.getLogger(__name__)

# Retry policy. Capped attempts with exponential backoff: an unreachable mail
# provider would otherwise retry forever and block the queue head.
MAX_ATTEMPTS = int(os.getenv("NOTIFICATION_MAX_ATTEMPTS", "5"))
BASE_BACKOFF_SECONDS = int(os.getenv("NOTIFICATION_BASE_BACKOFF", "60"))
#: Extra candidates read per claim, so concurrent workers rarely come up empty.
CLAIM_HEADROOM = 10

# A PROCESSING job older than this is assumed orphaned by a crashed worker.
#
# Jobs are claimed one at a time, so a PROCESSING job is at most one send old.
# The threshold is kept well above the longest a send can take (several SMTP
# operations, each bounded by SMTP_TIMEOUT_SECONDS), so recovery never takes a
# job whose send is still running.
STALE_PROCESSING_SECONDS = max(
    int(os.getenv("NOTIFICATION_STALE_SECONDS", "300")),
    6 * int(os.getenv("SMTP_TIMEOUT_SECONDS", "20")) + 60,
)

# What to do with a reminder whose window has already passed -- a booking made
# less than 24h (or less than 1h) before the appointment.
#
#   skip     -- do not queue it. Default, and the behaviour the spec requires:
#               an overdue reminder that fires on arrival arrives after the
#               appointment it is reminding about, which reads as a system that
#               does not know when the appointment is.
#   compress -- queue a single reminder to fire as soon as the worker next runs.
#               For a clinic that genuinely wants late bookers contacted.
LATE_BOOKING_POLICY = os.getenv("REMINDER_LATE_BOOKING_POLICY", "skip").strip().lower()
COMPRESS_DELAY_SECONDS = int(os.getenv("REMINDER_COMPRESS_DELAY_SECONDS", "300"))
LATE_BOOKING_POLICIES = ("skip", "compress")


class NotificationError(RuntimeError):
    """Notification enqueue/delivery failed."""


def idempotency_key(
    appointment_id: str,
    offset_seconds: int,
    channel: str,
    scheduled_for: Optional[datetime] = None,
) -> str:
    """Deterministic key for one logical notification.

    Deterministic rather than random: uniqueness must come from *what the
    notification is*, not from *when it was created*, otherwise a retry creates
    a duplicate instead of being deduplicated.

    `scheduled_for` is part of the identity. An appointment that moves from
    Tuesday to Thursday still wants a 24-hour reminder, but it is a *different*
    notification about a *different* time. Without the appointment instant in
    the key, re-arming a rescheduled appointment would collide with the
    already-cancelled job for the old time, the unique constraint would reject
    it, and the patient would receive nothing at all.
    """
    stamp = scheduled_for.isoformat() if scheduled_for is not None else ""
    raw = f"{appointment_id}|{offset_seconds}|{channel}|{stamp}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"{appointment_id}:{offset_seconds}:{channel}:{digest}"


def skip_idempotency_key(
    appointment_id: str, offset_seconds: int, channel: str, reason: str
) -> str:
    """Key for a recorded policy decision to *not* send.

    A deliberately separate namespace from `idempotency_key`. If skip records
    shared the send key, the very first skipped window would permanently block
    the real reminder for that offset -- and a reschedule that moves an
    appointment into a future window would be silently dropped.
    """
    raw = f"{appointment_id}|{offset_seconds}|{channel}|{reason}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"skip:{appointment_id}:{offset_seconds}:{channel}:{reason}:{digest}"


@dataclass
class EnqueueOutcome:
    """Result of a scheduling pass.

    `skipped` is reported rather than swallowed so that "the patient got no
    reminder" is always attributable to a named policy rule.
    """

    created: List[str] = field(default_factory=list)
    skipped: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def queued(self) -> int:
        return len(self.created)


def _insert_notification(
    user_id: str,
    appointment_id: Optional[str],
    channel: str,
    template: str,
    destination: Optional[str],
    key: str,
    status: str,
    fire_at: datetime,
    payload: Optional[Dict[str, Any]],
    correlation_id: Optional[str],
) -> Optional[str]:
    """Insert one notification row. Returns its id, or None if it already existed.

    Uses an explicit session rather than `session_scope`, because the duplicate
    case needs a rollback followed by *no* commit: `session_scope` commits on
    exit, so returning early from inside its `with` block would make it commit a
    session that had already failed, raising PendingRollbackError instead of
    quietly ignoring the duplicate.

    The flush/commit is inside the try: `session.add()` is lazy, so the unique
    constraint is not evaluated until the transaction ends. Wrapping only the
    `with` block let the IntegrityError escape during commit -- outside the
    except -- and a duplicate reminder was silently queued. Caught by test.
    """
    job_id = new_uuid()
    session = get_session_factory()()
    try:
        session.add(Notification(
            id=job_id,
            user_id=user_id,
            appointment_id=appointment_id,
            channel=channel,
            template=template,
            destination=destination,
            idempotency_key=key,
            status=status,
            scheduled_for=fire_at,
            payload_json=json.dumps(payload) if payload else None,
            correlation_id=correlation_id,
        ))
        session.commit()
        return job_id
    except IntegrityError:
        # Unique constraint did its job: this logical notification already
        # exists. Rolling back drops the pending insert and nothing else,
        # because this session has written nothing else.
        session.rollback()
    finally:
        session.close()

    if status != NotificationStatus.PENDING:
        # A skip record colliding with another skip record is the same decision
        # being recorded twice. Nothing to resurrect.
        return None

    resurrected = _resurrect(key, status, fire_at, payload)
    if resurrected:
        return resurrected
    logger.info("notification_already_queued", extra={"key": key})
    return None


#: Terminal states a still-undelivered job may be revived from. SENT and FAILED
#: are excluded: SENT has real delivery evidence behind it, and FAILED has
#: exhausted its retry budget, so reviving either would risk a duplicate message
#: or an unbounded retry loop.
RESURRECTABLE = (NotificationStatus.CANCELLED, NotificationStatus.SKIPPED)


def _resurrect(
    key: str,
    status: str,
    fire_at: datetime,
    payload: Optional[Dict[str, Any]],
) -> Optional[str]:
    """Revive a CANCELLED/SKIPPED job so the same reminder can be scheduled again.

    The idempotency key is derived from (appointment, offset, channel, scheduled
    instant), so it deliberately survives cancellation: re-arming a reminder for
    the *same* appointment time must not produce a second logical notification.
    But that means a key stays occupied after its row is cancelled, and without
    this a genuinely needed re-arm -- reminders lost during a failed enqueue, or
    an appointment reinstated after being cancelled -- would be silently dropped
    by the very constraint that prevents duplicates.

    Only ever moves a job *forward* from an undelivered state, so the
    no-duplicate-delivery guarantee is preserved.
    """
    with session_scope() as session:
        existing = session.scalar(
            select(Notification).where(Notification.idempotency_key == key)
        )
        if existing is None or existing.status not in RESURRECTABLE:
            return None
        existing.status = NotificationStatus.PENDING
        existing.scheduled_for = fire_at
        existing.attempts = 0
        existing.last_error = None
        existing.updated_at = utcnow()
        if payload is not None:
            existing.payload_json = json.dumps(payload)
        session.flush()
        return existing.id


def enqueue_reminders(
    user_id: str,
    appointment_id: str,
    scheduled_at: datetime,
    offsets: List[int],
    destination: Optional[str],
    payload: Optional[Dict[str, Any]] = None,
    channel: str = NotificationChannel.EMAIL,
    correlation_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> EnqueueOutcome:
    """Queue one reminder per offset. Returns what was created and what was skipped.

    A duplicate enqueue is *not* an error: re-running the scheduler after a
    crash must be safe, so existing keys are skipped rather than raised on.
    """
    now = now or utcnow()
    outcome = EnqueueOutcome()
    policy = LATE_BOOKING_POLICY if LATE_BOOKING_POLICY in LATE_BOOKING_POLICIES else "skip"

    for offset in offsets:
        fire_at = scheduled_at - timedelta(seconds=offset)

        if fire_at <= now:
            # The window has already closed: a booking made less than `offset`
            # ahead of the appointment. Firing now would arrive after the
            # appointment it is reminding about.
            if policy == "compress":
                fire_at = now + timedelta(seconds=COMPRESS_DELAY_SECONDS)
                logger.info(
                    "reminder_window_compressed",
                    extra={"appointment": appointment_id, "offset": offset},
                )
            else:
                _record_skip(
                    user_id=user_id,
                    appointment_id=appointment_id,
                    offset=offset,
                    channel=channel,
                    reason=SKIP_REASON_WINDOW_PASSED,
                    fire_at=fire_at,
                    correlation_id=correlation_id,
                )
                outcome.skipped.append({
                    "offset_seconds": offset,
                    "reason": SKIP_REASON_WINDOW_PASSED,
                    "scheduled_for": fire_at.isoformat(),
                })
                logger.info(
                    "reminder_window_already_passed",
                    extra={"appointment": appointment_id, "offset": offset},
                )
                continue

        key = idempotency_key(appointment_id, offset, channel, scheduled_at)
        job_id = _insert_notification(
            user_id=user_id,
            appointment_id=appointment_id,
            channel=channel,
            template="appointment_reminder",
            destination=destination,
            key=key,
            status=NotificationStatus.PENDING,
            fire_at=fire_at,
            payload=payload,
            correlation_id=correlation_id,
        )
        if job_id:
            outcome.created.append(job_id)
    return outcome


def _record_skip(
    user_id: str,
    appointment_id: str,
    offset: int,
    channel: str,
    reason: str,
    fire_at: datetime,
    correlation_id: Optional[str] = None,
) -> None:
    """Persist a SKIPPED row so a non-delivery is always explainable."""
    _insert_notification(
        user_id=user_id,
        appointment_id=appointment_id,
        channel=channel,
        template="appointment_reminder",
        destination=None,
        key=skip_idempotency_key(appointment_id, offset, channel, reason),
        status=NotificationStatus.SKIPPED,
        fire_at=fire_at,
        payload={"offset_seconds": offset, "skip_reason": reason},
        correlation_id=correlation_id,
    )


def record_window_passed_skip(
    user_id: str,
    appointment_id: str,
    offset: int,
    channel: str,
    scheduled_at: datetime,
    correlation_id: Optional[str] = None,
) -> None:
    """Record a reminder window that had already closed when we got here.

    A booking made less than `offset` before the appointment. The reminder was
    wanted but is no longer possible, so it is recorded rather than dropped --
    this is the record that distinguishes "policy said no" from "we forgot".
    """
    _record_skip(
        user_id=user_id,
        appointment_id=appointment_id,
        offset=offset,
        channel=channel,
        reason=SKIP_REASON_WINDOW_PASSED,
        fire_at=scheduled_at - timedelta(seconds=offset),
        correlation_id=correlation_id,
    )


def record_no_destination_skip(
    user_id: str,
    appointment_id: str,
    offset: int,
    channel: str,
    scheduled_at: datetime,
    correlation_id: Optional[str] = None,
) -> None:
    """Record a reminder withheld because the channel had no usable address.

    Distinct from an opt-out: consent may be granted and the address simply
    missing or invalid. Collapsing the two would hide a data-quality problem
    behind a consent decision.
    """
    _record_skip(
        user_id=user_id,
        appointment_id=appointment_id,
        offset=offset,
        channel=channel,
        reason=SKIP_REASON_NO_DESTINATION,
        fire_at=scheduled_at - timedelta(seconds=offset),
        correlation_id=correlation_id,
    )


def record_opt_out_skip(
    user_id: str,
    appointment_id: str,
    offset: int,
    channel: str,
    correlation_id: Optional[str] = None,
) -> None:
    """Record that a reminder was withheld because the channel is switched off.

    Consent is not the same as a bug. Recording the decision means a support
    agent can answer "why did I get nothing?" without reading code, and it keeps
    an opt-out from looking like a queue failure in the delivery metrics.
    """
    _record_skip(
        user_id=user_id,
        appointment_id=appointment_id,
        offset=offset,
        channel=channel,
        reason=SKIP_REASON_OPTED_OUT,
        fire_at=utcnow(),
        correlation_id=correlation_id,
    )


def claim_due_jobs(
    limit: int = 20,
    now: Optional[datetime] = None,
    channels: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Atomically claim due jobs and return them.

    Claiming is a conditional UPDATE (`WHERE status = PENDING`), not a
    SELECT-then-UPDATE: with two workers running, a plain read would hand the
    same job to both and the patient would get two emails. The conditional
    update makes the claim atomic and the loser gets zero rows.

    `now` is injectable so an end-to-end test can drive the queue to a
    reminder's due time without sleeping through the 24-hour wait.
    """
    now = now or utcnow()
    claimed: List[Dict[str, Any]] = []
    with session_scope() as session:
        # More candidates than needed: with several workers polling together,
        # losing the conditional UPDATE on one candidate moves on to the next
        # instead of returning nothing (which ended that worker's whole pass).
        query = (
            select(Notification)
            .where(
                Notification.status.in_(list(NotificationStatus.CLAIMABLE)),
                Notification.scheduled_for <= now,
            )
            .order_by(Notification.scheduled_for)
            .limit(limit + CLAIM_HEADROOM)
        )
        if channels is not None:
            # Only channels with a working transport, so jobs for a channel
            # that is not configured wait instead of failing.
            query = query.where(Notification.channel.in_(channels))
        candidates = list(session.scalars(query))
        for job in candidates:
            if len(claimed) >= limit:
                break
            result = session.execute(
                update(Notification)
                .where(Notification.id == job.id)
                .where(Notification.status.in_(list(NotificationStatus.CLAIMABLE)))
                .values(status=NotificationStatus.PROCESSING, updated_at=utcnow())
            )
            if result.rowcount == 1:
                job.status = NotificationStatus.PROCESSING
                claimed.append({
                    "id": job.id,
                    "user_id": job.user_id,
                    "appointment_id": job.appointment_id,
                    "channel": job.channel,
                    "template": job.template,
                    "destination": job.destination,
                    "attempts": job.attempts,
                    "payload": json.loads(job.payload_json) if job.payload_json else {},
                    "correlation_id": job.correlation_id,
                })
    return claimed


def mark_sent(job_id: str, provider_message_id: Optional[str] = None) -> None:
    """Record successful submission to the transport.

    `provider_message_id` is the strongest delivery evidence available without
    a signed provider webhook: the provider's own reference for the message.
    Its absence does not mean delivery failed -- SMTP returns no id -- which is
    why this is recorded rather than required.
    """
    with session_scope() as session:
        session.execute(
            update(Notification).where(Notification.id == job_id).values(
                status=NotificationStatus.SENT,
                sent_at=utcnow(),
                updated_at=utcnow(),
                provider_message_id=provider_message_id,
                last_error=None,
            )
        )


def mark_skipped(job_id: str, reason: str) -> None:
    """Close a claimed job that cannot be delivered, recording why."""
    with session_scope() as session:
        session.execute(
            update(Notification).where(Notification.id == job_id).values(
                status=NotificationStatus.SKIPPED,
                updated_at=utcnow(),
                last_error=reason[:500],
            )
        )


def mark_failed(job_id: str, error: str, attempts: int) -> str:
    """Record a failure and decide whether to retry.

    ``attempts`` is the number of delivery attempts made, *including* this one;
    it is stored as given. (It used to be incremented again here as well, so a
    job with five allowed attempts failed permanently after three.)

    Returns the resulting status so the caller (and tests) can assert on it.
    """
    if attempts >= MAX_ATTEMPTS:
        with session_scope() as session:
            session.execute(
                update(Notification)
                .where(Notification.id == job_id)
                .where(Notification.status == NotificationStatus.PROCESSING)
                .values(
                    status=NotificationStatus.FAILED,
                    updated_at=utcnow(),
                    last_error=error[:500],
                    attempts=attempts,
                )
            )
        logger.error(
            "notification_failed_permanently",
            extra={"job": job_id, "attempts": attempts},
        )
        return NotificationStatus.FAILED

    # Exponential backoff, so a provider outage does not produce a tight retry
    # loop that starves the rest of the queue. The next eligible time is stored
    # in `scheduled_for`, which is the same column the worker scans, so there is
    # no second clock to keep in sync.
    delay = BASE_BACKOFF_SECONDS * (2 ** max(0, attempts - 1))
    with session_scope() as session:
        session.execute(
            update(Notification)
            .where(Notification.id == job_id)
            .where(Notification.status == NotificationStatus.PROCESSING)
            .values(
                status=NotificationStatus.RETRYING,
                updated_at=utcnow(),
                last_error=error[:500],
                attempts=attempts,
                scheduled_for=utcnow() + timedelta(seconds=delay),
            )
        )
    return NotificationStatus.RETRYING


def cancel_for_appointment(appointment_id: str) -> int:
    """Cancel every unsent reminder for an appointment.

    Called when an appointment is cancelled, completed, missed or rescheduled: a
    reminder about an appointment that no longer stands is worse than no
    reminder, because it sends the patient to a clinic for a visit that does not
    exist.

    Matches on the indexed `appointment_id` column. The previous
    `payload_json LIKE '%<id>%'` scan was both a full-text scan and unsound --
    it would match any payload that happened to contain the id as a substring.
    """
    with session_scope() as session:
        rows = list(session.scalars(
            select(Notification).where(
                Notification.appointment_id == appointment_id,
                Notification.status.in_(list(NotificationStatus.CLAIMABLE)),
            )
        ))
        for job in rows:
            job.status = NotificationStatus.CANCELLED
            job.updated_at = utcnow()
        if rows:
            logger.info(
                "appointment_reminders_cancelled",
                extra={"appointment": appointment_id, "count": len(rows)},
            )
        return len(rows)


def recover_stale_jobs(now: Optional[datetime] = None) -> int:
    """Return orphaned PROCESSING jobs to the queue.

    Called on worker start and each pass. Without it, a crash mid-delivery
    leaves a job stuck in PROCESSING forever -- neither retried nor failed, so
    the patient silently never receives it.

    Measured from `updated_at`, which moves on every status write, rather than
    `created_at`: a job enqueued three days ago and claimed a second ago is not
    orphaned.
    """
    now = now or utcnow()
    cutoff = now - timedelta(seconds=STALE_PROCESSING_SECONDS)
    with session_scope() as session:
        rows = list(session.scalars(
            select(Notification).where(
                Notification.status == NotificationStatus.PROCESSING,
                Notification.updated_at <= cutoff,
            )
        ))
        for job in rows:
            # Counted as an attempt: a job that crashes the worker every time
            # would otherwise be recovered and retried forever.
            job.attempts = int(job.attempts or 0) + 1
            job.updated_at = now
            if job.attempts >= MAX_ATTEMPTS:
                job.status = NotificationStatus.FAILED
                job.last_error = "stuck in processing"
                logger.error(
                    "notification_failed_permanently",
                    extra={"job": job.id, "attempts": job.attempts, "reason": "stuck_in_processing"},
                )
            else:
                job.status = NotificationStatus.RETRYING
                job.scheduled_for = now
        if rows:
            logger.info("recovered_stale_notifications", extra={"count": len(rows)})
        return len(rows)


def queue_stats() -> Dict[str, int]:
    """Counts by status, for the observability requirement (spec §32)."""
    from sqlalchemy import func

    with session_scope() as session:
        rows = session.execute(
            select(Notification.status, func.count(Notification.id))
            .group_by(Notification.status)
        ).all()
        stats = {status: 0 for status in NotificationStatus.ALL}
        for status, count in rows:
            stats[status] = count
        return stats


def queue_depth() -> Dict[str, Any]:
    """Queue pressure: depth plus the oldest pending job's age.

    A depth that is merely "large" says little; the age of the oldest due job
    is what distinguishes a busy queue from a stalled one, and it is what an
    alert should fire on.
    """
    now = utcnow()
    with session_scope() as session:
        pending = session.scalar(
            select(func.count(Notification.id)).where(
                Notification.status.in_(list(NotificationStatus.CLAIMABLE))
            )
        )
        oldest = session.scalar(
            select(func.min(Notification.scheduled_for)).where(
                Notification.status.in_(list(NotificationStatus.CLAIMABLE))
            )
        )
    oldest_aware = oldest if (oldest is None or oldest.tzinfo) else oldest.replace(tzinfo=timezone.utc)
    age = None if oldest_aware is None else (now - oldest_aware).total_seconds()
    return {
        "pending": int(pending or 0),
        "oldest_pending_seconds": None if age is None else int(age),
        "by_status": queue_stats(),
    }


class _Offsets:
    """Minimal stand-in exposing only what `reminder_offsets_for` reads.

    Lets reconciliation evaluate the reminder policy without holding an ORM
    instance open across sessions.
    """

    __slots__ = ("scheduled_at", "reminder_offsets")

    def __init__(self, scheduled_at: datetime, reminder_offsets: Optional[str]):
        self.scheduled_at = scheduled_at
        self.reminder_offsets = reminder_offsets


def reconcile_appointments(horizon_days: int = 30, now: Optional[datetime] = None) -> Dict[str, int]:
    """Repair appointments whose reminder jobs went missing.

    Two failure modes are reconciled here, both of which are silent without it:

    * **No reminders at all.** An appointment created while enqueueing was
      failing (a database blip, a deploy between the two writes) has no rows
      and no error -- nothing was logged, because nothing threw.
    * **A cancelled/completed appointment still holding open reminders**, which
      would send a patient to a clinic for a visit that does not exist.

    Idempotent: re-running re-derives the same jobs and the unique constraint
    absorbs the ones that already exist.
    """
    from dedan_platform import appointments as appt
    from dedan_platform import scheduler

    now = now or utcnow()
    horizon = now + timedelta(days=horizon_days)
    result = {"repaired": 0, "cancelled": 0, "examined": 0}

    # Projected into plain values inside the session. Touching a detached ORM
    # instance after the session closes re-loads it, which on a SQLite row
    # written as UTC comes back *naive* -- and comparing that against an aware
    # `now` raises. Normalising once, here, keeps every later comparison sound.
    with session_scope() as session:
        rows = list(session.execute(
            select(
                Appointment.id,
                Appointment.user_id,
                Appointment.scheduled_at,
                Appointment.correlation_id,
            ).where(
                Appointment.scheduled_at >= now,
                Appointment.scheduled_at <= horizon,
                Appointment.status.in_([
                    EventStatus.SCHEDULED, EventStatus.CONFIRMED, EventStatus.RESCHEDULED,
                ]),
            )
        ).all())

    for appointment_id, user_id, scheduled_at, correlation_id in rows:
        result["examined"] += 1
        scheduled_at = ensure_aware(scheduled_at)

        # How many reminders the policy says should still be open. Compared
        # against what is actually open, so a partial loss is repaired without
        # re-queueing reminders that already exist.
        expected = len(appt.reminder_offsets_for(
            _Offsets(scheduled_at, None), _preference_offsets(user_id)
        ))
        # Per channel: three email reminders must not hide three missing SMS.
        existing = min(
            count_handled_for_appointment(appointment_id, channel)
            for channel in scheduler.REMINDER_CHANNELS
        )
        if existing >= expected:
            continue

        # Routed through the same scheduler the booking path uses, so a repair
        # derives identical jobs -- including consent and skip records -- rather
        # than a second, subtly different policy. Channels a patient has not
        # opted into, or has no address for, are recorded as skips and not
        # counted as missing next time (skips are idempotent).
        report = scheduler.schedule_all_channels(
            user_id=user_id,
            appointment_id=appointment_id,
            correlation_id=correlation_id,
        )
        if report["queued"]:
            result["repaired"] += report["queued"]
            logger.warning(
                "appointment_reminders_repaired",
                extra={
                    "appointment": appointment_id,
                    "queued": report["queued"],
                    "expected": expected,
                    "found": existing,
                },
            )

    # Terminal appointments must not be holding open reminders. Only those
    # that still do are selected (one joined query), rather than every
    # terminal appointment ever, which grew without bound and ran hourly.
    with session_scope() as session:
        terminal = session.scalars(
            select(Appointment.id)
            .join(Notification, Notification.appointment_id == Appointment.id)
            .where(
                Appointment.status.in_([
                    EventStatus.CANCELLED, EventStatus.COMPLETED, EventStatus.MISSED,
                ]),
                Notification.status.in_(list(NotificationStatus.CLAIMABLE)),
            )
            .distinct()
        )
        for appointment_id in list(terminal):
            result["cancelled"] += cancel_for_appointment(appointment_id)
    return result


def _preference_offsets(user_id: str) -> Optional[str]:
    """The user's stored reminder offsets, or None if unset."""
    from dedan_platform import identity

    try:
        return identity.get_profile_payload(user_id)["preferences"].get("reminder_offsets")
    except Exception:
        logger.warning("preferences_unreadable", extra={"user": user_id})
        return None


def count_open_for_appointment(appointment_id: str) -> int:
    """How many reminders for this appointment are still deliverable."""
    with session_scope() as session:
        return int(session.scalar(
            select(func.count(Notification.id)).where(
                Notification.appointment_id == appointment_id,
                Notification.status.in_(list(NotificationStatus.CLAIMABLE)),
            )
        ) or 0)


def count_handled_for_appointment(appointment_id: str, channel: str) -> int:
    """Reminders on one channel that are deliverable or deliberately skipped.

    For reconciliation: a channel the patient opted out of, or has no
    address for, is fully handled, not missing.
    """
    with session_scope() as session:
        return int(session.scalar(
            select(func.count(Notification.id)).where(
                Notification.appointment_id == appointment_id,
                Notification.channel == channel,
                Notification.status.in_(
                    list(NotificationStatus.CLAIMABLE) + [NotificationStatus.SKIPPED]
                ),
            )
        ) or 0)
