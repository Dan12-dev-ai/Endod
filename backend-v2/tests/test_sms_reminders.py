"""Appointment reminders by SMS for patients who signed up by phone."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update


@pytest.fixture
def db(tmp_path, monkeypatch):
    from dedan_platform import db as dbmod

    monkeypatch.setenv("DEDAN_DATABASE_URL", f"sqlite:///{tmp_path / 'sms.db'}")
    dbmod.reset_engine()
    dbmod.create_all()
    yield
    dbmod.reset_engine()


class FakeSms:
    def __init__(self):
        self.sent = []

    def send(self, phone, text):
        self.sent.append((phone, text))
        return "sms-1"


class FakeEmail:
    def __init__(self):
        self.sent = []

    def send(self, to_address, subject, body, correlation_id=None):
        self.sent.append(to_address)
        return None


def _phone_patient():
    from dedan_platform import identity

    return identity.create_user(phone="+251911234567", phone_verified=True)


def _book(uid, hours=48):
    from dedan_platform import appointments, scheduler

    when = datetime.now(timezone.utc) + timedelta(hours=hours)
    appointment = appointments.create_appointment(
        uid, scheduled_at=when, location="Black Lion Hospital", timezone_name="Africa/Addis_Ababa"
    )["appointment"]
    scheduler.schedule_all_channels(uid, appointment["appointment_id"])
    return appointment


def _jobs():
    from dedan_platform.models import Notification
    from dedan_platform.notifications import session_scope

    with session_scope() as session:
        return [
            {"channel": j.channel, "status": j.status, "destination": j.destination, "id": j.id}
            for j in session.scalars(select(Notification))
        ]


def _due_now():
    from dedan_platform.models import Notification
    from dedan_platform.notifications import session_scope

    with session_scope() as session:
        session.execute(update(Notification).values(
            scheduled_for=datetime.now(timezone.utc) - timedelta(seconds=1)))


class TestScheduling:
    def test_phone_signup_turns_sms_reminders_on(self, db):
        from dedan_platform import identity

        user = _phone_patient()
        prefs = identity.get_profile_payload(user["internal_user_id"])["preferences"]
        assert prefs["sms_notifications"] is True

    def test_email_signup_keeps_sms_off(self, db):
        from dedan_platform import identity

        user = identity.create_user(email="a@example.com")
        prefs = identity.get_profile_payload(user["internal_user_id"])["preferences"]
        assert prefs["sms_notifications"] is False

    def test_phone_patient_gets_sms_reminders(self, db):
        user = _phone_patient()
        _book(user["internal_user_id"])
        sms_jobs = [j for j in _jobs() if j["channel"] == "sms" and j["status"] == "PENDING"]
        assert sms_jobs and all(j["destination"] == "+251911234567" for j in sms_jobs)

    def test_unverified_phone_is_never_texted(self, db):
        from dedan_platform import identity

        user = identity.create_user(phone="+251922222222")  # typed, never verified
        identity.update_preferences(user["internal_user_id"], {"sms_notifications": True})
        _book(user["internal_user_id"])
        assert not [j for j in _jobs() if j["channel"] == "sms" and j["status"] == "PENDING"]


class TestDelivery:
    def test_worker_texts_the_reminder(self, db):
        import dedan_platform.worker as wk

        user = _phone_patient()
        _book(user["internal_user_id"])
        _due_now()
        sms = FakeSms()
        wk.run_once(provider=FakeEmail(), sms_provider=sms)
        assert sms.sent
        phone, text = sms.sent[0]
        assert phone == "+251911234567"
        assert "(Africa/Addis_Ababa)" in text and "Black Lion Hospital" in text
        # Reminders whose window had already passed are recorded as SKIPPED.
        assert all(j["status"] == "SENT" for j in _jobs() if j["channel"] == "sms" and j["status"] != "SKIPPED")

    def test_sms_is_delivered_when_email_is_not_configured(self, db, monkeypatch):
        import dedan_platform.worker as wk

        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.delenv("SMTP_HOST", raising=False)
        user = _phone_patient()
        _book(user["internal_user_id"])
        _due_now()
        sms = FakeSms()
        summary = wk.run_once(sms_provider=sms)
        assert sms.sent
        assert summary.get("blocked_channels") == 1

    def test_sms_jobs_wait_when_sms_is_not_configured(self, db, monkeypatch):
        import dedan_platform.worker as wk

        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.delenv("SMSETHIOPIA_API_KEY", raising=False)
        user = _phone_patient()
        _book(user["internal_user_id"])
        _due_now()
        wk.run_once(provider=FakeEmail())
        statuses = {j["status"] for j in _jobs() if j["channel"] == "sms"}
        assert "PENDING" in statuses
        assert not statuses & {"SENT", "PROCESSING", "FAILED"}


class TestReconciliation:
    def test_missing_sms_reminders_are_repaired(self, db):
        from dedan_platform import notifications as nt
        from dedan_platform.models import Notification

        user = _phone_patient()
        _book(user["internal_user_id"])
        with nt.session_scope() as session:
            session.execute(Notification.__table__.delete().where(Notification.channel == "sms"))
        result = nt.reconcile_appointments()
        assert result["repaired"] >= 1
        assert [j for j in _jobs() if j["channel"] == "sms" and j["status"] == "PENDING"]

    def test_opted_out_channel_is_not_repaired_forever(self, db):
        from dedan_platform import notifications as nt

        user = _phone_patient()  # no email: email reminders are recorded as skipped
        _book(user["internal_user_id"])
        first = nt.reconcile_appointments()
        second = nt.reconcile_appointments()
        assert first["repaired"] == 0 and second["repaired"] == 0


def test_sms_text_is_short_and_not_clinical():
    from dedan_platform.sms_provider import render_sms_reminder

    text = render_sms_reminder({
        "scheduled_at": "2026-10-20T06:30:00+00:00",
        "timezone": "Africa/Addis_Ababa",
        "appointment_type": "follow_up",
        "location": "Black Lion Hospital",
    })
    assert len(text) <= 200
    assert "Tuesday 20 October 2026, 09:30" in text
