"""The Digital Health Card: unique, signed, verifiable without revealing anything."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

PASSWORD = "Str0ng-pass!"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from dedan_platform import db as dbmod
    from dedan_platform.api_auth import router as auth_router
    from dedan_platform.api_cards import router as cards_router
    from dedan_platform.api_profile import router as profile_router

    monkeypatch.setenv("REALTIME_TOKEN_SECRET", "test-secret")
    monkeypatch.setenv("DEDAN_DATABASE_URL", f"sqlite:///{tmp_path / 'cards.db'}")
    dbmod.reset_engine()
    dbmod.create_all()
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(profile_router)
    app.include_router(cards_router)
    yield TestClient(app)
    dbmod.reset_engine()


def register(client, email, first="Abebe", last="Kebede"):
    resp = client.post("/auth/register", json={
        "first_name": first, "last_name": last, "email": email,
        "password": PASSWORD, "password_confirmation": PASSWORD,
    })
    assert resp.status_code in (200, 201), resp.text
    return {"Authorization": resp.json()["access_token"]}


def test_each_patient_gets_their_own_signed_card(client):
    cards = [client.get("/users/me/card", headers=register(client, f"p{i}@example.com")).json() for i in range(5)]
    assert len({c["dedan_user_id"] for c in cards}) == 5
    assert len({c["signature"] for c in cards}) == 5
    for card in cards:
        assert card["dedan_user_id"].startswith("DE") and len(card["signature"]) >= 20


def test_a_genuine_card_verifies_with_only_what_is_printed_on_it(client):
    card = client.get("/users/me/card", headers=register(client, "a@example.com", "Almaz", "Tefera")).json()
    resp = client.get(f"/cards/{card['dedan_user_id']}/verify", params={"s": card["signature"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True and body["full_name"] == "Almaz Tefera"
    assert set(body) == {"valid", "dedan_user_id", "full_name", "issued_at"}
    # A lowercase ID typed by hand is the same card.
    lower = client.get(f"/cards/{card['dedan_user_id'].lower()}/verify", params={"s": card["signature"]})
    assert lower.status_code == 200


def test_forged_and_swapped_cards_do_not_verify(client):
    one = client.get("/users/me/card", headers=register(client, "a@example.com")).json()
    two = client.get("/users/me/card", headers=register(client, "b@example.com")).json()
    attempts = [
        (one["dedan_user_id"], two["signature"]),  # another card's signature
        (one["dedan_user_id"], ""),
        (one["dedan_user_id"], one["signature"][:-2] + "AA"),
        ("DE000000", one["signature"]),
        ("not-an-id", one["signature"]),
    ]
    for dedan_id, signature in attempts:
        resp = client.get(f"/cards/{dedan_id}/verify", params={"s": signature})
        assert resp.status_code == 404, (dedan_id, signature)


def test_an_unknown_id_answers_like_a_forgery(client):
    from dedan_platform.cards import card_signature

    # Correctly signed, but no such account: the same answer as a forgery.
    resp = client.get("/cards/DE000001/verify", params={"s": card_signature("DE000001")})
    assert resp.status_code == 404


def test_card_needs_sign_in(client):
    assert client.get("/users/me/card").status_code == 401


def test_onboarding_complete_follows_the_name(client):
    headers = register(client, "a@example.com")
    assert client.get("/users/me", headers=headers).json()["onboarding_complete"] is True
    client.patch("/users/me", headers=headers, json={"first_name": None})
    assert client.get("/users/me", headers=headers).json()["onboarding_complete"] is False


@pytest.mark.parametrize("signature", ["é" * 22, "x" * 65, "a b", "%00"])
def test_odd_signatures_are_refused_not_errors(client, signature):
    card = client.get("/users/me/card", headers=register(client, "a@example.com")).json()
    # Refused (404, or 422 past the length limit), never a server error.
    assert client.get(f"/cards/{card['dedan_user_id']}/verify", params={"s": signature}).status_code in (404, 422)


def test_cards_have_their_own_secret(client, monkeypatch):
    from dedan_platform.cards import card_signature

    with_session_secret = card_signature("DE123456")
    monkeypatch.setenv("CARD_SIGNING_SECRET", "card-only-secret")
    with_card_secret = card_signature("DE123456")
    assert with_card_secret != with_session_secret
    # Rotating the session secret no longer touches the cards.
    monkeypatch.setenv("REALTIME_TOKEN_SECRET", "rotated")
    assert card_signature("DE123456") == with_card_secret
