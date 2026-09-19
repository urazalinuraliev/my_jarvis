"""Tests for the CandidateScreenWorkflow."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openexecutive.talent import store as talent_store
from openexecutive.talent.models import CandidateStage
from openexecutive.workflows.candidate_screen import (
    CandidateScreenInput,
    CandidateScreenWorkflow,
    _parse_fit_score,
)


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "talent.db"
    monkeypatch.setattr(talent_store, "DB_PATH", path)
    talent_store.initialize_db()
    return path


_ASSESSMENT = (
    "Fit score: 84/100 — directly led drilling through the 2020 downturn.\n\n"
    "**Evidence for fit**\n- 12 years upstream, cycle-tested.\n\n"
    "**Recommendation:** advance."
)


def _run(engagement_id: int, candidate_id: int) -> list:
    workflow = CandidateScreenWorkflow()
    inputs = CandidateScreenInput(engagement_id=engagement_id, candidate_id=candidate_id)
    store = MagicMock()
    events: list = []

    async def _collect() -> None:
        async for event in workflow.run(inputs=inputs, store=store):
            events.append(event)

    import asyncio

    with patch(
        "openexecutive.workflows.candidate_screen.route_to_specialist",
        new_callable=AsyncMock,
        return_value=_ASSESSMENT,
    ), patch(
        "openexecutive.workflows.candidate_screen.retrieve", return_value=""
    ):
        asyncio.run(_collect())
    return events


def _seed(db: Path) -> tuple[int, int]:
    eid = talent_store.upsert_engagement(
        role_title="VP Drilling", department="Drilling",
        must_haves="cycle-tested upstream lead",
    )
    cand_id = talent_store.upsert_candidate(engagement_id=eid, full_name="Dana Cole")
    return eid, cand_id


def test_screen_persists_score_and_advances(db: Path) -> None:
    eid, cand_id = _seed(db)
    events = _run(eid, cand_id)

    types = [e.type for e in events]
    assert "artifact" in types
    assert "error" not in types

    artifact = next(e for e in events if e.type == "artifact")
    assert "Dana Cole" in artifact.content
    assert "84/100" in artifact.content

    result = next(e for e in events if e.type == "result")
    assert result.data["fit_score"] == 84
    assert result.data["recorded"] is True

    cand = talent_store.get_candidate(cand_id)
    assert cand is not None
    assert cand.fit_score == 84
    assert cand.stage == CandidateStage.SCREENED


def test_screen_unknown_candidate_errors(db: Path) -> None:
    eid = talent_store.upsert_engagement(role_title="CFO", department="Finance")
    events = _run(eid, 9999)
    assert events[-1].type == "error"
    assert "Candidate 9999 not found" in events[-1].message


def test_screen_candidate_engagement_mismatch_errors(db: Path) -> None:
    eid1 = talent_store.upsert_engagement(role_title="CFO", department="Finance")
    eid2 = talent_store.upsert_engagement(role_title="COO", department="Ops")
    cand_id = talent_store.upsert_candidate(engagement_id=eid2, full_name="Dana")
    events = _run(eid1, cand_id)  # screen against the wrong engagement
    assert events[-1].type == "error"
    assert "belongs to engagement" in events[-1].message


def test_parse_fit_score_variants() -> None:
    # Only the mandated N/100 form is parsed.
    assert _parse_fit_score("Fit score: 84/100 — strong.") == 84
    assert _parse_fit_score("I'd put them at 73/100 overall.") == 73
    assert _parse_fit_score("") is None
    assert _parse_fit_score("No number anywhere here.") is None
    # Bare numbers without a /100 denominator are deliberately NOT parsed —
    # recording a wrong score is worse than skipping (caller emits artifact,
    # persists nothing).
    assert _parse_fit_score("Fit score: 82 — strong, no denominator.") is None
    assert _parse_fit_score("Overall score of 60.") is None
    # Out-of-range guarded: 250 is rejected, the valid /100 form wins instead.
    assert _parse_fit_score("ranked 250th; fit 45/100") == 45
    assert _parse_fit_score("I'd give 150/100 if I could; realistic fit: 82/100") == 82
    # Criteria-count language must not be mistaken for the score.
    assert _parse_fit_score("Fit score: 3/5 must-haves met; overall 82/100") == 82
    assert _parse_fit_score("Fit score: 4 of 5 met. I'd rate 75 overall.") is None
    # Qualifying text before the score doesn't capture the percentage.
    assert _parse_fit_score("Fit score: top 10% of candidates. Score: 82/100.") == 82


def test_screen_no_score_skips_persistence(db: Path) -> None:
    eid, cand_id = _seed(db)
    workflow = CandidateScreenWorkflow()
    inputs = CandidateScreenInput(engagement_id=eid, candidate_id=cand_id)
    events: list = []

    async def _collect() -> None:
        async for event in workflow.run(inputs=inputs, store=MagicMock()):
            events.append(event)

    import asyncio

    with patch(
        "openexecutive.workflows.candidate_screen.route_to_specialist",
        new_callable=AsyncMock,
        return_value="A qualitative read with no number at all.",
    ), patch("openexecutive.workflows.candidate_screen.retrieve", return_value=""):
        asyncio.run(_collect())

    result = next(e for e in events if e.type == "result")
    assert result.data["fit_score"] is None
    assert result.data["recorded"] is False
    # Candidate stays a lead, no score recorded.
    cand = talent_store.get_candidate(cand_id)
    assert cand is not None
    assert cand.fit_score is None
    assert cand.stage == CandidateStage.LEAD
