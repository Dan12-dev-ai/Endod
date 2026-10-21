"""Clinics and hospitals signing up to Endod: texts about their demo call.

The hospital service sends ``onboarding.demo_booked`` on ``endod:hospital``
when a facility books (or moves) a demo during sign-up:

``{"hospital_id", "booking_id" (32 hex), "contact_name", "phone" (E.164),
"demo_at" (ISO-8601 with an offset), "hospital_name", "changed": bool}``

The contact is texted once per booking and time, in Amharic then English,
with the time in Addis Ababa. The text goes through the notification queue
(``patient_sms``), so it is retried, and its key makes a redelivered or
repeated event harmless. The contact has no Endod account: the text goes to
the number given, like a walk-in's. A number that is not an Ethiopian mobile
is skipped. A malformed event is dead-lettered.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy.orm import Session

from dedan_platform import patient_sms
from dedan_platform.eventbus import PermanentEventError
from dedan_platform.phone import mask, normalise_ethiopian_mobile

logger = logging.getLogger(__name__)

ADDIS_ABABA = ZoneInfo("Africa/Addis_Ababa")
#: ``notifications.user_id`` for a facility's contact (no account).
CONTACT = "facility-contact"

_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class DemoBooked(BaseModel):
    hospital_id: str = Field(min_length=1, max_length=32)
    booking_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    contact_name: str = Field(min_length=1, max_length=160)
    phone: str = Field(min_length=1, max_length=32)
    demo_at: datetime
    hospital_name: str = Field(min_length=1, max_length=120)
    changed: bool = Field(strict=True)

    @field_validator("demo_at")
    @classmethod
    def _with_offset(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("demo_at needs a UTC offset")
        return value

    @field_validator("hospital_name", "contact_name")
    @classmethod
    def _one_line(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("blank")
        return value


def when_text(demo_at: datetime) -> Dict[str, str]:
    """The demo's time in Addis Ababa: "Tue 28 Oct, 10:30" (and 28/10/2026 in Amharic)."""
    local = demo_at.astimezone(ADDIS_ABABA)
    return {
        "en": f"{_DAYS[local.weekday()]} {local.day} {_MONTHS[local.month - 1]}, {local:%H:%M}",
        "am": f"{local:%d/%m/%Y} {local:%H:%M}",
    }


def on_demo_booked(session: Session, payload: Dict[str, Any]) -> None:
    try:
        event = DemoBooked.model_validate(payload)
    except ValidationError as exc:
        raise PermanentEventError(f"onboarding.demo_booked: {exc.errors()[0].get('loc')}") from exc
    phone = normalise_ethiopian_mobile(event.phone)
    if phone is None:
        logger.info("demo_sms_skipped booking=%s reason=invalid_phone", event.booking_id)
        return
    if not patient_sms.sms_in_use():
        return
    demo_utc = event.demo_at.astimezone(timezone.utc)
    prefix = f"sms:demo:{event.booking_id}:"
    key = f"{prefix}{demo_utc:%Y%m%dT%H%M%SZ}"
    # A text for an earlier time, not sent yet, must not go out after the move.
    patient_sms.cancel_prefix(session, prefix, keep_key=key)
    template = patient_sms.DEMO_MOVED if event.changed else patient_sms.DEMO_BOOKED
    params = {"booking_id": event.booking_id, "hospital": event.hospital_name, "when": when_text(event.demo_at)}
    if patient_sms.enqueue(session, user_id=CONTACT, destination=phone, template=template, key=key,
                           params=params, walk_in=True):
        logger.info("demo_sms_queued booking=%s phone=%s", event.booking_id, mask(phone))


HANDLERS = {
    "onboarding.demo_booked": on_demo_booked,
}
