"""Medical records for the Next.js records screen."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

PASSWORD = "Str0ng-pass!"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from dedan_platform import db as dbmod
    from dedan_platform.api_auth import router as auth_router
    from dedan_platform.api_profile import router as profile_router
    from dedan_platform.api_records import router as records_router

    monkeypatch.setenv("REALTIME_TOKEN_SECRET", "test-secret")
    monkeypatch.setenv("DEDAN_DATABASE_URL", f"sqlite:///{tmp_path / 'records.db'}")
    dbmod.reset_engine()
    dbmod.create_all()
    app = FastAPI()
    for router in (auth_router, profile_router, records_router):
        app.include_router(router)
    yield TestClient(app)
    dbmod.reset_engine()


@pytest.fixture
def auth(client):
    token = client.post("/auth/register", json={
        "first_name": "A", "last_name": "B", "email": "a@example.com",
        "password": PASSWORD, "password_confirmation": PASSWORD,
    }).json()["access_token"]
    headers = {"Authorization": token}
    client.patch("/users/me/consent", headers=headers, json={"treatment_processing": True})
    return headers


def visit(days_ago=10, **extra):
    return {
        "occurred_at": (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(),
        "facility_name": "St. Paul's Hospital", "department": "Cardiology",
        "diagnosis": "High blood pressure",
        "medications": [{"name": "Amlodipine", "dose": "5 mg"}],
        "follow_up_days": 30, "follow_up_note": "Check blood pressure",
        **extra,
    }


def test_add_and_list_with_summary(client, auth):
    assert client.post("/users/me/records", headers=auth, json=visit()).status_code == 201
    client.post("/users/me/records", headers=auth, json=visit(
        days_ago=100, facility_name="Black Lion Hospital", medications=["Paracetamol"], follow_up_days=None))
    body = client.get("/users/me/records", headers=auth).json()
    first = body["records"][0]
    assert first["facility_name"] == "St. Paul's Hospital"
    assert first["medications"] == [{"name": "Amlodipine", "dose": "5 mg"}]
    assert first["verified"] is False  # entered by the patient
    assert body["summary"] == {
        "total_visits": 2, "verified_records": 0, "facilities_visited": 2,
        "medications_used": 2, "active_follow_ups": 1,
    }


def test_completed_appointment_becomes_an_unverified_record(client, auth):
    from dedan_platform import appointments, identity

    user = identity.find_user_by_email("a@example.com")
    when = datetime.now(timezone.utc) + timedelta(days=2)
    appointment = appointments.create_appointment(
        user.id, scheduled_at=when, location="Yekatit 12 Hospital")["appointment"]
    appointments.update_status(user.id, appointment["appointment_id"], "CONFIRMED")
    appointments.update_status(user.id, appointment["appointment_id"], "COMPLETED")
    record = client.get("/users/me/records", headers=auth).json()["records"][0]
    assert record["facility_name"] == "Yekatit 12 Hospital"
    # The patient completed their own booking and typed its place: not verified.
    assert record["verified"] is False and record["source"] == "appointment"


def test_only_trusted_sources_are_verified(client, auth):
    from datetime import datetime as dt

    from dedan_platform import identity, records

    user = identity.find_user_by_email("a@example.com")
    records.add_record(user.id, {"facility_name": "Tikur Anbessa"},
                       dt.now(timezone.utc) - timedelta(days=1), source="clinician")
    body = client.get("/users/me/records", headers=auth).json()
    assert body["records"][0]["verified"] is True
    assert body["summary"]["verified_records"] == 1


def test_consultation_events_without_a_record_are_not_records(client, auth):
    from dedan_platform import identity
    from dedan_platform.models import EventStatus, HealthEventType
    from dedan_platform.timeline import record_event

    user = identity.find_user_by_email("a@example.com")
    # The shape older appointment completions were stored with.
    record_event(user_id=user.id, event_type=HealthEventType.CONSULTATION,
                 title="Consultation completed", status=EventStatus.COMPLETED,
                 source="dedan", metadata={"appointment_id": "a-1"})
    body = client.get("/users/me/records", headers=auth).json()
    assert body["records"] == [] and body["summary"]["total_visits"] == 0


def test_summary_covers_all_records_not_just_the_page(client, auth):
    for i, place in enumerate(("A Clinic", "B Clinic", "C Clinic")):
        assert client.post("/users/me/records", headers=auth,
                           json=visit(days_ago=10 + i, facility_name=place)).status_code == 201
    body = client.get("/users/me/records?limit=1", headers=auth).json()
    assert len(body["records"]) == 1
    assert body["summary"]["total_visits"] == 3 and body["summary"]["facilities_visited"] == 3


@pytest.mark.parametrize("when", ["0001-01-01T00:30:00+01:00", "1850-06-01T10:00:00+00:00"])
def test_implausible_dates_are_rejected(client, auth, when):
    payload = visit()
    payload["occurred_at"] = when
    assert client.post("/users/me/records", headers=auth, json=payload).status_code == 400


def test_requires_consent(client):
    token = client.post("/auth/register", json={
        "first_name": "C", "last_name": "D", "email": "c@example.com",
        "password": PASSWORD, "password_confirmation": PASSWORD,
    }).json()["access_token"]
    assert client.post("/users/me/records", headers={"Authorization": token}, json=visit()).status_code == 403


@pytest.mark.parametrize("change", [
    {"facility_name": ""}, {"follow_up_days": 0}, {"follow_up_days": 5000},
    {"medications": [{"dose": "5 mg"}]}, {"diagnosis": "x" * 301},
])
def test_invalid_records_are_rejected(client, auth, change):
    assert client.post("/users/me/records", headers=auth, json=visit(**change)).status_code in (400, 422)


def test_future_visits_are_not_records(client, auth):
    assert client.post("/users/me/records", headers=auth, json=visit(days_ago=-3)).status_code == 400


def test_records_are_private(client, auth):
    client.post("/users/me/records", headers=auth, json=visit())
    other = client.post("/auth/register", json={
        "first_name": "E", "last_name": "F", "email": "e@example.com",
        "password": PASSWORD, "password_confirmation": PASSWORD,
    }).json()["access_token"]
    assert client.get("/users/me/records", headers={"Authorization": other}).json()["records"] == []
