"""Test data the browser tests cannot create through the app (run from backend-v2).

    python seed.py partner                         list the test partner hospital (as the hospital service would)
    python seed.py confirm <id> [room]             the hospital confirms a booking (a video one with a room)
    python seed.py records <dedan_id> <tag>        the hospital publishes records (titles end with <tag>),
                                                   then their files are downloaded from tests/fake-hospital.mjs
    python seed.py records-arriving <dedan_id> <tag>
                                                   the same, without downloading the files yet
    python seed.py download                        download the files that are due (the events worker's job)
    python seed.py follow-up <dedan_id> <date>     the hospital sets a follow-up on <date> (YYYY-MM-DD)
    python seed.py queue <dedan_id> <entry> <seq> <ahead> <status>
                                                   the patient's place in today's queue (Africa/Addis_Ababa)
    python seed.py prescription <dedan_id> <tag>   the hospital publishes a prescription ("Chest infection <tag>")
    python seed.py dispense <tag> <pharmacy> <amount>
                                                   a pharmacy gives <amount> of its first medicine
                                                   (as internal-api's /pharmacy/dispense does)

Uses the same handlers as the event worker, against DEDAN_DATABASE_URL. The
patient is linked to the test hospital first (the platform accepts nothing
about a patient from a hospital that has not linked them).
"""

import base64
import hashlib
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.getcwd())

from dedan_platform import hospital_bookings, partners, patient_history, prescriptions, record_files  # noqa: E402
from dedan_platform.db import create_all, session_scope  # noqa: E402

PARTNER_ID = "e2e0" * 8
PARTNER_NAME = "Endod Test General Hospital"

LISTING = {
    "hospital_id": PARTNER_ID, "version": 1, "code": "E2EGH", "name": PARTNER_NAME,
    "name_am": "የእንዶድ መሞከሪያ ሆስፒታል", "kind": "private", "city": "Addis Ababa", "address": "Bole Road",
    "phone": "+251111234567", "ambulance_phone": "+251911000111", "emergency": True,
    "latitude": 8.9950, "longitude": 38.7890, "services": ["general_medicine", "emergency"],
    "open_hours": "24h", "timezone": "Africa/Addis_Ababa",
    "video_enabled": True, "price_in_person": 20000, "price_video": 12000,
}

# The same bytes tests/fake-hospital.mjs serves (file ids starting with "a": the PNG).
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAEUlEQVR4nGMQaEjAihiGlgQAXiE8AWpkQeQAAAAASUVORK5CYII=")
PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
       b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")


def _file(body, content_type, filename):
    file_id = ("a" if content_type == "image/png" else "b") + uuid.uuid4().hex[1:]
    return {"file_id": file_id, "filename": filename, "content_type": content_type, "size": len(body),
            "sha256": hashlib.sha256(body).hexdigest()}


def _records(dedan, tag):
    now = datetime.now(timezone.utc)
    visit = uuid.uuid4().hex

    def record(category, title, details, days_ago, files=()):
        return {"record_id": uuid.uuid4().hex, "version": 1, "hospital_id": PARTNER_ID, "hospital_name": PARTNER_NAME,
                "dedan_id": dedan, "visit_id": visit, "category": category, "title": f"{title} {tag}",
                "details": details, "occurred_at": (now - timedelta(days=days_ago)).isoformat(),
                "recorded_by": "Dr. Hiwot Bekele", "source": "portal", "files": list(files)}

    return [
        record("lab_result", "Complete blood count", {
            "items": [{"test": "Hemoglobin", "value": "10.2", "unit": "g/dL", "reference_range": "12-16", "flag": "low"},
                      {"test": "Platelets", "value": "250", "unit": "10^9/L", "reference_range": "150-400",
                       "flag": "normal"}],
            "specimen": "Blood"}, 3, [_file(PNG, "image/png", "cbc-scan.png")]),
        record("prescription", "Malaria treatment", {
            "items": [{"drug": "Artemether-lumefantrine", "dose": "4 tablets", "route": "oral",
                       "frequency": "twice a day", "duration": "3 days", "quantity": "24"}]}, 3),
        record("diagnosis", "Malaria", {"condition": "Plasmodium falciparum malaria", "code": "B50.9",
                                        "status": "active"}, 3),
        record("imaging", "Chest X-ray", {"modality": "X-ray", "body_part": "Chest", "findings": "Clear lungs",
                                          "impression": "Normal chest"}, 40,
               [_file(PDF, "application/pdf", "chest-xray-report.pdf")]),
        record("visit_note", "Outpatient visit", {"complaint": "Fever for three days", "plan": "Treat and review",
                                                  "vitals": {"bp": "118/76", "temp": "38.4", "pulse": "96"}}, 3),
    ]


def _prescription(dedan, tag):
    return {"record_id": uuid.uuid4().hex, "version": 1, "hospital_id": PARTNER_ID, "hospital_name": PARTNER_NAME,
            "dedan_id": dedan, "visit_id": uuid.uuid4().hex, "category": "prescription",
            "title": f"Chest infection {tag}",
            "details": {"items": [
                {"drug": "Amoxicillin", "dose": "500 mg", "route": "oral", "frequency": "three times a day",
                 "duration": "7 days", "quantity": "21 tablets"},
                {"drug": "Paracetamol syrup", "dose": "10 ml", "quantity": "1 bottle"}]},
            "occurred_at": datetime.now(timezone.utc).isoformat(), "recorded_by": "Dr. Hiwot Bekele",
            "source": "portal", "files": []}


def _dispense(tag, pharmacy, amount):
    from sqlalchemy import select

    from dedan_platform.models import HospitalRecord, Prescription

    with session_scope() as session:
        rx_id = session.scalar(select(Prescription.id).join(HospitalRecord, HospitalRecord.id == Prescription.record_id)
                               .where(HospitalRecord.title == f"Chest infection {tag}"))
    prescriptions.dispense(rx_id, pharmacy_name=pharmacy, pharmacist_name=None,
                           items=[{"item_index": 0, "amount": float(amount), "complete": False}])


def _link(session, dedan):
    user = patient_history._user_by_dedan(session, dedan)
    if user is not None:
        patient_history.link_booking(session, user.id, PARTNER_ID)


def main(argv):
    create_all()
    deferred = []
    with session_scope() as session:
        if argv[0] in ("records", "records-arriving", "follow-up", "queue", "prescription"):
            _link(session, argv[1])
        if argv[0] in ("download", "dispense"):
            pass
        elif argv[0] == "prescription":
            patient_history.on_record_published(session, _prescription(argv[1], argv[2]))
        elif argv[0] == "partner":
            partners.on_listed(session, LISTING)
        elif argv[0] == "confirm":
            hospital_bookings.on_confirmed(session, {
                "appointment_id": argv[1], "hospital_id": PARTNER_ID, "status": "confirmed",
                "meeting_room": argv[2] if len(argv) > 2 else None, "doctor_name": "Dr. Hiwot Bekele",
            })
        elif argv[0] in ("records", "records-arriving"):
            for payload in _records(argv[1], argv[2]):
                patient_history.on_record_published(session, payload)
        elif argv[0] == "follow-up":
            patient_history.on_follow_up(session, {
                "visit_id": uuid.uuid4().hex, "hospital_id": PARTNER_ID, "hospital_name": PARTNER_NAME,
                "dedan_id": argv[1], "follow_up_on": argv[2], "note": "Bring your lab results",
                "doctor_name": "Dr. Hiwot Bekele", "cancelled": False,
            })
        elif argv[0] == "queue":
            _dedan, entry, seq, ahead, status = argv[1:6]
            patient_history.on_queue_updated(session, {
                "entry_id": entry, "hospital_id": PARTNER_ID, "hospital_name": PARTNER_NAME,
                "doctor_name": "Dr. Hiwot Bekele", "day": datetime.now(ZoneInfo("Africa/Addis_Ababa")).date().isoformat(),
                "ticket": 17, "status": status, "ahead": int(ahead), "dedan_id": _dedan, "phone": None,
                "patient_name": "Test Patient", "notify": None, "seq": int(seq),
            })
        else:
            raise SystemExit(f"unknown command {argv[0]!r}")
        deferred = list(session.info.get("after_commit", []))
    for action in deferred:
        action()
    if argv[0] == "dispense":
        _dispense(argv[1], argv[2], argv[3])
    if argv[0] in ("records", "download"):
        # What the events worker's download thread does.
        record_files.download_due()


if __name__ == "__main__":
    main(sys.argv[1:])
