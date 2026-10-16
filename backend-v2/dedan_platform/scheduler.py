"""
Reminder scheduling policy (spec §2, §16, §18).

This is the single place that decides *which* reminders an appointment should
produce and *who* should receive them. It sits above the appointment service
(which owns the booking) and the notification queue (which owns delivery).

    Appointment Service
        -> Reminder Scheduler      (this module)
        -> Durable job rows        (notifications table)
        -> Notification Worker     (delivers, out of band)
        -> Notification Provider
        -> Delivery status + audit record

Why a separate module
---------------------
The reminder policy was previously spread across three files -- the appointment
service, the worker, and an inline re-query inside the HTTP handler -- and the
result was that three of its rules were dead code:

* the user's `reminder_offsets` preference was accepted by the API and then
  discarded (`reminder_offsets_for(stored, None)`);
* `email_notifications` was editable in the portal and read by nothing;
* a reschedule cancelled reminders and re-armed none.

Consolidating the policy here means the API handler and the reconciliation pass
derive identical jobs, so a repair cannot disagree with a booking.

Nothing in this module sends anything. It only writes job rows; delivery is the
worker's job, out of band, so a mail outage can never fail a booking.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from dedan_platform import appointments as appt
from dedan_platform import identity
from dedan_platform import notifications
from dedan_platform.models import (
    NotificationChannel, SKIP_REASON_NO_DESTINATION, SKIP_REASON_OPTED_OUT,
    SKIP_REASON_WINDOW_PASSED,
)

logger = logging.getLogger(__name__)

#: Maps a channel to the preference field that governs consent for it.
#:
#: Keyed by the `Preferences` column name rather than the channel string so a
#: mismatch between the two is a visible KeyError rather than a silent opt-out.
CHANNEL_PREFERENCE_FIELD = {
    NotificationChannel.EMAIL: "email_notifications",
    NotificationChannel.SMS: "sms_notifications",
    NotificationChannel.PUSH: "push_notifications",
}


def _load_appointment(user_id: str, appointment_id: str):
    """Fetch the ORM row so the stored policy is the one that is honoured."""
    from sqlalchemy import select

    from dedan_platform.db import session_scope
    from dedan_platform.models import Appointment

    with session_scope() as session:
        return session.scalar(
            select(Appointment).where(
                Appointment.id == appointment_id, Appointment.user_id == user_id
            )
        )


def schedule_reminders(
    user_id: str,
    appointment_id: str,
    correlation_id: Optional[str] = None,
    channel: str = NotificationChannel.EMAIL,
) -> Dict[str, Any]:
    """Derive and enqueue the reminders for one appointment.

    Returns a report rather than just a count, so an API caller can tell the
    difference between "queued", "already queued", "no open window" and
    "recipient opted out" -- four outcomes a single integer cannot distinguish.

    Idempotent: re-running against an unchanged appointment produces no new
    rows, so the reconciliation pass and the booking path can both call it.
    """
    appointment = _load_appointment(user_id, appointment_id)
    if appointment is None:
        raise appt.AppointmentError("Appointment not found.")

    if appointment.status in appt.TERMINAL_STATUSES:
        # A cancelled, completed or missed appointment must never gain a new
        # reminder. Suppression elsewhere stops reminders that already exist, but
        # nothing stopped a caller -- or a reconciliation pass -- from arming new
        # ones against an appointment that has already happened.
        logger.info(
            "reminders_refused_for_terminal_appointment",
            extra={"appointment": appointment_id, "status": appointment.status},
        )
        return {
            "queued": 0,
            "job_ids": [],
            "skipped": [{"reason": "appointment_terminal",
                         "status": appointment.status}],
            "offsets": [],
        }

    profile = identity.get_profile_payload(user_id)
    preferences = profile.get("preferences", {})
    offsets = appt.reminder_offsets_for(appointment, preferences.get("reminder_offsets"))
    # Every offset the policy asked for, so the ones whose window has already
    # closed can be recorded as SKIPPED rather than vanishing.
    policy_offsets = appt.parse_reminder_offsets(
        appointment.reminder_offsets or preferences.get("reminder_offsets")
    )
    closed = sorted(set(policy_offsets) - set(offsets))

    scheduled_at = appointment.scheduled_at
    if scheduled_at.tzinfo is None:
        # The row was written as UTC; SQLite hands it back naive.
        scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)

    opted_in = preferences.get(CHANNEL_PREFERENCE_FIELD.get(channel, ""), True)
    destination = _destination_for(channel, profile)

    if not opted_in:
        # Consent is explicit and wins over the reminder schedule. Recorded, not
        # silently dropped, so the patient can be told why they received nothing.
        for offset in offsets:
            notifications.record_opt_out_skip(
                user_id=user_id,
                appointment_id=appointment_id,
                offset=offset,
                channel=channel,
                correlation_id=correlation_id,
            )
        logger.info(
            "reminders_skipped_channel_opted_out",
            extra={"appointment": appointment_id, "channel": channel},
        )
        return {
            "queued": 0,
            "job_ids": [],
            "skipped": [{"reason": SKIP_REASON_OPTED_OUT, "channel": channel}],
            "offsets": offsets,
        }

    if not destination:
        for offset in offsets:
            notifications.record_no_destination_skip(
                user_id=user_id,
                appointment_id=appointment_id,
                offset=offset,
                channel=channel,
                scheduled_at=scheduled_at,
                correlation_id=correlation_id,
            )
        logger.info(
            "reminders_skipped_no_address",
            extra={"appointment": appointment_id, "channel": channel},
        )
        return {
            "queued": 0,
            "job_ids": [],
            "skipped": [{"reason": SKIP_REASON_NO_DESTINATION, "channel": channel}],
            "offsets": offsets,
        }

    # Record the windows that closed before this appointment was booked. This is
    # the record that answers "why did I not get a 24-hour reminder?" -- without
    # it a late booking is indistinguishable from a broken scheduler.
    for offset in closed:
        notifications.record_window_passed_skip(
            user_id=user_id,
            appointment_id=appointment_id,
            offset=offset,
            channel=channel,
            scheduled_at=scheduled_at,
            correlation_id=correlation_id,
        )

    outcome = notifications.enqueue_reminders(
        user_id=user_id,
        appointment_id=appointment_id,
        scheduled_at=scheduled_at,
        offsets=offsets,
        destination=destination,
        payload=_reminder_payload(appointment, scheduled_at),
        channel=channel,
        correlation_id=correlation_id,
    )
    skipped = [
        {"offset_seconds": offset, "reason": SKIP_REASON_WINDOW_PASSED}
        for offset in closed
    ] + outcome.skipped
    return {
        "queued": outcome.queued,
        "job_ids": outcome.created,
        "skipped": skipped,
        "offsets": offsets,
    }


def _destination_for(channel: str, profile: Dict[str, Any]) -> Optional[str]:
    """Resolve the real address for a channel from the authorized profile.

    Resolved per call rather than trusted from a request body, so a patient
    cannot be made to queue a reminder to an address they do not control.
    """
    if channel == NotificationChannel.EMAIL:
        return profile.get("email") or None
    if channel == NotificationChannel.SMS:
        # Only a phone the patient proved they hold: an unverified number may
        # be someone else's, and reminders would text a stranger.
        return profile.get("phone") if profile.get("phone_verified") else None
    if channel in (NotificationChannel.IN_APP, NotificationChannel.PUSH):
        # In-app and push need no external address; the recipient is the user id.
        return str(profile.get("internal_user_id") or "")
    return None


def _reminder_payload(appointment, scheduled_at: datetime) -> Dict[str, Any]:
    """Queue payload. Logistics only -- never clinical.

    The appointment type is included because it tells the patient what to
    prepare for; no condition, diagnosis or medication ever appears here, since
    this is rendered into an inbox and a lock-screen preview.
    """
    return {
        "appointment_id": appointment.id,
        "scheduled_at": scheduled_at.isoformat(),
        "appointment_type": appointment.appointment_type,
        "location": appointment.location,
        "meeting_url": appointment.meeting_url,
        "timezone": appointment.timezone,
    }


#: Channels reminders are scheduled on. Each honours its own preference and
#: is recorded as SKIPPED (with the reason) when it does not apply.
REMINDER_CHANNELS = (NotificationChannel.EMAIL, NotificationChannel.SMS)


def schedule_all_channels(
    user_id: str,
    appointment_id: str,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """`schedule_reminders` for every reminder channel, merged into one report."""
    merged: Dict[str, Any] = {"queued": 0, "job_ids": [], "skipped": [], "offsets": [], "channels": {}}
    for channel in REMINDER_CHANNELS:
        report = schedule_reminders(user_id, appointment_id, correlation_id=correlation_id, channel=channel)
        merged["queued"] += report.get("queued", 0)
        merged["job_ids"].extend(report.get("job_ids", []))
        merged["skipped"].extend(report.get("skipped", []))
        merged["offsets"] = merged["offsets"] or report.get("offsets", [])
        merged["channels"][channel] = report.get("queued", 0)
    return merged


def reschedule_reminders(
    user_id: str,
    appointment_id: str,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Re-arm reminders for an appointment that has just moved.

    Suppression of the old reminders happens inside
    `appointments.reschedule` (a safety invariant); re-arming happens here,
    because creating reminders is a policy action rather than a safety one.
    """
    return schedule_all_channels(user_id, appointment_id, correlation_id=correlation_id)