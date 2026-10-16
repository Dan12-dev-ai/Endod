"""Reminder delivery fixes from the backend review."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from test_reminders import FakeProvider, _book


@pytest.fixture
def db(tmp_path, monkeypatch):
    from dedan_platform import db as dbmod

    monkeypatch.setenv("DEDAN_DATABASE_URL", f"sqlite:///{tmp_path / 'delivery.db'}")
    dbmod.reset_engine()
    dbmod.create_all()
    yield
    dbmod.reset_engine()


@pytest.fixture
def user(db):
    from dedan_platform import identity

    return identity.create_user(display_name="Ada", email="ada@example.org")


def _due_now():
    from dedan_platform.models import Notification
    from dedan_platform.notifications import session_scope

    with session_scope() as session:
        session.execute(update(Notification).values(
            scheduled_for=datetime.now(timezone.utc) - timedelta(seconds=1)))


def _jobs():
    from dedan_platform.models import Notification
    from dedan_platform.notifications import session_scope

    with session_scope() as session:
        return [
            {"id": j.id, "status": j.status, "attempts": j.attempts, "error": j.last_error}
            for j in session.scalars(select(Notification))
        ]


def _queue_one(uid):
    from dedan_platform import scheduler

    appointment, _ = _book(uid, in_hours=48)
    scheduler.schedule_reminders(uid, appointment["appointment_id"])
    return appointment


class TestAttempts:
    def test_a_job_gets_every_allowed_attempt(self, user, monkeypatch):
        import dedan_platform.notifications as nt
        import dedan_platform.worker as wk

        monkeypatch.setattr(nt, "MAX_ATTEMPTS", 5)
        monkeypatch.setattr(nt, "BASE_BACKOFF_SECONDS", 0)
        _queue_one(user["internal_user_id"])
        # Keep one pending job so the count is exact.
        kept = next(j for j in _jobs() if j["status"] == "PENDING")
        with nt.session_scope() as session:
            from dedan_platform.models import Notification
            session.execute(update(Notification).where(Notification.id != kept["id"]).values(
                status=nt.NotificationStatus.CANCELLED))

        tries = 0

        class CountingFailure(FakeProvider):
            def send(self, *args, **kwargs):
                nonlocal tries
                tries += 1
                return super().send(*args, **kwargs)

        provider = CountingFailure(permanent=True)
        for _ in range(10):
            _due_now()
            wk.run_once(provider=provider)
        job = next(j for j in _jobs() if j["id"] == kept["id"])
        # Previously each failure counted twice: FAILED after 3 tries.
        assert tries == 5
        assert job["status"] == "FAILED" and job["attempts"] == 5

    def test_a_job_stuck_in_processing_eventually_fails(self, user, monkeypatch):
        import dedan_platform.notifications as nt

        monkeypatch.setattr(nt, "MAX_ATTEMPTS", 3)
        monkeypatch.setattr(nt, "STALE_PROCESSING_SECONDS", 0)
        _queue_one(user["internal_user_id"])
        for _ in range(3):
            with nt.session_scope() as session:
                from dedan_platform.models import Notification
                session.execute(update(Notification).values(status=nt.NotificationStatus.PROCESSING))
            nt.recover_stale_jobs(now=datetime.now(timezone.utc) + timedelta(seconds=1))
        assert all(j["status"] == "FAILED" for j in _jobs())
        assert all(j["error"] == "stuck in processing" for j in _jobs())


class TestNoDuplicates:
    def test_jobs_are_claimed_one_at_a_time(self, user):
        import dedan_platform.worker as wk
        from dedan_platform.models import Notification, NotificationStatus
        from dedan_platform.notifications import session_scope

        _queue_one(user["internal_user_id"])
        _due_now()
        processing_during_send = []

        class Watching(FakeProvider):
            def send(self, *args, **kwargs):
                with session_scope() as session:
                    processing_during_send.append(len(list(session.scalars(
                        select(Notification).where(Notification.status == NotificationStatus.PROCESSING)
                    ))))
                return super().send(*args, **kwargs)

        summary = wk.run_once(provider=Watching())
        assert summary["SENT"] >= 2
        # Only the job being sent is ever in PROCESSING.
        assert set(processing_during_send) == {1}

    def test_stop_flag_is_honoured_between_jobs(self, user):
        import dedan_platform.worker as wk

        _queue_one(user["internal_user_id"])
        _due_now()
        provider = FakeProvider()
        summary = wk.run_once(provider=provider, should_stop=lambda: len(provider.sent) >= 1)
        assert summary["claimed"] == 1
        assert not any(j["status"] == "PROCESSING" for j in _jobs())


class TestNoFakeDelivery:
    def test_production_without_smtp_leaves_reminders_queued(self, user, monkeypatch):
        import dedan_platform.worker as wk

        monkeypatch.delenv("SMTP_HOST", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "production")
        _queue_one(user["internal_user_id"])
        _due_now()
        summary = wk.run_once()
        assert summary["blocked"] == 1 and summary["SENT"] == 0
        assert not any(j["status"] in ("SENT", "PROCESSING") for j in _jobs())

    def test_non_email_job_is_never_given_to_the_email_provider(self, user):
        import dedan_platform.notifications as nt
        import dedan_platform.worker as wk
        from dedan_platform.models import Notification, NotificationChannel

        _queue_one(user["internal_user_id"])
        with nt.session_scope() as session:
            session.execute(update(Notification).values(
                channel=NotificationChannel.SMS, destination="+251911234567"))
        _due_now()
        provider = FakeProvider()
        wk.run_once(provider=provider)
        assert provider.sent == []
        assert all(j["status"] == "SKIPPED" for j in _jobs())


class TestReminderContent:
    PAYLOAD = {
        "scheduled_at": "2026-10-20T06:30:00+00:00",
        "timezone": "Africa/Addis_Ababa",
        "appointment_type": "follow_up",
        "location": "Black Lion Hospital",
    }

    def test_shows_the_appointment_time_in_its_timezone(self, monkeypatch):
        from dedan_platform.email_provider import render_appointment_reminder

        body = render_appointment_reminder(self.PAYLOAD, "u", "a")["body"]
        assert "Tuesday 20 October 2026, 09:30 (Africa/Addis_Ababa)" in body
        assert "your scheduled time" not in body

    def test_no_localhost_link_by_default(self, monkeypatch):
        from dedan_platform.email_provider import render_appointment_reminder

        monkeypatch.delenv("PUBLIC_WEB_URL", raising=False)
        body = render_appointment_reminder(self.PAYLOAD, "u", "a")["body"]
        assert "localhost" not in body and "http" not in body

    def test_link_points_at_the_configured_portal(self, monkeypatch):
        from dedan_platform.email_provider import render_appointment_reminder

        monkeypatch.setenv("PUBLIC_WEB_URL", "https://app.example.org/")
        body = render_appointment_reminder(self.PAYLOAD, "user-123", "appt-9")["body"]
        assert "https://app.example.org/interview" in body
        assert "user-123" not in body  # no internal ids in links


class TestReviewFindings:
    """Automated review (Qodo) of PR #5."""

    def test_failure_never_overwrites_a_recorded_send(self, user):
        import dedan_platform.notifications as nt
        from dedan_platform.models import Notification

        _queue_one(user["internal_user_id"])
        job_id = _jobs()[0]["id"]
        with nt.session_scope() as session:
            session.execute(update(Notification).where(Notification.id == job_id).values(
                status=nt.NotificationStatus.SENT))
        nt.mark_failed(job_id, "late failure", 5)
        assert next(j for j in _jobs() if j["id"] == job_id)["status"] == "SENT"

    def test_stale_threshold_outlasts_a_send(self):
        import dedan_platform.email_provider as ep
        import dedan_platform.notifications as nt

        assert nt.STALE_PROCESSING_SECONDS > 4 * ep.SMTP_TIMEOUT_SECONDS

    def test_claim_takes_exactly_the_requested_number(self, user):
        import dedan_platform.notifications as nt

        _queue_one(user["internal_user_id"])
        _due_now()
        assert len(nt.claim_due_jobs(limit=1)) == 1

    def test_production_set_only_in_settings_is_honoured(self, monkeypatch):
        from app.core.config import get_settings
        from dedan_platform import email_provider, sms_provider

        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("SMTP_HOST", raising=False)
        monkeypatch.delenv("SMSETHIOPIA_API_KEY", raising=False)
        monkeypatch.setattr(get_settings(), "ENVIRONMENT", "production")
        with pytest.raises(email_provider.EmailNotConfiguredError):
            email_provider.build_provider()
        with pytest.raises(sms_provider.SmsNotConfiguredError):
            sms_provider.build_provider()

    def test_one_shot_worker_exits_non_zero_when_blocked(self, db, monkeypatch, capsys):
        from dedan_platform import worker_main

        monkeypatch.delenv("SMTP_HOST", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "production")
        assert worker_main.main(["--once"]) == 2

    def test_reconcile_cancels_open_reminders_of_cancelled_appointments(self, user):
        import dedan_platform.notifications as nt
        from dedan_platform.models import Appointment, EventStatus

        appointment = _queue_one(user["internal_user_id"])
        with nt.session_scope() as session:
            session.execute(update(Appointment).where(Appointment.id == appointment["appointment_id"]).values(
                status=EventStatus.CANCELLED))
        result = nt.reconcile_appointments()
        assert result["cancelled"] >= 1
        assert not any(j["status"] in ("PENDING", "RETRYING") for j in _jobs())
