"""
Appointment reminder lifecycle (spec §2, §12).

These tests exist because the reminders were never actually delivered: the queue,
the retry policy and the idempotency keys were all implemented and all tested,
while `run_once()` had no production caller. The suite below therefore treats
"a due reminder reaches the transport exactly once" as a first-class invariant
rather than an implementation detail.

Time is controlled explicitly. A 24-hour reminder is reached by moving the
scheduled time relative to an injected `now`, never by sleeping.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from dedan_platform.db import ensure_aware


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Isolated database per test. The suite must never touch a developer's
    real `dedan_platform.db`, which `create_app()` would otherwise migrate."""
    from dedan_platform import db as dbmod

    monkeypatch.setenv("DEDAN_DATABASE_URL", f"sqlite:///{tmp_path/'reminders.db'}")
    dbmod.reset_engine()
    dbmod.create_all()
    yield
    dbmod.reset_engine()


@pytest.fixture
def user(db):
    from dedan_platform import identity

    return identity.create_user(display_name="Ada", email="ada@example.org")


class FakeProvider:
    """Records deliveries. Never contacts a patient."""

    def __init__(self, fail_times: int = 0, permanent: bool = False):
        self.sent: list[dict] = []
        self.fail_times = fail_times
        #: Every send raises, so the capped-retry path is exercised to
        #: exhaustion rather than recovering on the second attempt.
        self.permanent = permanent

    def send(self, to_address, subject, body, correlation_id=None):
        from dedan_platform.email_provider import EmailProviderError

        if self.permanent:
            raise EmailProviderError("simulated permanent rejection")
        if self.fail_times > 0:
            self.fail_times -= 1
            raise EmailProviderError("simulated outage")
        self.sent.append({"to": to_address, "subject": subject, "body": body})
        return f"<fake-{len(self.sent)}@test>"


def _book(uid, in_hours=48, **kwargs):
    import dedan_platform.appointments as appt

    scheduled = datetime.now(timezone.utc) + timedelta(hours=in_hours)
    result = appt.create_appointment(uid, scheduled_at=scheduled, **kwargs)
    return result["appointment"], scheduled


# --- scheduling -------------------------------------------------------------


class TestReminderScheduling:
    def test_twenty_four_hour_reminder_is_scheduled(self, db, user):
        from dedan_platform import scheduler

        uid = user["internal_user_id"]
        appt, _ = _book(uid, in_hours=48)
        report = scheduler.schedule_reminders(uid, appt["appointment_id"])
        assert 86400 in report["offsets"]
        assert report["queued"] >= 1

    def test_one_hour_reminder_is_scheduled(self, db, user):
        from dedan_platform import scheduler

        uid = user["internal_user_id"]
        appt, _ = _book(uid, in_hours=48)
        report = scheduler.schedule_reminders(uid, appt["appointment_id"])
        assert 3600 in report["offsets"]

    def test_reminder_times_are_relative_to_the_appointment(self, db, user):
        """Every default offset must fire at exactly appointment - offset, in UTC."""
        from dedan_platform import notifications as nt
        from dedan_platform import scheduler

        uid = user["internal_user_id"]
        # Ten days out, so all three default windows (7d, 24h, 1h) are open.
        appt, scheduled = _book(uid, in_hours=24 * 10)
        scheduler.schedule_reminders(uid, appt["appointment_id"])

        with nt.session_scope() as session:
            from sqlalchemy import select

            from dedan_platform.models import Notification

            fire_times = {
                ensure_aware(job.scheduled_for)
                for job in session.scalars(
                    select(Notification).where(
                        Notification.appointment_id == appt["appointment_id"],
                        Notification.status == "PENDING",
                    )
                )
            }

        # Every open default offset must have a job at exactly that instant.
        for offset in (604800, 86400, 3600):
            assert scheduled - timedelta(seconds=offset) in fire_times

    def test_booking_less_than_24_hours_away_still_queues_the_one_hour_reminder(
        self, db, user
    ):
        """A late booking keeps the reminder that is still open."""
        from dedan_platform import notifications as nt
        from dedan_platform import scheduler

        uid = user["internal_user_id"]
        appt, _ = _book(uid, in_hours=12)
        report = scheduler.schedule_reminders(uid, appt["appointment_id"])

        assert 3600 in report["offsets"]
        assert 86400 not in report["offsets"]
        assert report["queued"] == 1
        # The closed windows (7d and 24h) are recorded, not silently dropped.
        closed = {s["offset_seconds"] for s in report["skipped"]
                  if s["reason"] == "reminder_window_passed"}
        assert closed == {604800, 86400}
        assert nt.queue_stats()["SKIPPED"] == 2

    def test_booking_less_than_one_hour_away_queues_nothing_and_records_it(
        self, db, user
    ):
        from dedan_platform import scheduler

        uid = user["internal_user_id"]
        appt, _ = _book(uid, in_hours=0.5)
        report = scheduler.schedule_reminders(uid, appt["appointment_id"])

        assert report["queued"] == 0
        assert report["offsets"] == []
        assert report["skipped"], "an unqueued reminder must still be explainable"

    def test_duplicate_scheduling_creates_no_second_job(self, db, user):
        from dedan_platform import notifications as nt
        from dedan_platform import scheduler

        uid = user["internal_user_id"]
        appt, _ = _book(uid, in_hours=48)
        first = scheduler.schedule_reminders(uid, appt["appointment_id"])
        second = scheduler.schedule_reminders(uid, appt["appointment_id"])

        assert second["queued"] == 0
        assert nt.queue_stats()["PENDING"] == first["queued"]


# --- lifecycle --------------------------------------------------------------


class TestReminderLifecycle:
    def test_cancelling_the_appointment_suppresses_its_reminders(self, db, user):
        from dedan_platform import appointments as appt
        from dedan_platform import notifications as nt
        from dedan_platform import scheduler

        uid = user["internal_user_id"]
        appt_row, _ = _book(uid, in_hours=48)
        scheduler.schedule_reminders(uid, appt_row["appointment_id"])
        assert nt.queue_stats()["PENDING"] > 0

        payload = appt.update_status(uid, appt_row["appointment_id"], "CANCELLED")

        assert payload["reminders_cancelled"] > 0
        assert nt.queue_stats()["PENDING"] == 0

    def test_completion_suppresses_future_reminders(self, db, user):
        """Telling a patient to prepare for a consultation already over."""
        from dedan_platform import appointments as appt
        from dedan_platform import notifications as nt
        from dedan_platform import scheduler

        uid = user["internal_user_id"]
        appt_row, _ = _book(uid, in_hours=48)
        scheduler.schedule_reminders(uid, appt_row["appointment_id"])
        appt.update_status(uid, appt_row["appointment_id"], "CONFIRMED")
        appt.update_status(uid, appt_row["appointment_id"], "COMPLETED")

        assert nt.queue_stats()["PENDING"] == 0

    def test_missed_appointment_suppresses_reminders(self, db, user):
        from dedan_platform import appointments as appt
        from dedan_platform import notifications as nt
        from dedan_platform import scheduler

        uid = user["internal_user_id"]
        appt_row, _ = _book(uid, in_hours=48)
        scheduler.schedule_reminders(uid, appt_row["appointment_id"])
        appt.update_status(uid, appt_row["appointment_id"], "MISSED")

        assert nt.queue_stats()["PENDING"] == 0

    def test_rescheduling_replaces_the_old_reminders(self, db, user):
        """The defect this fixes: reschedule cancelled, then armed nothing."""
        from dedan_platform import notifications as nt
        from dedan_platform import scheduler

        uid = user["internal_user_id"]
        appt_row, _ = _book(uid, in_hours=48)
        scheduler.schedule_reminders(uid, appt_row["appointment_id"])
        before = nt.count_open_for_appointment(appt_row["appointment_id"])
        assert before > 0

        moved = datetime.now(timezone.utc) + timedelta(days=5)
        scheduler.reschedule_reminders(uid, appt_row["appointment_id"])
        import dedan_platform.appointments as appt

        appt.reschedule(uid, appt_row["appointment_id"], moved)
        report = scheduler.reschedule_reminders(uid, appt_row["appointment_id"])

        assert report["queued"] > 0, "a rescheduled appointment must re-arm"
        assert nt.count_open_for_appointment(appt_row["appointment_id"]) == report["queued"]

    def test_stale_reminder_does_not_fire_after_a_reschedule(self, db, user, monkeypatch):
        """The old time's job must be CANCELLED, so the worker never claims it."""
        import dedan_platform.appointments as appt
        import dedan_platform.notifications as nt
        import dedan_platform.worker as wk
        from dedan_platform import scheduler
        from sqlalchemy import update

        uid = user["internal_user_id"]
        appt_row, _ = _book(uid, in_hours=2)
        scheduler.schedule_reminders(uid, appt_row["appointment_id"])

        appt.reschedule(uid, appt_row["appointment_id"],
                        datetime.now(timezone.utc) + timedelta(days=7))

        # Make every cancelled job look due; the worker must still skip them.
        with nt.session_scope() as session:
            session.execute(update(nt.Notification).values(
                scheduled_for=datetime.now(timezone.utc) - timedelta(hours=2)))

        provider = FakeProvider()
        wk.run_once(provider=provider)

        assert provider.sent == [], "a superseded reminder was delivered"

    def test_no_reminder_is_queued_for_a_terminal_appointment(self, db, user):
        from dedan_platform import appointments as appt
        from dedan_platform import scheduler

        uid = user["internal_user_id"]
        appt_row, _ = _book(uid, in_hours=48)
        appt.update_status(uid, appt_row["appointment_id"], "CANCELLED")
        report = scheduler.schedule_reminders(uid, appt_row["appointment_id"])
        assert report["queued"] == 0


# --- delivery ---------------------------------------------------------------


class TestDelivery:
    def _due_now(self, db):
        """Force every pending job to be due, without touching its offsets."""
        from sqlalchemy import update

        import dedan_platform.notifications as nt
        from dedan_platform.models import Notification

        with nt.session_scope() as session:
            session.execute(update(Notification).values(
                scheduled_for=datetime.now(timezone.utc) - timedelta(seconds=1)))

    def test_worker_delivers_a_due_reminder_exactly_once(self, db, user):
        import dedan_platform.worker as wk
        from dedan_platform import scheduler

        uid = user["internal_user_id"]
        appt_row, _ = _book(uid, in_hours=48)
        scheduler.schedule_reminders(uid, appt_row["appointment_id"])
        self._due_now(db)

        provider = FakeProvider()
        first = wk.run_once(provider=provider)
        assert first["SENT"] > 0
        delivered = len(provider.sent)

        # A second pass must find nothing left to send.
        wk.run_once(provider=provider)
        assert len(provider.sent) == delivered

    def test_transient_failure_is_retried(self, db, user):
        import dedan_platform.notifications as nt
        import dedan_platform.worker as wk
        from dedan_platform import scheduler

        uid = user["internal_user_id"]
        appt_row, _ = _book(uid, in_hours=48)
        scheduler.schedule_reminders(uid, appt_row["appointment_id"])
        self._due_now(db)

        provider = FakeProvider(fail_times=1)
        summary = wk.run_once(provider=provider)
        assert summary["RETRYING"] == 1
        # Exactly one job failed; the rest of the batch still delivered.
        assert len(provider.sent) == summary["SENT"]
        assert nt.queue_stats()["RETRYING"] == 1

        # Next pass succeeds once the backoff window is open.
        self._due_now(db)
        summary2 = wk.run_once(provider=provider)
        assert summary2["SENT"] == 1

    def test_permanent_failure_stops_after_max_attempts(self, db, user, monkeypatch):
        import dedan_platform.notifications as nt
        import dedan_platform.worker as wk
        from dedan_platform import scheduler

        monkeypatch.setattr(nt, "MAX_ATTEMPTS", 2)
        monkeypatch.setattr(nt, "BASE_BACKOFF_SECONDS", 0)

        uid = user["internal_user_id"]
        appt_row, _ = _book(uid, in_hours=48)
        scheduler.schedule_reminders(uid, appt_row["appointment_id"])

        provider = FakeProvider(permanent=True)
        for _ in range(6):
            self._due_now(db)
            wk.run_once(provider=provider)

        assert nt.queue_stats()["FAILED"] >= 1
        assert provider.sent == [], "a permanently rejected message must never succeed"

    def test_a_crashed_worker_does_not_swallow_the_reminder(self, db, user):
        """A job stuck in PROCESSING must be recovered, not abandoned."""
        import dedan_platform.notifications as nt
        import dedan_platform.worker as wk
        from dedan_platform import scheduler
        from sqlalchemy import update

        monkey = None
        uid = user["internal_user_id"]
        appt_row, _ = _book(uid, in_hours=48)
        scheduler.schedule_reminders(uid, appt_row["appointment_id"])

        original = nt.STALE_PROCESSING_SECONDS
        try:
            nt.STALE_PROCESSING_SECONDS = 0
            with nt.session_scope() as session:
                session.execute(update(nt.Notification).values(status="PROCESSING"))
            assert nt.queue_stats()["PROCESSING"] > 0

            provider = FakeProvider()
            wk.run_once(provider=provider)
            assert provider.sent, "an orphaned job was never retried"
        finally:
            nt.STALE_PROCESSING_SECONDS = original

    def test_concurrent_workers_deliver_one_copy(self, db, user, monkeypatch):
        """Two workers must not both take the same job.

        The claim is a conditional UPDATE, so the loser of the race gets zero
        rows. This test runs two passes over one queue and asserts that the
        number of deliveries equals the number of jobs, not double it.
        """
        import dedan_platform.notifications as nt
        import dedan_platform.worker as wk
        from dedan_platform import scheduler

        uid = user["internal_user_id"]
        appt_row, _ = _book(uid, in_hours=48)
        report = scheduler.schedule_reminders(uid, appt_row["appointment_id"])
        queued = report["queued"]
        self._due_now(db)

        provider_a = FakeProvider()
        provider_b = FakeProvider()
        wk.run_once(provider=provider_a)
        wk.run_once(provider=provider_b)

        assert len(provider_a.sent) + len(provider_b.sent) == queued

    def test_delivery_records_the_provider_receipt(self, db, user):
        from dedan_platform import notifications as nt
        import dedan_platform.worker as wk
        from dedan_platform import scheduler
        from sqlalchemy import select

        from dedan_platform.models import Notification

        uid = user["internal_user_id"]
        appt_row, _ = _book(uid, in_hours=48)
        scheduler.schedule_reminders(uid, appt_row["appointment_id"])
        self._due_now(db)
        wk.run_once(provider=FakeProvider())

        with nt.session_scope() as session:
            job = session.scalar(
                select(Notification).where(
                    Notification.appointment_id == appt_row["appointment_id"],
                    Notification.status == "SENT",
                )
            )
            assert job.sent_at is not None
            assert job.provider_message_id


# --- preferences and consent ------------------------------------------------


class TestConsentAndPreferences:
    def test_opted_out_channel_records_a_skip_and_sends_nothing(self, db, user):
        import dedan_platform.identity as identity
        import dedan_platform.notifications as nt
        import dedan_platform.worker as wk
        from dedan_platform import scheduler

        uid = user["internal_user_id"]
        identity.update_preferences(uid, {"email_notifications": False})

        appt_row, _ = _book(uid, in_hours=48)
        report = scheduler.schedule_reminders(uid, appt_row["appointment_id"])

        assert report["queued"] == 0
        assert nt.queue_stats()["SKIPPED"] > 0

        provider = FakeProvider()
        wk.run_once(provider=provider)
        assert provider.sent == []

    def test_user_reminder_offsets_are_honoured(self, db, user):
        """The preference was editable in the portal and read by nothing."""
        import dedan_platform.identity as identity
        from dedan_platform import scheduler

        uid = user["internal_user_id"]
        identity.update_preferences(uid, {"reminder_offsets": "7200"})

        appt_row, _ = _book(uid, in_hours=48)
        report = scheduler.schedule_reminders(uid, appt_row["appointment_id"])

        assert report["offsets"] == [7200]

    def test_per_appointment_offsets_override_the_preference(self, db, user):
        import dedan_platform.identity as identity
        from dedan_platform import scheduler

        uid = user["internal_user_id"]
        identity.update_preferences(uid, {"reminder_offsets": "7200"})
        appt_row, _ = _book(uid, in_hours=48, reminder_offsets="3600")

        report = scheduler.schedule_reminders(uid, appt_row["appointment_id"])
        assert report["offsets"] == [3600]

    def test_no_destination_records_a_skip(self, db):
        from dedan_platform import identity
        import dedan_platform.notifications as nt
        from dedan_platform import scheduler

        user_without_email = identity.create_user(display_name="NoEmail")
        uid = user_without_email["internal_user_id"]
        appt_row, _ = _book(uid, in_hours=48)
        report = scheduler.schedule_reminders(uid, appt_row["appointment_id"])

        assert report["queued"] == 0
        assert nt.queue_stats()["SKIPPED"] > 0


# --- timezone ---------------------------------------------------------------


class TestTimezoneHandling:
    def test_naive_scheduled_time_is_refused(self, db, user):
        import dedan_platform.appointments as appt

        with pytest.raises(appt.AppointmentError):
            appt.create_appointment(
                user["internal_user_id"], scheduled_at=datetime(2030, 1, 1, 10, 0)
            )

    def test_reminder_instants_are_identical_across_equivalent_offsets(self, db, user):
        """09:00+03:00 and 06:00Z are the same instant and must schedule alike."""
        import dedan_platform.notifications as nt
        from dedan_platform import scheduler
        from sqlalchemy import select

        from dedan_platform.models import Notification

        uid = user["internal_user_id"]
        addis = datetime(2031, 3, 1, 9, 0, tzinfo=timezone(timedelta(hours=3)))
        result = appt_create(uid, addis)["appointment"]
        scheduler.schedule_reminders(uid, result["appointment_id"])

        with nt.session_scope() as session:
            fire_times = {
                ensure_aware(job.scheduled_for)
                for job in session.scalars(
                    select(Notification).where(
                        Notification.appointment_id == result["appointment_id"]
                    )
                )
            }

        # The instant is authoritative: 09:00+03:00 is 06:00Z, and the 24-hour
        # reminder sits exactly 24 hours before it. A naive-datetime bug here
        # would silently shift every reminder by the local UTC offset.
        assert addis.astimezone(timezone.utc) == datetime(2031, 3, 1, 6, 0, tzinfo=timezone.utc)
        assert addis - timedelta(hours=24) in fire_times

    def test_stored_appointment_timezone_is_preserved(self, db, user):
        import dedan_platform.appointments as appt

        uid = user["internal_user_id"]
        scheduled = datetime.now(timezone.utc) + timedelta(days=10)
        result = appt.create_appointment(
            uid, scheduled_at=scheduled, timezone_name="Africa/Addis_Ababa"
        )
        assert result["appointment"]["timezone"] == "Africa/Addis_Ababa"
        assert appt.get_appointment(uid, result["appointment"]["appointment_id"])[
            "timezone"
        ] == "Africa/Addis_Ababa"


def appt_create(uid, scheduled_at):
    import dedan_platform.appointments as appt

    return appt.create_appointment(
        uid, scheduled_at=scheduled_at, timezone_name="Africa/Addis_Ababa"
    )


# --- reconciliation ---------------------------------------------------------


class TestReconciliation:
    def test_missing_reminders_are_repaired(self, db, user):
        """An appointment whose reminders were lost gets them back."""
        from dedan_platform import notifications as nt
        from dedan_platform import scheduler

        uid = user["internal_user_id"]
        appt_row, _ = _book(uid, in_hours=72)
        scheduler.schedule_reminders(uid, appt_row["appointment_id"])
        queued = nt.queue_stats()["PENDING"]
        assert queued > 0

        # Simulate the enqueue having silently failed at booking time.
        from sqlalchemy import update

        with nt.session_scope() as session:
            session.execute(update(nt.Notification).values(status="CANCELLED"))
        assert nt.count_open_for_appointment(appt_row["appointment_id"]) == 0

        result = nt.reconcile_appointments()
        assert result["repaired"] > 0
        assert nt.count_open_for_appointment(appt_row["appointment_id"]) == result["repaired"]

    def test_reconciliation_is_idempotent(self, db, user):
        from dedan_platform import notifications as nt
        from dedan_platform import scheduler

        uid = user["internal_user_id"]
        appt_row, _ = _book(uid, in_hours=72)
        scheduler.schedule_reminders(uid, appt_row["appointment_id"])
        before = nt.count_open_for_appointment(appt_row["appointment_id"])

        nt.reconcile_appointments()
        nt.reconcile_appointments()

        assert nt.count_open_for_appointment(appt_row["appointment_id"]) == before

    def test_orphan_reminders_for_a_cancelled_appointment_are_cleared(self, db, user):
        import dedan_platform.notifications as nt
        from sqlalchemy import update

        from dedan_platform.models import Notification

        uid = user["internal_user_id"]
        appt_row, _ = _book(uid, in_hours=72)
        from dedan_platform import scheduler

        scheduler.schedule_reminders(uid, appt_row["appointment_id"])
        with nt.session_scope() as session:
            # Put the appointment back to SCHEDULED while its reminders are
            # still PENDING: the exact shape a race between cancel and enqueue
            # leaves behind.
            session.execute(update(Notification).values(status="PENDING"))
            from dedan_platform.models import Appointment

            session.execute(
                update(Appointment).where(
                    Appointment.id == appt_row["appointment_id"]
                ).values(status="CANCELLED"))

        result = nt.reconcile_appointments()
        assert result["cancelled"] > 0
        assert nt.count_open_for_appointment(appt_row["appointment_id"]) == 0