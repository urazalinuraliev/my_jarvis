"""Tests for the CandidateOutreachWorkflow (Phase 3 recruiting automation)."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openexecutive.memory import episodic
from openexecutive.people import store as people_store
from openexecutive.talent import store as talent_store
from openexecutive.workflows.candidate_outreach import (
    CandidateOutreachInput,
    CandidateOutreachWorkflow,
)


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """One shared episodic_memory.db for talent + people + scheduled_actions."""
    path = tmp_path / "shared.db"
    monkeypatch.setattr(talent_store, "DB_PATH", path)
    monkeypatch.setattr(people_store, "DB_PATH", path)
    monkeypatch.setattr(episodic, "DB_PATH", path)
    episodic.initialize_db(path)
    people_store.initialize_db(path)
    talent_store.initialize_db(path)
    return path


CANDIDATE_EMAIL = "dana@example.com"


def _seed_candidate(db: Path) -> int:
    eid = talent_store.upsert_engagement(
        role_title="VP Drilling", department="Drilling",
        must_haves="cycle-tested upstream lead",
    )
    # Candidate HAS an email so the "never route to the candidate" assertion is
    # a real check, not trivially true.
    return talent_store.upsert_candidate(
        engagement_id=eid, full_name="Dana Cole", current_title="Drilling Director",
        current_company="Permian Co", email=CANDIDATE_EMAIL,
    )


def _seed_principal(*, email: str = "boss@example.com", preferred: str = "email") -> int:
    return people_store.upsert_person(
        full_name="Alex Rivera", is_principal=True, email=email,
        preferred_channel=preferred,  # type: ignore[arg-type]
    )


def _run(candidate_id: int, follow_up_count: int = 2) -> list:
    workflow = CandidateOutreachWorkflow()
    inputs = CandidateOutreachInput(
        candidate_id=candidate_id, follow_up_count=follow_up_count, follow_up_interval_days=3
    )
    events: list = []

    # Mock returns exactly one body per expected specialist call (first touch +
    # one per follow-up). Sized to the call count so an extra/missing call would
    # raise StopAsyncIteration rather than passing silently.
    bodies = ["FIRST_TOUCH_BODY"] + [f"FOLLOWUP_{k}_BODY" for k in range(1, follow_up_count + 1)]
    mock_specialist = AsyncMock(side_effect=bodies)

    async def _collect() -> None:
        async for ev in workflow.run(inputs=inputs, store=MagicMock()):
            events.append(ev)

    with patch(
        "openexecutive.workflows.candidate_outreach.route_to_specialist",
        mock_specialist,
    ), patch("openexecutive.workflows.candidate_outreach.retrieve", return_value=""):
        asyncio.run(_collect())
    # When the run reaches drafting, exactly 1 + follow_up_count calls are made.
    if events and events[-1].type != "error":
        assert mock_specialist.await_count == len(bodies)
    return events


def test_schedules_reminders_to_principal_not_candidate(db: Path) -> None:
    cand_id = _seed_candidate(db)
    principal_id = _seed_principal(email="boss@example.com")
    events = _run(cand_id, follow_up_count=2)

    assert "error" not in [e.type for e in events]
    result = next(e for e in events if e.type == "result")
    assert result.data["scheduled_count"] == 3  # first + 2 follow-ups

    actions = episodic.list_scheduled_actions()
    assert len(actions) == 3
    for a in actions:
        # Reminders go to the PRINCIPAL, never the candidate.
        assert a.assigned_to_person_id == principal_id
        assert a.channel == "email"
        assert a.channel_ref == "boss@example.com"
        # Real check now that the candidate HAS an email: no reminder is routed
        # to the candidate.
        assert a.channel_ref != CANDIDATE_EMAIL
        assert "Do NOT contact the candidate directly" in a.intent_text
        assert "Dana Cole" in a.intent_text

    # The drafted bodies are carried in the reminders.
    intents = " ".join(a.intent_text for a in actions)
    assert "FIRST_TOUCH_BODY" in intents
    assert "FOLLOWUP_1_BODY" in intents
    assert "FOLLOWUP_2_BODY" in intents


def test_artifact_contains_sequence(db: Path) -> None:
    cand_id = _seed_candidate(db)
    _seed_principal()
    events = _run(cand_id, follow_up_count=1)
    artifact = next(e for e in events if e.type == "artifact")
    assert "Outreach Sequence — Dana Cole" in artifact.content
    assert "First touch" in artifact.content
    assert "Follow-up 1" in artifact.content
    assert "FIRST_TOUCH_BODY" in artifact.content


def test_zero_follow_ups_schedules_only_first(db: Path) -> None:
    cand_id = _seed_candidate(db)
    _seed_principal()
    events = _run(cand_id, follow_up_count=0)
    assert next(e for e in events if e.type == "result").data["scheduled_count"] == 1
    assert len(episodic.list_scheduled_actions()) == 1


def test_unknown_candidate_errors(db: Path) -> None:
    _seed_principal()
    events = _run(9999)
    assert events[-1].type == "error"
    assert "Candidate 9999 not found" in events[-1].message
    assert episodic.list_scheduled_actions() == []


def test_no_principal_errors_and_schedules_nothing(db: Path) -> None:
    cand_id = _seed_candidate(db)
    # No principal seeded.
    events = _run(cand_id)
    assert events[-1].type == "error"
    assert "No principal configured" in events[-1].message
    assert episodic.list_scheduled_actions() == []


def test_principal_without_channel_errors(db: Path) -> None:
    cand_id = _seed_candidate(db)
    # Principal with no email/slack/etc. → no reachable channel.
    people_store.upsert_person(full_name="Alex", is_principal=True, preferred_channel="any")
    events = _run(cand_id)
    assert events[-1].type == "error"
    assert "no reachable channel" in events[-1].message
    assert episodic.list_scheduled_actions() == []


# (principal-channel resolution is covered in test_talent_reminders.py, where
# the helper now lives.)
