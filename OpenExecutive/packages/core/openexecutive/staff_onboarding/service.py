"""Instantiation + lifecycle helpers for the staff-onboarding framework.

Kept separate from ``store`` (pure persistence) and ``api.routes`` (HTTP glue)
so the logic that turns a template into a concrete plan — due-date math, owner
resolution against the roster/departments — is unit-testable on its own.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

from openexecutive.staff_onboarding import store
from openexecutive.staff_onboarding.models import (
    OnboardingPhase,
    OnboardingStatus,
    OnboardingTemplate,
)

logger = logging.getLogger(__name__)

# Forward order of phases, used to advance a plan and to order instantiated tasks.
_PHASE_ORDER: tuple[OnboardingPhase, ...] = (
    OnboardingPhase.PRE_START,
    OnboardingPhase.WEEK_1,
    OnboardingPhase.DAY_30,
    OnboardingPhase.DAY_60,
    OnboardingPhase.DAY_90,
)


def _parse_date(iso: str) -> date | None:
    """Parse a ``YYYY-MM-DD`` string, tolerating a full ISO datetime. None on
    failure so a malformed start date degrades to "no due date" rather than
    crashing instantiation."""
    try:
        return date.fromisoformat(iso[:10])
    except (ValueError, TypeError):
        logger.warning("staff_onboarding: unparseable date %r", iso)
        return None


def _resolve_owner(
    owner_role: str,
    *,
    person_id: int | None,
    manager_person_id: int | None,
    buddy_person_id: int | None,
    department: str,
    db_path: Path | None,
) -> int | None:
    """Map a template ``owner_role`` to a concrete person_id, or None when it
    can't be resolved (the task is created unassigned — better than guessing)."""
    role = (owner_role or "").strip().lower()
    if role == "hire":
        return person_id
    if role == "manager":
        return manager_person_id
    if role == "buddy":
        return buddy_person_id
    if role == "department_head" and department:
        try:
            from openexecutive.departments import store as dept_store

            dept = dept_store.get_department(department)
            if dept is not None:
                return dept.config.head_person_id
        except Exception:
            logger.exception("staff_onboarding: department-head resolution failed")
    # it / hr / unknown roles → unassigned for now.
    return None


def instantiate_plan(
    *,
    full_name: str,
    start_date: str,
    role: str = "",
    template: OnboardingTemplate | None = None,
    person_id: int | None = None,
    manager_person_id: int | None = None,
    buddy_person_id: int | None = None,
    engagement_id: int | None = None,
    candidate_id: int | None = None,
    db_path: Path | None = None,
) -> int:
    """Create a plan and (when a template is given) its tasks.

    Each template task spec becomes an ``OnboardingTask`` with a concrete
    ``due_date`` (``start_date + due_offset_days``) and a resolved owner. Returns
    the new plan id. The plan starts in ``DRAFT`` — orchestration/ramp are fired
    explicitly on activation, not here.
    """
    template_name = template.name if template else ""
    plan_id = store.create_plan(
        full_name=full_name,
        start_date=start_date,
        role=role,
        person_id=person_id,
        manager_person_id=manager_person_id,
        buddy_person_id=buddy_person_id,
        template_name=template_name,
        status=OnboardingStatus.DRAFT,
        engagement_id=engagement_id,
        candidate_id=candidate_id,
        db_path=db_path,
    )

    if template is None:
        return plan_id

    base = _parse_date(start_date)
    for order, spec in enumerate(template.task_specs):
        due: str | None = None
        if base is not None:
            due = (base + timedelta(days=spec.due_offset_days)).isoformat()
        owner = _resolve_owner(
            spec.owner_role,
            person_id=person_id,
            manager_person_id=manager_person_id,
            buddy_person_id=buddy_person_id,
            department=template.department,
            db_path=db_path,
        )
        store.add_task(
            plan_id=plan_id,
            title=spec.title,
            phase=spec.phase,
            category=spec.category,
            owner_person_id=owner,
            due_date=due,
            sort_order=order,
            db_path=db_path,
        )
    return plan_id


def activate_plan(plan_id: int, db_path: Path | None = None) -> bool:
    """Move a plan to ``active`` and fire its onboarding orchestration.

    On activation we enqueue (all idempotent, all pure DB inserts — the async
    scheduler does the actual sending):

    - the **ramp drip** (``enqueue_ramp``) — only actually fires once the plan
      has a roster ``person_id`` and pre-generated ``ramp_segments``;
    - the **kickoff** (``enqueue_kickoff``) — team notice + manager/buddy intro
      nudges, on the next tick;
    - the **milestone check-ins** (``enqueue_checkins``) — day 7/30/60/90.

    Returns False if the plan is missing.
    """
    plan = store.get_plan(plan_id, db_path=db_path)
    if plan is None:
        return False
    store.update_plan(plan_id, status=OnboardingStatus.ACTIVE, db_path=db_path)
    from openexecutive.staff_onboarding.orchestration import (
        enqueue_checkins,
        enqueue_kickoff,
    )
    from openexecutive.staff_onboarding.ramp_scheduler import enqueue_ramp

    enqueue_ramp(plan_id, db_path=db_path)
    enqueue_kickoff(plan_id, db_path=db_path)
    enqueue_checkins(plan_id, db_path=db_path)
    return True


def advance_phase(plan_id: int, db_path: Path | None = None) -> OnboardingPhase | None:
    """Move a plan to the next phase in ``_PHASE_ORDER``. Returns the new phase,
    or None if the plan is missing or already at the final phase."""
    plan = store.get_plan(plan_id, db_path=db_path)
    if plan is None:
        return None
    try:
        idx = _PHASE_ORDER.index(plan.current_phase)
    except ValueError:
        # Phase not in the known order (e.g. a future enum value not yet added
        # here) — refuse to advance rather than silently jumping to WEEK_1.
        logger.warning(
            "staff_onboarding: plan %d has phase %r outside _PHASE_ORDER",
            plan_id, plan.current_phase,
        )
        return None
    if idx >= len(_PHASE_ORDER) - 1:
        return None
    new_phase = _PHASE_ORDER[idx + 1]
    store.update_plan(plan_id, current_phase=new_phase, db_path=db_path)
    return new_phase
