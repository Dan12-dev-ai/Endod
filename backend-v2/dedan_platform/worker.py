"""
Notification worker (spec §16, §18).

Runs out-of-band from the request path. A single `run_once()` is the unit of
work; `worker_loop()` repeats it on a poll interval.

    run_once() -> claim_due_jobs() -> deliver -> mark_sent / mark_failed

Why the loop lives here and is env-gated
----------------------------------------
This repository built the whole queue -- atomic claim, exponential backoff,
stale-job recovery, idempotency keys -- and then never invoked it.
`run_once()` had no production caller, so reminders accumulated in the
`notifications` table and were never delivered. The deployed database held 52
PENDING reminders and 0 SENT.

The loop is gated by `NOTIFICATION_WORKER_ENABLED` (default off) because it
lives inside the FastAPI process: with multiple uvicorn workers each process
runs its own loop. That is safe for correctness -- claiming is an atomic
conditional UPDATE, so two workers cannot both take the same job -- but it does
mean delivery throughput scales with pod count. Deployments that run more than
one API replica should set this on exactly one process, or run the CLI in
`worker_main.py` instead.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from dedan_platform import notifications
from dedan_platform.email_provider import (
    EmailNotConfiguredError, EmailProviderError, build_provider, render_appointment_reminder,
)
from dedan_platform.models import NotificationChannel, NotificationStatus
from dedan_platform import sms_provider as sms

logger = logging.getLogger(__name__)


def _env_flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


#: Off by default: starting a delivery loop is an operational decision, and a
#: fresh checkout must not silently begin sending mail.
WORKER_ENABLED = _env_flag("NOTIFICATION_WORKER_ENABLED", False)
WORKER_POLL_INTERVAL = float(os.getenv("NOTIFICATION_WORKER_INTERVAL_SECONDS", "30"))
WORKER_BATCH_SIZE = int(os.getenv("NOTIFICATION_WORKER_BATCH_SIZE", "50"))
#: Run a reconciliation pass on worker start. Repairs appointments whose
#: reminders went missing (see `notifications.reconcile_appointments`).
WORKER_RECONCILE_ON_START = _env_flag("NOTIFICATION_RECONCILE_ON_START", True)
#: Reconciliation also repeats while running, so an appointment whose reminder
#: enqueue failed is repaired within this interval rather than at next restart.
WORKER_RECONCILE_INTERVAL = float(os.getenv("NOTIFICATION_RECONCILE_INTERVAL_SECONDS", "3600"))


def _stale_reason(job: Dict[str, Any]) -> Optional[str]:
    """Why a queued reminder must no longer be sent, or None.

    Checked immediately before every send, because things change between
    queueing and delivery: the patient may opt out or change the phone or
    email (which could now belong to someone else), and the appointment may
    have been cancelled or moved -- a job already being processed when that
    happened was not covered by the cancellation.
    """
    from sqlalchemy import select

    from dedan_platform import identity, scheduler
    from dedan_platform.db import ensure_aware, session_scope
    from dedan_platform.models import Appointment
    from dedan_platform.appointments import TERMINAL_STATUSES

    from dedan_platform import patient_sms

    if patient_sms.handles(job):
        # Booking decisions, refunds, follow-ups and queues: their own checks.
        return patient_sms.stale_reason(job)
    payload = job.get("payload") or {}
    appointment_id = job.get("appointment_id") or payload.get("appointment_id")
    if appointment_id:
        with session_scope() as session:
            row = session.execute(
                select(Appointment.status, Appointment.scheduled_at)
                .where(Appointment.id == appointment_id)
            ).first()
        if row is None or row.status in TERMINAL_STATUSES:
            return "appointment_inactive"
        queued_for = payload.get("scheduled_at")
        if queued_for and ensure_aware(row.scheduled_at) != datetime.fromisoformat(queued_for):
            return "appointment_time_changed"
    try:
        profile = identity.get_profile_payload(job["user_id"])
    except identity.UserNotFound:
        return "account_not_found"
    if scheduler.current_destination(job.get("channel", NotificationChannel.EMAIL), profile) != job.get("destination"):
        return "destination_changed_or_opted_out"
    return None


def _deliver_sms(job: Dict[str, Any], provider) -> str:
    attempt = job.get("attempts", 0) + 1
    try:
        from dedan_platform import patient_sms

        text = patient_sms.render(job) if patient_sms.handles(job) else sms.render_sms_reminder(job.get("payload") or {})
        message_id = provider.send(job["destination"], text)
    except sms.SmsProviderError as exc:
        return notifications.mark_failed(job["id"], str(exc), attempt)
    except Exception as exc:
        return notifications.mark_failed(job["id"], f"{type(exc).__name__}", attempt)
    notifications.mark_sent(job["id"], provider_message_id=message_id)
    return "SENT"


def deliver_one(job: Dict[str, Any], provider=None, sms_provider=None) -> str:
    """Attempt one job. Returns the resulting status.

    Separated from `run_once` so a test can drive a single job deterministically
    without racing the queue. ``provider`` sends email, ``sms_provider`` SMS.
    """
    channel = job.get("channel", NotificationChannel.EMAIL)
    if channel in (NotificationChannel.EMAIL, NotificationChannel.SMS):
        reason = _stale_reason(job)
        if reason:
            notifications.mark_skipped(job["id"], reason)
            return NotificationStatus.SKIPPED
    if channel == NotificationChannel.SMS:
        return _deliver_sms(job, sms_provider or sms.build_provider())
    if channel != NotificationChannel.EMAIL:
        # No transport for push/in-app yet. Never hand these to the email
        # provider, which would use a user id as an email address.
        notifications.mark_skipped(job["id"], f"channel_not_supported:{channel}")
        return NotificationStatus.SKIPPED

    provider = provider or build_provider()
    payload = job.get("payload") or {}
    attempt = job.get("attempts", 0) + 1
    try:
        rendered = render_appointment_reminder(
            payload, job["user_id"], payload.get("appointment_id", job.get("appointment_id") or "unknown"),
        )
        provider_message_id = provider.send(
            to_address=job["destination"],
            subject=rendered["subject"],
            body=rendered["body"],
            correlation_id=job.get("correlation_id"),
        )
    except EmailProviderError as exc:
        return notifications.mark_failed(job["id"], str(exc), attempt)
    except Exception as exc:
        return notifications.mark_failed(job["id"], f"{type(exc).__name__}", attempt)

    # A transport may return a provider-side reference. Recorded when present,
    # but never required: SMTP returns no id, and "SENT" means submitted to the
    # transport -- not confirmed delivered to a mailbox.
    notifications.mark_sent(job["id"], provider_message_id=provider_message_id)
    return "SENT"


def run_once(
    limit: int = 20,
    provider=None,
    now: Optional[datetime] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    sms_provider=None,
) -> Dict[str, int]:
    """Process up to ``limit`` due notifications.

    Returns per-status counts, which is the observability hook the spec asks for
    (`reminders_sent`, `email_failures`).

    Jobs are claimed **one at a time**, immediately before each send. Claiming
    the whole batch up front left later jobs sitting in PROCESSING while
    earlier sends ran; with a slow mail server that outlasted the stale
    threshold, another worker "recovered" them and both sent the reminder.

    `now` is injectable so an end-to-end test can advance a controllable clock to
    a reminder's due time instead of waiting 24 hours for it. `should_stop` is
    checked between jobs so shutdown never interrupts a send.
    """
    # Each channel is delivered only if its transport is configured; the
    # other channel's jobs are not claimed and wait in the queue. (A missing
    # mail server used to stop every reminder, including SMS.)
    # A channel this deployment does not use (REMINDER_CHANNELS, e.g. SMS
    # only) is not a blocked channel: no transport is built and nothing is
    # logged as an error for it.
    from dedan_platform import scheduler

    in_use = set(scheduler.reminder_channels())
    channels = []
    if provider is not None or NotificationChannel.EMAIL in in_use:
        try:
            provider = provider or build_provider()
            channels.append(NotificationChannel.EMAIL)
        except EmailNotConfiguredError as exc:
            logger.error("notification_delivery_blocked channel=email: %s", exc)
    if sms_provider is not None or NotificationChannel.SMS in in_use:
        try:
            sms_provider = sms_provider or sms.build_provider()
            channels.append(NotificationChannel.SMS)
        except sms.SmsNotConfiguredError as exc:
            logger.error("notification_delivery_blocked channel=sms: %s", exc)
    # Channels without a transport are claimed only to be closed as SKIPPED,
    # so they do not sit in the queue forever.
    channels.extend(
        c for c in NotificationChannel.ALL
        if c not in (NotificationChannel.EMAIL, NotificationChannel.SMS)
    )
    wanted = {NotificationChannel.EMAIL, NotificationChannel.SMS} & (in_use | set(channels))
    blocked = sum(c not in channels for c in wanted)
    if wanted and blocked == len(wanted):
        return {"claimed": 0, "recovered_stale": 0, "SENT": 0, "RETRYING": 0, "FAILED": 0,
                "blocked": 1}
    recovered = notifications.recover_stale_jobs(now=now)

    counts: Dict[str, int] = {"SENT": 0, "RETRYING": 0, "FAILED": 0}
    claimed = 0
    while claimed < limit and not (should_stop and should_stop()):
        jobs = notifications.claim_due_jobs(limit=1, now=now, channels=channels)
        if not jobs:
            break
        claimed += 1
        result = deliver_one(jobs[0], provider, sms_provider)
        counts[result] = counts.get(result, 0) + 1

    summary = {"claimed": claimed, "recovered_stale": recovered, **counts}
    if blocked:
        summary["blocked_channels"] = blocked
    logger.info("notification_batch_complete", extra=summary)
    return summary


def reconcile(now: Optional[datetime] = None) -> Dict[str, int]:
    """Repair reminder coverage. Safe to run on every worker start."""
    try:
        return notifications.reconcile_appointments(now=now)
    except Exception:
        # Reconciliation is a repair, never a precondition. A failure here must
        # not stop the worker from delivering reminders that are already due.
        logger.exception("notification_reconciliation_failed")
        return {"repaired": 0, "cancelled": 0, "examined": 0}


def queue_metrics() -> Dict[str, Any]:
    """Observability snapshot for the metrics the spec requires (§11).

    Emitted as a structured log line rather than exposed over HTTP: queue depth
    and failure rates are operational facts, and this platform has no role model
    that could gate an endpoint carrying them. A patient-facing notification API
    is a separate concern and lives in `api_notifications.py`, scoped to the
    caller's own rows.
    """
    depth = notifications.queue_depth()
    logger.info("notification_queue_metrics", extra={
        "pending": depth["pending"],
        "oldest_pending_seconds": depth["oldest_pending_seconds"],
        "sent": depth["by_status"].get("SENT", 0),
        "failed": depth["by_status"].get("FAILED", 0),
        "retrying": depth["by_status"].get("RETRYING", 0),
        "skipped": depth["by_status"].get("SKIPPED", 0),
        "cancelled": depth["by_status"].get("CANCELLED", 0),
    })
    return depth


async def worker_loop(stop_event: asyncio.Event, provider=None) -> None:
    """Poll for due jobs until `stop_event` is set.

    Runs the blocking database + SMTP work in a thread so one slow provider
    cannot stall the event loop and take the API's other requests down with it.
    """
    loop = asyncio.get_running_loop()
    last_reconcile = loop.time()
    if WORKER_RECONCILE_ON_START:
        await asyncio.to_thread(reconcile)
        logger.info("notification_worker_started", extra={
            "poll_interval": WORKER_POLL_INTERVAL,
            "batch_size": WORKER_BATCH_SIZE,
        })
    await asyncio.to_thread(queue_metrics)

    while not stop_event.is_set():
        try:
            if loop.time() - last_reconcile >= WORKER_RECONCILE_INTERVAL:
                await asyncio.to_thread(reconcile)
                last_reconcile = loop.time()
            summary = await asyncio.to_thread(
                run_once, WORKER_BATCH_SIZE, provider, None, stop_event.is_set
            )
            # Queue pressure is only meaningful when something is stuck, so it
            # is emitted on every pass and left to the log pipeline to alert on.
            await asyncio.to_thread(queue_metrics)
            if summary.get("FAILED"):
                logger.error("notification_failures_in_batch", extra=summary)
        except asyncio.CancelledError:
            raise
        except Exception:
            # A single failed pass must not kill the loop; the next tick retries
            # and the jobs themselves are still PENDING/RETRYING.
            logger.exception("notification_worker_pass_failed")

        try:
            # `wait_for` rather than `sleep` so shutdown is immediate instead
            # of taking up to one full poll interval.
            await asyncio.wait_for(stop_event.wait(), timeout=WORKER_POLL_INTERVAL)
        except asyncio.TimeoutError:
            continue
    logger.info("notification_worker_stopped")