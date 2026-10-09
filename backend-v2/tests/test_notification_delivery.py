"""
Worker execution, notification API, and schema migration (spec §12).

Three separate concerns, grouped because each covers a way this subsystem could
regress silently:

* **Worker execution.** The queue, retry policy and idempotency keys were all
  implemented and all tested while `run_once()` had no production caller -- 52
  reminders sat PENDING and 0 were ever sent. A test that only calls `run_once`
  would have passed in exactly that situation. These tests drive the loop.
* **Notification API.** Ownership cannot be requested away.
* **Migrations.** `create_all()` cannot add a column, so new columns are only
  present on a legacy database if the migration actually runs.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    from dedan_platform import db as dbmod

    monkeypatch.setenv("DEDAN_DATABASE_URL", f"sqlite:///{tmp_path/'worker.db'}")
    dbmod.reset_engine()
    dbmod.create_all()
    yield
    dbmod.reset_engine()


@pytest.fixture
def user(db):
    from dedan_platform import identity

    return identity.create_user(display_name="Ada", email="ada@example.org")


class FakeProvider:
    def __init__(self, fail_times: int = 0):
        self.sent: list[dict] = []
        self.fail_times = fail_times

    def send(self, to_address, subject, body, correlation_id=None):
        if self.fail_times > 0:
            self.fail_times -= 1
            from dedan_platform.email_provider import EmailProviderError

            raise EmailProviderError("simulated outage")
        self.sent.append({"to": to_address})
        return None


def _due(db):
    from sqlalchemy import update

    from dedan_platform import notifications as nt
    from dedan_platform.models import Notification

    with nt.session_scope() as session:
        session.execute(update(Notification).where(
            Notification.status.in_(["PENDING", "RETRYING"])
        ).values(scheduled_for=datetime.now(timezone.utc) - timedelta(seconds=1)))


# --- worker loop ------------------------------------------------------------


class TestWorkerLoop:
    def test_loop_delivers_due_jobs_without_being_asked(self, db, user):
        """The regression this whole change exists for.

        `run_once()` had no production caller, so no reminder was ever
        delivered. This drives `worker_loop` itself and asserts a queued
        reminder reaches the transport.
        """
        import dedan_platform.notifications as nt
        import dedan_platform.worker as wk
        from dedan_platform import appointments as appt
        from dedan_platform import scheduler

        uid = user["internal_user_id"]
        result = appt.create_appointment(
            uid, scheduled_at=datetime.now(timezone.utc) + timedelta(hours=72)
        )
        scheduler.schedule_reminders(uid, result["appointment"]["appointment_id"])
        assert nt.queue_stats()["PENDING"] > 0
        _due(db)

        provider = FakeProvider()
        stop = asyncio.Event()
        original_interval = wk.WORKER_POLL_INTERVAL
        original_reconcile = wk.WORKER_RECONCILE_ON_START
        wk.WORKER_POLL_INTERVAL = 0.01
        wk.WORKER_RECONCILE_ON_START = False

        async def stop_after_first_pass():
            # Let exactly one pass run, then ask the loop to stop.
            await asyncio.sleep(0.05)
            stop.set()

        async def drive():
            await asyncio.gather(
                wk.worker_loop(stop, provider=provider), stop_after_first_pass()
            )

        try:
            asyncio.run(drive())
        finally:
            wk.WORKER_POLL_INTERVAL = original_interval
            wk.WORKER_RECONCILE_ON_START = original_reconcile

        assert provider.sent, "the worker loop delivered nothing"
        assert nt.queue_stats()["SENT"] == len(provider.sent)

    def test_loop_stops_promptly_when_asked(self, db, user, monkeypatch):
        """Shutdown must not wait out the poll interval."""
        import dedan_platform.worker as wk

        monkeypatch.setattr(wk, "WORKER_POLL_INTERVAL", 30.0)
        monkeypatch.setattr(wk, "WORKER_RECONCILE_ON_START", False)

        stop = asyncio.Event()
        stop.set()  # already stopped: the loop must exit without polling

        async def drive():
            await asyncio.wait_for(wk.worker_loop(stop, provider=FakeProvider()), timeout=5)

        asyncio.run(drive())  # returning at all is the assertion

    def test_worker_is_disabled_by_default(self):
        """Starting a mail loop must be an explicit operational decision."""
        import importlib

        import dedan_platform.worker as wk

        importlib.reload(wk)
        assert wk.WORKER_ENABLED is False, "the worker must not auto-start"

    def test_queue_metrics_report_depth_and_age(self, db, user):
        import dedan_platform.notifications as nt
        import dedan_platform.worker as wk
        from dedan_platform import appointments as appt
        from dedan_platform import scheduler

        uid = user["internal_user_id"]
        result = appt.create_appointment(
            uid, scheduled_at=datetime.now(timezone.utc) + timedelta(hours=72)
        )
        scheduler.schedule_reminders(uid, result["appointment"]["appointment_id"])

        depth = wk.queue_metrics()
        assert depth["pending"] > 0
        assert depth["oldest_pending_seconds"] is not None


# --- end-to-end -------------------------------------------------------------


class TestEndToEndLifecycle:
    def test_full_booking_to_delivery_lifecycle(self, db, user):
        """The §12 scenario, end to end, with a controllable clock.

        Booking -> both reminders scheduled -> delivered once each ->
        rescheduled so the old reminders are suppressed -> completed so no
        future reminder fires.
        """
        import dedan_platform.appointments as appt
        import dedan_platform.notifications as nt
        import dedan_platform.worker as wk
        from dedan_platform import scheduler

        uid = user["internal_user_id"]
        provider = FakeProvider()

        # 1-3. Book and confirm both reminders are scheduled.
        scheduled = datetime.now(timezone.utc) + timedelta(hours=48)
        created = appt.create_appointment(
            uid, scheduled_at=scheduled, timezone_name="Africa/Addis_Ababa"
        )["appointment"]
        appointment_id = created["appointment_id"]

        report = scheduler.schedule_reminders(uid, appointment_id)
        assert set(report["offsets"]) == {86400, 3600}
        assert nt.queue_stats()["PENDING"] == 2

        # 4-5. Advance to the 24-hour reminder: exactly one notification.
        from sqlalchemy import update

        from dedan_platform.models import Notification

        with nt.session_scope() as session:
            session.execute(update(Notification).where(
                Notification.appointment_id == appointment_id,
                Notification.scheduled_for == scheduled - timedelta(hours=24),
            ).values(scheduled_for=datetime.now(timezone.utc) - timedelta(seconds=1)))

        wk.run_once(provider=provider)
        assert len(provider.sent) == 1
        assert nt.queue_stats()["SENT"] == 1
        assert nt.queue_stats()["PENDING"] == 1

        # 6-7. Advance to the 1-hour reminder: the second, and no more.
        _due(db)
        wk.run_once(provider=provider)
        assert len(provider.sent) == 2
        assert nt.queue_stats()["SENT"] == 2

        # Re-running produces nothing further.
        wk.run_once(provider=provider)
        assert len(provider.sent) == 2

        # 8. Reschedule: old reminders suppressed, new ones armed.
        moved = datetime.now(timezone.utc) + timedelta(days=6)
        appt.reschedule(uid, appointment_id, moved)
        rearmed = scheduler.reschedule_reminders(uid, appointment_id)
        assert rearmed["queued"] == 2
        assert nt.count_open_for_appointment(appointment_id) == 2

        # 9. Completion stops everything.
        appt.update_status(uid, appointment_id, "CONFIRMED")
        appt.update_status(uid, appointment_id, "COMPLETED")
        assert nt.count_open_for_appointment(appointment_id) == 0

        before = len(provider.sent)
        _due(db)
        wk.run_once(provider=provider)
        assert len(provider.sent) == before, "a completed appointment sent a reminder"


# --- API --------------------------------------------------------------------


class TestNotificationAPI:
    @pytest.fixture
    def api(self, db, user, monkeypatch):
        monkeypatch.setenv("REALTIME_TOKEN_SECRET", "test-secret")
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from dedan_platform.api_health import router as health_router
        from dedan_platform.api_notifications import router as notifications_router
        from realtime.auth import issue_token

        app = FastAPI()
        app.include_router(health_router)
        app.include_router(notifications_router)
        client = TestClient(app)

        class Harness:
            def __init__(self):
                self.client = client
                self.token = issue_token(user["dedan_user_id"])

            @property
            def headers(self):
                return {"Authorization": self.token}

        return Harness()

    def test_requires_authentication(self, api):
        assert api.client.get("/users/me/notifications").status_code in (401, 403)

    def test_returns_only_the_callers_notifications(self, api, db, user):
        import dedan_platform.identity as identity
        import dedan_platform.notifications as nt
        from dedan_platform import appointments as appt
        from dedan_platform import scheduler

        mine = user["internal_user_id"]
        result = appt.create_appointment(
            mine, scheduled_at=datetime.now(timezone.utc) + timedelta(hours=72)
        )
        scheduler.schedule_reminders(mine, result["appointment"]["appointment_id"])

        other = identity.create_user(display_name="Other", email="other@example.org")
        other_appt = appt.create_appointment(
            other["internal_user_id"],
            scheduled_at=datetime.now(timezone.utc) + timedelta(hours=72),
        )
        scheduler.schedule_reminders(
            other["internal_user_id"], other_appt["appointment"]["appointment_id"]
        )

        body = api.client.get("/users/me/notifications", headers=api.headers).json()
        mine_rows = [
            n for n in body["notifications"]
            if n["appointment_id"] and n["status"] == "PENDING"
        ]
        assert len(mine_rows) == 2
        assert {n["appointment_id"] for n in mine_rows} == {
            result["appointment"]["appointment_id"]
        }
        # The other patient's rows are absent entirely, not merely filtered out
        # of this page.
        assert all(
            n["appointment_id"] != other_appt["appointment"]["appointment_id"]
            for n in body["notifications"]
        )

    def test_does_not_leak_the_destination_address(self, api, db, user):
        """The queue's internals must not become a patient-readable export."""
        from dedan_platform import appointments as appt
        from dedan_platform import scheduler

        uid = user["internal_user_id"]
        result = appt.create_appointment(
            uid, scheduled_at=datetime.now(timezone.utc) + timedelta(hours=72)
        )
        scheduler.schedule_reminders(uid, result["appointment"]["appointment_id"])

        body = api.client.get("/users/me/notifications", headers=api.headers).json()
        raw = repr(body)
        assert "ada@example.org" not in raw
        assert "payload_json" not in raw
        assert "last_error" not in raw

    def test_another_patients_notification_is_a_404(self, api, db, user):
        """Not 403: existence must not be confirmable across owners."""
        import dedan_platform.identity as identity
        from dedan_platform import appointments as appt
        from dedan_platform import scheduler
        from dedan_platform.models import Notification
        from sqlalchemy import select

        # Build a notification belonging to a different patient.
        victim = identity.create_user(display_name="Victim", email="victim@example.org")
        victim_appt = appt.create_appointment(
            victim["internal_user_id"],
            scheduled_at=datetime.now(timezone.utc) + timedelta(hours=72),
        )
        scheduler.schedule_reminders(
            victim["internal_user_id"], victim_appt["appointment"]["appointment_id"]
        )

        with nt_session() as session:
            victim_job = session.scalar(
                select(Notification).where(
                    Notification.user_id == victim["internal_user_id"]
                )
            )

        response = api.client.get(
            f"/users/me/notifications/{victim_job}", headers=api.headers
        )
        assert response.status_code == 404

    def test_rejects_an_unknown_status_filter(self, api):
        response = api.client.get(
            "/users/me/notifications?status=BOGUS", headers=api.headers
        )
        assert response.status_code == 400


def nt_session():
    from dedan_platform.db import session_scope

    return session_scope()


# --- migrations -------------------------------------------------------------


class TestMigrations:
    def test_new_columns_are_added_to_a_legacy_database(self, tmp_path, monkeypatch):
        """`create_all` cannot ALTER, so the migration must."""
        import sqlite3

        from dedan_platform import db as dbmod
        from dedan_platform import migrations

        path = tmp_path / "legacy.db"

        # A pre-migration schema: the table without the newer columns.
        legacy = sqlite3.connect(path)
        legacy.execute(
            "CREATE TABLE notifications ("
            "id VARCHAR(32) PRIMARY KEY, user_id VARCHAR(32) NOT NULL, "
            "channel VARCHAR(16), template VARCHAR(64), destination VARCHAR(255), "
            "idempotency_key VARCHAR(160) NOT NULL UNIQUE, status VARCHAR(16), "
            "scheduled_for DATETIME NOT NULL, attempts INTEGER, last_error TEXT, "
            "sent_at DATETIME, payload_json TEXT, correlation_id VARCHAR(64), "
            "created_at DATETIME)"
        )
        legacy.execute(
            "INSERT INTO notifications VALUES "
            "('j1','u1','email','appointment_reminder','a@b.org','k1','PENDING',"
            "'2031-01-01 00:00:00',0,NULL,NULL,'{\"appointment_id\":\"appt1\"}',"
            "'corr', '2031-01-01 00:00:00')"
        )
        legacy.commit()
        legacy.close()

        monkeypatch.setenv("DEDAN_DATABASE_URL", f"sqlite:///{path}")
        dbmod.reset_engine()
        try:
            from dedan_platform.models import Notification

            dbmod.create_all()
            engine = dbmod.get_engine()

            columns = {c["name"] for c in __import__("sqlalchemy").inspect(
                engine).get_columns("notifications")}
            assert {"appointment_id", "provider_message_id", "updated_at"} <= columns

            # The legacy row is linked to its appointment, so it can be
            # cancelled by the new indexed lookup rather than becoming immortal.
            with engine.connect() as conn:
                linked = conn.exec_driver_sql(
                    "SELECT appointment_id FROM notifications WHERE id = 'j1'"
                ).scalar()
                stamped = conn.exec_driver_sql(
                    "SELECT updated_at FROM notifications WHERE id = 'j1'"
                ).scalar()
            assert linked == "appt1"
            assert stamped is not None, "legacy rows must be backfilled, not left stale"
        finally:
            dbmod.reset_engine()

    def test_migrations_are_idempotent(self, db):
        from dedan_platform import migrations

        assert migrations.apply_migrations() == []
        assert migrations.apply_migrations() == []

    def test_a_failure_is_not_swallowed(self, db, monkeypatch):
        """A migration that cannot apply must surface, not pass silently.

        A swallowed schema failure is the worst possible outcome here: the
        service starts, the ORM selects a column that does not exist, and every
        query fails far from the cause.
        """
        from dedan_platform import migrations

        monkeypatch.setattr(
            migrations, "_COLUMN_MIGRATIONS",
            (migrations.ColumnMigration("notifications", "brand_new", "VARCHAR(1)"),),
        )

        def boom(engine, statement, params=None):
            raise RuntimeError("disk on fire")

        monkeypatch.setattr(migrations, "_execute", boom)

        with pytest.raises(RuntimeError, match="disk on fire"):
            migrations.apply_migrations()

    def test_a_concurrent_migration_is_absorbed(self, db, monkeypatch):
        """Two processes racing must not crash startup."""
        from dedan_platform import migrations

        monkeypatch.setattr(
            migrations, "_COLUMN_MIGRATIONS",
            (migrations.ColumnMigration("notifications", "raced", "VARCHAR(1)"),),
        )
        monkeypatch.setattr(
            migrations, "_execute",
            lambda *a, **k: (_ for _ in ()).throw(
                Exception("duplicate column name: raced")),
        )
        assert migrations.apply_migrations() == []