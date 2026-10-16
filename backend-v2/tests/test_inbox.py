"""The patient's in-app inbox (Next.js notifications screen)."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

PASSWORD = "Str0ng-pass!"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from dedan_platform import db as dbmod
    from dedan_platform.api_auth import router as auth_router
    from dedan_platform.api_health import router as health_router
    from dedan_platform.api_inbox import router as inbox_router
    from dedan_platform.api_profile import router as profile_router

    monkeypatch.setenv("REALTIME_TOKEN_SECRET", "test-secret")
    monkeypatch.setenv("DEDAN_DATABASE_URL", f"sqlite:///{tmp_path / 'inbox.db'}")
    dbmod.reset_engine()
    dbmod.create_all()
    app = FastAPI()
    for router in (auth_router, profile_router, health_router, inbox_router):
        app.include_router(router)
    yield TestClient(app)
    dbmod.reset_engine()


def register(client, email):
    resp = client.post("/auth/register", json={
        "first_name": "A", "last_name": "B", "email": email,
        "password": PASSWORD, "password_confirmation": PASSWORD,
    })
    return {"Authorization": resp.json()["access_token"]}


def book(client, auth, days=3):
    when = datetime.now(timezone.utc) + timedelta(days=days)
    resp = client.post("/users/me/appointments", headers=auth, json={
        "scheduled_at": when.isoformat(), "location": "Black Lion Hospital", "timezone": "Africa/Addis_Ababa",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["appointment"]["appointment_id"]


class TestEvents:
    def test_booking_and_cancelling_appear_in_the_inbox(self, client):
        auth = register(client, "a@example.com")
        appointment_id = book(client, auth)
        client.patch(f"/users/me/appointments/{appointment_id}/status", headers=auth,
                     json={"status": "CANCELLED"})
        items = client.get("/users/me/inbox", headers=auth).json()["items"]
        assert [i["kind"] for i in items] == ["appointment_cancelled", "appointment_booked"]
        assert items[1]["link"] == {"screen": "appointment", "id": appointment_id}
        assert "(Africa/Addis_Ababa)" in items[1]["body"] and "Black Lion Hospital" in items[1]["body"]

    def test_password_change_is_a_security_item(self, client):
        auth = register(client, "a@example.com")
        client.post("/auth/password", headers=auth, json={
            "current_password": PASSWORD, "new_password": "N3w-Str0ng-pass!",
            "new_password_confirmation": "N3w-Str0ng-pass!",
        })
        # The old token is signed out by the change; sign in again.
        token = client.post("/auth/login", json={"identifier": "a@example.com",
                                                 "password": "N3w-Str0ng-pass!"}).json()["access_token"]
        items = client.get("/users/me/inbox?category=security",
                           headers={"Authorization": token}).json()["items"]
        assert items[0]["kind"] == "password_changed"


class TestReading:
    def test_unread_counts_mark_read_and_read_all(self, client):
        auth = register(client, "a@example.com")
        book(client, auth)
        book(client, auth, days=5)
        inbox = client.get("/users/me/inbox", headers=auth).json()
        assert inbox["unread_count"] == 2
        assert inbox["unread_by_category"]["appointments"] == 2

        first = inbox["items"][0]["id"]
        assert client.post(f"/users/me/inbox/{first}/read", headers=auth).status_code == 200
        assert client.get("/users/me/inbox", headers=auth).json()["unread_count"] == 1
        assert client.get("/users/me/inbox?unread_only=true", headers=auth).json()["items"][0]["id"] != first

        assert client.post("/users/me/inbox/read-all", headers=auth).json()["marked_read"] == 1
        assert client.get("/users/me/inbox", headers=auth).json()["unread_count"] == 0

    def test_dismiss_hides_the_item(self, client):
        auth = register(client, "a@example.com")
        book(client, auth)
        item = client.get("/users/me/inbox", headers=auth).json()["items"][0]["id"]
        assert client.delete(f"/users/me/inbox/{item}", headers=auth).status_code == 200
        assert client.get("/users/me/inbox", headers=auth).json()["items"] == []

    def test_paging(self, client):
        from dedan_platform import identity, inbox

        auth = register(client, "a@example.com")
        user = identity.find_user_by_email("a@example.com")
        for n in range(5):
            inbox.add_item(user.id, "messages", "note", f"Message {n}")
        page = client.get("/users/me/inbox?limit=3", headers=auth).json()
        assert len(page["items"]) == 3 and page["next_cursor"]
        rest = client.get("/users/me/inbox", headers=auth, params={"cursor": page["next_cursor"]}).json()
        assert len(rest["items"]) == 2 and rest["next_cursor"] is None

    def test_paging_with_identical_timestamps_loses_nothing(self, client):
        from sqlalchemy import update

        from dedan_platform import identity, inbox
        from dedan_platform.db import session_scope
        from dedan_platform.models import InboxItem, utcnow

        auth = register(client, "a@example.com")
        user = identity.find_user_by_email("a@example.com")
        for n in range(5):
            inbox.add_item(user.id, "messages", "note", f"Message {n}")
        with session_scope() as session:
            session.execute(update(InboxItem).values(created_at=utcnow()))
        seen, cursor = [], None
        for _ in range(5):
            params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
            page = client.get("/users/me/inbox", headers=auth, params=params).json()
            seen += [i["id"] for i in page["items"]]
            cursor = page["next_cursor"]
            if not cursor:
                break
        assert len(seen) == 5 and len(set(seen)) == 5

    def test_bad_cursor_is_400(self, client):
        auth = register(client, "a@example.com")
        assert client.get("/users/me/inbox?cursor=not-a-cursor", headers=auth).status_code == 400

    def test_bad_category_is_400(self, client):
        auth = register(client, "a@example.com")
        assert client.get("/users/me/inbox?category=spam", headers=auth).status_code == 400


class TestOwnership:
    def test_another_patients_item_is_404(self, client):
        alice = register(client, "alice@example.com")
        bob = register(client, "bob@example.com")
        book(client, alice)
        item = client.get("/users/me/inbox", headers=alice).json()["items"][0]["id"]
        assert client.post(f"/users/me/inbox/{item}/read", headers=bob).status_code == 404
        assert client.delete(f"/users/me/inbox/{item}", headers=bob).status_code == 404
        assert client.get("/users/me/inbox", headers=bob).json()["items"] == []
