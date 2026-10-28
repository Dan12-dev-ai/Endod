"""
Care navigation + doctor handoff API (consultation continuation).

Reuses `current_user_id` from the profile API so there is exactly one
authorization implementation in the platform. There is deliberately no route
that accepts a user id: a patient can only ever reach their own records.

Two rules enforced here rather than in the client
-------------------------------------------------
* **Location is permission-gated.** Coordinates arrive only after the patient
  explicitly grants geolocation. A request without them still works and ranks by
  clinical relevance alone, and says so in `location_used`.
* **Sharing requires the fingerprint the patient reviewed.** The client echoes
  back the fingerprint of the summary it displayed; a mismatch is refused.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from dedan_platform import care_navigation as cn
from dedan_platform import handoff as ho
from dedan_platform import identity
from dedan_platform.api_profile import current_user_id
from dedan_platform.models import EventStatus, HealthEventType
from dedan_platform.timeline import record_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users/me", tags=["care-navigation", "handoff"])


# --- care navigation --------------------------------------------------------

class CareSearchRequest(BaseModel):
    symptoms: List[str] = Field(default_factory=list, max_length=40)
    urgency: str = "routine"
    is_emergency: bool = False
    language: str = "en"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    query: Optional[str] = Field(default=None, max_length=120)
    #: ISO country code to search in (e.g. "ET"); all countries when omitted.
    country: Optional[str] = Field(default=None, min_length=2, max_length=2)
    limit: int = Field(default=5, ge=1, le=20)
    #: Set by the client only when the patient granted geolocation. Informational
    #: for the audit trail; the coordinates themselves are the evidence.
    location_granted: bool = False


@router.post("/care/facilities")
def search_facilities(
    body: CareSearchRequest,
    user_id: str = Depends(current_user_id),
) -> Dict[str, Any]:
    """Rank real facilities for this consultation."""
    # Coordinates without an explicit grant are treated as absent. A client that
    # sends both and claims `location_granted: false` gets relevance-only
    # ranking rather than the precise result -- the flag is not trusted over the
    # operator's own consent flow.
    latitude = body.latitude if (body.location_granted and body.latitude is not None) else None
    longitude = body.longitude if (body.location_granted and body.longitude is not None) else None

    context = cn.ClinicalContext(
        symptoms=body.symptoms,
        is_emergency=body.is_emergency,
        urgency=body.urgency,
        language=body.language,
    )
    try:
        return cn.search(
            context,
            latitude=latitude,
            longitude=longitude,
            limit=body.limit,
            query=body.query,
            country=body.country,
        )
    except cn.CareNavigationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/care/facilities")
def browse_facilities(
    country: Optional[str] = Query(default=None, min_length=2, max_length=2),
    city: Optional[str] = Query(default=None, max_length=100),
    department: Optional[str] = None,
    emergency_only: bool = False,
    q: Optional[str] = Query(default=None, max_length=120),
    latitude: Optional[float] = Query(default=None, ge=-90, le=90),
    longitude: Optional[float] = Query(default=None, ge=-180, le=180),
    sort: str = "name",
    limit: int = Query(default=50, ge=1, le=100),
    user_id: str = Depends(current_user_id),
) -> Dict[str, Any]:
    """Browse the facility directory (the booking screen's hospital list).

    Coordinates are optional and only sent once the patient has shared their
    location; without them there is no distance and no distance sort.
    """
    if (latitude is None) != (longitude is None):
        raise HTTPException(status_code=400, detail="Send both latitude and longitude, or neither.")
    try:
        return cn.browse(
            country=country, city=city, department=department, emergency_only=emergency_only,
            query=q, latitude=latitude, longitude=longitude, sort=sort, limit=limit,
        )
    except cn.CareNavigationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/care/facilities/{facility_id}")
def read_facility(facility_id: str, user_id: str = Depends(current_user_id)) -> Dict[str, Any]:
    facility = cn.get_facility(facility_id)
    if facility is None:
        # 404 rather than 403: a wrong-owner request must not confirm the
        # facility exists elsewhere.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Facility not found.")
    return facility.to_payload()


@router.get("/care/facilities/{facility_id}/availability")
def read_availability(
    facility_id: str,
    on_date: Optional[str] = None,
    user_id: str = Depends(current_user_id),
) -> Dict[str, Any]:
    """Real availability, or an honest statement that there is none.

    Never fabricates a slot: see `care_navigation.slots_for`.
    """
    facility = cn.get_facility(facility_id)
    if facility is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Facility not found.")
    return cn.slots_for(facility, on_date=on_date)


# --- care navigation events -------------------------------------------------

class CareNavigationRecord(BaseModel):
    facility_id: Optional[str] = None
    facility_name: Optional[str] = None
    appointment_id: Optional[str] = None
    symptoms: List[str] = Field(default_factory=list, max_length=40)
    urgency: str = "routine"
    is_emergency: bool = False
    reason: Optional[str] = Field(default=None, max_length=200)


@router.post("/care/navigation", status_code=status.HTTP_201_CREATED)
def record_care_navigation(
    body: CareNavigationRecord,
    request: Request,
    user_id: str = Depends(current_user_id),
) -> Dict[str, Any]:
    """Record that DEDAN routed this patient toward care.

    Written as a `SAFETY_ALERT` when the consultation escalated and as
    `CARE_NAVIGATION` otherwise. A red flag that produced no navigation record
    would be invisible in the patient's history, which is precisely the case a
    reviewer needs to see.
    """
    event_type = (
        HealthEventType.SAFETY_ALERT if body.is_emergency
        else HealthEventType.CARE_NAVIGATION
    )
    title = "Urgent care recommended" if body.is_emergency else "Care navigation"
    description = body.facility_name or body.reason or "DEDAN recommended professional care."

    try:
        return record_event(
            user_id=user_id,
            event_type=event_type,
            title=title,
            description=description,
            status=EventStatus.COMPLETED if not body.is_emergency else EventStatus.SCHEDULED,
            source="dedan",
            correlation_id=request.headers.get("X-Correlation-ID"),
            metadata={
                "facility_id": body.facility_id,
                "facility_name": body.facility_name,
                "appointment_id": body.appointment_id,
                "urgency": body.urgency,
                "symptom_count": len(body.symptoms),
            },
        )
    except ValueError as exc:
        # Input problems only. Anything else is a server fault: it goes to the
        # generic 500 handler instead of echoing internal (database) errors.
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --- doctor handoff ---------------------------------------------------------

class HandoffRequest(BaseModel):
    main_concern: str = Field(default="", max_length=400)
    patient_statements: List[str] = Field(default_factory=list, max_length=40)
    allergies: List[str] = Field(default_factory=list, max_length=40)
    medications: List[str] = Field(default_factory=list, max_length=40)
    relevant_context: List[str] = Field(default_factory=list, max_length=20)
    safety_findings: List[str] = Field(default_factory=list, max_length=20)
    possible_causes: List[str] = Field(default_factory=list, max_length=20)
    clinician_questions: List[str] = Field(default_factory=list, max_length=20)
    onset: Optional[str] = Field(default=None, max_length=120)
    severity: Optional[str] = Field(default=None, max_length=40)
    language: str = "en"


def _require_consent(user_id: str, kind: str, detail: str) -> None:
    """403 unless the patient has granted ``kind`` consent.

    Same rule `/users/me/health-profile` enforces: without it, health details
    must not be stored (or shared) through a side door.
    """
    if not identity.get_profile_payload(user_id)["consent"].get(kind):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


@router.post("/handoff/summary", status_code=status.HTTP_201_CREATED)
def create_handoff_summary(
    body: HandoffRequest,
    user_id: str = Depends(current_user_id),
) -> Dict[str, Any]:
    """Build the clinician-facing summary and record the patient's review.

    The response carries `fingerprint`. Nothing is transmitted to any clinician at
    this point -- the patient must read it first, then approve it explicitly.
    """
    # The summary (allergies, medications, main concern) is stored on the
    # timeline, so it needs the same consent as the health profile.
    _require_consent(user_id, "treatment_processing", "Consent to store health information is required.")
    try:
        summary = ho.build_summary(
            main_concern=body.main_concern,
            patient_statements=body.patient_statements,
            allergies=body.allergies,
            medications=body.medications,
            relevant_context=body.relevant_context,
            safety_findings=body.safety_findings,
            possible_causes=body.possible_causes,
            clinician_questions=body.clinician_questions,
            onset=body.onset,
            severity=body.severity,
        )
    except ho.HandoffError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    approved = ho.approve(summary)
    explanation = ho.patient_explanation(summary, language=body.language)

    record_event(
        user_id=user_id,
        event_type=HealthEventType.DOCUMENT,
        title="Visit summary prepared",
        description=summary.main_concern,
        status=EventStatus.COMPLETED,
        source="dedan",
        metadata={
            "handoff_id": approved["handoff_id"],
            "is_shared": False,
            "fingerprint": approved["fingerprint"],
            # The full payload is stored so `share` can re-verify the
            # fingerprint against *our* copy. Verifying against a
            # client-supplied summary would make the consent check theatre: a
            # client could send any content plus a matching hash.
            "summary": approved["summary"],
        },
    )
    return {**approved, "patient_explanation": explanation}


def _prepared_handoff(user_id: str, handoff_id: str) -> Optional[Dict[str, Any]]:
    """The "summary prepared" event for this handoff, however old.

    Looked up directly rather than in a recent page of the timeline (which
    missed older summaries), and only the prepared event, which carries the
    fingerprint -- not a later "shared" event for the same handoff.
    """
    from dedan_platform.db import session_scope
    from dedan_platform.timeline import _to_payload, events_with_metadata

    with session_scope() as session:
        # Matched after decryption: the metadata is stored encrypted.
        rows = events_with_metadata(session, user_id, HealthEventType.DOCUMENT, "handoff_id", handoff_id)
        events = [_to_payload(row) for row in rows]
    return next(
        (
            e for e in events
            if e["metadata"].get("handoff_id") == handoff_id and e["metadata"].get("fingerprint")
        ),
        None,
    )


class HandoffShareRequest(BaseModel):
    handoff_id: str = Field(..., pattern=r"^[0-9a-f]{32}$")
    fingerprint: str = Field(default="", max_length=128)


@router.post("/handoff/share")
def share_handoff(
    body: HandoffShareRequest,
    request: Request,
    user_id: str = Depends(current_user_id),
) -> Dict[str, Any]:
    """Approve sharing -- gated on the fingerprint the patient actually read."""
    if not body.fingerprint:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sharing requires explicit patient approval.",
        )
    _require_consent(
        user_id,
        "data_sharing_with_clinicians",
        "Consent to share your information with clinicians is required.",
    )

    stored = _prepared_handoff(user_id, body.handoff_id)
    if stored is None:
        # 404, not 403: do not confirm that someone else's handoff exists.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Handoff not found.")

    try:
        shared = ho.share(
            {
                "handoff_id": body.handoff_id,
                "fingerprint": stored["metadata"].get("fingerprint", ""),
                "summary": stored["metadata"].get("summary", {}),
            },
            body.fingerprint,
        )
    except ho.HandoffError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    record_event(
        user_id=user_id,
        event_type=HealthEventType.DOCUMENT,
        title="Visit summary shared with care team",
        description=f"Handoff {body.handoff_id} approved and shared.",
        status=EventStatus.COMPLETED,
        source="dedan",
        correlation_id=request.headers.get("X-Correlation-ID"),
        metadata={"handoff_id": body.handoff_id, "is_shared": True},
    )
    return {
        "handoff_id": shared["handoff_id"],
        "is_shared": True,
        "shared_at": shared["shared_at"],
        "disclaimer": ho.AI_SUMMARY_DISCLAIMER,
    }
