"""Practice layer tests: engagement metadata + the cross-client cockpit.

The cockpit's contract: live DB counts for the active client, read-only
``state.db`` counts (with a staleness stamp) for parked ones, per-card
degradation instead of board failure, and complete invisibility for
single-company installs.
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openexecutive.clients import cockpit, slots
from openexecutive.clients.cockpit import (
    format_practice_for_today,
    practice_overview,
)
from openexecutive.clients.slots import (
    ClientSlotError,
    ClientSlotNotFoundError,
    activate_client_slot,
    create_client_slot,
    list_client_slots,
    update_client_meta,
)


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Same isolation pattern as test_client_slots.py's env fixture."""
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
    from openexecutive.memory import episodic

    monkeypatch.setattr(episodic, "DB_PATH", db_path)
    episodic.initialize_db(db_path)

    async def _no_vector(_settings: Any, _app_state: Any) -> int:
        return 0

    monkeypatch.setattr(slots, "_rebuild_vector_state", _no_vector)
    monkeypatch.setattr(slots, "_set_honcho_client_workspace", lambda _slug: None)
    monkeypatch.setattr(slots, "_reseed_blank_defaults", lambda **kw: None)
    monkeypatch.setattr(slots, "snapshot_user_state", lambda _s: None)
    return SimpleNamespace(settings=settings, db_path=db_path, company=company)


def _stage_actions(db_path: Path, *, overdue: int, future: int, awaiting: int) -> None:
    now = datetime.now(UTC)
    conn = sqlite3.connect(str(db_path))
    try:
        def _insert(run_at: str, awaiting_since: str | None) -> None:
            conn.execute(
                "INSERT INTO scheduled_actions (created_at, run_at, channel, "
                "channel_ref, intent_text, status, attempts, last_error, "
                "department, kind, awaiting_response_since) "
                "VALUES (?, ?, 'any', '', 'x', 'pending', 0, '', '', 'ad_hoc', ?)",
                (now.isoformat(), run_at, awaiting_since),
            )

        for _ in range(overdue):
            _insert((now - timedelta(hours=2)).isoformat(), None)
        for _ in range(future):
            _insert((now + timedelta(days=2)).isoformat(), None)
        for _ in range(awaiting):
            _insert((now + timedelta(days=2)).isoformat(), (now - timedelta(days=1)).isoformat())
        conn.commit()
    finally:
        conn.close()


async def _two_client_practice(env: SimpleNamespace) -> None:
    """Acme (parked, 1 overdue + 1 awaiting) and Beta (active, 2 future)."""
    _stage_actions(env.db_path, overdue=1, future=0, awaiting=1)
    await create_client_slot(env.settings, display_name="Acme", source="current")
    await create_client_slot(env.settings, display_name="Beta", source="blank")
    await activate_client_slot(env.settings, "beta")  # parks Acme with its state
    _stage_actions(env.db_path, overdue=0, future=2, awaiting=0)


async def test_cockpit_counts_live_vs_parked(env: SimpleNamespace) -> None:
    await _two_client_practice(env)

    cards = {c.slug: c for c in practice_overview(env.settings)}
    assert set(cards) == {"acme", "beta"}

    acme = cards["acme"]  # parked — read from its slot's state.db
    assert acme.is_active is False
    assert acme.overdue_actions == 1
    assert acme.awaiting_replies == 1
    assert acme.pending_actions == 2  # overdue + awaiting rows are both pending
    assert acme.saved_at is not None  # staleness stamp

    beta = cards["beta"]  # active — read from the live DB
    assert beta.is_active is True
    assert beta.pending_actions == 2
    assert beta.overdue_actions == 0
    assert beta.saved_at is None

    # Active card sorts first.
    ordered = practice_overview(env.settings)
    assert ordered[0].slug == "beta"


async def test_cockpit_metadata_and_renewal(env: SimpleNamespace) -> None:
    await _two_client_practice(env)
    soon = (datetime.now(UTC) + timedelta(days=10)).date().isoformat()
    await update_client_meta(
        env.settings,
        "acme",
        {"role": "Fractional CFO", "status": "active", "renewal_date": soon},
    )

    card = next(c for c in practice_overview(env.settings) if c.slug == "acme")
    assert card.role == "Fractional CFO"
    assert card.days_to_renewal == 10

    # Metadata also surfaces on the plain list endpoint payload.
    listed = {s["slug"]: s for s in list_client_slots(env.settings)}
    assert listed["acme"]["role"] == "Fractional CFO"
    assert listed["acme"]["renewal_date"] == soon


async def test_never_activated_slot_is_metadata_only_card(env: SimpleNamespace) -> None:
    await create_client_slot(env.settings, display_name="Acme", source="current")
    await create_client_slot(env.settings, display_name="Beta", source="blank")

    card = next(c for c in practice_overview(env.settings) if c.slug == "beta")
    assert card.has_state is False
    assert card.pending_actions is None
    assert card.error is False


async def test_corrupt_slot_degrades_one_card_not_the_board(env: SimpleNamespace) -> None:
    await _two_client_practice(env)
    (env.company / "_client_slots" / "acme" / "state.db").write_text("not a database")

    cards = {c.slug: c for c in practice_overview(env.settings)}
    assert cards["acme"].error is True
    assert cards["beta"].error is False
    assert cards["beta"].pending_actions == 2


async def test_today_panel_gating(env: SimpleNamespace) -> None:
    # 0 slots → empty.
    assert format_practice_for_today(env.settings) == []
    # 1 slot → still empty (single-client mode).
    await create_client_slot(env.settings, display_name="Acme", source="current")
    assert format_practice_for_today(env.settings) == []
    # 2 slots → parked clients only.
    await create_client_slot(env.settings, display_name="Beta", source="blank")
    panel = format_practice_for_today(env.settings)
    assert [c.slug for c in panel] == ["beta"]
    assert all(not c.is_active for c in panel)


async def test_today_panel_swallows_errors(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(_settings: Any) -> Any:
        raise RuntimeError("cockpit exploded")

    monkeypatch.setattr(cockpit, "practice_overview", _boom)
    assert format_practice_for_today(env.settings) == []


# ── Metadata gates ───────────────────────────────────────────────────────────


async def test_update_meta_rejects_unknown_fields_and_bad_status(
    env: SimpleNamespace,
) -> None:
    await create_client_slot(env.settings, display_name="Acme", source="current")

    with pytest.raises(ClientSlotError, match="Unknown metadata fields"):
        await update_client_meta(env.settings, "acme", {"display_name": "Hacked"})
    with pytest.raises(ClientSlotError, match="status must be one of"):
        await update_client_meta(env.settings, "acme", {"status": "vibing"})
    with pytest.raises(ClientSlotNotFoundError):
        await update_client_meta(env.settings, "nope", {"role": "CFO"})


# ── HTTP contract ────────────────────────────────────────────────────────────


@pytest.fixture()
def client(env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from openexecutive import config
    from openexecutive.api.routes import clients as route

    monkeypatch.setattr(config, "get_settings", lambda: env.settings)
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app)


async def test_patch_and_cockpit_routes(env: SimpleNamespace, client: TestClient) -> None:
    await _two_client_practice(env)

    resp = client.patch(
        "/clients/acme", json={"role": "Fractional COO", "status": "paused"}
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "Fractional COO"

    assert client.patch("/clients/nope", json={"role": "X"}).status_code == 404
    assert client.patch("/clients/acme", json={}).status_code == 400
    assert client.patch("/clients/acme", json={"status": "vibing"}).status_code == 400

    board = client.get("/clients/cockpit").json()
    assert {c["slug"] for c in board["clients"]} == {"acme", "beta"}
    acme = next(c for c in board["clients"] if c["slug"] == "acme")
    assert acme["role"] == "Fractional COO"
    assert acme["overdue_actions"] == 1
    assert board["generated_at"]
