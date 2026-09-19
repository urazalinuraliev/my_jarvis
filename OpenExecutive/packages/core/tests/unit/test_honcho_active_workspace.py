"""Active-workspace override for Honcho.

Used to isolate demo-fixture traffic from the operator's real Honcho
data. ``set_active_workspace_id`` writes a state file under
``_user_backup/.honcho_active_workspace.json``; ``get_active_workspace_id``
reads it (falling back to ``settings.honcho_workspace_id`` when absent
or unreadable); ``clear_active_workspace_id`` removes it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from openexecutive.memory import honcho_client


@pytest.fixture(autouse=True)
def _required_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Minimal env so get_settings() succeeds; point company profile at tmp."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("EXEC_EMAIL_ADDRESS", "exec@example.com")
    monkeypatch.setenv("COMPANY_PROFILE_PATH", str(tmp_path / "company" / "profile.yaml"))
    monkeypatch.setenv("HONCHO_WORKSPACE_ID", "openexec-test")
    # Drop any cached client/state from prior tests.
    honcho_client.reset_client_for_tests()
    return tmp_path


def test_active_workspace_defaults_to_env(_required_env: Path) -> None:
    """No state file → env-default workspace_id."""
    assert honcho_client.get_active_workspace_id() == "openexec-test"


def test_set_active_workspace_id_persists_and_overrides(_required_env: Path) -> None:
    honcho_client.set_active_workspace_id(
        "openexec-fixture-bombas-a1b2c3d4", fixture_name="bombas"
    )
    assert honcho_client.get_active_workspace_id() == "openexec-fixture-bombas-a1b2c3d4"

    # File should exist on disk under the company profile's _user_backup.
    state_path = honcho_client._active_workspace_state_path()
    assert state_path.exists()
    import json
    payload = json.loads(state_path.read_text())
    assert payload["workspace_id"] == "openexec-fixture-bombas-a1b2c3d4"
    assert payload["fixture_name"] == "bombas"
    assert "set_at" in payload


def test_clear_active_workspace_id_falls_back_to_env(_required_env: Path) -> None:
    honcho_client.set_active_workspace_id("openexec-fixture-x-1234")
    assert honcho_client.get_active_workspace_id() == "openexec-fixture-x-1234"
    honcho_client.clear_active_workspace_id()
    assert honcho_client.get_active_workspace_id() == "openexec-test"


def test_corrupt_state_file_falls_back_to_env(_required_env: Path) -> None:
    """A corrupt JSON file must NOT break Honcho calls — fall back silently."""
    state_path = honcho_client._active_workspace_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("{not valid json")
    assert honcho_client.get_active_workspace_id() == "openexec-test"


def test_set_active_workspace_id_drops_cached_clients(_required_env: Path) -> None:
    """After switching workspaces, the next _get_client must rebuild."""
    fake = object()
    # Simulate a cached client.
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        honcho_client._clients[loop] = fake  # type: ignore[assignment]
        honcho_client.set_active_workspace_id("openexec-fixture-x")
        assert loop not in honcho_client._clients
    finally:
        loop.close()
