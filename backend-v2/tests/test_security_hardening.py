"""Security and data-integrity fixes from the backend review."""

import io
import struct
import zlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

PASSWORD = "Str0ng-pass!"


@pytest.fixture
def platform(tmp_path, monkeypatch):
    from dedan_platform import credentials
    from dedan_platform import db as dbmod
    from dedan_platform.api_auth import router as auth_router
    from dedan_platform.api_care import router as care_router
    from dedan_platform.api_health import router as health_router
    from dedan_platform.api_profile import router as profile_router

    monkeypatch.setenv("REALTIME_TOKEN_SECRET", "test-secret")
    monkeypatch.setenv("DEDAN_DATABASE_URL", f"sqlite:///{tmp_path / 'hardening.db'}")
    # Distinct callers are told apart by X-Forwarded-For in these tests.
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")
    monkeypatch.setattr(credentials, "_throttle", credentials._LoginThrottle())
    dbmod.reset_engine()
    dbmod.create_all()
    app = FastAPI()
    for router in (auth_router, profile_router, health_router, care_router):
        app.include_router(router)
    yield TestClient(app)
    dbmod.reset_engine()


def register(client, email="abebe@example.com"):
    resp = client.post(
        "/auth/register",
        json={
            "first_name": "Abebe",
            "last_name": "Kebede",
            "email": email,
            "password": PASSWORD,
            "password_confirmation": PASSWORD,
        },
    )
    return resp


def auth(token):
    return {"Authorization": token}


class TestUniqueEmail:
    def test_duplicate_registration_is_409(self, platform):
        assert register(platform).status_code == 201
        assert register(platform, email="ABEBE@example.com").status_code == 409

    def test_cannot_take_another_accounts_email(self, platform):
        register(platform, "victim@example.com")
        token = register(platform, "attacker@example.com").json()["access_token"]
        resp = platform.patch("/users/me", headers=auth(token), json={"email": "Victim@Example.com"})
        assert resp.status_code == 409

    def test_wrong_types_are_400_not_500(self, platform):
        token = register(platform).json()["access_token"]
        assert platform.patch("/users/me", headers=auth(token), json={"email": {"x": 1}}).status_code == 400
        assert platform.patch("/users/me", headers=auth(token), json={"timezone": "Mars/Base"}).status_code == 400
        assert platform.patch("/users/me", headers=auth(token), json={"locale": "x" * 50}).status_code == 400

    def test_valid_profile_update(self, platform):
        token = register(platform).json()["access_token"]
        resp = platform.patch(
            "/users/me",
            headers=auth(token),
            json={"timezone": "Africa/Addis_Ababa", "country_code": "et"},
        )
        assert resp.status_code == 200, resp.text


class TestConsent:
    SUMMARY = {"main_concern": "Headache for three days", "allergies": ["penicillin"], "medications": ["warfarin"]}

    def test_summary_requires_treatment_consent(self, platform):
        token = register(platform).json()["access_token"]
        resp = platform.post("/users/me/handoff/summary", headers=auth(token), json=self.SUMMARY)
        assert resp.status_code == 403

    def test_share_requires_clinician_sharing_consent(self, platform):
        token = register(platform).json()["access_token"]
        platform.patch("/users/me/consent", headers=auth(token), json={"treatment_processing": True})
        summary = platform.post("/users/me/handoff/summary", headers=auth(token), json=self.SUMMARY)
        assert summary.status_code == 201, summary.text
        body = summary.json()
        share = {"handoff_id": body["handoff_id"], "fingerprint": body["fingerprint"]}

        assert platform.post("/users/me/handoff/share", headers=auth(token), json=share).status_code == 403

        platform.patch("/users/me/consent", headers=auth(token), json={"data_sharing_with_clinicians": True})
        assert platform.post("/users/me/handoff/share", headers=auth(token), json=share).status_code == 200


class TestLoginThrottling:
    def _login(self, client, identifier, password, ip):
        return client.post(
            "/auth/login",
            json={"identifier": identifier, "password": password},
            headers={"X-Forwarded-For": ip},
        )

    def test_attacker_cannot_lock_the_patient_out(self, platform):
        dedan_id = register(platform).json()["dedan_user_id"]
        for _ in range(8):
            self._login(platform, dedan_id, "wrong-password", "10.0.0.66")
        assert self._login(platform, dedan_id, "wrong-password", "10.0.0.66").status_code == 429
        # The patient, from their own device, still signs in.
        assert self._login(platform, dedan_id, PASSWORD, "10.0.0.7").status_code == 200

    def test_unknown_ids_are_throttled_identically(self, platform):
        real = register(platform).json()["dedan_user_id"]
        fake = "DE000001" if real != "DE000001" else "DE000002"
        real_codes = [self._login(platform, real, "nope", "10.1.1.1").status_code for _ in range(9)]
        fake_codes = [self._login(platform, fake, "nope", "10.1.1.2").status_code for _ in range(9)]
        assert real_codes == fake_codes
        assert real_codes[-1] == 429


def _png(width, height):
    """A tiny file whose header declares ``width`` x ``height`` pixels."""
    raw = b"\x00" * (width + 1)  # one row; the header is what is checked
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


class TestImageUploads:
    @pytest.fixture
    def service(self, tmp_path):
        from app.core.config import get_settings
        from image_service import ImageService

        settings = get_settings().model_copy(update={"IMAGE_STORAGE_PATH": str(tmp_path)})
        return ImageService(settings)

    def test_decompression_bomb_is_rejected_from_the_header(self, service):
        from image_service import ImageValidationError

        with pytest.raises(ImageValidationError, match="dimensions too large"):
            service.validate_and_store(_png(12000, 12000), "bomb.png")

    def test_filename_does_not_decide_the_type(self, service):
        from image_service import ImageValidationError

        with pytest.raises(ImageValidationError, match="Unsupported file type"):
            service.validate_and_store(b"BM" + b"\x00" * 4000, "photo.jpg")

    def test_stored_extension_comes_from_the_content(self, service):
        from PIL import Image

        buffer = io.BytesIO()
        Image.effect_noise((300, 300), 64).convert("RGB").save(buffer, "JPEG")
        result = service.validate_and_store(buffer.getvalue(), "photo.pdf")
        stored = service.get_metadata(result.image_id)["stored_filename"]
        assert stored.endswith(".jpg")


class TestAppointments:
    def _book(self, client, token, when, **extra):
        return client.post(
            "/users/me/appointments",
            headers=auth(token),
            json={"scheduled_at": when.isoformat(), **extra},
        )

    def test_can_reschedule_more_than_once(self, platform):
        token = register(platform).json()["access_token"]
        soon = datetime.now(timezone.utc) + timedelta(days=3)
        appointment_id = self._book(platform, token, soon).json()["appointment"]["appointment_id"]
        for days in (4, 5):
            resp = platform.post(
                f"/users/me/appointments/{appointment_id}/reschedule",
                headers=auth(token),
                json={"scheduled_at": (soon + timedelta(days=days)).isoformat()},
            )
            assert resp.status_code == 200, resp.text

    def test_past_dates_are_rejected(self, platform):
        token = register(platform).json()["access_token"]
        resp = self._book(platform, token, datetime(2001, 1, 1, tzinfo=timezone.utc))
        assert resp.status_code == 400

    def test_javascript_meeting_url_is_rejected(self, platform):
        token = register(platform).json()["access_token"]
        when = datetime.now(timezone.utc) + timedelta(days=3)
        resp = self._book(platform, token, when, meeting_url="javascript:alert(1)")
        assert resp.status_code == 400


class TestSmtp:
    def test_starttls_verifies_the_certificate(self, monkeypatch):
        import smtplib
        import ssl

        from dedan_platform import email_provider

        seen = {}

        class FakeSMTP:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def starttls(self, context=None):
                seen["context"] = context

            def login(self, *args):
                pass

            def send_message(self, message):
                pass

        monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
        monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("SMTP_TLS", "true")
        provider = email_provider.SmtpEmailProvider()
        provider.send("patient@example.com", "Reminder", "Body")
        assert isinstance(seen["context"], ssl.SSLContext)
        assert seen["context"].verify_mode == ssl.CERT_REQUIRED
        assert seen["context"].check_hostname is True
