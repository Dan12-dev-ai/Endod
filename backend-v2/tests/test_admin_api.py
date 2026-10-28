"""The Endod super admin's API on internal-api (``/internal/admin``, api_admin.py):
its own key, account data and counts only (never health data), suspending
an account (signed out everywhere, no sign-in), card checks, health, and a
search that is never SQL.
"""

import json
import time
from datetime import datetime, timedelta, timezone

import fakeredis
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from test_patient_history import HOSPITAL, PASSWORD, link, register

ADMIN_KEY = "admin-api-test-key-0123456789abcdefghij"
PLATFORM_KEY = "platform-admin-test-key-0123456789abcdef"
PHARMACY_KEY = "pharmacy-test-key-0123456789abcdefghijkl"
HEADERS = {"X-Superadmin-Key": ADMIN_KEY}
ACTOR = "ops@endod.example"

#: Names of health and record fields: none may appear in any admin answer.
HEALTH_FIELDS = {
    "health_profile", "allergies", "medications", "conditions", "blood_type", "sex", "date_of_birth",
    "age_range", "emergency_contact_name", "emergency_contact_phone", "records", "record", "history",
    "title", "details", "details_json", "category", "prescriptions", "medicines", "notes", "department",
    "hospital_reason", "timeline", "appointments", "follow_ups", "files", "consent", "preferences",
}
#: Written into the patient's health profile; must never come back.
SECRET = "PENICILLIN-SENTINEL-7731"

ROUTES = [
    ("GET", "/internal/admin/stats", None),
    ("GET", "/internal/admin/users?query=a", None),
    ("GET", "/internal/admin/users/DE123456", None),
    ("POST", "/internal/admin/users/DE123456/suspend", {"reason": "abuse", "actor_email": ACTOR}),
    ("POST", "/internal/admin/users/DE123456/reactivate", {"reason": "cleared", "actor_email": ACTOR}),
    ("GET", "/internal/admin/cards/DE123456", None),
    ("GET", "/internal/admin/health", None),
]


@pytest.fixture
def client(tmp_path, monkeypatch):
    """The patient API (sign-up, sign-in, profile, cards)."""
    from dedan_platform import credentials
    from dedan_platform import db as dbmod
    from dedan_platform.api_auth import router as auth_router
    from dedan_platform.api_cards import router as cards_router
    from dedan_platform.api_profile import router as profile_router

    monkeypatch.setenv("REALTIME_TOKEN_SECRET", "test-secret")
    monkeypatch.setenv("DEDAN_DATABASE_URL", f"sqlite:///{tmp_path / 'admin.db'}")
    monkeypatch.setenv("RECORD_FILES_DIR", str(tmp_path / "records"))
    monkeypatch.setenv("SUPERADMIN_API_KEY", ADMIN_KEY)
    monkeypatch.setenv("PLATFORM_ADMIN_KEY", PLATFORM_KEY)
    monkeypatch.setenv("PHARMACY_API_KEY", PHARMACY_KEY)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_SENTINELS", raising=False)
    monkeypatch.setattr(credentials, "_throttle", credentials._LoginThrottle())
    dbmod.reset_engine()
    dbmod.create_all()
    app = FastAPI()
    for router in (auth_router, profile_router, cards_router):
        app.include_router(router)
    yield TestClient(app)
    dbmod.reset_engine()


@pytest.fixture
def admin(client, monkeypatch):
    """internal-api, as the super admin's API calls it."""
    import main_internal

    monkeypatch.setenv("INTERNAL_ALLOWED_HOSTS", "testserver")
    return TestClient(main_internal.create_app())


@pytest.fixture
def patient(client):
    p = register(client)
    consent = client.patch("/users/me/consent", headers=p["auth"], json={"treatment_processing": True})
    assert consent.status_code == 200
    resp = client.patch("/users/me/health-profile", headers=p["auth"],
                        json={"allergies": SECRET, "conditions": SECRET, "medications": SECRET})
    assert resp.status_code == 200, resp.text
    return p


def login(client, identifier, password=PASSWORD):
    return client.post("/auth/login", json={"identifier": identifier, "password": password})


def suspend(admin, dedan, reason="Fraudulent bookings reported by two hospitals."):
    return admin.post(f"/internal/admin/users/{dedan}/suspend", headers=HEADERS,
                      json={"reason": reason, "actor_email": ACTOR})


def reactivate(admin, dedan, reason="Cleared after review."):
    return admin.post(f"/internal/admin/users/{dedan}/reactivate", headers=HEADERS,
                      json={"reason": reason, "actor_email": ACTOR})


def _keys(value):
    """Every key anywhere in a JSON answer."""
    if isinstance(value, dict):
        found = set(value)
        for item in value.values():
            found |= _keys(item)
        return found
    if isinstance(value, list):
        found = set()
        for item in value:
            found |= _keys(item)
        return found
    return set()


# --- the key -----------------------------------------------------------------------------

@pytest.mark.parametrize("method, path, body", ROUTES)
def test_every_route_needs_the_admin_key(admin, method, path, body):
    for headers in ({}, {"X-Superadmin-Key": "wrong"}, {"X-Superadmin-Key": ADMIN_KEY[:-1]},
                    {"X-Superadmin-Key": ADMIN_KEY + "x"}, {"X-Platform-Key": PLATFORM_KEY},
                    {"X-Pharmacy-Key": PHARMACY_KEY}, {"X-Superadmin-Key": PLATFORM_KEY},
                    {"X-Superadmin-Key": PHARMACY_KEY}):
        resp = admin.request(method, path, headers=headers, json=body)
        assert resp.status_code == 401, (method, path, headers, resp.text)


@pytest.mark.parametrize("method, path, body", ROUTES)
def test_refused_while_the_key_is_unset(admin, monkeypatch, method, path, body):
    monkeypatch.delenv("SUPERADMIN_API_KEY", raising=False)
    resp = admin.request(method, path, headers=HEADERS, json=body)
    assert resp.status_code == 503
    resp = admin.request(method, path, headers={"X-Superadmin-Key": ""}, json=body)
    assert resp.status_code == 503


SESSION_KEY = "platform-session-secret-0123456789abcdefgh"


@pytest.mark.parametrize("value", ["short-key", PLATFORM_KEY, PHARMACY_KEY, "   ", SESSION_KEY])
def test_refused_with_a_weak_or_shared_key(admin, monkeypatch, value):
    """Too short, the hospital service's or the pharmacy site's key, or the
    platform's own session secret (ADMIN_API_KEY): refused, even to a caller
    who sends exactly that value."""
    monkeypatch.setenv("ADMIN_API_KEY", SESSION_KEY)
    monkeypatch.setenv("SUPERADMIN_API_KEY", value)
    resp = admin.get("/internal/admin/stats", headers={"X-Superadmin-Key": value})
    assert resp.status_code == 503


def test_the_platform_key_does_not_open_admin_routes_and_vice_versa(admin):
    assert admin.get("/internal/admin/stats", headers={"X-Platform-Key": PLATFORM_KEY}).status_code == 401
    # The hospital service's internal route does not take the admin key.
    resp = admin.get(f"/internal/shares/{'a' * 32}/files/{'b' * 32}", headers={"X-Platform-Key": ADMIN_KEY})
    assert resp.status_code == 401


def test_the_key_is_compared_in_constant_time(monkeypatch):
    from dedan_platform import api_admin

    calls = []
    real = api_admin.hmac.compare_digest
    monkeypatch.setattr(api_admin.hmac, "compare_digest", lambda a, b: calls.append(1) or real(a, b))
    monkeypatch.setenv("SUPERADMIN_API_KEY", ADMIN_KEY)
    api_admin.require_admin_key(ADMIN_KEY)
    assert calls
    source = open(api_admin.__file__, encoding="utf-8").read()
    assert "x_superadmin_key == " not in source and "== expected" not in source


def test_the_patient_api_does_not_serve_admin_routes(client):
    import main_clinical

    paths = {getattr(route, "path", "") for route in main_clinical.app.routes}
    assert not any(path.startswith("/internal") for path in paths)


# --- no health data ---------------------------------------------------------------------

def test_no_health_data_in_any_answer(admin, patient, client):
    from dedan_platform import api_admin

    dedan = patient["dedan"]
    answers = [
        admin.get("/internal/admin/stats", headers=HEADERS),
        admin.get("/internal/admin/users", headers=HEADERS),
        admin.get("/internal/admin/users?query=Almaz", headers=HEADERS),
        admin.get(f"/internal/admin/users/{dedan}", headers=HEADERS),
        admin.get(f"/internal/admin/cards/{dedan}", headers=HEADERS),
        admin.get("/internal/admin/health", headers=HEADERS),
        suspend(admin, dedan),
        reactivate(admin, dedan),
    ]
    for resp in answers:
        assert resp.status_code == 200, resp.text
        assert SECRET not in resp.text
        assert not (_keys(resp.json()) & HEALTH_FIELDS), (resp.request.url, _keys(resp.json()) & HEALTH_FIELDS)
    # An account answer has exactly the account fields.
    one = admin.get(f"/internal/admin/users/{dedan}", headers=HEADERS).json()
    assert set(one) == set(api_admin.ACCOUNT_FIELDS)
    for row in admin.get("/internal/admin/users", headers=HEADERS).json()["items"]:
        assert set(row) == set(api_admin.ACCOUNT_FIELDS)
    # The health profile is still there (and encrypted), untouched.
    assert client.get("/users/me/health-profile", headers=patient["auth"]).status_code == 401  # signed out


def test_the_admin_module_never_touches_health_tables():
    """No ORM entity of a health table (which would decrypt it) is selected."""
    from dedan_platform import api_admin

    source = open(api_admin.__file__, encoding="utf-8").read()
    for name in ("HealthProfile", "HealthEvent", "RecordFile", "FollowUp", "PrescriptionItem",
                 "PrescriptionDispense", "decrypt(", "field_encryption", "import crypto", "crypto."):
        assert name not in source, name
    # HospitalRecord and Prescription are only counted (retracted_at, status, dates).
    assert "select(HospitalRecord" not in source and "select(Prescription)" not in source


# --- accounts ----------------------------------------------------------------------------

def test_account_detail(admin, patient):
    from dedan_platform import identity

    link(patient["id"], hospital="c" * 32)
    one = admin.get(f"/internal/admin/users/{patient['dedan']}", headers=HEADERS).json()
    assert one["dedan_id"] == patient["dedan"]
    assert one["name"] == "Almaz Tefera"
    assert one["email"] == "a@example.com"
    assert one["phone"] == "+251911223344"
    assert one["status"] == "active"
    assert one["linked_hospitals"] == 2  # HOSPITAL (register) and c*32
    assert one["created_at"] and one["suspended_at"] is None
    assert identity.get_user_by_dedan_id(patient["dedan"]) is not None
    # Lower case is accepted; anything else is not an Endod ID.
    assert admin.get(f"/internal/admin/users/{patient['dedan'].lower()}", headers=HEADERS).status_code == 200
    assert admin.get("/internal/admin/users/DE000000", headers=HEADERS).status_code == 404
    for bad in ("DE12345", "XX123456", "DE1234567", "..%2F..%2Fstats"):
        assert admin.get(f"/internal/admin/users/{bad}", headers=HEADERS).status_code in (404, 422)


def test_last_sign_in(admin, client, patient):
    assert login(client, patient["dedan"]).status_code == 200
    one = admin.get(f"/internal/admin/users/{patient['dedan']}", headers=HEADERS).json()
    assert one["last_sign_in_at"] is not None


def test_search_by_name_phone_email_and_id(admin, client):
    a = register(client, email="almaz@example.com", first="Almaz", last="Tefera", phone="+251911000001")
    b = register(client, email="bekele@example.com", first="Bekele", last="Girma", phone="+251911000002",
                 linked=False)

    def found(query):
        resp = admin.get("/internal/admin/users", params={"query": query}, headers=HEADERS)
        assert resp.status_code == 200, resp.text
        return {row["dedan_id"] for row in resp.json()["items"]}

    assert found("") == {a["dedan"], b["dedan"]}
    assert found("almaz") == {a["dedan"]}
    assert found("Almaz Tefera") == {a["dedan"]}
    assert found("GIRMA") == {b["dedan"]}
    assert found("bekele@example") == {b["dedan"]}
    assert found("+251911000002") == {b["dedan"]}
    assert found("0911 000 001") == {a["dedan"]}  # the local form finds the stored one
    assert found(a["dedan"]) == {a["dedan"]}
    assert found(b["dedan"].lower()) == {b["dedan"]}
    assert found("nobody") == set()


@pytest.mark.parametrize("attack", [
    "' OR '1'='1", "' OR 1=1 --", "%", "_", "%%", "\\", "%' --", "a%' OR '%'='",
    "'; DROP TABLE users; --", "\" OR \"\"=\"", "') UNION SELECT password_hash, NULL FROM credentials --",
    "*", "[a-z]", "%_%",
])
def test_search_is_not_sql(admin, client, attack):
    register(client, email="almaz@example.com", phone="+251911000001")
    register(client, email="bekele@example.com", first="Bekele", last="Girma", phone="+251911000002",
             linked=False)
    resp = admin.get("/internal/admin/users", params={"query": attack}, headers=HEADERS)
    assert resp.status_code == 200, resp.text
    # Nobody's name, phone, email or ID contains these characters literally.
    assert resp.json()["items"] == []
    assert "password" not in resp.text and "hash" not in resp.text
    # Nothing was dropped or changed.
    from dedan_platform.db import session_scope
    from dedan_platform.models import Credential, User

    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 2
        assert session.scalar(select(func.count()).select_from(Credential)) == 2


def test_wildcards_match_literally(admin, client):
    weird = register(client, email="under_score%pct@example.com", phone=None, linked=False)
    register(client, email="plain@example.com", phone=None, linked=False)
    resp = admin.get("/internal/admin/users", params={"query": "_score%"}, headers=HEADERS)
    assert [row["dedan_id"] for row in resp.json()["items"]] == [weird["dedan"]]


def test_search_length_is_capped(admin):
    resp = admin.get("/internal/admin/users", params={"query": "a" * 101}, headers=HEADERS)
    assert resp.status_code == 422


# --- suspend and reactivate --------------------------------------------------------------

def test_suspend_signs_out_and_refuses_sign_in(admin, client, patient):
    from dedan_platform.db import session_scope
    from dedan_platform.models import User, UserEvent

    second_session = login(client, "a@example.com").json()["access_token"]
    assert client.get("/users/me", headers=patient["auth"]).status_code == 200

    resp = suspend(admin, patient["dedan"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "suspended"
    assert body["suspended_by"] == ACTOR
    assert body["suspended_reason"] == "Fraudulent bookings reported by two hospitals."

    # Every session ended: the one from sign-up and the one from sign-in.
    for token in (patient["auth"]["Authorization"], second_session):
        resp = client.get("/users/me", headers={"Authorization": token})
        assert resp.status_code in (401, 403), resp.text
    # No sign-in, by Endod ID or email; the right password only learns it is suspended.
    for identifier in (patient["dedan"], "a@example.com"):
        resp = login(client, identifier)
        assert resp.status_code == 403 and "suspended" in resp.json()["detail"]
        assert "access_token" not in resp.text
    wrong = login(client, patient["dedan"], password="Wrong-pass-123")
    assert wrong.status_code == 401 and "suspended" not in wrong.text
    # The public card check no longer vouches for the card.
    card = client.get("/users/me/card", headers=patient["auth"])
    assert card.status_code in (401, 403)

    # Twice is refused; the audit trail has who and why.
    assert suspend(admin, patient["dedan"]).status_code == 409
    with session_scope() as session:
        user = session.scalar(select(User).where(User.dedan_user_id == patient["dedan"]))
        assert user.sessions_revoked_at is not None
        events = [(e.event_type, json.loads(e.payload)) for e in
                  session.scalars(select(UserEvent).where(UserEvent.user_id == user.id,
                                                          UserEvent.event_type == "account_suspended"))]
    assert events == [("account_suspended", {"by": ACTOR, "reason": "Fraudulent bookings reported by two hospitals.",
                                              "via": "endod-admin"})]

    # Reactivated: signs in again, but the old sessions stay ended.
    time.sleep(1.1)  # tokens carry whole seconds; the revocation's second is refused
    resp = reactivate(admin, patient["dedan"])
    assert resp.status_code == 200 and resp.json()["status"] == "active"
    assert resp.json()["suspended_at"] is None
    assert reactivate(admin, patient["dedan"]).status_code == 409
    for token in (patient["auth"]["Authorization"], second_session):
        assert client.get("/users/me", headers={"Authorization": token}).status_code == 401
    fresh = login(client, patient["dedan"])
    assert fresh.status_code == 200
    assert client.get("/users/me", headers={"Authorization": fresh.json()["access_token"]}).status_code == 200


def test_a_token_from_the_second_of_the_suspension_is_refused(admin, client, patient):
    from dedan_platform import credentials

    suspend(admin, patient["dedan"])
    reactivate(admin, patient["dedan"])
    valid_from = credentials.tokens_valid_from(patient["id"])
    from dedan_platform.db import session_scope
    from dedan_platform.models import User

    with session_scope() as session:
        revoked = session.scalar(select(User.sessions_revoked_at).where(User.id == patient["id"]))
    revoked = revoked if revoked.tzinfo else revoked.replace(tzinfo=timezone.utc)
    assert valid_from == int(revoked.timestamp()) + 1


def test_suspended_patient_cannot_reset_the_password_by_phone(admin, client, monkeypatch):
    import test_phone_auth as phone_tests
    from dedan_platform import phone_auth

    sms = phone_tests.FakeSms()
    monkeypatch.setattr(phone_auth, "build_provider", lambda: sms)
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")
    signed_up = phone_tests.sign_up(client, sms)
    assert suspend(admin, signed_up["dedan_user_id"]).status_code == 200
    phone_tests._age_codes(120)  # past the resend wait
    assert phone_tests.request_code(client, ip="10.0.0.9").status_code == 202
    token = phone_tests.verify(client, sms.last_code()).json()["verification_token"]
    resp = phone_tests.complete(client, token, password="An0ther-Str0ng-pass!")
    assert resp.status_code == 403 and "suspended" in resp.json()["detail"]
    assert "access_token" not in resp.text


def test_suspend_needs_a_reason_and_an_actor(admin, patient):
    path = f"/internal/admin/users/{patient['dedan']}/suspend"
    for body in ({}, {"reason": "  ", "actor_email": ACTOR}, {"reason": "ok reason"},
                 {"reason": "ok reason", "actor_email": "not-an-email"}, {"reason": "x" * 501, "actor_email": ACTOR}):
        assert admin.post(path, json=body, headers=HEADERS).status_code == 422, body
    assert admin.post("/internal/admin/users/DE000000/suspend", headers=HEADERS,
                      json={"reason": "abuse", "actor_email": ACTOR}).status_code == 404


def test_a_closed_account_is_not_suspended(admin, patient):
    from dedan_platform.db import session_scope
    from dedan_platform.models import User

    with session_scope() as session:
        session.execute(update(User).where(User.id == patient["id"]).values(is_active=False))
    assert suspend(admin, patient["dedan"]).status_code == 409
    assert admin.get(f"/internal/admin/users/{patient['dedan']}", headers=HEADERS).json()["status"] == "deactivated"


# --- digital cards -----------------------------------------------------------------------

def test_card_check(admin, client, patient):
    from dedan_platform import cards

    dedan = patient["dedan"]
    signature = cards.card_signature(dedan)
    plain = admin.get(f"/internal/admin/cards/{dedan}", headers=HEADERS).json()
    assert plain["valid"] is True and plain["signature_checked"] is False
    assert plain["account_status"] == "active" and plain["issued_at"]
    signed = admin.get(f"/internal/admin/cards/{dedan}", params={"s": signature}, headers=HEADERS).json()
    assert signed["valid"] is True and signed["signature_valid"] is True
    forged = admin.get(f"/internal/admin/cards/{dedan}", params={"s": "A" * 22}, headers=HEADERS).json()
    assert forged["valid"] is False and forged["signature_valid"] is False
    junk = admin.get(f"/internal/admin/cards/{dedan}", params={"s": "<script>"}, headers=HEADERS).json()
    assert junk["valid"] is False
    assert admin.get("/internal/admin/cards/DE000000", headers=HEADERS).status_code == 404
    # The public check agrees, and both refuse a suspended account's card.
    assert client.get(f"/cards/{dedan}/verify", params={"s": signature}).status_code == 200
    suspend(admin, dedan)
    suspended = admin.get(f"/internal/admin/cards/{dedan}", params={"s": signature}, headers=HEADERS).json()
    assert suspended["valid"] is False and suspended["signature_valid"] is True
    assert suspended["account_status"] == "suspended"
    assert client.get(f"/cards/{dedan}/verify", params={"s": signature}).status_code == 404


# --- stats and health --------------------------------------------------------------------

def test_stats(admin, client):
    from dedan_platform.db import session_scope
    from dedan_platform.models import Appointment, User

    a = register(client, email="one@example.com", phone="+251911000001")
    register(client, email="two@example.com", phone="+251911000002", linked=False)
    old = register(client, email="old@example.com", phone="+251911000003", linked=False)
    now = datetime.now(timezone.utc)
    with session_scope() as session:
        session.execute(update(User).where(User.id == old["id"]).values(created_at=now - timedelta(days=30)))
        for state, when in (("confirmed", now), ("awaiting_hospital", now), ("awaiting_payment", now),
                            ("cancelled", now), ("completed", now - timedelta(days=40))):
            session.add(Appointment(user_id=a["id"], hospital_id=HOSPITAL, hospital_state=state,
                                    scheduled_at=when, timezone="Africa/Addis_Ababa"))
        # The patient's own entry (no hospital) is not a booking.
        session.add(Appointment(user_id=a["id"], scheduled_at=now, timezone="UTC"))
    body = admin.get("/internal/admin/stats", headers=HEADERS).json()
    assert body["users_total"] == 3
    assert body["users_new_7d"] == 2
    assert body["users_suspended"] == 0
    assert body["bookings_today"] == 2
    assert body["bookings_week"] == 2
    assert body["open_prescriptions"] == 0


def test_health_without_redis(admin):
    body = admin.get("/internal/admin/health", headers=HEADERS).json()
    assert body["database"] == {"ok": True}
    assert body["redis"] == {"configured": False, "ok": None}
    assert body["outbox"]["backlog"] == 0
    assert body["dead_letters"] is None


def test_health_with_redis(admin, monkeypatch):
    from dedan_platform import eventbus, events_worker
    from dedan_platform.db import session_scope

    bus = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(eventbus, "connect", lambda: bus)
    monkeypatch.setattr(bus, "close", lambda: None)
    with session_scope() as session:
        eventbus.emit(session, "test.event", {"x": 1})
        eventbus.emit(session, "test.event", {"x": 2})
    bus.xadd(eventbus.DEAD_LETTER, {"type": "x", "error": "boom"})
    # No heartbeat yet: the worker is reported as not running.
    body = admin.get("/internal/admin/health", headers=HEADERS).json()
    assert body["redis"] == {"configured": True, "ok": True}
    assert body["events_worker"] == {"last_heartbeat": None, "ok": False}
    assert body["status"] == "degraded"
    assert body["outbox"]["backlog"] == 2 and body["outbox"]["oldest_at"]
    assert body["dead_letters"] == 1

    events_worker._last["heartbeat"] = 0.0
    events_worker.run_once(bus, now=10_000_000.0)
    body = admin.get("/internal/admin/health", headers=HEADERS).json()
    assert body["events_worker"]["ok"] is True and body["events_worker"]["last_heartbeat"]
    assert body["outbox"]["backlog"] == 0  # the round published them
    assert body["status"] == "ok"
    # No secret, URL or password in the answer.
    text = json.dumps(body).lower()
    for word in ("password", "redis://", "secret", ADMIN_KEY.lower(), PLATFORM_KEY.lower()):
        assert word not in text
