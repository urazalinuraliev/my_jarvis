"""Stakeholder orchestration for staff onboarding.

Activating a plan does three things beyond the ramp drip (``ramp_scheduler``):

1. **Kickoff** (one-shot, fires next tick): a welcome notice to the hire's
   department channel *if one is configured* (never an accidental broadcast),
   plus intro-1:1 nudges DM'd to the manager and buddy.
2. **Milestone check-ins** (day 7 / 30 / 60 / 90): scheduled actions that DM the
   hire + manager a check-in and deterministically advance the plan's phase. The
   recipient's reply lands in chat, where the Executive's onboarding tools fold
   it into task/plan progress (``wait_for_human`` resume is a Phase-7 item, so we
   deliberately use the chat-integrated path that works today).

All sends happen in the async scheduler runner (consistent with the ramp), so
these enqueue functions are pure, synchronous DB inserts — unit-testable without
touching any integration.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from openexecutive.staff_onboarding import store
from openexecutive.staff_onboarding.models import OnboardingPhase

logger = logging.getLogger(__name__)

_INTERNAL_CHANNEL = "__internal__"
_CHECKIN_HOUR = 9  # UTC, matching the ramp drip

# Milestone label → (days after start, phase the plan advances to on fire).
# Ordered; day_7 maps to WEEK_1 since the 30/60/90 enum starts at DAY_30.
MILESTONES: tuple[tuple[str, int, OnboardingPhase], ...] = (
    ("day_7", 7, OnboardingPhase.WEEK_1),
    ("day_30", 30, OnboardingPhase.DAY_30),
    ("day_60", 60, OnboardingPhase.DAY_60),
    ("day_90", 90, OnboardingPhase.DAY_90),
)


def _parse_date(iso: str) -> datetime | None:
    try:
        d = datetime.fromisoformat(iso[:10])
        return d.replace(hour=_CHECKIN_HOUR, minute=0, second=0, microsecond=0, tzinfo=UTC)
    except (ValueError, TypeError):
        return None


def _already_enqueued(scope_key: str, db_path: Path | None) -> bool:
    """True if a live (pending/running/done) action with this ``scope_key``
    already exists, so re-activating a plan never duplicates kickoff/check-in
    rows. A single indexed lookup — covers the ``running`` window and is not
    capped (unlike scanning ``list_scheduled_actions``).

    NOTE: this is a read-then-insert check, not a DB-level uniqueness
    constraint, so a narrow TOCTOU window remains if two activations race for
    the same plan. The scheduler is single-worker and activation is operator-
    triggered, so the worst case is a duplicate DM — acceptable for v1."""
    from openexecutive.memory.episodic import scope_key_in_use

    return scope_key_in_use(scope_key, db_path=db_path)


def _plan_department(plan_id: int, db_path: Path | None) -> str:
    """The department of a plan's template, or "" — used to route the team
    notice to a department channel."""
    plan = store.get_plan(plan_id, db_path=db_path)
    if plan is None or not plan.template_name:
        return ""
    tmpl = store.get_template(plan.template_name, db_path=db_path)
    return tmpl.department if tmpl is not None else ""


def enqueue_kickoff(plan_id: int, *, db_path: Path | None = None) -> int | None:
    """Enqueue the one-shot kickoff action (team notice + intro nudges).

    Fires on the next scheduler tick. Idempotent. Returns the action id, or None
    if the plan is missing or a kickoff was already enqueued."""
    from openexecutive.memory.episodic import insert_scheduled_action

    plan = store.get_plan(plan_id, db_path=db_path)
    if plan is None:
        return None
    channel_ref = str(plan_id)
    scope_key = f"onboarding_kickoff:{plan_id}"
    if _already_enqueued(scope_key, db_path):
        return None
    try:
        return insert_scheduled_action(
            run_at=datetime.now(UTC).isoformat(),
            channel=_INTERNAL_CHANNEL,
            channel_ref=channel_ref,
            intent_text=f"Onboarding kickoff for plan {plan_id} ({plan.full_name})",
            kind="onboarding_kickoff",
            department=_plan_department(plan_id, db_path),
            assigned_to_person_id=plan.person_id,
            scope_key=scope_key,
            db_path=db_path,
        )
    except Exception:
        logger.exception("staff_onboarding: enqueue_kickoff failed for plan %s", plan_id)
        return None


def enqueue_checkins(plan_id: int, *, db_path: Path | None = None) -> list[int]:
    """Enqueue milestone check-in actions for a plan. Returns the ids enqueued.

    Skips milestones whose date is already in the past (activating a hire who
    has been around a while shouldn't backfire historical check-ins) and any
    already enqueued. Each milestone is its own pre-scheduled row — they do not
    self-chain."""
    from openexecutive.memory.episodic import insert_scheduled_action

    plan = store.get_plan(plan_id, db_path=db_path)
    if plan is None or plan.person_id is None:
        return []
    base = _parse_date(plan.start_date)
    if base is None:
        logger.warning("staff_onboarding: plan %s has unparseable start_date", plan_id)
        return []

    now = datetime.now(UTC)
    department = _plan_department(plan_id, db_path)
    enqueued: list[int] = []
    for label, offset, _phase in MILESTONES:
        run_at = base + timedelta(days=offset)
        if run_at <= now:
            continue  # milestone already in the past — skip
        channel_ref = f"{plan_id}:{label}"
        scope_key = f"onboarding_checkin:{plan_id}:{label}"
        if _already_enqueued(scope_key, db_path):
            continue
        try:
            aid = insert_scheduled_action(
                run_at=run_at.isoformat(),
                channel=_INTERNAL_CHANNEL,
                channel_ref=channel_ref,
                intent_text=f"Onboarding {label} check-in for plan {plan_id}",
                kind="onboarding_checkin",
                department=department,
                assigned_to_person_id=plan.person_id,
                scope_key=scope_key,
                db_path=db_path,
            )
            enqueued.append(aid)
        except Exception:
            logger.exception(
                "staff_onboarding: enqueue_checkins %s/%s failed", plan_id, label
            )
    return enqueued


def phase_for_milestone(label: str) -> OnboardingPhase | None:
    """The phase a milestone label advances a plan to, or None if unknown."""
    for name, _offset, phase in MILESTONES:
        if name == label:
            return phase
    return None


__all__ = [
    "MILESTONES",
    "enqueue_checkins",
    "enqueue_kickoff",
    "phase_for_milestone",
]
