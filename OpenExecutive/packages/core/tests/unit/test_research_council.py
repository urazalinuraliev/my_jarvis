"""Tests for the `research` virtual agent and its model/deep-reasoning knobs."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-not-used")

from openexecutive.agents import overrides as ov_mod  # noqa: E402
from openexecutive.agents.research_council import (  # noqa: E402
    RESEARCH_AGENT_ID,
    ResearchCouncilAgent,
    get_research_model,
    get_research_use_deep_reasoning,
)
from openexecutive.config import get_settings  # noqa: E402


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "research_council_test.db"
    monkeypatch.setattr(ov_mod, "DB_PATH", db)
    ov_mod.invalidate_cache()
    yield db
    ov_mod.invalidate_cache()


def test_get_research_model_returns_settings_default_with_no_override(
    isolated_db: Path,
) -> None:
    assert get_research_model() == get_settings().research_model


def test_get_research_use_deep_reasoning_defaults_off(isolated_db: Path) -> None:
    assert get_research_use_deep_reasoning() is False


def test_get_research_model_returns_override_when_set(isolated_db: Path) -> None:
    ov_mod.set_override(
        RESEARCH_AGENT_ID,
        model="claude-opus-4-7",
        model_set=True,
        db_path=isolated_db,
    )
    ov_mod.invalidate_cache()
    assert get_research_model() == "claude-opus-4-7"


def test_get_research_deep_reasoning_honors_override(isolated_db: Path) -> None:
    ov_mod.set_override(
        RESEARCH_AGENT_ID,
        use_deep_reasoning=True,
        deep_set=True,
        db_path=isolated_db,
    )
    ov_mod.invalidate_cache()
    assert get_research_use_deep_reasoning() is True


def test_get_research_model_falls_back_when_override_clears_model(
    isolated_db: Path,
) -> None:
    # Override row exists but model is None — falls back to settings default.
    ov_mod.set_override(
        RESEARCH_AGENT_ID,
        use_deep_reasoning=True,
        deep_set=True,
        db_path=isolated_db,
    )
    ov_mod.invalidate_cache()
    assert get_research_model() == get_settings().research_model


def test_research_council_agent_class_default_matches_settings() -> None:
    agent = ResearchCouncilAgent()
    assert agent.model == get_settings().research_model
    assert agent.name == "research"
    assert agent.domain == "utility"
    assert agent.use_deep_reasoning is False
    assert agent.get_system_prompt() == ""
