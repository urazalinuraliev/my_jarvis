"""Tests for the NewHireOnboardingWorkflow (placed → Person handoff)."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openexecutive.memory import episodic
from openexecutive.people import store as people_store
from openexecutive.talent import store as talent_store
from openexecutive.talent.models import CandidateStage, OfferStatus
from openexecutive.workflows.new_hire_onboarding import (
    NewHireOnboardingInput,
    NewHireOnboardingWorkflow,
)

HIRE_EMAIL = "dana@example.com"


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


def _seed_placed_candidate(
    stage: CandidateStage = CandidateStage.PLACED, email: str | None = HIRE_EMAIL
) -> int:
    eid = talent_store.upsert_engagement(
        role_title="VP Drilling", department="Drilling",
        must_haves="cycle-tested upstream lead",
    )
    return talent_store.upsert_candidate(
        engagement_id=eid, full_name="Dana Cole", email=email, stage=stage,
    )


def _seed_principal() -> int:
    return people_store.upsert_person(
        full_name="Alex Rivera", is_principal=True, email="boss@example.com",
        preferred_channel="email",  # type: ignore[arg-type]
    )


def _run(candidate_id: int, start_date: str = "") -> list:
    workflow = NewHireOnboardingWorkflow()
    inputs = NewHireOnboardingInput(candidate_id=candidate_id, start_date=start_date)
    events: list = []

    async def _collect() -> None:
        async for ev in workflow.run(inputs=inputs, store=MagicMock()):
            events.append(ev)

    with patch(
        "openexecutive.workflows.new_hire_onboarding.route_to_specialist",
        AsyncMock(return_value="PLAN_BODY"),
    ), patch("openexecutive.workflows.new_hire_onboarding.retrieve", return_value=""):
        asyncio.run(_collect())
    return events


def test_creates_person_and_schedules_checkins_to_principal(db: Path) -> None:
    cand_id = _seed_placed_candidate()
    principal_id = _seed_principal()

    events = _run(cand_id)
    assert "error" not in [e.type for e in events]

    result = next(e for e in events if e.type == "result")
    assert result.data["person_created"] is True

    # Person mapped from candidate + engagement; no authority scopes granted.
    person = people_store.get_person(result.data["person_id"])
    assert person is not None
    assert person.full_name == "Dana Cole"
    assert person.role == "VP Drilling"
    assert person.email == HIRE_EMAIL
    assert person.is_principal is False
    assert person.authority_scope == []
    # "Drilling" is free text that doesn't resolve to a department slug here.
    assert person.department_slugs == []

    # All four check-ins (start = today, so day 7/30/60/90 are in the future),
    # each assigned to the principal — never the hire.
    assert result.data["scheduled_count"] == 4
    pending = episodic.list_scheduled_actions(status="pending")
    assert len(pending) == 4
    for action in pending:
        assert action.assigned_to_person_id == principal_id
        assert action.kind == "ad_hoc"
        assert action.channel_ref != HIRE_EMAIL
        assert "Do NOT contact the new hire" in action.intent_text

    artifact = next(e for e in events if e.type == "artifact")
    assert "PLAN_BODY" in artifact.content


def test_idempotent_rerun_updates_instead_of_duplicating(db: Path) -> None:
    cand_id = _seed_placed_candidate()
    _seed_principal()

    first = _run(cand_id)
    second = _run(cand_id)
    assert "error" not in [e.type for e in second]

    first_id = next(e for e in first if e.type == "result").data["person_id"]
    second_result = next(e for e in second if e.type == "result")
    assert second_result.data["person_id"] == first_id
    assert second_result.data["person_created"] is False

    hires = [p for p in people_store.list_people() if p.full_name == "Dana Cole"]
    assert len(hires) == 1


def test_matches_existing_person_by_name_when_no_email(db: Path) -> None:
    cand_id = _seed_placed_candidate(email=None)
    _seed_principal()
    existing = people_store.upsert_person(full_name="Dana Cole", role="Consultant")

    events = _run(cand_id)
    result = next(e for e in events if e.type == "result")
    assert result.data["person_id"] == existing
    assert result.data["person_created"] is False
    person = people_store.get_person(existing)
    assert person is not None and person.role == "VP Drilling"


def test_refuses_unplaced_candidate_without_accepted_offer(db: Path) -> None:
    cand_id = _seed_placed_candidate(stage=CandidateStage.INTERVIEWED)
    _seed_principal()

    events = _run(cand_id)
    assert events[-1].type == "error"
    assert "record the offer acceptance" in events[-1].message
    assert all(p.full_name != "Dana Cole" for p in people_store.list_people())


def test_accepted_offer_qualifies_even_before_stage_moves(db: Path) -> None:
    cand_id = _seed_placed_candidate(stage=CandidateStage.OFFER)
    _seed_principal()
    cand = talent_store.get_candidate(cand_id)
    assert cand is not None
    oid = talent_store.create_offer(
        candidate_id=cand_id, engagement_id=cand.engagement_id, comp_summary="x"
    )
    talent_store.set_offer_status(oid, OfferStatus.EXTENDED)
    talent_store.set_offer_status(oid, OfferStatus.ACCEPTED)

    events = _run(cand_id)
    assert "error" not in [e.type for e in events]


def test_past_milestones_are_skipped(db: Path) -> None:
    cand_id = _seed_placed_candidate()
    _seed_principal()
    # Started 45 days ago: day-7 and day-30 check-ins are in the past.
    start = (datetime.now(UTC) - timedelta(days=45)).date().isoformat()

    events = _run(cand_id, start_date=start)
    result = next(e for e in events if e.type == "result")
    assert result.data["scheduled_count"] == 2  # day 60 + day 90 only


def test_bad_start_date_errors(db: Path) -> None:
    cand_id = _seed_placed_candidate()
    _seed_principal()
    events = _run(cand_id, start_date="not-a-date")
    assert events[-1].type == "error"
    assert "ISO date" in events[-1].message


def test_rehire_into_new_department_replaces_stale_slugs(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A re-hire whose engagement resolves to a real department must not keep
    the old department_slugs (the engagement is the source of truth for the
    new role, same as `role`)."""
    from openexecutive.workflows import new_hire_onboarding as wf_module

    cand_id = _seed_placed_candidate()
    _seed_principal()
    existing = people_store.upsert_person(
        full_name="Dana Cole", role="Sales Lead", email=HIRE_EMAIL,
        department_slugs=["sales"],
    )
    monkeypatch.setattr(
        wf_module, "_resolvable_department_slugs", lambda _eng: ["engineering"]
    )

    events = _run(cand_id)
    assert "error" not in [e.type for e in events]
    person = people_store.get_person(existing)
    assert person is not None
    assert person.department_slugs == ["engineering"]
    assert person.role == "VP Drilling"
