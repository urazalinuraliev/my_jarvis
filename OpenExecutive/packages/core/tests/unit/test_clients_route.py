"""HTTP-level tests for the /clients routes.

Covers the FastAPI contract (status codes, error mapping, payload shapes)
over the slot machinery; the deeper save/restore behavior is covered by
``test_client_slots.py``.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openexecutive.api.routes import clients as route
from openexecutive.clients import slots


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    company = tmp_path / "company"
    company.mkdir()
    settings = SimpleNamespace(
        company_profile_path=company / "profile.yaml",
        vector_store_path=tmp_path / "chroma",
        mcp_servers_config_path=company / "mcp_servers.json",
        honcho_workspace_id="default-ws",
    )
    settings.company_profile_path.write_text("name: Live Co\n")

    db_path = tmp_path / "episodic.db"
    from openexecutive import config
    from openexecutive.memory import episodic

    monkeypatch.setattr(episodic, "DB_PATH", db_path)
    episodic.initialize_db(db_path)
    monkeypatch.setattr(config, "get_settings", lambda: settings)

    async def _no_vector(_settings: Any, _app_state: Any) -> int:
        return 0

    monkeypatch.setattr(slots, "_rebuild_vector_state", _no_vector)
    monkeypatch.setattr(slots, "_set_honcho_client_workspace", lambda _slug: None)
    monkeypatch.setattr(slots, "_reseed_blank_defaults", lambda **kw: None)
    monkeypatch.setattr(slots, "snapshot_user_state", lambda _s: None)

    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app)


def test_list_starts_empty_with_no_active(client: TestClient) -> None:
    body = client.get("/clients").json()
    assert body == {
        "active": None,
        "fixture_active": None,
        "rotation_in_progress": False,
        "clients": [],
    }


def test_create_activate_save_delete_lifecycle(client: TestClient) -> None:
    # Create from current → becomes active.
    resp = client.post(
        "/clients", json={"display_name": "Acme Corp", "source": "current"}
    )
    assert resp.status_code == 200
    assert resp.json()["slug"] == "acme_corp"
    assert resp.json()["active"] is True

    body = client.get("/clients").json()
    assert body["active"] == "acme_corp"
    assert [c["slug"] for c in body["clients"]] == ["acme_corp"]

    # Blank second client, then switch to it.
    assert (
        client.post(
            "/clients", json={"display_name": "Beta", "source": "blank"}
        ).status_code
        == 200
    )
    resp = client.post("/clients/beta/activate")
    assert resp.status_code == 200
    assert resp.json()["slug"] == "beta"
    assert resp.json()["previous"] == "acme_corp"
    assert client.get("/clients").json()["active"] == "beta"

    # Checkpoint without switching.
    assert client.post("/clients/save").json()["slug"] == "beta"

    # Active client refuses deletion; parked one deletes.
    assert client.delete("/clients/beta").status_code == 409
    assert client.delete("/clients/acme_corp").status_code == 200
    assert [c["slug"] for c in client.get("/clients").json()["clients"]] == ["beta"]


def test_error_mapping(client: TestClient) -> None:
    # Unknown slot → 404.
    assert client.post("/clients/nope/activate").status_code == 404
    assert client.delete("/clients/nope").status_code == 404
    # No active client → save conflicts.
    assert client.post("/clients/save").status_code == 409
    # Bad input → 400.
    assert (
        client.post("/clients", json={"display_name": "", "source": "current"}).status_code
        == 400
    )
    assert (
        client.post(
            "/clients", json={"display_name": "X", "source": "weird"}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/clients", json={"display_name": "X", "slug": "Bad Slug!"}
        ).status_code
        == 400
    )
    # Duplicate → 409.
    client.post("/clients", json={"display_name": "Acme", "source": "blank"})
    assert (
        client.post(
            "/clients", json={"display_name": "Acme", "slug": "acme", "source": "blank"}
        ).status_code
        == 409
    )


def test_refuses_while_fixture_active(client: TestClient, tmp_path: Path) -> None:
    backup = tmp_path / "company" / "_user_backup"
    backup.mkdir(parents=True)
    (backup / ".fixture_active").write_text("halcyon_motors")

    body = client.get("/clients").json()
    assert body["fixture_active"] == "halcyon_motors"
    assert (
        client.post(
            "/clients", json={"display_name": "Acme", "source": "current"}
        ).status_code
        == 409
    )
