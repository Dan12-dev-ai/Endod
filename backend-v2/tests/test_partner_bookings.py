"""Partner hospitals, the Endod balance (Chapa), paid bookings, decisions from
the hospital service, refunds, video joins and emergency numbers.

Redis is real-protocol but in memory (fakeredis); Chapa is an httpx mock that
behaves like its API.
"""

import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import fakeredis
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

PASSWORD = "Str0ng-pass!"
ADDIS = ZoneInfo("Africa/Addis_Ababa")
HOSPITAL = "a" * 32
JITSI_SECRET = "jitsi-secret"
WEBHOOK_SECRET = "hook-secret"


class FakeChapa:
    """Chapa's initialize and verify endpoints, with payments the test can mark paid."""

    def __init__(self):
        self.payments = {}  # tx_ref -> {"amount": "100.00", "status": "pending"}
        self.initialized = []
        self.outage = None  # an HTTP status Chapa answers verify with (e.g. 503)

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer CHASECK_TEST-key"
        if request.url.path.endswith("/transaction/initialize"):
            body = json.loads(request.content)
            self.initialized.append(body)
            self.payments[body["tx_ref"]] = {"amount": body["amount"], "status": "pending", "currency": "ETB"}
            return httpx.Response(200, json={"status": "success", "message": "Hosted Link",
                                             "data": {"checkout_url": f"https://checkout.chapa.co/{body['tx_ref']}"}})
        if "/transaction/verify/" in request.url.path:
            if self.outage:
                return httpx.Response(self.outage, json={"message": "unavailable"})
            tx_ref = request.url.path.rsplit("/", 1)[-1]
            payment = self.payments.get(tx_ref)
            if payment is None:
                return httpx.Response(404, json={"status": "failed", "message": "Invalid transaction", "data": None})
            return httpx.Response(200, json={"status": "success", "data": {
                "status": payment["status"], "amount": payment["amount"], "currency": payment["currency"],
                "tx_ref": tx_ref, "reference": "APabc123"}})
        return httpx.Response(404)

    def pay(self, tx_ref, amount=None, currency="ETB"):
        payment = self.payments[tx_ref]
        payment["status"] = "success"
        payment["currency"] = currency
        if amount is not None:
            payment["amount"] = amount


@pytest.fixture
def chapa_api(monkeypatch):
    from dedan_platform import chapa

    fake = FakeChapa()
    monkeypatch.setattr(chapa, "_transport", httpx.MockTransport(fake.handler))
    monkeypatch.setenv("CHAPA_SECRET_KEY", "CHASECK_TEST-key")
    return fake


@pytest.fixture
def client(tmp_path, monkeypatch):
    from dedan_platform import db as dbmod
    from dedan_platform.api_auth import router as auth_router
    from dedan_platform.api_care import router as care_router
    from dedan_platform.api_health import router as health_router
    from dedan_platform.api_inbox import router as inbox_router
    from dedan_platform.api_payments import router as payments_router
    from dedan_platform.api_profile import router as profile_router

    monkeypatch.setenv("REALTIME_TOKEN_SECRET", "test-secret")
    monkeypatch.setenv("DEDAN_DATABASE_URL", f"sqlite:///{tmp_path / 'partner.db'}")
    monkeypatch.setenv("JITSI_APP_SECRET", JITSI_SECRET)
    monkeypatch.setenv("SERVICE_FEE_FLAT_SANTIM", "500")
    monkeypatch.setenv("SERVICE_FEE_PERCENT_BP", "200")  # 2%
    monkeypatch.setenv("PUBLIC_APP_URL", "https://endod.example")
    dbmod.reset_engine()
    dbmod.create_all()
    app = FastAPI()
    for router in (auth_router, profile_router, health_router, care_router, payments_router, inbox_router):
        app.include_router(router)
    yield TestClient(app)
    dbmod.reset_engine()


def register(client, email="a@example.com", first="Almaz", last="Tefera"):
    resp = client.post("/auth/register", json={
        "first_name": first, "last_name": last, "email": email,
        "password": PASSWORD, "password_confirmation": PASSWORD})
    assert resp.status_code in (200, 201), resp.text
    return {"Authorization": resp.json()["access_token"]}


@pytest.fixture
def auth(client):
    return register(client)


@pytest.fixture
def bus():
    return fakeredis.FakeRedis(decode_responses=True)


def from_hospital(bus, event_type, payload, event_id=None):
    bus.xadd("endod:hospital", {"id": event_id or uuid.uuid4().hex, "type": event_type,
                                "source": "hospital-service",
                                "occurred_at": datetime.now(timezone.utc).isoformat(),
                                "payload": json.dumps(payload)})


def run_worker(bus, rounds=1):
    from dedan_platform import events_worker

    for _ in range(rounds):
        events_worker.run_once(bus)


def sent(bus):
    return [(f["type"], json.loads(f["payload"])) for _id, f in bus.xrange("endod:patient")]


LISTING = {"hospital_id": HOSPITAL, "version": 1, "code": "TASH", "name": "Tikur Anbessa Specialized Hospital",
           "name_am": "ጥቁር አንበሳ", "kind": "public", "city": "Addis Ababa", "address": "Churchill Ave",
           "phone": "011 551 7611", "ambulance_phone": "907", "emergency": True,
           "latitude": 9.0207, "longitude": 38.7531, "services": ["general_medicine", "emergency"],
           "open_hours": "24h", "timezone": "Africa/Addis_Ababa",
           "video_enabled": True, "price_in_person": 15000, "price_video": 10000}


@pytest.fixture
def listed(bus, client):
    from_hospital(bus, "hospital.listed", LISTING)
    run_worker(bus)
    return HOSPITAL


def fund(client, auth, chapa_api, birr="1000.00"):
    started = client.post("/users/me/wallet/deposits", headers=auth, json={"amount": birr}).json()
    tx_ref = chapa_api.initialized[-1]["tx_ref"]
    chapa_api.pay(tx_ref)
    assert client.get(f"/payments/chapa/callback?trx_ref={tx_ref}").json()["status"] == "succeeded"
    return started["deposit_id"]


def when(days=2, hour=10):
    day = datetime.now(ADDIS) + timedelta(days=days)
    return day.replace(hour=hour, minute=0, second=0, microsecond=0)


def book(client, auth, mode="in_person", at=None, **extra):
    return client.post("/users/me/appointments", headers=auth, json={
        "scheduled_at": (at or when()).isoformat(), "timezone": "Africa/Addis_Ababa", "facility_id": HOSPITAL,
        "visit_mode": mode, "department": "general_medicine", **extra})


def balance(client, auth):
    return client.get("/users/me/wallet", headers=auth).json()["balance"]


# ---------------------------------------------------------------------------------------

class TestPartnerListings:
    def test_a_listed_hospital_is_browsable_with_prices(self, client, auth, listed):
        resp = client.get("/users/me/care/facilities", headers=auth, params={"q": "Tikur Anbessa Specialized"})
        assert resp.status_code == 200, resp.text
        found = resp.json()
        partner = next(f for f in found["facilities"] if f["id"] == HOSPITAL)
        assert partner["partner"] is True and partner["ownership"] == "public"
        assert partner["price_in_person"] == 15000 and partner["video_enabled"] is True
        assert partner["ambulance_phone"] == "907" and partner["departments"] == ["general_medicine", "emergency"]

    def test_older_announcements_are_ignored_and_unlisting_hides(self, client, auth, bus, listed):
        from_hospital(bus, "hospital.listed", {**LISTING, "version": 3, "price_in_person": 20000})
        from_hospital(bus, "hospital.listed", {**LISTING, "version": 2, "price_in_person": 99})
        run_worker(bus)
        assert client.get(f"/users/me/care/facilities/{HOSPITAL}", headers=auth).json()["price_in_person"] == 20000
        from_hospital(bus, "hospital.unlisted", {"hospital_id": HOSPITAL, "version": 4})
        run_worker(bus)
        assert client.get(f"/users/me/care/facilities/{HOSPITAL}", headers=auth).status_code == 404

    @pytest.mark.parametrize("change", [{"price_in_person": 150.5}, {"latitude": 200}, {"version": -1},
                                        {"name": ""}])
    def test_malformed_listings_are_dead_lettered(self, client, auth, bus, change):
        from_hospital(bus, "hospital.listed", {**LISTING, **change})
        run_worker(bus)
        assert len(bus.xrange("endod:dead-letter")) == 1
        assert client.get(f"/users/me/care/facilities/{HOSPITAL}", headers=auth).status_code == 404

    def test_production_shows_only_partner_hospitals(self, client, auth, listed, monkeypatch):
        monkeypatch.setenv("CARE_DEMO_DIRECTORY", "false")
        ids = [f["id"] for f in client.get("/users/me/care/facilities", headers=auth).json()["facilities"]]
        assert ids == [HOSPITAL]


class TestDeposits:
    def test_a_deposit_is_credited_only_after_chapa_confirms(self, client, auth, chapa_api):
        resp = client.post("/users/me/wallet/deposits", headers=auth, json={"amount": "250.50"})
        assert resp.status_code == 201, resp.text
        deposit = resp.json()
        assert deposit["status"] == "pending" and deposit["checkout_url"].startswith("https://checkout.chapa.co/")
        sent_body = chapa_api.initialized[-1]
        assert sent_body["amount"] == "250.50" and sent_body["currency"] == "ETB"
        assert sent_body["return_url"].startswith("https://endod.example/interview")
        assert sent_body["callback_url"] == "https://endod.example/api/payments/chapa/callback"
        assert len(sent_body["customization"]["title"]) <= 16

        # Not paid yet: the callback changes nothing.
        tx_ref = sent_body["tx_ref"]
        assert client.get(f"/payments/chapa/callback?trx_ref={tx_ref}").json()["status"] == "pending"
        assert balance(client, auth) == 0
        chapa_api.pay(tx_ref)
        # The patient's return page asks; the deposit is settled with Chapa.
        assert client.get(f"/users/me/wallet/deposits/{deposit['deposit_id']}", headers=auth).json()["status"] \
            == "succeeded"
        assert balance(client, auth) == 25050
        # Every later notification is a no-op.
        for _ in range(3):
            client.get(f"/payments/chapa/callback?trx_ref={tx_ref}")
            client.post("/payments/chapa/webhook", json={"tx_ref": tx_ref})
        wallet = client.get("/users/me/wallet", headers=auth).json()
        assert wallet["balance"] == 25050 and [e["kind"] for e in wallet["entries"]] == ["deposit"]
        inbox = client.get("/users/me/inbox", headers=auth).json()
        assert any(i["kind"] == "deposit_received" for i in inbox["items"])

    def test_a_wrong_amount_or_currency_is_never_credited(self, client, auth, chapa_api):
        client.post("/users/me/wallet/deposits", headers=auth, json={"amount": "100"})
        tx_ref = chapa_api.initialized[-1]["tx_ref"]
        chapa_api.pay(tx_ref, amount="1000.00")
        assert client.get(f"/payments/chapa/callback?trx_ref={tx_ref}").json()["status"] == "failed"
        client.post("/users/me/wallet/deposits", headers=auth, json={"amount": "100"})
        tx_ref = chapa_api.initialized[-1]["tx_ref"]
        chapa_api.pay(tx_ref, currency="USD")
        assert client.get(f"/payments/chapa/callback?trx_ref={tx_ref}").json()["status"] == "failed"
        assert balance(client, auth) == 0

    def test_webhook_signature_is_checked_when_configured(self, client, auth, chapa_api, monkeypatch):
        monkeypatch.setenv("CHAPA_WEBHOOK_SECRET", WEBHOOK_SECRET)
        client.post("/users/me/wallet/deposits", headers=auth, json={"amount": "100"})
        tx_ref = chapa_api.initialized[-1]["tx_ref"]
        chapa_api.pay(tx_ref)
        body = json.dumps({"tx_ref": tx_ref, "status": "success"}).encode()
        assert client.post("/payments/chapa/webhook", content=body,
                           headers={"x-chapa-signature": "forged"}).status_code == 401
        good = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        resp = client.post("/payments/chapa/webhook", content=body, headers={"x-chapa-signature": good})
        assert resp.status_code == 200 and resp.json()["status"] == "succeeded"
        assert balance(client, auth) == 10000

    def test_a_forged_success_notification_adds_nothing(self, client, auth, chapa_api):
        client.post("/users/me/wallet/deposits", headers=auth, json={"amount": "100"})
        tx_ref = chapa_api.initialized[-1]["tx_ref"]
        # Someone posts "success" without paying: Chapa's verify says pending.
        client.post("/payments/chapa/webhook", json={"tx_ref": tx_ref, "status": "success"})
        assert balance(client, auth) == 0

    @pytest.mark.parametrize("amount,status", [("5", 400), ("100001", 400), ("10.555", 422), ("0", 422)])
    def test_deposit_limits(self, client, auth, chapa_api, amount, status):
        assert client.post("/users/me/wallet/deposits", headers=auth, json={"amount": amount}).status_code == status

    def test_no_chapa_key_means_no_deposits(self, client, auth):
        assert client.post("/users/me/wallet/deposits", headers=auth, json={"amount": "100"}).status_code == 503

    def test_deposits_are_private(self, client, auth, chapa_api):
        deposit = client.post("/users/me/wallet/deposits", headers=auth, json={"amount": "100"}).json()
        other = register(client, "b@example.com")
        assert client.get(f"/users/me/wallet/deposits/{deposit['deposit_id']}", headers=other).status_code == 404


class TestPaidBookings:
    def test_quote_shows_price_fee_and_whether_the_balance_covers_it(self, client, auth, listed, chapa_api):
        quote = client.get("/users/me/hospital-bookings/quote", headers=auth,
                           params={"hospital_id": HOSPITAL, "visit_mode": "telehealth"}).json()
        # 100 birr + 5 birr flat + 2% = 107 birr.
        assert quote == {"hospital_id": HOSPITAL, "visit_mode": "telehealth", "price": 10000, "service_fee": 700,
                         "total": 10700, "currency": "ETB", "balance": 0, "enough": False}

    def test_booking_without_enough_money_is_refused_and_charges_nothing(self, client, auth, listed):
        resp = book(client, auth)
        assert resp.status_code == 402 and "Add money" in resp.json()["detail"]
        assert client.get("/users/me/appointments", headers=auth).json() == []

    def test_a_booking_pays_and_tells_the_hospital(self, client, auth, bus, listed, chapa_api):
        fund(client, auth, chapa_api)
        resp = book(client, auth, notes="Headache")
        assert resp.status_code == 201, resp.text
        body = resp.json()
        appointment = body["appointment"]
        assert body["payment"] == {"price": 15000, "service_fee": 800, "total": 15800}
        assert appointment["hospital_booking"]["state"] == "awaiting_hospital"
        assert appointment["location"].startswith("Tikur Anbessa")
        assert balance(client, auth) == 100000 - 15800
        assert len(body["reminders"]) >= 1

        run_worker(bus)
        events = sent(bus)
        assert [t for t, _ in events] == ["appointment.requested"]
        request = events[0][1]
        assert request["hospital_id"] == HOSPITAL and request["price"] == 15000 and request["visit_mode"] == "in_person"
        assert request["patient"]["name"] == "Almaz Tefera" and request["patient"]["dedan_id"].startswith("DE")
        assert datetime.fromisoformat(request["scheduled_at"]).tzinfo is not None

    def test_the_hospital_confirms_in_person(self, client, auth, bus, listed, chapa_api):
        fund(client, auth, chapa_api)
        aid = book(client, auth).json()["appointment"]["appointment_id"]
        from_hospital(bus, "appointment.confirmed", {"appointment_id": aid, "hospital_id": HOSPITAL,
                                                     "status": "confirmed", "meeting_room": None,
                                                     "doctor_name": None, "reason": None})
        run_worker(bus)
        appointment = client.get(f"/users/me/appointments/{aid}", headers=auth).json()
        assert appointment["status"] == "CONFIRMED" and appointment["hospital_booking"]["state"] == "confirmed"

    def test_video_waits_for_a_doctor_then_can_be_joined(self, client, auth, bus, listed, chapa_api):
        fund(client, auth, chapa_api)
        at = datetime.now(timezone.utc) + timedelta(minutes=20)
        resp = book(client, auth, mode="telehealth", at=at)
        assert resp.status_code == 201, resp.text
        aid = resp.json()["appointment"]["appointment_id"]
        assert resp.json()["appointment"]["hospital_booking"]["state"] == "awaiting_doctor"
        assert client.post(f"/users/me/appointments/{aid}/video", headers=auth).status_code == 409

        from_hospital(bus, "appointment.confirmed", {"appointment_id": aid, "hospital_id": HOSPITAL,
                                                     "status": "confirmed", "meeting_room": "endod-abc123",
                                                     "doctor_name": "Dr. Hiwot", "reason": None})
        run_worker(bus)
        appointment = client.get(f"/users/me/appointments/{aid}", headers=auth).json()
        assert appointment["provider_name"] == "Dr. Hiwot" and appointment["hospital_booking"]["video_ready"] is True
        assert appointment["meeting_url"] == "https://meet.endod-health.com/endod-abc123"

        join = client.post(f"/users/me/appointments/{aid}/video", headers=auth)
        assert join.status_code == 200, join.text
        details = join.json()
        head, payload, sig = details["jwt"].split(".")
        expected = hmac.new(JITSI_SECRET.encode(), f"{head}.{payload}".encode(), hashlib.sha256).digest()
        assert base64.urlsafe_b64decode(sig + "==") == expected
        claims = json.loads(base64.urlsafe_b64decode(payload + "=="))
        assert claims["room"] == "endod-abc123" and claims["context"]["user"]["moderator"] is False
        assert claims["context"]["user"]["name"] == "Almaz Tefera"
        # Someone else's visit cannot be joined.
        assert client.post(f"/users/me/appointments/{aid}/video",
                           headers=register(client, "b@example.com")).status_code == 404

    def test_rejection_refunds_in_full_once(self, client, auth, bus, listed, chapa_api):
        fund(client, auth, chapa_api)
        aid = book(client, auth, mode="telehealth").json()["appointment"]["appointment_id"]
        rejected = {"appointment_id": aid, "hospital_id": HOSPITAL, "status": "rejected",
                    "meeting_room": None, "doctor_name": None, "reason": "No doctor available"}
        from_hospital(bus, "appointment.rejected", rejected)
        from_hospital(bus, "appointment.rejected", rejected)  # sent twice (new event id)
        run_worker(bus)
        assert balance(client, auth) == 100000
        appointment = client.get(f"/users/me/appointments/{aid}", headers=auth).json()
        assert appointment["status"] == "CANCELLED" and appointment["hospital_booking"]["state"] == "rejected"
        assert appointment["hospital_booking"]["reason"] == "No doctor available"
        kinds = [e["kind"] for e in client.get("/users/me/wallet", headers=auth).json()["entries"]]
        assert kinds.count("refund") == 1

    def test_hospital_cancellation_refunds_and_completion_makes_the_payout_due(self, client, auth, bus, listed,
                                                                              chapa_api):
        from sqlalchemy import select

        from dedan_platform.db import session_scope
        from dedan_platform.models import HospitalPayout

        fund(client, auth, chapa_api)
        first = book(client, auth).json()["appointment"]["appointment_id"]
        second = book(client, auth, at=when(days=3)).json()["appointment"]["appointment_id"]
        for aid in (first, second):
            from_hospital(bus, "appointment.confirmed", {"appointment_id": aid, "hospital_id": HOSPITAL,
                                                         "status": "confirmed"})
        from_hospital(bus, "appointment.cancelled", {"appointment_id": first, "hospital_id": HOSPITAL,
                                                     "status": "cancelled", "reason": "Doctor ill", "by": "hospital"})
        from_hospital(bus, "appointment.completed", {"appointment_id": second, "hospital_id": HOSPITAL,
                                                     "status": "completed"})
        run_worker(bus)
        assert balance(client, auth) == 100000 - 15800
        with session_scope() as session:
            payouts = {p.appointment_id: p.status for p in session.scalars(select(HospitalPayout))}
        assert payouts == {first: "void", second: "due"}
        assert client.get(f"/users/me/appointments/{second}", headers=auth).json()["status"] == "COMPLETED"

    def test_patient_cancel_refunds_and_tells_the_hospital(self, client, auth, bus, listed, chapa_api):
        fund(client, auth, chapa_api)
        aid = book(client, auth).json()["appointment"]["appointment_id"]
        resp = client.patch(f"/users/me/appointments/{aid}/status", headers=auth, json={"status": "CANCELLED"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["hospital_booking"]["state"] == "cancelled"
        assert balance(client, auth) == 100000
        run_worker(bus)
        assert sent(bus)[-1] == ("appointment.cancelled", {"appointment_id": aid, "hospital_id": HOSPITAL,
                                                            "by": "patient"})
        # A late confirmation from the hospital changes nothing.
        from_hospital(bus, "appointment.confirmed", {"appointment_id": aid, "hospital_id": HOSPITAL,
                                                     "status": "confirmed"})
        run_worker(bus)
        assert client.get(f"/users/me/appointments/{aid}", headers=auth).json()["status"] == "CANCELLED"
        assert client.patch(f"/users/me/appointments/{aid}/status", headers=auth,
                            json={"status": "CANCELLED"}).status_code == 400

    def test_the_hospital_owns_confirming_completing_and_times(self, client, auth, listed, chapa_api):
        fund(client, auth, chapa_api)
        aid = book(client, auth).json()["appointment"]["appointment_id"]
        for target in ("CONFIRMED", "COMPLETED"):
            assert client.patch(f"/users/me/appointments/{aid}/status", headers=auth,
                                json={"status": target}).status_code == 400
        moved = client.post(f"/users/me/appointments/{aid}/reschedule", headers=auth,
                            json={"scheduled_at": when(days=4).isoformat()})
        assert moved.status_code == 400 and "cancel" in moved.json()["detail"]

    def test_a_started_visit_cannot_be_cancelled_by_the_patient(self, client, auth, listed, chapa_api):
        from sqlalchemy import update

        from dedan_platform.db import session_scope
        from dedan_platform.models import Appointment

        fund(client, auth, chapa_api)
        aid = book(client, auth).json()["appointment"]["appointment_id"]
        with session_scope() as session:
            session.execute(update(Appointment).values(scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=5)))
        resp = client.patch(f"/users/me/appointments/{aid}/status", headers=auth, json={"status": "CANCELLED"})
        assert resp.status_code == 400 and "contact the hospital" in resp.json()["detail"]

    def test_video_needs_the_hospital_to_offer_it(self, client, auth, bus, listed, chapa_api):
        from_hospital(bus, "hospital.listed", {**LISTING, "version": 2, "video_enabled": False, "price_video": None})
        run_worker(bus)
        fund(client, auth, chapa_api)
        resp = book(client, auth, mode="telehealth")
        assert resp.status_code == 400 and "video" in resp.json()["detail"]
        assert balance(client, auth) == 100000

    def test_two_bookings_cannot_spend_the_same_money(self, client, auth, listed, chapa_api):
        fund(client, auth, chapa_api, birr="200.00")
        assert book(client, auth).status_code == 201
        assert book(client, auth, at=when(days=3)).status_code == 402
        assert balance(client, auth) == 20000 - 15800

    def test_events_wait_in_the_database_while_redis_is_down(self, client, auth, listed, chapa_api):
        from dedan_platform import eventbus

        fund(client, auth, chapa_api)
        book(client, auth)
        later = fakeredis.FakeRedis(decode_responses=True)
        assert eventbus.publish_pending(later) == 1
        assert [t for t, _ in sent(later)] == ["appointment.requested"]

    def test_unknown_appointments_in_decisions_are_dead_lettered(self, client, auth, bus, listed):
        from_hospital(bus, "appointment.confirmed", {"appointment_id": "nope", "hospital_id": HOSPITAL,
                                                     "status": "confirmed"})
        run_worker(bus)
        assert len(bus.xrange("endod:dead-letter")) == 1


class TestEmergency:
    def test_numbers_and_nearest_hospitals(self, client, auth, bus, listed):
        from_hospital(bus, "hospital.listed", {**LISTING, "hospital_id": "b" * 32, "version": 1, "code": "STP",
                                               "name": "St. Peter Hospital", "latitude": 9.06, "longitude": 38.72,
                                               "ambulance_phone": "011 111 1111"})
        run_worker(bus)
        near_st_peter = client.get("/users/me/care/emergency", headers=auth,
                                   params={"latitude": 9.065, "longitude": 38.72}).json()
        assert near_st_peter["national"][0] == {"service": "ambulance", "number": "907", "label": "Ambulance"}
        assert [h["name"] for h in near_st_peter["hospitals"]][:2] == ["St. Peter Hospital",
                                                                       "Tikur Anbessa Specialized Hospital"]
        assert near_st_peter["hospitals"][0]["distance_km"] < 1
        no_location = client.get("/users/me/care/emergency", headers=auth).json()
        assert no_location["location_used"] is False and no_location["hospitals"][0]["distance_km"] is None
        assert client.get("/users/me/care/emergency", headers=auth, params={"latitude": 9}).status_code == 400


# --- review fixes --------------------------------------------------------------------

def _age_deposit(deposit_id, hours):
    from dedan_platform.db import session_scope
    from dedan_platform.models import Deposit

    with session_scope() as session:
        deposit = session.get(Deposit, deposit_id)
        deposit.created_at = deposit.created_at - timedelta(hours=hours)


def _start_deposit(client, auth, chapa_api, birr="300.00"):
    started = client.post("/users/me/wallet/deposits", headers=auth, json={"amount": birr}).json()
    return started["deposit_id"], chapa_api.initialized[-1]["tx_ref"]


def _deposit_status(client, auth, deposit_id):
    return client.get(f"/users/me/wallet/deposits/{deposit_id}", headers=auth).json()["status"]


def _user_id(email="a@example.com"):
    from dedan_platform import identity

    return identity.find_user_by_email(email).id


class TestChapaHiccups:
    def test_an_outage_never_closes_a_deposit_even_a_day_later(self, client, auth, chapa_api):
        from dedan_platform import events_worker

        deposit_id, tx_ref = _start_deposit(client, auth, chapa_api)
        _age_deposit(deposit_id, 30)
        chapa_api.pay(tx_ref)
        for outage in (503, 429, 401):
            chapa_api.outage = outage
            assert _deposit_status(client, auth, deposit_id) == "pending"
            events_worker.recheck_deposits()
        chapa_api.outage = None
        assert _deposit_status(client, auth, deposit_id) == "succeeded"
        assert balance(client, auth) == 30000

    def test_an_unknown_payment_closes_only_after_a_day(self, client, auth, chapa_api):
        deposit_id, tx_ref = _start_deposit(client, auth, chapa_api)
        del chapa_api.payments[tx_ref]  # Chapa has no record (checkout never finished)
        assert _deposit_status(client, auth, deposit_id) == "pending"
        _age_deposit(deposit_id, 30)
        assert _deposit_status(client, auth, deposit_id) == "failed"

    def test_a_failed_deposit_paid_later_is_still_credited_once(self, client, auth, chapa_api):
        deposit_id, tx_ref = _start_deposit(client, auth, chapa_api)
        chapa_api.payments[tx_ref]["status"] = "failed"
        assert _deposit_status(client, auth, deposit_id) == "failed"
        chapa_api.pay(tx_ref)
        assert client.get(f"/payments/chapa/callback?trx_ref={tx_ref}").json()["status"] == "succeeded"
        client.post("/payments/chapa/webhook", json={"tx_ref": tx_ref, "status": "success"})
        assert balance(client, auth) == 30000

    def test_a_different_transaction_in_the_answer_is_not_trusted(self, client, auth, chapa_api, monkeypatch):
        from dedan_platform import chapa

        deposit_id, tx_ref = _start_deposit(client, auth, chapa_api)
        chapa_api.pay(tx_ref)

        def swapped(request):
            response = chapa_api.handler(request)
            if "/transaction/verify/" in request.url.path:
                body = response.json()
                body["data"]["tx_ref"] = "endod-someone-else"
                return httpx.Response(200, json=body)
            return response

        monkeypatch.setattr(chapa, "_transport", httpx.MockTransport(swapped))
        assert _deposit_status(client, auth, deposit_id) == "pending"
        assert balance(client, auth) == 0

    def test_a_mismatched_amount_alerts_the_patient(self, client, auth, chapa_api):
        deposit_id, tx_ref = _start_deposit(client, auth, chapa_api)
        chapa_api.pay(tx_ref, amount="3.00")
        assert _deposit_status(client, auth, deposit_id) == "failed"
        items = client.get("/users/me/inbox", headers=auth).json()["items"]
        assert any(i["title"] == "Deposit needs checking" for i in items)
        assert balance(client, auth) == 0

    def test_a_reversed_deposit_is_taken_back_once(self, client, auth, chapa_api, listed):
        deposit_id = fund(client, auth, chapa_api)
        tx_ref = chapa_api.initialized[-1]["tx_ref"]
        assert book(client, auth).status_code == 201  # spends 158 birr of the 1000
        chapa_api.payments[tx_ref]["status"] = "reversed"
        # A plain notification does not re-open a settled deposit...
        client.post("/payments/chapa/webhook", json={"tx_ref": tx_ref, "status": "success"})
        assert balance(client, auth) == 100000 - 15800
        # ...a refund or reversal notice does (and Chapa's verify confirms it).
        for _ in range(2):
            resp = client.post("/payments/chapa/webhook", json={"tx_ref": tx_ref, "event": "charge.refunded"})
            assert resp.status_code == 200, resp.text
        assert balance(client, auth) == -15800
        kinds = [e["kind"] for e in client.get("/users/me/wallet", headers=auth).json()["entries"]]
        assert kinds.count("reversal") == 1
        assert _deposit_status(client, auth, deposit_id) == "reversed"

    def test_rechecks_take_turns(self, client, auth, chapa_api, monkeypatch):
        from dedan_platform import chapa, events_worker

        deposit_id, _tx_ref = _start_deposit(client, auth, chapa_api)
        _age_deposit(deposit_id, 1)
        calls = []

        def counting(request):
            calls.append(request.url.path)
            return chapa_api.handler(request)

        monkeypatch.setattr(chapa, "_transport", httpx.MockTransport(counting))
        events_worker.recheck_deposits()
        events_worker.recheck_deposits()  # checked a moment ago: skipped this round
        assert len(calls) == 1


class TestBookingSafety:
    def test_the_hospital_gets_a_normalised_phone_or_none(self, client, auth, monkeypatch):
        from dedan_platform import hospital_bookings, identity

        real = identity.get_profile_payload
        phones = iter(["0911 22 33 44", "+44 20 7946 0958 ext. 1234567"])
        monkeypatch.setattr(identity, "get_profile_payload", lambda uid: {**real(uid), "phone": next(phones)})
        assert hospital_bookings._patient(_user_id())["phone"] == "+251911223344"
        assert hospital_bookings._patient(_user_id())["phone"] is None

    def test_completion_before_confirmation_waits_for_it(self, client, auth, bus, listed, chapa_api, monkeypatch):
        from sqlalchemy import select

        from dedan_platform import eventbus
        from dedan_platform.db import session_scope
        from dedan_platform.models import HospitalPayout

        monkeypatch.setattr(eventbus, "RETRY_AFTER_MS", 0)
        fund(client, auth, chapa_api)
        aid = book(client, auth).json()["appointment"]["appointment_id"]
        decision = {"appointment_id": aid, "hospital_id": HOSPITAL}
        from_hospital(bus, "appointment.completed", {**decision, "status": "completed"})
        run_worker(bus)
        assert client.get(f"/users/me/appointments/{aid}", headers=auth).json()["status"] != "COMPLETED"
        from_hospital(bus, "appointment.confirmed", {**decision, "status": "confirmed"})
        run_worker(bus, rounds=2)
        assert client.get(f"/users/me/appointments/{aid}", headers=auth).json()["status"] == "COMPLETED"
        with session_scope() as session:
            assert session.scalar(select(HospitalPayout.status)) == "due"

    def test_completion_racing_a_patient_cancel_is_flagged(self, client, auth, bus, listed, chapa_api):
        from sqlalchemy import select

        from dedan_platform.db import session_scope
        from dedan_platform.models import HospitalPayout

        fund(client, auth, chapa_api)
        aid = book(client, auth).json()["appointment"]["appointment_id"]
        from_hospital(bus, "appointment.confirmed", {"appointment_id": aid, "hospital_id": HOSPITAL,
                                                     "status": "confirmed"})
        run_worker(bus)
        assert client.patch(f"/users/me/appointments/{aid}/status", headers=auth,
                            json={"status": "CANCELLED"}).status_code == 200
        from_hospital(bus, "appointment.completed", {"appointment_id": aid, "hospital_id": HOSPITAL,
                                                     "status": "completed"})
        run_worker(bus)
        assert balance(client, auth) == 100000
        with session_scope() as session:
            assert session.scalar(select(HospitalPayout.status)) == "disputed"

    def test_an_unanswered_booking_is_refunded_after_its_time(self, client, auth, bus, listed, chapa_api):
        from dedan_platform import hospital_bookings
        from dedan_platform.db import session_scope
        from dedan_platform.models import Appointment

        fund(client, auth, chapa_api)
        waiting = book(client, auth).json()["appointment"]["appointment_id"]
        future = book(client, auth, at=when(days=5)).json()["appointment"]["appointment_id"]
        run_worker(bus)
        with session_scope() as session:
            session.get(Appointment, waiting).scheduled_at = datetime.now(timezone.utc) - timedelta(hours=3)
        assert hospital_bookings.refund_unanswered() == 1
        assert hospital_bookings.refund_unanswered() == 0
        assert balance(client, auth) == 100000 - 15800
        assert client.get(f"/users/me/appointments/{waiting}", headers=auth).json()["status"] == "CANCELLED"
        assert client.get(f"/users/me/appointments/{future}", headers=auth).json()["status"] != "CANCELLED"
        run_worker(bus)
        assert sent(bus)[-1] == ("appointment.cancelled", {"appointment_id": waiting, "hospital_id": HOSPITAL,
                                                            "by": "patient"})

    def test_video_reminders_wait_for_the_doctor(self, client, auth, bus, listed, chapa_api):
        from sqlalchemy import func, select

        from dedan_platform.db import session_scope
        from dedan_platform.models import Notification

        fund(client, auth, chapa_api)
        resp = book(client, auth, mode="telehealth")
        aid = resp.json()["appointment"]["appointment_id"]
        assert resp.json()["reminders"]["queued"] == 0
        with session_scope() as session:
            before = session.scalar(select(func.count()).select_from(Notification)
                                    .where(Notification.appointment_id == aid))
        assert before == 0
        from_hospital(bus, "appointment.confirmed", {"appointment_id": aid, "hospital_id": HOSPITAL,
                                                     "status": "confirmed", "meeting_room": "endod-x1"})
        run_worker(bus)
        with session_scope() as session:
            after = session.scalar(select(func.count()).select_from(Notification)
                                   .where(Notification.appointment_id == aid))
        assert after >= 1

    def test_old_sample_facilities_keep_their_names_but_cannot_be_booked(self, client, auth, monkeypatch):
        from dedan_platform.care_navigation import get_facility

        monkeypatch.setenv("CARE_DEMO_DIRECTORY", "false")
        assert get_facility("et-addis-black-lion").name
        resp = client.post("/users/me/appointments", headers=auth, json={
            "scheduled_at": when().isoformat(), "timezone": "Africa/Addis_Ababa",
            "facility_id": "et-addis-black-lion"})
        assert resp.status_code == 400
