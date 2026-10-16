"""Fixes found while documenting the API for the Next.js frontend."""

import base64
import io
from datetime import datetime, timedelta, timezone

import pytest

PASSWORD = "Str0ng-pass!"


@pytest.fixture
def auth(client, tmp_path, monkeypatch):
    from dedan_platform import db as dbmod

    monkeypatch.setenv("REALTIME_TOKEN_SECRET", "test-secret")
    monkeypatch.setenv("DEDAN_DATABASE_URL", f"sqlite:///{tmp_path / 'hardening.db'}")
    dbmod.reset_engine()
    dbmod.create_all()
    token = client.post("/auth/register", json={
        "first_name": "A", "last_name": "B", "email": "a@example.com",
        "password": PASSWORD, "password_confirmation": PASSWORD,
    }).json()["access_token"]
    yield {"Authorization": token}
    dbmod.reset_engine()


def _png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (400, 400), (200, 120, 90)).save(buf, format="PNG")
    return buf.getvalue()


def _book(client, auth, days=3):
    when = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    return client.post("/users/me/appointments", headers=auth, json={"scheduled_at": when}).json()["appointment"]


def test_cors_allows_patch_and_correlation_header():
    from fastapi.testclient import TestClient

    import main_clinical
    from app.core.config import get_settings

    settings = get_settings().model_copy(update={"CORS_ORIGINS": ["http://localhost:3000"]})
    resp = TestClient(main_clinical.create_app(settings)).options("/users/me", headers={
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "PATCH",
        "Access-Control-Request-Headers": "authorization,content-type,x-correlation-id",
    })
    assert resp.status_code == 200
    assert "PATCH" in resp.headers["access-control-allow-methods"]
    assert "x-correlation-id" in resp.headers["access-control-allow-headers"].lower()


@pytest.mark.parametrize("value", ["false", "true", 1, None])
def test_consent_takes_only_booleans(client, auth, value):
    resp = client.patch("/users/me/consent", headers=auth, json={"treatment_processing": value})
    assert resp.status_code in (400, 422)
    assert client.get("/users/me/consent", headers=auth).json()["treatment_processing"] is False


def test_http_error_headers_survive():
    import asyncio

    from fastapi import HTTPException

    import main_clinical

    handler = main_clinical.app.exception_handlers[HTTPException]
    resp = asyncio.run(handler(None, HTTPException(status_code=429, detail="Slow down",
                                                   headers={"Retry-After": "30"})))
    assert resp.status_code == 429 and resp.headers["retry-after"] == "30"


def test_base64_upload_accepts_data_urls_and_hides_internals(client):
    data_url = "data:image/png;base64," + base64.b64encode(_png()).decode()
    resp = client.post("/api/images/upload-base64",
                       json={"image_data": data_url, "session_id": "s-1", "filename": "rash.png"})
    assert resp.status_code == 200, resp.text
    image_id = resp.json()["image_id"]
    meta = client.get(f"/api/images/{image_id}").json()
    assert meta["image_id"] == image_id and meta["original_filename"] == "rash.png"
    assert not {"stored_filename", "content_hash", "session_id"} & set(meta)


def test_bad_base64_is_400(client):
    assert client.post("/api/images/upload-base64", json={"image_data": "%%%not base64%%%"}).status_code == 400


def test_facility_detail_requires_sign_in(client, auth):
    assert client.get("/users/me/care/facilities/et-addis-black-lion").status_code == 401
    assert client.get("/users/me/care/facilities/et-addis-black-lion", headers=auth).status_code == 200


def test_missing_appointment_is_404_everywhere(client, auth):
    when = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    assert client.patch("/users/me/appointments/nope/status", headers=auth,
                        json={"status": "CANCELLED"}).status_code == 404
    assert client.post("/users/me/appointments/nope/reschedule", headers=auth,
                       json={"scheduled_at": when}).status_code == 404


def test_rescheduled_status_needs_the_reschedule_endpoint(client, auth):
    appt = _book(client, auth)
    resp = client.patch(f"/users/me/appointments/{appt['appointment_id']}/status", headers=auth,
                        json={"status": "RESCHEDULED"})
    assert resp.status_code == 400 and "reschedule" in resp.text.lower()


def test_upcoming_is_soonest_first_and_skips_missed(client, auth):
    later = _book(client, auth, days=6)
    sooner = _book(client, auth, days=2)
    missed = _book(client, auth, days=4)
    client.patch(f"/users/me/appointments/{missed['appointment_id']}/status", headers=auth,
                 json={"status": "MISSED"})
    ids = [a["appointment_id"] for a in client.get("/users/me/appointments?upcoming_only=true",
                                                    headers=auth).json()]
    assert ids == [sooner["appointment_id"], later["appointment_id"]]


def test_completed_record_uses_the_booked_department(client, auth):
    when = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    appt = client.post("/users/me/appointments", headers=auth, json={
        "scheduled_at": when, "department": "Cardiology", "location": "Yekatit 12 Hospital",
    }).json()["appointment"]
    url = f"/users/me/appointments/{appt['appointment_id']}/status"
    client.patch(url, headers=auth, json={"status": "CONFIRMED"})
    client.patch(url, headers=auth, json={"status": "COMPLETED"})
    record = client.get("/users/me/records", headers=auth).json()["records"][0]
    assert record["department"] == "Cardiology"


def test_static_assets_are_not_rate_limited():
    from starlette.requests import Request

    from app.core.security import RateLimitMiddleware

    middleware = RateLimitMiddleware(app=None)

    def req(method, path):
        return Request({"type": "http", "method": method, "path": path, "headers": [], "query_string": b""})

    assert middleware._is_exempt(req("GET", "/assets/app.js"))
    assert not middleware._is_exempt(req("POST", "/assets/app.js"))
    assert not middleware._is_exempt(req("GET", "/api/images/x.png"))
    assert not middleware._is_exempt(req("GET", "/users/me"))
