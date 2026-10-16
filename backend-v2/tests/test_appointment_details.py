"""Appointment details the booking screens need, and the facility browse list."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

PASSWORD = "Str0ng-pass!"
ADDIS = ZoneInfo("Africa/Addis_Ababa")


@pytest.fixture
def client(tmp_path, monkeypatch):
    from dedan_platform import db as dbmod
    from dedan_platform.api_auth import router as auth_router
    from dedan_platform.api_care import router as care_router
    from dedan_platform.api_health import router as health_router
    from dedan_platform.api_profile import router as profile_router

    monkeypatch.setenv("REALTIME_TOKEN_SECRET", "test-secret")
    monkeypatch.setenv("DEDAN_DATABASE_URL", f"sqlite:///{tmp_path / 'details.db'}")
    dbmod.reset_engine()
    dbmod.create_all()
    app = FastAPI()
    for router in (auth_router, profile_router, health_router, care_router):
        app.include_router(router)
    yield TestClient(app)
    dbmod.reset_engine()


@pytest.fixture
def auth(client):
    resp = client.post("/auth/register", json={
        "first_name": "A", "last_name": "B", "email": "a@example.com",
        "password": PASSWORD, "password_confirmation": PASSWORD,
    })
    return {"Authorization": resp.json()["access_token"]}


def local(hour, days=3):
    day = datetime.now(ADDIS) + timedelta(days=days)
    return day.replace(hour=hour, minute=30, second=0, microsecond=0).isoformat()


def book(client, auth, **body):
    return client.post("/users/me/appointments", headers=auth, json={
        "scheduled_at": local(10), "timezone": "Africa/Addis_Ababa", **body,
    })


class TestAppointmentDetails:
    def test_in_person_at_a_directory_facility(self, client, auth):
        resp = book(client, auth, facility_id="et-addis-black-lion", department="Cardiology",
                    time_window="morning", provider_name="Dr. Abebe Kebede")
        assert resp.status_code == 201, resp.text
        appt = resp.json()["appointment"]
        assert appt["visit_mode"] == "in_person"
        assert appt["facility"]["name"] == "Tikur Anbessa Specialized Hospital"
        assert appt["location"].startswith("Tikur Anbessa")  # filled from the directory
        assert (appt["department"], appt["time_window"], appt["provider_name"]) == (
            "Cardiology", "morning", "Dr. Abebe Kebede")
        listed = client.get("/users/me/appointments", headers=auth).json()[0]
        assert listed["facility"]["id"] == "et-addis-black-lion"

    def test_telehealth_from_a_meeting_link(self, client, auth):
        appt = book(client, auth, meeting_url="https://meet.example.com/x").json()["appointment"]
        assert appt["visit_mode"] == "telehealth" and appt["facility"] is None

    @pytest.mark.parametrize("body", [
        {"visit_mode": "home_visit"},
        {"visit_mode": "in_person", "meeting_url": "https://meet.example.com/x"},
        {"visit_mode": "telehealth", "facility_id": "et-addis-black-lion"},
        {"facility_id": "no-such-place"},
        {"time_window": "night"},
        {"time_window": "afternoon"},  # 10:30 local is not in the afternoon
        {"timezone": "Mars/Olympus"},
        {"department": "x" * 121},
    ])
    def test_inconsistent_bookings_are_400(self, client, auth, body):
        assert book(client, auth, **body).status_code == 400

    def test_window_is_checked_in_the_appointments_timezone(self, client, auth):
        # 10:30 in Addis Ababa is 07:30 UTC: morning there, not in UTC.
        assert book(client, auth, time_window="morning").status_code == 201

    def test_reschedule_keeps_or_resets_the_window(self, client, auth):
        appt = book(client, auth, time_window="morning").json()["appointment"]
        url = f"/users/me/appointments/{appt['appointment_id']}/reschedule"
        moved = client.post(url, headers=auth, json={"scheduled_at": local(9, days=4),
                                                     "timezone": "Africa/Addis_Ababa"}).json()
        assert moved["time_window"] == "morning"
        moved = client.post(url, headers=auth, json={"scheduled_at": local(15, days=5)}).json()
        assert moved["time_window"] == "exact"
        bad = client.post(url, headers=auth, json={"scheduled_at": local(15, days=6), "time_window": "morning"})
        assert bad.status_code == 400

    def test_rows_from_before_the_columns_still_read(self, client, auth):
        from sqlalchemy import update

        from dedan_platform.db import session_scope
        from dedan_platform.models import Appointment

        book(client, auth, meeting_url="https://meet.example.com/x")
        with session_scope() as session:
            session.execute(update(Appointment).values(visit_mode=None, time_window=None))
        appt = client.get("/users/me/appointments", headers=auth).json()[0]
        assert appt["visit_mode"] == "telehealth" and appt["time_window"] == "exact"


class TestFacilityBrowse:
    def test_filters(self, client, auth):
        body = client.get("/users/me/care/facilities?country=ET", headers=auth).json()
        assert body["total"] == 2 and {f["country"] for f in body["facilities"]} == {"ET"}
        assert all(f["distance_km"] is None for f in body["facilities"])
        assert body["location_used"] is False
        cardio = client.get("/users/me/care/facilities?department=cardiology", headers=auth).json()
        assert all("cardiology" in f["departments"] for f in cardio["facilities"])
        named = client.get("/users/me/care/facilities?q=anbessa", headers=auth).json()
        assert [f["id"] for f in named["facilities"]] == ["et-addis-black-lion"]

    def test_distance_needs_location(self, client, auth):
        assert client.get("/users/me/care/facilities?sort=distance", headers=auth).status_code == 400
        assert client.get("/users/me/care/facilities?latitude=9.0", headers=auth).status_code == 400
        body = client.get("/users/me/care/facilities?sort=distance&latitude=9.03&longitude=38.74",
                          headers=auth).json()
        assert body["location_used"] is True
        assert body["facilities"][0]["country"] == "ET"
        distances = [f["distance_km"] for f in body["facilities"]]
        assert distances == sorted(distances)

    def test_nothing_is_invented(self, client, auth):
        for facility in client.get("/users/me/care/facilities", headers=auth).json()["facilities"]:
            assert facility["website"] is None
            assert "rating" not in facility and "wait" not in facility

    def test_bad_department_is_400(self, client, auth):
        assert client.get("/users/me/care/facilities?department=astrology", headers=auth).status_code == 400

    def test_requires_sign_in(self, client):
        assert client.get("/users/me/care/facilities").status_code == 401


def test_legacy_invalid_timezone_can_still_be_rescheduled(client, auth):
    from sqlalchemy import update

    from dedan_platform.db import session_scope
    from dedan_platform.models import Appointment

    appt = book(client, auth).json()["appointment"]
    with session_scope() as session:
        session.execute(update(Appointment).values(timezone="EAT", time_window=None))
    resp = client.post(f"/users/me/appointments/{appt['appointment_id']}/reschedule",
                       headers=auth, json={"scheduled_at": local(11, days=4)})
    assert resp.status_code == 200, resp.text


def test_blank_city_filter_is_ignored(client, auth):
    body = client.get("/users/me/care/facilities", headers=auth, params={"city": " "}).json()
    assert body["total"] == 6
