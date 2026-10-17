"""Handoff sharing, care search, preference validation and onboarding values."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

PASSWORD = "Str0ng-pass!"
SUMMARY = {"main_concern": "Headache for three days", "allergies": ["penicillin"]}


@pytest.fixture
def client(tmp_path, monkeypatch):
    from dedan_platform import db as dbmod
    from dedan_platform.api_auth import router as auth_router
    from dedan_platform.api_care import router as care_router
    from dedan_platform.api_profile import router as profile_router

    monkeypatch.setenv("REALTIME_TOKEN_SECRET", "test-secret")
    monkeypatch.setenv("DEDAN_DATABASE_URL", f"sqlite:///{tmp_path / 'correct.db'}")
    dbmod.reset_engine()
    dbmod.create_all()
    app = FastAPI()
    for router in (auth_router, profile_router, care_router):
        app.include_router(router)
    yield TestClient(app)
    dbmod.reset_engine()


def register(client, **extra):
    resp = client.post("/auth/register", json={
        "first_name": "A", "last_name": "B", "email": "a@example.com",
        "password": PASSWORD, "password_confirmation": PASSWORD, **extra,
    })
    assert resp.status_code == 201, resp.text
    return {"Authorization": resp.json()["access_token"]}


class TestHandoffShare:
    def _prepare(self, client, auth):
        client.patch("/users/me/consent", headers=auth,
                     json={"treatment_processing": True, "data_sharing_with_clinicians": True})
        body = client.post("/users/me/handoff/summary", headers=auth, json=SUMMARY).json()
        return {"handoff_id": body["handoff_id"], "fingerprint": body["fingerprint"]}

    def test_can_share_twice(self, client):
        auth = register(client)
        share = self._prepare(client, auth)
        assert client.post("/users/me/handoff/share", headers=auth, json=share).status_code == 200
        assert client.post("/users/me/handoff/share", headers=auth, json=share).status_code == 200

    def test_an_old_summary_can_still_be_shared(self, client):
        from dedan_platform import identity
        from dedan_platform.models import EventStatus, HealthEventType
        from dedan_platform.timeline import record_event

        auth = register(client)
        share = self._prepare(client, auth)
        user = identity.find_user_by_email("a@example.com")
        for n in range(105):
            record_event(user_id=user.id, event_type=HealthEventType.DOCUMENT, title=f"Doc {n}",
                         status=EventStatus.COMPLETED, metadata={})
        assert client.post("/users/me/handoff/share", headers=auth, json=share).status_code == 200

    def test_malformed_ids_are_rejected(self, client):
        auth = register(client)
        resp = client.post("/users/me/handoff/share", headers=auth,
                           json={"handoff_id": "%", "fingerprint": "x"})
        assert resp.status_code == 422


class TestCareSearch:
    def test_country_filter(self, client):
        auth = register(client)
        body = client.post("/users/me/care/facilities", headers=auth,
                           json={"symptoms": ["fever"], "country": "ET", "limit": 20}).json()
        assert body["facilities"] and {f["country"] for f in body["facilities"]} == {"ET"}

    def test_query_is_applied_before_the_limit(self, client):
        auth = register(client)
        body = client.post("/users/me/care/facilities", headers=auth,
                           json={"symptoms": ["fever"], "query": "Peter", "limit": 1}).json()
        assert body["query_matched"] is True
        assert [f["id"] for f in body["facilities"]] == ["et-addis-stpeter"]

    def test_no_match_is_reported(self, client):
        auth = register(client)
        body = client.post("/users/me/care/facilities", headers=auth,
                           json={"symptoms": ["fever"], "query": "zzzz"}).json()
        assert body["query_matched"] is False and body["facilities"]


class TestPreferences:
    @pytest.mark.parametrize("change", [
        {"email_notifications": "false"}, {"theme": "neon"},
        {"preferred_contact_window": "x" * 65}, {"reminder_offsets": "abc"},
        {"reminder_offsets": [0]}, {"reminder_offsets": [1, 2, 3, 4, 5, 6]},
        {"reminder_offsets": [40 * 86400]},
    ])
    def test_bad_values_are_400(self, client, change):
        auth = register(client)
        assert client.patch("/users/me/preferences", headers=auth, json=change).status_code == 400

    @pytest.mark.parametrize("field", ["voice_preference", "voice_gender"])
    def test_removed_voice_fields_are_rejected(self, client, field):
        # Live voice is not part of the patient app.
        auth = register(client)
        resp = client.patch("/users/me/preferences", headers=auth, json={field: "warm"})
        assert resp.status_code == 400
        assert field not in client.get("/users/me/preferences", headers=auth).json()

    def test_reminder_offsets_are_normalised(self, client):
        auth = register(client)
        resp = client.patch("/users/me/preferences", headers=auth,
                            json={"reminder_offsets": [3600, 86400, 3600]})
        assert resp.status_code == 200, resp.text
        assert client.get("/users/me/preferences", headers=auth).json()["reminder_offsets"] in (
            "86400,3600", [86400, 3600])

    @pytest.mark.parametrize("empty", ["", "  ", None, []])
    def test_empty_offsets_mean_the_defaults(self, client, empty):
        auth = register(client)
        assert client.patch("/users/me/preferences", headers=auth,
                            json={"reminder_offsets": empty}).status_code == 200
        assert client.get("/users/me/preferences", headers=auth).json()["reminder_offsets"] in (
            "604800,86400,3600", [604800, 86400, 3600])

    def test_region_locale_sets_its_language(self, client):
        auth = register(client, locale="am-ET")
        assert client.get("/users/me/preferences", headers=auth).json()["language"] == "am"

    def test_unsupported_locale_does_not_become_the_language(self, client):
        auth = register(client, locale="xx")
        assert client.get("/users/me/preferences", headers=auth).json()["language"] == "en"


@pytest.mark.parametrize("given,stored", [
    ("1-20", "0-20"), ("81-100", "81+"), ("21-40", "21-40"),
    ("1–20", "0-20"), ("81–100", "81+"), (" 21–40 ", "21-40"),
])
def test_onboarding_age_buckets_are_accepted(client, given, stored):
    auth = register(client)
    client.patch("/users/me/consent", headers=auth, json={"treatment_processing": True})
    resp = client.patch("/users/me/health-profile", headers=auth, json={"age_range": given})
    assert resp.status_code == 200, resp.text
    assert client.get("/users/me/health-profile", headers=auth).json()["age_range"] == stored
