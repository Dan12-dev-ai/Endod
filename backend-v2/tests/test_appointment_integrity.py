"""Timeline consistency, double booking, and protected safety records."""

from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    from dedan_platform import db as dbmod

    monkeypatch.setenv("DEDAN_DATABASE_URL", f"sqlite:///{tmp_path / 'integrity.db'}")
    dbmod.reset_engine()
    dbmod.create_all()
    yield
    dbmod.reset_engine()


@pytest.fixture
def patient(db):
    from dedan_platform import identity

    return identity.create_user(email="p@example.com")["internal_user_id"]


def _at(hours, minutes=0):
    return (datetime.now(timezone.utc) + timedelta(days=3, hours=hours, minutes=minutes)).replace(
        second=0, microsecond=0
    )


def _book(uid, when, **kwargs):
    from dedan_platform import appointments

    return appointments.create_appointment(uid, scheduled_at=when, **kwargs)["appointment"]


def _appointment_events(uid):
    from dedan_platform import timeline

    return [e for e in timeline.list_events(user_id=uid, limit=50)["events"] if e["event_type"] == "APPOINTMENT"]


class TestTimeline:
    def test_cancellation_updates_the_timeline(self, patient):
        from dedan_platform import appointments, timeline

        appointment = _book(patient, _at(0))
        assert timeline.summarise_timeline(patient)["upcoming"] == 1
        appointments.update_status(patient, appointment["appointment_id"], "CANCELLED")
        assert _appointment_events(patient)[0]["status"] == "CANCELLED"
        assert timeline.summarise_timeline(patient)["upcoming"] == 0

    def test_reschedule_moves_the_timeline_entry(self, patient):
        from dedan_platform import appointments

        appointment = _book(patient, _at(0))
        new_time = _at(26)
        appointments.reschedule(patient, appointment["appointment_id"], new_time)
        event = _appointment_events(patient)[0]
        assert event["status"] == "RESCHEDULED"
        assert datetime.fromisoformat(event["occurred_at"]).replace(tzinfo=timezone.utc) == new_time


class TestDoubleBooking:
    def test_patient_cannot_be_in_two_appointments_at_once(self, patient):
        from dedan_platform import appointments

        _book(patient, _at(0), duration_minutes=60)
        with pytest.raises(appointments.AppointmentError, match="already have"):
            _book(patient, _at(0, 30))

    def test_back_to_back_is_allowed(self, patient):
        _book(patient, _at(0), duration_minutes=30)
        _book(patient, _at(0, 30))

    def test_provider_cannot_be_double_booked(self, patient):
        from dedan_platform import appointments, identity

        other = identity.create_user(email="o@example.com")["internal_user_id"]
        _book(patient, _at(0), provider_id="dr-abebe")
        with pytest.raises(appointments.AppointmentError, match="no longer available"):
            _book(other, _at(0, 15), provider_id="dr-abebe")

    def test_cancelled_slot_can_be_rebooked(self, patient):
        from dedan_platform import appointments

        first = _book(patient, _at(0))
        appointments.update_status(patient, first["appointment_id"], "CANCELLED")
        _book(patient, _at(0))

    def test_reschedule_into_a_clash_is_refused(self, patient):
        from dedan_platform import appointments

        _book(patient, _at(0), duration_minutes=60)
        second = _book(patient, _at(5))
        with pytest.raises(appointments.AppointmentError):
            appointments.reschedule(patient, second["appointment_id"], _at(0, 30))

    def test_reschedule_within_its_own_slot_is_fine(self, patient):
        from dedan_platform import appointments

        appointment = _book(patient, _at(0), duration_minutes=60)
        appointments.reschedule(patient, appointment["appointment_id"], _at(0, 15))


class TestProtectedRecords:
    def test_safety_alert_cannot_be_deleted(self, patient):
        from dedan_platform import timeline
        from dedan_platform.models import HealthEventType

        event = timeline.record_event(user_id=patient, event_type=HealthEventType.SAFETY_ALERT,
                                      title="Urgent care recommended", source="dedan")
        with pytest.raises(timeline.ProtectedEventError):
            timeline.delete_event(patient, event["event_id"])

    def test_ordinary_entries_can_be_deleted(self, patient):
        from dedan_platform import timeline
        from dedan_platform.models import HealthEventType

        event = timeline.record_event(user_id=patient, event_type=HealthEventType.MEDICATION,
                                      title="Started vitamin D", source="patient")
        assert timeline.delete_event(patient, event["event_id"]) is True


class TestReviewFindings:
    """Automated review (Qodo) of PR #10."""

    def test_confirmed_and_rescheduled_visits_stay_upcoming(self, patient):
        from dedan_platform import appointments, timeline

        first = _book(patient, _at(0))
        second = _book(patient, _at(10))
        appointments.update_status(patient, first["appointment_id"], "CONFIRMED")
        appointments.reschedule(patient, second["appointment_id"], _at(30))
        assert timeline.summarise_timeline(patient)["upcoming"] == 2

    def test_timeline_and_appointment_change_together(self, patient, monkeypatch):
        from dedan_platform import appointments

        appointment = _book(patient, _at(0))

        def fail(*args, **kwargs):
            raise RuntimeError("timeline write failed")

        monkeypatch.setattr(appointments, "update_appointment_event", fail)
        with pytest.raises(RuntimeError):
            appointments.update_status(patient, appointment["appointment_id"], "CANCELLED")
        # Rolled back as one unit: the appointment did not change either.
        assert appointments.get_appointment(patient, appointment["appointment_id"])["status"] == "SCHEDULED"

    def test_postgres_bookings_take_ordered_advisory_locks(self):
        from types import SimpleNamespace

        from dedan_platform import appointments

        calls = []
        session = SimpleNamespace(
            bind=SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
            execute=lambda statement, params: calls.append(params["id"]),
        )
        appointments._lock_booking(session, ["provider:dr-a", "patient:u1"])
        assert len(calls) == 2
        again = []
        session.execute = lambda statement, params: again.append(params["id"])
        appointments._lock_booking(session, ["patient:u1", "provider:dr-a"])
        assert again == calls  # same order regardless of input order: no deadlock
