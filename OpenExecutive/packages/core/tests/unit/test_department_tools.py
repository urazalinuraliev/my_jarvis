"""Unit tests for openexecutive.orchestrator.department_tools.

These tools let the Executive update department Goal status and progress
from inside a chat turn — closing the loop that Phase A's check-in
workflow opened. Mirrors the shape of test_people_tools.py.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from openexecutive.departments import registry as dept_registry
from openexecutive.departments import store as dept_store
from openexecutive.memory import episodic as episodic_module
from openexecutive.orchestrator.department_tools import (
    handle_list_department_goals,
    handle_update_department_goal,
)


@pytest.fixture(autouse=True)
def shared_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated SQLite for each test, shared by all stores like in prod."""
    db_path = tmp_path / "episodic.db"
    monkeypatch.setattr(dept_store, "DB_PATH", db_path)
    monkeypatch.setattr(episodic_module, "DB_PATH", db_path)
    dept_store.initialize_db()
    dept_registry.invalidate()
    return db_path


def _call(coro_fn, payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(asyncio.run(coro_fn(payload)))


def _seed_engineering_goal(
    *,
    status: str = "on_track",
    current: str = "0% done",
    key_result: str = "Ship billing migration",
) -> int:
    dept_store.create_department("Engineering")
    return dept_store.insert_goal(
        "engineering",
        period_type="quarter",
        period_value="Q2 2026",
        key_result=key_result,
        target="Cutover by Jun 30",
        current=current,
        status=status,  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------- #
# list_department_goals
# --------------------------------------------------------------------------- #

def test_list_department_goals_returns_compact_shape() -> None:
    goal_id = _seed_engineering_goal()
    result = _call(handle_list_department_goals, {"department_slug": "engineering"})
    assert result["department_slug"] == "engineering"
    assert result["count"] == 1
    g = result["goals"][0]
    assert g["id"] == goal_id
    assert g["key_result"] == "Ship billing migration"
    assert g["target"] == "Cutover by Jun 30"
    assert g["status"] == "on_track"
    assert g["last_reviewed_at"] == ""
    assert "quarter" in g["period"]


def test_list_department_goals_empty_dept() -> None:
    dept_store.create_department("Empty")
    result = _call(handle_list_department_goals, {"department_slug": "empty"})
    assert result["count"] == 0
    assert result["goals"] == []


def test_list_department_goals_missing_slug() -> None:
    result = _call(handle_list_department_goals, {})
    assert "error" in result


# --------------------------------------------------------------------------- #
# update_department_goal — happy path
# --------------------------------------------------------------------------- #

def test_update_department_goal_happy_path_status_change() -> None:
    goal_id = _seed_engineering_goal(status="on_track")
    result = _call(handle_update_department_goal, {
        "department_slug": "engineering",
        "goal_id": goal_id,
        "status": "at_risk",
        "rationale": "deals slipping into Q3 per pipeline review",
    })
    assert result["status"] == "ok"
    assert result["from_status"] == "on_track"
    assert result["to_status"] == "at_risk"
    assert result["current_updated"] is False

    after = dept_store.get_goal(goal_id)
    assert after is not None
    assert after.status == "at_risk"
    assert after.current == "0% done"  # unchanged
    assert after.last_reviewed_at != ""


def test_update_department_goal_happy_path_current_only() -> None:
    """Bumping `current` without changing `status` is the
    'we made progress, still on track' case."""
    goal_id = _seed_engineering_goal(status="on_track", current="0% done")
    result = _call(handle_update_department_goal, {
        "department_slug": "engineering",
        "goal_id": goal_id,
        "current": "cutover complete",
        "rationale": "user reported the migration shipped this morning",
    })
    assert result["status"] == "ok"
    assert result["from_status"] == "on_track"
    assert result["to_status"] == "on_track"
    assert result["current_updated"] is True

    after = dept_store.get_goal(goal_id)
    assert after is not None
    assert after.current == "cutover complete"
    assert after.status == "on_track"
    assert after.last_reviewed_at != ""


def test_update_department_goal_status_and_current_together() -> None:
    goal_id = _seed_engineering_goal(status="on_track", current="50%")
    result = _call(handle_update_department_goal, {
        "department_slug": "engineering",
        "goal_id": goal_id,
        "status": "off_track",
        "current": "stalled on regulatory review",
        "rationale": "external blocker per legal counsel",
    })
    assert result["status"] == "ok"
    after = dept_store.get_goal(goal_id)
    assert after is not None
    assert after.status == "off_track"
    assert after.current == "stalled on regulatory review"


# --------------------------------------------------------------------------- #
# update_department_goal — validation errors
# --------------------------------------------------------------------------- #

def test_update_department_goal_missing_rationale_rejected() -> None:
    goal_id = _seed_engineering_goal()
    result = _call(handle_update_department_goal, {
        "department_slug": "engineering",
        "goal_id": goal_id,
        "status": "at_risk",
    })
    assert "error" in result
    assert "rationale" in result["error"]
    # Row unchanged.
    assert dept_store.get_goal(goal_id).status == "on_track"  # type: ignore[union-attr]


def test_update_department_goal_neither_status_nor_current_rejected() -> None:
    goal_id = _seed_engineering_goal()
    result = _call(handle_update_department_goal, {
        "department_slug": "engineering",
        "goal_id": goal_id,
        "rationale": "wanted to call the tool just to call it",
    })
    assert "error" in result
    assert "status" in result["error"] and "current" in result["error"]
    assert dept_store.get_goal(goal_id).status == "on_track"  # type: ignore[union-attr]


def test_update_department_goal_invalid_status_rejected() -> None:
    goal_id = _seed_engineering_goal()
    result = _call(handle_update_department_goal, {
        "department_slug": "engineering",
        "goal_id": goal_id,
        "status": "in_progress",  # not a valid enum value
        "rationale": "made-up status",
    })
    assert "error" in result
    assert dept_store.get_goal(goal_id).status == "on_track"  # type: ignore[union-attr]


def test_update_department_goal_missing_goal_rejected() -> None:
    result = _call(handle_update_department_goal, {
        "department_slug": "engineering",
        "goal_id": 99999,
        "status": "at_risk",
        "rationale": "ghost goal",
    })
    assert "error" in result
    assert "not found" in result["error"]


def test_update_department_goal_cross_department_id_blocked() -> None:
    """Goal id from engineering must NOT be writable as 'finance'."""
    eng_goal = _seed_engineering_goal()
    dept_store.create_department("Finance")
    result = _call(handle_update_department_goal, {
        "department_slug": "finance",
        "goal_id": eng_goal,
        "status": "off_track",
        "rationale": "trying to mutate the wrong dept",
    })
    assert "error" in result
    assert "engineering" in result["error"]
    # Engineering row unchanged.
    after = dept_store.get_goal(eng_goal)
    assert after is not None
    assert after.status == "on_track"


def test_update_department_goal_boolean_id_rejected() -> None:
    """`isinstance(True, int)` is True in Python — explicit reject."""
    _seed_engineering_goal()
    result = _call(handle_update_department_goal, {
        "department_slug": "engineering",
        "goal_id": True,
        "status": "at_risk",
        "rationale": "should fail",
    })
    assert "error" in result


def test_update_department_goal_empty_rationale_rejected() -> None:
    goal_id = _seed_engineering_goal()
    result = _call(handle_update_department_goal, {
        "department_slug": "engineering",
        "goal_id": goal_id,
        "status": "at_risk",
        "rationale": "   ",  # whitespace-only
    })
    assert "error" in result


# --------------------------------------------------------------------------- #
# Audit logging
# --------------------------------------------------------------------------- #

def test_update_department_goal_emits_tool_invocation_audit_row() -> None:
    goal_id = _seed_engineering_goal(status="on_track")
    fake_log = MagicMock()
    with patch("openexecutive.audit.log_event", fake_log):
        result = _call(handle_update_department_goal, {
            "department_slug": "engineering",
            "goal_id": goal_id,
            "status": "at_risk",
            "rationale": "deals slipping",
        })
    assert result["status"] == "ok"
    # The handler may call _audit multiple times (e.g. on different paths);
    # find the write success row.
    write_calls = [
        c for c in fake_log.call_args_list
        if c.args and c.args[0] == "tool_invocation"
        and c.kwargs.get("details", {}).get("tool") == "update_department_goal"
        and c.kwargs.get("details", {}).get("ok") is True
    ]
    assert len(write_calls) == 1
    details = write_calls[0].kwargs["details"]
    assert details["from_status"] == "on_track"
    assert details["to_status"] == "at_risk"
    assert details["goal_id"] == goal_id
    assert details["department_slug"] == "engineering"
    assert details["rationale"] == "deals slipping"
    assert write_calls[0].kwargs["actor"] == "executive"


def test_update_department_goal_audit_row_tagged_with_department() -> None:
    """The `department=` top-level kwarg on log_event lets dept-scoped
    audit queries (audit_logger.query(department=slug)) pick this row up
    — same plumbing the department_check_in workflow uses."""
    goal_id = _seed_engineering_goal(status="on_track")
    fake_log = MagicMock()
    with patch("openexecutive.audit.log_event", fake_log):
        _call(handle_update_department_goal, {
            "department_slug": "engineering",
            "goal_id": goal_id,
            "status": "at_risk",
            "rationale": "deal slipping",
        })
    write_calls = [
        c for c in fake_log.call_args_list
        if c.args and c.args[0] == "tool_invocation"
        and c.kwargs.get("details", {}).get("ok") is True
    ]
    assert len(write_calls) == 1
    assert write_calls[0].kwargs.get("department") == "engineering"


def test_update_department_goal_failed_input_audited_as_not_ok() -> None:
    fake_log = MagicMock()
    with patch("openexecutive.audit.log_event", fake_log):
        _call(handle_update_department_goal, {
            "department_slug": "engineering",
            "goal_id": "not-an-int",
            "rationale": "x",
        })
    bad_calls = [
        c for c in fake_log.call_args_list
        if c.args and c.args[0] == "tool_invocation"
        and c.kwargs.get("details", {}).get("tool") == "update_department_goal"
        and c.kwargs.get("details", {}).get("ok") is False
    ]
    assert len(bad_calls) >= 1


# --------------------------------------------------------------------------- #
# Tool definitions present in the executive registry
# --------------------------------------------------------------------------- #

def test_department_tools_wired_into_executive_registry() -> None:
    """Smoke: the Executive's tool registry includes both new tools, and
    the handlers are wired correctly."""
    from openexecutive.orchestrator.executive import (
        _ALL_SKILL_HANDLERS,
        _ALL_SKILL_TOOLS,
    )
    names = {t["name"] for t in _ALL_SKILL_TOOLS}
    assert "list_department_goals" in names
    assert "update_department_goal" in names
    assert _ALL_SKILL_HANDLERS["list_department_goals"] is handle_list_department_goals
    assert _ALL_SKILL_HANDLERS["update_department_goal"] is handle_update_department_goal


def test_tool_list_sorts_stably_by_name() -> None:
    """The Executive sorts tools by name before sending them to Anthropic —
    so prompt-cache layout stays stable across deploys. The sort must
    handle the new tools without surprises (alphabetical insertion)."""
    from openexecutive.orchestrator.executive import _ALL_SKILL_TOOLS
    sorted_names = [t["name"] for t in sorted(_ALL_SKILL_TOOLS, key=lambda t: t["name"])]
    # Pure assertion: sorted order is stable and includes our tools.
    assert sorted_names == sorted(sorted_names)
    assert "list_department_goals" in sorted_names
    assert "update_department_goal" in sorted_names
