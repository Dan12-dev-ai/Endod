"""Application-level encryption of health data (dedan_platform/crypto.py,
field_encryption.py, file_crypto.py, tools.py).

Covers the primitives (round trips, associated data, wrong keys, the file
format), and that after the main flows -- a hospital record received, a
self-reported visit, a health profile saved, an AI interview completed --
no clinical text is stored in plaintext anywhere in the database.
"""

import base64
import hashlib
import io
import json
import os
import re
from datetime import datetime, timedelta, timezone

import fakeredis
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select, text, update

from test_patient_history import (  # noqa: F401 -- shared helpers (not fixtures)
    HOSPITAL, KEY, PDF, PNG, file_meta, from_hospital, hexid, lab_record, register, run_worker,
)

CIPHERTEXT = re.compile(r"^enc:v1:[0-9]+:[A-Za-z0-9+/]+=*$")


# --- fixtures ------------------------------------------------------------------------------------

def _write_key(path, key=None):
    path.write_bytes(key or os.urandom(32))
    return path


@pytest.fixture(autouse=True)
def master_key(tmp_path, monkeypatch):
    """A real master key file for every test here (not the development key)."""
    from dedan_platform import crypto

    path = _write_key(tmp_path / "master.key")
    monkeypatch.setenv("PLATFORM_MASTER_KEY_FILE", str(path))
    crypto.reset()
    yield path
    crypto.reset()


@pytest.fixture
def client(tmp_path, monkeypatch):
    from dedan_platform import db as dbmod
    from dedan_platform.api_auth import router as auth_router
    from dedan_platform.api_care import router as care_router
    from dedan_platform.api_health import router as health_router
    from dedan_platform.api_history import internal_router, router as history_router
    from dedan_platform.api_inbox import router as inbox_router
    from dedan_platform.api_profile import router as profile_router
    from dedan_platform.api_records import router as records_router

    monkeypatch.setenv("REALTIME_TOKEN_SECRET", "test-secret")
    monkeypatch.setenv("DEDAN_DATABASE_URL", f"sqlite:///{tmp_path / 'encryption.db'}")
    monkeypatch.setenv("REMINDER_CHANNELS", "sms")
    monkeypatch.setenv("RECORD_FILES_DIR", str(tmp_path / "records"))
    monkeypatch.setenv("HOSPITAL_API_URL", "http://endod-hospital-api:8000")
    monkeypatch.setenv("PLATFORM_ADMIN_KEY", KEY)
    monkeypatch.setenv("PHARMACY_API_KEY", "pharmacy-test-key")
    monkeypatch.setenv("RX_SIGNING_KEY", "rx-test-key")
    dbmod.reset_engine()
    dbmod.create_all()
    app = FastAPI()
    for router in (auth_router, profile_router, health_router, care_router, inbox_router, records_router,
                   history_router, internal_router):
        app.include_router(router)
    yield TestClient(app)
    dbmod.reset_engine()


@pytest.fixture
def bus():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def patient(client):
    return register(client)


@pytest.fixture
def hospital_files(monkeypatch):
    """The hospital API serving record files (as tests/test_patient_history does)."""
    import httpx

    from dedan_platform import record_files

    files = {}

    def handler(request):
        if request.headers.get("X-Platform-Key") != KEY:
            return httpx.Response(401)
        parts = request.url.path.strip("/").split("/")
        body = files.get((parts[2], parts[4]))
        return httpx.Response(200, content=body) if body is not None else httpx.Response(404)

    monkeypatch.setattr(record_files, "_transport", httpx.MockTransport(handler))
    return files


# --- helpers -------------------------------------------------------------------------------------

def raw_values():
    """Every stored value of every encrypted column: {(table, column): [(id, user_id, value)]}."""
    from dedan_platform import field_encryption
    from dedan_platform.db import get_engine

    out = {}
    with get_engine().connect() as conn:
        for model in field_encryption.encrypted_models():
            table = model.__table__
            for name in model.__encrypted__:
                out[(table.name, name)] = [tuple(r) for r in conn.execute(
                    select(table.c.id, table.c.user_id, table.c[name]).where(table.c[name].is_not(None)))]
    return out


def all_stored_text():
    """Every text value in every table of the database, as stored."""
    from dedan_platform.db import get_engine

    engine = get_engine()
    values = []
    with engine.connect() as conn:
        for table in sa_inspect(engine).get_table_names():
            for row in conn.execute(text(f'SELECT * FROM "{table}"')):
                values.extend(f"{table}: {v}" for v in row if isinstance(v, str))
    return values


def assert_not_stored(*plaintexts):
    """None of these clinical strings is stored anywhere in the database, in
    any table, and every encrypted column holds ciphertext only."""
    stored = all_stored_text()
    for plaintext in plaintexts:
        leaks = [v for v in stored if plaintext.lower() in v.lower()]
        assert not leaks, f"{plaintext!r} stored in plaintext: {leaks[:3]}"
    for (table, column), rows in raw_values().items():
        for row_id, _user, value in rows:
            assert CIPHERTEXT.match(value), f"{table}.{column} of {row_id} is not encrypted"


def raw(table, column, row_id):
    from dedan_platform.db import get_engine

    with get_engine().connect() as conn:
        return conn.execute(text(f"SELECT {column} FROM {table} WHERE id = :id"), {"id": row_id}).scalar()


def set_raw(table, column, row_id, value):
    from dedan_platform.db import get_engine

    with get_engine().begin() as conn:
        conn.execute(text(f"UPDATE {table} SET {column} = :v WHERE id = :id"), {"v": value, "id": row_id})


def add_event(user_id, title="Visit", description="Asthma flare-up"):
    from dedan_platform.timeline import record_event

    return record_event(user_id=user_id, event_type="CONSULTATION", title=title, description=description,
                        metadata={"record": {"facility_name": "Black Lion", "diagnosis": description}})


def load_event(event_id):
    from dedan_platform.db import session_scope
    from dedan_platform.models import HealthEvent

    with session_scope() as session:
        event = session.get(HealthEvent, event_id)
        return (event.title, event.description, event.metadata_json)


# --- 1. values: round trip, format, binding, keys ----------------------------------------------------

class TestValues:
    def test_round_trip_and_format(self):
        from dedan_platform import crypto

        key = os.urandom(32)
        aad = crypto.value_aad("health_events", "title", "a" * 32, "b" * 32)
        for plaintext in ("", "Hypertension", "ደም ግፊት — 140/90 mmHg", "x" * 100_000):
            sealed = crypto.encrypt_value(plaintext, key=key, version=3, aad=aad)
            assert CIPHERTEXT.match(sealed) and sealed.startswith("enc:v1:3:")
            assert crypto.key_version(sealed) == 3
            assert crypto.decrypt_value(sealed, key=key, aad=aad) == plaintext
            # nonce || ciphertext || tag
            assert len(base64.b64decode(sealed.split(":", 3)[3])) == 12 + len(plaintext.encode()) + 16

    def test_every_encryption_uses_a_fresh_nonce(self):
        from dedan_platform import crypto

        key, aad = os.urandom(32), b"aad"
        sealed = [crypto.encrypt_value("same", key=key, version=1, aad=aad) for _ in range(200)]
        nonces = {base64.b64decode(s.split(":", 3)[3])[:12] for s in sealed}
        assert len(nonces) == 200

    @pytest.mark.parametrize("other", [
        ("health_events", "title", "a" * 32, "c" * 32),        # another user
        ("health_events", "title", "d" * 32, "b" * 32),        # another row
        ("health_events", "description", "a" * 32, "b" * 32),  # another column
        ("hospital_records", "title", "a" * 32, "b" * 32),     # another table
    ])
    def test_ciphertext_is_bound_to_its_table_column_row_and_user(self, other):
        from dedan_platform import crypto

        key = os.urandom(32)
        sealed = crypto.encrypt_value("Type 2 diabetes", key=key, version=1,
                                      aad=crypto.value_aad("health_events", "title", "a" * 32, "b" * 32))
        with pytest.raises(crypto.DecryptionError):
            crypto.decrypt_value(sealed, key=key, aad=crypto.value_aad(*other))

    def test_a_wrong_key_or_a_tampered_value_fails(self):
        from dedan_platform import crypto

        key, aad = os.urandom(32), b"aad"
        sealed = crypto.encrypt_value("HIV positive", key=key, version=1, aad=aad)
        with pytest.raises(crypto.DecryptionError):
            crypto.decrypt_value(sealed, key=os.urandom(32), aad=aad)
        raw_bytes = bytearray(base64.b64decode(sealed.split(":", 3)[3]))
        raw_bytes[15] ^= 1
        with pytest.raises(crypto.DecryptionError):
            crypto.decrypt_value("enc:v1:1:" + base64.b64encode(bytes(raw_bytes)).decode(), key=key, aad=aad)
        for malformed in ("enc:v1:x:AAAA", "enc:v1:1:not base64!", "enc:v1:1:" + base64.b64encode(b"short").decode()):
            with pytest.raises(crypto.DecryptionError):
                crypto.decrypt_value(malformed, key=key, aad=aad)

    def test_errors_never_carry_the_plaintext(self, client, patient):
        from dedan_platform import crypto

        event = add_event(patient["id"], description="Bipolar disorder")
        set_raw("health_events", "description", event["event_id"], raw("health_events", "title", event["event_id"]))
        with pytest.raises(crypto.DecryptionError) as error:
            load_event(event["event_id"])
        assert "Bipolar" not in str(error.value) and "enc:v1" not in str(error.value)
        assert f"health_events.description of row {event['event_id']}" in str(error.value)


# --- 2. keys --------------------------------------------------------------------------------------------

class TestKeys:
    def test_production_refuses_to_start_without_the_master_key(self, monkeypatch):
        from dedan_platform import crypto

        monkeypatch.setenv("PLATFORM_MASTER_KEY_FILE", "")  # unset (settings may hold one)
        monkeypatch.setenv("ENVIRONMENT", "production")
        crypto.reset()
        with pytest.raises(crypto.MasterKeyError):
            crypto.require_master_key()

    def test_internal_api_and_events_worker_refuse_to_start_without_it(self, monkeypatch):
        import main_internal

        from dedan_platform import crypto, events_worker

        monkeypatch.setenv("PLATFORM_MASTER_KEY_FILE", "")  # unset (settings may hold one)
        monkeypatch.setenv("ENVIRONMENT", "production")
        crypto.reset()
        with pytest.raises(crypto.MasterKeyError):
            main_internal.create_app()
        with pytest.raises(crypto.MasterKeyError):
            events_worker.main()

    @pytest.mark.parametrize("content", [b"", b"short", os.urandom(31), os.urandom(33), b"a" * 64])
    def test_a_malformed_key_file_is_refused(self, tmp_path, monkeypatch, content):
        from dedan_platform import crypto

        path = tmp_path / "bad.key"
        path.write_bytes(content)
        monkeypatch.setenv("PLATFORM_MASTER_KEY_FILE", str(path))
        crypto.reset()
        with pytest.raises(crypto.MasterKeyError) as error:
            crypto.require_master_key()
        assert "openssl rand" in str(error.value)

    def test_a_missing_key_file_is_refused_in_any_environment(self, tmp_path, monkeypatch):
        from dedan_platform import crypto

        monkeypatch.setenv("PLATFORM_MASTER_KEY_FILE", str(tmp_path / "nope.key"))
        monkeypatch.setenv("ENVIRONMENT", "development")
        crypto.reset()
        with pytest.raises(crypto.MasterKeyError):
            crypto.master_key()

    def test_outside_production_without_a_key_file_the_development_key_is_used(self, monkeypatch):
        from dedan_platform import crypto

        monkeypatch.setenv("PLATFORM_MASTER_KEY_FILE", "")  # unset (settings may hold one)
        monkeypatch.setenv("ENVIRONMENT", "development")
        crypto.reset()
        assert crypto.master_key() == crypto._DEVELOPMENT_KEY

    def test_data_keys_are_per_user_wrapped_and_bound(self, client, patient):
        from dedan_platform import crypto
        from dedan_platform.db import get_engine, session_scope
        from dedan_platform.models import UserKey

        other = register(client, email="b@example.com", phone=None)
        add_event(patient["id"])
        add_event(other["id"])
        with session_scope() as session:
            keys = {k.user_id: (k.version, k.wrapped_key, k.active) for k in session.scalars(select(UserKey))}
        assert set(keys) == {patient["id"], other["id"]}
        version, wrapped, active = keys[patient["id"]]
        assert version == 1 and active and len(base64.b64decode(wrapped)) == 12 + 32 + 16
        assert keys[patient["id"]][1] != keys[other["id"]][1]
        # A wrapped key opens only for its own user and version.
        with pytest.raises(crypto.DecryptionError):
            crypto.unwrap_key(wrapped, other["id"], 1)
        with pytest.raises(crypto.DecryptionError):
            crypto.unwrap_key(wrapped, patient["id"], 2)
        # ... and only with the master key.
        with pytest.raises(crypto.DecryptionError):
            crypto.unwrap_key(wrapped, patient["id"], 1, kek=os.urandom(32))
        with get_engine().connect() as conn:
            assert crypto.data_key(conn, patient["id"], 1) == crypto.unwrap_key(wrapped, patient["id"], 1)

    def test_a_wrong_master_key_cannot_read_the_data(self, client, patient, tmp_path, monkeypatch):
        from dedan_platform import crypto

        event = add_event(patient["id"], description="Epilepsy")
        assert load_event(event["event_id"])[1] == "Epilepsy"
        monkeypatch.setenv("PLATFORM_MASTER_KEY_FILE", str(_write_key(tmp_path / "other.key")))
        crypto.reset()
        with pytest.raises(crypto.DecryptionError):
            load_event(event["event_id"])

    def test_unwrapped_keys_are_cached_briefly(self, client, patient, monkeypatch):
        from dedan_platform import crypto
        from dedan_platform.db import get_engine

        add_event(patient["id"])
        crypto.clear_cache()
        calls = []
        real = crypto.unwrap_key
        monkeypatch.setattr(crypto, "unwrap_key", lambda *a, **k: calls.append(1) or real(*a, **k))
        with get_engine().connect() as conn:
            for _ in range(5):
                crypto.data_key(conn, patient["id"], 1)
        assert len(calls) == 1
        monkeypatch.setattr(crypto, "CACHE_SECONDS", -1)
        crypto.clear_cache()
        with get_engine().connect() as conn:
            crypto.data_key(conn, patient["id"], 1)
            crypto.data_key(conn, patient["id"], 1)
        assert len(calls) == 3


# --- 3. the ORM: encrypted on write, decrypted on read, bound to row and user -------------------------------

class TestStoredValues:
    def test_round_trip_through_the_database(self, client, patient):
        event = add_event(patient["id"], title="Cardiology", description="Atrial fibrillation")
        # What the writer gets back, and what a later read gets, is the plaintext.
        assert event["title"] == "Cardiology" and event["description"] == "Atrial fibrillation"
        title, description, metadata = load_event(event["event_id"])
        assert (title, description) == ("Cardiology", "Atrial fibrillation")
        assert json.loads(metadata)["record"]["diagnosis"] == "Atrial fibrillation"
        for column in ("title", "description", "metadata_json"):
            assert CIPHERTEXT.match(raw("health_events", column, event["event_id"]))

    def test_a_changed_value_is_encrypted_again_and_unchanged_ones_are_not_rewritten(self, client, patient):
        from dedan_platform.db import session_scope
        from dedan_platform.models import HealthEvent

        event = add_event(patient["id"])
        before = {c: raw("health_events", c, event["event_id"]) for c in ("title", "description")}
        with session_scope() as session:
            session.get(HealthEvent, event["event_id"]).description = "Asthma, controlled"
        assert raw("health_events", "title", event["event_id"]) == before["title"]
        after = raw("health_events", "description", event["event_id"])
        assert after != before["description"] and CIPHERTEXT.match(after)
        assert load_event(event["event_id"])[1] == "Asthma, controlled"

    def test_ciphertext_moved_to_another_users_row_does_not_decrypt(self, client, patient):
        from dedan_platform import crypto

        other = register(client, email="b@example.com", phone=None)
        mine = add_event(patient["id"], description="Tuberculosis")
        theirs = add_event(other["id"], description="Sprained ankle")
        set_raw("health_events", "description", theirs["event_id"], raw("health_events", "description",
                                                                          mine["event_id"]))
        with pytest.raises(crypto.DecryptionError):
            load_event(theirs["event_id"])

    def test_ciphertext_moved_to_another_row_or_column_of_the_same_user_does_not_decrypt(self, client, patient):
        from dedan_platform import crypto

        first = add_event(patient["id"], description="Tuberculosis")
        second = add_event(patient["id"], description="Sprained ankle")
        set_raw("health_events", "description", second["event_id"],
                raw("health_events", "description", first["event_id"]))
        with pytest.raises(crypto.DecryptionError):
            load_event(second["event_id"])
        third = add_event(patient["id"])
        set_raw("health_events", "title", third["event_id"], raw("health_events", "description", third["event_id"]))
        with pytest.raises(crypto.DecryptionError):
            load_event(third["event_id"])

    def test_a_row_moved_to_another_patient_is_re_encrypted_for_them(self, client, patient):
        from dedan_platform.db import session_scope
        from dedan_platform.models import FollowUp

        other = register(client, email="b@example.com", phone=None)
        with session_scope() as session:
            row = FollowUp(user_id=patient["id"], hospital_id=HOSPITAL, hospital_name="Zewditu", visit_id=hexid(),
                           follow_up_on="2030-01-01", note="Bring the glucose diary")
            session.add(row)
            session.flush()
            follow_up_id = row.id
        with session_scope() as session:
            session.get(FollowUp, follow_up_id).user_id = other["id"]  # note itself unchanged
        with session_scope() as session:
            assert session.get(FollowUp, follow_up_id).note == "Bring the glucose diary"

    def test_plaintext_from_before_encryption_is_still_read(self, client, patient):
        event = add_event(patient["id"])
        set_raw("health_events", "description", event["event_id"], "Legacy plaintext note")
        assert load_event(event["event_id"])[1] == "Legacy plaintext note"


# --- 4. files ------------------------------------------------------------------------------------------------

def _encrypt_bytes(data, key, binding, chunk_size=1024, version=1):
    from dedan_platform import file_crypto

    out = io.BytesIO()
    sha = file_crypto.encrypt_file(io.BytesIO(data), out, key=key, version=version, binding=binding,
                                   chunk_size=chunk_size)
    assert sha == hashlib.sha256(data).hexdigest()
    return out.getvalue()


def _decrypt_bytes(blob, key, binding):
    from dedan_platform import file_crypto

    return b"".join(file_crypto.decrypt_chunks(io.BytesIO(blob), key_for_version=lambda _v: key, binding=binding))


class TestFiles:
    BINDING = None

    @pytest.fixture(autouse=True)
    def _binding(self):
        from dedan_platform import file_crypto

        self.binding = file_crypto.FileBinding(record_id="a" * 32, file_id="b" * 32, user_id="c" * 32)

    @pytest.mark.parametrize("size", [0, 1, 1023, 1024, 1025, 4096, 10 * 1024 + 7])
    def test_round_trip_at_and_around_chunk_boundaries(self, size):
        from dedan_platform import file_crypto

        key, data = os.urandom(32), os.urandom(size)
        blob = _encrypt_bytes(data, key, self.binding)
        assert blob.startswith(file_crypto.MAGIC) and data[:16] not in blob[file_crypto.HEADER.size:] or size < 16
        chunks = max(1, -(-size // 1024))
        assert len(blob) == file_crypto.HEADER.size + size + chunks * (12 + 16)
        assert _decrypt_bytes(blob, key, self.binding) == data

    def test_an_empty_file_is_one_empty_final_chunk(self):
        from dedan_platform import file_crypto

        key = os.urandom(32)
        blob = _encrypt_bytes(b"", key, self.binding)
        assert len(blob) == file_crypto.HEADER.size + 12 + 16
        assert _decrypt_bytes(blob, key, self.binding) == b""

    def test_a_large_file_streams_in_chunks(self):
        from dedan_platform import file_crypto

        key = os.urandom(32)
        data = os.urandom(5 * 1024 * 1024 + 123)  # several default-size chunks
        out = io.BytesIO()
        encryptor = file_crypto.Encryptor(out, key=key, version=7, binding=self.binding)
        for start in range(0, len(data), 10_000):  # pieces that do not line up with chunks
            encryptor.write(data[start:start + 10_000])
        encryptor.close()
        handle = io.BytesIO(out.getvalue())
        assert file_crypto.read_header(handle) == 7
        pieces = list(file_crypto.decrypt_chunks(handle, key_for_version=lambda v: key, binding=self.binding))
        assert len(pieces) == len(data) // file_crypto.CHUNK_SIZE + 1
        assert all(len(p) == file_crypto.CHUNK_SIZE for p in pieces[:-1])
        assert b"".join(pieces) == data

    def test_tampered_reordered_cut_or_moved_chunks_fail(self):
        from dedan_platform import file_crypto

        key, data = os.urandom(32), os.urandom(3 * 1024 + 10)
        blob = _encrypt_bytes(data, key, self.binding)
        head, block = file_crypto.HEADER.size, 12 + 1024 + 16
        chunks = [blob[head + i * block: head + (i + 1) * block] for i in range(4)]
        flipped = bytearray(blob)
        flipped[head + 40] ^= 1
        cases = {
            "tampered": bytes(flipped),
            "reordered": blob[:head] + chunks[1] + chunks[0] + chunks[2] + chunks[3],
            "cut at a chunk boundary": blob[:head] + b"".join(chunks[:3]),
            "cut inside a chunk": blob[:-5],
            "chunk dropped": blob[:head] + chunks[0] + chunks[2] + chunks[3],
        }
        for name, bad in cases.items():
            with pytest.raises(file_crypto.FileCryptoError):
                _decrypt_bytes(bad, key, self.binding)
        for other in (file_crypto.FileBinding("a" * 32, "d" * 32, "c" * 32),   # another file
                      file_crypto.FileBinding("a" * 32, "b" * 32, "e" * 32),   # another patient
                      file_crypto.FileBinding("f" * 32, "b" * 32, "c" * 32)):  # another record
            with pytest.raises(file_crypto.FileCryptoError):
                _decrypt_bytes(blob, key, other)
        with pytest.raises(file_crypto.FileCryptoError):
            _decrypt_bytes(blob, os.urandom(32), self.binding)

    def test_the_sha256_is_checked_before_anything_is_returned(self, tmp_path):
        from dedan_platform import file_crypto

        key, data = os.urandom(32), PDF
        path = tmp_path / "copy"
        path.write_bytes(_encrypt_bytes(data, key, self.binding))
        stream, size = file_crypto.open_verified(path, key_for_version=lambda v: key, binding=self.binding,
                                                 sha256=hashlib.sha256(data).hexdigest(), size=len(data))
        assert size == len(data) and b"".join(stream) == data
        with pytest.raises(file_crypto.FileCryptoError):
            file_crypto.open_verified(path, key_for_version=lambda v: key, binding=self.binding,
                                      sha256=hashlib.sha256(b"another file").hexdigest())
        with pytest.raises(file_crypto.FileCryptoError):
            file_crypto.open_verified(path, key_for_version=lambda v: key, binding=self.binding,
                                      sha256=hashlib.sha256(data).hexdigest(), size=len(data) + 1)
        # A copy from before encryption: read as it is, with the same check.
        plain = tmp_path / "legacy"
        plain.write_bytes(data)
        stream, _ = file_crypto.open_verified(plain, key_for_version=lambda v: key, binding=self.binding,
                                              sha256=hashlib.sha256(data).hexdigest())
        assert b"".join(stream) == data


def _publish_with_file(client, bus, patient, hospital_files, body=PDF, content_type="application/pdf",
                       filename="hiv-viral-load.pdf"):
    from dedan_platform import record_files

    meta = file_meta(body, content_type, filename=filename)
    record = lab_record(patient["dedan"], files=[meta])
    hospital_files[(record["record_id"], meta["file_id"])] = body
    from_hospital(bus, "record.published", record)
    run_worker(bus)
    assert record_files.download_due() == 1
    return record, meta


def _copy_path(record_id, file_id):
    from dedan_platform import record_files
    from dedan_platform.db import session_scope
    from dedan_platform.models import RecordFile

    with session_scope() as session:
        row = session.scalar(select(RecordFile).where(RecordFile.file_id == file_id))
        return record_files.stored_path(record_id, file_id, row.copy_id)


class TestStoredFiles:
    def test_downloads_are_encrypted_at_rest_and_served_decrypted(self, client, bus, patient, hospital_files):
        from dedan_platform import file_crypto

        record, meta = _publish_with_file(client, bus, patient, hospital_files)
        path = _copy_path(record["record_id"], meta["file_id"])
        stored = path.read_bytes()
        assert stored.startswith(file_crypto.MAGIC) and b"%PDF" not in stored
        resp = client.get(f"/users/me/history/records/{record['record_id']}/files/{meta['file_id']}",
                          headers=patient["auth"])
        assert resp.status_code == 200 and resp.content == PDF
        assert resp.headers["content-length"] == str(len(PDF))
        assert "hiv-viral-load.pdf" in resp.headers["content-disposition"]
        assert CIPHERTEXT.match(raw("record_files", "filename", _file_row_id(meta["file_id"])))

    def test_a_copy_that_fails_its_check_is_never_served(self, client, bus, patient, hospital_files):
        record, meta = _publish_with_file(client, bus, patient, hospital_files)
        path = _copy_path(record["record_id"], meta["file_id"])
        blob = bytearray(path.read_bytes())
        blob[-3] ^= 1
        path.write_bytes(bytes(blob))
        resp = client.get(f"/users/me/history/records/{record['record_id']}/files/{meta['file_id']}",
                          headers=patient["auth"])
        assert resp.status_code == 503 and b"%PDF" not in resp.content

    def test_the_sha256_is_verified_on_read(self, client, bus, patient, hospital_files):
        from dedan_platform.db import session_scope
        from dedan_platform.models import RecordFile

        record, meta = _publish_with_file(client, bus, patient, hospital_files)
        with session_scope() as session:  # as if the copy were of another file
            session.execute(update(RecordFile).where(RecordFile.file_id == meta["file_id"])
                            .values(sha256=hashlib.sha256(b"other").hexdigest()))
        resp = client.get(f"/users/me/history/records/{record['record_id']}/files/{meta['file_id']}",
                          headers=patient["auth"])
        assert resp.status_code == 503

    def test_the_hospital_gets_a_shared_file_decrypted(self, client, bus, patient, hospital_files):
        from test_patient_history import LISTING

        from_hospital(bus, "hospital.listed", LISTING)
        run_worker(bus)
        record, meta = _publish_with_file(client, bus, patient, hospital_files, body=PNG, content_type="image/png",
                                          filename="scan.png")
        share = client.post("/users/me/shares", headers=patient["auth"],
                            json={"hospital_id": HOSPITAL, "record_ids": [record["record_id"]]})
        assert share.status_code == 201, share.text
        resp = client.get(f"/internal/shares/{share.json()['share_id']}/files/{meta['file_id']}",
                          headers={"X-Platform-Key": KEY})
        assert resp.status_code == 200 and resp.content == PNG
        # The share's payload left the outbox; nothing of it stays.
        from dedan_platform import eventbus

        eventbus.publish_pending(bus)
        assert_not_stored("Complete blood count", "Hemoglobin", "scan.png")


def _file_row_id(file_id):
    from dedan_platform.db import session_scope
    from dedan_platform.models import RecordFile

    with session_scope() as session:
        return session.scalar(select(RecordFile.id).where(RecordFile.file_id == file_id))


# --- 5. no plaintext after the main flows ---------------------------------------------------------------------

class TestNothingClinicalInPlaintext:
    def test_a_hospital_record_received(self, client, bus, patient, hospital_files):
        record, meta = _publish_with_file(client, bus, patient, hospital_files)
        items = client.get("/users/me/history", headers=patient["auth"]).json()["items"]
        assert items[0]["title"] == "Complete blood count"
        assert items[0]["details"]["items"][0]["test"] == "Hemoglobin"
        assert items[0]["files"][0]["filename"] == "hiv-viral-load.pdf"
        inbox = client.get("/users/me/inbox", headers=patient["auth"]).json()["items"]
        assert any(i["body"] == "Complete blood count" for i in inbox)
        assert_not_stored("Complete blood count", "Hemoglobin", "reference_range", "hiv-viral-load")

    def test_a_follow_up_and_a_retraction(self, client, bus, patient):
        record = lab_record(patient["dedan"])
        from_hospital(bus, "record.published", record)
        from_hospital(bus, "visit.follow_up", {
            "visit_id": hexid(), "hospital_id": HOSPITAL, "hospital_name": "Zewditu Memorial Hospital",
            "dedan_id": patient["dedan"], "follow_up_on": (datetime.now(timezone.utc) + timedelta(days=9)).date()
            .isoformat(), "note": "Repeat the HbA1c test fasting", "doctor_name": "Dr. Hana"})
        from_hospital(bus, "record.retracted", {"record_id": record["record_id"], "hospital_id": HOSPITAL,
                                                "reason": "Entered for the wrong patient"})
        run_worker(bus)
        follow_ups = client.get("/users/me/follow-ups", headers=patient["auth"]).json()["follow_ups"]
        assert follow_ups[0]["note"] == "Repeat the HbA1c test fasting"
        assert_not_stored("HbA1c", "Complete blood count", "wrong patient")

    def test_a_self_reported_visit(self, client, patient):
        resp = client.post("/users/me/records", headers=patient["auth"], json={
            "occurred_at": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),
            "facility_name": "St. Paul's Hospital", "department": "Psychiatry",
            "diagnosis": "Major depressive disorder", "medications": [{"name": "Sertraline", "dose": "50 mg"}],
            "follow_up_days": 30, "follow_up_note": "Review the sertraline dose"})
        assert resp.status_code == 201, resp.text
        records = client.get("/users/me/records", headers=patient["auth"]).json()["records"]
        assert records[0]["diagnosis"] == "Major depressive disorder"
        assert records[0]["medications"] == [{"name": "Sertraline", "dose": "50 mg"}]
        assert_not_stored("depressive", "Sertraline", "Psychiatry", "St. Paul")

    def test_a_health_profile_saved(self, client, patient):
        resp = client.patch("/users/me/health-profile", headers=patient["auth"], json={
            "allergies": ["Penicillin"], "medications": ["Metformin 500 mg"], "conditions": ["Type 2 diabetes"],
            "blood_type": "AB-", "sex": "female", "age_range": "41-60"})
        assert resp.status_code == 200, resp.text
        profile = client.get("/users/me/health-profile", headers=patient["auth"]).json()
        assert profile["allergies"] == ["Penicillin"] and profile["blood_type"] == "AB-"
        assert profile["conditions"] == ["Type 2 diabetes"] and profile["medications"] == ["Metformin 500 mg"]
        assert_not_stored("Penicillin", "Metformin", "diabetes", "AB-")

    def test_an_appointment_with_symptoms_and_the_outbox(self, client, patient):
        from dedan_platform import eventbus
        from dedan_platform.db import session_scope

        when = (datetime.now(timezone.utc) + timedelta(days=5)).replace(microsecond=0).isoformat()
        resp = client.post("/users/me/appointments", headers=patient["auth"], json={
            "scheduled_at": when, "appointment_type": "consultation", "notes": "Blood in my urine since Monday",
            "location": "Clinic", "department": "Urology"})
        assert resp.status_code == 201, resp.text
        listed = client.get("/users/me/appointments", headers=patient["auth"]).json()
        assert "Blood in my urine since Monday" in json.dumps(listed)
        with session_scope() as session:  # an event carrying the notes, sent and purged
            eventbus.emit(session, "appointment.requested", {"notes": "Blood in my urine since Monday"})
        eventbus.publish_pending(fakeredis.FakeRedis(decode_responses=True))
        assert_not_stored("Blood in my urine", "Urology")

    def test_an_interview_completed(self, app_module, tmp_path, monkeypatch):
        from dedan_platform import db as dbmod

        monkeypatch.setenv("REALTIME_TOKEN_SECRET", "test-secret")
        monkeypatch.setenv("DEDAN_DATABASE_URL", f"sqlite:///{tmp_path / 'interview.db'}")
        dbmod.reset_engine()
        dbmod.create_all()
        try:
            api = TestClient(app_module.app)
            token = api.post("/auth/register", json={
                "first_name": "Almaz", "last_name": "B", "email": "almaz@example.com",
                "password": "Str0ng-pass!", "password_confirmation": "Str0ng-pass!"}).json()["access_token"]
            auth = {"Authorization": token}
            api.patch("/users/me/consent", headers=auth, json={"treatment_processing": True})
            api.patch("/users/me/health-profile", headers=auth, json={
                "age_range": "21-40", "allergies": ["Sulfa drugs"], "conditions": ["asthma"]})
            body = api.post("/users/me/consultations", headers=auth, json={
                "symptom_description": "I have crushing chest pain and can't breathe"}).json()
            assert body["safety"]["urgency"] == "emergency"
            events = api.get("/users/me/timeline", headers=auth).json()["events"]
            kinds = {e["event_type"] for e in events}
            assert {"AI_CONVERSATION", "SAFETY_ALERT"} <= kinds
            alert = next(e for e in events if e["event_type"] == "SAFETY_ALERT")
            assert alert["description"] == body["safety"]["emergency_message"]
            labels = [e["label"] for e in body.get("possible_explanations") or [] if e.get("label")]
            assert_not_stored("crushing chest pain", "Sulfa drugs", "asthma", "Emergency care recommended",
                              "Urgency: emergency", body["safety"]["emergency_message"][:40], *labels[:3])
        finally:
            dbmod.reset_engine()

    def test_a_prescription_is_still_served_to_a_pharmacy(self, client, bus, patient, monkeypatch):
        import main_internal

        from dedan_platform import prescriptions
        from dedan_platform.db import session_scope
        from dedan_platform.models import Prescription

        record_id = hexid()
        from_hospital(bus, "record.published", {
            "record_id": record_id, "version": 1, "hospital_id": HOSPITAL, "hospital_name": "Zewditu",
            "dedan_id": patient["dedan"], "category": "prescription", "title": "Chest infection",
            "details": {"items": [{"drug": "Amoxicillin", "dose": "500 mg", "quantity": "21 tablets"}],
                        "notes": "Finish the course"},
            "occurred_at": datetime.now(timezone.utc).isoformat(), "recorded_by": "Dr. Hiwot", "source": "portal"})
        run_worker(bus)
        with session_scope() as session:
            rx_id = session.scalar(select(Prescription.id).where(Prescription.record_id == record_id))
        monkeypatch.setenv("INTERNAL_ALLOWED_HOSTS", "testserver")
        pharmacy = TestClient(main_internal.create_app())
        headers = {"X-Pharmacy-Key": "pharmacy-test-key", "X-Client-IP": "196.188.1.10"}
        found = pharmacy.post("/pharmacy/lookup", json={"token": prescriptions.token_for(rx_id)}, headers=headers)
        assert found.status_code == 200, found.text
        item = found.json()["items"][0]
        assert (item["drug"], item["dose"], item["quantity_text"]) == ("Amoxicillin", "500 mg", "21 tablets")
        given = pharmacy.post("/pharmacy/dispense", headers=headers, json={
            "token": prescriptions.token_for(rx_id), "pharmacy_name": "Kenema", "pharmacist_name": "Sara",
            "items": [{"item_index": 0, "amount": 7, "complete": False}]})
        assert given.status_code == 200, given.text
        eventbus_publish(bus)
        assert_not_stored("Amoxicillin", "21 tablets", "Finish the course", "Chest infection")


def eventbus_publish(bus):
    from dedan_platform import eventbus

    eventbus.publish_pending(bus)


# --- 6. outbox --------------------------------------------------------------------------------------------------

class TestOutbox:
    def test_payloads_are_purged_once_sent_and_kept_until_then(self, client, bus):
        from dedan_platform import eventbus
        from dedan_platform.db import session_scope
        from dedan_platform.models import OutboxEvent

        with session_scope() as session:
            eventbus.emit(session, "records.shared", {"records": [{"title": "Schizophrenia"}]})
        with session_scope() as session:
            row = session.scalar(select(OutboxEvent))
            assert "Schizophrenia" in row.payload and row.published_at is None
        assert eventbus.publish_pending(bus) == 1
        sent = [json.loads(f["payload"]) for _id, f in bus.xrange("endod:patient")]
        assert sent == [{"records": [{"title": "Schizophrenia"}]}]
        with session_scope() as session:
            row = session.scalar(select(OutboxEvent))
            assert row.payload == eventbus.PURGED and row.published_at is not None

    def test_a_failed_send_keeps_the_payload(self, client):
        from dedan_platform import eventbus
        from dedan_platform.db import session_scope
        from dedan_platform.models import OutboxEvent

        class Down:
            def pipeline(self, transaction=False):
                raise ConnectionError("redis down")

        with session_scope() as session:
            eventbus.emit(session, "appointment.requested", {"notes": "Chest pain"})
        with pytest.raises(ConnectionError):
            eventbus.publish_pending(Down())
        with session_scope() as session:
            assert "Chest pain" in session.scalar(select(OutboxEvent.payload))

    def test_housekeeping_purges_rows_sent_before_purging_existed(self, client, bus):
        from dedan_platform import eventbus
        from dedan_platform.db import session_scope
        from dedan_platform.models import OutboxEvent

        with session_scope() as session:
            session.add(OutboxEvent(type="records.shared", payload='{"title": "Old"}',
                                    published_at=datetime.now(timezone.utc)))
            session.add(OutboxEvent(type="records.shared", payload='{"title": "Waiting"}'))
        eventbus.housekeeping(bus)
        with session_scope() as session:
            payloads = {r.payload for r in session.scalars(select(OutboxEvent))}
        assert payloads == {eventbus.PURGED, '{"title": "Waiting"}'}


# --- 7. one-off commands ------------------------------------------------------------------------------------------

def _legacy_data(client, patient, tmp_path):
    """Rows and a file as stored before encryption (plaintext)."""
    from dedan_platform.db import get_engine, session_scope
    from dedan_platform.models import HealthProfile, InboxItem, OutboxEvent, RecordFile, RecordFileStatus

    event = add_event(patient["id"], title="Neurology", description="Migraine with aura")
    for column, value in (("title", "Neurology"), ("description", "Migraine with aura"),
                          ("metadata_json", '{"record": {"diagnosis": "Migraine with aura"}}')):
        set_raw("health_events", column, event["event_id"], value)
    with session_scope() as session:
        profile_id = session.scalar(select(HealthProfile.id).where(HealthProfile.user_id == patient["id"]))
        session.add(OutboxEvent(type="records.shared", payload='{"title": "Migraine"}',
                                published_at=datetime.now(timezone.utc)))
    set_raw("health_profiles", "allergies", profile_id, "Aspirin")
    with get_engine().begin() as conn:
        conn.execute(InboxItem.__table__.insert().values(
            id=hexid(), user_id=patient["id"], category="records", kind="hospital_lab_result",
            title="New lab result", body="Migraine panel", created_at=datetime.now(timezone.utc)))
    record_id, file_id, copy_id = hexid(), hexid(), "0123456789abcdef"
    with get_engine().begin() as conn:
        conn.execute(RecordFile.__table__.insert().values(
            id=hexid(), record_id=record_id, file_id=file_id, user_id=patient["id"], filename="mri-brain.pdf",
            content_type="application/pdf", size=len(PDF), sha256=hashlib.sha256(PDF).hexdigest(),
            status=RecordFileStatus.STORED, attempts=1, next_attempt_at=datetime.now(timezone.utc),
            copy_id=copy_id, updated_at=datetime.now(timezone.utc)))
    path = tmp_path / "records" / record_id / f"{file_id}.{copy_id}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(PDF)
    return {"event": event["event_id"], "profile": profile_id, "record": record_id, "file": file_id, "path": path}


class TestCommands:
    def test_check_reports_plaintext_and_encrypt_existing_is_idempotent(self, client, patient, tmp_path):
        from dedan_platform import tools

        legacy = _legacy_data(client, patient, tmp_path)
        report = tools.check(out=lambda _line: None)
        assert report["health_events.description"] == 1 and report["health_profiles.allergies"] == 1
        assert report["inbox_items.body"] == 1 and report["record files"] == 1
        assert report["outbox_events.payload (sent)"] == 1
        assert tools.main(["check"]) == 1

        first = tools.encrypt_existing(out=lambda _line: None)
        assert first["health_events.description"] == 1 and first["record files"] == 1
        assert not any(tools.check(out=lambda _line: None).values())
        assert tools.main(["check"]) == 0
        assert_not_stored("Migraine", "Aspirin", "Neurology", "mri-brain")
        stored = raw_values()

        second = tools.encrypt_existing(out=lambda _line: None)
        assert not any(second.values())
        assert raw_values() == stored  # nothing rewritten

        # Everything still reads as before.
        assert load_event(legacy["event"])[:2] == ("Neurology", "Migraine with aura")
        profile = client.get("/users/me/health-profile", headers=patient["auth"]).json()
        assert profile["allergies"] == ["Aspirin"]
        resp = client.get(f"/users/me/history/records/{legacy['record']}/files/{legacy['file']}",
                          headers=patient["auth"])
        assert not legacy["path"].exists()  # replaced by an encrypted copy, which holds the same file
        from test_patient_history import plaintext

        assert plaintext(_copy_path(legacy["record"], legacy["file"])) == PDF
        # (no hospital record row for this file: the endpoint correctly refuses it)
        assert resp.status_code == 404

    def test_encrypt_existing_never_overwrites_a_concurrent_change(self, client, patient, monkeypatch):
        from dedan_platform import tools

        event = add_event(patient["id"])
        set_raw("health_events", "description", event["event_id"], "Old plaintext")
        real = tools._encrypt

        def meanwhile(conn, keys, table, column, row_id, user_id, plaintext):
            sealed = real(conn, keys, table, column, row_id, user_id, plaintext)
            if column.name == "description":
                conn.execute(table.update().where(table.c.id == row_id).values(description="Changed meanwhile"))
            return sealed

        monkeypatch.setattr(tools, "_encrypt", meanwhile)
        tools.encrypt_existing(out=lambda _line: None)
        assert raw("health_events", "description", event["event_id"]) == "Changed meanwhile"

    def test_rotate_key(self, client, bus, patient, hospital_files):
        from dedan_platform import crypto, file_crypto, tools
        from dedan_platform.db import session_scope
        from dedan_platform.models import UserKey

        other = register(client, email="b@example.com", phone=None)
        theirs = add_event(other["id"], description="Gout")
        their_raw = raw("health_events", "description", theirs["event_id"])
        record, meta = _publish_with_file(client, bus, patient, hospital_files)
        mine = add_event(patient["id"], description="Hepatitis B")
        client.patch("/users/me/health-profile", headers=patient["auth"], json={"allergies": ["Latex"]})
        assert crypto.key_version(raw("health_events", "description", mine["event_id"])) == 1

        assert tools.main(["rotate-key", "--user", patient["dedan"]]) == 0
        for (table, column), rows in raw_values().items():
            for _row_id, user_id, value in rows:
                if user_id == patient["id"]:
                    assert crypto.key_version(value) == 2, f"{table}.{column}"
        with open(_copy_path(record["record_id"], meta["file_id"]), "rb") as handle:
            assert file_crypto.read_header(handle) == 2
        with session_scope() as session:
            keys = {(k.user_id, k.version): k.active for k in session.scalars(select(UserKey))}
        assert keys == {(patient["id"], 1): False, (patient["id"], 2): True, (other["id"], 1): True}
        # Still readable, and the other patient is untouched.
        assert load_event(mine["event_id"])[1] == "Hepatitis B"
        assert client.get("/users/me/health-profile", headers=patient["auth"]).json()["allergies"] == ["Latex"]
        resp = client.get(f"/users/me/history/records/{record['record_id']}/files/{meta['file_id']}",
                          headers=patient["auth"])
        assert resp.status_code == 200 and resp.content == PDF
        assert raw("health_events", "description", theirs["event_id"]) == their_raw
        # New data uses the new key at once.
        assert crypto.key_version(raw("health_events", "description",
                                      add_event(patient["id"])["event_id"])) == 2

        # The old key goes only once nothing uses it.
        assert tools.main(["rotate-key", "--user", patient["id"], "--purge-old"]) == 0
        with session_scope() as session:
            versions = sorted(k.version for k in session.scalars(select(UserKey).where(
                UserKey.user_id == patient["id"])))
        assert versions == [3]
        assert load_event(mine["event_id"])[1] == "Hepatitis B"
        assert tools.main(["rotate-key", "--user", "DE000000"]) == 2

    def test_decrypt_existing_for_a_rollback(self, client, bus, patient, hospital_files):
        from dedan_platform import file_crypto, tools

        record, meta = _publish_with_file(client, bus, patient, hospital_files)
        event = add_event(patient["id"], description="Hepatitis B")
        assert tools.main(["decrypt-existing"]) == 2  # refused without --yes
        assert CIPHERTEXT.match(raw("health_events", "description", event["event_id"]))
        assert tools.main(["decrypt-existing", "--yes"]) == 0
        # What a release from before encryption reads: plaintext values and files.
        assert raw("health_events", "description", event["event_id"]) == "Hepatitis B"
        assert raw("hospital_records", "title", record["record_id"]) == "Complete blood count"
        path = _copy_path(record["record_id"], meta["file_id"])
        assert path.read_bytes() == PDF
        with open(path, "rb") as handle:
            assert file_crypto.read_header(handle) is None
        # ... and encrypting again restores the encrypted state.
        tools.encrypt_existing(out=lambda _line: None)
        assert not any(tools.check(out=lambda _line: None).values())

    def test_purge_old_refuses_while_the_old_key_is_still_used(self, client, patient, monkeypatch):
        from dedan_platform import tools
        from dedan_platform.db import session_scope
        from dedan_platform.models import UserKey

        add_event(patient["id"])
        monkeypatch.setattr(tools, "_old_values", lambda user_id, version: 1)  # written meanwhile
        assert tools.rotate_key(patient["id"], purge_old=True, out=lambda _line: None) == 1
        with session_scope() as session:
            assert session.scalar(select(UserKey).where(UserKey.user_id == patient["id"], UserKey.version == 1))
