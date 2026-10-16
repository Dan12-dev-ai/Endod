"""Signed-in AI consultation: patient details come from the stored profile."""

import pytest

PASSWORD = "Str0ng-pass!"


@pytest.fixture
def auth(client, tmp_path, monkeypatch):
    from dedan_platform import db as dbmod

    monkeypatch.setenv("REALTIME_TOKEN_SECRET", "test-secret")
    monkeypatch.setenv("DEDAN_DATABASE_URL", f"sqlite:///{tmp_path / 'consult.db'}")
    dbmod.reset_engine()
    dbmod.create_all()
    token = client.post("/auth/register", json={
        "first_name": "Almaz", "last_name": "B", "email": "almaz@example.com",
        "password": PASSWORD, "password_confirmation": PASSWORD,
    }).json()["access_token"]
    headers = {"Authorization": token}
    yield headers
    dbmod.reset_engine()


def _consent_and_profile(client, auth, **health):
    client.patch("/users/me/consent", headers=auth, json={"treatment_processing": True})
    client.patch("/users/me", headers=auth, json={"city": "Mekelle", "country_code": "ET"})
    if health:
        client.patch("/users/me/health-profile", headers=auth, json=health)


def test_requires_sign_in(client):
    resp = client.post("/users/me/consultations", json={"symptom_description": "headache for two days"})
    assert resp.status_code == 401


def test_requires_consent(client, auth):
    resp = client.post("/users/me/consultations", headers=auth,
                       json={"symptom_description": "headache for two days"})
    assert resp.status_code == 403


def test_needs_an_age(client, auth):
    _consent_and_profile(client, auth)
    resp = client.post("/users/me/consultations", headers=auth,
                       json={"symptom_description": "headache for two days"})
    assert resp.status_code == 400 and "age" in resp.json()["error"].lower() + str(resp.json()).lower()


def test_stored_age_reaches_the_safety_rules(client, auth):
    # An older adult with a fever: urgent because of the stored age range.
    _consent_and_profile(client, auth, age_range="81+", sex="female")
    body = client.post("/users/me/consultations", headers=auth,
                       json={"symptom_description": "I have had a fever since yesterday"}).json()
    assert body["safety"]["urgency"] in ("urgent", "emergency")


def test_emergency_uses_the_stored_location_and_is_recorded(client, auth):
    _consent_and_profile(client, auth, age_range="21-40")
    body = client.post("/users/me/consultations", headers=auth,
                       json={"symptom_description": "I have crushing chest pain and can't breathe"}).json()
    assert body["safety"]["urgency"] == "emergency"
    assert "907" in (body["safety"]["emergency_message"] or "")

    events = client.get("/users/me/timeline", headers=auth).json()["events"]
    kinds = {e["event_type"] for e in events}
    assert {"AI_CONVERSATION", "SAFETY_ALERT"} <= kinds


def test_profile_allergies_are_used(client, auth, monkeypatch):
    import main_clinical

    seen = {}
    original = main_clinical.safety_validator.validate_async

    async def spy(response, profile, original_text=""):
        seen["allergies"] = profile.allergies
        return await original(response, profile, original_text=original_text)

    monkeypatch.setattr(main_clinical.safety_validator, "validate_async", spy)
    _consent_and_profile(client, auth, age_range="21-40", allergies=["penicillin"])
    client.post("/users/me/consultations", headers=auth,
                json={"symptom_description": "sore throat and mild fever"})
    assert seen["allergies"] == ["penicillin"]
