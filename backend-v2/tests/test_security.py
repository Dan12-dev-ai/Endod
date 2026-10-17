"""Tests for session tokens, HTTP hardening and router mounting."""

import base64
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.security import (
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    normalize_token,
)
from realtime import auth
from dedan_platform.languages import SUPPORTED_LANGUAGES


@pytest.fixture
def secret(monkeypatch):
    monkeypatch.setenv("REALTIME_TOKEN_SECRET", "test-secret")
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)


class TestTokens:
    def test_round_trip(self, secret):
        token = auth.issue_token("DE123456", expires_in=60, scope="portal")
        assert auth.identity_from_token(token) == "DE123456"
        payload = auth.decode_token(token)
        assert payload["scope"] == "portal"
        assert payload["exp"] - payload["iat"] == 60

    def test_tampered_payload_is_rejected(self, secret):
        token = auth.issue_token("DE123456", expires_in=60)
        version, _, signature = token.split(".")
        forged = base64.urlsafe_b64encode(
            json.dumps({"sub": "DE999999", "iat": int(time.time()), "exp": int(time.time()) + 60}).encode()
        ).rstrip(b"=").decode()
        with pytest.raises(auth.AuthError):
            auth.identity_from_token(f"{version}.{forged}.{signature}")

    def test_other_secret_is_rejected(self, secret, monkeypatch):
        token = auth.issue_token("DE123456", expires_in=60)
        monkeypatch.setenv("REALTIME_TOKEN_SECRET", "another-secret")
        with pytest.raises(auth.AuthError):
            auth.identity_from_token(token)

    def test_expired_token_is_rejected(self, secret, monkeypatch):
        token = auth.issue_token("DE123456", expires_in=60)
        real_time = time.time
        monkeypatch.setattr(auth.time, "time", lambda: real_time() + 61)
        with pytest.raises(auth.AuthError):
            auth.identity_from_token(token)

    @pytest.mark.parametrize("token", [None, "", "garbage", "v1.a.b", "v2.a.b", "v1..."])
    def test_malformed_tokens_are_rejected(self, secret, token):
        with pytest.raises(auth.AuthError):
            auth.identity_from_token(token)

    def test_no_secret_refuses_to_mint(self, monkeypatch):
        monkeypatch.delenv("REALTIME_TOKEN_SECRET", raising=False)
        monkeypatch.delenv("ADMIN_API_KEY", raising=False)
        with pytest.raises(auth.AuthError):
            auth.issue_token("DE123456")

    def test_admin_key_is_the_fallback_secret(self, monkeypatch):
        monkeypatch.delenv("REALTIME_TOKEN_SECRET", raising=False)
        monkeypatch.setenv("ADMIN_API_KEY", "admin-secret")
        assert auth.identity_from_token(auth.issue_token("DE123456")) == "DE123456"


class TestNormalizeToken:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("abc", "abc"),
            ("Bearer abc", "abc"),
            ("bearer  abc ", "abc"),
            ("DEDAN abc", "abc"),
            ("", None),
            (None, None),
            ("Bearer ", None),
        ],
    )
    def test_schemes(self, value, expected):
        assert normalize_token(value) == expected


class TestLanguages:
    def test_languages_include_english_and_amharic(self):
        assert SUPPORTED_LANGUAGES[0] == "en"
        assert "am" in SUPPORTED_LANGUAGES


def _app_with(*middleware):
    app = FastAPI()

    @app.post("/echo")
    async def echo(payload: dict):
        return payload

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    for cls, kwargs in middleware:
        app.add_middleware(cls, **kwargs)
    return app


class TestHttpHardening:
    def test_oversized_body_is_413(self):
        client = TestClient(_app_with((BodySizeLimitMiddleware, {"max_bytes": 100})))
        resp = client.post("/echo", json={"data": "x" * 500})
        assert resp.status_code == 413
        assert resp.json()["error_code"] == "PAYLOAD_TOO_LARGE"

    def test_small_body_passes(self):
        client = TestClient(_app_with((BodySizeLimitMiddleware, {"max_bytes": 100})))
        assert client.post("/echo", json={"a": 1}).json() == {"a": 1}

    def test_security_headers_are_set(self):
        client = TestClient(_app_with((SecurityHeadersMiddleware, {})))
        headers = client.get("/ping").headers
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"

    def test_rate_limit_blocks_after_the_limit(self):
        client = TestClient(
            _app_with((RateLimitMiddleware, {"requests_per_window": 2, "window_seconds": 60}))
        )
        assert client.get("/ping").status_code == 200
        assert client.get("/ping").status_code == 200
        resp = client.get("/ping")
        assert resp.status_code == 429
        assert resp.headers["retry-after"] == "60"

    def test_rate_limit_tracking_is_bounded(self, monkeypatch):
        import app.core.security as security

        monkeypatch.setattr(security, "MAX_TRACKED_CLIENTS", 5)
        limiter = RateLimitMiddleware(app=None, requests_per_window=1, window_seconds=60)
        for i in range(20):
            assert limiter.hit(f"10.0.0.{i}")
        assert len(limiter._hits) == 5
        # The newest client is still tracked and limited.
        assert limiter.hit("10.0.0.19") is False

    def test_forwarded_for_is_ignored_by_default(self, monkeypatch):
        monkeypatch.delenv("TRUST_PROXY_HEADERS", raising=False)
        client = TestClient(
            _app_with((RateLimitMiddleware, {"requests_per_window": 1, "window_seconds": 60}))
        )
        assert client.get("/ping", headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 200
        assert client.get("/ping", headers={"X-Forwarded-For": "2.2.2.2"}).status_code == 429


class TestRouterMounting:
    """The platform routes must exist on the real app."""

    def test_login_route_is_mounted(self, client):
        resp = client.post("/auth/login", json={"identifier": "DE000000", "password": "x"})
        assert resp.status_code != 404

    def test_profile_requires_auth(self, client):
        assert client.get("/users/me").status_code == 401

    def test_live_voice_is_not_part_of_the_patient_api(self, client):
        assert client.get("/dedan/v2/live-voice/capabilities").status_code == 404


class TestReviewFixes:
    """Regression tests for the automated review of the restored modules."""

    @pytest.fixture
    def platform(self, tmp_path, monkeypatch, secret):
        from dedan_platform import db as dbmod
        from dedan_platform.api_auth import router as auth_router
        from dedan_platform.api_profile import router as profile_router

        monkeypatch.setenv("DEDAN_DATABASE_URL", f"sqlite:///{tmp_path / 'auth.db'}")
        dbmod.reset_engine()
        dbmod.create_all()
        app = FastAPI()
        app.include_router(auth_router)
        app.include_router(profile_router)
        yield TestClient(app)
        dbmod.reset_engine()

    def _register(self, client):
        resp = client.post(
            "/auth/register",
            json={
                "first_name": "Abebe",
                "last_name": "Kebede",
                "email": "abebe@example.com",
                "password": "Str0ng-pass!",
                "password_confirmation": "Str0ng-pass!",
            },
        )
        assert resp.status_code == 201, resp.text
        return resp.json()["access_token"]

    def test_password_change_signs_out_older_tokens(self, platform):
        old_token = self._register(platform)
        # Token `iat` has whole-second precision, and a token from the same
        # second as the change is deliberately still accepted.
        time.sleep(1.1)

        resp = platform.post(
            "/auth/password",
            headers={"Authorization": old_token},
            json={
                "current_password": "Str0ng-pass!",
                "new_password": "N3w-Str0ng-pass!",
                "new_password_confirmation": "N3w-Str0ng-pass!",
            },
        )
        assert resp.status_code == 200, resp.text
        new_token = resp.json()["access_token"]

        assert platform.get("/users/me", headers={"Authorization": old_token}).status_code == 401
        assert platform.get("/users/me", headers={"Authorization": new_token}).status_code == 200

    def test_bearer_scheme_is_accepted(self, platform):
        token = self._register(platform)
        resp = platform.get("/users/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_non_ascii_token_is_401_not_500(self, platform):
        resp = platform.get("/users/me", headers={"Authorization": "v1.é.abc".encode("utf-8")})
        assert resp.status_code == 401

    def test_admin_key_from_settings_signs_tokens(self, monkeypatch):
        from app.core.config import get_settings

        monkeypatch.delenv("REALTIME_TOKEN_SECRET", raising=False)
        monkeypatch.delenv("ADMIN_API_KEY", raising=False)
        monkeypatch.setattr(get_settings(), "ADMIN_API_KEY", "from-dotenv")
        assert auth.identity_from_token(auth.issue_token("DE123456")) == "DE123456"

    def test_rejections_carry_security_headers(self, client):
        resp = client.post(
            "/api/analyze",
            content=b"x" * (64 * 1024 * 1024),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 413
        assert resp.headers["x-content-type-options"] == "nosniff"

    def test_registry_includes_the_configured_default_model(self, client):
        from app.core.config import get_settings

        registry = client.get("/api/providers").json()["registry"]
        assert get_settings().GEMINI_MODEL in registry
