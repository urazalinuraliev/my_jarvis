"""The research addendum honors a Council research_focus override but keeps
the shared contract fixed; the research path passes the resolved knobs."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-not-used")

from openexecutive.agents import overrides as ov_mod  # noqa: E402
from openexecutive.monitoring.research import prompts as rp  # noqa: E402


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "research_focus_test.db"
    monkeypatch.setattr(ov_mod, "DB_PATH", db)
    ov_mod.invalidate_cache()
    yield db
    ov_mod.invalidate_cache()


def test_addendum_uses_code_default_when_no_override(isolated_db: Path) -> None:
    addendum = rp.research_addendum_for("cso")
    # Shared contract present + the default CSO focus.
    assert "## TASK: RESEARCH FINDINGS" in addendum
    assert "Chief Strategy Officer" in addendum


def test_addendum_uses_override_focus_when_set(isolated_db: Path) -> None:
    ov_mod.set_override(
        "cso",
        research_focus="\n\nCUSTOM FOCUS: only watch acme.com filings.",
        research_focus_set=True,
        db_path=isolated_db,
    )
    ov_mod.invalidate_cache()
    addendum = rp.research_addendum_for("cso")
    # Shared contract is ALWAYS present (not overridable).
    assert "## TASK: RESEARCH FINDINGS" in addendum
    assert "REQUIRED GROUNDING" in addendum
    # Custom focus replaces the code default.
    assert "CUSTOM FOCUS: only watch acme.com filings." in addendum
    assert "Chief Strategy Officer" not in addendum


def test_specialist_research_passes_resolved_knobs(
    isolated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """research_one_specialist routes through the research model + deep-reasoning
    knobs and the override-aware addendum."""
    from openexecutive.monitoring.research import specialist_research as sr

    # Pin the research knobs via a Council override on the `research` agent.
    ov_mod.set_override(
        "research", model="claude-cheap-research", model_set=True, db_path=isolated_db
    )
    ov_mod.invalidate_cache()

    captured: dict = {}

    async def fake_analyze_with_tools(user_content: str, **kwargs: object) -> object:
        captured.update(kwargs)
        captured["user_content"] = user_content
        return SimpleNamespace(content=[])

    agent = SimpleNamespace(analyze_with_tools=AsyncMock(side_effect=fake_analyze_with_tools))
    # Web search off so the tool list is deterministic.
    monkeypatch.setattr(sr, "build_web_search_tool", lambda: None)

    asyncio.run(sr.research_one_specialist("cso", agent, "CONTEXT"))

    assert captured["model_override"] == "claude-cheap-research"
    assert captured["deep_reasoning_override"] is False
    assert "## TASK: RESEARCH FINDINGS" in captured["system_addendum"]
