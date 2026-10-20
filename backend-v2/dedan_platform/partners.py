"""Endod partner hospitals: the platform's copy of their listings.

The hospital service announces each approved hospital with a full snapshot
(``hospital.listed``) and withdraws it with ``hospital.unlisted``; each carries
a rising ``version``, so a late, older announcement never overwrites a newer
one. The copy lives here so patients can browse, book and call an ambulance
even while the hospital service is unreachable.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from dedan_platform.db import session_scope
from dedan_platform.eventbus import PermanentEventError
from dedan_platform.models import PartnerHospital, utcnow

OWNERSHIP = ("public", "private")


class Listing(BaseModel):
    hospital_id: str = Field(min_length=1, max_length=32)
    version: int = Field(ge=0, strict=True)
    code: str = Field(min_length=1, max_length=12)
    name: str = Field(min_length=1, max_length=160)
    name_am: Optional[str] = Field(default=None, max_length=160)
    kind: str = "public"
    city: Optional[str] = Field(default=None, max_length=100)
    address: Optional[str] = Field(default=None, max_length=200)
    phone: Optional[str] = Field(default=None, max_length=20)
    ambulance_phone: Optional[str] = Field(default=None, max_length=20)
    emergency: bool = False
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    services: List[str] = Field(default_factory=list, max_length=20)
    open_hours: Optional[str] = Field(default=None, max_length=80)
    timezone: str = Field(default="Africa/Addis_Ababa", max_length=64)
    video_enabled: bool = False
    #: Santim, whole numbers.
    price_in_person: int = Field(ge=0, strict=True)
    price_video: Optional[int] = Field(default=None, ge=0, strict=True)


class Unlisting(BaseModel):
    hospital_id: str = Field(min_length=1, max_length=32)
    version: int = Field(ge=0, strict=True)


def _parse(model, payload: Dict[str, Any]):
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise PermanentEventError(str(exc).splitlines()[0]) from exc


def on_listed(session: Session, payload: Dict[str, Any]) -> None:
    from dedan_platform.care_navigation import DEPARTMENTS

    listing = _parse(Listing, payload)
    row = session.get(PartnerHospital, listing.hospital_id, with_for_update=True)
    if row is not None and row.version >= listing.version:
        return  # an older announcement arriving late
    if row is None:
        row = PartnerHospital(id=listing.hospital_id)
        session.add(row)
    row.version = listing.version
    row.code = listing.code
    row.name = listing.name
    row.name_am = listing.name_am
    row.ownership = listing.kind if listing.kind in OWNERSHIP else "public"
    row.city, row.address = listing.city, listing.address
    row.phone, row.ambulance_phone = listing.phone, listing.ambulance_phone
    row.emergency = listing.emergency
    row.latitude, row.longitude = listing.latitude, listing.longitude
    row.services = ",".join(s for s in dict.fromkeys(listing.services) if s in DEPARTMENTS) or None
    row.open_hours = listing.open_hours
    row.timezone = listing.timezone
    row.price_in_person = listing.price_in_person
    row.price_video = listing.price_video
    row.video_enabled = listing.video_enabled and listing.price_video is not None
    row.listed = True
    row.updated_at = utcnow()


def on_unlisted(session: Session, payload: Dict[str, Any]) -> None:
    unlisting = _parse(Unlisting, payload)
    row = session.get(PartnerHospital, unlisting.hospital_id, with_for_update=True)
    if row is None or row.version >= unlisting.version:
        return
    row.version = unlisting.version
    row.listed = False
    row.updated_at = utcnow()


def listed() -> List[PartnerHospital]:
    with session_scope() as session:
        return list(session.scalars(select(PartnerHospital).where(PartnerHospital.listed.is_(True))))


def get(hospital_id: Optional[str], listed_only: bool = True) -> Optional[PartnerHospital]:
    if not hospital_id:
        return None
    with session_scope() as session:
        row = session.get(PartnerHospital, hospital_id)
        if row is None or (listed_only and not row.listed):
            return None
        return row
