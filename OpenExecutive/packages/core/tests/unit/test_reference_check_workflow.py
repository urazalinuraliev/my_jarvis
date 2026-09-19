"""Tests for the ReferenceCheckWorkflow."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openexecutive.memory import episodic
from openexecutive.people import store as people_store
from openexecutive.talent import store as talent_store
from openexecutive.workflows.reference_check import (
    ReferenceCheckInput,
    ReferenceCheckWorkflow,
)

CANDIDATE_EMAIL = "dana@example.com"


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "shared.db"
    monkeypatch.setattr(talent_store, "DB_PATH", path)
    monkeypatch.setattr(people_store, "DB_PATH", path)
    monkeypatch.setattr(episodic, "DB_PATH", path)
    episodic.initialize_db(path)
    people_store.initialize_db(path)
    talent_store.initialize_db(path)
    return path


def _seed_candidate() -> int:
    eid = talent_store.upsert_engagement(role_title="VP Drilling", department="Drilling")
    return talent_store.upsert_candidate(
        engagement_id=eid, full_name="Dana Cole", email=CANDIDATE_EMAIL,
    )


def _seed_principal() -> int:
    return people_store.upsert_person(
        full_name="Alex Rivera", is_principal=True, email="boss@example.com",
        preferred_channel="email",
    )


def _run(candidate_id: int, reference_count: int = 2) -> list:
    workflow = ReferenceCheckWorkflow()
    inputs = ReferenceCheckInput(candidate_id=candidate_id, reference_count=reference_count)
    events: list = []

    async def _collect() -> None:
        async for ev in workflow.run(inputs=inputs, store=MagicMock()):
            events.append(ev)

    with patch(
        "openexecutive.workflows.reference_check.route_to_specialist",
        new_callable=AsyncMock,
        side_effect=["RUBRIC_BODY", "OUTREACH_BODY"],
    ), patch("openexecutive.workflows.reference_check.retrieve", return_value=""):
        asyncio.run(_collect())
    return events


def test_schedules_one_reminder_to_principal(db: Path) -> None:
    cand_id = _seed_candidate()
    pid = _seed_principal()
    events = _run(cand_id)
    assert "error" not in [e.type for e in events]
    assert next(e for e in events if e.type == "result").data["scheduled_count"] == 1

    actions = episodic.list_scheduled_actions()
    assert len(actions) == 1
    a = actions[0]
    assert a.assigned_to_person_id == pid
    assert a.channel_ref == "boss@example.com"
    assert a.channel_ref != CANDIDATE_EMAIL
    assert "Do NOT contact the references directly" in a.intent_text
    assert "RUBRIC_BODY" in a.intent_text
    assert "OUTREACH_BODY" in a.intent_text


def test_artifact_has_rubric_and_outreach(db: Path) -> None:
    cand_id = _seed_candidate()
    _seed_principal()
    artifact = next(e for e in _run(cand_id) if e.type == "artifact")
    assert "Reference Rubric" in artifact.content
    assert "Reference Outreach" in artifact.content
    assert "RUBRIC_BODY" in artifact.content
    assert "OUTREACH_BODY" in artifact.content


def test_unknown_candidate_errors(db: Path) -> None:
    _seed_principal()
    events = _run(9999)
    assert events[-1].type == "error"
    assert episodic.list_scheduled_actions() == []


def test_no_principal_schedules_nothing(db: Path) -> None:
    cand_id = _seed_candidate()
    events = _run(cand_id)
    assert events[-1].type == "error"
    assert episodic.list_scheduled_actions() == []
