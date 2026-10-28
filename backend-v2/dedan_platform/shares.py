"""Records a patient shares with a partner hospital (docs/history-events.md, section 5).

The patient picks records (from hospitals, or their own) and a listed partner
hospital, optionally until a date. One transaction stores the share and
queues ``records.shared`` (a copy of those records for the hospital); revoking
it, or its expiry (found by the events worker), queues ``records.unshared``
and the hospital deletes its copy.

The hospital service fetches shared files on demand from
``GET /internal/shares/{share_id}/files/{file_id}`` (``X-Platform-Key``):
only files of hospital records in that share, still the patient's, not
retracted, and only while the share is live.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from dedan_platform import eventbus, partners, record_files
from dedan_platform.db import ensure_aware, ensure_utc, session_scope
from dedan_platform.models import (
    HealthEvent, HealthEventType, HospitalRecord, Profile, RecordFile, RecordFileStatus, RecordShare,
    RecordShareItem, User, utcnow,
)

_ID = re.compile(r"^[0-9a-f]{32}$")
MAX_RECORDS = 100
MAX_DAYS = 366
SELF_REPORTED = "Self-reported"


class ShareError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _hospital_entry(record: HospitalRecord, files: List[RecordFile]) -> Dict[str, Any]:
    return {
        "record_id": record.id, "origin": record.hospital_name, "category": record.category,
        "title": record.title, "details": json.loads(record.details_json) if record.details_json else {},
        "occurred_at": ensure_aware(record.occurred_at).isoformat(), "recorded_by": record.recorded_by,
        "files": [{"file_id": f.file_id, "filename": f.filename, "content_type": f.content_type,
                   "size": f.size, "sha256": f.sha256}
                  for f in files if f.status != RecordFileStatus.REMOVED],
    }


def _self_entry(event: HealthEvent) -> Optional[Dict[str, Any]]:
    """A self-reported visit, as a ``visit_note`` (its own keys ride along; the
    hospital ignores what it does not know)."""
    try:
        record = (json.loads(event.metadata_json or "{}") or {}).get("record")
    except ValueError:
        return None
    if not isinstance(record, dict):
        return None
    medicines = ", ".join(" ".join(p for p in (m.get("name"), m.get("dose")) if p)
                          for m in record.get("medications") or [] if isinstance(m, dict))
    findings = "; ".join(p for p in (
        f"Diagnosis: {record['diagnosis']}" if record.get("diagnosis") else None,
        f"Medicines: {medicines}" if medicines else None,
    ) if p) or None
    plan = None
    if record.get("follow_up_days"):
        plan = f"Follow-up in {record['follow_up_days']} days" + (
            f": {record['follow_up_note']}" if record.get("follow_up_note") else "")
    return {
        "record_id": event.id, "origin": SELF_REPORTED, "category": "visit_note",
        "title": f"Visit: {record.get('facility_name') or event.title}"[:200],
        "details": {"complaint": None, "findings": findings, "plan": plan, "vitals": {},
                    "facility_name": record.get("facility_name"), "department": record.get("department"),
                    "diagnosis": record.get("diagnosis"), "medications": record.get("medications") or []},
        "occurred_at": ensure_aware(event.occurred_at).isoformat(), "recorded_by": None, "files": [],
    }


def _resolve(session: Session, user_id: str, record_id: str) -> Tuple[str, Dict[str, Any]]:
    """("hospital" | "self", the record as shared), for the patient's own record only."""
    record = session.scalar(select(HospitalRecord).where(
        HospitalRecord.id == record_id, HospitalRecord.user_id == user_id, HospitalRecord.retracted_at.is_(None)))
    if record is not None:
        # Sorted here: the stored filename is encrypted, so the database cannot order it.
        files = sorted(session.scalars(select(RecordFile).where(
            RecordFile.record_id == record.id, RecordFile.user_id == user_id)), key=lambda f: (f.filename, f.file_id))
        return "hospital", _hospital_entry(record, files)
    event = session.scalar(select(HealthEvent).where(
        HealthEvent.id == record_id, HealthEvent.user_id == user_id,
        HealthEvent.event_type == HealthEventType.CONSULTATION))
    entry = _self_entry(event) if event is not None else None
    if entry is None:
        raise ShareError("One of the chosen records was not found.", 404)
    return "self", entry


def _status(share: RecordShare, now: datetime) -> str:
    if share.revoked_at is not None:
        return "revoked"
    if share.unshared_at is not None or (share.expires_at is not None and ensure_aware(share.expires_at) <= now):
        return "expired"
    return "active"


def create(user_id: str, hospital_id: str, record_ids: List[str], expires_at: Optional[datetime]) -> Dict[str, Any]:
    hospital = partners.get(hospital_id)
    if hospital is None:
        raise ShareError("Records can only be shared with an Endod partner hospital.")
    ids = list(dict.fromkeys(record_ids))
    if not ids or len(ids) > MAX_RECORDS:
        raise ShareError(f"Choose from 1 to {MAX_RECORDS} records.")
    if any(not _ID.match(i or "") for i in ids):
        raise ShareError("A record id is not valid.")
    now = utcnow()
    if expires_at is not None:
        if expires_at.tzinfo is None:
            raise ShareError("expires_at needs a UTC offset.")
        if expires_at <= now + timedelta(minutes=5):
            raise ShareError("The end of sharing must be in the future.")
        if expires_at > now + timedelta(days=MAX_DAYS):
            raise ShareError("Sharing can last at most a year.")
    with session_scope() as session:
        user = session.get(User, user_id)
        profile = session.scalar(select(Profile).where(Profile.user_id == user_id))
        resolved = [_resolve(session, user_id, record_id) for record_id in ids]
        share = RecordShare(user_id=user_id, hospital_id=hospital.id, hospital_name=hospital.name,
                            expires_at=ensure_utc(expires_at) if expires_at else None, created_at=now)
        session.add(share)
        session.flush()
        for kind, entry in resolved:
            session.add(RecordShareItem(share_id=share.id, kind=kind, record_id=entry["record_id"]))
        names = [getattr(profile, p, None) for p in ("first_name", "middle_name", "last_name")] if profile else []
        eventbus.emit(session, "records.shared", {
            "share_id": share.id, "hospital_id": hospital.id, "dedan_id": user.dedan_user_id,
            "patient_name": (" ".join(n for n in names if n) or getattr(profile, "display_name", None)
                             or user.dedan_user_id)[:160],
            "expires_at": share.expires_at.isoformat() if share.expires_at else None,
            "records": [entry for _kind, entry in resolved],
        })
        session.flush()
        return _payload(share, [(k, e["record_id"], e["title"]) for k, e in resolved], now)


def _payload(share: RecordShare, records: List[Tuple[str, str, str]], now: datetime) -> Dict[str, Any]:
    return {
        "share_id": share.id, "hospital_id": share.hospital_id, "hospital_name": share.hospital_name,
        "created_at": ensure_aware(share.created_at).isoformat(),
        "expires_at": ensure_aware(share.expires_at).isoformat() if share.expires_at else None,
        "status": _status(share, now), "record_count": len(records),
        "records": [{"record_id": r, "kind": k, "title": t} for k, r, t in records],
    }


def list_for(user_id: str) -> List[Dict[str, Any]]:
    now = utcnow()
    with session_scope() as session:
        shares = list(session.scalars(select(RecordShare).where(RecordShare.user_id == user_id)
                                      .order_by(RecordShare.created_at.desc()).limit(200)))
        out = []
        for share in shares:
            items = list(session.scalars(select(RecordShareItem).where(RecordShareItem.share_id == share.id)))
            titles: Dict[str, str] = {}
            hospital_ids = [i.record_id for i in items if i.kind == "hospital"]
            self_ids = [i.record_id for i in items if i.kind == "self"]
            # Whole rows, not columns: titles are stored encrypted and decrypted on load.
            if hospital_ids:
                titles.update({r.id: r.title for r in session.scalars(select(HospitalRecord).where(
                    HospitalRecord.id.in_(hospital_ids), HospitalRecord.user_id == user_id))})
            if self_ids:
                titles.update({e.id: e.title for e in session.scalars(select(HealthEvent).where(
                    HealthEvent.id.in_(self_ids), HealthEvent.user_id == user_id))})
            out.append(_payload(share, [(i.kind, i.record_id, titles.get(i.record_id, "")) for i in items], now))
        return out


def _unshare(session: Session, share: RecordShare) -> None:
    share.unshared_at = utcnow()
    eventbus.emit(session, "records.unshared", {"share_id": share.id, "hospital_id": share.hospital_id})


def revoke(user_id: str, share_id: str) -> Dict[str, Any]:
    with session_scope() as session:
        share = session.scalar(select(RecordShare).where(
            RecordShare.id == share_id, RecordShare.user_id == user_id).with_for_update())
        if share is None:
            raise ShareError("Share not found.", 404)
        if share.revoked_at is None and share.unshared_at is None:
            share.revoked_at = utcnow()
            _unshare(session, share)
        elif share.revoked_at is None:
            share.revoked_at = utcnow()  # already expired: nothing more to tell the hospital
        session.flush()
        return {"share_id": share.id, "status": "revoked"}


def expire_due(limit: int = 100) -> int:
    """Unshare shares whose end has come (the events worker runs this)."""
    now = utcnow()
    with session_scope() as session:
        ids = list(session.scalars(select(RecordShare.id).where(
            RecordShare.unshared_at.is_(None), RecordShare.expires_at.is_not(None), RecordShare.expires_at <= now,
        ).limit(limit)))
    count = 0
    for share_id in ids:
        with session_scope() as session:
            share = session.get(RecordShare, share_id, with_for_update=True)
            if share is None or share.unshared_at is not None:
                continue
            _unshare(session, share)
            count += 1
    return count


class ShareAccessError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def file_for_hospital(share_id: str, file_id: str) -> record_files.StoredFile:
    """A file in a live share, for the hospital service."""
    if not (_ID.match(share_id or "") and _ID.match(file_id or "")):
        raise ShareAccessError(404, "Not found.")
    now = utcnow()
    with session_scope() as session:
        share = session.get(RecordShare, share_id)
        if share is None:
            raise ShareAccessError(404, "Not found.")
        if _status(share, now) != "active":
            raise ShareAccessError(410, "This share has ended.")
        row = session.execute(select(RecordFile).join(HospitalRecord, HospitalRecord.id == RecordFile.record_id)
                              .join(RecordShareItem, RecordShareItem.record_id == HospitalRecord.id).where(
            RecordShareItem.share_id == share.id, RecordShareItem.kind == "hospital",
            RecordFile.file_id == file_id, RecordFile.status != RecordFileStatus.REMOVED,
            RecordFile.user_id == share.user_id, HospitalRecord.user_id == share.user_id,
            HospitalRecord.retracted_at.is_(None),
        )).scalars().first()
        if row is None:
            raise ShareAccessError(404, "Not found.")
        if row.status != RecordFileStatus.STORED:
            raise ShareAccessError(503, "The file has not reached Endod yet.")
        stored = record_files.stored_file(row)
    if stored is None:
        raise ShareAccessError(503, "The file has not reached Endod yet.")
    return stored

