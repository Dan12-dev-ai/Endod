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
from typing import Any, Dict, Optional

from dedan_platform import notifications
from dedan_platform.email_provider import (
    EmailProviderError, build_provider, render_appointment_reminder,
)

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


def schedule_appointment_reminders(
    user_id: str,
    appointment_id: str,
    scheduled_at: "datetime | str",
    offsets,
    email_address: Optional[str],
    appointment_type: str = "consultation",
    location: Optional[str] = None,
    meeting_url: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Queue the reminders for an appointment. Called by the appointment service.

    Accepts `scheduled_at` as a datetime or an ISO string, because the
    appointment API returns serialised payloads and callers naturally pass those
    straight through. Requiring one type here would have pushed a needless
    re-parse onto every caller.

    Deliberately returns rather than sends: this is what keeps email out of the
    request path.

    The production path is `scheduler.schedule_reminders`, which derives offsets
    from stored preferences rather than from arguments. This function stays for
    callers that already know their offsets.
    """
    if isinstance(scheduled_at, str):
        # A naive ISO string is rejected for the same reason `create_appointment`
        # rejects a naive datetime: it would be silently read as UTC.
        scheduled_at = datetime.fromisoformat(scheduled_at)
        if scheduled_at.tzinfo is None:
            raise ValueError("scheduled_at must include a timezone offset.")
    if not email_address:
        logger.info("reminders_skipped_no_address", extra={"appointment": appointment_id})
        return {"queued": 0, "job_ids": [], "skipped": [
            {"reason": "no_consented_destination"}]}

    # Payloads are logistics-only. The appointment type is included because it
    # tells the patient what to prepare for; no condition or diagnosis ever is.
    payload = {
        "appointment_id": appointment_id,
        "scheduled_at": scheduled_at.isoformat(),
        "appointment_type": appointment_type,
        "location": location,
        "meeting_url": meeting_url,
    }
    outcome = notifications.enqueue_reminders(
        user_id=user_id,
        appointment_id=appointment_id,
        scheduled_at=scheduled_at,
        offsets=list(offsets),
        destination=email_address,
        payload=payload,
        correlation_id=correlation_id,
    )
    return {"queued": outcome.queued, "job_ids": outcome.created, "skipped": outcome.skipped}


def deliver_one(job: Dict[str, Any], provider=None) -> str:
    """Attempt one job. Returns the resulting status.

    Separated from `run_once` so a test can drive a single job deterministically
    without racing the queue.
    """
    provider = provider or build_provider()
    payload = job.get("payload") or {}
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
        status = notifications.mark_failed(job["id"], str(exc), job.get("attempts", 0) + 1)
        return status
    except Exception as exc:
        status = notifications.mark_failed(
            job["id"], f"{type(exc).__name__}", job.get("attempts", 0) + 1
        )
        return status

    # A transport may return a provider-side reference. Recorded when present,
    # but never required: SMTP returns no id, and "SENT" means submitted to the
    # transport -- not confirmed delivered to a mailbox.
    notifications.mark_sent(job["id"], provider_message_id=provider_message_id)
    return "SENT"


def run_once(limit: int = 20, provider=None, now: Optional[datetime] = None) -> Dict[str, int]:
    """Process one batch of due notifications.

    Returns per-status counts, which is the observability hook the spec asks for
    (`reminders_sent`, `email_failures`).

    `now` is injectable so an end-to-end test can advance a controllable clock to
    a reminder's due time instead of waiting 24 hours for it.
    """
    provider = provider or build_provider()
    recovered = notifications.recover_stale_jobs(now=now)
    jobs = notifications.claim_due_jobs(limit=limit, now=now)

    counts: Dict[str, int] = {"SENT": 0, "RETRYING": 0, "FAILED": 0}
    for job in jobs:
        result = deliver_one(job, provider)
        counts[result] = counts.get(result, 0) + 1

    summary = {"claimed": len(jobs), "recovered_stale": recovered, **counts}
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
    if WORKER_RECONCILE_ON_START:
        await asyncio.to_thread(reconcile)
        logger.info("notification_worker_started", extra={
            "poll_interval": WORKER_POLL_INTERVAL,
            "batch_size": WORKER_BATCH_SIZE,
        })
    await asyncio.to_thread(queue_metrics)

    while not stop_event.is_set():
        try:
            summary = await asyncio.to_thread(run_once, WORKER_BATCH_SIZE, provider)
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