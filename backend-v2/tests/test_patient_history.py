"""Patient history from partner hospitals (docs/history-events.md): links,
records and their files, follow-ups, queues, booking texts and shares.

Redis is in memory (fakeredis) and the hospital API an httpx mock. Dates are
computed in Africa/Addis_Ababa, the hospitals' timezone.
"""

import hashlib
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import fakeredis
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, update

PASSWORD = "Str0ng-pass!"
ADDIS = ZoneInfo("Africa/Addis_Ababa")
HOSPITAL = "b" * 32
OTHER_HOSPITAL = "c" * 32
PHONE = "+251911223344"
KEY = "platform-test-key"

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
PDF = b"%PDF-1.4\n%test\n" + b"0" * 30


def hexid():
    return uuid.uuid4().hex


class FakeSms:
    def __init__(self):
        self.sent = []

    def send(self, phone, text):
        self.sent.append((phone, text))
        return f"sms-{len(self.sent)}"


class FakeHospitalApi:
    """The hospital service's /platform/records/{record}/files/{file} endpoint."""

    def __init__(self):
        self.files = {}  # (record_id, file_id) -> bytes
        self.calls = []
        self.fail_next = 0
        self.status = 200

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.url.path, request.headers.get("X-Platform-Key")))
        if request.headers.get("X-Platform-Key") != KEY:
            return httpx.Response(401)
        if self.fail_next:
            self.fail_next -= 1
            return httpx.Response(503)
        parts = request.url.path.strip("/").split("/")
        body = self.files.get((parts[2], parts[4]))
        if body is None:
            return httpx.Response(404)
        return httpx.Response(self.status, content=body)


@pytest.fixture
def hospital_api(monkeypatch, tmp_path):
    from dedan_platform import record_files

    fake = FakeHospitalApi()
    monkeypatch.setattr(record_files, "_transport", httpx.MockTransport(fake.handler))
    monkeypatch.setenv("HOSPITAL_API_URL", "http://endod-hospital-api:8000")
    monkeypatch.setenv("PLATFORM_ADMIN_KEY", KEY)
    monkeypatch.setenv("RECORD_FILES_DIR", str(tmp_path / "records"))
    return fake


@pytest.fixture
def client(tmp_path, monkeypatch):
    from dedan_platform import db as dbmod
    from dedan_platform.api_auth import router as auth_router
    from dedan_platform.api_care import router as care_router
    from dedan_platform.api_health import router as health_router
    from dedan_platform.api_history import internal_router, router as history_router
    from dedan_platform.api_inbox import router as inbox_router
    from dedan_platform.api_payments import router as payments_router
    from dedan_platform.api_profile import router as profile_router
    from dedan_platform.api_records import router as records_router

    monkeypatch.setenv("REALTIME_TOKEN_SECRET", "test-secret")
    monkeypatch.setenv("DEDAN_DATABASE_URL", f"sqlite:///{tmp_path / 'history.db'}")
    monkeypatch.setenv("REMINDER_CHANNELS", "sms")
    monkeypatch.setenv("SERVICE_FEE_FLAT_SANTIM", "500")
    monkeypatch.setenv("SERVICE_FEE_PERCENT_BP", "0")
    monkeypatch.setenv("RECORD_FILES_DIR", str(tmp_path / "records"))
    dbmod.reset_engine()
    dbmod.create_all()
    app = FastAPI()
    for router in (auth_router, profile_router, health_router, care_router, payments_router, inbox_router,
                   records_router, history_router, internal_router):
        app.include_router(router)
    yield TestClient(app)
    dbmod.reset_engine()


def link(user_id, hospital=HOSPITAL, patient_id=None):
    """The hospital linked this account (as a confirmed patient.link_requested does)."""
    from dedan_platform.db import session_scope
    from dedan_platform.models import HospitalLink

    with session_scope() as session:
        session.add(HospitalLink(user_id=user_id, hospital_id=hospital, patient_id=patient_id or hexid()))


def register(client, email="a@example.com", first="Almaz", last="Tefera", phone=PHONE, language="en",
             linked=True):
    """A patient; ``linked``: already linked to HOSPITAL, which may then send about them."""
    from dedan_platform import identity

    resp = client.post("/auth/register", json={
        "first_name": first, "last_name": last, "email": email,
        "password": PASSWORD, "password_confirmation": PASSWORD})
    assert resp.status_code in (200, 201), resp.text
    auth = {"Authorization": resp.json()["access_token"]}
    me = client.get("/users/me", headers=auth).json()
    if phone:
        identity.set_verified_phone(me["internal_user_id"], phone)
    identity.update_preferences(me["internal_user_id"], {"sms_notifications": bool(phone), "language": language})
    consent = client.patch("/users/me/consent", headers=auth, json={"treatment_processing": True})
    assert consent.status_code == 200, consent.text
    if linked:
        link(me["internal_user_id"])
    return {"auth": auth, "id": me["internal_user_id"], "dedan": me["dedan_user_id"]}


@pytest.fixture
def patient(client):
    return register(client)


@pytest.fixture
def bus():
    return fakeredis.FakeRedis(decode_responses=True)


def from_hospital(bus, event_type, payload, event_id=None, occurred_at=None):
    bus.xadd("endod:hospital", {"id": event_id or hexid(), "type": event_type, "source": "hospital-service",
                                "occurred_at": (occurred_at or datetime.now(timezone.utc)).isoformat(),
                                "payload": json.dumps(payload)})


def run_worker(bus, rounds=1):
    from dedan_platform import eventbus, events_worker

    for _ in range(rounds):
        events_worker.run_once(bus)
    eventbus.publish_pending(bus)  # what the handlers emitted


def sent(bus, event_type=None):
    events = [(f["type"], json.loads(f["payload"])) for _id, f in bus.xrange("endod:patient")]
    return [p for t, p in events if t == event_type] if event_type else events


def dead_letters(bus):
    return bus.xrange("endod:dead-letter")


def texts(template=None):
    from dedan_platform.db import session_scope
    from dedan_platform.models import Notification

    with session_scope() as session:
        rows = session.scalars(select(Notification).where(Notification.channel == "sms")).all()
        return [{"template": r.template, "status": r.status, "destination": r.destination,
                 "key": r.idempotency_key, "scheduled_for": r.scheduled_for, "user_id": r.user_id,
                 "payload": json.loads(r.payload_json or "{}")}
                for r in rows if template is None or r.template == template]


def deliver_due(now=None):
    """Run the notification worker; returns what it texted."""
    from dedan_platform import worker

    sms = FakeSms()
    worker.run_once(limit=100, now=now, sms_provider=sms)
    return sms.sent


LISTING = {"hospital_id": HOSPITAL, "version": 1, "code": "ZEW", "name": "Zewditu Memorial Hospital",
           "kind": "public", "city": "Addis Ababa", "latitude": 9.01, "longitude": 38.76,
           "services": ["general_medicine"], "timezone": "Africa/Addis_Ababa", "price_in_person": 10000}


@pytest.fixture
def listed(bus, client):
    from_hospital(bus, "hospital.listed", LISTING)
    run_worker(bus)
    return HOSPITAL


def inbox(client, auth):
    return client.get("/users/me/inbox", headers=auth).json()["items"]


# --- 1. linking -----------------------------------------------------------------------------

def link_request(dedan, **extra):
    return {"request_id": hexid(), "hospital_id": HOSPITAL, "patient_id": "MRN-0042", "dedan_id": dedan,
            "card_signature": None, "phone": None, **extra}


class TestLinking:
    def test_a_genuine_card_links_and_tells_the_patient_once(self, client, bus, patient, listed):
        from dedan_platform import cards

        request = link_request(patient["dedan"], card_signature=cards.card_signature(patient["dedan"]))
        from_hospital(bus, "patient.link_requested", request)
        from_hospital(bus, "patient.link_requested", {**request, "request_id": hexid()})  # scanned twice
        run_worker(bus)
        linked = sent(bus, "patient.linked")
        assert len(linked) == 2
        assert linked[0] == {"request_id": request["request_id"], "hospital_id": HOSPITAL, "patient_id": "MRN-0042",
                             "dedan_id": patient["dedan"], "name": "Almaz Tefera", "phone": PHONE}
        items = [i for i in inbox(client, patient["auth"]) if i["kind"] == "hospital_linked"]
        assert len(items) == 1 and items[0]["title"] == "Zewditu Memorial Hospital linked your records to Endod"

    @pytest.mark.parametrize("typed", ["+251 911 223 344", "0911223344", "911223344", "251911223344"])
    def test_the_account_phone_in_any_format_links(self, client, bus, patient, typed):
        from_hospital(bus, "patient.link_requested", link_request(patient["dedan"].lower(), phone=typed))
        run_worker(bus)
        assert [p["dedan_id"] for p in sent(bus, "patient.linked")] == [patient["dedan"]]

    @pytest.mark.parametrize("extra", [{"card_signature": "AAAAAAAAAAAAAAAAAAAAAA"}, {"phone": "+251922000000"},
                                       {}, {"card_signature": "../../etc", "phone": "not a phone"}])
    def test_anything_else_is_refused_without_patient_data(self, client, bus, patient, extra):
        request = link_request(patient["dedan"], **extra)
        from_hospital(bus, "patient.link_requested", request)
        run_worker(bus)
        assert sent(bus, "patient.linked") == []
        assert sent(bus, "patient.link_refused") == [{
            "request_id": request["request_id"], "hospital_id": HOSPITAL, "patient_id": "MRN-0042",
            "dedan_id": patient["dedan"], "reason": "not_verified"}]
        assert not [i for i in inbox(client, patient["auth"]) if i["kind"] == "hospital_linked"]

    def test_an_unknown_or_deactivated_account_is_not_found(self, client, bus, patient):
        from dedan_platform.db import session_scope
        from dedan_platform.models import User

        from_hospital(bus, "patient.link_requested", link_request("DE000001", phone=PHONE))
        with session_scope() as session:
            session.execute(update(User).where(User.id == patient["id"]).values(is_active=False))
        from_hospital(bus, "patient.link_requested", link_request(patient["dedan"], phone=PHONE))
        run_worker(bus)
        assert [p["reason"] for p in sent(bus, "patient.link_refused")] == ["not_found", "not_found"]
        assert all("name" not in p and "phone" not in p for p in sent(bus, "patient.link_refused"))

    def test_a_malformed_request_is_dead_lettered(self, client, bus, patient):
        from_hospital(bus, "patient.link_requested", {"request_id": "x", "hospital_id": HOSPITAL})
        run_worker(bus)
        assert len(dead_letters(bus)) == 1 and sent(bus) == []


# --- 2. records -------------------------------------------------------------------------------

def lab_record(dedan, record_id=None, version=1, files=(), **extra):
    return {
        "record_id": record_id or hexid(), "version": version, "hospital_id": HOSPITAL,
        "hospital_name": "Zewditu Memorial Hospital", "dedan_id": dedan, "visit_id": hexid(),
        "category": "lab_result", "title": "Complete blood count",
        "details": {"items": [{"test": "Hemoglobin", "value": 10.2, "unit": "g/dL", "reference_range": "12-16",
                               "flag": "low", "secret": "dropped"}, {"test": "WBC", "value": "7.1", "flag": "weird"}],
                    "specimen": "Blood", "notes": None, "script": "<b>unknown key</b>"},
        "occurred_at": "2026-10-01T07:30:00+00:00", "recorded_by": "Dr. Hana Girma", "source": "portal",
        "files": list(files), **extra,
    }


def file_meta(body, content_type="image/png", file_id=None, filename="cbc.png"):
    return {"file_id": file_id or hexid(), "filename": filename, "content_type": content_type,
            "size": len(body), "sha256": hashlib.sha256(body).hexdigest()}


def history(client, auth):
    resp = client.get("/users/me/history", headers=auth)
    assert resp.status_code == 200, resp.text
    return resp.json()


def file_rows():
    from dedan_platform.db import session_scope
    from dedan_platform.models import RecordFile

    with session_scope() as session:
        return {r.file_id: {"status": r.status, "attempts": r.attempts, "error": r.last_error,
                            "next": r.next_attempt_at, "copy": r.copy_id}
                for r in session.scalars(select(RecordFile))}


def stored_copy(record_id, file_id):
    """Where the file's current copy is (None while there is none)."""
    from dedan_platform import record_files

    return record_files.stored_path(record_id, file_id, file_rows()[file_id]["copy"])


def make_due():
    from dedan_platform.db import session_scope
    from dedan_platform.models import RecordFile

    with session_scope() as session:
        session.execute(update(RecordFile).values(next_attempt_at=datetime.now(timezone.utc) - timedelta(seconds=1)))


class TestRecords:
    def test_a_published_record_shows_with_clean_details_and_an_inbox_item(self, client, bus, patient):
        record = lab_record(patient["dedan"])
        from_hospital(bus, "record.published", record)
        run_worker(bus)
        [item] = history(client, patient["auth"])["items"]
        assert item["id"] == record["record_id"] and item["kind"] == "hospital" and item["verified"] is True
        assert item["hospital_name"] == "Zewditu Memorial Hospital" and item["recorded_by"] == "Dr. Hana Girma"
        assert item["details"] == {
            "items": [{"test": "Hemoglobin", "value": "10.2", "unit": "g/dL", "reference_range": "12-16",
                       "flag": "low"},
                      {"test": "WBC", "value": "7.1", "unit": None, "reference_range": None, "flag": None}],
            "specimen": "Blood", "notes": None}
        [notice] = [i for i in inbox(client, patient["auth"]) if i["category"] == "records"]
        assert notice["title"] == "New lab result from Zewditu Memorial Hospital"
        assert notice["link"] == {"screen": "history", "id": record["record_id"]}

    def test_the_highest_version_wins_whatever_the_order(self, client, bus, patient):
        record_id = hexid()
        from_hospital(bus, "record.published", lab_record(patient["dedan"], record_id, 3, title="v3"))
        from_hospital(bus, "record.published", lab_record(patient["dedan"], record_id, 2, title="v2"))
        event_id = hexid()
        from_hospital(bus, "record.published", lab_record(patient["dedan"], record_id, 1, title="v1"), event_id)
        from_hospital(bus, "record.published", lab_record(patient["dedan"], record_id, 1, title="v1"), event_id)
        run_worker(bus)
        [item] = history(client, patient["auth"])["items"]
        assert (item["title"], item["version"]) == ("v3", 3)
        # One record, one inbox item: corrections do not notify again.
        assert len([i for i in inbox(client, patient["auth"]) if i["category"] == "records"]) == 1

    def test_a_retracted_record_is_kept_but_hidden(self, client, bus, patient):
        from dedan_platform.db import session_scope
        from dedan_platform.models import HospitalRecord

        record = lab_record(patient["dedan"])
        from_hospital(bus, "record.published", record)
        from_hospital(bus, "record.retracted", {"record_id": record["record_id"], "hospital_id": HOSPITAL,
                                                "dedan_id": patient["dedan"], "reason": "wrong patient"})
        # A late correction does not bring it back.
        from_hospital(bus, "record.published", {**record, "version": 2})
        run_worker(bus)
        assert history(client, patient["auth"])["items"] == []
        with session_scope() as session:
            row = session.get(HospitalRecord, record["record_id"])
            assert row.retracted_reason == "wrong patient" and row.version == 2

    def test_a_retraction_before_its_record_waits_for_it(self, client, bus, patient, monkeypatch):
        from dedan_platform import eventbus

        monkeypatch.setattr(eventbus, "RETRY_AFTER_MS", 0)
        record = lab_record(patient["dedan"])
        from_hospital(bus, "record.retracted", {"record_id": record["record_id"], "hospital_id": HOSPITAL,
                                                "dedan_id": patient["dedan"], "reason": None})
        run_worker(bus)
        assert dead_letters(bus) == []
        from_hospital(bus, "record.published", record)
        run_worker(bus, rounds=2)
        assert history(client, patient["auth"])["items"] == [] and dead_letters(bus) == []

    def test_another_hospital_cannot_overwrite_or_retract_a_record(self, client, bus, patient):
        record = lab_record(patient["dedan"])
        from_hospital(bus, "record.published", record)
        from_hospital(bus, "record.published", {**record, "version": 9, "hospital_id": OTHER_HOSPITAL,
                                                "title": "forged"})
        from_hospital(bus, "record.retracted", {"record_id": record["record_id"], "hospital_id": OTHER_HOSPITAL,
                                                "dedan_id": patient["dedan"], "reason": "x"})
        run_worker(bus)
        assert [i["title"] for i in history(client, patient["auth"])["items"]] == ["Complete blood count"]
        assert len(dead_letters(bus)) == 2

    @pytest.mark.parametrize("change", [
        {"category": "x-ray"}, {"version": -1}, {"record_id": "../../etc/passwd"}, {"dedan_id": "DE000002"},
        {"occurred_at": "2026-10-01T07:30:00"},
        {"files": [{**file_meta(PNG), "content_type": "text/html"}]},
        {"files": [{**file_meta(PNG), "file_id": "../../../evil"}]},
        {"files": [{**file_meta(PNG), "size": 21 * 1024 * 1024}]},
        {"files": [file_meta(PNG) for _ in range(11)]},
    ])
    def test_malformed_records_are_dead_lettered(self, client, bus, patient, change):
        from_hospital(bus, "record.published", {**lab_record(patient["dedan"]), **change})
        run_worker(bus)
        assert len(dead_letters(bus)) == 1
        assert history(client, patient["auth"])["items"] == []

    def test_other_patients_never_see_a_record_or_its_file(self, client, bus, patient, hospital_api):
        from dedan_platform import record_files

        meta = file_meta(PNG)
        record = lab_record(patient["dedan"], files=[meta])
        hospital_api.files[(record["record_id"], meta["file_id"])] = PNG
        from_hospital(bus, "record.published", record)
        run_worker(bus)
        record_files.download_due()
        other = register(client, email="b@example.com", phone=None)
        assert history(client, other["auth"])["items"] == []
        url = f"/users/me/history/records/{record['record_id']}/files/{meta['file_id']}"
        assert client.get(url, headers=other["auth"]).status_code == 404
        assert client.get(url).status_code == 401
        mine = client.get(url, headers=patient["auth"])
        assert mine.status_code == 200 and mine.content == PNG
        assert mine.headers["content-type"] == "image/png" and mine.headers["x-content-type-options"] == "nosniff"
        assert "sandbox" in mine.headers["content-security-policy"]
        download = client.get(url + "?download=true", headers=patient["auth"])
        assert download.headers["content-disposition"].startswith('attachment; filename="cbc.png"')
        assert client.get(f"/users/me/history/records/{record['record_id']}/files/..%2F..%2Fx",
                          headers=patient["auth"]).status_code == 404


class TestRecordFiles:
    def publish_with(self, bus, patient, hospital_api, body=PNG, content_type="image/png", serve=None):
        meta = file_meta(body, content_type)
        record = lab_record(patient["dedan"], files=[meta])
        hospital_api.files[(record["record_id"], meta["file_id"])] = body if serve is None else serve
        from_hospital(bus, "record.published", record)
        run_worker(bus)
        return record, meta

    def test_files_are_fetched_with_the_key_checked_and_stored(self, client, bus, patient, hospital_api, tmp_path):
        from dedan_platform import record_files

        record, meta = self.publish_with(bus, patient, hospital_api, PDF, "application/pdf")
        # The record shows before its file arrives.
        assert history(client, patient["auth"])["items"][0]["files"][0]["state"] == "arriving"
        assert record_files.download_due() == 1
        assert hospital_api.calls == [(f"/platform/records/{record['record_id']}/files/{meta['file_id']}", KEY)]
        stored = stored_copy(record["record_id"], meta["file_id"])
        assert stored.parent == (tmp_path / "records" / record["record_id"]).resolve()
        assert stored.name.startswith(meta["file_id"] + ".") and stored.read_bytes() == PDF
        assert history(client, patient["auth"])["items"][0]["files"][0]["state"] == "ready"
        assert record_files.download_due() == 0  # nothing more to do

    def test_a_failed_download_is_retried_with_backoff(self, client, bus, patient, hospital_api):
        from dedan_platform import record_files

        record, meta = self.publish_with(bus, patient, hospital_api)
        hospital_api.fail_next = 2
        record_files.download_due()
        first = file_rows()[meta["file_id"]]
        assert first["status"] == "pending" and first["attempts"] == 1 and "503" in first["error"]
        record_files.download_due()  # not due yet: the backoff holds it
        assert len(hospital_api.calls) == 1
        make_due()
        record_files.download_due()
        second = file_rows()[meta["file_id"]]
        assert second["attempts"] == 2
        assert second["next"].replace(tzinfo=timezone.utc) - datetime.now(timezone.utc) > timedelta(seconds=45)
        make_due()
        record_files.download_due()
        assert file_rows()[meta["file_id"]]["status"] == "stored"

    @pytest.mark.parametrize("served,why", [
        (PNG[:-1] + b"X", "sha256"),
        (PNG + b"more", "larger than"),
        (PNG[:-5], "got"),
    ])
    def test_a_file_that_does_not_match_is_not_kept(self, client, bus, patient, hospital_api, tmp_path, served, why):
        from dedan_platform import record_files

        record, meta = self.publish_with(bus, patient, hospital_api, serve=served)
        record_files.download_due()
        row = file_rows()[meta["file_id"]]
        assert row["status"] == "pending" and why in row["error"]
        assert not (tmp_path / "records" / record["record_id"] / meta["file_id"]).exists()
        assert list((tmp_path / "records" / record["record_id"]).iterdir()) == []  # no partial file left

    def test_content_that_is_not_the_declared_type_is_refused(self, client, bus, patient, hospital_api):
        from dedan_platform import record_files

        html = b"<html><script>alert(1)</script></html>"
        record, meta = self.publish_with(bus, patient, hospital_api, html, "image/png")
        record_files.download_due()
        assert "content is not image/png" in file_rows()[meta["file_id"]]["error"]

    def test_after_the_last_retry_the_file_is_unavailable_but_the_record_stays(self, client, bus, patient,
                                                                            hospital_api, monkeypatch):
        from dedan_platform import record_files

        monkeypatch.setattr(record_files, "MAX_ATTEMPTS", 2)
        record, meta = self.publish_with(bus, patient, hospital_api)
        hospital_api.status = 500
        record_files.download_due()
        make_due()
        record_files.download_due()
        assert file_rows()[meta["file_id"]]["status"] == "failed"
        [item] = history(client, patient["auth"])["items"]
        assert item["files"][0]["state"] == "unavailable"

    def test_no_api_configured_means_no_downloads_and_no_errors(self, client, bus, patient, hospital_api, monkeypatch):
        from dedan_platform import record_files

        self.publish_with(bus, patient, hospital_api)
        monkeypatch.delenv("HOSPITAL_API_URL")
        assert record_files.download_due() == 0 and hospital_api.calls == []

    def test_a_correction_refetches_a_changed_file_and_drops_a_removed_one(self, client, bus, patient,
                                                                            hospital_api, tmp_path):
        from dedan_platform import record_files

        kept, dropped = file_meta(PNG), file_meta(PDF, "application/pdf", filename="report.pdf")
        record = lab_record(patient["dedan"], files=[kept, dropped])
        hospital_api.files[(record["record_id"], kept["file_id"])] = PNG
        hospital_api.files[(record["record_id"], dropped["file_id"])] = PDF
        from_hospital(bus, "record.published", record)
        run_worker(bus)
        record_files.download_due()
        old_kept, old_dropped = stored_copy(record["record_id"], kept["file_id"]), \
            stored_copy(record["record_id"], dropped["file_id"])
        assert old_kept.is_file() and old_dropped.is_file()
        new_png = PNG + b"\x01"
        hospital_api.files[(record["record_id"], kept["file_id"])] = new_png
        from_hospital(bus, "record.published", {**record, "version": 2,
                                                "files": [{**kept, "size": len(new_png),
                                                           "sha256": hashlib.sha256(new_png).hexdigest()}]})
        run_worker(bus)
        assert not old_dropped.exists() and not old_kept.exists()
        [item] = history(client, patient["auth"])["items"]
        assert [(f["file_id"], f["state"]) for f in item["files"]] == [(kept["file_id"], "arriving")]
        record_files.download_due()
        new_copy = stored_copy(record["record_id"], kept["file_id"])
        assert new_copy != old_kept and new_copy.read_bytes() == new_png
        assert sorted(p.name for p in new_copy.parent.iterdir()) == [new_copy.name]

    def test_paths_never_leave_the_records_directory(self, tmp_path, monkeypatch):
        from dedan_platform import record_files

        monkeypatch.setenv("RECORD_FILES_DIR", str(tmp_path))
        for bad in ("..", "../" + "a" * 30, "A" * 32, "a" * 31, "/" + "a" * 31):
            with pytest.raises(ValueError):
                record_files.path_for(bad, "a" * 32)
            with pytest.raises(ValueError):
                record_files.path_for("a" * 32, bad)
        for bad_copy in ("..", "../" + "a" * 13, "A" * 16, "a" * 15, "a" * 17, "/" + "a" * 15):
            with pytest.raises(ValueError):
                record_files.path_for("a" * 32, "a" * 32, bad_copy)
            assert record_files.stored_path("a" * 32, "a" * 32, bad_copy) is None


# --- 3. follow-ups ----------------------------------------------------------------------------

def follow_up(dedan, visit_id, days=7, cancelled=False, **extra):
    day = datetime.now(ADDIS).date() + timedelta(days=days)
    return {"visit_id": visit_id, "hospital_id": HOSPITAL, "hospital_name": "Zewditu Memorial Hospital",
            "dedan_id": dedan, "follow_up_on": day.isoformat(), "note": "Bring your results",
            "doctor_name": "Dr. Hana Girma", "cancelled": cancelled, **extra}


def timeline_follow_ups(user_id):
    from dedan_platform.db import session_scope
    from dedan_platform.models import HealthEvent

    with session_scope() as session:
        return [(e.status, e.occurred_at) for e in session.scalars(select(HealthEvent).where(
            HealthEvent.user_id == user_id, HealthEvent.event_type == "FOLLOW_UP"))]


class TestFollowUps:
    def test_a_follow_up_is_shown_texted_now_and_reminded_the_day_before(self, client, bus, patient, listed):
        visit = hexid()
        event = follow_up(patient["dedan"], visit)
        from_hospital(bus, "visit.follow_up", event)
        from_hospital(bus, "visit.follow_up", event)  # sent twice
        run_worker(bus)
        [shown] = client.get("/users/me/follow-ups", headers=patient["auth"]).json()["follow_ups"]
        assert shown["hospital_id"] == HOSPITAL and shown["follow_up_on"] == event["follow_up_on"]
        assert shown["doctor_name"] == "Dr. Hana Girma"
        [(status, when)] = timeline_follow_ups(patient["id"])
        assert status == "SCHEDULED"
        assert [i["kind"] for i in inbox(client, patient["auth"])].count("follow_up_set") == 1
        now_text, reminder = texts(), None
        assert sorted(t["template"] for t in now_text) == ["sms_follow_up_reminder", "sms_follow_up_set"]
        reminder = next(t for t in now_text if t["template"] == "sms_follow_up_reminder")
        expected = datetime.combine(date.fromisoformat(event["follow_up_on"]) - timedelta(days=1),
                                    datetime.min.time().replace(hour=9), ADDIS)
        assert reminder["scheduled_for"].replace(tzinfo=timezone.utc) == expected.astimezone(timezone.utc)
        delivered = deliver_due()
        assert len(delivered) == 1
        phone, text = delivered[0]
        day = date.fromisoformat(event["follow_up_on"])
        assert phone == PHONE and f"{day:%d/%m/%Y}" in text
        for private in ("Zewditu", "Hana", "results"):
            assert private not in text
        later = deliver_due(now=expected.astimezone(timezone.utc) + timedelta(minutes=1))
        assert len(later) == 1 and "tomorrow" in later[0][1]
        assert deliver_due(now=expected.astimezone(timezone.utc) + timedelta(days=2)) == []

    def test_cancelling_removes_it_and_its_reminder(self, client, bus, patient):
        visit = hexid()
        from_hospital(bus, "visit.follow_up", follow_up(patient["dedan"], visit))
        run_worker(bus)
        from_hospital(bus, "visit.follow_up", follow_up(patient["dedan"], visit, cancelled=True))
        run_worker(bus)
        assert client.get("/users/me/follow-ups", headers=patient["auth"]).json()["follow_ups"] == []
        assert {t["status"] for t in texts()} == {"CANCELLED"}
        assert timeline_follow_ups(patient["id"])[0][0] == "CANCELLED"
        assert deliver_due(now=datetime.now(timezone.utc) + timedelta(days=30)) == []

    def test_an_older_change_arriving_late_is_ignored(self, client, bus, patient):
        visit = hexid()
        now = datetime.now(timezone.utc)
        from_hospital(bus, "visit.follow_up", follow_up(patient["dedan"], visit, cancelled=True), occurred_at=now)
        from_hospital(bus, "visit.follow_up", follow_up(patient["dedan"], visit),
                      occurred_at=now - timedelta(minutes=5))
        run_worker(bus)
        assert client.get("/users/me/follow-ups", headers=patient["auth"]).json()["follow_ups"] == []
        assert texts() == []

    def test_a_new_date_replaces_the_old_reminder(self, client, bus, patient):
        visit = hexid()
        from_hospital(bus, "visit.follow_up", follow_up(patient["dedan"], visit, days=5))
        run_worker(bus)
        deliver_due()
        from_hospital(bus, "visit.follow_up", follow_up(patient["dedan"], visit, days=9))
        run_worker(bus)
        reminders = texts("sms_follow_up_reminder")
        assert sorted(r["status"] for r in reminders) == ["CANCELLED", "PENDING"]
        assert len([t for t in texts("sms_follow_up_set") if t["status"] == "SENT"]) == 1
        assert len(deliver_due()) == 1  # the new date, once
        [shown] = client.get("/users/me/follow-ups", headers=patient["auth"]).json()["follow_ups"]
        assert shown["follow_up_on"] == (datetime.now(ADDIS).date() + timedelta(days=9)).isoformat()

    def test_no_texts_without_a_verified_phone_or_with_sms_off(self, client, bus):
        from dedan_platform import identity

        quiet = register(client, email="q@example.com", phone=None)
        off = register(client, email="o@example.com", phone="+251911000999")
        identity.update_preferences(off["id"], {"sms_notifications": False})
        for who in (quiet, off):
            from_hospital(bus, "visit.follow_up", follow_up(who["dedan"], hexid()))
        run_worker(bus)
        assert texts() == []
        assert len(client.get("/users/me/follow-ups", headers=quiet["auth"]).json()["follow_ups"]) == 1

    def test_amharic_accounts_get_amharic_texts(self, client, bus):
        amharic = register(client, email="am@example.com", phone="+251911000777", language="am")
        from_hospital(bus, "visit.follow_up", follow_up(amharic["dedan"], hexid()))
        run_worker(bus)
        [(_phone, text)] = deliver_due()
        assert "ሐኪምዎ" in text and "doctor" not in text


# --- 4. queues ---------------------------------------------------------------------------------

def queue_update(entry_id, seq, dedan=None, phone=None, status="waiting", ahead=3, notify=None, ticket=14):
    return {"entry_id": entry_id, "hospital_id": HOSPITAL, "hospital_name": "Zewditu Memorial Hospital",
            "doctor_name": "Dr. Hana Girma", "day": datetime.now(ADDIS).date().isoformat(), "ticket": ticket,
            "status": status, "ahead": ahead, "dedan_id": dedan, "phone": phone, "patient_name": "Kebede Alemu",
            "notify": notify, "seq": seq}


class TestQueues:
    def test_the_latest_place_is_shown_and_an_older_seq_ignored(self, client, bus, patient):
        entry = hexid()
        from_hospital(bus, "queue.updated", queue_update(entry, 1, patient["dedan"], ahead=6))
        from_hospital(bus, "queue.updated", queue_update(entry, 3, patient["dedan"], ahead=2))
        from_hospital(bus, "queue.updated", queue_update(entry, 2, patient["dedan"], ahead=4))
        run_worker(bus)
        body = client.get("/users/me/queue", headers=patient["auth"]).json()
        assert body["day"] == datetime.now(ADDIS).date().isoformat()
        [shown] = body["entries"]
        assert (shown["ahead"], shown["position"], shown["doctor_name"]) == (2, 3, "Dr. Hana Girma")
        other = register(client, email="b@example.com", phone=None)
        assert client.get("/users/me/queue", headers=other["auth"]).json()["entries"] == []

    def test_one_text_per_notice_whatever_the_retries(self, client, bus, patient):
        entry = hexid()
        near = queue_update(entry, 2, patient["dedan"], ahead=3, notify="near")
        from_hospital(bus, "queue.updated", near)
        from_hospital(bus, "queue.updated", near)  # the same notice, as a new event (a retry)
        from_hospital(bus, "queue.updated", {**near, "seq": 3, "ahead": 2})  # a re-send with a later seq
        run_worker(bus)
        assert len(deliver_due()) == 1
        turn = queue_update(entry, 5, patient["dedan"], status="called", ahead=0, notify="turn")
        from_hospital(bus, "queue.updated", turn)
        from_hospital(bus, "queue.updated", {**turn, "seq": 6})
        run_worker(bus)
        [(phone, text)] = deliver_due()
        assert phone == PHONE and "your turn" in text and "ticket 14" in text
        assert "Hana" not in text and "Zewditu" not in text
        assert sorted(t["template"] for t in texts()) == ["sms_queue_near", "sms_queue_turn"]

    def test_a_walk_in_is_texted_in_amharic_then_english_and_not_kept(self, client, bus):
        from dedan_platform.db import session_scope
        from dedan_platform.models import QueueEntry, User

        entry = hexid()
        from_hospital(bus, "queue.updated", queue_update(entry, 1, phone="0912345678", notify="near", ahead=1))
        run_worker(bus)
        [(phone, text)] = deliver_due()
        amharic, english = text.split("\n")
        assert phone == "+251912345678"
        assert "ከእርስዎ በፊት 1 ሰው አለ" in amharic and "1 person ahead of you" in english
        with session_scope() as session:
            row = session.get(QueueEntry, entry)
            assert row.user_id is None and "Kebede" not in json.dumps(row.__dict__, default=str)
            assert session.scalar(select(User)) is None  # no account was made

    def test_a_late_notice_that_is_no_longer_true_is_not_sent(self, client, bus, patient):
        entry = hexid()
        from_hospital(bus, "queue.updated", queue_update(entry, 4, patient["dedan"], status="done", ahead=0))
        from_hospital(bus, "queue.updated", queue_update(entry, 2, patient["dedan"], notify="near"))
        run_worker(bus)
        assert texts() == []

    def test_a_walk_in_without_a_usable_phone_gets_nothing(self, client, bus):
        from_hospital(bus, "queue.updated", queue_update(hexid(), 1, phone="12345", notify="turn", status="called"))
        run_worker(bus)
        assert texts() == [] and dead_letters(bus) == []

    def test_a_queued_text_is_dropped_when_the_queue_moved_on(self, client, bus, patient):
        entry = hexid()
        from_hospital(bus, "queue.updated", queue_update(entry, 1, patient["dedan"], notify="near"))
        from_hospital(bus, "queue.updated", queue_update(entry, 2, patient["dedan"], status="done", ahead=0))
        run_worker(bus)
        assert deliver_due() == []
        assert texts()[0]["status"] == "SKIPPED"


# --- 5. texts about bookings ----------------------------------------------------------------

class TestBookingTexts:
    def book(self, client, patient):
        from dedan_platform import wallet
        from dedan_platform.db import session_scope
        from dedan_platform.models import WalletEntryKind

        with session_scope() as session:
            wallet.post(session, patient["id"], WalletEntryKind.DEPOSIT, 100_000, description="test")
        at = (datetime.now(ADDIS) + timedelta(days=3)).replace(hour=10, minute=30, second=0, microsecond=0)
        resp = client.post("/users/me/appointments", headers=patient["auth"], json={
            "scheduled_at": at.isoformat(), "timezone": "Africa/Addis_Ababa", "facility_id": HOSPITAL,
            "visit_mode": "in_person", "department": "general_medicine"})
        assert resp.status_code == 201, resp.text
        return resp.json()["appointment"]["appointment_id"], at

    def test_confirmed_then_cancelled_by_the_hospital(self, client, bus, patient, listed):
        appointment_id, at = self.book(client, patient)
        decision = {"appointment_id": appointment_id, "hospital_id": HOSPITAL, "doctor_name": "Dr. Hana"}
        from_hospital(bus, "appointment.confirmed", decision)
        from_hospital(bus, "appointment.confirmed", decision)
        run_worker(bus)
        from_hospital(bus, "appointment.cancelled", {**decision, "reason": "Doctor has a psychiatric emergency"})
        run_worker(bus)
        delivered = deliver_due()
        assert len(delivered) == 2
        confirmed, cancelled = sorted(delivered, key=lambda m: "cancelled" in m[1])
        assert f"{at:%d/%m/%Y %H:%M}" in confirmed[1] and "confirmed" in confirmed[1]
        assert "cancelled" in cancelled[1] and "105.00 birr" in cancelled[1]
        assert "psychiatric" not in cancelled[1] and "Zewditu" not in cancelled[1]
        assert deliver_due() == []

    def test_declined_and_unanswered_and_patient_refunds_are_texted(self, client, bus, patient, listed):
        from dedan_platform import hospital_bookings
        from dedan_platform.db import session_scope
        from dedan_platform.models import Appointment

        declined, _ = self.book(client, patient)
        from_hospital(bus, "appointment.rejected", {"appointment_id": declined, "hospital_id": HOSPITAL})
        run_worker(bus)
        unanswered, _ = self.book(client, patient)
        with session_scope() as session:
            session.execute(update(Appointment).where(Appointment.id == unanswered).values(
                scheduled_at=datetime.now(timezone.utc) - timedelta(hours=3)))
        assert hospital_bookings.refund_unanswered() == 1
        mine, _ = self.book(client, patient)
        assert client.patch(f"/users/me/appointments/{mine}/status", headers=patient["auth"],
                           json={"status": "CANCELLED"}).status_code in (200, 201)
        assert sorted(t["template"] for t in texts() if t["template"].startswith("sms_")) == [
            "sms_booking_declined", "sms_booking_unanswered", "sms_refund"]
        bodies = [m[1] for m in deliver_due()]
        assert len([b for b in bodies if "105.00 birr is back" in b]) == 3


# --- 6. sharing --------------------------------------------------------------------------------

class TestSharing:
    def setup_records(self, client, bus, patient, hospital_api):
        from dedan_platform import record_files

        meta = file_meta(PNG)
        record = lab_record(patient["dedan"], files=[meta])
        hospital_api.files[(record["record_id"], meta["file_id"])] = PNG
        from_hospital(bus, "record.published", record)
        run_worker(bus)
        record_files.download_due()
        own = client.post("/users/me/records", headers=patient["auth"], json={
            "occurred_at": "2026-09-01T09:00:00+03:00", "facility_name": "Bethel Clinic",
            "diagnosis": "Malaria", "medications": [{"name": "Coartem", "dose": "4 tabs"}], "follow_up_days": 14})
        assert own.status_code == 201, own.text
        bus.delete("endod:patient")
        return record, meta, own.json()["record_id"]

    def share(self, client, patient, ids, hospital=HOSPITAL, expires_at=None):
        return client.post("/users/me/shares", headers=patient["auth"], json={
            "hospital_id": hospital, "record_ids": ids, "expires_at": expires_at})

    def test_sharing_sends_the_chosen_records_and_revoking_unshares(self, client, bus, patient, listed,
                                                                    hospital_api):
        record, meta, own_id = self.setup_records(client, bus, patient, hospital_api)
        hospitals = client.get("/users/me/shares/hospitals", headers=patient["auth"]).json()["hospitals"]
        assert [h["hospital_id"] for h in hospitals] == [HOSPITAL]
        until = (datetime.now(ADDIS) + timedelta(days=30)).replace(microsecond=0)
        resp = self.share(client, patient, [record["record_id"], own_id], expires_at=until.isoformat())
        assert resp.status_code == 201, resp.text
        share = resp.json()
        assert share["status"] == "active" and share["record_count"] == 2
        run_worker(bus)
        [event] = sent(bus, "records.shared")
        assert event["share_id"] == share["share_id"] and event["hospital_id"] == HOSPITAL
        assert event["dedan_id"] == patient["dedan"] and event["patient_name"] == "Almaz Tefera"
        assert datetime.fromisoformat(event["expires_at"]) == until
        hospital_rec, own = event["records"]
        assert hospital_rec["origin"] == "Zewditu Memorial Hospital" and hospital_rec["category"] == "lab_result"
        assert hospital_rec["files"] == [meta]
        assert own["origin"] == "Self-reported" and own["category"] == "visit_note" and own["files"] == []
        assert "Malaria" in own["details"]["findings"] and "Coartem 4 tabs" in own["details"]["findings"]
        assert set(hospital_rec) == {"record_id", "origin", "category", "title", "details", "occurred_at",
                                     "recorded_by", "files"}
        listed_shares = client.get("/users/me/shares", headers=patient["auth"]).json()["shares"]
        assert [s["share_id"] for s in listed_shares] == [share["share_id"]]
        assert {r["title"] for r in listed_shares[0]["records"]} == {"Complete blood count", "Bethel Clinic"}
        assert client.delete(f"/users/me/shares/{share['share_id']}", headers=patient["auth"]).status_code == 200
        assert client.delete(f"/users/me/shares/{share['share_id']}", headers=patient["auth"]).status_code == 200
        run_worker(bus)
        assert sent(bus, "records.unshared") == [{"share_id": share["share_id"], "hospital_id": HOSPITAL}]
        assert client.get("/users/me/shares", headers=patient["auth"]).json()["shares"][0]["status"] == "revoked"

    def test_only_listed_partners_own_records_and_sane_dates(self, client, bus, patient, listed, hospital_api):
        record, _meta, own_id = self.setup_records(client, bus, patient, hospital_api)
        assert self.share(client, patient, [own_id], hospital=OTHER_HOSPITAL).status_code == 400
        other = register(client, email="b@example.com", phone=None)
        assert self.share(client, other, [record["record_id"]]).status_code == 404
        assert self.share(client, other, [own_id]).status_code == 404
        assert self.share(client, patient, ["../" + "a" * 29]).status_code == 400
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        assert self.share(client, patient, [own_id], expires_at=past).status_code == 400
        far = (datetime.now(timezone.utc) + timedelta(days=400)).isoformat()
        assert self.share(client, patient, [own_id], expires_at=far).status_code == 400
        from_hospital(bus, "record.retracted", {"record_id": record["record_id"], "hospital_id": HOSPITAL,
                                                "dedan_id": patient["dedan"], "reason": None})
        run_worker(bus)
        assert self.share(client, patient, [record["record_id"]]).status_code == 404
        assert client.delete(f"/users/me/shares/{'d' * 32}", headers=patient["auth"]).status_code == 404
        assert sent(bus, "records.shared") == []

    def test_the_internal_file_endpoint(self, client, bus, patient, listed, hospital_api, monkeypatch):
        record, meta, own_id = self.setup_records(client, bus, patient, hospital_api)
        share = self.share(client, patient, [record["record_id"]]).json()
        url = f"/internal/shares/{share['share_id']}/files/{meta['file_id']}"
        ok = client.get(url, headers={"X-Platform-Key": KEY})
        assert ok.status_code == 200 and ok.content == PNG
        assert client.get(url).status_code == 401
        assert client.get(url, headers={"X-Platform-Key": KEY + "x"}).status_code == 401
        assert client.get(url, headers=patient["auth"]).status_code == 401  # a patient session is no key
        # A file not in this share (another record of the same patient) is not served.
        other_meta = file_meta(PDF, "application/pdf")
        other = lab_record(patient["dedan"], files=[other_meta])
        hospital_api.files[(other["record_id"], other_meta["file_id"])] = PDF
        from_hospital(bus, "record.published", other)
        run_worker(bus)
        from dedan_platform import record_files

        record_files.download_due()
        assert client.get(f"/internal/shares/{share['share_id']}/files/{other_meta['file_id']}",
                          headers={"X-Platform-Key": KEY}).status_code == 404
        assert client.get(f"/internal/shares/{'e' * 32}/files/{meta['file_id']}",
                          headers={"X-Platform-Key": KEY}).status_code == 404
        client.delete(f"/users/me/shares/{share['share_id']}", headers=patient["auth"])
        assert client.get(url, headers={"X-Platform-Key": KEY}).status_code == 410
        monkeypatch.delenv("PLATFORM_ADMIN_KEY")
        assert client.get(url, headers={"X-Platform-Key": KEY}).status_code == 503

    def test_a_file_still_arriving_or_retracted_is_not_served(self, client, bus, patient, listed, hospital_api):
        meta = file_meta(PNG)
        record = lab_record(patient["dedan"], files=[meta])
        from_hospital(bus, "record.published", record)
        run_worker(bus)
        share = self.share(client, patient, [record["record_id"]]).json()
        url = f"/internal/shares/{share['share_id']}/files/{meta['file_id']}"
        assert client.get(url, headers={"X-Platform-Key": KEY}).status_code == 503
        from_hospital(bus, "record.retracted", {"record_id": record["record_id"], "hospital_id": HOSPITAL,
                                                "dedan_id": patient["dedan"], "reason": None})
        run_worker(bus)
        assert client.get(url, headers={"X-Platform-Key": KEY}).status_code == 404

    def test_a_share_ends_by_itself_at_its_expiry(self, client, bus, patient, listed, hospital_api):
        from dedan_platform import events_worker, shares
        from dedan_platform.db import session_scope
        from dedan_platform.models import RecordShare

        record, meta, _own = self.setup_records(client, bus, patient, hospital_api)
        until = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        share = self.share(client, patient, [record["record_id"]], expires_at=until).json()
        assert shares.expire_due() == 0
        with session_scope() as session:
            session.execute(update(RecordShare).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
        url = f"/internal/shares/{share['share_id']}/files/{meta['file_id']}"
        assert client.get(url, headers={"X-Platform-Key": KEY}).status_code == 410  # refused at once
        events_worker._last["shares"] = -10**9
        run_worker(bus)
        assert sent(bus, "records.unshared") == [{"share_id": share["share_id"], "hospital_id": HOSPITAL}]
        assert shares.expire_due() == 0  # told once
        assert client.get("/users/me/shares", headers=patient["auth"]).json()["shares"][0]["status"] == "expired"


# --- review fixes -------------------------------------------------------------------------------

def set_unverified_phone(user_id, phone):
    from dedan_platform.db import session_scope
    from dedan_platform.models import Profile

    with session_scope() as session:
        session.execute(update(Profile).where(Profile.user_id == user_id).values(phone=phone, phone_verified_at=None))


class TestLinkNeedsAVerifiedPhone:
    def test_an_unverified_phone_never_links(self, client, bus):
        unverified = register(client, email="u@example.com", phone=None, linked=False)
        set_unverified_phone(unverified["id"], PHONE)
        request = link_request(unverified["dedan"], phone=PHONE)
        from_hospital(bus, "patient.link_requested", request)
        run_worker(bus)
        assert sent(bus, "patient.linked") == []
        assert [p["reason"] for p in sent(bus, "patient.link_refused")] == ["not_verified"]

    def test_a_card_link_gives_the_phone_only_when_verified(self, client, bus):
        from dedan_platform import cards

        unverified = register(client, email="u@example.com", phone=None, linked=False)
        set_unverified_phone(unverified["id"], PHONE)
        verified = register(client, email="v@example.com", phone="+251911000555", linked=False)
        for who in (unverified, verified):
            from_hospital(bus, "patient.link_requested",
                          link_request(who["dedan"], patient_id=f"MRN-{who['dedan']}",
                                       card_signature=cards.card_signature(who["dedan"])))
        run_worker(bus)
        phones = {p["dedan_id"]: p["phone"] for p in sent(bus, "patient.linked")}
        assert phones == {unverified["dedan"]: None, verified["dedan"]: "+251911000555"}


class TestOnlyLinkedHospitalsSendData:
    def test_records_and_follow_ups_without_a_link_are_dead_lettered_and_never_stored(self, client, bus):
        from dedan_platform.db import session_scope
        from dedan_platform.models import FollowUp, HospitalRecord

        stranger = register(client, email="s@example.com", linked=False)
        linked_elsewhere = register(client, email="e@example.com", phone="+251911000444")  # HOSPITAL only
        from_hospital(bus, "record.published", lab_record(stranger["dedan"]))
        from_hospital(bus, "visit.follow_up", follow_up(stranger["dedan"], hexid()))
        from_hospital(bus, "record.published", lab_record(linked_elsewhere["dedan"], hospital_id=OTHER_HOSPITAL))
        from_hospital(bus, "visit.follow_up", follow_up(linked_elsewhere["dedan"], hexid(),
                                                        hospital_id=OTHER_HOSPITAL))
        run_worker(bus)
        assert len(dead_letters(bus)) == 4
        with session_scope() as session:
            assert session.scalar(select(HospitalRecord)) is None and session.scalar(select(FollowUp)) is None
        for who in (stranger, linked_elsewhere):
            assert history(client, who["auth"])["items"] == []
            assert not [i for i in inbox(client, who["auth"]) if i["category"] == "records"]
        assert texts() == []

    def test_a_link_lets_the_hospital_send_and_tells_the_patient(self, client, bus, listed):
        from dedan_platform import cards

        newcomer = register(client, email="n@example.com", linked=False)
        from_hospital(bus, "patient.link_requested",
                      link_request(newcomer["dedan"], card_signature=cards.card_signature(newcomer["dedan"])))
        run_worker(bus)
        from_hospital(bus, "record.published", lab_record(newcomer["dedan"]))
        run_worker(bus)
        assert dead_letters(bus) == [] and len(history(client, newcomer["auth"])["items"]) == 1
        assert "hospital_linked" in [i["kind"] for i in inbox(client, newcomer["auth"])]

    def test_a_booking_links_the_patient_to_that_hospital(self, client, bus, listed):
        from dedan_platform.db import session_scope
        from dedan_platform.models import HospitalLink

        booker = register(client, email="b@example.com", linked=False)
        TestBookingTexts().book(client, booker)
        with session_scope() as session:
            links = session.scalars(select(HospitalLink).where(HospitalLink.user_id == booker["id"])).all()
            assert [(l.hospital_id, l.patient_id) for l in links] == [(HOSPITAL, f"endod:{booker['dedan']}")]
        from dedan_platform import patient_history

        with session_scope() as session:  # another booking there: still one link
            patient_history.link_booking(session, booker["id"], HOSPITAL)
        from_hospital(bus, "record.published", lab_record(booker["dedan"]))
        from_hospital(bus, "visit.follow_up", follow_up(booker["dedan"], hexid()))
        run_worker(bus)
        assert dead_letters(bus) == []
        assert len(history(client, booker["auth"])["items"]) == 1
        assert len(client.get("/users/me/follow-ups", headers=booker["auth"]).json()["follow_ups"]) == 1
        with session_scope() as session:
            assert len(session.scalars(select(HospitalLink).where(HospitalLink.user_id == booker["id"])).all()) == 1

    def test_an_endod_booking_there_is_enough_without_a_link_row(self, client, bus, listed):
        from dedan_platform.db import session_scope
        from dedan_platform.models import HospitalLink

        booker = register(client, email="b@example.com", linked=False)
        TestBookingTexts().book(client, booker)
        with session_scope() as session:  # a booking made before links were recorded
            session.execute(HospitalLink.__table__.delete())
        from_hospital(bus, "record.published", lab_record(booker["dedan"]))
        run_worker(bus)
        assert dead_letters(bus) == [] and len(history(client, booker["auth"])["items"]) == 1

    def test_an_unlinked_queue_place_is_a_walk_in(self, client, bus):
        from dedan_platform.db import session_scope
        from dedan_platform.models import QueueEntry

        stranger = register(client, email="s@example.com", linked=False)
        entry = hexid()
        from_hospital(bus, "queue.updated", queue_update(entry, 1, stranger["dedan"], phone="0912345678",
                                                         notify="near", ahead=1))
        run_worker(bus)
        assert dead_letters(bus) == []
        assert client.get("/users/me/queue", headers=stranger["auth"]).json()["entries"] == []
        with session_scope() as session:
            assert session.get(QueueEntry, entry).user_id is None
        [(phone, text)] = deliver_due()
        assert phone == "+251912345678" and phone != PHONE
        assert len(text.split("\n")) == 2  # Amharic then English: a walk-in, not the account
        # Without a phone of its own, the account is never texted.
        from_hospital(bus, "queue.updated", queue_update(hexid(), 1, stranger["dedan"], notify="turn",
                                                         status="called", ahead=0))
        run_worker(bus)
        assert deliver_due() == []


def all_paths(routes, prefix=""):
    """Every route path of an app or router, through included routers."""
    paths = set()
    for route in routes:
        if hasattr(route, "original_router"):
            paths |= all_paths(route.original_router.routes)
        elif hasattr(route, "path"):
            paths.add(route.path)
    return paths


class TestInternalApi:
    def internal(self):
        import main_internal

        return TestClient(main_internal.create_app(), base_url="http://endod-platform-api")

    def test_it_serves_only_internal_routes_and_health(self, client):
        from dedan_platform.api_auth import router as auth_router
        from dedan_platform.api_history import router as history_router
        from dedan_platform.api_profile import router as profile_router

        import main_internal

        # Plus the pharmacy site's two routes (docs/pharmacy.md; test_pharmacy.py).
        assert all_paths(main_internal.create_app().routes) == {
            "/health", "/internal/shares/{share_id}/files/{file_id}", "/pharmacy/lookup", "/pharmacy/dispense"}
        internal = self.internal()
        assert internal.get("/health").json()["status"] == "healthy"
        for path in sorted(all_paths(auth_router.routes) | all_paths(profile_router.routes)
                           | all_paths(history_router.routes) | {"/docs", "/openapi.json", "/api/health", "/"}):
            concrete = path.replace("{", "").replace("}", "")
            for method in ("GET", "POST"):
                assert internal.request(method, concrete, headers={"X-Platform-Key": KEY}).status_code in (404, 405), \
                    (method, path)
        # Only the names it is reached by.
        assert TestClient(main_internal.create_app(), base_url="http://backend").get("/health").status_code == 400

    def test_it_serves_a_shared_file_with_the_key_only(self, client, bus, patient, listed, hospital_api):
        sharing = TestSharing()
        record, meta, _own = sharing.setup_records(client, bus, patient, hospital_api)
        share = sharing.share(client, patient, [record["record_id"]]).json()
        url = f"/internal/shares/{share['share_id']}/files/{meta['file_id']}"
        internal = self.internal()
        ok = internal.get(url, headers={"X-Platform-Key": KEY})
        assert ok.status_code == 200 and ok.content == PNG
        assert internal.get(url).status_code == 401
        assert internal.get(url, headers={"X-Platform-Key": "nope", "X-Forwarded-For": "127.0.0.1"}).status_code == 401

    def test_the_patient_app_does_not_serve_internal(self, app_module):
        assert not [p for p in all_paths(app_module.app.routes) if p.startswith("/internal")]
        patient_app = TestClient(app_module.app)
        response = patient_app.get(f"/internal/shares/{'a' * 32}/files/{'a' * 32}", headers={"X-Platform-Key": KEY})
        assert response.status_code == 404


class TestDownloadsNeverEscape:
    publish_with = TestRecordFiles.publish_with

    def leftovers(self, tmp_path, record):
        directory = tmp_path / "records" / record["record_id"]
        return sorted(p.name for p in directory.iterdir()) if directory.exists() else []

    def test_an_invalid_hospital_api_url_fails_the_attempt(self, client, bus, patient, hospital_api, tmp_path,
                                                            monkeypatch):
        from dedan_platform import record_files

        monkeypatch.setattr(record_files, "_transport", None)
        record, meta = self.publish_with(bus, patient, hospital_api)
        for bad in ("http://exa mple:abc", "ftp://endod-hospital-api", "not a url at all"):
            monkeypatch.setenv("HOSPITAL_API_URL", bad)
            make_due()
            assert record_files.download_due() == 1
            row = file_rows()[meta["file_id"]]
            assert row["status"] == "pending" and row["error"]
        assert file_rows()[meta["file_id"]]["attempts"] == 3
        assert self.leftovers(tmp_path, record) == []

    def test_any_error_fails_only_that_attempt_and_leaves_no_part_file(self, client, bus, patient, hospital_api,
                                                                        tmp_path, monkeypatch):
        from dedan_platform import record_files

        record, meta = self.publish_with(bus, patient, hospital_api)

        def broken(*_args):
            raise PermissionError("disk says no")

        monkeypatch.setattr(record_files.os, "replace", broken)
        assert record_files.download_due() == 1
        row = file_rows()[meta["file_id"]]
        assert row["status"] == "pending" and "PermissionError" in row["error"]
        assert self.leftovers(tmp_path, record) == []

        def exploding(request):
            raise RuntimeError("unexpected")

        monkeypatch.setattr(record_files, "_transport", httpx.MockTransport(exploding))
        make_due()
        assert record_files.download_due() == 1
        assert "RuntimeError" in file_rows()[meta["file_id"]]["error"]
        assert self.leftovers(tmp_path, record) == []

    def test_a_download_has_a_deadline_inside_the_stale_window(self, client, bus, patient, hospital_api, tmp_path,
                                                               monkeypatch):
        from dedan_platform import record_files

        read_timeout = record_files.TIMEOUT.read + record_files.TIMEOUT.connect
        assert record_files.DOWNLOAD_DEADLINE_SECONDS <= 300
        assert record_files.STALE_DOWNLOAD.total_seconds() >= 2 * (record_files.DOWNLOAD_DEADLINE_SECONDS
                                                                   + read_timeout)
        record, meta = self.publish_with(bus, patient, hospital_api)
        monkeypatch.setattr(record_files, "DOWNLOAD_DEADLINE_SECONDS", 0.0)
        record_files.download_due()
        assert "took longer than" in file_rows()[meta["file_id"]]["error"]
        assert self.leftovers(tmp_path, record) == []

    def test_a_claim_counts_as_an_attempt_even_if_its_worker_dies(self, client, bus, patient, hospital_api,
                                                                  monkeypatch):
        from dedan_platform import record_files
        from dedan_platform.db import session_scope
        from dedan_platform.models import RecordFile

        def make_stale():
            with session_scope() as session:
                session.execute(update(RecordFile).values(
                    updated_at=datetime.now(timezone.utc) - record_files.STALE_DOWNLOAD - timedelta(seconds=1)))

        record, meta = self.publish_with(bus, patient, hospital_api)
        assert record_files._claim()["attempts"] == 1  # then the worker dies
        assert file_rows()[meta["file_id"]]["status"] == "downloading"
        assert record_files.download_due() == 0  # not stale yet: nobody else takes it
        make_stale()
        assert record_files.download_due() == 1
        row = file_rows()[meta["file_id"]]
        assert (row["status"], row["attempts"]) == ("stored", 2)

        # Out of attempts: a reclaim gives up without fetching.
        monkeypatch.setattr(record_files, "MAX_ATTEMPTS", 1)
        other, other_meta = self.publish_with(bus, patient, hospital_api)
        record_files._claim()
        make_stale()
        calls = len(hospital_api.calls)
        record_files.download_due()
        assert file_rows()[other_meta["file_id"]]["status"] == "failed" and len(hospital_api.calls) == calls

    def test_a_download_whose_claim_was_taken_over_keeps_nothing(self, client, bus, patient, hospital_api,
                                                                 tmp_path, monkeypatch):
        from dedan_platform import record_files
        from dedan_platform.db import session_scope
        from dedan_platform.models import RecordFile

        record, meta = self.publish_with(bus, patient, hospital_api)
        serve = hospital_api.handler

        def taken_over(request):
            with session_scope() as session:  # another worker claimed it meanwhile
                session.execute(update(RecordFile).values(attempts=RecordFile.attempts + 1))
            return serve(request)

        monkeypatch.setattr(record_files, "_transport", httpx.MockTransport(taken_over))
        assert record_files.download_one() == "retry"
        assert file_rows()[meta["file_id"]]["status"] == "downloading"  # the other worker's
        assert self.leftovers(tmp_path, record) == []


class TestCorrectionsKeepTheNewCopy:
    def test_an_old_copy_removed_late_never_takes_the_new_one(self, client, bus, patient, hospital_api, monkeypatch):
        from dedan_platform import eventbus, record_files

        meta = file_meta(PNG)
        record = lab_record(patient["dedan"], files=[meta])
        hospital_api.files[(record["record_id"], meta["file_id"])] = PNG
        from_hospital(bus, "record.published", record)
        run_worker(bus)
        record_files.download_due()
        old = stored_copy(record["record_id"], meta["file_id"])

        # The correction commits; its clean-up runs only after the new copy arrived.
        late = []
        monkeypatch.setattr(eventbus, "after_commit", lambda session, action: late.append(action))
        new_png = PNG + b"\x02"
        hospital_api.files[(record["record_id"], meta["file_id"])] = new_png
        from_hospital(bus, "record.published", {**record, "version": 2, "files": [
            {**meta, "size": len(new_png), "sha256": hashlib.sha256(new_png).hexdigest()}]})
        run_worker(bus)
        record_files.download_due()
        new = stored_copy(record["record_id"], meta["file_id"])
        for action in late:
            action()
        assert new != old and new.read_bytes() == new_png and not old.exists()
        url = f"/users/me/history/records/{record['record_id']}/files/{meta['file_id']}"
        assert client.get(url, headers=patient["auth"]).content == new_png

    def test_the_current_copy_is_never_forgotten(self, client, bus, patient, hospital_api):
        from dedan_platform import record_files

        meta = file_meta(PNG)
        record = lab_record(patient["dedan"], files=[meta])
        hospital_api.files[(record["record_id"], meta["file_id"])] = PNG
        from_hospital(bus, "record.published", record)
        run_worker(bus)
        record_files.download_due()
        current = stored_copy(record["record_id"], meta["file_id"])
        record_files.forget_copy(record["record_id"], meta["file_id"], file_rows()[meta["file_id"]]["copy"])
        assert current.read_bytes() == PNG


class TestFollowUpMovedToAnotherPatient:
    def test_it_leaves_the_first_account_with_its_texts(self, client, bus, patient):
        from dedan_platform.db import session_scope
        from dedan_platform.models import FollowUp

        other = register(client, email="b@example.com", phone="+251911000888")
        visit = hexid()
        now = datetime.now(timezone.utc)
        from_hospital(bus, "visit.follow_up", follow_up(patient["dedan"], visit), occurred_at=now)
        run_worker(bus)
        assert len(deliver_due()) == 1  # the first patient was told
        from_hospital(bus, "visit.follow_up", follow_up(other["dedan"], visit),
                      occurred_at=now + timedelta(seconds=1))
        run_worker(bus)
        assert client.get("/users/me/follow-ups", headers=patient["auth"]).json()["follow_ups"] == []
        assert timeline_follow_ups(patient["id"]) == []
        [(status, _when)] = timeline_follow_ups(other["id"])
        assert status == "SCHEDULED"
        assert len(client.get("/users/me/follow-ups", headers=other["auth"]).json()["follow_ups"]) == 1
        mine = [t for t in texts() if t["user_id"] == patient["id"]]
        assert {t["template"]: t["status"] for t in mine} == {
            "sms_follow_up_set": "SENT", "sms_follow_up_reminder": "CANCELLED"}
        theirs = [t for t in texts() if t["user_id"] == other["id"]]
        assert sorted(t["template"] for t in theirs) == ["sms_follow_up_reminder", "sms_follow_up_set"]
        [(phone, _text)] = deliver_due()
        assert phone == "+251911000888"
        assert "follow_up_set" in [i["kind"] for i in inbox(client, other["auth"])]
        # The same change again: nothing new for either.
        from_hospital(bus, "visit.follow_up", follow_up(other["dedan"], visit),
                      occurred_at=now + timedelta(seconds=2))
        run_worker(bus)
        assert len(timeline_follow_ups(other["id"])) == 1 and deliver_due() == []
        with session_scope() as session:
            assert session.scalar(select(FollowUp)).user_id == other["id"]
