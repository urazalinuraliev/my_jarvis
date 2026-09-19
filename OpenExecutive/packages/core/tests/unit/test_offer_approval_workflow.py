"""Tests for the OfferApprovalWorkflow (close-the-hire-loop).

The workflow drafts the package, persists the Offer, DMs the HIRING_SIGNOFF
approver, and pauses on a WaitForHumanEvent gate. The candidate is never the
DM recipient — the seeded candidate has an email so that assertion is real.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openexecutive.memory import episodic
from openexecutive.people import store as people_store
from openexecutive.people.models import AuthorityScope
from openexecutive.talent import store as talent_store
from openexecutive.talent.models import CandidateStage, OfferStatus
from openexecutive.workflows.offer_approval import (
    OfferApprovalInput,
    OfferApprovalWorkflow,
)
from openexecutive.workflows.wait_for_human import WaitForHumanEvent

CANDIDATE_EMAIL = "dana@example.com"


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


def _seed_candidate(stage: CandidateStage = CandidateStage.INTERVIEWED) -> int:
    eid = talent_store.upsert_engagement(
        role_title="VP Drilling", department="Drilling",
        comp_band="280-340k base + 0.4-0.6% equity",
        must_haves="cycle-tested upstream lead",
    )
    return talent_store.upsert_candidate(
        engagement_id=eid, full_name="Dana Cole", current_title="Drilling Director",
        current_company="Permian Co", email=CANDIDATE_EMAIL, stage=stage,
    )


def _seed_principal(*, email: str = "boss@example.com") -> int:
    return people_store.upsert_person(
        full_name="Alex Rivera", is_principal=True, email=email,
        preferred_channel="email",  # type: ignore[arg-type]
    )


def _seed_signoff_approver(*, slack: str = "U999") -> int:
    pid = people_store.upsert_person(
        full_name="Morgan Hale", role="Head of People", slack_user_id=slack,
        preferred_channel="slack",  # type: ignore[arg-type]
        response_sla_hours=4,
    )
    people_store.set_authority_scope(pid, [AuthorityScope.HIRING_SIGNOFF])
    return pid


def _run(candidate_id: int, *, dm_mock: AsyncMock | None = None) -> list:
    workflow = OfferApprovalWorkflow()
    inputs = OfferApprovalInput(candidate_id=candidate_id, comp_notes="top of band")
    events: list = []
    dm = dm_mock or AsyncMock(return_value=json.dumps({"status": "sent"}))

    async def _collect() -> None:
        async for ev in workflow.run(inputs=inputs, store=MagicMock()):
            events.append(ev)

    with patch(
        "openexecutive.workflows.offer_approval.route_to_specialist",
        AsyncMock(side_effect=["TERMS_BODY", "CLOSE_PLAN_BODY"]),
    ), patch(
        "openexecutive.workflows.offer_approval.retrieve", return_value=""
    ), patch(
        "openexecutive.orchestrator.schedule_tools.handle_message_person", dm,
    ):
        asyncio.run(_collect())
    return events


def test_happy_path_pauses_on_gate_for_the_approver(db: Path) -> None:
    cand_id = _seed_candidate()
    _seed_principal()
    approver_id = _seed_signoff_approver()
    dm = AsyncMock(return_value=json.dumps({"status": "sent"}))

    events = _run(cand_id, dm_mock=dm)

    assert "error" not in [getattr(e, "type", None) for e in events]

    # The run ends on the gate, addressed to the delegated approver (not the
    # principal, who is sorted after delegated humans by find_approvers).
    gate = events[-1]
    assert isinstance(gate, WaitForHumanEvent)
    assert gate.person_id == approver_id
    assert gate.expected_reply_shape == "approve_reject"
    assert gate.context_summary.startswith("offer_id=")
    assert gate.on_timeout == "escalate"

    # The offer row is persisted pending approval with the package attached.
    offer = talent_store.get_open_offer_for_candidate(cand_id)
    assert offer is not None
    assert offer.status is OfferStatus.PENDING_APPROVAL
    assert offer.comp_summary == "top of band"
    assert "TERMS_BODY" in offer.package_md and "CLOSE_PLAN_BODY" in offer.package_md
    assert gate.context_summary.startswith(f"offer_id={offer.id}")

    # Candidate advanced interviewed -> offer.
    cand = talent_store.get_candidate(cand_id)
    assert cand is not None and cand.stage is CandidateStage.OFFER

    # The sign-off DM went to the approver — never to the candidate's email.
    dm.assert_awaited_once()
    dm_input = dm.await_args.args[0]
    assert dm_input["person_id"] == approver_id
    assert CANDIDATE_EMAIL not in dm_input["text"]

    # result + artifact were yielded BEFORE the gate (the runner stops there).
    types = [getattr(e, "type", "gate") for e in events]
    assert types.index("result") < len(events) - 1
    assert types.index("artifact") < len(events) - 1
    result = next(e for e in events if getattr(e, "type", "") == "result")
    assert result.data["offer_id"] == offer.id
    assert result.data["approver_person_id"] == approver_id


def test_falls_back_to_principal_when_no_scoped_approver(db: Path) -> None:
    cand_id = _seed_candidate()
    principal_id = _seed_principal()

    events = _run(cand_id)
    gate = events[-1]
    assert isinstance(gate, WaitForHumanEvent)
    assert gate.person_id == principal_id


def test_refuses_unscreened_candidate(db: Path) -> None:
    cand_id = _seed_candidate(stage=CandidateStage.LEAD)
    _seed_principal()

    events = _run(cand_id)
    assert events[-1].type == "error"
    assert "screen and interview" in events[-1].message
    assert talent_store.list_offers(candidate_id=cand_id) == []


def test_refuses_when_open_offer_exists(db: Path) -> None:
    cand_id = _seed_candidate()
    _seed_principal()
    cand = talent_store.get_candidate(cand_id)
    assert cand is not None
    talent_store.create_offer(
        candidate_id=cand_id, engagement_id=cand.engagement_id, comp_summary="x"
    )

    events = _run(cand_id)
    assert events[-1].type == "error"
    assert "already has an open offer" in events[-1].message


def test_errors_without_principal(db: Path) -> None:
    cand_id = _seed_candidate()
    events = _run(cand_id)
    assert events[-1].type == "error"
    assert "principal" in events[-1].message.lower()
