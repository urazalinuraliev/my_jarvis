"""Tests for the offer chat tools (list/create/extend/record_offer_decision)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from openexecutive.memory import episodic
from openexecutive.orchestrator.talent_tools import (
    TALENT_TOOL_HANDLERS,
    handle_create_offer,
    handle_extend_offer,
    handle_list_offers,
    handle_record_offer_decision,
    handle_set_candidate_stage,
)
from openexecutive.people import store as people_store
from openexecutive.talent import store as talent_store
from openexecutive.talent.models import CandidateStage, EngagementStatus, OfferStatus
from openexecutive.workflows import persistence as wf_persistence


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Shared episodic_memory.db; persistence.DB_PATH is a separate import-time
    binding from episodic.DB_PATH, so it needs its own monkeypatch."""
    path = tmp_path / "shared.db"
    monkeypatch.setattr(talent_store, "DB_PATH", path)
    monkeypatch.setattr(people_store, "DB_PATH", path)
    monkeypatch.setattr(episodic, "DB_PATH", path)
    monkeypatch.setattr(wf_persistence, "DB_PATH", path)
    episodic.initialize_db(path)
    people_store.initialize_db(path)
    talent_store.initialize_db(path)
    wf_persistence.initialize_runs_db(path)
    return path


def _seed_candidate(stage: CandidateStage = CandidateStage.INTERVIEWED) -> int:
    eid = talent_store.upsert_engagement(role_title="VP Drilling", comp_band="300k")
    return talent_store.upsert_candidate(
        engagement_id=eid, full_name="Dana Cole", email="dana@example.com", stage=stage,
    )


def _seed_principal() -> int:
    return people_store.upsert_person(
        full_name="Alex Rivera", is_principal=True, email="boss@example.com",
        preferred_channel="email",  # type: ignore[arg-type]
    )


def _create_offer(candidate_id: int) -> dict:
    return json.loads(asyncio.run(handle_create_offer({
        "candidate_id": candidate_id, "comp_summary": "base 300k, 0.5% equity",
    })))


def test_all_offer_tools_registered() -> None:
    for name in ("list_offers", "create_offer", "extend_offer", "record_offer_decision"):
        assert name in TALENT_TOOL_HANDLERS


# --------------------------------------------------------------------------- #
# create_offer / list_offers
# --------------------------------------------------------------------------- #

def test_create_offer_happy_path(db: Path) -> None:
    cand_id = _seed_candidate()
    out = _create_offer(cand_id)
    assert out["status"] == "ok"
    assert out["offer"]["status"] == "draft"
    assert out["offer"]["candidate_id"] == cand_id
    assert "never sends offers" in out["presentation_hint"]


def test_create_offer_unknown_candidate(db: Path) -> None:
    out = json.loads(asyncio.run(handle_create_offer({
        "candidate_id": 999, "comp_summary": "x",
    })))
    assert out["status"] == "not_found"


def test_create_offer_rejects_duplicate_open_offer(db: Path) -> None:
    cand_id = _seed_candidate()
    _create_offer(cand_id)
    out = json.loads(asyncio.run(handle_create_offer({
        "candidate_id": cand_id, "comp_summary": "y",
    })))
    assert "already has an open offer" in out["error"]


def test_create_offer_length_cap(db: Path) -> None:
    cand_id = _seed_candidate()
    out = json.loads(asyncio.run(handle_create_offer({
        "candidate_id": cand_id, "comp_summary": "x" * 8001,
    })))
    assert "too long" in out["error"]


def test_list_offers_filters_by_status(db: Path) -> None:
    cand_id = _seed_candidate()
    _create_offer(cand_id)
    out = json.loads(asyncio.run(handle_list_offers({"status": "draft"})))
    assert out["count"] == 1
    out = json.loads(asyncio.run(handle_list_offers({"status": "extended"})))
    assert out["count"] == 0
    out = json.loads(asyncio.run(handle_list_offers({"status": "bogus"})))
    assert "invalid status" in out["error"]


# --------------------------------------------------------------------------- #
# extend_offer
# --------------------------------------------------------------------------- #

def test_extend_offer_schedules_expiry_nudges_to_principal(db: Path) -> None:
    cand_id = _seed_candidate()
    principal_id = _seed_principal()
    offer_id = _create_offer(cand_id)["offer"]["offer_id"]

    out = json.loads(asyncio.run(handle_extend_offer({
        "offer_id": offer_id, "expires_in_days": 7,
    })))
    assert out["status"] == "ok"
    assert out["offer"]["status"] == "extended"
    assert out["offer"]["expires_at"]
    # No approval run exists — flagged, not blocked (principal's terminal).
    assert out["approval_state"] == "none"
    assert any("without a recorded HIRING_SIGNOFF" in w for w in out["warnings"])

    # T-3d and T-1d are future (7-day expiry), plus the T+12h past-expiry nudge.
    assert out["nudges_scheduled"] == 3
    pending = episodic.list_scheduled_actions(status="pending")
    assert len(pending) == 3
    for action in pending:
        assert action.kind == "ad_hoc"
        assert action.assigned_to_person_id == principal_id
        assert "dana@example.com" not in action.channel_ref


def test_extend_offer_short_expiry_skips_past_nudges(db: Path) -> None:
    cand_id = _seed_candidate()
    _seed_principal()
    offer_id = _create_offer(cand_id)["offer"]["offer_id"]

    out = json.loads(asyncio.run(handle_extend_offer({
        "offer_id": offer_id, "expires_in_days": 2,
    })))
    # T-3d is already past; only T-1d and T+12h get scheduled.
    assert out["nudges_scheduled"] == 2


def test_extend_offer_blocked_by_recorded_rejection(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cand_id = _seed_candidate()
    _seed_principal()
    offer_id = _create_offer(cand_id)["offer"]["offer_id"]

    from openexecutive.talent import offers as talent_offers
    monkeypatch.setattr(
        talent_offers, "find_offer_approval",
        lambda _oid: {"run_id": "r1", "status": "resolved", "decision": "reject", "person_id": 2},
    )
    out = json.loads(asyncio.run(handle_extend_offer({"offer_id": offer_id})))
    assert "rejected" in out["error"]
    offer = talent_store.get_offer(offer_id)
    assert offer is not None and offer.status is OfferStatus.DRAFT


def test_extend_offer_stamps_recorded_approval(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cand_id = _seed_candidate()
    _seed_principal()
    offer_id = _create_offer(cand_id)["offer"]["offer_id"]

    from openexecutive.talent import offers as talent_offers
    monkeypatch.setattr(
        talent_offers, "find_offer_approval",
        lambda _oid: {"run_id": "r1", "status": "resolved", "decision": "approve", "person_id": 7},
    )
    out = json.loads(asyncio.run(handle_extend_offer({"offer_id": offer_id})))
    assert out["approval_state"] == "approved"
    assert out["warnings"] == []
    offer = talent_store.get_offer(offer_id)
    assert offer is not None
    assert offer.approval_run_id == "r1"
    assert offer.approved_by_person_id == 7


def test_extend_offer_validates_inputs(db: Path) -> None:
    cand_id = _seed_candidate()
    _seed_principal()
    offer_id = _create_offer(cand_id)["offer"]["offer_id"]

    out = json.loads(asyncio.run(handle_extend_offer({"offer_id": offer_id, "expires_in_days": 0})))
    assert "1-60" in out["error"]
    out = json.loads(asyncio.run(handle_extend_offer({"offer_id": offer_id, "expires_at": "nope"})))
    assert "ISO" in out["error"]
    out = json.loads(asyncio.run(handle_extend_offer({"offer_id": 999})))
    assert "not found" in out["error"]


def test_extend_offer_without_principal_still_extends_with_warning(db: Path) -> None:
    cand_id = _seed_candidate()
    offer_id = _create_offer(cand_id)["offer"]["offer_id"]

    out = json.loads(asyncio.run(handle_extend_offer({"offer_id": offer_id})))
    assert out["status"] == "ok"
    assert out["nudges_scheduled"] == 0
    assert any("no expiry reminders" in w.lower() for w in out["warnings"])


# --------------------------------------------------------------------------- #
# record_offer_decision
# --------------------------------------------------------------------------- #

def _extended_offer(cand_id: int) -> int:
    offer_id = _create_offer(cand_id)["offer"]["offer_id"]
    json.loads(asyncio.run(handle_extend_offer({"offer_id": offer_id})))
    return offer_id


def test_accepted_places_candidate_fills_engagement_and_cancels_nudges(db: Path) -> None:
    cand_id = _seed_candidate()
    _seed_principal()
    offer_id = _extended_offer(cand_id)
    assert len(episodic.list_scheduled_actions(status="pending")) == 3

    out = json.loads(asyncio.run(handle_record_offer_decision({
        "offer_id": offer_id, "decision": "accepted",
    })))
    assert out["status"] == "ok"
    assert out["offer"]["status"] == "accepted"
    assert out["cancelled_nudges"] == 3
    assert "new_hire_onboarding" in out["next_step"]

    cand = talent_store.get_candidate(cand_id)
    assert cand is not None and cand.stage is CandidateStage.PLACED
    eng = talent_store.get_engagement(cand.engagement_id)
    assert eng is not None and eng.status is EngagementStatus.FILLED
    assert episodic.list_scheduled_actions(status="pending") == []


def test_declined_leaves_candidate_stage_untouched(db: Path) -> None:
    cand_id = _seed_candidate()
    _seed_principal()
    offer_id = _extended_offer(cand_id)

    out = json.loads(asyncio.run(handle_record_offer_decision({
        "offer_id": offer_id, "decision": "declined", "note": "took a competing offer",
    })))
    assert out["status"] == "ok"
    assert out["side_effects"] == []
    assert "next_step" not in out
    cand = talent_store.get_candidate(cand_id)
    assert cand is not None and cand.stage is CandidateStage.INTERVIEWED


def test_decision_requires_legal_transition(db: Path) -> None:
    cand_id = _seed_candidate()
    offer_id = _create_offer(cand_id)["offer"]["offer_id"]  # still draft

    out = json.loads(asyncio.run(handle_record_offer_decision({
        "offer_id": offer_id, "decision": "accepted",
    })))
    assert "not a legal transition" in out["error"]
    # Rescind, however, is legal straight from draft.
    out = json.loads(asyncio.run(handle_record_offer_decision({
        "offer_id": offer_id, "decision": "rescinded",
    })))
    assert out["status"] == "ok"


def test_decision_rejects_non_terminal_value(db: Path) -> None:
    cand_id = _seed_candidate()
    _seed_principal()
    offer_id = _extended_offer(cand_id)
    out = json.loads(asyncio.run(handle_record_offer_decision({
        "offer_id": offer_id, "decision": "draft",
    })))
    assert "must be terminal" in out["error"]


# --------------------------------------------------------------------------- #
# set_candidate_stage suggestion
# --------------------------------------------------------------------------- #

def test_set_stage_placed_suggests_offer_and_onboarding(db: Path) -> None:
    cand_id = _seed_candidate()
    out = json.loads(asyncio.run(handle_set_candidate_stage({
        "candidate_id": cand_id, "stage": "placed",
    })))
    assert out["status"] == "ok"
    assert "record_offer_decision" in out["onboarding_suggestion"]
    assert "new_hire_onboarding" in out["onboarding_suggestion"]
    # And the suggestion stays read-only: no offer rows, stage is the only write.
    assert talent_store.list_offers(candidate_id=cand_id) == []

    out = json.loads(asyncio.run(handle_set_candidate_stage({
        "candidate_id": cand_id, "stage": "interviewed",
    })))
    assert "onboarding_suggestion" not in out


def test_recorded_rejection_survives_failed_run_noise(db: Path) -> None:
    """find_offer_approval must not let failed runs push a recorded rejection
    out of its scan window (it scans per gate-relevant status)."""
    import json as _json

    from openexecutive.talent.offers import offer_approval_state
    from openexecutive.workflows.wait_for_human import (
        WaitForHumanEvent,
        WaitForHumanResolution,
    )

    cand_id = _seed_candidate()
    offer_id = _create_offer(cand_id)["offer"]["offer_id"]

    gate_run = "gate-run-1"
    wf_persistence.create_run(gate_run, "offer_approval", "gate", {})
    wf_persistence.save_checkpoint(
        run_id=gate_run,
        state_json=WaitForHumanEvent(
            person_id=1,
            question="approve?",
            context_summary=f"offer_id={offer_id} — offer approval for Dana Cole (VP Drilling)",
        ).model_dump_json(),
        awaiting_person_id=1,
        awaiting_until=None,
    )
    wf_persistence.store_resolution(
        gate_run,
        _json.dumps(
            WaitForHumanResolution(
                run_id=gate_run, reply_text="no", source_channel="slack",
                parsed_decision={"decision": "reject", "note": "comp too high"},
                person_id=1,
            ).model_dump()
        ),
    )
    # Bury the resolved gate under a pile of newer failed offer_approval runs
    # (more than one scan window's worth).
    for n in range(250):
        rid = f"failed-{n}"
        wf_persistence.create_run(rid, "offer_approval", "boom", {})
        wf_persistence.fail_run(rid, "exploded before the gate")

    assert offer_approval_state(offer_id) == "rejected"
    out = json.loads(asyncio.run(handle_extend_offer({"offer_id": offer_id})))
    assert "rejected" in out["error"]
