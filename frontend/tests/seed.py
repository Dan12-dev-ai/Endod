"""Test data the browser tests cannot create through the app (run from backend-v2).

    python seed.py partner              list the test partner hospital (as the hospital service would)
    python seed.py confirm <id> [room]  the hospital confirms a booking (a video one with a room)

Uses the same handlers as the event worker, against DEDAN_DATABASE_URL.
"""

import os
import sys

sys.path.insert(0, os.getcwd())

from dedan_platform import hospital_bookings, partners  # noqa: E402
from dedan_platform.db import create_all, session_scope  # noqa: E402

PARTNER_ID = "e2e0" * 8

LISTING = {
    "hospital_id": PARTNER_ID, "version": 1, "code": "E2EGH", "name": "Endod Test General Hospital",
    "name_am": "የእንዶድ መሞከሪያ ሆስፒታል", "kind": "private", "city": "Addis Ababa", "address": "Bole Road",
    "phone": "+251111234567", "ambulance_phone": "+251911000111", "emergency": True,
    "latitude": 8.9950, "longitude": 38.7890, "services": ["general_medicine", "emergency"],
    "open_hours": "24h", "timezone": "Africa/Addis_Ababa",
    "video_enabled": True, "price_in_person": 20000, "price_video": 12000,
}


def main(argv):
    create_all()
    deferred = []
    with session_scope() as session:
        if argv[0] == "partner":
            partners.on_listed(session, LISTING)
        elif argv[0] == "confirm":
            hospital_bookings.on_confirmed(session, {
                "appointment_id": argv[1], "hospital_id": PARTNER_ID, "status": "confirmed",
                "meeting_room": argv[2] if len(argv) > 2 else None, "doctor_name": "Dr. Hiwot Bekele",
            })
        else:
            raise SystemExit(f"unknown command {argv[0]!r}")
        deferred = list(session.info.get("after_commit", []))
    for action in deferred:
        action()


if __name__ == "__main__":
    main(sys.argv[1:])
