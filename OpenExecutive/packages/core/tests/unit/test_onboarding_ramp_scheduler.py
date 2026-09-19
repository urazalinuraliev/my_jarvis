"""Tests for the bounded onboarding ramp drip (ramp_scheduler + runner branch).

Covers business-day scheduling, enqueue eligibility, and the runner handler:
deliver the next segment, advance the index, chain while segments remain, and
self-terminate when exhausted.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from openexecutive.memory import episodic
from openexecutive.scheduler import runner
from openexecutive.staff_onboarding import service, store
from openexecutive.staff_onboarding.ramp_scheduler import enqueue_ramp, next_business_day


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # episodic (scheduled_actions) and the onboarding store share one DB file.
    path = tmp_path / "shared.db"
    monkeypatch.setattr(episodic, "DB_PATH", path)
    monkeypatch.setattr(store, "DB_PATH", path)
    episodic.initialize_db(path)
    store.initialize_db(path)
    return path


def test_next_business_day_skips_weekend() -> None:
    # 2026-01-02 is a Friday → next business day is Monday 2026-01-05.
    friday = datetime(2026, 1, 2, 15, 0, tzinfo=UTC)
    nxt = next_business_day(friday)
    assert nxt.date().isoformat() == "2026-01-05"
    assert nxt.weekday() < 5
    # Thursday → Friday.
    thursday = datetime(2026, 1, 1, 15, 0, tzinfo=UTC)
    assert next_business_day(thursday).date().isoformat() == "2026-01-02"


def test_next_business_day_coerces_naive_to_utc() -> None:
    naive = datetime(2026, 1, 1, 15, 0)  # no tzinfo
    result = next_business_day(naive)
    assert result.tzinfo is not None  # always tz-aware out
    assert result.date().isoformat() == "2026-01-02"


def test_enqueue_ramp_eligibility(db: Path) -> None:
    # No person_id → no enqueue.
    no_person = store.create_plan(full_name="A", start_date="2026-07-01")
    store.update_plan(no_person, ramp_segments=["d1"])
    assert enqueue_ramp(no_person) is None

    # Person but no segments → no enqueue.
    no_segs = store.create_plan(full_name="B", start_date="2026-07-01")
    store.update_plan(no_segs, person_id=5)
    assert enqueue_ramp(no_segs) is None

    # Person + segments → enqueued.
    ok = store.create_plan(full_name="C", start_date="2026-07-01")
    store.update_plan(ok, person_id=5, ramp_segments=["d1", "d2"])
    assert enqueue_ramp(ok) is not None
    # Idempotent: a second enqueue while one is pending is a no-op.
    assert enqueue_ramp(ok) is None


def test_activate_is_idempotent(db: Path) -> None:
    plan_id = store.create_plan(full_name="C", start_date="2026-07-01")
    store.update_plan(plan_id, person_id=5, ramp_segments=["d1", "d2"])
    assert service.activate_plan(plan_id) is True
    assert service.activate_plan(plan_id) is True  # double-activate
    assert len(_pending_ramp_actions(plan_id)) == 1  # only one drip chain


@pytest.mark.asyncio
async def test_no_assignee_does_not_burn_segment(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from openexecutive.memory.episodic import ScheduledAction

    plan_id = store.create_plan(full_name="C", start_date="2026-07-01")
    store.update_plan(plan_id, person_id=5, ramp_segments=["d1", "d2"])
    # An action row with no assignee must not claim/advance a segment.
    action = ScheduledAction(
        id=999, created_at="", run_at="", channel="__internal__",
        channel_ref=str(plan_id), intent_text="", kind="onboarding_ramp",
        assigned_to_person_id=None,
    )
    # mark_action_done would 404 on a non-existent row; stub it out.
    monkeypatch.setattr(runner, "mark_action_done", lambda _id: None)
    await runner._run_onboarding_ramp(action, datetime.now(UTC))
    assert store.get_plan(plan_id).ramp_next_index == 0  # type: ignore[union-attr]


def _pending_ramp_actions(plan_id: int) -> list:
    # Ramp rows use the __internal__ channel, which list_pending_scheduled_actions
    # intentionally hides — query the full table and filter by status instead.
    return [
        a for a in episodic.list_scheduled_actions()
        if a.kind == "onboarding_ramp"
        and a.channel_ref == str(plan_id)
        and a.status == "pending"
    ]


@pytest.mark.asyncio
async def test_drip_delivers_chains_and_terminates(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[tuple[int, str]] = []

    async def _fake_message_person(tool_input: dict) -> str:
        sent.append((tool_input["person_id"], tool_input["text"]))
        return "{}"

    from openexecutive.orchestrator import schedule_tools
    monkeypatch.setattr(schedule_tools, "handle_message_person", _fake_message_person)

    plan_id = store.create_plan(full_name="Priya", start_date="2026-07-01")
    store.update_plan(plan_id, person_id=42, ramp_segments=["Day one note", "Day two note"])

    assert service.activate_plan(plan_id) is True
    actions = _pending_ramp_actions(plan_id)
    assert len(actions) == 1

    # Fire #1 → delivers segment 1, advances index, chains the next.
    await runner._run_onboarding_ramp(actions[0], datetime.now(UTC))
    assert sent == [(42, "Day one note")]
    assert store.get_plan(plan_id).ramp_next_index == 1  # type: ignore[union-attr]
    actions = _pending_ramp_actions(plan_id)
    assert len(actions) == 1  # one new pending occurrence chained

    # Fire #2 → delivers segment 2, exhausts the drip, no further chain.
    await runner._run_onboarding_ramp(actions[0], datetime.now(UTC))
    assert sent[-1] == (42, "Day two note")
    assert store.get_plan(plan_id).ramp_next_index == 2  # type: ignore[union-attr]
    assert _pending_ramp_actions(plan_id) == []

    # A stray fire after exhaustion is a no-op (claims nothing, no send/chain).
    leftover_done = [
        a for a in episodic.list_scheduled_actions() if a.kind == "onboarding_ramp"
    ]
    assert len(sent) == 2
    assert len(leftover_done) >= 2  # both fired rows recorded
