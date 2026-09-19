"""Overnight client rotation: guards, ordering, always-restore, claim pause.

The rotation automates the destructive switch path, so these tests pin the
safety rails: it refuses to run outside multi-client mode, restores the
original client even when individual clients fail, cleans its marker in all
paths, never rotates completed/stateless slots, and the scheduler's claim
pause reads the same marker.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from openexecutive.clients import rotation, slots
from openexecutive.clients.rotation import (
    clear_stale_rotation_marker,
    rotation_in_progress,
    run_client_rotation,
    seed_client_rotation,
)
from openexecutive.clients.slots import (
    activate_client_slot,
    create_client_slot,
    get_active_client,
    update_client_meta,
)


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Slot environment (test_client_slots.py pattern) + rotation enabled."""
    company = tmp_path / "company"
    company.mkdir()
    settings = SimpleNamespace(
        company_profile_path=company / "profile.yaml",
        vector_store_path=tmp_path / "chroma",
        mcp_servers_config_path=company / "mcp_servers.json",
        honcho_workspace_id="default-ws",
        client_rotation_enabled=True,
        external_monitor_enabled=False,
    )
    settings.company_profile_path.write_text("name: Acme\n")

    from openexecutive.memory import episodic

    db_path = tmp_path / "episodic.db"
    monkeypatch.setattr(episodic, "DB_PATH", db_path)
    episodic.initialize_db(db_path)

    async def _no_vector(_settings: Any, _app_state: Any) -> int:
        return 0

    monkeypatch.setattr(slots, "_rebuild_vector_state", _no_vector)
    monkeypatch.setattr(slots, "_set_honcho_client_workspace", lambda _slug: None)
    monkeypatch.setattr(slots, "_reseed_blank_defaults", lambda **kw: None)
    monkeypatch.setattr(slots, "snapshot_user_state", lambda _s: None)

    # Quiet work is stubbed by default; tests record which client was LIVE
    # when it ran (the rotation's whole point).
    live_log: list[str] = []

    async def _record_quiet_work(_settings: Any, slug: str) -> None:
        live_log.append(
            (slots.get_active_client(_settings) or "?") + f"=={slug}"
        )

    monkeypatch.setattr(rotation, "_run_quiet_work_for_live_client", _record_quiet_work)
    return SimpleNamespace(
        settings=settings, db_path=db_path, company=company, live_log=live_log
    )


async def _practice(env: SimpleNamespace, *parked: str) -> None:
    """Active client 'acme' plus the given parked clients (with state)."""
    await create_client_slot(env.settings, display_name="Acme", source="current")
    for name in parked:
        await create_client_slot(env.settings, display_name=name, source="blank")
        await activate_client_slot(env.settings, name.lower())
    if parked:
        await activate_client_slot(env.settings, "acme")


async def test_rotation_guards(env: SimpleNamespace) -> None:
    env.settings.client_rotation_enabled = False
    assert (await run_client_rotation(env.settings))["reason"] == "disabled"
    env.settings.client_rotation_enabled = True

    # No active client.
    assert (await run_client_rotation(env.settings))["reason"] == "no_active_client"

    # Single client.
    await create_client_slot(env.settings, display_name="Acme", source="current")
    assert (await run_client_rotation(env.settings))["reason"] == "single_client"

    # Fixture active.
    backup = env.company / "_user_backup"
    backup.mkdir()
    (backup / ".fixture_active").write_text("halcyon_motors")
    assert (await run_client_rotation(env.settings))["reason"] == "fixture_active"


async def test_rotation_visits_parked_and_restores_original(env: SimpleNamespace) -> None:
    await _practice(env, "Beta", "Gamma")
    assert get_active_client(env.settings) == "acme"

    result = await run_client_rotation(env.settings)

    assert result["ran"] is True
    assert sorted(result["rotated"]) == ["beta", "gamma"]
    assert result["failed"] == {}
    # Quiet work ran while each parked client was LIVE.
    assert sorted(env.live_log) == ["beta==beta", "gamma==gamma"]
    # Original restored; marker gone.
    assert get_active_client(env.settings) == "acme"
    assert rotation_in_progress(env.settings) is False
    # Digest covers the whole practice.
    assert "Acme" in result["digest"] and "(active)" in result["digest"]
    assert "Overnight briefs generated for:" in result["digest"]
    assert "beta" in result["digest"] and "gamma" in result["digest"]


async def test_rotation_skips_completed_and_stateless(env: SimpleNamespace) -> None:
    await _practice(env, "Beta")
    # Completed engagement sleeps.
    await update_client_meta(env.settings, "beta", {"status": "completed"})
    # Never-activated seed/blank slot sleeps.
    await create_client_slot(env.settings, display_name="Fresh", source="blank")

    result = await run_client_rotation(env.settings)
    assert result["reason"] == "no_rotatable_clients"
    assert env.live_log == []


async def test_rotation_failure_still_restores_and_continues(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _practice(env, "Beta", "Gamma")

    async def _explode_on_beta(_settings: Any, slug: str) -> None:
        if slug == "beta":
            raise RuntimeError("brief generation exploded")
        env.live_log.append(slug)

    monkeypatch.setattr(rotation, "_run_quiet_work_for_live_client", _explode_on_beta)

    result = await run_client_rotation(env.settings)

    assert result["rotated"] == ["gamma"]
    assert "beta" in result["failed"]
    assert get_active_client(env.settings) == "acme"  # always restored
    assert rotation_in_progress(env.settings) is False  # marker cleaned
    assert "Rotation issues" in result["digest"]


async def test_stale_marker_reconcile_and_pause_predicate(env: SimpleNamespace) -> None:
    marker = env.company / "_client_slots" / ".rotation_in_progress"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("2026-06-10T03:30:00")

    assert rotation_in_progress(env.settings) is True
    assert clear_stale_rotation_marker(env.settings) is True
    assert rotation_in_progress(env.settings) is False
    assert clear_stale_rotation_marker(env.settings) is False


async def test_seed_is_gated_and_idempotent(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from openexecutive import config

    monkeypatch.setattr(config, "get_settings", lambda: env.settings)

    env.settings.client_rotation_enabled = False
    assert seed_client_rotation() is None

    env.settings.client_rotation_enabled = True
    first = seed_client_rotation()
    assert isinstance(first, int)
    # Pending row suppresses a duplicate.
    assert seed_client_rotation() is None

    import sqlite3

    conn = sqlite3.connect(str(env.db_path))
    rows = conn.execute(
        "SELECT kind, status FROM scheduled_actions WHERE kind='client_rotation'"
    ).fetchall()
    conn.close()
    assert rows == [("client_rotation", "pending")]


async def test_activation_reseeds_rotation_row(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Switching clients swaps the DB — the rotation row must follow."""
    from openexecutive import config

    monkeypatch.setattr(config, "get_settings", lambda: env.settings)

    await _practice(env, "Beta")
    import sqlite3

    conn = sqlite3.connect(str(env.db_path))
    n = conn.execute(
        "SELECT COUNT(*) FROM scheduled_actions WHERE kind='client_rotation' "
        "AND status='pending'"
    ).fetchone()[0]
    conn.close()
    # The last activation (back to acme) re-seeded into the live DB.
    assert n == 1


async def test_real_quiet_work_propagates_brief_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The unstubbed quiet-work helper must raise on brief failure so the
    digest never claims a brief that wasn't generated. (No env fixture here:
    that fixture stubs this very function — and the registry lookup fails
    before any DB/store access, so bare settings suffice.)"""
    from openexecutive import workflows as wf_pkg

    monkeypatch.setattr(wf_pkg, "WORKFLOW_REGISTRY", {})
    settings = SimpleNamespace(vector_store_path=tmp_path / "chroma")
    with pytest.raises(KeyError):
        await rotation._run_quiet_work_for_live_client(settings, "acme")
