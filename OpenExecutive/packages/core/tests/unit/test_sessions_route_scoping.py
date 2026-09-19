"""Tests for GET /sessions per-caller scoping.

The Recent-chats sidebar must show each signed-in user only their own
chats. The route resolves `x-caller-email` to a Person and filters the
list; an unknown header MUST NOT fall through to the principal.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openexecutive.api.routes import sessions as sessions_route
from openexecutive.memory import episodic, session_store
from openexecutive.people import store as people_store


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.chdir(tmp_path)
    db_path = Path("./episodic_memory.db").resolve()
    monkeypatch.setattr(episodic, "DB_PATH", db_path)
    monkeypatch.setattr(session_store, "DB_PATH", db_path)
    monkeypatch.setattr(people_store, "DB_PATH", tmp_path / "people.db")
    episodic.initialize_db(db_path)
    people_store.initialize_db()

    app = FastAPI()
    app.include_router(sessions_route.router)
    return TestClient(app)


def test_sessions_list_filters_by_caller_email(client: TestClient) -> None:
    """Two users with their own sessions each see only their own."""
    alex_id = people_store.upsert_person(
        full_name="Alex", is_principal=True, email="alex@example.com"
    )
    sabin_id = people_store.upsert_person(
        full_name="Sabin", email="sabin@example.com"
    )

    session_store.create_session("alex-s1", "Alex chat", "2024-01-01T00:00:00", caller_person_id=alex_id)
    session_store.create_session("sabin-s1", "Sabin chat", "2024-01-02T00:00:00", caller_person_id=sabin_id)

    alex_resp = client.get("/sessions", headers={"x-caller-email": "alex@example.com"})
    sabin_resp = client.get("/sessions", headers={"x-caller-email": "sabin@example.com"})

    assert alex_resp.status_code == 200
    assert sabin_resp.status_code == 200
    assert [s["session_id"] for s in alex_resp.json()] == ["alex-s1"]
    assert [s["session_id"] for s in sabin_resp.json()] == ["sabin-s1"]


def test_sessions_list_unknown_email_returns_empty_not_principal(client: TestClient) -> None:
    """A signed-in user whose email isn't in the roster gets an empty list,
    not the principal's chats. Mirrors the chat-route precedence rule."""
    alex_id = people_store.upsert_person(
        full_name="Alex", is_principal=True, email="alex@example.com"
    )
    session_store.create_session("alex-only", "Alex chat", "2024-01-01T00:00:00", caller_person_id=alex_id)

    resp = client.get("/sessions", headers={"x-caller-email": "stranger@example.com"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_sessions_list_no_header_falls_back_to_principal(client: TestClient) -> None:
    """CLI / direct-curl callers (no x-caller-email header) see the principal's chats."""
    alex_id = people_store.upsert_person(
        full_name="Alex", is_principal=True, email="alex@example.com"
    )
    people_store.upsert_person(full_name="Sabin", email="sabin@example.com")

    session_store.create_session("alex-s1", "Alex chat", "2024-01-01T00:00:00", caller_person_id=alex_id)

    resp = client.get("/sessions")
    assert resp.status_code == 200
    assert [s["session_id"] for s in resp.json()] == ["alex-s1"]


def test_sessions_list_hides_legacy_null_owner_rows(client: TestClient) -> None:
    """Sessions created before the migration have NULL owner and stay hidden."""
    alex_id = people_store.upsert_person(
        full_name="Alex", is_principal=True, email="alex@example.com"
    )
    # Simulate a pre-migration row.
    session_store.create_session("legacy", "Pre-migration", "2024-01-01T00:00:00", caller_person_id=None)
    session_store.create_session("modern", "Post-migration", "2024-01-02T00:00:00", caller_person_id=alex_id)

    resp = client.get("/sessions", headers={"x-caller-email": "alex@example.com"})
    assert resp.status_code == 200
    assert [s["session_id"] for s in resp.json()] == ["modern"]


def test_sessions_list_email_case_insensitive(client: TestClient) -> None:
    """Header is lowercased before lookup; mixed-case still resolves."""
    sabin_id = people_store.upsert_person(
        full_name="Sabin", email="sabin@example.com"
    )
    session_store.create_session("sabin-s1", "Sabin chat", "2024-01-01T00:00:00", caller_person_id=sabin_id)

    resp = client.get("/sessions", headers={"x-caller-email": "Sabin@Example.COM"})
    assert resp.status_code == 200
    assert [s["session_id"] for s in resp.json()] == ["sabin-s1"]
