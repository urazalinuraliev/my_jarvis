"""Tests for the utility_fast virtual agent and get_fast_model() helper."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-not-used")

from openexecutive.agents import overrides as ov_mod  # noqa: E402
from openexecutive.agents.utility_fast import (  # noqa: E402
    UTILITY_FAST_AGENT_ID,
    UtilityFastAgent,
    get_fast_model,
)
from openexecutive.config import get_settings  # noqa: E402


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the overrides module at a temp DB and invalidate its cache."""
    db = tmp_path / "utility_fast_test.db"
    monkeypatch.setattr(ov_mod, "DB_PATH", db)
    ov_mod.invalidate_cache()
    yield db
    ov_mod.invalidate_cache()


def test_get_fast_model_returns_routing_default_with_no_override(
    isolated_db: Path,
) -> None:
    assert get_fast_model() == get_settings().routing_model


def test_get_fast_model_returns_override_when_set(isolated_db: Path) -> None:
    ov_mod.set_override(
        UTILITY_FAST_AGENT_ID,
        model="claude-sonnet-4-6",
        model_set=True,
        db_path=isolated_db,
    )
    ov_mod.invalidate_cache()
    assert get_fast_model() == "claude-sonnet-4-6"


def test_get_fast_model_falls_back_when_override_clears_model(
    isolated_db: Path,
) -> None:
    # Override row exists but model is None — falls back to settings default.
    ov_mod.set_override(
        UTILITY_FAST_AGENT_ID,
        role="something",
        role_set=True,
        db_path=isolated_db,
    )
    ov_mod.invalidate_cache()
    assert get_fast_model() == get_settings().routing_model


def test_utility_fast_agent_class_default_matches_settings() -> None:
    # Instantiating picks up the runtime ROUTING_MODEL value.
    agent = UtilityFastAgent()
    assert agent.model == get_settings().routing_model
    assert agent.name == "utility_fast"
    assert agent.domain == "utility"
    assert agent.get_system_prompt() == ""


def test_allowed_models_for_utility_fast_has_no_special_extras(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After the free-model-matrix trim, utility_fast gets the SAME allowlist
    as any other agent — no owl-alpha / :free leaf-model extras, with
    OpenRouter on or off."""
    from types import SimpleNamespace

    from openexecutive.providers.registry import allowed_models_for

    monkeypatch.setattr(
        "openexecutive.providers.registry.get_settings",
        lambda: SimpleNamespace(openrouter_enabled=True),
    )
    assert allowed_models_for("utility_fast") == allowed_models_for("cso")
    assert "openrouter/owl-alpha" not in allowed_models_for("utility_fast")

    monkeypatch.setattr(
        "openexecutive.providers.registry.get_settings",
        lambda: SimpleNamespace(openrouter_enabled=False),
    )
    assert allowed_models_for("utility_fast") == allowed_models_for("cso")
