"""Tests for the role_onboarding workflow.

Specialists are mocked (no API calls). Covers specialist resolution, section
assembly, ramp-segment parsing, plan write-back, and the no-context error path.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from openexecutive.staff_onboarding import store
from openexecutive.staff_onboarding.models import OnboardingTemplate
from openexecutive.staff_onboarding.specialists import resolve_specialist
from openexecutive.workflows import role_onboarding
from openexecutive.workflows.role_onboarding import (
    RoleOnboardingInput,
    RoleOnboardingWorkflow,
    _split_ramp,
)


class _FakeStore:
    """Duck-typed ChromaDBStore: reading-list query returns nothing."""

    def query(self, *a: Any, **k: Any) -> list[dict[str, Any]]:
        return []


async def _fake_route(*, specialist_name: str, query: str, context: str = "",
                      retrieved_knowledge: str = "", **_: Any) -> str:
    if "ramp drip" in query:
        return "DAY 1: Read the handbook.\n\nDAY 2: Meet your manager.\n\nDAY 3: Ship a fix."
    return f"Content from {specialist_name}."


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "onboarding.db"
    monkeypatch.setattr(store, "DB_PATH", path)
    store.initialize_db()
    return path


@pytest.fixture(autouse=True)
def _mock_specialists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(role_onboarding, "route_to_specialist", _fake_route)
    monkeypatch.setattr(role_onboarding, "retrieve", lambda **k: "")
    monkeypatch.setattr(role_onboarding, "_roster_block", lambda: "CURRENT TEAM:\n- Sam — CEO")

    class _EmptyProfile:
        def is_empty(self) -> bool:
            return True

        def to_prompt_block(self) -> str:
            return ""

    monkeypatch.setattr(role_onboarding, "load_or_create_profile", lambda: _EmptyProfile())


async def _collect(workflow: RoleOnboardingWorkflow, inputs: RoleOnboardingInput) -> list[Any]:
    return [e async for e in workflow.run(inputs, _FakeStore())]  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_adhoc_brief_assembles_all_sections(db: Path) -> None:
    events = await _collect(
        RoleOnboardingWorkflow(),
        RoleOnboardingInput(full_name="Priya Rao", role="Fractional CFO",
                            function="finance", ramp_days=2),
    )
    artifact = next(e.content for e in events if e.type == "artifact")
    for heading in (
        "# Onboarding Brief: Priya Rao",
        "## Company Landscape",
        "## State of Your Function",
        "## People Map",
        "## 30 / 60 / 90 Day Plan",
        "## Questions to Ask in Week One",
    ):
        assert heading in artifact

    result = next(e for e in events if e.type == "result")
    assert result.data["specialist"] == "cfo"        # finance → cfo
    assert len(result.data["ramp_segments"]) == 2     # capped to ramp_days=2
    assert events[-1].type == "done"


@pytest.mark.asyncio
async def test_plan_backed_run_writes_brief_and_ramp(db: Path) -> None:
    plan_id = store.create_plan(full_name="Dana Lee", start_date="2026-07-01", role="VP Eng")
    events = await _collect(
        RoleOnboardingWorkflow(), RoleOnboardingInput(plan_id=plan_id, function="engineering",
                                                      ramp_days=3),
    )
    assert any(e.type == "artifact" for e in events)

    plan = store.get_plan(plan_id)
    assert plan is not None
    assert plan.brief_artifact.startswith("# Onboarding Brief: Dana Lee")
    assert len(plan.ramp_segments) == 3
    assert plan.ramp_next_index == 0
    # engineering → cpo (no CTO specialist).
    assert next(e for e in events if e.type == "result").data["specialist"] == "cpo"


@pytest.mark.asyncio
async def test_ramp_days_none_falls_back_to_template(db: Path) -> None:
    store.upsert_template(OnboardingTemplate(name="t", title="T", ramp_days=2))
    plan_id = store.create_plan(
        full_name="Dana", start_date="2026-07-01", template_name="t"
    )
    # ramp_days left at its default (None) → template's 2 is used.
    await _collect(RoleOnboardingWorkflow(), RoleOnboardingInput(plan_id=plan_id))
    plan = store.get_plan(plan_id)
    assert plan is not None
    assert len(plan.ramp_segments) == 2


@pytest.mark.asyncio
async def test_ramp_rerun_with_zero_preserves_in_progress_drip(db: Path) -> None:
    plan_id = store.create_plan(full_name="Dana", start_date="2026-07-01")
    store.update_plan(plan_id, ramp_segments=["a", "b", "c"], ramp_next_index=2)
    # Explicit ramp_days=0 → no drip generated, and the in-progress one is kept.
    await _collect(
        RoleOnboardingWorkflow(), RoleOnboardingInput(plan_id=plan_id, ramp_days=0)
    )
    plan = store.get_plan(plan_id)
    assert plan is not None
    assert plan.ramp_segments == ["a", "b", "c"]
    assert plan.ramp_next_index == 2
    assert plan.brief_artifact.startswith("# Onboarding Brief")  # brief still written


@pytest.mark.asyncio
async def test_no_context_errors(db: Path) -> None:
    events = await _collect(RoleOnboardingWorkflow(), RoleOnboardingInput())
    assert events[-1].type == "error"
    assert "plan_id or a full_name" in (events[-1].message or "")


def test_split_ramp_markers_and_fallback() -> None:
    marked = "DAY 1: alpha\n\nDAY 2: beta\n\nDAY 3: gamma"
    assert _split_ramp(marked, 3) == ["alpha", "beta", "gamma"]
    # Over-production is capped to the requested count.
    assert _split_ramp(marked, 2) == ["alpha", "beta"]
    # Single-day drip with a marker is NOT mistaken for a parse failure: the
    # marker is stripped and the (multi-paragraph) body is kept intact.
    assert _split_ramp("DAY 1: Hello.\n\nRead this doc.", 1) == ["Hello.\n\nRead this doc."]
    # No markers → paragraph fallback.
    assert _split_ramp("para one\n\npara two", 5) == ["para one", "para two"]
    assert _split_ramp("", 3) == []


def test_resolve_specialist_precedence() -> None:
    assert resolve_specialist(function="finance") == "cfo"
    assert resolve_specialist(function="sales") == "cmo"
    assert resolve_specialist(role="Head of Legal") == "gc"       # keyword in role text
    assert resolve_specialist() == "cso"                          # fallback
