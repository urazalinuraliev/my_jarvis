"""Tests for staff-onboarding instantiation + phase advance (service.py).

Covers due-date math (start_date + offset), owner-role resolution
(hire/manager/buddy → ids, unknown → unassigned), task ordering, and the
phase-advance walk that stops at the final phase.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from openexecutive.staff_onboarding import service, store
from openexecutive.staff_onboarding.models import (
    OnboardingPhase,
    OnboardingTemplate,
    TaskSpec,
)


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "onboarding.db"
    monkeypatch.setattr(store, "DB_PATH", path)
    store.initialize_db()
    return path


def _template() -> OnboardingTemplate:
    return OnboardingTemplate(
        name="generic",
        title="Generic Onboarding",
        ramp_days=3,
        task_specs=[
            TaskSpec(title="Sign offer", phase=OnboardingPhase.PRE_START,
                     owner_role="hire", due_offset_days=-3),
            TaskSpec(title="1:1 with manager", phase=OnboardingPhase.WEEK_1,
                     owner_role="manager", due_offset_days=1),
            TaskSpec(title="Coffee with buddy", phase=OnboardingPhase.WEEK_1,
                     owner_role="buddy", due_offset_days=2),
            TaskSpec(title="Compliance training", phase=OnboardingPhase.WEEK_1,
                     owner_role="hr", due_offset_days=4),  # unknown→unassigned
        ],
    )


def test_instantiate_sets_due_dates_owners_and_order(db: Path) -> None:
    plan_id = service.instantiate_plan(
        full_name="Priya Rao",
        start_date="2026-07-01",
        role="CFO",
        template=_template(),
        person_id=100,
        manager_person_id=200,
        buddy_person_id=300,
    )
    plan = store.get_plan(plan_id)
    assert plan is not None
    assert plan.template_name == "generic"
    assert plan.status.value == "draft"
    assert len(plan.tasks) == 4

    by_title = {t.title: t for t in plan.tasks}
    assert by_title["Sign offer"].due_date == "2026-06-28"      # -3 days
    assert by_title["Sign offer"].owner_person_id == 100        # hire
    assert by_title["1:1 with manager"].due_date == "2026-07-02"  # +1
    assert by_title["1:1 with manager"].owner_person_id == 200  # manager
    assert by_title["Coffee with buddy"].owner_person_id == 300  # buddy
    assert by_title["Compliance training"].owner_person_id is None  # hr unresolved

    # Tasks keep template order via sort_order.
    assert [t.title for t in plan.tasks] == [
        "Sign offer", "1:1 with manager", "Coffee with buddy", "Compliance training",
    ]


def test_instantiate_without_template_creates_bare_plan(db: Path) -> None:
    plan_id = service.instantiate_plan(full_name="Sam", start_date="2026-07-01")
    plan = store.get_plan(plan_id)
    assert plan is not None
    assert plan.tasks == []
    assert plan.template_name == ""


def test_instantiate_tolerates_bad_start_date(db: Path) -> None:
    plan_id = service.instantiate_plan(
        full_name="Sam", start_date="not-a-date", template=_template()
    )
    plan = store.get_plan(plan_id)
    assert plan is not None
    # Tasks still created, just with no due date.
    assert len(plan.tasks) == 4
    assert all(t.due_date is None for t in plan.tasks)


def test_advance_phase_walks_and_stops(db: Path) -> None:
    plan_id = service.instantiate_plan(full_name="Sam", start_date="2026-07-01")
    assert store.get_plan(plan_id).current_phase == OnboardingPhase.PRE_START  # type: ignore[union-attr]

    assert service.advance_phase(plan_id) == OnboardingPhase.WEEK_1
    assert service.advance_phase(plan_id) == OnboardingPhase.DAY_30
    assert service.advance_phase(plan_id) == OnboardingPhase.DAY_60
    assert service.advance_phase(plan_id) == OnboardingPhase.DAY_90
    # Already at the final phase → no further advance.
    assert service.advance_phase(plan_id) is None
    assert store.get_plan(plan_id).current_phase == OnboardingPhase.DAY_90  # type: ignore[union-attr]


def test_advance_phase_missing_plan(db: Path) -> None:
    assert service.advance_phase(99999) is None
