"""Phone sign-up, sign-in and password reset with SMS codes."""

import re
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dedan_platform.phone import normalise_ethiopian_mobile

PASSWORD = "Str0ng-pass!"
PHONE = "0911 234 567"
E164 = "+251911234567"


class FakeSms:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def send(self, phone, text):
        from dedan_platform.sms_provider import SmsProviderError

        if self.fail:
            raise SmsProviderError("gateway down")
        self.sent.append((phone, text))
        return "msg-1"

    def last_code(self):
        return re.search(r"\b(\d{6})\b", self.sent[-1][1]).group(1)


@pytest.fixture
def sms(monkeypatch):
    from dedan_platform import phone_auth

    fake = FakeSms()
    monkeypatch.setattr(phone_auth, "build_provider", lambda: fake)
    return fake


@pytest.fixture
def client(tmp_path, monkeypatch, sms):
    from dedan_platform import credentials, phone_auth
    from dedan_platform import db as dbmod
    from dedan_platform.api_auth import router as auth_router
    from dedan_platform.api_profile import router as profile_router

    monkeypatch.setenv("REALTIME_TOKEN_SECRET", "test-secret")
    monkeypatch.setenv("DEDAN_DATABASE_URL", f"sqlite:///{tmp_path / 'phone.db'}")
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "true")
    monkeypatch.setattr(credentials, "_throttle", credentials._LoginThrottle())
    monkeypatch.setattr(phone_auth, "OTP_MAX_PER_CLIENT_PER_HOUR", 10)
    dbmod.reset_engine()
    dbmod.create_all()
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(profile_router)
    yield TestClient(app)
    dbmod.reset_engine()


def request_code(client, phone=PHONE, ip="10.0.0.1"):
    return client.post("/auth/phone/request-code", json={"phone": phone}, headers={"X-Forwarded-For": ip})


def verify(client, code, phone=PHONE):
    return client.post("/auth/phone/verify", json={"phone": phone, "code": code})


def complete(client, token, password=PASSWORD, **extra):
    return client.post(
        "/auth/phone/complete",
        json={"verification_token": token, "password": password, "password_confirmation": password, **extra},
    )


def sign_up(client, sms, phone=PHONE, **extra):
    assert request_code(client, phone).status_code == 202
    token = verify(client, sms.last_code(), phone).json()["verification_token"]
    resp = complete(client, token, **extra)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _age_codes(seconds):
    """Move every stored code `seconds` into the past (cooldowns, expiry)."""
    from sqlalchemy import update

    from dedan_platform.db import session_scope
    from dedan_platform.models import PhoneVerification

    with session_scope() as session:
        for row in session.query(PhoneVerification).all():
            session.execute(
                update(PhoneVerification)
                .where(PhoneVerification.id == row.id)
                .values(
                    created_at=row.created_at - timedelta(seconds=seconds),
                    expires_at=row.expires_at - timedelta(seconds=seconds),
                )
            )


class TestNormalisation:
    @pytest.mark.parametrize(
        "raw", ["0911234567", "911234567", "251911234567", "+251 911 234 567", "(0911) 234-567"]
    )
    def test_ethio_telecom_forms(self, raw):
        assert normalise_ethiopian_mobile(raw) == E164

    def test_safaricom_ethiopia(self):
        assert normalise_ethiopian_mobile("0711234567") == "+251711234567"

    @pytest.mark.parametrize("raw", ["", "12345", "0811234567", "+254711234567", "09112345678", "abc"])
    def test_rejects(self, raw):
        assert normalise_ethiopian_mobile(raw) is None


class TestSignUpFlow:
    def test_full_signup_then_profile(self, client, sms):
        result = sign_up(client, sms, first_name="Abebe", last_name="Kebede")
        assert result["created"] is True
        profile = client.get("/users/me", headers={"Authorization": result["access_token"]}).json()
        assert profile["phone"] == E164
        assert profile["phone_verified"] is True
        assert profile["display_name"] == "Abebe Kebede"

    def test_sms_text_and_destination(self, client, sms):
        request_code(client)
        phone, text = sms.sent[-1]
        assert phone == E164
        assert "verification code" in text and "Do not share" in text

    def test_sign_in_with_phone_in_any_format(self, client, sms):
        sign_up(client, sms)
        for identifier in ("0911234567", E164, "911 234 567"):
            resp = client.post("/auth/login", json={"identifier": identifier, "password": PASSWORD})
            assert resp.status_code == 200, (identifier, resp.text)

    def test_request_is_identical_for_new_and_existing_numbers(self, client, sms):
        sign_up(client, sms)
        _age_codes(120)
        existing = request_code(client, PHONE, ip="10.0.0.2")
        new = request_code(client, "0922 000 111", ip="10.0.0.3")
        assert existing.status_code == new.status_code == 202
        assert existing.json() == new.json()

    def test_invalid_phone_is_400(self, client):
        assert request_code(client, "12345").status_code == 400


class TestCodeChecks:
    def test_code_is_not_stored_in_plain_text(self, client, sms):
        from dedan_platform.db import session_scope
        from dedan_platform.models import PhoneVerification

        request_code(client)
        with session_scope() as session:
            row = session.query(PhoneVerification).one()
            assert sms.last_code() not in row.code_hash

    def test_wrong_code(self, client, sms):
        request_code(client)
        wrong = "000000" if sms.last_code() != "000000" else "111111"
        assert verify(client, wrong).status_code == 400

    def test_five_wrong_guesses_lock_the_code(self, client, sms):
        request_code(client)
        right = sms.last_code()
        wrong = "000000" if right != "000000" else "111111"
        for _ in range(5):
            verify(client, wrong)
        resp = verify(client, right)
        assert resp.status_code == 400
        assert "Too many" in resp.json()["detail"]

    def test_expired_code(self, client, sms):
        request_code(client)
        _age_codes(6 * 60)
        resp = verify(client, sms.last_code())
        assert resp.status_code == 400
        assert "expired" in resp.json()["detail"]

    def test_no_code_requested(self, client):
        assert verify(client, "123456").status_code == 400


class TestRateLimits:
    def test_resend_cooldown(self, client, sms):
        assert request_code(client).status_code == 202
        resp = request_code(client)
        assert resp.status_code == 429
        assert int(resp.headers["retry-after"]) > 0

    def test_hourly_cap_per_phone(self, client, sms):
        for i in range(5):
            assert request_code(client, ip=f"10.1.0.{i}").status_code == 202
            _age_codes(61)
        assert request_code(client, ip="10.1.0.99").status_code == 429

    def test_cap_per_client(self, client, sms):
        for i in range(10):
            assert request_code(client, f"09{i:02d}000000"[:10], ip="10.7.7.7").status_code == 202
        assert request_code(client, "0933333333", ip="10.7.7.7").status_code == 429

    def test_failed_send_is_503_and_not_counted(self, client, sms):
        sms.fail = True
        assert request_code(client).status_code == 503
        sms.fail = False
        assert request_code(client).status_code == 202


class TestVerificationToken:
    def test_single_use(self, client, sms):
        request_code(client)
        token = verify(client, sms.last_code()).json()["verification_token"]
        assert complete(client, token).status_code == 200
        assert complete(client, token).status_code == 401

    def test_is_not_a_session(self, client, sms):
        request_code(client)
        token = verify(client, sms.last_code()).json()["verification_token"]
        assert client.get("/users/me", headers={"Authorization": token}).status_code == 401

    def test_forged_token(self, client):
        assert complete(client, "v1.not.real").status_code == 401

    def test_session_token_cannot_complete(self, client, sms):
        session_token = sign_up(client, sms)["access_token"]
        assert complete(client, session_token).status_code == 401

    def test_weak_password_does_not_burn_the_verification(self, client, sms):
        request_code(client)
        token = verify(client, sms.last_code()).json()["verification_token"]
        assert complete(client, token, password="short").status_code == 400
        assert complete(client, token).status_code == 200


class TestPasswordReset:
    def test_existing_phone_resets_password_and_signs_out_old_sessions(self, client, sms):
        import time

        old_session = sign_up(client, sms)["access_token"]
        time.sleep(1.1)  # token iat has whole-second precision
        _age_codes(120)
        request_code(client, ip="10.0.0.9")
        verified = verify(client, sms.last_code()).json()
        assert verified["account_exists"] is True
        resp = complete(client, verified["verification_token"], password="N3w-Str0ng-pass!")
        assert resp.status_code == 200 and resp.json()["created"] is False
        assert client.get("/users/me", headers={"Authorization": old_session}).status_code == 401
        login = client.post("/auth/login", json={"identifier": PHONE, "password": "N3w-Str0ng-pass!"})
        assert login.status_code == 200


class TestProfilePhoneChanges:
    def test_changing_phone_removes_verification(self, client, sms):
        token = sign_up(client, sms)["access_token"]
        resp = client.patch("/users/me", headers={"Authorization": token}, json={"phone": "0922 111 222"})
        assert resp.json()["phone_verified"] is False
        login = client.post("/auth/login", json={"identifier": "0922111222", "password": PASSWORD})
        assert login.status_code == 401

    def test_resaving_same_number_keeps_verification(self, client, sms):
        token = sign_up(client, sms)["access_token"]
        resp = client.patch("/users/me", headers={"Authorization": token}, json={"phone": "0911234567"})
        assert resp.json()["phone_verified"] is True

    def test_cannot_take_over_someone_elses_number(self, client, sms):
        sign_up(client, sms)  # victim owns 0911 234 567
        attacker = client.post("/auth/register", json={
            "first_name": "M", "last_name": "X", "email": "m@example.com",
            "password": PASSWORD, "password_confirmation": PASSWORD,
        }).json()["access_token"]
        client.patch("/users/me", headers={"Authorization": attacker}, json={"phone": PHONE})
        # Signing in with the number still reaches only the verified owner.
        login = client.post("/auth/login", json={"identifier": PHONE, "password": PASSWORD})
        assert login.status_code == 200
        me = client.get("/users/me", headers={"Authorization": login.json()["access_token"]}).json()
        assert me["email"] is None  # the victim, not the attacker


class TestSmsEthiopiaProvider:
    def _provider(self):
        from dedan_platform.sms_provider import SmsEthiopiaProvider

        return SmsEthiopiaProvider("secret-key", url="https://sms.example/send")

    def _fake_post(self, monkeypatch, status, body):
        import httpx

        calls = {}

        def post(url, headers, json, timeout):
            calls.update(url=url, headers=headers, json=json)
            return httpx.Response(status, json=body, request=httpx.Request("POST", url))

        monkeypatch.setattr(httpx, "post", post)
        return calls

    def test_request_shape(self, monkeypatch):
        calls = self._fake_post(monkeypatch, 200, {"success": True, "message_id": "abc"})
        assert self._provider().send(E164, "hello") == "abc"
        assert calls["headers"]["KEY"] == "secret-key"
        assert calls["json"] == {"msisdn": "251911234567", "text": "hello"}

    def test_http_error_raises(self, monkeypatch):
        from dedan_platform.sms_provider import SmsProviderError

        self._fake_post(monkeypatch, 401, {"message": "invalid key"})
        with pytest.raises(SmsProviderError):
            self._provider().send(E164, "hello")

    def test_failure_reported_in_a_200_body_raises(self, monkeypatch):
        from dedan_platform.sms_provider import SmsProviderError

        self._fake_post(monkeypatch, 200, {"success": False, "message": "insufficient balance"})
        with pytest.raises(SmsProviderError):
            self._provider().send(E164, "hello")

    def test_production_without_key_fails_closed(self, monkeypatch):
        from dedan_platform.sms_provider import SmsNotConfiguredError, build_provider

        monkeypatch.delenv("SMSETHIOPIA_API_KEY", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "production")
        with pytest.raises(SmsNotConfiguredError):
            build_provider()


class TestReviewFindings:
    """Automated review (Qodo) of PR #4."""

    def test_older_code_is_retired_by_a_resend(self, client, sms):
        request_code(client)
        first = sms.last_code()
        _age_codes(61)
        request_code(client, ip="10.0.0.2")
        second = sms.last_code()
        assert verify(client, second).status_code == 200
        if first != second:
            assert verify(client, first).status_code == 400

    def test_code_is_recorded_before_the_sms_is_sent(self, client, sms, monkeypatch):
        from dedan_platform.db import session_scope
        from dedan_platform.models import PhoneVerification

        seen = {}
        original = sms.send

        def send(phone, text):
            with session_scope() as session:
                seen["rows"] = session.query(PhoneVerification).count()
            return original(phone, text)

        monkeypatch.setattr(sms, "send", send)
        request_code(client)
        assert seen["rows"] == 1

    def test_concurrent_request_during_a_send_hits_the_cooldown(self, client, sms, monkeypatch):
        from dedan_platform import phone_auth

        nested = {}
        original = sms.send

        def send(phone, text):
            if "done" not in nested:
                nested["done"] = True
                try:
                    phone_auth.request_code(PHONE, client="10.5.5.5")
                except phone_auth.TooManyRequests:
                    nested["blocked"] = True
            return original(phone, text)

        monkeypatch.setattr(sms, "send", send)
        assert request_code(client).status_code == 202
        assert nested.get("blocked") is True
        assert len(sms.sent) == 1

    def test_phone_collision_is_classified_as_phone(self):
        from sqlalchemy.exc import IntegrityError

        from dedan_platform import identity

        class Session:
            def flush(self):
                raise IntegrityError(
                    "INSERT INTO profiles (email, phone) VALUES (?, ?)", {},
                    Exception("UNIQUE constraint failed: profiles.phone"),
                )

        with pytest.raises(identity.PhoneInUse):
            identity._flush_checking_email(Session())

    def test_deactivated_account_cannot_reset_by_phone(self, client, sms):
        from sqlalchemy import update

        from dedan_platform.db import session_scope
        from dedan_platform.models import User

        sign_up(client, sms)
        with session_scope() as session:
            session.execute(update(User).values(is_active=False))
        _age_codes(120)
        request_code(client, ip="10.0.0.8")
        token = verify(client, sms.last_code()).json()["verification_token"]
        assert complete(client, token).status_code == 403

    def test_email_patient_links_phone_without_a_second_account(self, client, sms):
        signup = client.post("/auth/register", json={
            "first_name": "E", "last_name": "P", "email": "e@example.com",
            "password": PASSWORD, "password_confirmation": PASSWORD, "phone": PHONE,
        }).json()
        request_code(client)
        token = verify(client, sms.last_code()).json()["verification_token"]
        resp = client.post("/users/me/phone", headers={"Authorization": signup["access_token"]},
                           json={"verification_token": token})
        assert resp.status_code == 200, resp.text
        assert resp.json()["phone_verified"] is True
        login = client.post("/auth/login", json={"identifier": PHONE, "password": PASSWORD})
        assert login.json()["dedan_user_id"] == signup["dedan_user_id"]

    def test_cannot_link_a_number_another_account_signs_in_with(self, client, sms):
        sign_up(client, sms)  # owner
        other = client.post("/auth/register", json={
            "first_name": "O", "last_name": "X", "email": "o@example.com",
            "password": PASSWORD, "password_confirmation": PASSWORD,
        }).json()["access_token"]
        _age_codes(120)
        request_code(client, ip="10.0.0.6")
        token = verify(client, sms.last_code()).json()["verification_token"]
        resp = client.post("/users/me/phone", headers={"Authorization": other},
                           json={"verification_token": token})
        assert resp.status_code == 409
