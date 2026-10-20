"""
Stage 2/3 API: timeline and appointments (spec §24).

Reuses the same `current_user_id` dependency as the profile API, so there is one
authorization implementation in the platform rather than one per module.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from dedan_platform import appointments as appt
from dedan_platform import scheduler
from dedan_platform import timeline as tl
from dedan_platform.api_profile import current_user_id

logger = logging.getLogger(__name__)

router = APIRouter(tags=["timeline", "appointments"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, tl.TimelineError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, appt.AppointmentNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, appt.AppointmentError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


# --- timeline ---------------------------------------------------------------

@router.get("/users/me/timeline")
def read_timeline(
    user_id: str = Depends(current_user_id),
    limit: int = Query(default=25, ge=1, le=100),
    cursor: Optional[str] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
    event_status: Optional[str] = Query(default=None, alias="status"),
    date_from: Optional[datetime] = Query(default=None),
    date_to: Optional[datetime] = Query(default=None),
) -> Dict[str, Any]:
    """Cursor-paginated timeline.

    `limit` is additionally capped inside the service, so an internal caller
    cannot bypass the ceiling the API advertises.
    """
    try:
        return tl.list_events(
            user_id=user_id, limit=limit, cursor=cursor, event_type=event_type,
            status=event_status, date_from=date_from, date_to=date_to,
        )
    except tl.TimelineError as exc:
        raise _error(exc) from exc


@router.get("/users/me/timeline/summary")
def read_timeline_summary(user_id: str = Depends(current_user_id)) -> Dict[str, Any]:
    return tl.summarise_timeline(user_id)


@router.get("/users/me/timeline/{event_id}")
def read_timeline_event(
    event_id: str, user_id: str = Depends(current_user_id)
) -> Dict[str, Any]:
    event = tl.get_event(user_id, event_id)
    if event is None:
        # 404 rather than 403: a wrong-owner request should not confirm that the
        # event exists somewhere.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found.")
    return event


@router.delete("/users/me/timeline/{event_id}")
def delete_timeline_event(
    event_id: str, user_id: str = Depends(current_user_id)
) -> Dict[str, Any]:
    try:
        deleted = tl.delete_event(user_id, event_id)
    except tl.ProtectedEventError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found.")
    return {"deleted": True, "event_id": event_id}


# --- appointments -----------------------------------------------------------

class AppointmentRequest(BaseModel):
    scheduled_at: datetime
    appointment_type: str = "consultation"
    provider_id: Optional[str] = None
    organization_id: Optional[str] = None
    duration_minutes: int = Field(default=30, ge=5, le=480)
    location: Optional[str] = None
    meeting_url: Optional[str] = None
    notes: Optional[str] = None
    timezone: str = "UTC"
    reminder_offsets: Optional[str] = None
    visit_mode: Optional[str] = Field(default=None, description="in_person | telehealth")
    department: Optional[str] = None
    time_window: Optional[str] = Field(default=None, description="exact | morning | afternoon | evening")
    facility_id: Optional[str] = Field(default=None, description="An id from /care/facilities")
    provider_name: Optional[str] = None


class StatusRequest(BaseModel):
    status: str


@router.get("/users/me/appointments")
def read_appointments(
    user_id: str = Depends(current_user_id),
    upcoming_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
) -> List[Dict[str, Any]]:
    return appt.list_appointments(user_id, upcoming_only=upcoming_only, limit=limit)


@router.post("/users/me/appointments", status_code=status.HTTP_201_CREATED)
def create_appointment(
    body: AppointmentRequest,
    request: Request,
    user_id: str = Depends(current_user_id),
) -> Dict[str, Any]:
    """Book an appointment and queue its reminders.

    No email is sent here: reminders are enqueued as jobs and delivered by the
    notification worker. Doing it synchronously would make a mail outage block
    a patient's booking.
    """
    from dedan_platform import hospital_bookings, partners, wallet

    if body.facility_id and partners.get(body.facility_id) is not None:
        # An Endod partner hospital: booked with the hospital and paid from
        # the patient's balance (hospital_bookings.py).
        try:
            result = hospital_bookings.book(
                user_id=user_id, hospital_id=body.facility_id, scheduled_at=body.scheduled_at,
                visit_mode=body.visit_mode, service=body.department, time_window=body.time_window,
                notes=body.notes, timezone_name=body.timezone if body.timezone != "UTC" else None,
                duration_minutes=body.duration_minutes,
                correlation_id=request.headers.get("X-Correlation-ID"),
            )
        except wallet.InsufficientFunds as exc:
            raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc)) from exc
        except appt.AppointmentError as exc:
            raise _error(exc) from exc
        # A video visit gets its reminders once a doctor approves it.
        queued = {"queued": 0, "job_ids": [], "skipped": [], "offsets": [], "channels": {}} if result["appointment"]["hospital_booking"]["state"] == "awaiting_doctor" else \
            scheduler.schedule_all_channels(
                user_id=user_id, appointment_id=result["appointment"]["appointment_id"],
                correlation_id=request.headers.get("X-Correlation-ID"),
            )
        return {**result, "reminders": queued}

    try:
        result = appt.create_appointment(
            user_id=user_id,
            scheduled_at=body.scheduled_at,
            appointment_type=body.appointment_type,
            provider_id=body.provider_id,
            organization_id=body.organization_id,
            duration_minutes=body.duration_minutes,
            location=body.location,
            meeting_url=body.meeting_url,
            notes=body.notes,
            timezone_name=body.timezone,
            reminder_offsets=body.reminder_offsets,
            correlation_id=request.headers.get("X-Correlation-ID"),
            visit_mode=body.visit_mode,
            department=body.department,
            time_window=body.time_window,
            facility_id=body.facility_id,
            provider_name=body.provider_name,
        )
    except appt.AppointmentError as exc:
        raise _error(exc) from exc

    # The scheduler re-derives offsets from the *stored* row and the user's
    # preferences, so the queue and the appointment can never disagree about
    # the reminder policy. This previously re-queried the row inline here and
    # passed `None` for preferences, which silently discarded the user's
    # configured reminder times.
    queued = scheduler.schedule_all_channels(
        user_id=user_id,
        appointment_id=result["appointment"]["appointment_id"],
        correlation_id=request.headers.get("X-Correlation-ID"),
    )
    return {**result, "reminders": queued}


@router.get("/users/me/appointments/{appointment_id}")
def read_appointment(
    appointment_id: str, user_id: str = Depends(current_user_id)
) -> Dict[str, Any]:
    appointment = appt.get_appointment(user_id, appointment_id)
    if appointment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found."
        )
    return appointment


@router.patch("/users/me/appointments/{appointment_id}/status")
def update_appointment_status(
    appointment_id: str,
    body: StatusRequest,
    request: Request,
    user_id: str = Depends(current_user_id),
) -> Dict[str, Any]:
    try:
        return appt.update_status(
            user_id, appointment_id, body.status,
            correlation_id=request.headers.get("X-Correlation-ID"),
        )
    except appt.AppointmentError as exc:
        raise _error(exc) from exc


@router.post("/users/me/appointments/{appointment_id}/reschedule")
def reschedule_appointment(
    appointment_id: str,
    body: AppointmentRequest,
    request: Request,
    user_id: str = Depends(current_user_id),
) -> Dict[str, Any]:
    """Move an appointment.

    Suppression of reminders for the old time happens inside the appointment
    service, so it cannot be bypassed by calling any other path. Re-arming for
    the new time is done here, and this handler previously cancelled without
    re-arming: a rescheduled appointment was told its new time and then heard
    nothing at all.
    """
    try:
        payload = appt.reschedule(
            user_id, appointment_id, body.scheduled_at,
            correlation_id=request.headers.get("X-Correlation-ID"),
            time_window=body.time_window,
        )
    except appt.AppointmentError as exc:
        raise _error(exc) from exc

    queued = scheduler.reschedule_reminders(
        user_id=user_id,
        appointment_id=appointment_id,
        correlation_id=request.headers.get("X-Correlation-ID"),
    )
    return {**payload, "reminders": queued}
