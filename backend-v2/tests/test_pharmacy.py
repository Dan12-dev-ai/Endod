"""Prescriptions at pharmacies (docs/pharmacy.md): dispensing entries, the
pharmacy API on internal-api, what the patient sees, texts and the event to
the hospital.

Records arrive as the hospital service sends them (fakeredis + the events
worker); the pharmacy API is called on main_internal's app.
"""

import json
import threading
import time as _time
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from test_patient_history import (  # noqa: F401 -- shared helpers (not fixtures)
    HOSPITAL, PHONE, deliver_due, from_hospital, hexid, register, run_worker, sent, texts,
)

from dedan_platform.sms_provider import BRAND_NAME as BRAND  # noqa: E402

ADDIS = ZoneInfo("Africa/Addis_Ababa")
PHARMACY_KEY = "pharmacy-test-key"
RX_KEY = "rx-signing-test-key"
HOSPITAL_NAME = "Zewditu Memorial Hospital"
KEY_HEADERS = {"X-Pharmacy-Key": PHARMACY_KEY, "X-Client-IP": "196.188.1.10"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    from dedan_platform import db as dbmod
    from dedan_platform.api_auth import router as auth_router
    from dedan_platform.api_history import router as history_router
    from dedan_platform.api_inbox import router as inbox_router
    from dedan_platform.api_profile import router as profile_router

    monkeypatch.setenv("REALTIME_TOKEN_SECRET", "test-secret")
    monkeypatch.setenv("DEDAN_DATABASE_URL", f"sqlite:///{tmp_path / 'pharmacy.db'}")
    monkeypatch.setenv("REMINDER_CHANNELS", "sms")
    monkeypatch.setenv("RECORD_FILES_DIR", str(tmp_path / "records"))
    monkeypatch.setenv("PHARMACY_API_KEY", PHARMACY_KEY)
    monkeypatch.setenv("RX_SIGNING_KEY", RX_KEY)
    dbmod.reset_engine()
    dbmod.create_all()
    app = FastAPI()
    for router in (auth_router, profile_router, history_router, inbox_router):
        app.include_router(router)
    yield TestClient(app)
    dbmod.reset_engine()


@pytest.fixture
def pharmacy(client, monkeypatch):
    """internal-api, as the pharmacy site's server calls it."""
    import main_internal

    monkeypatch.setenv("INTERNAL_ALLOWED_HOSTS", "testserver")
    return TestClient(main_internal.create_app())


@pytest.fixture
def patient(client):
    return register(client)


@pytest.fixture
def bus():
    import fakeredis

    return fakeredis.FakeRedis(decode_responses=True)


ITEMS = [
    {"drug": "Amoxicillin", "dose": "500 mg", "route": "oral", "frequency": "three times a day",
     "duration": "7 days", "quantity": "21 tablets"},
    {"drug": "Paracetamol syrup", "dose": "10 ml", "quantity": "1 bottle", "notes": "after meals"},
    {"drug": "ORS", "quantity": "x"},
]


def publish(bus, patient, record_id=None, version=1, items=None, occurred_at=None, dedan=None, category="prescription"):
    record_id = record_id or hexid()
    from_hospital(bus, "record.published", {
        "record_id": record_id, "version": version, "hospital_id": HOSPITAL, "hospital_name": HOSPITAL_NAME,
        "dedan_id": dedan or patient["dedan"], "category": category, "title": "Chest infection",
        "details": {"items": ITEMS if items is None else items, "notes": "Finish the course"},
        "occurred_at": (occurred_at or datetime.now(timezone.utc)).isoformat(),
        "recorded_by": "Dr. Hiwot Bekele", "source": "portal",
    })
    run_worker(bus)
    return record_id


def entry(record_id):
    from dedan_platform.db import session_scope
    from dedan_platform.models import Prescription

    with session_scope() as session:
        rx = session.scalar(select(Prescription).where(Prescription.record_id == record_id,
                                                       Prescription.withdrawn_at.is_(None)))
        return None if rx is None else {"rx_id": rx.id, "code": rx.code, "status": rx.status,
                                        "active_code": rx.active_code}


def token(record_id):
    from dedan_platform import prescriptions

    return prescriptions.token_for(entry(record_id)["rx_id"])


def lookup(pharmacy, body, ip="196.188.1.10"):
    return pharmacy.post("/pharmacy/lookup", json=body, headers={**KEY_HEADERS, "X-Client-IP": ip})


def dispense(pharmacy, body, key=None, ip="196.188.1.10"):
    headers = {**KEY_HEADERS, "X-Client-IP": ip}
    if key:
        headers["Idempotency-Key"] = key
    return pharmacy.post("/pharmacy/dispense", json=body, headers=headers)


def give(record_id, *items, name="Kenema Pharmacy"):
    return {"token": token(record_id), "pharmacy_name": name, "pharmacist_name": "Sara",
            "items": [{"item_index": i, "amount": a, "complete": c} for i, a, c in items]}


# --- section 1: the entry ---------------------------------------------------------------------

def test_token_is_signed_and_tampering_is_refused(client, patient, bus, monkeypatch):
    from dedan_platform import prescriptions

    record_id = publish(bus, patient)
    rx = entry(record_id)
    tok = prescriptions.token_for(rx["rx_id"])
    rx_id, sig = tok.split(".")
    assert rx_id == rx["rx_id"] and len(rx_id) == 32 and len(sig) == 22
    assert prescriptions.rx_id_from_token(tok) == rx_id
    flipped = sig[:-1] + ("A" if sig[-1] != "A" else "B")
    assert prescriptions.rx_id_from_token(f"{rx_id}.{flipped}") is None
    other = hexid()
    assert prescriptions.rx_id_from_token(f"{other}.{sig}") is None
    assert prescriptions.rx_id_from_token(tok + "x") is None
    assert prescriptions.rx_id_from_token(None) is None
    # The card key does not sign prescriptions, nor does any other key.
    monkeypatch.setenv("RX_SIGNING_KEY", "another-key")
    assert prescriptions.rx_id_from_token(tok) is None
    monkeypatch.delenv("RX_SIGNING_KEY")
    assert prescriptions.rx_id_from_token(tok) is None
    assert prescriptions.token_for(rx_id) is None


def test_quantity_parsing():
    from dedan_platform.prescriptions import parse_quantity

    assert parse_quantity("21 tablets") == 21
    assert parse_quantity("1 bottle") == 1
    assert parse_quantity("x") is None
    assert parse_quantity("24") == 24
    assert parse_quantity(" 2.5 ml") == 2.5
    assert parse_quantity("0 tablets") is None
    assert parse_quantity("tablets: 21") is None
    assert parse_quantity("") is None and parse_quantity(None) is None


def test_items_from_the_prescription(client, patient, bus, pharmacy):
    record_id = publish(bus, patient)
    body = lookup(pharmacy, {"token": token(record_id)}).json()
    assert [(i["item_index"], i["quantity_text"], i["quantity_total"], i["given_total"], i["status"])
            for i in body["items"]] == [(0, "21 tablets", 21, None, "not_given"), (1, "1 bottle", 1, None, "not_given"),
                                        (2, "x", None, None, "not_given")]


def test_codes_are_unique_among_active_prescriptions(client, patient, bus, monkeypatch):
    from dedan_platform import prescriptions

    draws = iter(["123456", "123456", "123456", "654321"])
    monkeypatch.setattr(prescriptions, "_random_code", lambda: next(draws))
    first = entry(publish(bus, patient))
    second = entry(publish(bus, patient))
    assert first["code"] == "123456" and second["code"] == "654321"
    assert first["active_code"] == "123456"


def test_a_completed_prescription_frees_its_code(client, patient, bus, pharmacy):
    record_id = publish(bus, patient, items=[{"drug": "Zinc", "quantity": "10 tablets"}])
    assert dispense(pharmacy, give(record_id, (0, 10, False))).status_code == 200
    rx = entry(record_id)
    assert rx["status"] == "completed" and rx["active_code"] is None


def test_expiry_is_30_days_at_the_end_of_the_day_in_addis(client, patient, bus, pharmacy):
    from dedan_platform.prescriptions import expiry_for

    # 22:00 UTC on 1 Jan is 01:00 on 2 Jan in Addis Ababa.
    assert expiry_for(datetime(2026, 1, 1, 22, 0, tzinfo=timezone.utc)) == \
        datetime(2026, 2, 1, 23, 59, 59, tzinfo=ADDIS).astimezone(timezone.utc)

    old = publish(bus, patient, occurred_at=datetime.now(timezone.utc) - timedelta(days=32))
    body = lookup(pharmacy, {"token": token(old)}).json()
    assert body["status"] == "expired"
    refused = dispense(pharmacy, give(old, (0, 1, False)))
    assert refused.status_code == 409 and refused.json()["detail"]["status"] == "expired"
    # Never texted: the code could not be used anyway.
    assert [t for t in texts("sms_rx_code") if t["payload"]["params"]["rx_id"] == entry(old)["rx_id"]] == []


# --- section 2: lookups ----------------------------------------------------------------------

def test_lookup_shows_the_prescription_and_nothing_else(client, patient, bus, pharmacy):
    from dedan_platform.db import session_scope
    from dedan_platform.models import HealthProfile

    today = datetime.now(ADDIS).date()
    born = today.replace(year=today.year - 34) - timedelta(days=1)
    with session_scope() as session:
        row = session.scalar(select(HealthProfile).where(HealthProfile.user_id == patient["id"]))
        if row is None:
            row = HealthProfile(user_id=patient["id"])
            session.add(row)
        row.date_of_birth = datetime(born.year, born.month, born.day, 12, tzinfo=timezone.utc)
        row.sex = "female"
        row.conditions = json.dumps(["asthma"])
    record_id = publish(bus, patient)
    body = lookup(pharmacy, {"token": token(record_id)}).json()
    assert set(body) == {"rx_id", "status", "hospital_name", "doctor_name", "written_at", "expires_at", "patient",
                         "notes", "items", "dispenses"}
    assert set(body["patient"]) == {"name", "dedan_id", "age", "sex"}
    assert body["patient"]["name"] == "Almaz Tefera" and body["patient"]["dedan_id"] == patient["dedan"]
    assert set(body["items"][0]) == {"item_index", "drug", "dose", "route", "frequency", "duration", "quantity_text",
                                     "quantity_total", "given_total", "status", "notes"}
    assert body["status"] == "open" and body["hospital_name"] == HOSPITAL_NAME
    assert body["doctor_name"] == "Dr. Hiwot Bekele" and body["notes"] == "Finish the course"
    assert body["items"][1]["notes"] == "after meals"
    assert body["patient"]["age"] == 34 and body["patient"]["sex"] == "female"
    assert "asthma" not in json.dumps(body)


def test_code_works_only_with_the_verified_phone(client, patient, bus, pharmacy):
    from dedan_platform.db import session_scope
    from dedan_platform.models import Profile

    record_id = publish(bus, patient)
    code = entry(record_id)["code"]
    assert lookup(pharmacy, {"code": code, "phone": "0911223344"}).status_code == 200
    assert lookup(pharmacy, {"code": code, "phone": "+251 911 223 344"}).status_code == 200
    assert lookup(pharmacy, {"code": code, "phone": "0911000000"}).status_code == 404
    with session_scope() as session:
        session.execute(update(Profile).where(Profile.user_id == patient["id"]).values(phone_verified_at=None))
    assert lookup(pharmacy, {"code": code, "phone": "0911223344"}).status_code == 404


def test_not_found_is_the_same_for_every_miss(client, patient, bus, pharmacy):
    record_id = publish(bus, patient)
    rx = entry(record_id)
    sig = token(record_id).split(".")[1]
    other = "000000" if rx["code"] != "000000" else "111111"
    misses = [
        {"token": f"{rx['rx_id']}.{'A' * 22}"},          # wrong signature
        {"token": f"{hexid()}.{sig}"},                    # someone else's signature
        {"token": "nonsense"},                            # malformed
        {"code": other, "phone": PHONE},                  # unknown code
        {"code": rx["code"], "phone": "0911000000"},      # phone does not match
        {"code": "12ab", "phone": PHONE},                 # malformed code
        {"code": rx["code"], "phone": "not a phone"},
    ]
    answers = {(r.status_code, r.text) for r in (lookup(pharmacy, body, ip=f"10.0.0.{n}")
                                                 for n, body in enumerate(misses))}
    assert answers == {(404, json.dumps({"detail": "Not found"}, separators=(",", ":")))}
    # Dispensing answers the same.
    miss = dispense(pharmacy, {"token": f"{rx['rx_id']}.{'A' * 22}", "pharmacy_name": "Kenema",
                               "items": [{"item_index": 0, "amount": 1}]})
    assert (miss.status_code, miss.json()) == (404, {"detail": "Not found"})


def test_failed_code_lookups_are_limited_per_client(client, patient, bus, pharmacy):
    record_id = publish(bus, patient)
    code = entry(record_id)["code"]
    wrong = [f"{n:06d}" for n in range(20) if f"{n:06d}" != code]
    # Successes do not count.
    for _ in range(12):
        assert lookup(pharmacy, {"code": code, "phone": PHONE}, ip="196.188.5.5").status_code == 200
    for guess in wrong[:10]:
        assert lookup(pharmacy, {"code": guess, "phone": PHONE}, ip="196.188.5.5").status_code == 404
    limited = lookup(pharmacy, {"code": code, "phone": PHONE}, ip="196.188.5.5")
    assert limited.status_code == 429 and int(limited.headers["Retry-After"]) > 3000
    # Dispensing by code from that client is limited too; another client is not.
    blocked = dispense(pharmacy, {"code": code, "phone": PHONE, "pharmacy_name": "Kenema",
                                  "items": [{"item_index": 0, "amount": 1}]}, ip="196.188.5.5")
    assert blocked.status_code == 429
    assert lookup(pharmacy, {"code": code, "phone": PHONE}, ip="196.188.5.6").status_code == 200


def test_ipv6_clients_are_limited_by_their_64_block(client, patient, bus, pharmacy):
    from dedan_platform.api_pharmacy import client_key

    assert client_key("2001:db8:1:2::5") == client_key("2001:db8:1:2:ffff::1") == "2001:db8:1:2::/64"
    assert client_key("::ffff:196.188.1.1") == "196.188.1.1"
    assert client_key(None) == client_key("garbage") == "unknown"


def test_failed_lookups_are_limited_per_code(client, patient, bus, pharmacy):
    record_id = publish(bus, patient)
    code = entry(record_id)["code"]
    for n in range(5):
        assert lookup(pharmacy, {"code": code, "phone": "0911000000"}, ip=f"10.1.0.{n}").status_code == 404
    # The right phone, from a fresh client: the code is locked for the hour.
    assert lookup(pharmacy, {"code": code, "phone": PHONE}, ip="10.1.0.99").status_code == 429
    # The QR still works.
    assert lookup(pharmacy, {"token": token(record_id)}, ip="10.1.0.99").status_code == 200


def test_token_lookups_are_limited_per_client(client, patient, bus, pharmacy):
    record_id = publish(bus, patient)
    tok = token(record_id)
    for _ in range(60):
        assert lookup(pharmacy, {"token": tok}, ip="10.2.0.1").status_code == 200
    assert lookup(pharmacy, {"token": tok}, ip="10.2.0.1").status_code == 429
    assert lookup(pharmacy, {"token": tok}, ip="10.2.0.2").status_code == 200


def test_limits_hold_across_processes(client, patient, bus):
    """Counted in the database: a second process (another engine) sees them."""
    from dedan_platform import throttle
    from dedan_platform.db import get_engine, reset_engine

    for _ in range(3):
        throttle.begin({"rx:test:bucket": 3})
    reset_engine()  # as a fresh process would start
    assert get_engine() is not None
    with pytest.raises(throttle.Limited):
        throttle.begin({"rx:test:bucket": 3})


def test_the_key_is_required(client, patient, bus, pharmacy, monkeypatch):
    record_id = publish(bus, patient)
    body = {"token": token(record_id)}
    assert pharmacy.post("/pharmacy/lookup", json=body).status_code == 401
    assert pharmacy.post("/pharmacy/lookup", json=body, headers={"X-Pharmacy-Key": "wrong"}).status_code == 401
    assert pharmacy.post("/pharmacy/dispense", json={**body, "pharmacy_name": "Kenema", "items": [
        {"item_index": 0, "amount": 1}]}, headers={"X-Pharmacy-Key": "wrong"}).status_code == 401
    # The platform key is not the pharmacy key.
    assert pharmacy.post("/pharmacy/lookup", json=body, headers={"X-Platform-Key": PHARMACY_KEY}).status_code == 401
    monkeypatch.delenv("PHARMACY_API_KEY")
    assert pharmacy.post("/pharmacy/lookup", json=body, headers=KEY_HEADERS).status_code == 503


def test_the_patient_api_does_not_serve_pharmacy_routes(client, patient, bus):
    import main_clinical

    api = TestClient(main_clinical.app)
    for path in ("/pharmacy/lookup", "/pharmacy/dispense", "/api/pharmacy/lookup"):
        response = api.post(path, json={"token": "x"}, headers=KEY_HEADERS)
        assert response.status_code in (404, 405), (path, response.status_code)


# --- section 2: dispensing -------------------------------------------------------------------

def test_partial_then_complete_dispensing(client, patient, bus, pharmacy):
    record_id = publish(bus, patient)
    first = dispense(pharmacy, give(record_id, (0, 14, False)))
    assert first.status_code == 200, first.text
    item = first.json()["items"][0]
    assert (item["given_total"], item["status"]) == (14, "partly_given")
    assert first.json()["status"] == "open"
    assert first.json()["dispenses"] == [{"at": first.json()["dispenses"][0]["at"], "pharmacy_name": "Kenema Pharmacy",
                                          "items": [{"item_index": 0, "amount": 14, "complete": False}]}]

    second = dispense(pharmacy, {**give(record_id, (0, 7, False), (1, None, True)), "pharmacy_name": "Bole Pharmacy"})
    assert second.status_code == 200, second.text
    items = second.json()["items"]
    assert (items[0]["given_total"], items[0]["status"]) == (21, "given")
    assert (items[1]["given_total"], items[1]["status"]) == (None, "given")
    assert items[2]["status"] == "not_given" and second.json()["status"] == "open"

    # "x": no count, so an amount is counted up, and "complete" finishes it.
    given = dispense(pharmacy, give(record_id, (1, None, True)))
    assert given.json() == {"detail": {"status": "open", "message": "Item 1 has already been given."}}
    third = dispense(pharmacy, give(record_id, (2, 2, False)))
    assert (third.json()["items"][2]["given_total"], third.json()["items"][2]["status"]) == (2, "partly_given")
    done = dispense(pharmacy, give(record_id, (2, None, True)))
    assert done.json()["status"] == "completed"
    assert [d["pharmacy_name"] for d in done.json()["dispenses"]] == [
        "Kenema Pharmacy", "Bole Pharmacy", "Kenema Pharmacy", "Kenema Pharmacy"]

    # Completed: the QR and code stop dispensing; lookup still shows it.
    again = dispense(pharmacy, give(record_id, (0, 1, False)))
    assert again.status_code == 409 and again.json()["detail"]["status"] == "completed"
    assert lookup(pharmacy, {"token": token(record_id)}).json()["status"] == "completed"
    code = entry(record_id)["code"]
    assert lookup(pharmacy, {"code": code, "phone": PHONE}).json()["status"] == "completed"


def test_more_than_is_left_is_refused(client, patient, bus, pharmacy):
    record_id = publish(bus, patient)
    assert dispense(pharmacy, give(record_id, (0, 22, False))).status_code == 409
    assert dispense(pharmacy, give(record_id, (0, 20, False))).status_code == 200
    over = dispense(pharmacy, give(record_id, (0, 2, False)))
    assert over.status_code == 409
    assert over.json() == {"detail": {"status": "open", "message": "Item 0: only 1 left to give."}}
    # Nothing of a refused request is applied (all items or none).
    partly = dispense(pharmacy, give(record_id, (1, None, True), (0, 5, False)))
    assert partly.status_code == 409 and partly.json()["detail"]["status"] == "open"
    body = lookup(pharmacy, {"token": token(record_id)}).json()
    assert body["items"][0]["given_total"] == 20 and body["items"][1]["status"] == "not_given"
    assert len(body["dispenses"]) == 1


def test_invalid_dispenses(client, patient, bus, pharmacy):
    record_id = publish(bus, patient)
    for items in ([{"item_index": 0, "amount": -1}], [{"item_index": 0, "amount": 0}], [{"item_index": 9, "amount": 1}],
                  [{"item_index": 0}], [{"item_index": 0, "amount": 1}, {"item_index": 0, "amount": 1}], [],
                  [{"item_index": 0, "amount": True}]):
        response = dispense(pharmacy, {"token": token(record_id), "pharmacy_name": "Kenema", "items": items})
        assert response.status_code == 422, (items, response.text)
    for name in ("K", " ", "x" * 121, "Kenema\nCall 0911"):
        response = dispense(pharmacy, {"token": token(record_id), "pharmacy_name": name,
                                       "items": [{"item_index": 0, "amount": 1}]})
        assert response.status_code == 422, name
    assert dispense(pharmacy, give(record_id, (0, 1, False)), key="not-a-uuid").status_code == 422


def test_the_same_idempotency_key_dispenses_once(client, patient, bus, pharmacy):
    from dedan_platform.db import session_scope
    from dedan_platform.models import PrescriptionDispense

    record_id = publish(bus, patient)
    key = str(uuid.uuid4())
    first = dispense(pharmacy, give(record_id, (0, 7, False)), key=key)
    second = dispense(pharmacy, give(record_id, (0, 7, False)), key=key)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert second.json()["items"][0]["given_total"] == 7
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(PrescriptionDispense)) == 1
    run_worker(bus)
    assert len(sent(bus, "prescription.dispensed")) == 1
    assert len(texts("sms_rx_dispensed")) == 1
    # The key cannot be reused for another prescription.
    other = publish(bus, patient)
    reused = dispense(pharmacy, give(other, (0, 1, False)), key=key)
    assert reused.status_code == 409 and reused.json()["detail"]["status"] == "open"


def test_two_pharmacies_at_the_same_moment_cannot_over_give(client, patient, bus):
    from dedan_platform import prescriptions

    record_id = publish(bus, patient)
    rx_id = entry(record_id)["rx_id"]
    results = []
    entered = threading.Event()

    def slow():
        # The first to hold the lock waits here; the second must wait for it.
        if not entered.is_set():
            entered.set()
            _time.sleep(0.5)

    def one(name):
        try:
            prescriptions.dispense(rx_id, pharmacy_name=name, pharmacist_name=None,
                                   items=[{"item_index": 0, "amount": 14, "complete": False}], before_apply=slow)
            results.append("ok")
        except prescriptions.DispenseError as exc:
            results.append(exc.status_code)

    threads = [threading.Thread(target=one, args=(f"Pharmacy {n}",)) for n in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert sorted(results, key=str) == [409, "ok"]
    from dedan_platform.db import session_scope
    from dedan_platform.models import PrescriptionItem

    with session_scope() as session:
        item = session.scalar(select(PrescriptionItem).where(PrescriptionItem.rx_id == rx_id,
                                                             PrescriptionItem.item_index == 0))
        assert item.given_total == 14


# --- corrections, retraction, moves ----------------------------------------------------------

def test_a_correction_keeps_rx_id_code_and_given_amounts(client, patient, bus, pharmacy):
    record_id = publish(bus, patient)
    before = entry(record_id)
    tok = token(record_id)
    assert dispense(pharmacy, give(record_id, (0, 14, False), (1, None, True))).status_code == 200
    corrected = [dict(ITEMS[0], quantity="28 tablets"), ITEMS[1], ITEMS[2], {"drug": "Vitamin C", "quantity": "10"}]
    publish(bus, patient, record_id=record_id, version=2, items=corrected)
    assert entry(record_id)["rx_id"] == before["rx_id"] and entry(record_id)["code"] == before["code"]
    body = lookup(pharmacy, {"token": tok}).json()
    assert [(i["quantity_total"], i["given_total"], i["status"]) for i in body["items"]] == [
        (28, 14, "partly_given"), (1, None, "given"), (None, None, "not_given"), (10, None, "not_given")]
    # An older version arriving late changes nothing.
    publish(bus, patient, record_id=record_id, version=1)
    assert len(lookup(pharmacy, {"token": tok}).json()["items"]) == 4
    # A correction down to what was already given completes it.
    publish(bus, patient, record_id=record_id, version=3, items=[dict(ITEMS[0], quantity="14 tablets"), ITEMS[1]])
    assert lookup(pharmacy, {"token": tok}).json()["status"] == "completed"
    assert len(texts("sms_rx_code")) == 1


def test_a_retraction_closes_it(client, patient, bus, pharmacy):
    record_id = publish(bus, patient)
    tok = token(record_id)
    from_hospital(bus, "record.retracted", {"record_id": record_id, "hospital_id": HOSPITAL,
                                            "dedan_id": patient["dedan"], "reason": "wrong patient"})
    run_worker(bus)
    body = lookup(pharmacy, {"token": tok}).json()
    assert body["status"] == "retracted" and body["items"] == [] and body["notes"] is None
    refused = dispense(pharmacy, {"token": tok, "pharmacy_name": "Kenema", "items": [{"item_index": 0, "amount": 1}]})
    assert refused.status_code == 409 and refused.json()["detail"]["status"] == "retracted"
    assert entry(record_id)["active_code"] is None
    # The unsent code text is not sent.
    assert deliver_due() == []
    history = client.get("/users/me/history", headers=patient["auth"]).json()
    assert all(i["id"] != record_id for i in history["items"])


def test_a_record_moved_to_another_patient_gets_a_new_entry(client, patient, bus, pharmacy):
    from test_patient_history import link

    other = register(client, email="b@example.com", first="Bekele", phone="+251922334455")
    record_id = publish(bus, patient)
    first = entry(record_id)
    old_token = token(record_id)
    link(other["id"])  # (register links already; harmless)
    publish(bus, patient, record_id=record_id, version=2, dedan=other["dedan"])
    moved = entry(record_id)
    assert moved["rx_id"] != first["rx_id"]
    assert lookup(pharmacy, {"token": old_token}).status_code == 404
    assert lookup(pharmacy, {"code": first["code"], "phone": PHONE}).status_code == 404
    assert lookup(pharmacy, {"token": token(record_id)}).json()["patient"]["dedan_id"] == other["dedan"]


# --- texts, inbox, the patient's History, the hospital event ---------------------------------

def test_the_code_is_texted_once_to_a_verified_phone(client, patient, bus):
    record_id = publish(bus, patient)
    code = entry(record_id)["code"]
    # The same event again, and a correction: still one text.
    publish(bus, patient, record_id=record_id, version=2)
    queued = texts("sms_rx_code")
    assert len(queued) == 1 and queued[0]["destination"] == PHONE
    delivered = deliver_due()
    assert len(delivered) == 1
    text = delivered[0][1]
    am, en = text.split("\n")
    assert "Endod" in en and code in en and HOSPITAL_NAME in en and "pharmacy" in en
    assert code in am and en.startswith(f"{BRAND}: prescription code {code} from {HOSPITAL_NAME}.")
    assert all(drug["drug"].split()[0] not in text for drug in ITEMS)


def test_no_code_text_to_an_unverified_phone(client, bus):
    from dedan_platform import identity
    from dedan_platform.db import session_scope
    from dedan_platform.models import Profile

    patient = register(client, email="u@example.com", phone=None)
    with session_scope() as session:
        session.execute(update(Profile).where(Profile.user_id == patient["id"]).values(phone="+251933445566"))
    identity.update_preferences(patient["id"], {"sms_notifications": True})
    publish(bus, patient)
    assert texts("sms_rx_code") == []


def test_each_dispense_texts_and_tells_the_inbox(client, patient, bus, pharmacy):
    record_id = publish(bus, patient)
    deliver_due()  # the code text
    assert dispense(pharmacy, give(record_id, (0, 7, False))).status_code == 200
    assert dispense(pharmacy, give(record_id, (0, 7, False), name="Visit www.evil.example now")).status_code == 200
    delivered = [t for _phone, t in deliver_due()]
    assert len(delivered) == 2
    assert delivered[0] == f"{BRAND}: medicine from your prescription was given at Kenema Pharmacy."
    assert delivered[1] == f"{BRAND}: medicine from your prescription was given at a pharmacy."
    assert all("Amoxicillin" not in t for t in delivered)
    inbox = client.get("/users/me/inbox", headers=patient["auth"]).json()["items"]
    given = [i for i in inbox if i["kind"] == "prescription_dispensed"]
    assert len(given) == 2 and given[-1]["title"] == "Medicine given at Kenema Pharmacy"
    assert given[0]["link"] == {"screen": "history", "id": record_id}
    assert all("Amoxicillin" not in (i["title"] + (i["body"] or "")) for i in given)


def test_the_hospital_is_told_of_each_dispense(client, patient, bus, pharmacy):
    record_id = publish(bus, patient)
    response = dispense(pharmacy, give(record_id, (0, 14, False), (1, None, True)))
    run_worker(bus)
    events = sent(bus, "prescription.dispensed")
    assert len(events) == 1
    event = events[0]
    assert set(event) == {"record_id", "hospital_id", "dedan_id", "dispense_id", "at", "pharmacy_name", "status",
                          "items"}
    assert event["record_id"] == record_id and event["hospital_id"] == HOSPITAL
    assert event["dedan_id"] == patient["dedan"] and len(event["dispense_id"]) == 32
    assert event["pharmacy_name"] == "Kenema Pharmacy" and event["status"] == "open"
    assert event["at"] == response.json()["dispenses"][0]["at"]
    assert event["items"] == [
        {"item_index": 0, "amount": 14, "complete": False, "given_total": 14, "status": "partly_given"},
        {"item_index": 1, "amount": None, "complete": True, "given_total": None, "status": "given"},
    ]
    dispense(pharmacy, give(record_id, (0, 7, False), (2, None, True)))
    run_worker(bus)
    assert sent(bus, "prescription.dispensed")[-1]["status"] == "completed"


def test_history_shows_the_qr_code_expiry_and_dispenses(client, patient, bus, pharmacy):
    from dedan_platform import prescriptions

    record_id = publish(bus, patient)
    dispense(pharmacy, give(record_id, (0, 14, False)))
    items = client.get("/users/me/history", headers=patient["auth"]).json()["items"]
    rx = next(i for i in items if i["id"] == record_id)["dispensing"]
    assert rx["qr_url"] == f"https://pharmacy.endod-health.com/rx/{token(record_id)}"
    assert prescriptions.rx_id_from_token(rx["qr_url"].rsplit("/", 1)[1]) == rx["rx_id"]
    assert rx["code"] == entry(record_id)["code"] and rx["status"] == "open"
    assert rx["items"][0] == {"item_index": 0, "quantity_text": "21 tablets", "quantity_total": 21,
                              "given_total": 14, "status": "partly_given"}
    assert rx["dispenses"][0]["pharmacy_name"] == "Kenema Pharmacy"
    # Completed: no QR or code any more, the list stays.
    dispense(pharmacy, give(record_id, (0, 7, False), (1, None, True), (2, None, True)))
    items = client.get("/users/me/history", headers=patient["auth"]).json()["items"]
    rx = next(i for i in items if i["id"] == record_id)["dispensing"]
    assert rx["status"] == "completed" and rx["qr_url"] is None and rx["code"] is None
    assert len(rx["dispenses"]) == 2
