"""The patient's history, follow-ups, queue places and shares; and the
hospital service's internal file endpoint.

* ``/users/me/history``: hospital records and self-reported visits.
* ``/users/me/history/records/{record_id}/files/{file_id}``: a record's file
  (the patient's own only).
* ``/users/me/follow-ups``, ``/users/me/queue``: upcoming follow-ups; today's
  queue places.
* ``/users/me/shares``: share records with a partner hospital, list, revoke.
* ``/internal/shares/{share_id}/files/{file_id}``: for the hospital service
  only, with ``X-Platform-Key``. Served by main_internal alone (its own
  service on the private network); the patient API does not mount it.
"""

from __future__ import annotations

import hmac
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from dedan_platform import history, partner_config, partners, shares
from dedan_platform.api_profile import current_user_id

router = APIRouter(tags=["history"])
internal_router = APIRouter(prefix="/internal", tags=["internal"], include_in_schema=False)

_HEX32 = re.compile(r"^[0-9a-f]{32}$")


def _file_response(path, content_type: str, filename: str, download: bool) -> FileResponse:
    # The name as the patient will see it, ASCII-safe for the plain parameter.
    ascii_name = re.sub(r"[^A-Za-z0-9._ -]", "_", filename)[:120] or "file"
    disposition = "attachment" if download else "inline"
    headers = {
        "Content-Disposition": f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    }
    if content_type.startswith("image/"):
        # Opened on its own, an image may not run or load anything. (Not for
        # PDFs: a sandboxed PDF does not open in the browser's viewer.)
        headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox"
    return FileResponse(path, media_type=content_type, headers=headers)


@router.get("/users/me/history")
def read_history(user_id: str = Depends(current_user_id)) -> Dict[str, Any]:
    return history.list_history(user_id)


@router.get("/users/me/history/records/{record_id}/files/{file_id}")
def read_record_file(record_id: str, file_id: str, download: bool = False,
                     user_id: str = Depends(current_user_id)) -> FileResponse:
    if not (_HEX32.match(record_id) and _HEX32.match(file_id)):
        raise HTTPException(status_code=404, detail="File not found.")
    found = history.file_for_patient(user_id, record_id, file_id)
    if found is None:
        raise HTTPException(status_code=404, detail="File not found.")
    return _file_response(*found, download=download)


@router.get("/users/me/follow-ups")
def read_follow_ups(user_id: str = Depends(current_user_id)) -> Dict[str, Any]:
    return {"follow_ups": history.upcoming_follow_ups(user_id)}


@router.get("/users/me/queue")
def read_queue(user_id: str = Depends(current_user_id)) -> Dict[str, Any]:
    return {"day": history.today(), "entries": history.today_queue(user_id)}


class ShareRequest(BaseModel):
    hospital_id: str = Field(min_length=1, max_length=32)
    record_ids: List[str] = Field(min_length=1, max_length=shares.MAX_RECORDS)
    expires_at: Optional[datetime] = None


@router.get("/users/me/shares/hospitals")
def share_hospitals(user_id: str = Depends(current_user_id)) -> Dict[str, Any]:
    """The partner hospitals records can be shared with."""
    return {"hospitals": sorted(({"hospital_id": h.id, "name": h.name, "name_am": h.name_am, "city": h.city}
                                 for h in partners.listed()), key=lambda h: h["name"].lower())}


@router.get("/users/me/shares")
def list_shares(user_id: str = Depends(current_user_id)) -> Dict[str, Any]:
    return {"shares": shares.list_for(user_id)}


@router.post("/users/me/shares", status_code=status.HTTP_201_CREATED)
def create_share(body: ShareRequest, user_id: str = Depends(current_user_id)) -> Dict[str, Any]:
    try:
        return shares.create(user_id, body.hospital_id, body.record_ids, body.expires_at)
    except shares.ShareError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.delete("/users/me/shares/{share_id}")
def revoke_share(share_id: str, user_id: str = Depends(current_user_id)) -> Dict[str, Any]:
    if not _HEX32.match(share_id):
        raise HTTPException(status_code=404, detail="Share not found.")
    try:
        return shares.revoke(user_id, share_id)
    except shares.ShareError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


# --- for the hospital service only ------------------------------------------------------------

def require_platform_key(x_platform_key: Optional[str] = Header(default=None)) -> None:
    """Constant-time check of ``X-Platform-Key``; refused outright when no key is set."""
    expected = partner_config.platform_admin_key()
    if not expected:
        raise HTTPException(status_code=503, detail="Not available.")
    if not x_platform_key or not hmac.compare_digest(x_platform_key.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Not authorised.")


@internal_router.get("/shares/{share_id}/files/{file_id}", dependencies=[Depends(require_platform_key)])
def shared_file(share_id: str, file_id: str) -> FileResponse:
    try:
        path, content_type, filename = shares.file_for_hospital(share_id, file_id)
    except shares.ShareAccessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return _file_response(path, content_type, filename, download=True)

