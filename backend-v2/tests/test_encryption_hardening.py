"""Hardening of the encryption of health data (review of the first version):
purging old keys safely, clinical data in Redis only while in flight,
enforcement (plaintext refused once everything is encrypted), rollbacks,
stale cached keys and failing closed without a master key.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from test_encryption import (  # noqa: F401 -- fixtures (client, bus, patient, hospital_files, master_key) and helpers
    CIPHERTEXT, _copy_path, _publish_with_file, add_event, age_keys, bus, client, hospital_files, load_event,
    master_key, patient, raw, set_raw,
)
from test_patient_history import (  # noqa: F401
    KEY, LISTING, PDF, file_meta, from_hospital, lab_record, register, run_worker,
)

QUIET = {"out": lambda _line: None}


def file_url(record, meta):
    return f"/users/me/history/records/{record['record_id']}/files/{meta['file_id']}"


def header_version(record, meta):
    from dedan_platform import file_crypto

    with open(_copy_path(record["record_id"], meta["file_id"]), "rb") as handle:
        return file_crypto.read_header(handle)


# --- 1. purging old keys -----------------------------------------------------------------------------

class TestPurgeOldKeys:
    def test_refused_within_the_grace_period(self, client, patient):
        from dedan_platform import tools

        add_event(patient["id"])
        assert tools.rotate_key(patient["id"], **QUIET) == 0
        assert tools.purge_old_keys(patient["id"], **QUIET) == 1
        age_keys(patient["id"], hours=23)
        assert tools.purge_old_keys(patient["id"], **QUIET) == 1
        age_keys(patient["id"], hours=25)
        assert tools.purge_old_keys(patient["id"], **QUIET) == 0
        assert load_event(add_event(patient["id"])["event_id"])[1] == "Asthma flare-up"

    def test_refused_while_a_file_is_waiting_or_downloading(self, client, bus, patient, hospital_files):
        from dedan_platform import record_files, tools
        from dedan_platform.db import session_scope
        from dedan_platform.models import RecordFile, RecordFileStatus

        meta = file_meta(PDF, "application/pdf", filename="mri.pdf")
        record = lab_record(patient["dedan"], files=[meta])
        hospital_files[(record["record_id"], meta["file_id"])] = PDF
        from_hospital(bus, "record.published", record)
        run_worker(bus)  # the file waits (PENDING)
        tools.rotate_key(patient["id"], **QUIET)
        age_keys(patient["id"], hours=25)
        assert tools.purge_old_keys(patient["id"], **QUIET) == 1
        with session_scope() as session:
            session.execute(update(RecordFile).values(status=RecordFileStatus.DOWNLOADING))
        assert tools.purge_old_keys(patient["id"], **QUIET) == 1
        with session_scope() as session:
            session.execute(update(RecordFile).values(status=RecordFileStatus.PENDING))
        assert record_files.download_due() == 1
        assert header_version(record, meta) == 2  # stored under the active key
        assert tools.purge_old_keys(patient["id"], **QUIET) == 0
        resp = client.get(file_url(record, meta), headers=patient["auth"])
        assert resp.status_code == 200 and resp.content == PDF

    def test_plaintext_values_are_not_counted_as_using_an_old_key(self, client, patient):
        from dedan_platform import crypto, tools
        from dedan_platform.db import session_scope

        event = add_event(patient["id"])
        with session_scope() as session:
            version = crypto.rotate_user_key(session, patient["id"])
        with session_scope() as session:
            before = tools._old_values(session.connection(), patient["id"], version)
        set_raw("health_events", "description", event["event_id"], "Legacy plaintext")
        with session_scope() as session:
            after = tools._old_values(session.connection(), patient["id"], version)
        assert before >= 3 and after == before - 1

    def test_a_download_begun_before_a_rotation_is_stored_under_the_new_key(self, client, bus, patient,
                                                                             monkeypatch):
        from dedan_platform import crypto, record_files
        from dedan_platform.db import session_scope

        meta = file_meta(PDF, "application/pdf", filename="ct-scan.pdf")
        record = lab_record(patient["dedan"], files=[meta])
        from_hospital(bus, "record.published", record)
        run_worker(bus)

        def handler(request):
            # The patient's key is rotated while the file is on its way.
            with session_scope() as session:
                crypto.rotate_user_key(session, patient["id"])
            return httpx.Response(200, content=PDF)

        monkeypatch.setattr(record_files, "_transport", httpx.MockTransport(handler))
        assert record_files.download_due() == 1
        assert header_version(record, meta) == 2
        resp = client.get(file_url(record, meta), headers=patient["auth"])
        assert resp.status_code == 200 and resp.content == PDF


# --- 2. Redis ----------------------------------------------------------------------------------------

class TestRedis:
    def test_handled_events_leave_the_stream(self, client, bus):
        from_hospital(bus, "hospital.listed", LISTING)
        from_hospital(bus, "no.such.event", {"title": "ignored"})
        run_worker(bus)
        assert bus.xlen("endod:hospital") == 0

    def test_entries_another_group_has_not_acknowledged_stay(self, client, bus):
        from dedan_platform import eventbus

        from_hospital(bus, "hospital.listed", LISTING)
        bus.xgroup_create("endod:hospital", "auditor", id="0")
        run_worker(bus)
        assert bus.xlen("endod:hospital") == 1
        for _stream, entries in bus.xreadgroup("auditor", "a", {"endod:hospital": ">"}):
            for message_id, _fields in entries:
                bus.xack("endod:hospital", "auditor", message_id)
        assert eventbus.trim_acknowledged(bus, "endod:hospital") == 1
        assert bus.xlen("endod:hospital") == 0

    def test_sent_events_leave_once_the_hospital_service_acknowledges(self, client, bus):
        from dedan_platform import eventbus
        from dedan_platform.db import session_scope

        with session_scope() as session:
            eventbus.emit(session, "appointment.requested", {"notes": "Chest pain"})
            eventbus.emit(session, "appointment.requested", {"notes": "Rash"})
        eventbus.publish_pending(bus)
        assert eventbus.trim_acknowledged(bus, "endod:patient") == 0  # no reader yet: kept
        bus.xgroup_create("endod:patient", "hospital-service", id="0")
        [(_stream, entries)] = bus.xreadgroup("hospital-service", "h", {"endod:patient": ">"}, count=2)
        bus.xack("endod:patient", "hospital-service", entries[0][0])
        assert eventbus.trim_acknowledged(bus, "endod:patient") == 1
        assert [f["payload"] for _id, f in bus.xrange("endod:patient")] == ['{"notes": "Rash"}']
        bus.xack("endod:patient", "hospital-service", entries[1][0])
        eventbus.trim_acknowledged(bus, "endod:patient")
        assert bus.xlen("endod:patient") == 0

    def test_dead_letters_keep_no_clinical_content_and_are_capped(self, client, bus, patient, monkeypatch):
        from dedan_platform import eventbus

        calls = []
        real = bus.xadd

        def spy(name, fields, *args, **kwargs):
            if name == eventbus.DEAD_LETTER:
                calls.append(kwargs)
            return real(name, fields, *args, **kwargs)

        monkeypatch.setattr(bus, "xadd", spy)
        record = lab_record(patient["dedan"], title="Schizophrenia relapse", occurred_at="not a date")
        from_hospital(bus, "record.published", record)
        run_worker(bus)
        [(_id, fields)] = bus.xrange("endod:dead-letter")
        assert "payload" not in fields
        assert json.loads(fields["payload_ids"])["record_id"] == record["record_id"]
        assert "title" in fields["payload_keys"].split(",")
        stored = json.dumps(fields)
        for clinical in ("Schizophrenia", "Hemoglobin", "Blood", "Dr. Hana"):
            assert clinical not in stored
        assert calls == [{"maxlen": eventbus.DEAD_LETTER_MAXLEN, "approximate": True}]

    def test_errors_lose_the_input_values_they_quote(self):
        from dedan_platform import eventbus

        why = ("1 validation error for Record\ntitle\n  String should have at most 200 characters "
               "[type=string_too_long, input_value='HIV positive, CD4 120', input_type=str]")
        assert "HIV" not in eventbus.redact_error(why) and "input_value=<removed>" in eventbus.redact_error(why)

    def test_redis_keeps_no_snapshot_and_rewrites_its_append_only_file(self):
        script = (Path(__file__).resolve().parents[2] / "deploy" / "redis" / "redis.sh").read_text()
        assert '--save ""' in script and "bgrewriteaof" in script


# --- 3. enforcement -----------------------------------------------------------------------------------

class TestEnforcement:
    def test_enforce_needs_a_clean_check_then_plaintext_is_refused(self, client, patient, caplog):
        from dedan_platform import crypto, tools

        event = add_event(patient["id"])
        set_raw("health_events", "description", event["event_id"], "Legacy note")
        assert load_event(event["event_id"])[1] == "Legacy note"  # read as it is before enforcement
        assert tools.enforce(**QUIET) == 1
        assert not crypto.enforced()
        tools.encrypt_existing(**QUIET)
        assert tools.main(["enforce"]) == 0
        assert crypto.enforced()
        assert load_event(event["event_id"])[1] == "Legacy note"  # encrypted values read as before

        set_raw("health_events", "description", event["event_id"], "Injected plaintext")
        with caplog.at_level(logging.ERROR), pytest.raises(crypto.DecryptionError) as error:
            load_event(event["event_id"])
        where = f"health_events.description of row {event['event_id']}"
        assert where in str(error.value) and where in caplog.text
        assert "Injected" not in str(error.value) and "Injected" not in caplog.text

    def test_a_plaintext_file_is_refused_once_enforced(self, client, bus, patient, hospital_files):
        from dedan_platform import tools

        record, meta = _publish_with_file(client, bus, patient, hospital_files)
        assert tools.enforce(**QUIET) == 0
        _copy_path(record["record_id"], meta["file_id"]).write_bytes(PDF)  # as if stored before encryption
        resp = client.get(file_url(record, meta), headers=patient["auth"])
        assert resp.status_code == 503 and b"%PDF" not in resp.content

    def test_a_plaintext_that_only_looks_encrypted(self, client, patient):
        from dedan_platform import crypto, tools

        event = add_event(patient["id"])
        for legacy in ("enc:v1:my own notes", "enc:v1:1:", "enc:v1:x:AAAA"):
            set_raw("health_events", "description", event["event_id"], legacy)
            assert load_event(event["event_id"])[1] == legacy  # not an envelope: plaintext, before enforcement
        assert tools.check(**QUIET)["health_events.description"] == 1
        tools.encrypt_existing(**QUIET)
        assert CIPHERTEXT.match(raw("health_events", "description", event["event_id"]))
        assert load_event(event["event_id"])[1] == "enc:v1:x:AAAA"
        assert tools.enforce(**QUIET) == 0
        set_raw("health_events", "description", event["event_id"], "enc:v1:junk")
        with pytest.raises(crypto.DecryptionError):
            load_event(event["event_id"])

    def test_decrypt_existing_turns_enforcement_off(self, client, patient):
        from dedan_platform import crypto, tools

        event = add_event(patient["id"], description="Hepatitis B")
        tools.enforce(**QUIET)
        assert tools.main(["decrypt-existing", "--yes"]) == 0
        assert not crypto.enforced()
        assert raw("health_events", "description", event["event_id"]) == "Hepatitis B"
        assert load_event(event["event_id"])[1] == "Hepatitis B"


# --- 4. rollbacks ---------------------------------------------------------------------------------------

class TestRollback:
    def test_values_from_a_rolled_back_savepoint_are_encrypted_again(self, client, patient):
        from dedan_platform import crypto
        from dedan_platform.db import session_scope
        from dedan_platform.models import HealthEvent, UserKey

        other = register(client, email="b@example.com", phone=None)
        taken = add_event(patient["id"])["event_id"]
        with session_scope() as session:  # a patient with no data key yet
            session.execute(UserKey.__table__.delete().where(UserKey.user_id == other["id"]))
        crypto.clear_cache()

        with session_scope() as session:
            event = HealthEvent(user_id=other["id"], event_type="CONSULTATION", title="Psoriasis",
                                description="Methotrexate", occurred_at=datetime.now(timezone.utc))
            with pytest.raises(IntegrityError):
                with session.begin_nested():
                    session.add(event)
                    # Same primary key as an existing row: the flush fails, and
                    # the data key made for ``other`` in it rolls back too.
                    session.add(HealthEvent(id=taken, user_id=patient["id"], event_type="CONSULTATION",
                                            title="duplicate", occurred_at=datetime.now(timezone.utc)))
                    session.flush()
            assert (event.title, event.description) == ("Psoriasis", "Methotrexate")  # plaintext again
            session.add(event)
            event_id = event.id
        assert load_event(event_id)[:2] == ("Psoriasis", "Methotrexate")
        assert CIPHERTEXT.match(raw("health_events", "title", event_id))


# --- 5. stale cached keys -----------------------------------------------------------------------------

class TestStaleCache:
    def test_a_file_is_read_again_with_the_key_from_the_database(self, client, bus, patient, hospital_files):
        from dedan_platform import crypto

        record, meta = _publish_with_file(client, bus, patient, hospital_files)
        crypto._cache_put(crypto.key_id(), patient["id"], 1, os.urandom(32))  # a stale key in the cache
        resp = client.get(file_url(record, meta), headers=patient["auth"])
        assert resp.status_code == 200 and resp.content == PDF

    def test_a_value_is_read_again_with_the_key_from_the_database(self, client, patient):
        from dedan_platform import crypto

        event = add_event(patient["id"], description="Lupus")
        crypto._cache_put(crypto.key_id(), patient["id"], 1, os.urandom(32))
        assert load_event(event["event_id"])[1] == "Lupus"


# --- 6. failing closed ----------------------------------------------------------------------------------

class TestFailClosed:
    @pytest.mark.parametrize("environment", ["staging", "production", "prod", "", None])
    def test_no_key_file_is_refused_unless_development_or_test(self, monkeypatch, environment):
        from app.core import config

        from dedan_platform import crypto

        monkeypatch.setenv("PLATFORM_MASTER_KEY_FILE", "")
        if environment is None:
            # Unset everywhere: the settings' default ("development") does not count.
            monkeypatch.delenv("ENVIRONMENT", raising=False)
            monkeypatch.setattr(config, "get_settings", lambda: config.Settings(_env_file=None))
        else:
            monkeypatch.setenv("ENVIRONMENT", environment)
        crypto.reset()
        with pytest.raises(crypto.MasterKeyError):
            crypto.require_master_key()

    def test_the_three_services_log_the_same_key_fingerprint(self, monkeypatch, caplog):
        import main_clinical
        import main_internal

        from dedan_platform import crypto, db, events_worker

        class Started(Exception):
            pass

        def stop():
            raise Started()

        with caplog.at_level(logging.WARNING, logger="dedan_platform.crypto"):
            main_clinical.create_app()
            main_internal.create_app()
            monkeypatch.setattr(db, "create_all", stop)  # the worker stops right after its key check
            with pytest.raises(Started):
                events_worker.main()
        ident = crypto.key_id()
        for service in ("backend", "internal-api", "events-worker"):
            assert f"master_key_in_use service={service} id={ident}" in caplog.text
