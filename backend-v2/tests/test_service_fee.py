"""Endod's service fee (docs/service-fee.md): the super admin's settings
(validated, audited, sent to the hospital service), the fee on every paid
booking (online and at the hospital; none on a free one), hospital charges
(bills in the app, a non-clinical SMS), and Endod's fee ledger with its
summaries and settlement through the admin API.
"""

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from test_patient_history import (  # noqa: F401 -- fixtures
    HOSPITAL, LISTING, bus, client, dead_letters, deliver_due, from_hospital, hexid, inbox, listed, patient, register,
    run_worker, sent, texts,
)

ADMIN_KEY = "admin-api-test-key-0123456789abcdefghij"
HEADERS = {"X-Superadmin-Key": ADMIN_KEY}
ACTOR = "ops@endod.example"
ADDIS = ZoneInfo("Africa/Addis_Ababa")
OTHER = "c" * 32


@pytest.fixture
def admin(client, monkeypatch):
    import main_internal

    monkeypatch.setenv("SUPERADMIN_API_KEY", ADMIN_KEY)
    monkeypatch.setenv("PLATFORM_ADMIN_KEY", "platform-admin-test-key-0123456789abcdef")
    monkeypatch.setenv("INTERNAL_ALLOWED_HOSTS", "testserver")
    return TestClient(main_internal.create_app())


@pytest.fixture
def default_fee(monkeypatch):
    """No environment override: the built-in defaults (25 birr flat, no share, on)."""
    for name in ("SERVICE_FEE_FLAT_SANTIM", "SERVICE_FEE_PERCENT_BP", "SERVICE_FEE_ENABLED"):
        monkeypatch.delenv(name, raising=False)


def when(days=2, hour=10):
    day = datetime.now(ADDIS) + timedelta(days=days)
    return day.replace(hour=hour, minute=0, second=0, microsecond=0)


def book(client, auth, at=None):
    return client.post("/users/me/appointments", headers=auth, json={
        "scheduled_at": (at or when()).isoformat(), "timezone": "Africa/Addis_Ababa", "facility_id": HOSPITAL,
        "visit_mode": "in_person", "department": "general_medicine"})


def change(admin, **body):
    values = {"enabled": True, "flat_santim": 2500, "percent_bp": 0, "reason": "CEO decision", "actor_email": ACTOR}
    return admin.put("/internal/admin/fees", headers=HEADERS, json={**values, **body})


def ledger():
    from dedan_platform.db import session_scope
    from dedan_platform.models import FeeLedgerEntry

    with session_scope() as session:
        return [{"source": (r.source_type, r.source_id), "hospital_id": r.hospital_id, "dedan_id": r.dedan_id,
                 "subtotal": r.subtotal, "fee": r.fee, "total": r.total, "method": r.method,
                 "collected_by": r.collected_by, "status": r.settlement_status, "id": r.id}
                for r in session.scalars(select(FeeLedgerEntry).order_by(FeeLedgerEntry.created_at))]


# --- the rule -------------------------------------------------------------------------------

class TestTheRule:
    def test_defaults_are_25_birr_flat_and_on(self, client, default_fee):
        from dedan_platform import fee_settings

        settings = fee_settings.current()
        assert (settings.enabled, settings.flat_santim, settings.percent_bp, settings.version) == (True, 2500, 0, 0)
        # The CEO's example: a 200 ETB bill costs the patient 225 ETB; a second one, the same again.
        assert fee_settings.fee_for(20_000) == 2500

    def test_percent_is_rounded_half_up_to_the_santim_and_free_is_free(self, client, monkeypatch):
        from dedan_platform import fee_settings

        settings = fee_settings.FeeSettings(True, 1000, 150, 1, None, None)
        assert fee_settings.fee_for(333, settings) == 1000 + 5  # 4.995 santim -> 5
        assert fee_settings.fee_for(300, settings) == 1000 + 5  # 4.5 -> 5
        assert fee_settings.fee_for(299, settings) == 1000 + 4  # 4.485 -> 4
        assert fee_settings.fee_for(0, settings) == 0
        off = fee_settings.FeeSettings(False, 1000, 150, 2, None, None)
        assert fee_settings.fee_for(20_000, off) == 0

    def test_the_environment_is_only_the_initial_default(self, client, admin, monkeypatch):
        from dedan_platform import fee_settings

        monkeypatch.setenv("SERVICE_FEE_FLAT_SANTIM", "700")
        assert fee_settings.current().flat_santim == 700
        assert change(admin, flat_santim=3000).status_code == 200
        assert fee_settings.current().flat_santim == 3000  # the database wins from now on


# --- settings through the admin API -----------------------------------------------------------

class TestSettings:
    def test_read_shows_the_settings_and_a_200_birr_example(self, client, admin, default_fee):
        resp = admin.get("/internal/admin/fees", headers=HEADERS)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["enabled"] is True and body["flat_santim"] == 2500 and body["percent_bp"] == 0
        assert body["example"] == {"subtotal": 20_000, "service_fee": 2500, "total": 22_500}
        assert body["history"] == [] and body["version"] == 0

    def test_the_key_is_required(self, client, admin):
        assert admin.get("/internal/admin/fees").status_code == 401
        assert admin.put("/internal/admin/fees", headers={"X-Superadmin-Key": "x" * 40},
                         json={}).status_code == 401

    @pytest.mark.parametrize("body,detail", [
        ({"flat_santim": 100_001}, "less than or equal"),
        ({"flat_santim": -1}, "greater than or equal"),
        ({"percent_bp": 2001}, "less than or equal"),
        ({"flat_santim": "2500"}, "valid integer"),
        ({"flat_santim": 25.5}, "valid integer"),
        ({"enabled": True, "flat_santim": 0, "percent_bp": 0}, "flat amount or a percentage"),
        ({"reason": "  "}, "at least 3"),
        ({"actor_email": "not-an-email"}, "email"),
    ])
    def test_changes_are_validated(self, client, admin, body, detail):
        resp = change(admin, **body)
        assert resp.status_code == 422, resp.text
        assert detail in json.dumps(resp.json())
        assert admin.get("/internal/admin/fees", headers=HEADERS).json()["version"] == 0

    def test_a_change_is_audited_and_sent_to_the_hospital_service(self, client, admin, bus):
        resp = change(admin, flat_santim=3000, percent_bp=150, reason="  New pricing from the CEO ",
                      actor_email="Ops@Endod.Example")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert (body["enabled"], body["flat_santim"], body["percent_bp"], body["version"]) == (True, 3000, 150, 1)
        assert body["updated_by"] == ACTOR
        assert body["example"] == {"subtotal": 20_000, "service_fee": 3300, "total": 23_300}
        [entry] = body["history"]
        assert entry["actor_email"] == ACTOR and entry["reason"] == "New pricing from the CEO"
        assert entry["before"] == {"enabled": True, "flat_santim": 500, "percent_bp": 0}
        assert entry["after"] == {"enabled": True, "flat_santim": 3000, "percent_bp": 150}
        # Switched off: no fee from now on; a new version.
        assert change(admin, enabled=False, flat_santim=0, percent_bp=0).json()["version"] == 2
        run_worker(bus)
        updates = sent(bus, "fees.updated")
        assert [(u["version"], u["enabled"], u["flat_santim"], u["percent_bp"]) for u in updates] == [
            (1, True, 3000, 150), (2, False, 0, 0)]
        assert all(u["currency"] == "ETB" and u["updated_at"] for u in updates)

    def test_the_worker_sends_the_settings_at_start_and_now_and_then(self, client, bus):
        from dedan_platform import eventbus, events_worker, fee_settings

        events_worker._fees_sent_at["at"] = None
        assert events_worker.broadcast_fees_if_due(now=1000.0) is True
        assert events_worker.broadcast_fees_if_due(now=1001.0) is False
        assert events_worker.broadcast_fees_if_due(now=1000.0 + fee_settings.BROADCAST_EVERY) is True
        eventbus.publish_pending(bus)
        assert [u["version"] for u in sent(bus, "fees.updated")] == [0, 0]


# --- bookings ---------------------------------------------------------------------------------

class TestBookings:
    def test_a_visit_paid_at_the_hospital_carries_the_fee_from_the_settings(self, client, admin, bus, patient,
                                                                            listed):
        change(admin, flat_santim=2500)
        quote = client.get("/users/me/hospital-bookings/quote", headers=patient["auth"],
                           params={"hospital_id": HOSPITAL}).json()
        assert quote["payment"] == "at_hospital" and quote["service_fee"] == 2500 and quote["total"] == 12_500
        resp = book(client, patient["auth"])
        assert resp.status_code == 201, resp.text
        booking = resp.json()["appointment"]["hospital_booking"]
        assert (booking["price"], booking["service_fee"], booking["total"]) == (10_000, 2500, 12_500)
        run_worker(bus)
        [request] = sent(bus, "appointment.requested")
        assert request["payment"] == "at_hospital" and request["service_fee"] == 2500 and request["total"] == 12_500
        [item] = [i for i in inbox(client, patient["auth"]) if i["kind"] == "appointment_booked"]
        assert "Pay ETB 125.00 at the hospital (including the Endod service fee of ETB 25.00)." in item["body"]
        assert ledger() == []  # nothing is paid yet

    def test_a_free_visit_has_no_fee(self, client, bus, patient):
        from_hospital(bus, "hospital.listed", {**LISTING, "price_in_person": 0})
        run_worker(bus)
        resp = book(client, patient["auth"])
        assert resp.status_code == 201, resp.text
        booking = resp.json()["appointment"]["hospital_booking"]
        assert (booking["price"], booking["service_fee"], booking["total"]) == (0, 0, 0)
        assert booking["payment"]["status"] == "paid"
        from_hospital(bus, "appointment.completed", {"appointment_id": resp.json()["appointment"]["appointment_id"],
                                                     "hospital_id": HOSPITAL})
        run_worker(bus)
        assert ledger() == []

    def test_paid_at_the_hospital_the_fee_is_owed_by_the_hospital(self, client, bus, patient, listed):
        aid = book(client, patient["auth"]).json()["appointment"]["appointment_id"]
        from_hospital(bus, "appointment.paid", {"appointment_id": aid, "hospital_id": HOSPITAL, "method": "cash",
                                                "reference": "RCPT-77",
                                                "paid_at": "2026-11-05T07:30:00+00:00"})
        from_hospital(bus, "appointment.paid", {"appointment_id": aid, "hospital_id": HOSPITAL, "method": "card"})
        from_hospital(bus, "appointment.completed", {"appointment_id": aid, "hospital_id": HOSPITAL})
        run_worker(bus)
        [entry] = ledger()  # once, whatever came after
        assert entry["source"] == ("booking", aid) and entry["dedan_id"] == patient["dedan"]
        assert (entry["subtotal"], entry["fee"], entry["total"]) == (10_000, 500, 10_500)
        assert entry["method"] == "cash" and entry["collected_by"] == "hospital" and entry["status"] == "owed"

    def test_completed_without_saying_how_it_was_paid_is_owed_too(self, client, bus, patient, listed):
        aid = book(client, patient["auth"]).json()["appointment"]["appointment_id"]
        from_hospital(bus, "appointment.completed", {"appointment_id": aid, "hospital_id": HOSPITAL})
        run_worker(bus)
        [entry] = ledger()
        assert entry["method"] == "unrecorded" and entry["status"] == "owed" and entry["fee"] == 500

    def test_a_cancelled_visit_paid_at_the_hospital_owes_nothing(self, client, bus, patient, listed):
        aid = book(client, patient["auth"]).json()["appointment"]["appointment_id"]
        client.patch(f"/users/me/appointments/{aid}/status", headers=patient["auth"], json={"status": "CANCELLED"})
        run_worker(bus)
        assert ledger() == []

    def test_paid_events_for_another_hospital_or_an_online_booking_are_refused(self, client, bus, patient, listed):
        aid = book(client, patient["auth"]).json()["appointment"]["appointment_id"]
        from_hospital(bus, "appointment.paid", {"appointment_id": aid, "hospital_id": OTHER, "method": "cash"})
        from_hospital(bus, "appointment.paid", {"appointment_id": aid, "hospital_id": HOSPITAL, "method": "gold"})
        run_worker(bus)
        assert ledger() == [] and len(dead_letters(bus)) == 2

    def test_online_the_fee_is_collected_by_endod_and_a_refund_cancels_it(self, client, bus, patient, listed,
                                                                          chapa_api):
        from dedan_platform import booking_payments

        resp = book(client, patient["auth"])
        assert resp.json()["payment"]["service_fee"] == 500
        aid = chapa_api.pay_booking(client, resp)
        [entry] = ledger()
        assert entry["source"] == ("booking", aid) and entry["method"] == "chapa"
        assert entry["collected_by"] == "endod" and entry["status"] == "collected" and entry["total"] == 10_500
        from_hospital(bus, "appointment.rejected", {"appointment_id": aid, "hospital_id": HOSPITAL,
                                                    "reason": "No doctor"})
        run_worker(bus)
        booking_payments.process_refunds()
        assert [e["status"] for e in ledger()] == ["refunded"]


# --- charges ----------------------------------------------------------------------------------

def charge(dedan, charge_id=None, subtotal=35_000, fee=2500, **extra):
    return {"charge_id": charge_id or hexid(), "hospital_id": HOSPITAL, "dedan_id": dedan,
            "items": [{"category": "lab_test", "code": "CBC", "name": "Complete blood count", "amount": 35_000,
                       "quantity": 1}],
            "subtotal": subtotal, "service_fee": fee, "total": subtotal + fee, "currency": "ETB", **extra}


def paid_charge(created, method="cash", **extra):
    body = {k: v for k, v in created.items() if k != "items"}
    return {**body, "method": method, "reference": "RCPT-1", "paid_at": "2026-11-05T09:00:00+03:00", **extra}


class TestCharges:
    def test_a_charge_becomes_a_bill_with_an_inbox_item_and_a_non_clinical_text(self, client, bus, patient,
                                                                                listed):
        created = charge(patient["dedan"])
        from_hospital(bus, "charge.created", created)
        from_hospital(bus, "charge.created", created)  # redelivered under a new id
        run_worker(bus)
        bills = client.get("/users/me/bills", headers=patient["auth"]).json()
        [bill] = bills["items"]
        assert (bill["subtotal"], bill["service_fee"], bill["total"]) == (35_000, 2500, 37_500)
        assert bill["status"] == "open" and bill["hospital_name"] == "Zewditu Memorial Hospital"
        assert bill["items"][0]["name"] == "Complete blood count" and bill["pay_at"] == "hospital"
        assert bills["open_total"] == 37_500
        [text] = texts("sms_bill")
        assert text["key"] == f"sms:bill:{created['charge_id']}"
        [sms] = deliver_due()
        message = sms[1] if isinstance(sms, tuple) else str(sms)
        assert "ETB 375.00" in message and "ETB 25.00" in message
        # Never clinical, never the hospital's name.
        assert "blood" not in message.lower() and "Zewditu" not in message
        [item] = [i for i in inbox(client, patient["auth"]) if i["kind"] == "bill_created"]
        assert "ETB 375.00" in item["body"]

    def test_paid_at_the_hospital_the_fee_is_owed_and_the_bill_paid(self, client, bus, patient, listed):
        created = charge(patient["dedan"])
        from_hospital(bus, "charge.created", created)
        from_hospital(bus, "charge.paid", paid_charge(created, method="mobile_money"))
        from_hospital(bus, "charge.paid", paid_charge(created, method="cash"))  # once only
        run_worker(bus)
        [entry] = ledger()
        assert entry["source"] == ("charge", created["charge_id"]) and entry["method"] == "mobile_money"
        assert (entry["subtotal"], entry["fee"], entry["total"]) == (35_000, 2500, 37_500)
        assert entry["collected_by"] == "hospital" and entry["status"] == "owed"
        [bill] = client.get("/users/me/bills", headers=patient["auth"]).json()["items"]
        assert bill["status"] == "paid" and bill["method"] == "mobile_money"
        assert bill["paid_at"].startswith("2026-11-05T06:00:00")

    def test_a_voided_charge_voids_the_bill_and_its_unsent_text(self, client, bus, patient, listed):
        created = charge(patient["dedan"])
        from_hospital(bus, "charge.created", created)
        from_hospital(bus, "charge.voided", {"charge_id": created["charge_id"], "hospital_id": HOSPITAL,
                                             "dedan_id": patient["dedan"]})
        run_worker(bus)
        [bill] = client.get("/users/me/bills", headers=patient["auth"]).json()["items"]
        assert bill["status"] == "voided"
        assert [t["status"] for t in texts("sms_bill")] != ["pending"]
        assert ledger() == []

    def test_a_patient_not_on_endod_still_reaches_the_ledger(self, client, bus, listed):
        created = charge(None)
        from_hospital(bus, "charge.created", created)
        from_hospital(bus, "charge.paid", paid_charge(created))
        run_worker(bus)
        [entry] = ledger()
        assert entry["dedan_id"] is None and entry["status"] == "owed"
        assert texts("sms_bill") == []

    def test_a_patient_not_linked_to_this_hospital_gets_no_bill(self, client, bus, listed):
        other = register(client, email="b@example.com", linked=False)
        created = charge(other["dedan"])
        from_hospital(bus, "charge.created", created)
        run_worker(bus)
        assert client.get("/users/me/bills", headers=other["auth"]).json()["items"] == []
        assert texts("sms_bill") == []

    @pytest.mark.parametrize("bad", [
        {"total": 1},  # does not add up
        {"subtotal": 1.5},
        {"currency": "USD"},
        {"items": []},
        {"items": [{"category": "massage", "name": "x", "amount": 1, "quantity": 1}]},
    ])
    def test_malformed_charges_are_dead_lettered(self, client, bus, patient, listed, bad):
        from_hospital(bus, "charge.created", {**charge(patient["dedan"]), **bad})
        run_worker(bus)
        assert len(dead_letters(bus)) == 1
        assert client.get("/users/me/bills", headers=patient["auth"]).json()["items"] == []

    def test_bills_are_the_patients_own(self, client, bus, patient, listed):
        from_hospital(bus, "charge.created", charge(patient["dedan"]))
        run_worker(bus)
        other = register(client, email="c@example.com", phone=None)
        assert client.get("/users/me/bills", headers=other["auth"]).json()["items"] == []
        assert client.get("/users/me/bills").status_code == 401


# --- the ledger through the admin API -----------------------------------------------------------

class TestLedgerAdmin:
    @pytest.fixture
    def books(self, client, bus, patient, listed, chapa_api, monkeypatch):
        """One booking paid online, one booking paid at the hospital, two charges paid at the hospital."""
        chapa_api.pay_booking(client, book(client, patient["auth"]))
        monkeypatch.delenv("CHAPA_SECRET_KEY")
        aid = book(client, patient["auth"], at=when(days=3)).json()["appointment"]["appointment_id"]
        from_hospital(bus, "appointment.paid", {"appointment_id": aid, "hospital_id": HOSPITAL, "method": "cash"})
        for _ in range(2):
            created = charge(patient["dedan"])
            from_hospital(bus, "charge.created", created)
            from_hospital(bus, "charge.paid", paid_charge(created, paid_at=datetime.now(timezone.utc).isoformat()))
        run_worker(bus)
        return ledger()

    def test_the_summary_per_hospital(self, admin, books):
        resp = admin.get("/internal/admin/fees/summary", headers=HEADERS)
        assert resp.status_code == 200, resp.text
        [row] = resp.json()["hospitals"]
        assert row["hospital_id"] == HOSPITAL and row["hospital_name"] == "Zewditu Memorial Hospital"
        assert row["payments"] == 4
        assert row["fees_collected"] == 500  # the online booking
        assert row["fees_owed"] == 500 + 2 * 2500 and row["owed_entries"] == 3
        assert row["fees_settled"] == 0 and row["fees_total"] == 6000
        assert resp.json()["totals"]["fees_owed"] == 5500
        # A period without payments.
        empty = admin.get("/internal/admin/fees/summary", headers=HEADERS,
                          params={"from": "2020-01-01", "to": "2020-01-31"}).json()
        assert empty["hospitals"] == [] and empty["totals"]["payments"] == 0
        assert admin.get("/internal/admin/fees/summary", headers=HEADERS,
                         params={"from": "2026-02-01", "to": "2026-01-01"}).status_code == 400

    def test_entries_and_settlement(self, admin, books):
        owed = admin.get("/internal/admin/fees/entries", headers=HEADERS,
                         params={"hospital_id": HOSPITAL, "status": "owed"}).json()
        assert owed["total"] == 3 and {e["collected_by"] for e in owed["items"]} == {"hospital"}
        assert set(owed["items"][0]) >= {"source_type", "source_id", "subtotal", "fee", "total", "method", "paid_at"}
        ids = [e["id"] for e in owed["items"]]
        collected = [e["id"] for e in books if e["status"] == "collected"]
        # All or nothing: an online one is not owed.
        refused = admin.post("/internal/admin/fees/settle", headers=HEADERS, json={
            "hospital_id": HOSPITAL, "entry_ids": ids + collected, "reference": "BANK-123", "actor_email": ACTOR})
        assert refused.status_code == 409
        other = admin.post("/internal/admin/fees/settle", headers=HEADERS, json={
            "hospital_id": OTHER, "entry_ids": ids, "reference": "BANK-123", "actor_email": ACTOR})
        assert other.status_code == 409
        done = admin.post("/internal/admin/fees/settle", headers=HEADERS, json={
            "hospital_id": HOSPITAL, "entry_ids": ids, "reference": "BANK-123", "actor_email": ACTOR})
        assert done.status_code == 200, done.text
        assert done.json()["settled"] == 3 and done.json()["amount"] == 5500
        again = admin.post("/internal/admin/fees/settle", headers=HEADERS, json={
            "hospital_id": HOSPITAL, "entry_ids": ids, "reference": "BANK-123", "actor_email": ACTOR})
        assert again.status_code == 409
        settled = admin.get("/internal/admin/fees/entries", headers=HEADERS, params={"status": "settled"}).json()
        assert {e["settlement_reference"] for e in settled["items"]} == {"BANK-123"}
        assert {e["settled_by"] for e in settled["items"]} == {ACTOR}
        row = admin.get("/internal/admin/fees/summary", headers=HEADERS).json()["hospitals"][0]
        assert row["fees_owed"] == 0 and row["fees_settled"] == 5500

    @pytest.mark.parametrize("params", [{"status": "lost"}, {"source": "wallet"}, {"limit": 0}])
    def test_entry_filters_are_checked(self, admin, books, params):
        assert admin.get("/internal/admin/fees/entries", headers=HEADERS, params=params).status_code in (400, 422)

    def test_settlement_needs_a_reference_and_an_admin(self, admin, books):
        ids = [e["id"] for e in books if e["status"] == "owed"]
        for body in ({"reference": " ", "actor_email": ACTOR}, {"reference": "BANK-1", "actor_email": "nope"},
                     {"reference": "BANK-1", "actor_email": ACTOR, "entry_ids": []},
                     {"reference": "BANK-1", "actor_email": ACTOR, "entry_ids": ["../x"]}):
            resp = admin.post("/internal/admin/fees/settle", headers=HEADERS,
                              json={"hospital_id": HOSPITAL, "entry_ids": ids, **body})
            assert resp.status_code in (404, 422), body
