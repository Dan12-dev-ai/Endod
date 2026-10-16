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


def test_completed_appointment_becomes_a_verified_record(client, auth):
    from dedan_platform import appointments, identity

    user = identity.find_user_by_email("a@example.com")
    when = datetime.now(timezone.utc) + timedelta(days=2)
    appointment = appointments.create_appointment(
        user.id, scheduled_at=when, location="Yekatit 12 Hospital")["appointment"]
    appointments.update_status(user.id, appointment["appointment_id"], "CONFIRMED")
    appointments.update_status(user.id, appointment["appointment_id"], "COMPLETED")
    record = client.get("/users/me/records", headers=auth).json()["records"][0]
    assert record["facility_name"] == "Yekatit 12 Hospital" and record["verified"] is True


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
