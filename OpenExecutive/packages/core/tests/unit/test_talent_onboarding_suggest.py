"""The talent → onboarding suggest-on-placed hook.

Moving a candidate to `placed` via the chat tool surfaces an onboarding
suggestion; other stages do not. No auto-fire, no candidate messaging.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from openexecutive.orchestrator import talent_tools
from openexecutive.talent import store as talent_store


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "talent.db"
    monkeypatch.setattr(talent_store, "DB_PATH", path)
    talent_store.initialize_db()
    return path


def _candidate(db: Path) -> int:
    eid = talent_store.upsert_engagement(role_title="VP Engineering", department="product")
    return talent_store.upsert_candidate(engagement_id=eid, full_name="Priya Rao")


@pytest.mark.asyncio
async def test_placed_surfaces_onboarding_suggestion(db: Path) -> None:
    cid = _candidate(db)
    res = json.loads(await talent_tools.handle_set_candidate_stage(
        {"candidate_id": cid, "stage": "placed"}
    ))
    assert res["status"] == "ok"
    assert "onboarding_suggestion" in res
    assert "Priya Rao" in res["onboarding_suggestion"]
    assert "create_onboarding_plan" in res["onboarding_suggestion"]


@pytest.mark.asyncio
async def test_non_placed_stage_has_no_suggestion(db: Path) -> None:
    cid = _candidate(db)
    for stage in ("screened", "interviewed", "offer", "rejected"):
        res = json.loads(await talent_tools.handle_set_candidate_stage(
            {"candidate_id": cid, "stage": stage}
        ))
        assert "onboarding_suggestion" not in res
