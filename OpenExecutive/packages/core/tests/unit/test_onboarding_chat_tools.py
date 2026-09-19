"""Tests for the staff-onboarding chat tools + their registration.

Verifies the tools are wired into the Executive's skill toolkit and that the
handlers create/list/advance plans and complete tasks against the store.
``start_onboarding`` (which runs the LLM workflow) is covered by the workflow
tests; here we only assert it's registered.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from openexecutive.orchestrator import onboarding_tools as tools
from openexecutive.staff_onboarding import store


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "onboarding.db"
    monkeypatch.setattr(store, "DB_PATH", path)
    store.initialize_db()
    return path


def test_tools_registered_in_executive_toolkit() -> None:
    from openexecutive.orchestrator.executive import (
        _ALL_SKILL_HANDLERS,
        _ALL_SKILL_TOOLS,
    )

    names = {t["name"] for t in _ALL_SKILL_TOOLS}
    expected = {
        "list_onboarding_plans", "get_onboarding_plan", "list_onboarding_templates",
        "create_onboarding_plan", "complete_onboarding_task",
        "advance_onboarding_plan", "start_onboarding",
    }
    assert expected <= names
    assert expected <= set(_ALL_SKILL_HANDLERS)


@pytest.mark.asyncio
async def test_create_list_complete_advance_flow(db: Path) -> None:
    created = json.loads(await tools.handle_create_onboarding_plan({
        "full_name": "Priya Rao", "start_date": "2026-07-01", "role": "Fractional CFO",
    }))
    assert created["status"] == "ok"
    plan_id = created["plan"]["id"]

    listed = json.loads(await tools.handle_list_onboarding_plans({}))
    assert listed["status"] == "ok"
    assert [p["plan_id"] for p in listed["plans"]] == [plan_id]

    # Add a task directly, then complete it via the tool.
    task_id = store.add_task(plan_id=plan_id, title="Sign NDA")
    completed = json.loads(await tools.handle_complete_onboarding_task({"task_id": task_id}))
    assert completed["status"] == "ok"
    assert completed["task"]["status"] == "done"

    got = json.loads(await tools.handle_get_onboarding_plan({"plan_id": plan_id}))
    assert got["plan"]["completion_pct"] == 100

    adv = json.loads(await tools.handle_advance_onboarding_plan({"plan_id": plan_id}))
    assert adv["new_phase"] == "week_1"


@pytest.mark.asyncio
async def test_create_from_template_and_list_templates(db: Path) -> None:
    from openexecutive.staff_onboarding.seed import seed_default_templates

    seed_default_templates()
    templates = json.loads(await tools.handle_list_onboarding_templates({}))
    names = {t["name"] for t in templates["templates"]}
    assert {"generic", "engineering", "finance"} <= names

    created = json.loads(await tools.handle_create_onboarding_plan({
        "full_name": "Dana", "start_date": "2026-07-01", "template_name": "generic",
    }))
    assert created["status"] == "ok"
    generic = store.get_template("generic")
    assert generic is not None
    assert len(created["plan"]["tasks"]) == len(generic.task_specs)


@pytest.mark.asyncio
async def test_handlers_validate_and_404(db: Path) -> None:
    assert "error" in json.loads(await tools.handle_create_onboarding_plan({"role": "x"}))
    assert json.loads(
        await tools.handle_get_onboarding_plan({"plan_id": 9999})
    )["status"] == "not_found"
    assert json.loads(
        await tools.handle_complete_onboarding_task({"task_id": 9999})
    )["status"] == "not_found"
    assert "error" in json.loads(
        await tools.handle_create_onboarding_plan(
            {"full_name": "X", "start_date": "2026-07-01", "template_name": "nope"}
        )
    )
    # A non-integer person_id is an error, not a silently-unlinked plan.
    assert "error" in json.loads(
        await tools.handle_create_onboarding_plan(
            {"full_name": "X", "start_date": "2026-07-01", "person_id": "not-an-int"}
        )
    )


def test_seed_is_idempotent(db: Path) -> None:
    from openexecutive.staff_onboarding.seed import seed_default_templates

    first = seed_default_templates()
    assert first >= 4
    assert seed_default_templates() == 0  # already present, no re-insert
