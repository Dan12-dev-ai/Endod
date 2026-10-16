"""Profile, onboarding and settings fields the Next.js frontend collects."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

PASSWORD = "Str0ng-pass!"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from dedan_platform import db as dbmod
    from dedan_platform.api_auth import router as auth_router
    from dedan_platform.api_profile import router as profile_router

    monkeypatch.setenv("REALTIME_TOKEN_SECRET", "test-secret")
    monkeypatch.setenv("DEDAN_DATABASE_URL", f"sqlite:///{tmp_path / 'profile.db'}")
    dbmod.reset_engine()
    dbmod.create_all()
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(profile_router)
    yield TestClient(app)
    dbmod.reset_engine()


@pytest.fixture
def auth(client):
    resp = client.post("/auth/register", json={
        "first_name": "Abebe", "last_name": "Kebede", "email": "a@example.com",
        "password": PASSWORD, "password_confirmation": PASSWORD,
    })
    return {"Authorization": resp.json()["access_token"]}


class TestNames:
    def test_signup_stores_name_parts(self, client, auth):
        me = client.get("/users/me", headers=auth).json()
        assert (me["first_name"], me["last_name"], me["display_name"]) == ("Abebe", "Kebede", "Abebe Kebede")

    def test_onboarding_names_derive_the_display_name(self, client, auth):
        me = client.patch("/users/me", headers=auth, json={
            "first_name": "Almaz", "middle_name": "Tesfaye", "last_name": "Bekele",
        }).json()
        assert me["display_name"] == "Almaz Tesfaye Bekele"

    def test_explicit_display_name_wins(self, client, auth):
        me = client.patch("/users/me", headers=auth, json={"first_name": "Almaz", "display_name": "Almi"}).json()
        assert me["display_name"] == "Almi"

    def test_overlong_name_is_400(self, client, auth):
        assert client.patch("/users/me", headers=auth, json={"first_name": "x" * 61}).status_code == 400


class TestLocation:
    def test_address_fields(self, client, auth):
        me = client.patch("/users/me", headers=auth, json={
            "address_line": "Bole Road", "city": "Addis Ababa", "region": "Addis Ababa", "postal_code": "1000",
        }).json()
        assert me["city"] == "Addis Ababa" and me["postal_code"] == "1000"

    def test_search_radius(self, client, auth):
        prefs = client.patch("/users/me/preferences", headers=auth, json={"care_search_radius_km": 25}).json()
        assert prefs["care_search_radius_km"] == 25
        assert client.patch("/users/me/preferences", headers=auth,
                            json={"care_search_radius_km": 0}).status_code == 400


class TestOnboarding:
    def test_goals(self, client, auth):
        prefs = client.patch("/users/me/preferences", headers=auth,
                             json={"onboarding_goals": ["symptoms", "appointments"]}).json()
        assert prefs["onboarding_goals"] == ["symptoms", "appointments"]
        assert client.patch("/users/me/preferences", headers=auth,
                            json={"onboarding_goals": ["crypto"]}).status_code == 400

    def test_age_range_and_sex_need_consent(self, client, auth):
        assert client.patch("/users/me/health-profile", headers=auth,
                            json={"age_range": "21-40"}).status_code == 403

    def test_age_range_gives_an_approximate_age(self, client, auth):
        client.patch("/users/me/consent", headers=auth, json={"treatment_processing": True})
        hp = client.patch("/users/me/health-profile", headers=auth,
                          json={"age_range": "21-40", "sex": "Female"}).json()
        assert hp["age_range"] == "21-40" and hp["age_years"] == 30 and hp["sex"] == "female"

    def test_date_of_birth_takes_precedence(self, client, auth):
        client.patch("/users/me/consent", headers=auth, json={"treatment_processing": True})
        hp = client.patch("/users/me/health-profile", headers=auth,
                          json={"age_range": "61-80", "date_of_birth": "2000-01-15"}).json()
        assert hp["date_of_birth"] == "2000-01-15"
        assert 20 <= hp["age_years"] <= 40

    @pytest.mark.parametrize("change", [
        {"sex": "robot"}, {"age_range": "18-25"}, {"blood_type": "Z"},
        {"date_of_birth": "2999-01-01"}, {"date_of_birth": "not a date"},
    ])
    def test_invalid_health_values_are_400(self, client, auth, change):
        client.patch("/users/me/consent", headers=auth, json={"treatment_processing": True})
        assert client.patch("/users/me/health-profile", headers=auth, json=change).status_code == 400

    def test_prefer_not_to_say(self, client, auth):
        client.patch("/users/me/consent", headers=auth, json={"treatment_processing": True})
        hp = client.patch("/users/me/health-profile", headers=auth, json={"sex": "Prefer not to say"}).json()
        assert hp["sex"] == "prefer_not_to_say"
