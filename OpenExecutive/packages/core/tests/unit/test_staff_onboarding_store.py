"""Tests for the staff-onboarding store (staff_onboarding/store.py).

Covers template round-trip (task specs + brief sections survive JSON), plan +
task CRUD, the done/undone completed_at stamping, and the completion_pct rollup
(skipped tasks excluded).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from openexecutive.staff_onboarding import store
from openexecutive.staff_onboarding.models import (
    OnboardingPhase,
    OnboardingStatus,
    OnboardingTemplate,
    TaskSpec,
    TaskStatus,
)


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "onboarding.db"
    monkeypatch.setattr(store, "DB_PATH", path)
    store.initialize_db()
    return path


def test_template_round_trip(db: Path) -> None:
    tmpl = OnboardingTemplate(
        name="eng_default",
        title="Engineering Onboarding",
        department="engineering",
        ramp_days=5,
        checkin_cadence="day_7,day_30",
        task_specs=[
            TaskSpec(title="Provision laptop", category="it",
                     phase=OnboardingPhase.PRE_START, owner_role="it", due_offset_days=-2),
            TaskSpec(title="Intro 1:1 with manager",
                     phase=OnboardingPhase.WEEK_1, owner_role="manager", due_offset_days=1),
        ],
        brief_sections=["company_landscape", "function_state"],
    )
    store.upsert_template(tmpl)

    got = store.get_template("eng_default")
    assert got is not None
    assert got.title == "Engineering Onboarding"
    assert got.ramp_days == 5
    assert len(got.task_specs) == 2
    assert got.task_specs[0].owner_role == "it"
    assert got.task_specs[0].due_offset_days == -2
    assert got.brief_sections == ["company_landscape", "function_state"]
    assert got.created_at and got.updated_at


def test_template_list_active_only_and_delete(db: Path) -> None:
    store.upsert_template(OnboardingTemplate(name="a", title="A"))
    store.upsert_template(OnboardingTemplate(name="b", title="B", is_active=False))

    active = store.list_templates(active_only=True)
    assert [t.name for t in active] == ["a"]
    assert {t.name for t in store.list_templates(active_only=False)} == {"a", "b"}

    assert store.delete_template("a") is True
    assert store.get_template("a") is None
    assert store.delete_template("missing") is False


def test_plan_and_task_crud_with_completion(db: Path) -> None:
    plan_id = store.create_plan(full_name="Priya Rao", start_date="2026-07-01", role="CFO")
    assert plan_id > 0

    t1 = store.add_task(plan_id=plan_id, title="Sign NDA", phase=OnboardingPhase.PRE_START)
    t2 = store.add_task(plan_id=plan_id, title="Meet team", phase=OnboardingPhase.WEEK_1)
    t3 = store.add_task(plan_id=plan_id, title="Optional reading", phase=OnboardingPhase.WEEK_1)

    plan = store.get_plan(plan_id)
    assert plan is not None
    assert plan.full_name == "Priya Rao"
    assert len(plan.tasks) == 3
    assert plan.completion_pct == 0

    # Complete one of three counted tasks → 33%.
    assert store.set_task_status(t1, TaskStatus.DONE, completed_by_person_id=9) is True
    done_task = store.get_task(t1)
    assert done_task is not None
    assert done_task.completed_at is not None
    assert done_task.completed_by_person_id == 9
    assert store.get_plan(plan_id).completion_pct == 33  # type: ignore[union-attr]

    # Skipped tasks are excluded from the denominator: 1 done of 2 counted → 50%.
    assert store.set_task_status(t3, TaskStatus.SKIPPED) is True
    assert store.get_plan(plan_id).completion_pct == 50  # type: ignore[union-attr]

    # Reverting a done task clears completed_at and drops completion back to 0.
    assert store.set_task_status(t1, TaskStatus.PENDING) is True
    reverted = store.get_task(t1)
    assert reverted is not None
    assert reverted.completed_at is None
    assert reverted.completed_by_person_id is None
    assert store.get_plan(plan_id).completion_pct == 0  # type: ignore[union-attr]

    # list_plans carries completion_pct but not tasks.
    assert store.set_task_status(t2, TaskStatus.DONE) is True
    listed = store.list_plans()
    assert len(listed) == 1
    assert listed[0].completion_pct == 50
    assert listed[0].tasks == []

    assert store.delete_task(t2) is True
    assert store.get_task(t2) is None


def test_update_and_archive_plan(db: Path) -> None:
    plan_id = store.create_plan(full_name="Sam Lee", start_date="2026-07-01")

    assert store.update_plan(
        plan_id, person_id=42, manager_person_id=7, status=OnboardingStatus.ACTIVE
    ) is True
    plan = store.get_plan(plan_id)
    assert plan is not None
    assert plan.person_id == 42
    assert plan.manager_person_id == 7
    assert plan.status == OnboardingStatus.ACTIVE

    # Empty patch is a no-op.
    assert store.update_plan(plan_id) is False

    assert store.archive_plan(plan_id) is True
    assert store.list_plans() == []  # archived hidden by default
    archived = store.list_plans(include_archived=True)
    assert len(archived) == 1
    assert archived[0].status == OnboardingStatus.ARCHIVED
    # Double-archive is a no-op.
    assert store.archive_plan(plan_id) is False


def test_claim_next_ramp_segment(db: Path) -> None:
    plan_id = store.create_plan(full_name="Dana", start_date="2026-07-01")
    store.update_plan(plan_id, ramp_segments=["day1", "day2"], ramp_next_index=0)

    seg, has_more = store.claim_next_ramp_segment(plan_id)
    assert (seg, has_more) == ("day1", True)
    seg, has_more = store.claim_next_ramp_segment(plan_id)
    assert (seg, has_more) == ("day2", False)
    # Exhausted → nothing more, no re-chain.
    assert store.claim_next_ramp_segment(plan_id) == (None, False)
    # Missing/archived plan → nothing.
    assert store.claim_next_ramp_segment(99999) == (None, False)
    store.archive_plan(plan_id)
    assert store.claim_next_ramp_segment(plan_id) == (None, False)


def test_reading_list_and_brief_persist(db: Path) -> None:
    plan_id = store.create_plan(full_name="Dana", start_date="2026-07-01")
    assert store.update_plan(
        plan_id, brief_artifact="# Welcome\nbody", reading_list=["doc-a", "doc-b"]
    ) is True
    plan = store.get_plan(plan_id)
    assert plan is not None
    assert plan.brief_artifact.startswith("# Welcome")
    assert plan.reading_list == ["doc-a", "doc-b"]
