"""Texts to a clinic's contact about its Endod demo (``onboarding.demo_booked``).

Redis is in memory (fakeredis); texts go through the notification queue and
a fake SMS provider.
"""

import json
import uuid
from datetime import datetime, timezone

import fakeredis
import pytest
from sqlalchemy import select

HOSPITAL = "d" * 32


class FakeSms:
    def __init__(self):
        self.sent = []

    def send(self, phone, text):
        self.sent.append((phone, text))
        return f"sms-{len(self.sent)}"


@pytest.fixture
def db(tmp_path, monkeypatch):
    from dedan_platform import db as dbmod

    monkeypatch.setenv("DEDAN_DATABASE_URL", f"sqlite:///{tmp_path / 'onboarding.db'}")
    monkeypatch.setenv("REMINDER_CHANNELS", "sms")
    dbmod.reset_engine()
    dbmod.create_all()
    yield
    dbmod.reset_engine()


@pytest.fixture
def bus():
    return fakeredis.FakeRedis(decode_responses=True)


def demo(booking_id=None, **extra):
    return {"hospital_id": HOSPITAL, "booking_id": booking_id or uuid.uuid4().hex,
            "contact_name": "Selam Bekele", "phone": "+251911556677",
            "demo_at": "2026-10-28T07:30:00+00:00", "hospital_name": "Bethel Clinic", "changed": False,
            **extra}


def send(bus, payload, event_id=None):
    bus.xadd("endod:hospital", {"id": event_id or uuid.uuid4().hex, "type": "onboarding.demo_booked",
                                "source": "hospital-service",
                                "occurred_at": datetime.now(timezone.utc).isoformat(),
                                "payload": json.dumps(payload)})


def run_worker(bus):
    from dedan_platform import events_worker

    events_worker.run_once(bus)


def deliver():
    from dedan_platform import worker

    sms = FakeSms()
    worker.run_once(limit=100, sms_provider=sms)
    return sms.sent


def texts():
    from dedan_platform.db import session_scope
    from dedan_platform.models import Notification

    with session_scope() as session:
        return [(r.template, r.status, r.destination, r.idempotency_key)
                for r in session.scalars(select(Notification)).all()]


def test_the_contact_is_texted_once_in_amharic_then_english_in_addis_time(db, bus):
    send(bus, demo())
    run_worker(bus)
    [(phone, text)] = deliver()
    amharic, english = text.split("\n")
    assert phone == "+251911556677"
    # 07:30 UTC is 10:30 in Addis Ababa.
    assert english.endswith("your demo for Bethel Clinic is booked for Wed 28 Oct, 10:30. We will call you then.")
    assert "ለBethel Clinic" in amharic and "28/10/2026 10:30" in amharic and "ተይዟል" in amharic
    assert deliver() == []


def test_a_redelivered_or_repeated_event_texts_once(db, bus):
    payload = demo()
    event_id = uuid.uuid4().hex
    send(bus, payload, event_id=event_id)
    send(bus, payload, event_id=event_id)  # the same event, redelivered
    send(bus, payload)  # the same booking and time, as a new event
    send(bus, {**payload, "demo_at": "2026-10-28T10:30:00+03:00"})  # the same moment, another offset
    run_worker(bus)
    run_worker(bus)
    assert len(deliver()) == 1
    assert len(texts()) == 1


def test_a_moved_demo_says_so_and_the_old_unsent_text_is_dropped(db, bus):
    booking = uuid.uuid4().hex
    send(bus, demo(booking))
    send(bus, demo(booking, demo_at="2026-10-30T09:00:00+03:00", changed=True))
    run_worker(bus)
    [(_phone, text)] = deliver()
    assert "has moved to Fri 30 Oct, 09:00" in text and "ተዛውሯል" in text
    statuses = sorted((template, status) for template, status, _d, _k in texts())
    assert statuses == [("sms_demo_booked", "CANCELLED"), ("sms_demo_moved", "SENT")]


def test_a_malformed_event_is_dead_lettered(db, bus):
    send(bus, demo(booking_id="not-hex"))
    send(bus, demo(demo_at="2026-10-28T10:30:00"))  # no offset
    send(bus, {k: v for k, v in demo().items() if k != "changed"})
    run_worker(bus)
    assert len(bus.xrange("endod:dead-letter")) == 3
    assert texts() == []


def test_an_invalid_phone_is_skipped(db, bus):
    send(bus, demo(phone="+14155550100"))
    send(bus, demo(phone="12345"))
    run_worker(bus)
    assert texts() == [] and bus.xrange("endod:dead-letter") == []


def test_a_local_number_is_normalised(db, bus):
    send(bus, demo(phone="0911 55 66 77"))
    run_worker(bus)
    [(phone, _text)] = deliver()
    assert phone == "+251911556677"
