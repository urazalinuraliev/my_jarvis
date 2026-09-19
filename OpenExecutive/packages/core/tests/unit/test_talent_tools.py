"""Unit tests for openexecutive.orchestrator.talent_tools.

These chat tools let the Executive read the live talent pipeline and trigger the
talent workflows. The read/light-write handlers are covered here end to end; the
``start_talent_workflow`` happy path needs the Anthropic API + vector store, so
only its validation/error branches (which never reach the model) are exercised.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from openexecutive.orchestrator.talent_tools import (
    TALENT_TOOL_HANDLERS,
    TALENT_TOOLS,
    handle_create_candidate,
    handle_create_engagement,
    handle_get_candidate,
    handle_list_candidates,
    handle_list_engagements,
    handle_match_candidates,
    handle_set_candidate_stage,
    handle_start_talent_workflow,
)
from openexecutive.talent import graph as talent_graph
from openexecutive.talent import store as talent_store
from openexecutive.talent.models import CandidateStage


@pytest.fixture(autouse=True)
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "talent.db"
    monkeypatch.setattr(talent_store, "DB_PATH", path)
    talent_store.initialize_db()
    return path


def _call(fn: Callable[[dict[str, Any]], Awaitable[str]], payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(asyncio.run(fn(payload)))


def _seed() -> int:
    """Seed one engagement (a role we're hiring for) and return its id."""
    return talent_store.upsert_engagement(role_title="VP Drilling", department="Drilling")


# --------------------------------------------------------------------------- #
# list_engagements
# --------------------------------------------------------------------------- #


def test_list_engagements_rolls_up_pipeline() -> None:
    eid = _seed()
    talent_store.upsert_candidate(engagement_id=eid, full_name="Lead A", stage=CandidateStage.LEAD)
    talent_store.upsert_candidate(engagement_id=eid, full_name="Offeree", stage=CandidateStage.OFFER)

    out = _call(handle_list_engagements, {})
    assert out["count"] == 1
    eng = out["engagements"][0]
    assert eng["engagement_id"] == eid
    assert eng["candidate_count"] == 2
    assert eng["needs_screening"] == 1
    assert eng["offers_out"] == 1


def test_list_engagements_empty() -> None:
    out = _call(handle_list_engagements, {})
    assert out == {"engagements": [], "count": 0}


# --------------------------------------------------------------------------- #
# list_candidates
# --------------------------------------------------------------------------- #


def test_list_candidates_happy_and_stage_filter() -> None:
    eid = _seed()
    talent_store.upsert_candidate(engagement_id=eid, full_name="Lead A", stage=CandidateStage.LEAD)
    talent_store.upsert_candidate(engagement_id=eid, full_name="Offeree", stage=CandidateStage.OFFER)

    everyone = _call(handle_list_candidates, {"engagement_id": eid})
    assert everyone["count"] == 2

    only_offer = _call(handle_list_candidates, {"engagement_id": eid, "stage": "offer"})
    assert only_offer["count"] == 1
    assert only_offer["candidates"][0]["full_name"] == "Offeree"


def test_list_candidates_bad_engagement_id() -> None:
    out = _call(handle_list_candidates, {})
    assert "error" in out


def test_list_candidates_invalid_stage() -> None:
    eid = _seed()
    out = _call(handle_list_candidates, {"engagement_id": eid, "stage": "bogus"})
    assert "error" in out
    assert "invalid stage" in out["error"]


# --------------------------------------------------------------------------- #
# get_candidate
# --------------------------------------------------------------------------- #


def test_get_candidate_found_and_missing() -> None:
    eid = _seed()
    cand_id = talent_store.upsert_candidate(engagement_id=eid, full_name="Jane Roe")

    found = _call(handle_get_candidate, {"candidate_id": cand_id})
    assert found["candidate"]["full_name"] == "Jane Roe"

    missing = _call(handle_get_candidate, {"candidate_id": 9999})
    assert missing["status"] == "not_found"


def test_get_candidate_bad_input() -> None:
    out = _call(handle_get_candidate, {"candidate_id": "not-an-int"})
    assert "error" in out


# --------------------------------------------------------------------------- #
# set_candidate_stage
# --------------------------------------------------------------------------- #


def test_set_candidate_stage_happy() -> None:
    eid = _seed()
    cand_id = talent_store.upsert_candidate(engagement_id=eid, full_name="Jane Roe")

    out = _call(handle_set_candidate_stage, {"candidate_id": cand_id, "stage": "interviewed"})
    assert out["status"] == "ok"
    assert out["stage"] == "interviewed"
    assert talent_store.get_candidate(cand_id).stage == CandidateStage.INTERVIEWED  # type: ignore[union-attr]


def test_set_candidate_stage_not_found() -> None:
    out = _call(handle_set_candidate_stage, {"candidate_id": 9999, "stage": "offer"})
    assert out["status"] == "not_found"


def test_set_candidate_stage_invalid_stage() -> None:
    eid = _seed()
    cand_id = talent_store.upsert_candidate(engagement_id=eid, full_name="Jane Roe")
    out = _call(handle_set_candidate_stage, {"candidate_id": cand_id, "stage": "promoted"})
    assert "error" in out


# --------------------------------------------------------------------------- #
# match_candidates (error branches that don't hit the vector store)
# --------------------------------------------------------------------------- #


def test_match_candidates_bad_input() -> None:
    out = _call(handle_match_candidates, {})
    assert "error" in out


def test_match_candidates_unknown_engagement() -> None:
    out = _call(handle_match_candidates, {"engagement_id": 4242})
    assert out["status"] == "not_found"


# --------------------------------------------------------------------------- #
# start_talent_workflow (validation branches only)
# --------------------------------------------------------------------------- #


def test_start_talent_workflow_unknown_workflow() -> None:
    out = _call(handle_start_talent_workflow, {"workflow": "not_a_workflow", "inputs": {}})
    assert "error" in out


def test_start_talent_workflow_inputs_must_be_object() -> None:
    out = _call(handle_start_talent_workflow, {"workflow": "candidate_screen", "inputs": "nope"})
    assert "error" in out
    assert "inputs must be an object" in out["error"]


def test_start_talent_workflow_invalid_inputs_for_workflow() -> None:
    # candidate_screen requires engagement_id + candidate_id; an empty object
    # must fail validation before any model/vector-store call.
    out = _call(handle_start_talent_workflow, {"workflow": "candidate_screen", "inputs": {}})
    assert "error" in out
    assert "invalid inputs" in out["error"]


# --------------------------------------------------------------------------- #
# Registry / contract
# --------------------------------------------------------------------------- #


def test_create_tools_registered() -> None:
    names = {t["name"] for t in TALENT_TOOLS}
    for name in (
        "create_engagement",
        "create_candidate",
    ):
        assert name in names
        assert name in TALENT_TOOL_HANDLERS
    # The external-client tools are gone (in-house hiring model).
    assert "list_clients" not in names
    assert "create_client" not in names
    assert "list_clients" not in TALENT_TOOL_HANDLERS
    assert "create_client" not in TALENT_TOOL_HANDLERS


# --------------------------------------------------------------------------- #
# create_engagement
# --------------------------------------------------------------------------- #


def test_create_engagement_happy() -> None:
    # role_title is the only required field now; department is optional in-house
    # grouping and there is no external client to resolve.
    out = _call(
        handle_create_engagement,
        {
            "role_title": "VP Completions",
            "department": "Completions",
            "location": "Midland, TX",
        },
    )
    assert out["status"] == "ok"
    eng = out["engagement"]
    assert eng["role_title"] == "VP Completions"
    assert eng["department"] == "Completions"
    assert eng["location"] == "Midland, TX"
    assert eng["status"] == "open"
    assert "client_id" not in eng
    # Persisted and reloadable.
    assert talent_store.get_engagement(eng["id"]) is not None


def test_create_engagement_defaults_department_to_empty() -> None:
    out = _call(handle_create_engagement, {"role_title": "VP Ops"})
    assert out["status"] == "ok"
    assert out["engagement"]["department"] == ""


def test_create_engagement_requires_role_title() -> None:
    out = _call(handle_create_engagement, {"role_title": ""})
    assert "error" in out
    assert "role_title is required" in out["error"]


def test_create_engagement_invalid_status() -> None:
    out = _call(
        handle_create_engagement,
        {"role_title": "VP Ops", "status": "bogus"},
    )
    assert "error" in out
    assert "invalid status" in out["error"]


# --------------------------------------------------------------------------- #
# create_candidate
# --------------------------------------------------------------------------- #


def _stub_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid constructing a real ChromaDB/embedding stack in create_candidate."""
    from openexecutive.knowledge import store as knowledge_store

    monkeypatch.setattr(knowledge_store, "ChromaDBStore", lambda **kwargs: object())


def test_create_candidate_happy_and_indexes(monkeypatch: pytest.MonkeyPatch) -> None:
    eid = _seed()
    _stub_store(monkeypatch)
    indexed: list[int] = []
    # Stub indexing so the test never builds a real vector store; assert the
    # handler still asks the graph to index the new candidate.
    monkeypatch.setattr(
        talent_graph, "index_candidate", lambda cand, store: indexed.append(cand.id)
    )

    out = _call(
        handle_create_candidate,
        {
            "engagement_id": eid,
            "full_name": "Dana Wells",
            "current_title": "Drilling Superintendent",
            "email": "  ",
            "stage": "screened",
        },
    )
    assert out["status"] == "ok"
    cand = out["candidate"]
    assert cand["full_name"] == "Dana Wells"
    assert cand["engagement_id"] == eid
    assert cand["stage"] == "screened"
    # Blank email normalized to null, not stored as "  ".
    assert cand["email"] is None
    # Persisted and handed to the indexer exactly once.
    assert talent_store.get_candidate(cand["id"]) is not None
    assert indexed == [cand["id"]]


def test_create_candidate_unknown_engagement(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[int] = []
    monkeypatch.setattr(
        talent_graph, "index_candidate", lambda cand, store: called.append(cand.id)
    )
    out = _call(handle_create_candidate, {"engagement_id": 4242, "full_name": "Nobody"})
    assert out["status"] == "not_found"
    assert out["engagement_id"] == 4242
    # No write, so nothing indexed.
    assert called == []


def test_create_candidate_requires_full_name() -> None:
    eid = _seed()
    out = _call(handle_create_candidate, {"engagement_id": eid, "full_name": ""})
    assert "error" in out
    assert "full_name is required" in out["error"]


def test_create_rejects_oversized_text() -> None:
    # Chat is just another caller; it must not be able to persist unbounded text
    # the /talent HTTP route would reject (here a >200-char role_title).
    out = _call(handle_create_engagement, {"role_title": "X" * 201})
    assert "error" in out
    assert "too long" in out["error"]
    # And nothing was written.
    assert _call(handle_list_engagements, {})["count"] == 0


def test_create_candidate_indexing_failure_does_not_break_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    eid = _seed()
    _stub_store(monkeypatch)

    def _boom(cand: Any, store: Any) -> None:
        raise RuntimeError("vector store down")

    monkeypatch.setattr(talent_graph, "index_candidate", _boom)
    out = _call(handle_create_candidate, {"engagement_id": eid, "full_name": "Resilient Rita"})
    # The candidate is still created even though indexing blew up.
    assert out["status"] == "ok"
    assert talent_store.get_candidate(out["candidate"]["id"]) is not None
