"""SMS-first (docs/sms.md): SMS-only patients enrolled by a hospital, pushed
"ready" notices, and the commands patients text to the short code.

Redis is in memory (fakeredis); every SMS provider is a fake that records
what it was asked to send."""

import hashlib
import hmac
import json
import re
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from test_patient_history import (  # noqa: F401 -- shared helpers and fixtures
    HOSPITAL, PHONE, FakeSms, bus, client, deliver_due, follow_up, from_hospital, hexid, lab_record, register,
    run_worker, sent, texts,
)

from dedan_platform.sms_provider import BRAND_NAME as BRAND  # noqa: E402

NEW_PHONE = "+251922334455"
PATIENT_ID = "f" * 32
SECRET = "inbound-test-secret-0123456789abcdef"
SHORT = "8123"


@pytest.fixture
def sms(monkeypatch):
    """What the enrolment texts (codes, welcome texts) and command replies go through."""
    from dedan_platform import api_sms, sms_enrol

    fake = FakeSms()
    monkeypatch.setattr(sms_enrol, "provider", fake)
    monkeypatch.setattr(api_sms, "reply_provider", fake)
    return fake


@pytest.fixture
def live(monkeypatch):
    """The short code is live (inbound on, a short code and a secret)."""
    monkeypatch.setenv("SMS_INBOUND_ENABLED", "true")
    monkeypatch.setenv("SMS_SHORT_CODE", SHORT)
    monkeypatch.setenv("SMS_INBOUND_SECRET", SECRET)


# --- enrolment ---------------------------------------------------------------------------------

def ask_enrol(bus, phone=NEW_PHONE, patient_id=PATIENT_ID, request_id=None):
    request_id = request_id or hexid()
    from_hospital(bus, "patient.sms_enrol_requested", {"request_id": request_id, "hospital_id": HOSPITAL,
                                                       "patient_id": patient_id, "phone": phone})
    run_worker(bus)
    return request_id


def verify(bus, request_id, code, patient_id=PATIENT_ID, name="Abebe Kebede", language="am"):
    from_hospital(bus, "patient.sms_enrol_verify", {"request_id": request_id, "hospital_id": HOSPITAL,
                                                    "patient_id": patient_id, "code": code, "name": name,
                                                    "language": language})
    run_worker(bus)


def code_in(text):
    return re.search(r"\b(\d{6})\b", text).group(1)


def pin_in(text):
    return re.search(r"(?:PIN is|ፒንዎ) (\d{4})", text).group(1)


def account(phone=NEW_PHONE):
    from dedan_platform.db import session_scope
    from dedan_platform.models import Profile, User

    with session_scope() as session:
        user = session.scalar(select(User).join(Profile, Profile.user_id == User.id).where(Profile.phone == phone))
        return None if user is None else {"id": user.id, "dedan": user.dedan_user_id, "sms_only": user.sms_only}


def enrolled_patient(bus, sms, phone=NEW_PHONE, language="am"):
    request_id = ask_enrol(bus, phone)
    verify(bus, request_id, code_in(sms.sent[-1][1]), language=language)
    return {**account(phone), "pin": pin_in(sms.sent[-1][1]), "phone": phone}


class TestEnrolment:
    def test_code_then_account_link_card_and_pin(self, client, bus, sms):
        from dedan_platform.db import session_scope
        from dedan_platform.models import HospitalLink, SmsPin, UserEvent

        request_id = ask_enrol(bus)
        [(to, text)] = sms.sent
        assert to == NEW_PHONE and "reception" in text
        [code_sent] = sent(bus, "patient.sms_enrol_code_sent")
        assert code_sent["request_id"] == request_id and code_sent["patient_id"] == PATIENT_ID
        assert account() is None  # nothing before the code

        verify(bus, request_id, code_in(text))
        [enrolled] = sent(bus, "patient.sms_enrolled")
        user = account()
        assert enrolled == {"request_id": request_id, "hospital_id": HOSPITAL, "patient_id": PATIENT_ID,
                            "dedan_id": user["dedan"], "name": "Abebe Kebede", "phone": NEW_PHONE, "created": True}
        assert user["sms_only"] is True
        to, welcome = sms.sent[-1]
        assert to == NEW_PHONE and user["dedan"] in welcome
        pin = pin_in(welcome)
        # The short code is not live: no command to text, nothing misleading.
        assert "HELP" not in welcome and SHORT not in welcome
        with session_scope() as session:
            assert session.scalar(select(HospitalLink.user_id).where(HospitalLink.patient_id == PATIENT_ID)) == user["id"]
            row = session.get(SmsPin, user["id"])
            assert row is not None and pin not in row.pin_hash  # stored as an HMAC only
            assert session.scalar(select(func.count()).select_from(UserEvent).where(
                UserEvent.user_id == user["id"], UserEvent.event_type == "sms_enrolled")) == 1

    def test_with_the_short_code_live_the_welcome_says_how_to_use_it(self, client, bus, sms, live):
        patient = enrolled_patient(bus, sms, language="en")
        welcome = sms.sent[-1][1]
        assert f"Text HELP to {SHORT}" in welcome and f"PIN {patient['pin']}" in welcome

    def test_a_wrong_code_spends_an_attempt_and_the_right_one_still_works(self, client, bus, sms):
        request_id = ask_enrol(bus)
        code = code_in(sms.sent[-1][1])
        wrong = "000000" if code != "000000" else "111111"
        verify(bus, request_id, wrong)
        assert sent(bus, "patient.sms_enrol_refused") == [{
            "request_id": request_id, "hospital_id": HOSPITAL, "patient_id": PATIENT_ID, "reason": "wrong_code",
            "attempts_left": 4}]
        verify(bus, request_id, code)
        assert len(sent(bus, "patient.sms_enrolled")) == 1

    def test_five_wrong_codes_lock_the_request(self, client, bus, sms):
        request_id = ask_enrol(bus)
        code = code_in(sms.sent[-1][1])
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(5):
            verify(bus, request_id, wrong)
        verify(bus, request_id, code)
        reasons = [(e["reason"], e["attempts_left"]) for e in sent(bus, "patient.sms_enrol_refused")]
        assert reasons == [("wrong_code", 4), ("wrong_code", 3), ("wrong_code", 2), ("wrong_code", 1),
                           ("too_many_attempts", 0), ("too_many_attempts", 0)]
        assert sent(bus, "patient.sms_enrolled") == [] and account() is None

    def test_an_expired_code(self, client, bus, sms):
        from dedan_platform.db import session_scope
        from dedan_platform.models import SmsEnrolment

        request_id = ask_enrol(bus)
        with session_scope() as session:
            session.execute(update(SmsEnrolment).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
        verify(bus, request_id, code_in(sms.sent[-1][1]))
        assert [e["reason"] for e in sent(bus, "patient.sms_enrol_refused")] == ["expired"]
        assert account() is None

    def test_only_the_newest_request_counts_and_sending_is_limited(self, client, bus, sms, monkeypatch):
        first = ask_enrol(bus)
        first_code = code_in(sms.sent[-1][1])
        ask_enrol(bus)  # at once: within the cooldown
        assert [e["reason"] for e in sent(bus, "patient.sms_enrol_refused")] == ["rate_limited"]
        monkeypatch.setenv("SMS_ENROL_RESEND_SECONDS", "0")
        ask_enrol(bus)
        verify(bus, first, first_code)
        assert [e["reason"] for e in sent(bus, "patient.sms_enrol_refused")] == ["rate_limited", "superseded"]
        monkeypatch.setenv("SMS_ENROL_MAX_PER_PHONE_PER_HOUR", "2")
        ask_enrol(bus)
        assert sent(bus, "patient.sms_enrol_refused")[-1]["reason"] == "rate_limited"
        assert len(sms.sent) == 2  # two codes, no more

    def test_an_invalid_phone_and_a_provider_failure(self, client, bus, sms, monkeypatch):
        from dedan_platform import sms_enrol
        from dedan_platform.sms_provider import SmsProviderError

        ask_enrol(bus, phone="12345")

        class Down:
            def send(self, phone, text):
                raise SmsProviderError("down")

        monkeypatch.setattr(sms_enrol, "provider", Down())
        ask_enrol(bus)
        assert [e["reason"] for e in sent(bus, "patient.sms_enrol_refused")] == ["invalid_phone", "sms_unavailable"]
        assert sms.sent == []

    def test_a_phone_with_an_app_account_links_that_account(self, client, bus, sms):
        patient = register(client, phone=NEW_PHONE, linked=False)
        request_id = ask_enrol(bus)
        verify(bus, request_id, code_in(sms.sent[-1][1]))
        [enrolled] = sent(bus, "patient.sms_enrolled")
        assert enrolled["dedan_id"] == patient["dedan"] and enrolled["created"] is False
        assert enrolled["name"] == "Almaz Tefera"
        user = account()
        assert user["id"] == patient["id"] and not user["sms_only"]
        # It had no PIN: it gets one, with the card number.
        assert patient["dedan"] in sms.sent[-1][1] and pin_in(sms.sent[-1][1])

    def test_a_suspended_account_is_not_enrolled(self, client, bus, sms):
        from dedan_platform.db import session_scope
        from dedan_platform.models import HospitalLink, User

        patient = register(client, phone=NEW_PHONE, linked=False)
        with session_scope() as session:
            session.execute(update(User).where(User.id == patient["id"]).values(suspended_at=datetime.now(timezone.utc)))
        request_id = ask_enrol(bus)
        verify(bus, request_id, code_in(sms.sent[-1][1]))
        assert [e["reason"] for e in sent(bus, "patient.sms_enrol_refused")] == ["not_allowed"]
        with session_scope() as session:
            assert session.scalar(select(func.count()).select_from(HospitalLink)) == 0

    def test_enrolled_again_gets_a_new_pin(self, client, bus, sms, monkeypatch):
        monkeypatch.setenv("SMS_ENROL_RESEND_SECONDS", "0")
        first = enrolled_patient(bus, sms)
        again = enrolled_patient(bus, sms)
        assert again["dedan"] == first["dedan"]
        assert sent(bus, "patient.sms_enrolled")[-1]["created"] is False

    def test_signing_up_in_the_app_later_takes_the_account_over(self, client, bus, sms):
        from dedan_platform import phone_auth

        patient = enrolled_patient(bus, sms)
        app_sms = FakeSms()
        phone_auth.request_code(patient["phone"], client="test", provider=app_sms)
        verified = phone_auth.verify_code(patient["phone"], code_in(app_sms.sent[-1][1]))
        assert verified["account_exists"] is True
        done = phone_auth.complete(verified["verification_token"], "Str0ng-pass!", "Str0ng-pass!")
        assert done["created"] is False and done["dedan_user_id"] == patient["dedan"]
        user = account()
        assert user["id"] == patient["id"] and user["sms_only"] is False
        login = client.post("/auth/login", json={"identifier": patient["phone"], "password": "Str0ng-pass!"})
        assert login.status_code == 200, login.text
        inbox = client.get("/users/me/inbox", headers={"Authorization": done["access_token"]}).json()["items"]
        assert [i["kind"] for i in inbox if i["category"] == "security"] == ["app_account_activated"]


# --- pushed notices ----------------------------------------------------------------------------

class TestReadyNotices:
    def test_an_sms_only_patient_is_told_to_ask_at_the_hospital_until_the_short_code_is_live(
            self, client, bus, sms, monkeypatch):
        patient = enrolled_patient(bus, sms, language="en")
        from_hospital(bus, "record.published", lab_record(patient["dedan"]))
        run_worker(bus)
        [ready] = texts("sms_record_ready")
        assert ready["destination"] == NEW_PHONE
        [(_to, text)] = deliver_due()
        assert text == f"{BRAND}: a new lab result from your hospital is ready. Please ask at the hospital to see it."

    def test_with_the_short_code_live_it_names_the_command(self, client, bus, sms, live):
        patient = enrolled_patient(bus, sms, language="en")
        from_hospital(bus, "record.published", {**lab_record(patient["dedan"]), "category": "imaging",
                                                "details": {"modality": "X-ray"}})
        run_worker(bus)
        [(_to, text)] = deliver_due()
        assert text == (f"{BRAND}: a new medical report from your hospital is ready. Text REPORT and your PIN to "
                        f"{SHORT} to read it.")

    def test_app_patients_who_allow_sms_get_it_in_their_language(self, client, bus, live):
        patient = register(client, language="am")
        from_hospital(bus, "record.published", lab_record(patient["dedan"]))
        run_worker(bus)
        [(_to, text)] = deliver_due()
        # No PIN: no command, only the app.
        assert text == f"{BRAND}፦ ከሆስፒታልዎ አዲስ የላብራቶሪ ውጤት ደርሷል። ለማየት የ{BRAND} መተግበሪያን ይክፈቱ።"

    def test_one_notice_a_day_per_kind_never_for_imports_or_without_sms(self, client, bus):
        from dedan_platform import identity

        patient = register(client)
        for _ in range(3):
            from_hospital(bus, "record.published", lab_record(patient["dedan"]))
        from_hospital(bus, "record.published", {**lab_record(patient["dedan"]), "source": "import"})
        run_worker(bus)
        assert len(texts("sms_record_ready")) == 1
        other = register(client, email="b@example.com", phone="+251933445566")
        identity.update_preferences(other["id"], {"sms_notifications": False})
        from_hospital(bus, "record.published", lab_record(other["dedan"]))
        run_worker(bus)
        assert len(texts("sms_record_ready")) == 1

    def test_a_retracted_record_is_not_announced(self, client, bus):
        patient = register(client)
        record = lab_record(patient["dedan"])
        from_hospital(bus, "record.published", record)
        from_hospital(bus, "record.retracted", {"record_id": record["record_id"], "hospital_id": HOSPITAL,
                                                "dedan_id": patient["dedan"], "reason": "wrong patient"})
        run_worker(bus)
        assert deliver_due() == []

    def test_follow_ups_and_prescription_codes_reach_sms_only_patients(self, client, bus, sms):
        patient = enrolled_patient(bus, sms, language="en")
        from_hospital(bus, "visit.follow_up", follow_up(patient["dedan"], hexid(), days=7))
        from_hospital(bus, "record.published", {
            "record_id": hexid(), "version": 1, "hospital_id": HOSPITAL, "hospital_name": "Zewditu Memorial Hospital",
            "dedan_id": patient["dedan"], "category": "prescription", "title": "Chest infection",
            "details": {"items": [{"drug": "Amoxicillin", "quantity": "21 tablets"}]},
            "occurred_at": datetime.now(timezone.utc).isoformat(), "source": "portal"})
        run_worker(bus)
        delivered = [text for _to, text in deliver_due()]
        assert any("follow-up visit" in t and "contact the hospital" in t and "app" not in t for t in delivered)
        assert any("prescription code" in t for t in delivered)
        assert not texts("sms_record_ready")  # a prescription is announced by its code


# --- the commands ------------------------------------------------------------------------------

@pytest.fixture
def inbound(client):
    from dedan_platform.api_sms import patient_router, router

    app = FastAPI()
    app.include_router(router)
    app.include_router(patient_router)
    return TestClient(app)


def text_in(inbound, text, phone=NEW_PHONE, message_id=None):
    """Africa's Talking's callback; returns the reply sent back (or None)."""
    from dedan_platform import api_sms

    before = len(api_sms.reply_provider.sent)
    resp = inbound.post(f"/sms/v1/inbound/africastalking/{SECRET}", data={
        "from": phone, "to": SHORT, "text": text, "id": message_id or hexid(), "date": "2026-11-03 10:00:00",
        "linkId": "", "networkCode": "63902"})
    assert resp.status_code == 200, resp.text
    replies = api_sms.reply_provider.sent[before:]
    assert len(replies) <= 1
    assert all(to == phone for to, _text in replies)
    return replies[0][1] if replies else None


def labs(dedan, items, title="Complete blood count", days_ago=0):
    record = lab_record(dedan, title=title, details={"items": items})
    record["occurred_at"] = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return record


class TestInbound:
    def test_off_by_default_everything_is_not_found(self, client, inbound, sms, monkeypatch):
        monkeypatch.setenv("SMS_INBOUND_SECRET", SECRET)
        assert inbound.post(f"/sms/v1/inbound/africastalking/{SECRET}", data={"from": NEW_PHONE}).status_code == 404
        assert inbound.post("/sms/v1/inbound/generic", json={}).status_code == 404

    def test_authentication(self, client, inbound, sms, live, monkeypatch):
        assert inbound.post("/sms/v1/inbound/africastalking/wrong", data={"from": NEW_PHONE}).status_code == 404
        assert inbound.post("/sms/v1/inbound/generic", json={"from": NEW_PHONE, "text": "HELP"}).status_code == 404
        bad = inbound.post("/sms/v1/inbound/generic", content=b"{}",
                           headers={"X-Endod-Signature": f"t={int(time.time())},v1=" + "0" * 64})
        assert bad.status_code == 404
        monkeypatch.setenv("EDGE_SHARED_SECRET", "edge-secret")
        assert inbound.post(f"/sms/v1/inbound/africastalking/{SECRET}", data={"from": NEW_PHONE}).status_code == 403
        ok = inbound.post(f"/sms/v1/inbound/africastalking/{SECRET}", data={"from": NEW_PHONE, "text": "HELP"},
                          headers={"X-Endod-Edge-Key": "edge-secret"})
        assert ok.status_code == 200

    def test_the_generic_adapter_answers_in_the_body(self, client, bus, inbound, sms, live):
        patient = enrolled_patient(bus, sms, language="en")
        body = json.dumps({"from": "0922334455", "to": SHORT, "text": f"card {patient['pin']}", "id": "m-1"}).encode()
        stamp = int(time.time())
        signature = hmac.new(SECRET.encode(), f"{stamp}.".encode() + body, hashlib.sha256).hexdigest()
        resp = inbound.post("/sms/v1/inbound/generic", content=body,
                            headers={"X-Endod-Signature": f"t={stamp},v1={signature}",
                                     "Content-Type": "application/json"})
        assert resp.status_code == 200
        assert resp.json() == {"reply": f"{BRAND}: your Endod card number (Endod ID) is {patient['dedan']}.",
                               "to": NEW_PHONE}

    def test_card_appt_rx_and_help(self, client, bus, inbound, sms, live):
        patient = enrolled_patient(bus, sms, language="en")
        pin = patient["pin"]
        assert text_in(inbound, f"CARD {pin}") == f"{BRAND}: your Endod card number (Endod ID) is {patient['dedan']}."
        assert text_in(inbound, f"appt {pin}") == f"{BRAND}: you have no upcoming visits."
        from_hospital(bus, "visit.follow_up", follow_up(patient["dedan"], hexid(), days=7))
        run_worker(bus)
        appt = text_in(inbound, f"APPT {pin}")
        assert "follow-up at Zewditu Memorial Hospital" in appt
        assert text_in(inbound, f"RX {pin}") == f"{BRAND}: you have no prescriptions to collect."
        from_hospital(bus, "record.published", {
            "record_id": hexid(), "version": 1, "hospital_id": HOSPITAL, "hospital_name": "Zewditu Memorial Hospital",
            "dedan_id": patient["dedan"], "category": "prescription", "title": "Chest infection",
            "details": {"items": [{"drug": "Amoxicillin", "quantity": "21 tablets"}]},
            "occurred_at": datetime.now(timezone.utc).isoformat(), "source": "portal"})
        run_worker(bus)
        rx = text_in(inbound, f"rx {pin}")
        assert re.search(r"Code \d{6}, until \d\d/\d\d/\d{4}, Zewditu Memorial Hospital", rx)
        assert "CARD, APPT, RESULT, REPORT or RX" in text_in(inbound, "HELP")
        assert "CARD, APPT, RESULT, REPORT or RX" in text_in(inbound, "hello")
        assert text_in(inbound, "CARD") == (f"{BRAND}: send the command and your 4-digit PIN, e.g. CARD 1234. "
                                            "Send HELP for the list.")

    def test_results_three_at_a_time_and_older_ones(self, client, bus, inbound, sms, live):
        patient = enrolled_patient(bus, sms, language="en")
        items = [{"test": f"Test {n}", "value": n, "unit": "mg/dL", "flag": "high" if n == 1 else "normal"}
                 for n in range(1, 5)]
        from_hospital(bus, "record.published", labs(patient["dedan"], items))
        run_worker(bus)
        first = text_in(inbound, f"RESULT {patient['pin']}")
        assert first.splitlines()[0] == f"{BRAND} lab results:"
        assert "Test 1: 1 mg/dL (HIGH)" in first and "Test 3: 3 mg/dL (normal)" in first
        assert "Test 4" not in first and first.endswith("Older: RESULT 2 and your PIN")
        second = text_in(inbound, f"RESULT 2 {patient['pin']}")
        assert "Test 4: 4 mg/dL (normal)" in second and "Older" not in second
        assert text_in(inbound, f"RESULT 3 {patient['pin']}") == f"{BRAND}: no older lab results."

    def test_sensitive_results_are_never_sent(self, client, bus, inbound, sms, live):
        patient = enrolled_patient(bus, sms, language="en")
        from_hospital(bus, "record.published", labs(patient["dedan"], [
            {"test": "HIV 1/2 antibody", "value": "reactive"},
            {"test": "Rapid test", "code": "7917-8", "value": "positive"},
            {"test": "Glucose", "value": 5.1, "unit": "mmol/L", "flag": "normal"}]))
        from_hospital(bus, "record.published", labs(patient["dedan"], [{"test": "Urine test", "value": "positive"}],
                                                    title="Pregnancy test", days_ago=1))
        run_worker(bus)
        reply = text_in(inbound, f"RESULT {patient['pin']}")
        assert "reactive" not in reply and "positive" not in reply and "HIV" not in reply
        assert reply.count("only available at the hospital or in the app") == 2
        assert "Glucose: 5.1 mmol/L (normal)" in reply
        older = text_in(inbound, f"RESULT 2 {patient['pin']}")
        assert "positive" not in older and "Pregnancy" not in older and "only available" in older
        from dedan_platform.db import session_scope
        from dedan_platform.models import SmsInboundMessage

        with session_scope() as session:
            outcomes = session.scalars(select(SmsInboundMessage.outcome).where(
                SmsInboundMessage.command == "RESULT")).all()
        assert outcomes == ["ok_withheld", "ok_withheld"]

    def test_reports_title_and_conclusion_and_a_sensitive_diagnosis(self, client, bus, inbound, sms, live):
        patient = enrolled_patient(bus, sms, language="en")
        from_hospital(bus, "record.published", {**lab_record(patient["dedan"]), "category": "diagnosis",
                                                "title": "Diagnosis", "details": {"condition": "Depressive episode",
                                                                                  "code": "F32.1"},
                                                "occurred_at": "2026-10-01T07:30:00+00:00"})
        from_hospital(bus, "record.published", {**lab_record(patient["dedan"]), "category": "imaging",
                                                "title": "Chest X-ray",
                                                "details": {"modality": "X-ray", "impression": "No pneumonia."},
                                                "occurred_at": "2026-10-20T07:30:00+00:00"})
        run_worker(bus)
        latest = text_in(inbound, f"REPORT {patient['pin']}")
        assert latest == f"{BRAND} 20/10/2026: Chest X-ray. No pneumonia.\nOlder: REPORT 2 and your PIN"
        older = text_in(inbound, f"REPORT 2 {patient['pin']}")
        assert "Depressive" not in older and "only available at the hospital or in the app" in older

    def test_change_the_pin(self, client, bus, inbound, sms, live):
        patient = enrolled_patient(bus, sms, language="en")
        assert "4 digits" in text_in(inbound, f"PIN {patient['pin']} 1234")
        assert text_in(inbound, f"PIN {patient['pin']} 7395").startswith(f"{BRAND}: your PIN was changed.")
        assert "wrong PIN" in text_in(inbound, f"CARD {patient['pin']}")
        assert patient["dedan"] in text_in(inbound, "CARD 7395")

    def test_five_wrong_pins_lock_it_for_an_hour_and_say_so(self, client, bus, inbound, sms, live):
        patient = enrolled_patient(bus, sms, language="en")
        wrong = "5678" if patient["pin"] != "5678" else "5679"
        replies = [text_in(inbound, f"CARD {wrong}") for _ in range(5)]
        assert replies[0] == f"{BRAND}: wrong PIN. 4 tries left before it is locked for an hour."
        assert replies[4].startswith(f"{BRAND}: too many wrong PINs. Your PIN is locked until ")
        locked = text_in(inbound, f"CARD {patient['pin']}")
        assert locked.startswith(f"{BRAND}: your PIN is locked until ") and patient["dedan"] not in locked
        from dedan_platform.db import session_scope
        from dedan_platform.models import SmsPin

        with session_scope() as session:
            session.execute(update(SmsPin).values(locked_until=datetime.now(timezone.utc) - timedelta(seconds=1)))
        assert patient["dedan"] in text_in(inbound, f"CARD {patient['pin']}")

    def test_amharic_replies_fit_in_three_segments(self, client, bus, inbound, sms, live):
        from dedan_platform import sms_segments

        patient = enrolled_patient(bus, sms, language="am")
        items = [{"test": "Haemoglobin concentration in whole blood", "value": 10.2, "unit": "g/dL",
                  "flag": "low"} for _ in range(3)]
        from_hospital(bus, "record.published", labs(patient["dedan"], items * 2))
        run_worker(bus)
        reply = text_in(inbound, f"ውጤት {patient['pin']}")
        assert reply.startswith(f"{BRAND} የላብራቶሪ ውጤቶች፦") and "ዝቅተኛ" in reply
        assert sms_segments.segments(reply) <= 3
        assert sms_segments.segments(text_in(inbound, "እርዳታ")) <= 3

    def test_unknown_numbers_get_one_generic_reply_a_day(self, client, inbound, sms, live):
        first = text_in(inbound, "CARD 1234", phone="+251944556677")
        assert "not registered" in first
        assert text_in(inbound, "CARD 1234", phone="+251944556677") is None

    def test_rate_limit_and_duplicates(self, client, bus, inbound, sms, live, monkeypatch):
        patient = enrolled_patient(bus, sms, language="en")
        assert text_in(inbound, "HELP", message_id="same") is not None
        assert text_in(inbound, "HELP", message_id="same") is None  # the provider retried its callback
        monkeypatch.setenv("SMS_INBOUND_MAX_PER_PHONE_PER_HOUR", "2")
        assert text_in(inbound, f"CARD {patient['pin']}") is not None
        assert text_in(inbound, f"CARD {patient['pin']}") is None

    def test_every_text_is_audited_without_its_content(self, client, bus, inbound, sms, live):
        from dedan_platform.db import session_scope
        from dedan_platform.models import SmsInboundMessage

        patient = enrolled_patient(bus, sms, language="en")
        text_in(inbound, f"CARD {patient['pin']}")
        text_in(inbound, "CARD 0001")
        with session_scope() as session:
            rows = session.scalars(select(SmsInboundMessage).order_by(SmsInboundMessage.received_at)).all()
            audit = [(r.command, r.outcome, r.user_id, r.phone_masked) for r in rows]
        assert audit == [("CARD", "ok", patient["id"], "+251*******55"),
                         ("CARD", "wrong_pin", patient["id"], "+251*******55")]

    def test_an_app_account_without_a_pin_is_told_how_to_get_one(self, client, inbound, sms, live):
        patient = register(client, phone=NEW_PHONE)
        assert "no SMS PIN yet" in text_in(inbound, "CARD 4821")
        resp = inbound.put("/users/me/sms-pin", headers=patient["auth"], json={"pin": "1111"})
        assert resp.status_code == 422
        resp = inbound.put("/users/me/sms-pin", headers=patient["auth"], json={"pin": "4821"})
        assert resp.status_code == 200 and resp.json() == {"has_pin": True, "locked_until": None,
                                                           "short_code": SHORT, "commands_enabled": True}
        assert patient["dedan"] in text_in(inbound, "CARD 4821")
