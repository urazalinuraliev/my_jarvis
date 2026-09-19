"""Tests for the staff-onboarding briefing digest (briefing/onboarding_digest.py).

Covers the active-plan rollup, overdue-task counting, exclusion of
completed/archived plans, and the chat-digest text.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from openexecutive.briefing.onboarding_digest import (
    build_onboarding_brief_items,
    format_onboarding_for_prompt,
)
from openexecutive.staff_onboarding import store
from openexecutive.staff_onboarding.models import (
    OnboardingPhase,
    OnboardingStatus,
    TaskStatus,
)


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "onboarding.db"
    monkeypatch.setattr(store, "DB_PATH", path)
    store.initialize_db()
    return path


def test_empty_digest(db: Path) -> None:
    assert build_onboarding_brief_items() == []
    assert format_onboarding_for_prompt() == ""


def test_rollup_counts_open_and_overdue(db: Path) -> None:
    plan_id = store.create_plan(full_name="Priya Rao", start_date="2026-07-01",
                                role="CFO", status=OnboardingStatus.ACTIVE)
    store.add_task(plan_id=plan_id, title="Past due", phase=OnboardingPhase.WEEK_1,
                   due_date="2020-01-01")           # overdue + open
    store.add_task(plan_id=plan_id, title="Future", phase=OnboardingPhase.DAY_30,
                   due_date="2999-01-01")            # open, not overdue
    done = store.add_task(plan_id=plan_id, title="Done already")
    store.set_task_status(done, TaskStatus.DONE)

    items = build_onboarding_brief_items()
    assert len(items) == 1
    item = items[0]
    assert item.full_name == "Priya Rao"
    assert item.open_tasks == 2
    assert item.overdue_tasks == 1

    text = format_onboarding_for_prompt()
    assert f"[plan {plan_id}]" in text
    assert "1 overdue" in text


def test_day_label_counts_start_as_day_one(db: Path) -> None:
    from datetime import UTC, datetime, timedelta

    yesterday = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
    plan_id = store.create_plan(full_name="Started Yesterday", start_date=yesterday,
                                status=OnboardingStatus.ACTIVE)
    text = format_onboarding_for_prompt()
    # Start date is day 1, so a hire who started yesterday is on day 2.
    assert "day 2" in text
    assert f"[plan {plan_id}]" in text


def test_completed_and_archived_excluded(db: Path) -> None:
    active = store.create_plan(full_name="Active", start_date="2026-07-01",
                               status=OnboardingStatus.ACTIVE)
    store.create_plan(full_name="Done", start_date="2026-07-01",
                      status=OnboardingStatus.COMPLETED)
    archived = store.create_plan(full_name="Gone", start_date="2026-07-01",
                                 status=OnboardingStatus.ACTIVE)
    store.archive_plan(archived)

    ids = {i.plan_id for i in build_onboarding_brief_items()}
    assert ids == {active}
