"""Partner hospitals, paying for each booking through Chapa, decisions from the
hospital service, refunds through Chapa, video joins and emergency numbers.

Redis is real-protocol but in memory (fakeredis); Chapa is an httpx mock that
behaves like its API (conftest.FakeChapa: payments and refunds).
"""

import base64
import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import fakeredis
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

PASSWORD = "Str0ng-pass!"
ADDIS = ZoneInfo("Africa/Addis_Ababa")
HOSPITAL = "a" * 32
JITSI_SECRET = "jitsi-secret"
WEBHOOK_SECRET = "hook-secret"


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


def when(days=2, hour=10):
    day = datetime.now(ADDIS) + timedelta(days=days)
    return day.replace(hour=hour, minute=0, second=0, microsecond=0)


def book(client, auth, mode="in_person", at=None, **extra):
    return client.post("/users/me/appointments", headers=auth, json={
        "scheduled_at": (at or when()).isoformat(), "timezone": "Africa/Addis_Ababa", "facility_id": HOSPITAL,
        "visit_mode": mode, "department": "general_medicine", **extra})


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



# --- helpers for paid bookings -------------------------------------------------------------

def paid(client, auth, chapa_api, mode="in_person", at=None, **extra):
    """Book and pay (Chapa's callback confirms it). Returns the appointment id."""
    return chapa_api.pay_booking(client, book(client, auth, mode=mode, at=at, **extra))


def appointment_of(client, auth, aid):
    return client.get(f"/users/me/appointments/{aid}", headers=auth).json()


def payment_row(aid):
    from sqlalchemy import select

    from dedan_platform.db import session_scope
    from dedan_platform.models import BookingPayment

    with session_scope() as session:
        payment = session.scalar(select(BookingPayment).where(BookingPayment.appointment_id == aid))
        session.expunge(payment)
        return payment


def refunds():
    from sqlalchemy import select

    from dedan_platform.db import session_scope
    from dedan_platform.models import BookingRefund

    with session_scope() as session:
        rows = list(session.scalars(select(BookingRefund).order_by(BookingRefund.created_at)))
        for row in rows:
            session.expunge(row)
        return rows


def make_refunds_due():
    from sqlalchemy import update

    from dedan_platform.db import session_scope
    from dedan_platform.models import BookingRefund

    with session_scope() as session:
        session.execute(update(BookingRefund).values(next_attempt_at=datetime.now(timezone.utc) - timedelta(seconds=1)))


def end_hold(aid, minutes=31):
    """Move the booking's hold into the past (as if ``minutes`` went by)."""
    from sqlalchemy import update

    from dedan_platform.db import session_scope
    from dedan_platform.models import Appointment, BookingPayment

    past = datetime.now(timezone.utc) - timedelta(minutes=minutes - 30)
    with session_scope() as session:
        session.execute(update(BookingPayment).where(BookingPayment.appointment_id == aid).values(
            expires_at=past, created_at=past - timedelta(minutes=30)))
        session.execute(update(Appointment).where(Appointment.id == aid).values(payment_due_at=past))


def inbox_items(client, auth):
    return client.get("/users/me/inbox", headers=auth).json()["items"]


def requested(bus):
    return [p for t, p in sent(bus) if t == "appointment.requested"]


# ---------------------------------------------------------------------------------------

class TestTopUpsAreGone:
    def test_deposit_endpoints_answer_410(self, client, auth, chapa_api):
        resp = client.post("/users/me/wallet/deposits", headers=auth, json={"amount": "100"})
        assert resp.status_code == 410 and "no longer available" in resp.json()["detail"].lower()
        assert client.post("/users/me/wallet/deposits", headers=auth, json={}).status_code == 410
        assert client.get("/users/me/wallet/deposits/anything", headers=auth).status_code == 410
        assert chapa_api.initialized == []
        # The old balance stays readable (empty: production never had money in it).
        assert client.get("/users/me/wallet", headers=auth).json()["balance"] == 0

    def test_the_quote_is_the_price_and_fee_without_a_balance(self, client, auth, listed):
        quote = client.get("/users/me/hospital-bookings/quote", headers=auth,
                           params={"hospital_id": HOSPITAL, "visit_mode": "telehealth"}).json()
        # 100 birr + 5 birr flat + 2% = 107 birr.
        assert quote == {"hospital_id": HOSPITAL, "visit_mode": "telehealth", "price": 10000, "service_fee": 700,
                         "total": 10700, "currency": "ETB"}


class TestPayingForABooking:
    def test_booking_holds_the_slot_and_opens_chapa_without_telling_the_hospital(self, client, auth, bus, listed,
                                                                                 chapa_api):
        resp = book(client, auth, notes="Headache")
        assert resp.status_code == 201, resp.text
        body = resp.json()
        appointment, payment = body["appointment"], body["payment"]
        assert appointment["hospital_booking"]["state"] == "awaiting_payment"
        assert appointment["hospital_booking"]["payment"]["status"] == "awaiting_payment"
        assert payment["price"] == 15000 and payment["service_fee"] == 800 and payment["total"] == 15800
        assert payment["checkout_url"] == f"https://checkout.chapa.co/{payment['tx_ref']}"
        assert body["reminders"]["queued"] == 0
        started = chapa_api.initialized[-1]
        assert started["amount"] == "158.00" and started["currency"] == "ETB"
        assert started["tx_ref"] == payment["tx_ref"]
        assert started["return_url"] == f"https://endod.example/interview?section=appointment&payment={payment['tx_ref']}"
        assert started["callback_url"] == "https://endod.example/api/payments/chapa/callback"
        assert len(started["customization"]["title"]) <= 16
        # The slot is held: the patient cannot book the same time twice.
        assert book(client, auth).status_code == 400
        # The appointments list offers "Pay now" until the hold ends.
        listed_row = client.get("/users/me/appointments", headers=auth).json()[0]
        hold = listed_row["hospital_booking"]["payment"]
        assert hold["checkout_url"] == payment["checkout_url"]
        due = datetime.fromisoformat(hold["due_at"])
        assert timedelta(minutes=29) < due - datetime.now(timezone.utc) <= timedelta(minutes=30)
        run_worker(bus)
        assert sent(bus) == []  # the hospital hears of paid bookings only

    def test_a_paid_booking_is_confirmed_once_by_webhook_and_the_hospital_told(self, client, auth, bus, listed,
                                                                                chapa_api):
        resp = book(client, auth, notes="Headache")
        tx_ref, aid = resp.json()["payment"]["tx_ref"], resp.json()["appointment"]["appointment_id"]
        chapa_api.pay(tx_ref)
        for _ in range(3):  # Chapa notifies more than once; the patient's return asks too
            assert client.post("/payments/chapa/webhook", json={"tx_ref": tx_ref, "status": "success"}).json() \
                == {"status": "paid"}
            client.get(f"/payments/chapa/callback?trx_ref={tx_ref}")
            client.get(f"/users/me/booking-payments/{tx_ref}", headers=auth)
        appointment = appointment_of(client, auth, aid)
        assert appointment["hospital_booking"]["state"] == "awaiting_hospital"
        assert appointment["hospital_booking"]["payment"] == {"status": "paid", "due_at": None, "checkout_url": None}
        run_worker(bus)
        [request] = requested(bus)
        # The hospital's event is exactly what it was before per-booking payments.
        assert set(request) == {"appointment_id", "hospital_id", "patient", "visit_mode", "service", "scheduled_at",
                                "duration_minutes", "notes", "price"}
        assert request["hospital_id"] == HOSPITAL and request["price"] == 15000 and request["visit_mode"] == "in_person"
        assert request["patient"]["name"] == "Almaz Tefera" and request["patient"]["dedan_id"].startswith("DE")
        assert request["notes"] == "Headache" and request["service"] == "general_medicine"
        assert datetime.fromisoformat(request["scheduled_at"]).tzinfo is not None
        assert payment_row(aid).provider_reference == "APabc123"
        assert [i["kind"] for i in inbox_items(client, auth)].count("appointment_booked") == 1

    def test_the_return_page_checks_with_chapa_and_is_private(self, client, auth, listed, chapa_api):
        resp = book(client, auth)
        tx_ref = resp.json()["payment"]["tx_ref"]
        # Back from Chapa without paying: the address alone confirms nothing.
        back = client.get(f"/users/me/booking-payments/{tx_ref}", headers=auth).json()
        assert back["status"] == "pending" and back["appointment"]["hospital_booking"]["state"] == "awaiting_payment"
        chapa_api.pay(tx_ref)
        back = client.get(f"/users/me/booking-payments/{tx_ref}", headers=auth).json()
        assert back["status"] == "paid" and back["appointment"]["hospital_booking"]["state"] == "awaiting_hospital"
        other = register(client, "b@example.com")
        assert client.get(f"/users/me/booking-payments/{tx_ref}", headers=other).status_code == 404
        assert client.get("/users/me/booking-payments/endod-nope", headers=auth).status_code == 404

    def test_a_forged_success_confirms_nothing(self, client, auth, bus, listed, chapa_api):
        aid = book(client, auth).json()["appointment"]["appointment_id"]
        tx_ref = payment_row(aid).tx_ref
        # Someone posts "success" without paying: Chapa's verify says pending.
        client.post("/payments/chapa/webhook", json={"tx_ref": tx_ref, "status": "success"})
        client.get(f"/payments/chapa/callback?trx_ref={tx_ref}&status=success")
        assert appointment_of(client, auth, aid)["hospital_booking"]["state"] == "awaiting_payment"
        run_worker(bus)
        assert requested(bus) == []

    @pytest.mark.parametrize("amount,currency", [("1.00", "ETB"), ("1580.00", "ETB"), ("158.00", "USD"),
                                                 ("158.00", None)])
    def test_another_amount_or_currency_is_never_accepted(self, client, auth, bus, listed, chapa_api, caplog,
                                                          amount, currency):
        resp = book(client, auth)
        aid, tx_ref = resp.json()["appointment"]["appointment_id"], resp.json()["payment"]["tx_ref"]
        chapa_api.pay(tx_ref, amount=amount, currency=currency)
        with caplog.at_level(logging.ERROR):
            for _ in range(2):
                assert client.get(f"/payments/chapa/callback?trx_ref={tx_ref}").json()["status"] == "mismatch"
        appointment = appointment_of(client, auth, aid)
        assert appointment["status"] == "CANCELLED" and appointment["hospital_booking"]["state"] == "payment_expired"
        assert appointment["hospital_booking"]["payment"]["status"] == "refund_pending"
        run_worker(bus)
        assert requested(bus) == []
        # A person refunds what was actually charged.
        [refund] = refunds()
        assert refund.status == "manual_refund_needed"
        assert "ALERT booking_payment_mismatch" in caplog.text and "ALERT manual_refund_needed" in caplog.text
        assert [i["title"] for i in inbox_items(client, auth)].count("Payment needs checking") == 1

    def test_the_webhook_signature_is_checked_when_configured(self, client, auth, bus, listed, chapa_api,
                                                              monkeypatch):
        monkeypatch.setenv("CHAPA_WEBHOOK_SECRET", WEBHOOK_SECRET)
        resp = book(client, auth)
        aid, tx_ref = resp.json()["appointment"]["appointment_id"], resp.json()["payment"]["tx_ref"]
        chapa_api.pay(tx_ref)
        body = json.dumps({"tx_ref": tx_ref, "status": "success"}).encode()
        for headers in ({"x-chapa-signature": "forged"}, {}):
            assert client.post("/payments/chapa/webhook", content=body, headers=headers).status_code == 401
        assert appointment_of(client, auth, aid)["hospital_booking"]["state"] == "awaiting_payment"
        good = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        resp = client.post("/payments/chapa/webhook", content=body, headers={"x-chapa-signature": good})
        assert resp.status_code == 200 and resp.json()["status"] == "paid"
        run_worker(bus)
        assert len(requested(bus)) == 1

    def test_a_chapa_outage_changes_nothing_until_it_answers(self, client, auth, listed, chapa_api):
        resp = book(client, auth)
        aid, tx_ref = resp.json()["appointment"]["appointment_id"], resp.json()["payment"]["tx_ref"]
        chapa_api.pay(tx_ref)
        for outage in (503, 429, 401):
            chapa_api.outage = outage
            assert client.get(f"/payments/chapa/callback?trx_ref={tx_ref}").status_code == 503
            assert client.get(f"/users/me/booking-payments/{tx_ref}", headers=auth).json()["status"] == "pending"
        chapa_api.outage = None
        assert client.get(f"/payments/chapa/callback?trx_ref={tx_ref}").json()["status"] == "paid"
        assert appointment_of(client, auth, aid)["hospital_booking"]["state"] == "awaiting_hospital"

    def test_a_different_transaction_in_chapas_answer_is_not_trusted(self, client, auth, listed, chapa_api,
                                                                     monkeypatch):
        import httpx

        from dedan_platform import chapa

        resp = book(client, auth)
        aid, tx_ref = resp.json()["appointment"]["appointment_id"], resp.json()["payment"]["tx_ref"]
        chapa_api.pay(tx_ref)

        def swapped(request):
            response = chapa_api.handler(request)
            if "/transaction/verify/" in request.url.path:
                body = response.json()
                body["data"]["tx_ref"] = "endod-someone-else"
                return httpx.Response(200, json=body)
            return response

        monkeypatch.setattr(chapa, "_transport", httpx.MockTransport(swapped))
        assert client.get(f"/payments/chapa/callback?trx_ref={tx_ref}").status_code == 503
        assert appointment_of(client, auth, aid)["hospital_booking"]["state"] == "awaiting_payment"

    def test_no_chapa_key_means_no_paid_bookings(self, client, auth, listed):
        resp = book(client, auth)
        assert resp.status_code == 503
        assert client.get("/users/me/appointments", headers=auth).json() == []

    def test_chapa_refusing_the_checkout_frees_the_slot(self, client, auth, listed, chapa_api, monkeypatch):
        import httpx

        from dedan_platform import chapa

        monkeypatch.setattr(chapa, "_transport", httpx.MockTransport(lambda request: httpx.Response(
            400, json={"status": "failed", "message": "Invalid phone"})))
        assert book(client, auth).status_code == 502
        [row] = client.get("/users/me/appointments", headers=auth).json()
        assert row["status"] == "CANCELLED" and row["hospital_booking"]["state"] == "payment_expired"
        monkeypatch.setattr(chapa, "_transport", httpx.MockTransport(chapa_api.handler))
        assert book(client, auth).status_code == 201  # the same time again

    def test_open_unpaid_holds_are_limited(self, client, auth, listed, chapa_api):
        from dedan_platform import booking_payments

        holds = [book(client, auth, at=when(days=2 + i)) for i in range(booking_payments.MAX_OPEN_HOLDS)]
        assert all(r.status_code == 201 for r in holds)
        refused = book(client, auth, at=when(days=9))
        assert refused.status_code == 409 and "waiting for payment" in refused.json()["detail"]
        assert len(chapa_api.initialized) == booking_payments.MAX_OPEN_HOLDS
        # Paying for one (or one expiring) makes room.
        chapa_api.pay_booking(client, holds[0])
        assert book(client, auth, at=when(days=9)).status_code == 201
        # Another patient has their own limit.
        assert book(client, register(client, "b@example.com"), at=when(days=9)).status_code == 201


class TestHolds:
    def test_an_unpaid_hold_expires_and_frees_the_slot(self, client, auth, bus, listed, chapa_api):
        from dedan_platform import booking_payments

        resp = book(client, auth)
        aid = resp.json()["appointment"]["appointment_id"]
        assert booking_payments.expire_holds() == 0  # not yet
        end_hold(aid)
        assert booking_payments.expire_holds() == 1
        assert booking_payments.expire_holds() == 0
        appointment = appointment_of(client, auth, aid)
        assert appointment["status"] == "CANCELLED" and appointment["hospital_booking"]["state"] == "payment_expired"
        assert appointment["hospital_booking"]["payment"] == {"status": "expired", "due_at": None,
                                                             "checkout_url": None}
        assert payment_row(aid).status == "expired"
        # The same time can be booked again, and the hospital never heard of the first.
        assert book(client, auth).status_code == 201
        run_worker(bus)
        assert sent(bus) == []

    def test_a_payment_whose_webhook_was_missed_is_confirmed_not_expired(self, client, auth, bus, listed, chapa_api):
        from dedan_platform import booking_payments

        resp = book(client, auth)
        aid = resp.json()["appointment"]["appointment_id"]
        chapa_api.pay(resp.json()["payment"]["tx_ref"])
        end_hold(aid)
        assert booking_payments.expire_holds() == 0
        assert appointment_of(client, auth, aid)["hospital_booking"]["state"] == "awaiting_hospital"
        assert refunds() == []

    def test_the_worker_rechecks_a_payment_whose_notifications_were_lost(self, client, auth, listed, chapa_api):
        from dedan_platform import booking_payments

        resp = book(client, auth)
        aid = resp.json()["appointment"]["appointment_id"]
        chapa_api.pay(resp.json()["payment"]["tx_ref"])
        assert booking_payments.recheck() == 0  # too new to need it
        end_hold(aid, minutes=5)  # created five minutes ago, hold still open
        assert booking_payments.recheck() == 1
        assert appointment_of(client, auth, aid)["hospital_booking"]["state"] == "awaiting_hospital"

    def test_a_payment_after_the_hold_ended_is_refunded_automatically(self, client, auth, bus, listed, chapa_api):
        from dedan_platform import booking_payments

        resp = book(client, auth)
        aid, tx_ref = resp.json()["appointment"]["appointment_id"], resp.json()["payment"]["tx_ref"]
        end_hold(aid)
        assert booking_payments.expire_holds() == 1
        chapa_api.pay(tx_ref)  # paid on Chapa's page after the slot was freed
        for _ in range(2):
            assert client.post("/payments/chapa/webhook", json={"tx_ref": tx_ref}).json()["status"] == "paid"
        appointment = appointment_of(client, auth, aid)
        assert appointment["hospital_booking"]["state"] == "payment_expired"
        assert appointment["hospital_booking"]["payment"]["status"] == "refund_pending"
        run_worker(bus)
        assert requested(bus) == []
        [refund] = refunds()
        assert refund.amount == 15800 and refund.status == "pending"
        assert booking_payments.process_refunds() == 1
        [request] = chapa_api.refund_requests
        assert request["tx_ref"] == tx_ref and request["amount"] == "158.00"
        items = [i for i in inbox_items(client, auth) if i["title"] == "Payment refunded"]
        assert len(items) == 1 and "refunded to your payment method (it can take a few days)" in items[0]["body"]

    def test_a_late_payment_found_by_the_worker_is_refunded_too(self, client, auth, listed, chapa_api):
        from dedan_platform import booking_payments

        resp = book(client, auth)
        aid, tx_ref = resp.json()["appointment"]["appointment_id"], resp.json()["payment"]["tx_ref"]
        end_hold(aid)
        chapa_api.outage = 503  # Chapa cannot answer when the hold ends: it still ends
        assert booking_payments.expire_holds() == 1
        chapa_api.outage = None
        chapa_api.pay(tx_ref)
        assert booking_payments.recheck() == 1
        assert [r.amount for r in refunds()] == [15800]

    def test_the_patient_can_drop_an_unpaid_hold(self, client, auth, bus, listed, chapa_api):
        resp = book(client, auth)
        aid, tx_ref = resp.json()["appointment"]["appointment_id"], resp.json()["payment"]["tx_ref"]
        dropped = client.patch(f"/users/me/appointments/{aid}/status", headers=auth, json={"status": "CANCELLED"})
        assert dropped.status_code == 200, dropped.text
        assert dropped.json()["hospital_booking"]["state"] == "cancelled"
        run_worker(bus)
        assert sent(bus) == []  # the hospital never heard of it
        assert book(client, auth).status_code == 201  # the slot is free
        # Paying the old checkout anyway gets the money back.
        chapa_api.pay(tx_ref)
        client.get(f"/payments/chapa/callback?trx_ref={tx_ref}")
        assert [r.amount for r in refunds()] == [15800]


class TestDecisionsAndRefunds:
    def test_the_hospital_confirms_in_person(self, client, auth, bus, listed, chapa_api):
        aid = paid(client, auth, chapa_api)
        from_hospital(bus, "appointment.confirmed", {"appointment_id": aid, "hospital_id": HOSPITAL,
                                                     "status": "confirmed", "meeting_room": None,
                                                     "doctor_name": None, "reason": None})
        run_worker(bus)
        appointment = appointment_of(client, auth, aid)
        assert appointment["status"] == "CONFIRMED" and appointment["hospital_booking"]["state"] == "confirmed"

    def test_video_waits_for_a_doctor_then_can_be_joined(self, client, auth, bus, listed, chapa_api):
        at = datetime.now(timezone.utc) + timedelta(minutes=20)
        aid = paid(client, auth, chapa_api, mode="telehealth", at=at)
        assert appointment_of(client, auth, aid)["hospital_booking"]["state"] == "awaiting_doctor"
        assert client.post(f"/users/me/appointments/{aid}/video", headers=auth).status_code == 409

        from_hospital(bus, "appointment.confirmed", {"appointment_id": aid, "hospital_id": HOSPITAL,
                                                     "status": "confirmed", "meeting_room": "endod-abc123",
                                                     "doctor_name": "Dr. Hiwot", "reason": None})
        run_worker(bus)
        appointment = appointment_of(client, auth, aid)
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

    def test_a_rejection_is_refunded_once_through_chapa(self, client, auth, bus, listed, chapa_api):
        from dedan_platform import booking_payments

        aid = paid(client, auth, chapa_api, mode="telehealth")
        tx_ref = payment_row(aid).tx_ref
        rejected = {"appointment_id": aid, "hospital_id": HOSPITAL, "status": "rejected",
                    "meeting_room": None, "doctor_name": None, "reason": "No doctor available"}
        from_hospital(bus, "appointment.rejected", rejected)
        from_hospital(bus, "appointment.rejected", rejected)  # sent twice (new event id)
        run_worker(bus)
        appointment = appointment_of(client, auth, aid)
        assert appointment["status"] == "CANCELLED" and appointment["hospital_booking"]["state"] == "rejected"
        assert appointment["hospital_booking"]["reason"] == "No doctor available"
        assert appointment["hospital_booking"]["payment"]["status"] == "refund_pending"
        # Sent to Chapa for the original payment, price and fee (107 birr).
        booking_payments.process_refunds()
        booking_payments.process_refunds()  # nothing more to send
        [request] = chapa_api.refund_requests
        [refund] = refunds()
        assert request["tx_ref"] == tx_ref and request["amount"] == "107.00"
        assert request["reference"] == refund.reference == f"endod-rf-{payment_row(aid).id}"
        assert refund.status == "submitted" and refund.chapa_ref_id == "MERC-REF-1"
        # Chapa is still processing it, then says it reached the payer.
        make_refunds_due()
        booking_payments.process_refunds()
        assert refunds()[0].status == "submitted"
        chapa_api.finish_refunds()
        make_refunds_due()
        booking_payments.process_refunds()
        assert refunds()[0].status == "succeeded"
        assert appointment_of(client, auth, aid)["hospital_booking"]["payment"]["status"] == "refunded"
        [item] = [i for i in inbox_items(client, auth) if i["title"] == "Visit declined by the hospital"]
        assert "107.00 birr is being refunded to your payment method (it can take a few days)." in item["body"]
        assert "balance" not in item["body"]

    def test_hospital_cancellation_refunds_and_completion_makes_the_payout_due(self, client, auth, bus, listed,
                                                                              chapa_api):
        from sqlalchemy import select

        from dedan_platform.db import session_scope
        from dedan_platform.models import HospitalPayout

        first = paid(client, auth, chapa_api)
        second = paid(client, auth, chapa_api, at=when(days=3))
        for aid in (first, second):
            from_hospital(bus, "appointment.confirmed", {"appointment_id": aid, "hospital_id": HOSPITAL,
                                                         "status": "confirmed"})
        from_hospital(bus, "appointment.cancelled", {"appointment_id": first, "hospital_id": HOSPITAL,
                                                     "status": "cancelled", "reason": "Doctor ill", "by": "hospital"})
        from_hospital(bus, "appointment.completed", {"appointment_id": second, "hospital_id": HOSPITAL,
                                                     "status": "completed"})
        run_worker(bus)
        with session_scope() as session:
            payouts = {p.appointment_id: p.status for p in session.scalars(select(HospitalPayout))}
        assert payouts == {first: "void", second: "due"}
        assert appointment_of(client, auth, second)["status"] == "COMPLETED"
        assert [(r.appointment_id, r.amount) for r in refunds()] == [(first, 15800)]

    def test_patient_cancel_refunds_and_tells_the_hospital(self, client, auth, bus, listed, chapa_api):
        aid = paid(client, auth, chapa_api)
        resp = client.patch(f"/users/me/appointments/{aid}/status", headers=auth, json={"status": "CANCELLED"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["hospital_booking"]["state"] == "cancelled"
        assert resp.json()["hospital_booking"]["payment"]["status"] == "refund_pending"
        run_worker(bus)
        assert sent(bus)[-1] == ("appointment.cancelled", {"appointment_id": aid, "hospital_id": HOSPITAL,
                                                            "by": "patient"})
        # A late confirmation, or a cancellation from the hospital, changes nothing (one refund per payment).
        from_hospital(bus, "appointment.confirmed", {"appointment_id": aid, "hospital_id": HOSPITAL,
                                                     "status": "confirmed"})
        from_hospital(bus, "appointment.cancelled", {"appointment_id": aid, "hospital_id": HOSPITAL,
                                                     "status": "cancelled"})
        run_worker(bus)
        assert appointment_of(client, auth, aid)["status"] == "CANCELLED"
        assert client.patch(f"/users/me/appointments/{aid}/status", headers=auth,
                            json={"status": "CANCELLED"}).status_code == 400
        assert len(refunds()) == 1
        [item] = [i for i in inbox_items(client, auth) if i["title"] == "Visit cancelled"]
        assert item["body"] == "158.00 birr is being refunded to your payment method (it can take a few days)."

    def test_the_hospital_owns_confirming_completing_and_times(self, client, auth, listed, chapa_api):
        aid = paid(client, auth, chapa_api)
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

        aid = paid(client, auth, chapa_api)
        with session_scope() as session:
            session.execute(update(Appointment).values(scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=5)))
        resp = client.patch(f"/users/me/appointments/{aid}/status", headers=auth, json={"status": "CANCELLED"})
        assert resp.status_code == 400 and "contact the hospital" in resp.json()["detail"]
        assert refunds() == []

    def test_video_needs_the_hospital_to_offer_it(self, client, auth, bus, listed, chapa_api):
        from_hospital(bus, "hospital.listed", {**LISTING, "version": 2, "video_enabled": False, "price_video": None})
        run_worker(bus)
        resp = book(client, auth, mode="telehealth")
        assert resp.status_code == 400 and "video" in resp.json()["detail"]
        assert chapa_api.initialized == []

    def test_events_wait_in_the_database_while_redis_is_down(self, client, auth, listed, chapa_api):
        from dedan_platform import eventbus

        paid(client, auth, chapa_api)
        later = fakeredis.FakeRedis(decode_responses=True)
        assert eventbus.publish_pending(later) == 1
        assert [t for t, _ in sent(later)] == ["appointment.requested"]

    def test_unknown_appointments_in_decisions_are_dead_lettered(self, client, auth, bus, listed):
        from_hospital(bus, "appointment.confirmed", {"appointment_id": "nope", "hospital_id": HOSPITAL,
                                                     "status": "confirmed"})
        run_worker(bus)
        assert len(bus.xrange("endod:dead-letter")) == 1

    def test_the_hospital_cannot_act_on_an_unpaid_hold(self, client, auth, bus, listed, chapa_api):
        aid = book(client, auth).json()["appointment"]["appointment_id"]
        for event in ("appointment.confirmed", "appointment.rejected", "appointment.completed"):
            from_hospital(bus, event, {"appointment_id": aid, "hospital_id": HOSPITAL})
        run_worker(bus)
        assert appointment_of(client, auth, aid)["hospital_booking"]["state"] == "awaiting_payment"
        assert refunds() == []


class TestRefundDelivery:
    def _rejected(self, client, auth, bus, chapa_api):
        aid = paid(client, auth, chapa_api)
        from_hospital(bus, "appointment.rejected", {"appointment_id": aid, "hospital_id": HOSPITAL})
        run_worker(bus)
        return aid

    def test_chapa_unavailable_is_retried_with_backoff(self, client, auth, bus, listed, chapa_api):
        from dedan_platform import booking_payments

        self._rejected(client, auth, bus, chapa_api)
        chapa_api.refund_outcome = 503
        assert booking_payments.process_refunds() == 1
        [refund] = refunds()
        assert refund.status == "pending" and refund.attempts == 1 and "503" in refund.last_error
        assert refund.maybe_accepted is True  # no answer is not a "no"
        wait = refund.next_attempt_at.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)
        assert timedelta(seconds=50) < wait <= timedelta(minutes=1)
        assert booking_payments.process_refunds() == 0  # not due yet
        chapa_api.refund_outcome = None
        make_refunds_due()
        assert booking_payments.process_refunds() == 1
        [refund] = refunds()
        assert refund.status == "submitted" and refund.attempts == 1 and refund.last_error is None
        assert len(chapa_api.refunds) == 1

    def test_a_refund_chapa_cannot_take_for_long_becomes_manual(self, client, auth, bus, listed, chapa_api, caplog):
        from sqlalchemy import select

        from dedan_platform import booking_payments
        from dedan_platform.db import session_scope
        from dedan_platform.models import UserEvent

        aid = self._rejected(client, auth, bus, chapa_api)
        chapa_api.refund_outcome = 503
        with caplog.at_level(logging.ERROR):
            for _ in range(len(booking_payments.REFUND_BACKOFF) + 1):
                make_refunds_due()
                booking_payments.process_refunds()
        [refund] = refunds()
        assert refund.status == "manual_refund_needed" and refund.next_attempt_at is None
        assert "ALERT manual_refund_needed" in caplog.text and refund.id in caplog.text
        # Chapa never answered: a refund may exist, and the alert says so.
        assert "refund_may_exist=yes" in caplog.text
        assert "check the Chapa dashboard before refunding" in caplog.text
        with session_scope() as session:
            audit = session.scalar(select(UserEvent).where(UserEvent.event_type == "payment.manual_refund_needed"))
            payload = json.loads(audit.payload)
            assert payload["amount"] == 15800 and payload["refund_may_already_exist"] is True
        # Left for a person: the worker sends nothing more.
        sent_before = len(chapa_api.refund_requests)
        make_refunds_due()
        booking_payments.process_refunds()
        assert len(chapa_api.refund_requests) == sent_before
        # The patient still sees it as on its way.
        assert appointment_of(client, auth, aid)["hospital_booking"]["payment"]["status"] == "refund_pending"

    def test_a_first_request_chapa_refuses_is_manual_at_once(self, client, auth, bus, listed, chapa_api, caplog):
        from dedan_platform import booking_payments

        self._rejected(client, auth, bus, chapa_api)
        chapa_api.refund_outcome = "refuse"
        with caplog.at_level(logging.ERROR):
            booking_payments.process_refunds()
        [refund] = refunds()
        assert refund.status == "manual_refund_needed" and "Insufficient balance" in refund.last_error
        assert "ALERT manual_refund_needed" in caplog.text and "refund_may_exist=no" in caplog.text
        assert "check the Chapa dashboard before refunding" in caplog.text

    def test_a_refusal_when_chapa_shows_the_payment_refunded_is_adopted(self, client, auth, bus, listed, chapa_api):
        from dedan_platform import booking_payments

        aid = self._rejected(client, auth, bus, chapa_api)
        chapa_api.refund_outcome = "refuse"
        chapa_api.payments[payment_row(aid).tx_ref]["status"] = "refunded"  # e.g. refunded from the dashboard
        booking_payments.process_refunds()
        assert refunds()[0].status == "succeeded"
        assert appointment_of(client, auth, aid)["hospital_booking"]["payment"]["status"] == "refunded"

    def test_a_lost_answer_is_looked_up_and_adopted_never_refunded_twice(self, client, auth, bus, listed, chapa_api,
                                                                         caplog):
        from dedan_platform import booking_payments

        aid = self._rejected(client, auth, bus, chapa_api)
        chapa_api.refund_outcome = "lost"  # Chapa accepts it, the answer times out
        booking_payments.process_refunds()
        [refund] = refunds()
        assert refund.status == "pending" and refund.maybe_accepted is True
        # The retry: Chapa (still processing) refuses the repeated reference.
        chapa_api.refund_outcome = None
        make_refunds_due()
        with caplog.at_level(logging.ERROR):
            booking_payments.process_refunds()
        [refund] = refunds()
        assert refund.status == "submitted" and "Duplicate reference" in refund.last_error
        assert "manual_refund_needed" not in caplog.text
        # Chapa finishes the one refund it has: adopted.
        chapa_api.finish_refunds()
        make_refunds_due()
        booking_payments.process_refunds()
        assert refunds()[0].status == "succeeded"
        assert len(chapa_api.refunds) == 1
        assert appointment_of(client, auth, aid)["hospital_booking"]["payment"]["status"] == "refunded"

    def test_an_unconfirmed_refund_left_too_long_is_manual_with_a_warning(self, client, auth, bus, listed, chapa_api,
                                                                          caplog):
        from sqlalchemy import update

        from dedan_platform import booking_payments
        from dedan_platform.db import session_scope
        from dedan_platform.models import BookingRefund

        self._rejected(client, auth, bus, chapa_api)
        chapa_api.refund_outcome = "lost"
        booking_payments.process_refunds()
        chapa_api.refund_outcome = None
        make_refunds_due()
        booking_payments.process_refunds()  # refused as a repeat: watched
        with session_scope() as session:
            session.execute(update(BookingRefund).values(created_at=datetime.now(timezone.utc) - timedelta(days=4)))
        make_refunds_due()
        with caplog.at_level(logging.ERROR):
            booking_payments.process_refunds()
        assert refunds()[0].status == "manual_refund_needed"
        assert "refund_may_exist=yes" in caplog.text and "MAY ALREADY HAVE BEEN ACCEPTED" in caplog.text

    def test_a_crash_mid_call_is_looked_up_before_anything_else(self, client, auth, bus, listed, chapa_api):
        from dedan_platform import booking_payments
        from dedan_platform.db import session_scope
        from dedan_platform.models import BookingRefund

        aid = self._rejected(client, auth, bus, chapa_api)
        booking_payments.process_refunds()  # Chapa accepts it ...
        with session_scope() as session:  # ... and the worker dies before recording that
            refund = session.get(BookingRefund, refunds()[0].id)
            refund.status, refund.chapa_ref_id = "pending", None
            refund.in_flight_since = datetime.now(timezone.utc) - timedelta(minutes=11)
        chapa_api.finish_refunds()  # meanwhile Chapa completed it
        make_refunds_due()
        booking_payments.process_refunds()
        assert refunds()[0].status == "succeeded"
        assert len(chapa_api.refund_requests) == 1  # looked up, never sent again
        assert appointment_of(client, auth, aid)["hospital_booking"]["payment"]["status"] == "refunded"

    def test_a_refund_chapa_reverses_is_manual(self, client, auth, bus, listed, chapa_api, caplog):
        from dedan_platform import booking_payments

        self._rejected(client, auth, bus, chapa_api)
        booking_payments.process_refunds()
        chapa_api.finish_refunds("reversed")
        make_refunds_due()
        with caplog.at_level(logging.ERROR):
            booking_payments.process_refunds()
        assert refunds()[0].status == "manual_refund_needed"
        assert "refund_may_exist=no" in caplog.text

    def test_one_refund_per_payment(self, client, auth, bus, listed, chapa_api):
        from sqlalchemy.exc import IntegrityError

        from dedan_platform import booking_payments
        from dedan_platform.db import session_scope
        from dedan_platform.models import BookingPayment, BookingRefund

        aid = self._rejected(client, auth, bus, chapa_api)
        payment = payment_row(aid)
        with session_scope() as session:
            again = booking_payments.request_refund(session, session.get(BookingPayment, payment.id), 15800, "again")
            assert again.reason == "Refund: visit declined by the hospital"
        with pytest.raises(IntegrityError):
            with session_scope() as session:
                session.add(BookingRefund(payment_id=payment.id, appointment_id=aid, user_id=payment.user_id,
                                          amount=1, reason="x", reference="endod-rf-other"))

    def test_two_workers_never_send_the_same_refund(self, client, auth, bus, listed, chapa_api, monkeypatch):
        from dedan_platform import booking_payments, chapa

        self._rejected(client, auth, bus, chapa_api)
        [refund] = refunds()
        real = chapa.refund

        def slow(*args, **kwargs):
            # Another worker picks the same refund while this one is at Chapa.
            assert booking_payments._attempt(refund.id) is False
            return real(*args, **kwargs)

        monkeypatch.setattr(chapa, "refund", slow)
        assert booking_payments.process_refunds() == 1
        assert len(chapa_api.refund_requests) == 1

    def test_no_chapa_key_burns_no_attempts(self, client, auth, bus, listed, chapa_api, monkeypatch, caplog):
        from dedan_platform import booking_payments

        self._rejected(client, auth, bus, chapa_api)
        monkeypatch.delenv("CHAPA_SECRET_KEY")
        with caplog.at_level(logging.WARNING):
            for _ in range(10):
                make_refunds_due()
                assert booking_payments.process_refunds() == 0
        [refund] = refunds()
        assert refund.status == "pending" and refund.attempts == 0
        assert "refunds_waiting chapa_not_configured" in caplog.text
        # A worker that finds the key gone mid-round leaves it pending, uncounted, for a few minutes.
        assert booking_payments._attempt(refund.id) is False
        [refund] = refunds()
        assert refund.status == "pending" and refund.attempts == 0 and refund.in_flight_since is None
        wait = refund.next_attempt_at.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)
        assert timedelta(minutes=4) < wait <= booking_payments.NOT_CONFIGURED_WAIT
        assert chapa_api.refund_requests == []
        # The key is set again: it goes out.
        monkeypatch.setenv("CHAPA_SECRET_KEY", "CHASECK_TEST-key")
        make_refunds_due()
        assert booking_payments.process_refunds() == 1 and refunds()[0].status == "submitted"


class TestChargebacks:
    def test_a_reversed_payment_cancels_the_booking_and_tells_everyone(self, client, auth, bus, listed, chapa_api,
                                                                       caplog):
        from sqlalchemy import select

        from dedan_platform.db import session_scope
        from dedan_platform.models import HospitalPayout, UserEvent

        aid = paid(client, auth, chapa_api)
        tx_ref = payment_row(aid).tx_ref
        run_worker(bus)
        chapa_api.payments[tx_ref]["status"] = "reversed"
        # An ordinary notice does not re-open a paid booking ...
        client.post("/payments/chapa/webhook", json={"tx_ref": tx_ref, "status": "success"})
        assert appointment_of(client, auth, aid)["hospital_booking"]["state"] == "awaiting_hospital"
        # ... Chapa's reversal notice does, and its verify confirms it.
        with caplog.at_level(logging.ERROR):
            for _ in range(2):
                resp = client.post("/payments/chapa/webhook",
                                   json={"tx_ref": tx_ref, "event": "charge.reversed", "status": "reversed"})
                assert resp.status_code == 200 and resp.json()["status"] == "reversed"
        appointment = appointment_of(client, auth, aid)
        assert appointment["status"] == "CANCELLED" and appointment["hospital_booking"]["state"] == "cancelled"
        assert appointment["hospital_booking"]["payment"]["status"] == "reversed"
        run_worker(bus)
        assert [e for e in sent(bus) if e[0] == "appointment.cancelled"] == [
            ("appointment.cancelled", {"appointment_id": aid, "hospital_id": HOSPITAL, "by": "endod"})]
        assert refunds() == []
        assert "ALERT booking_payment_reversed" in caplog.text
        with session_scope() as session:
            assert session.scalar(select(HospitalPayout.status)) == "void"
            assert session.scalar(select(UserEvent.id).where(UserEvent.event_type == "payment.reversed"))
        assert [i["title"] for i in inbox_items(client, auth)].count("Booking cancelled: payment reversed") == 1

    def test_a_completed_visit_reversed_is_flagged_for_the_payout(self, client, auth, bus, listed, chapa_api):
        from sqlalchemy import select

        from dedan_platform.db import session_scope
        from dedan_platform.models import HospitalPayout

        aid = paid(client, auth, chapa_api)
        from_hospital(bus, "appointment.completed", {"appointment_id": aid, "hospital_id": HOSPITAL})
        run_worker(bus)
        tx_ref = payment_row(aid).tx_ref
        chapa_api.payments[tx_ref]["status"] = "refunded"
        client.post("/payments/chapa/webhook", json={"tx_ref": tx_ref, "event": "charge.refunded"})
        assert appointment_of(client, auth, aid)["status"] == "COMPLETED"
        with session_scope() as session:
            assert session.scalar(select(HospitalPayout.status)) == "disputed"

    def test_our_own_refund_completing_is_not_a_chargeback(self, client, auth, bus, listed, chapa_api):
        from dedan_platform import booking_payments

        aid = paid(client, auth, chapa_api)
        from_hospital(bus, "appointment.rejected", {"appointment_id": aid, "hospital_id": HOSPITAL})
        run_worker(bus)
        booking_payments.process_refunds()
        chapa_api.finish_refunds()
        client.post("/payments/chapa/webhook", json={"tx_ref": payment_row(aid).tx_ref, "event": "charge.refunded"})
        assert refunds()[0].status == "succeeded"
        appointment = appointment_of(client, auth, aid)
        assert appointment["hospital_booking"]["state"] == "rejected"
        assert appointment["hospital_booking"]["payment"]["status"] == "refunded"
        assert not any(i["kind"] == "payment_reversed" for i in inbox_items(client, auth))


class TestLateAndLockedPayments:
    def test_a_payment_too_close_to_the_visit_is_refunded_not_sent(self, client, auth, bus, listed, chapa_api):
        from sqlalchemy import update

        from dedan_platform.db import session_scope
        from dedan_platform.models import Appointment

        resp = book(client, auth, at=datetime.now(timezone.utc) + timedelta(minutes=20))
        aid = resp.json()["appointment"]["appointment_id"]
        with session_scope() as session:  # the patient pays when the visit is minutes away
            session.execute(update(Appointment).where(Appointment.id == aid).values(
                scheduled_at=datetime.now(timezone.utc) + timedelta(minutes=3)))
        chapa_api.pay_booking(client, resp)
        appointment = appointment_of(client, auth, aid)
        assert appointment["status"] == "CANCELLED" and appointment["hospital_booking"]["state"] == "payment_expired"
        assert appointment["hospital_booking"]["payment"]["status"] == "refund_pending"
        assert payment_row(aid).status == "paid"
        assert [(r.appointment_id, r.amount) for r in refunds()] == [(aid, 15800)]
        run_worker(bus)
        assert requested(bus) == []
        items = [i for i in inbox_items(client, auth) if i["title"] == "Payment refunded"]
        assert len(items) == 1 and "too close to the visit time" in items[0]["body"]

    def test_late_payments_are_looked_for_through_the_checkout_lifetime(self, client, auth, listed, chapa_api):
        from sqlalchemy import update

        from dedan_platform import booking_payments
        from dedan_platform.db import session_scope
        from dedan_platform.models import BookingPayment

        resp = book(client, auth)
        aid, tx_ref = resp.json()["appointment"]["appointment_id"], resp.json()["payment"]["tx_ref"]
        end_hold(aid)
        assert booking_payments.expire_holds() == 1

        def aged(days, checked_hours_ago=None):
            now = datetime.now(timezone.utc)
            with session_scope() as session:
                session.execute(update(BookingPayment).where(BookingPayment.tx_ref == tx_ref).values(
                    expires_at=now - timedelta(days=days),
                    last_checked_at=None if checked_hours_ago is None else now - timedelta(hours=checked_hours_ago)))

        aged(3, checked_hours_ago=1)
        assert booking_payments.recheck() == 0  # three days on: every six hours
        aged(3, checked_hours_ago=7)
        assert booking_payments.recheck() == 1
        aged(8)
        assert booking_payments.recheck() == 0  # past the window
        aged(6)
        chapa_api.pay(tx_ref)  # paid six days later
        assert booking_payments.recheck() == 1
        assert [r.amount for r in refunds()] == [15800]

    def test_the_check_schedule_slows_down_with_age(self):
        from dedan_platform.booking_payments import _late_check_due

        now = datetime.now(timezone.utc)
        ago = lambda **kw: now - timedelta(**kw)  # noqa: E731
        assert _late_check_due(ago(minutes=30), ago(minutes=6), now)
        assert not _late_check_due(ago(hours=5), ago(minutes=20), now)
        assert _late_check_due(ago(hours=5), ago(minutes=31), now)
        assert not _late_check_due(ago(days=2), ago(hours=5), now)
        assert _late_check_due(ago(days=6, hours=23), None, now)
        assert not _late_check_due(ago(days=7, minutes=1), None, now)

    def test_one_failing_hold_does_not_keep_the_others(self, client, auth, listed, chapa_api, monkeypatch):
        from dedan_platform import booking_payments

        first = book(client, auth).json()
        second = book(client, auth, at=when(days=3)).json()
        for body in (first, second):
            end_hold(body["appointment"]["appointment_id"])
        real = booking_payments.settle

        def broken(tx_ref, *args, **kwargs):
            if tx_ref == first["payment"]["tx_ref"]:
                raise RuntimeError("boom")
            return real(tx_ref, *args, **kwargs)

        monkeypatch.setattr(booking_payments, "settle", broken)
        assert booking_payments.expire_holds() == 1
        assert payment_row(second["appointment"]["appointment_id"]).status == "expired"
        assert payment_row(first["appointment"]["appointment_id"]).status == "pending"  # next round

    def test_booking_rows_are_locked_appointment_first(self, client, auth, listed, chapa_api):
        from sqlalchemy import event

        from dedan_platform import booking_payments, db

        tx_ref = book(client, auth).json()["payment"]["tx_ref"]
        statements = []

        def capture(_conn, _cursor, statement, *_args):
            statements.append(statement)

        engine = db.get_engine()
        event.listen(engine, "before_cursor_execute", capture)
        try:
            with db.session_scope() as session:
                appointment, payment = booking_payments.lock_booking(session, tx_ref=tx_ref)
                assert payment.tx_ref == tx_ref and appointment.id == payment.appointment_id
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        reads = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
        tables = ["appointments" if "FROM appointments" in s else "booking_payments" for s in reads[1:]]
        assert tables == ["appointments", "booking_payments"]


class TestPaymentsStatus:
    def test_the_app_can_tell_whether_online_payment_is_on(self, client, monkeypatch):
        monkeypatch.delenv("CHAPA_SECRET_KEY", raising=False)
        off = client.get("/payments/status").json()
        assert off == {"online_payments": False, "checkout_origins": ["https://checkout.chapa.co"]}
        assert client.get("/users/me/payments/status").json() == off
        monkeypatch.setenv("CHAPA_SECRET_KEY", "CHASECK_TEST-key")
        assert client.get("/payments/status").json()["online_payments"] is True
        # A stand-in Chapa (tests) adds its own origin; Chapa's own never does.
        monkeypatch.setenv("CHAPA_BASE_URL", "http://127.0.0.1:8012/v1")
        assert client.get("/payments/status").json()["checkout_origins"] == [
            "https://checkout.chapa.co", "http://127.0.0.1:8012"]
        monkeypatch.setenv("CHAPA_BASE_URL", "https://api.chapa.co/v1")
        assert client.get("/payments/status").json()["checkout_origins"] == ["https://checkout.chapa.co"]


class TestBookingSafety:
    def test_the_hospital_gets_a_normalised_phone_or_none(self, client, auth, monkeypatch):
        from dedan_platform import hospital_bookings, identity

        real = identity.get_profile_payload
        phones = iter(["0911 22 33 44", "+44 20 7946 0958 ext. 1234567"])
        monkeypatch.setattr(identity, "get_profile_payload", lambda uid: {**real(uid), "phone": next(phones)})
        assert hospital_bookings._patient(_user_id())["phone"] == "+251911223344"
        assert hospital_bookings._patient(_user_id())["phone"] is None

    def test_a_completion_before_or_without_its_confirmation_counts(self, client, auth, bus, listed, chapa_api):
        from sqlalchemy import select

        from dedan_platform import hospital_bookings
        from dedan_platform.db import session_scope
        from dedan_platform.models import Appointment, HospitalPayout

        aid = paid(client, auth, chapa_api)
        decision = {"appointment_id": aid, "hospital_id": HOSPITAL}
        from_hospital(bus, "appointment.completed", {**decision, "status": "completed", "doctor_name": "Dr. Abebe"})
        run_worker(bus)
        appointment = appointment_of(client, auth, aid)
        assert appointment["status"] == "COMPLETED" and appointment["provider_name"] == "Dr. Abebe"
        # The late confirmation changes nothing, and the visit is never refunded as unanswered.
        from_hospital(bus, "appointment.confirmed", {**decision, "status": "confirmed"})
        run_worker(bus)
        with session_scope() as session:
            session.get(Appointment, aid).scheduled_at = datetime.now(timezone.utc) - timedelta(hours=3)
        assert hospital_bookings.refund_unanswered() == 0
        assert appointment_of(client, auth, aid)["status"] == "COMPLETED"
        assert refunds() == []
        with session_scope() as session:
            assert session.scalar(select(HospitalPayout.status)) == "due"

    def test_completion_racing_a_patient_cancel_is_flagged(self, client, auth, bus, listed, chapa_api):
        from sqlalchemy import select

        from dedan_platform.db import session_scope
        from dedan_platform.models import HospitalPayout

        aid = paid(client, auth, chapa_api)
        from_hospital(bus, "appointment.confirmed", {"appointment_id": aid, "hospital_id": HOSPITAL,
                                                     "status": "confirmed"})
        run_worker(bus)
        assert client.patch(f"/users/me/appointments/{aid}/status", headers=auth,
                            json={"status": "CANCELLED"}).status_code == 200
        from_hospital(bus, "appointment.completed", {"appointment_id": aid, "hospital_id": HOSPITAL,
                                                     "status": "completed"})
        run_worker(bus)
        assert len(refunds()) == 1
        with session_scope() as session:
            assert session.scalar(select(HospitalPayout.status)) == "disputed"

    def test_an_unanswered_booking_is_refunded_after_its_time(self, client, auth, bus, listed, chapa_api):
        from dedan_platform import hospital_bookings
        from dedan_platform.db import session_scope
        from dedan_platform.models import Appointment

        waiting = paid(client, auth, chapa_api)
        future = paid(client, auth, chapa_api, at=when(days=5))
        run_worker(bus)
        with session_scope() as session:
            session.get(Appointment, waiting).scheduled_at = datetime.now(timezone.utc) - timedelta(hours=3)
        assert hospital_bookings.refund_unanswered() == 1
        assert hospital_bookings.refund_unanswered() == 0
        assert [(r.appointment_id, r.amount) for r in refunds()] == [(waiting, 15800)]
        assert appointment_of(client, auth, waiting)["status"] == "CANCELLED"
        assert appointment_of(client, auth, future)["status"] != "CANCELLED"
        run_worker(bus)
        assert sent(bus)[-1] == ("appointment.cancelled", {"appointment_id": waiting, "hospital_id": HOSPITAL,
                                                            "by": "endod"})
        [item] = [i for i in inbox_items(client, auth) if (i["link"] or {}).get("id") == waiting and i["title"] == "Visit cancelled"]
        assert item["body"] == ("The hospital did not answer. 158.00 birr is being refunded to your payment method "
                                "(it can take a few days).")

    def test_video_reminders_wait_for_the_doctor(self, client, auth, bus, listed, chapa_api):
        from sqlalchemy import func, select

        from dedan_platform.db import session_scope
        from dedan_platform.models import Notification

        aid = paid(client, auth, chapa_api, mode="telehealth")
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

    def test_in_person_reminders_start_once_paid(self, client, auth, listed, chapa_api):
        from sqlalchemy import func, select

        from dedan_platform.db import session_scope
        from dedan_platform.models import Notification

        def count(aid):
            with session_scope() as session:
                return session.scalar(select(func.count()).select_from(Notification)
                                      .where(Notification.appointment_id == aid))

        resp = book(client, auth)
        aid = resp.json()["appointment"]["appointment_id"]
        assert count(aid) == 0
        chapa_api.pay_booking(client, resp)
        assert count(aid) >= 1

    def test_old_sample_facilities_keep_their_names_but_cannot_be_booked(self, client, auth, monkeypatch):
        from dedan_platform.care_navigation import get_facility

        monkeypatch.setenv("CARE_DEMO_DIRECTORY", "false")
        assert get_facility("et-addis-black-lion").name
        resp = client.post("/users/me/appointments", headers=auth, json={
            "scheduled_at": when().isoformat(), "timezone": "Africa/Addis_Ababa",
            "facility_id": "et-addis-black-lion"})
        assert resp.status_code == 400


def _user_id(email="a@example.com"):
    from dedan_platform import identity

    return identity.find_user_by_email(email).id


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



class TestRefundTexts:
    @pytest.mark.parametrize("language,expected", [
        ("en", "158.00 birr is being refunded to your payment method (it can take a few days)."),
        ("am", "158.00 ብር ወደ ከፈሉበት የክፍያ መንገድ ተመላሽ ይደረጋል (ጥቂት ቀናት ሊወስድ ይችላል)።"),
    ])
    def test_refund_texts_name_the_payment_method_not_a_balance(self, language, expected):
        from dedan_platform import patient_sms

        for template in (patient_sms.REFUND, patient_sms.BOOKING_DECLINED, patient_sms.BOOKING_CANCELLED,
                         patient_sms.BOOKING_UNANSWERED):
            text = patient_sms.render({"template": template, "payload": {
                "language": language, "params": {"amount": 15800, "when": "01/11/2026 10:30"}}})
            assert expected in text
            assert "balance" not in text and "ሂሳብ" not in text

    def test_an_amharic_patient_gets_the_refund_notice_in_amharic(self, client, auth, bus, listed, chapa_api):
        from dedan_platform import identity

        identity.update_preferences(_user_id(), {"language": "am"})
        aid = paid(client, auth, chapa_api)
        from_hospital(bus, "appointment.rejected", {"appointment_id": aid, "hospital_id": HOSPITAL,
                                                    "reason": "No doctor"})
        run_worker(bus)
        [item] = [i for i in inbox_items(client, auth) if i["kind"] == "appointment_cancelled"]
        assert item["title"] == "ሆስፒታሉ ቀጠሮውን አልተቀበለም"
        assert item["body"].startswith("158.00 ብር ወደ ከፈሉበት የክፍያ መንገድ ተመላሽ ይደረጋል")
