"""MorningBriefWorkflow contract: it must use the STANDALONE brief prompt.

The morning brief is delivered as a DM with no cards beside it, so it must
enumerate actionables (standalone=True) rather than the /today header synthesis
that assumes a card list renders below it.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from openexecutive.api.routes import today as today_route
from openexecutive.api.routes.today import ActivityResponse, TodayResponse
from openexecutive.briefing import narrative as briefing_narrative
from openexecutive.workflows.morning_brief import (
    MorningBriefInput,
    MorningBriefWorkflow,
)


@pytest.mark.asyncio
async def test_morning_brief_uses_standalone_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def _synth(**kw: object) -> str:
        captured.update(kw)
        return "MORNING BRIEF BODY"

    monkeypatch.setattr(briefing_narrative, "synthesize_briefing_narrative", _synth)
    # Avoid touching the DB — stub the aggregators.
    monkeypatch.setattr(
        today_route, "_build_today",
        lambda: TodayResponse(departments=[], people=[], proposals=[]),
    )
    monkeypatch.setattr(
        today_route, "_build_activity", lambda limit: ActivityResponse(items=[])
    )

    wf = MorningBriefWorkflow()
    events = [
        e async for e in wf.run(MorningBriefInput(period_label="2026-05-29"), MagicMock())
    ]

    # The morning brief must request the standalone (enumerated) prompt.
    assert captured.get("standalone") is True
    assert captured.get("viewer") is None
    # And the synthesized body becomes the artifact.
    artifacts = [e for e in events if getattr(e, "type", "") == "artifact"]
    assert artifacts and "MORNING BRIEF BODY" in artifacts[0].content
