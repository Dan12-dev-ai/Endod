"""The patient's history as the app shows it: hospital records and their own.

Everything here is scoped to the signed-in account in the query itself;
another patient's record or file id simply is not found. Retracted hospital
records, and files a correction dropped, never appear.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select

from dedan_platform import record_files
from dedan_platform.db import ensure_aware, session_scope
from dedan_platform.models import (
    FollowUp, HealthEvent, HealthEventType, HospitalRecord, QueueEntry, RecordFile, RecordFileStatus,
)

MAX_ITEMS = 1000
ZONE = ZoneInfo("Africa/Addis_Ababa")

#: How the app describes a file: ready to open, still arriving, or given up on.
_FILE_STATE = {
    RecordFileStatus.STORED: "ready",
    RecordFileStatus.PENDING: "arriving",
    RecordFileStatus.DOWNLOADING: "arriving",
    RecordFileStatus.FAILED: "unavailable",
}


def file_payload(row: RecordFile) -> Dict[str, Any]:
    return {"file_id": row.file_id, "filename": row.filename, "content_type": row.content_type,
            "size": row.size, "state": _FILE_STATE.get(row.status, "unavailable")}


def hospital_item(record: HospitalRecord, files: List[RecordFile]) -> Dict[str, Any]:
    return {
        "id": record.id, "kind": "hospital", "category": record.category, "title": record.title,
        "hospital_id": record.hospital_id, "hospital_name": record.hospital_name,
        "occurred_at": ensure_aware(record.occurred_at).isoformat(), "recorded_by": record.recorded_by,
        "verified": True, "source": record.source, "visit_id": record.visit_id, "version": record.version,
        "details": json.loads(record.details_json) if record.details_json else {},
        "files": [file_payload(f) for f in files if f.status != RecordFileStatus.REMOVED],
    }


def self_item(event: HealthEvent) -> Optional[Dict[str, Any]]:
    """A visit the patient recorded (records.py), or None for other consultation events."""
    from dedan_platform.records import VERIFIED_SOURCES

    try:
        metadata = json.loads(event.metadata_json) if event.metadata_json else {}
    except ValueError:
        return None
    record = metadata.get("record") if isinstance(metadata, dict) else None
    if not isinstance(record, dict):
        return None
    return {
        "id": event.id, "kind": "self", "category": "visit", "title": event.title,
        "hospital_id": None, "hospital_name": record.get("facility_name"),
        "occurred_at": ensure_aware(event.occurred_at).isoformat(), "recorded_by": None,
        "verified": event.source in VERIFIED_SOURCES, "source": event.source, "visit_id": None, "version": None,
        "details": {
            "department": record.get("department"), "diagnosis": record.get("diagnosis") or event.description,
            "medications": record.get("medications") or [], "follow_up_days": record.get("follow_up_days"),
            "follow_up_note": record.get("follow_up_note"),
        },
        "files": [],
    }


def list_history(user_id: str) -> Dict[str, Any]:
    """Every record, newest first (the app filters, searches and groups them)."""
    with session_scope() as session:
        records = list(session.scalars(select(HospitalRecord).where(
            HospitalRecord.user_id == user_id, HospitalRecord.retracted_at.is_(None),
        ).order_by(HospitalRecord.occurred_at.desc()).limit(MAX_ITEMS)))
        files: Dict[str, List[RecordFile]] = {}
        if records:
            # Sorted here: the stored filename is encrypted, so the database cannot order it.
            for row in sorted(session.scalars(select(RecordFile).where(
                    RecordFile.record_id.in_([r.id for r in records]), RecordFile.user_id == user_id)),
                    key=lambda f: (f.filename, f.file_id)):
                files.setdefault(row.record_id, []).append(row)
        items = [hospital_item(r, files.get(r.id, [])) for r in records]
        # A prescription's QR, code and what pharmacies have given (docs/pharmacy.md section 3).
        from dedan_platform import prescriptions

        dispensing = prescriptions.patient_views(session, records)
        for item in items:
            if item["category"] == "prescription":
                item["dispensing"] = dispensing.get(item["id"])
        for event in session.scalars(select(HealthEvent).where(
                HealthEvent.user_id == user_id, HealthEvent.event_type == HealthEventType.CONSULTATION,
        ).order_by(HealthEvent.occurred_at.desc()).limit(MAX_ITEMS)):
            item = self_item(event)
            if item:
                items.append(item)
    items.sort(key=lambda item: (item["occurred_at"], item["id"]), reverse=True)
    counts: Dict[str, int] = {}
    for item in items:
        counts[item["category"]] = counts.get(item["category"], 0) + 1
    hospitals = {item["hospital_name"].lower() for item in items if item["hospital_name"]}
    return {"items": items[:MAX_ITEMS], "summary": {
        "total": len(items), "verified": sum(1 for i in items if i["verified"]),
        "self_reported": sum(1 for i in items if i["kind"] == "self"),
        "hospitals": len(hospitals), "by_category": counts,
    }}


def file_for_patient(user_id: str, record_id: str, file_id: str) -> Optional[record_files.StoredFile]:
    """The patient's own stored file, or None."""
    with session_scope() as session:
        row = session.execute(select(RecordFile, HospitalRecord).join(
            HospitalRecord, HospitalRecord.id == RecordFile.record_id).where(
            RecordFile.record_id == record_id, RecordFile.file_id == file_id,
            RecordFile.status == RecordFileStatus.STORED,
            HospitalRecord.user_id == user_id, RecordFile.user_id == user_id,
            HospitalRecord.retracted_at.is_(None),
        )).first()
        if row is None:
            return None
        return record_files.stored_file(row[0])


def today() -> str:
    return datetime.now(ZONE).date().isoformat()


def upcoming_follow_ups(user_id: str) -> List[Dict[str, Any]]:
    """Follow-ups from today on, soonest first."""
    with session_scope() as session:
        rows = list(session.scalars(select(FollowUp).where(
            FollowUp.user_id == user_id, FollowUp.cancelled_at.is_(None), FollowUp.follow_up_on >= today(),
        ).order_by(FollowUp.follow_up_on)))
        return [{"follow_up_id": r.id, "hospital_id": r.hospital_id, "hospital_name": r.hospital_name,
                 "visit_id": r.visit_id, "follow_up_on": r.follow_up_on, "note": r.note,
                 "doctor_name": r.doctor_name} for r in rows]


def today_queue(user_id: str) -> List[Dict[str, Any]]:
    """The patient's places in today's queues (still waiting or called first)."""
    now_day = today()
    with session_scope() as session:
        rows = list(session.scalars(select(QueueEntry).where(
            QueueEntry.user_id == user_id, QueueEntry.day == now_day,
        )))
        entries = [{"entry_id": r.id, "hospital_id": r.hospital_id, "hospital_name": r.hospital_name,
                    "doctor_name": r.doctor_name, "day": r.day, "ticket": r.ticket, "status": r.status,
                    "ahead": r.ahead, "position": r.ahead + 1,
                    "updated_at": ensure_aware(r.updated_at).isoformat()}
                   for r in rows]
    order = {"called": 0, "waiting": 1}
    entries.sort(key=lambda e: (order.get(e["status"], 2), e["ticket"]))
    return entries
