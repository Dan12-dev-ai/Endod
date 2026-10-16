"""`/users/me/records`: the patient's medical records (visits)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from dedan_platform import identity, records
from dedan_platform.api_profile import current_user_id

router = APIRouter(prefix="/users/me/records", tags=["records"])


class MedicationEntry(BaseModel):
    name: str
    dose: Optional[str] = None


class RecordRequest(BaseModel):
    occurred_at: datetime
    facility_name: str
    department: Optional[str] = None
    diagnosis: Optional[str] = None
    medications: List[Union[MedicationEntry, str]] = Field(default_factory=list)
    follow_up_days: Optional[int] = None
    follow_up_note: Optional[str] = None


@router.get("")
def list_records(
    limit: int = Query(default=100, ge=1, le=200),
    user_id: str = Depends(current_user_id),
) -> Dict[str, Any]:
    return records.list_records(user_id, limit)


@router.post("", status_code=status.HTTP_201_CREATED)
def add_record(body: RecordRequest, user_id: str = Depends(current_user_id)) -> Dict[str, Any]:
    """A visit the patient records themselves (shown as unverified).

    Health information, so it needs treatment consent, like the health profile.
    """
    if not identity.get_profile_payload(user_id)["consent"]["treatment_processing"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Consent to store health information is required.",
        )
    if body.occurred_at.tzinfo is None:
        raise HTTPException(status_code=400, detail="occurred_at must include a timezone offset.")
    payload = body.model_dump(exclude={"occurred_at"})
    payload["medications"] = [m.model_dump() if hasattr(m, "model_dump") else m for m in body.medications]
    try:
        return records.add_record(user_id, payload, body.occurred_at, source="patient")
    except records.RecordError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
