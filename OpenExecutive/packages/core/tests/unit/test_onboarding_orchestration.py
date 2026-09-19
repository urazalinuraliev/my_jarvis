"""Tests for staff-onboarding stakeholder orchestration.

Covers the enqueue helpers (kickoff + milestone check-ins: idempotency,
past-milestone skip, person_id requirement), activate_plan firing all three
scheduler kinds, and the runner handlers (kickoff nudges, check-in messaging +
deterministic phase advance).
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from openexecutive.memory import episodic
from openexecutive.orchestrator import schedule_tools
from openexecutive.scheduler import runner
from openexecutive.staff_onboarding import orchestration, service, store
from openexecutive.staff_onboarding.models import OnboardingPhase

_FUTURE = "2999-07-01"  # all milestones in the future
_PAST = "2000-01-01"    # all milestones in the past


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "shared.db"
    monkeypatch.setattr(episodic, "DB_PATH", path)
    monkeypatch.setattr(store, "DB_PATH", path)
    episodic.initialize_db(path)
    store.initialize_db(path)
    return path


def _pending(kind: str) -> list:
    return [a for a in episodic.list_scheduled_actions(status="pending") if a.kind == kind]


def test_enqueue_kickoff_idempotent(db: Path) -> None:
    pid = store.create_plan(full_name="Priya Rao", start_date=_FUTURE, person_id=5)
    assert orchestration.enqueue_kickoff(pid) is not None
    assert orchestration.enqueue_kickoff(pid) is None  # already enqueued
    assert len(_pending("onboarding_kickoff")) == 1


def test_enqueue_checkins_future_and_idempotent(db: Path) -> None:
    pid = store.create_plan(full_name="Priya Rao", start_date=_FUTURE, person_id=5)
    ids = orchestration.enqueue_checkins(pid)
    assert len(ids) == 4
    assert orchestration.enqueue_checkins(pid) == []  # idempotent (return)
    # Idempotent at the DB level too — no duplicate rows on the second call.
    assert len(_pending("onboarding_checkin")) == 4
    refs = {a.channel_ref for a in _pending("onboarding_checkin")}
    assert refs == {f"{pid}:day_7", f"{pid}:day_30", f"{pid}:day_60", f"{pid}:day_90"}


def test_enqueue_checkins_skips_past_milestones(db: Path) -> None:
    pid = store.create_plan(full_name="Old Hire", start_date=_PAST, person_id=5)
    assert orchestration.enqueue_checkins(pid) == []


def test_enqueue_checkins_requires_person(db: Path) -> None:
    pid = store.create_plan(full_name="No Person", start_date=_FUTURE)  # person_id=None
    assert orchestration.enqueue_checkins(pid) == []


def test_phase_for_milestone() -> None:
    assert orchestration.phase_for_milestone("day_30") == OnboardingPhase.DAY_30
    assert orchestration.phase_for_milestone("day_90") == OnboardingPhase.DAY_90
    assert orchestration.phase_for_milestone("nope") is None


def test_activate_enqueues_ramp_kickoff_and_checkins(db: Path) -> None:
    pid = store.create_plan(full_name="Priya Rao", start_date=_FUTURE, person_id=5)
    store.update_plan(pid, ramp_segments=["d1", "d2"])  # so the ramp can enqueue
    assert service.activate_plan(pid) is True
    kinds = {a.kind for a in episodic.list_scheduled_actions(status="pending")}
    assert {"onboarding_ramp", "onboarding_kickoff", "onboarding_checkin"} <= kinds


@pytest.mark.asyncio
async def test_run_kickoff_sends_manager_and_buddy_nudges(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = store.create_plan(
        full_name="Priya Rao", start_date=_FUTURE, role="CFO",
        person_id=5, manager_person_id=7, buddy_person_id=9,
    )
    orchestration.enqueue_kickoff(pid)
    action = _pending("onboarding_kickoff")[0]

    sent: list[dict] = []

    async def fake_msg(inp: dict) -> str:
        sent.append(inp)
        return "{}"

    monkeypatch.setattr(schedule_tools, "handle_message_person", fake_msg)
    await runner._run_onboarding_kickoff(action, datetime.now(UTC))

    by_person = {m["person_id"]: m["text"] for m in sent}
    assert set(by_person) == {7, 9}  # manager + buddy, not the hire
    assert "manager" in by_person[7].lower()  # role-specific copy
    assert "buddy" in by_person[9].lower()
    # Action consumed.
    assert _pending("onboarding_kickoff") == []


@pytest.mark.asyncio
async def test_run_checkin_messages_and_advances_phase(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = store.create_plan(
        full_name="Priya Rao", start_date=_FUTURE, role="CFO",
        person_id=5, manager_person_id=7,
    )
    orchestration.enqueue_checkins(pid)
    action = next(a for a in _pending("onboarding_checkin") if a.channel_ref.endswith(":day_30"))

    sent: list[dict] = []

    async def fake_msg(inp: dict) -> str:
        sent.append(inp)
        return "{}"

    monkeypatch.setattr(schedule_tools, "handle_message_person", fake_msg)
    await runner._run_onboarding_checkin(action, datetime.now(UTC))

    by_person = {m["person_id"]: m["text"] for m in sent}
    assert set(by_person) == {5, 7}  # hire + manager
    assert by_person[5] != by_person[7]  # hire and manager get different copy
    assert "30" in by_person[5]  # day number surfaced
    plan = store.get_plan(pid)
    assert plan is not None
    assert plan.current_phase == OnboardingPhase.DAY_30  # advanced


@pytest.mark.asyncio
async def test_checkin_never_drags_phase_backwards(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = store.create_plan(full_name="X", start_date=_FUTURE, person_id=5)
    store.update_plan(pid, current_phase=OnboardingPhase.DAY_60)  # already past day_30
    orchestration.enqueue_checkins(pid)
    action = next(a for a in _pending("onboarding_checkin") if a.channel_ref.endswith(":day_30"))

    async def _swallow(inp: dict) -> str:
        return "{}"

    monkeypatch.setattr(schedule_tools, "handle_message_person", _swallow)
    await runner._run_onboarding_checkin(action, datetime.now(UTC))
    plan = store.get_plan(pid)
    assert plan is not None
    assert plan.current_phase == OnboardingPhase.DAY_60  # unchanged (day_30 < day_60)


@pytest.mark.asyncio
async def test_activate_chat_tool_enqueues_and_404(db: Path) -> None:
    import json as _json

    from openexecutive.orchestrator import onboarding_tools

    pid = store.create_plan(full_name="Priya Rao", start_date=_FUTURE, person_id=5)
    store.update_plan(pid, ramp_segments=["d1"])
    res = _json.loads(await onboarding_tools.handle_activate_onboarding_plan({"plan_id": pid}))
    assert res["status"] == "ok"
    assert res["plan"]["status"] == "active"
    kinds = {a.kind for a in episodic.list_scheduled_actions(status="pending")}
    assert {"onboarding_ramp", "onboarding_kickoff", "onboarding_checkin"} <= kinds

    missing = _json.loads(
        await onboarding_tools.handle_activate_onboarding_plan({"plan_id": 9999})
    )
    assert missing["status"] == "not_found"
    # The tool is registered in the toolkit.
    assert "activate_onboarding_plan" in onboarding_tools.ONBOARDING_TOOL_HANDLERS


@pytest.mark.asyncio
async def test_send_team_notice_no_channel_returns_false(db: Path) -> None:
    # No department / no channel configured → False, never raises.
    assert await runner._send_team_notice("", "hi") is False
    assert await runner._send_team_notice("nonexistent_dept", "hi") is False
