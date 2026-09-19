"""Staff-onboarding digest for the briefing surfaces.

Mirrors ``briefing/talent_digest.py``: one rollup that both ``/today`` and the
chat ``<briefing>`` block share, so the structured cards and the chat digest
never disagree.

- :func:`build_onboarding_brief_items` → structured ``OnboardingBriefItem`` list
  for a dedicated ``/today`` section.
- :func:`format_onboarding_for_prompt` → a compact one-line-per-plan digest the
  chat route appends to the user-turn briefing so the Executive proactively
  knows who is onboarding and what's overdue.

Every entry point swallows its own errors and returns an empty result, so an
onboarding-store hiccup can never break a brief or a chat turn.
"""
from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import BaseModel

from openexecutive.staff_onboarding.models import OnboardingStatus, TaskStatus

logger = logging.getLogger(__name__)

# Plans in these statuses are still in flight; COMPLETED / ARCHIVED drop off.
_ACTIVE_STATUSES: frozenset[OnboardingStatus] = frozenset(
    {OnboardingStatus.DRAFT, OnboardingStatus.ACTIVE}
)

_OPEN_TASK_STATUSES: frozenset[TaskStatus] = frozenset(
    {TaskStatus.PENDING, TaskStatus.IN_PROGRESS}
)

_MAX_PLANS = 25


class OnboardingBriefItem(BaseModel):
    """One in-flight onboarding plan, rolled up for the briefing surfaces."""

    plan_id: int
    full_name: str
    role: str = ""
    status: str
    current_phase: str
    completion_pct: int = 0
    open_tasks: int = 0
    overdue_tasks: int = 0
    days_to_start: int | None = None  # negative once the hire has started


def _parse_date(iso: str) -> date | None:
    try:
        return date.fromisoformat(iso[:10])
    except (ValueError, TypeError):
        return None


def build_onboarding_brief_items(
    db_path: Path | None = None,
    *,
    limit: int = _MAX_PLANS,
) -> list[OnboardingBriefItem]:
    """Roll in-flight onboarding plans up into briefing items.

    Returns ``[]`` on any failure (e.g. the tables don't exist yet on a fresh
    install) rather than raising, so callers never have to guard it.
    """
    from openexecutive.staff_onboarding import store

    try:
        plans = store.list_plans(db_path=db_path)
    except Exception:
        logger.exception("onboarding_digest.list_plans_failed")
        return []

    today = datetime.now(UTC).date()
    items: list[OnboardingBriefItem] = []

    for plan in plans:
        if plan.status not in _ACTIVE_STATUSES or plan.id is None:
            continue
        try:
            tasks = store.list_tasks(plan.id, db_path=db_path)
        except Exception:
            logger.exception("onboarding_digest.list_tasks_failed plan_id=%s", plan.id)
            tasks = []

        open_tasks = 0
        overdue = 0
        for t in tasks:
            if t.status not in _OPEN_TASK_STATUSES:
                continue
            open_tasks += 1
            due = _parse_date(t.due_date) if t.due_date else None
            if due is not None and due < today:
                overdue += 1

        start = _parse_date(plan.start_date)
        days_to_start = (start - today).days if start is not None else None

        items.append(
            OnboardingBriefItem(
                plan_id=plan.id,
                full_name=plan.full_name,
                role=plan.role,
                status=plan.status.value,
                current_phase=plan.current_phase.value,
                completion_pct=plan.completion_pct,
                open_tasks=open_tasks,
                overdue_tasks=overdue,
                days_to_start=days_to_start,
            )
        )

    # Most attention-worthy first: overdue tasks, then least complete, then
    # soonest to start. Stable so ties keep store order.
    items.sort(
        key=lambda i: (
            -i.overdue_tasks,
            i.completion_pct,
            i.days_to_start if i.days_to_start is not None else 9999,
        )
    )
    return items[:limit]


def format_onboarding_for_prompt(
    db_path: Path | None = None,
    *,
    limit: int = _MAX_PLANS,
) -> str:
    """Render in-flight onboardings as a compact digest, or ``""`` when none.

    One line per plan::

        [plan <id>] <name> — <role> (<phase>, <pct>% done): N open · K overdue · starts in D days

    Pure synchronous reads — wrap in ``asyncio.to_thread`` at the call site.
    Never raises.
    """
    items = build_onboarding_brief_items(db_path=db_path, limit=limit)
    if not items:
        return ""

    lines: list[str] = []
    for it in items:
        parts = [f"{it.completion_pct}% done"]
        if it.open_tasks:
            parts.append(f"{it.open_tasks} open")
        if it.overdue_tasks:
            parts.append(f"{it.overdue_tasks} overdue")
        if it.days_to_start is not None:
            if it.days_to_start > 0:
                parts.append(f"starts in {it.days_to_start}d")
            elif it.days_to_start < 0:
                # Start date is day 1, so the day after start (days_to_start=-1)
                # is day 2 — hence abs()+1.
                parts.append(f"day {abs(it.days_to_start) + 1}")
            else:
                parts.append("starts today")
        role = f" — {it.role}" if it.role else ""
        lines.append(
            f"[plan {it.plan_id}] {it.full_name}{role} "
            f"({it.current_phase}): " + " · ".join(parts)
        )

    header = (
        "New hires currently onboarding — the principal sees these as cards on "
        "/today. Each line is [plan <id>] name — role (phase): progress rollup. "
        "When the user asks about a hire's onboarding, this is what they mean; "
        "use the onboarding tools to pull or update plan detail."
    )
    return header + "\n" + "\n".join(lines)


__all__ = [
    "OnboardingBriefItem",
    "build_onboarding_brief_items",
    "format_onboarding_for_prompt",
]
