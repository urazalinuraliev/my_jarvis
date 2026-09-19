"""Bounded ramp-drip scheduling for staff onboarding.

A plan's welcome-brief run pre-generates ``ramp_segments`` (one short message per
ramp day). Activating the plan enqueues the first ``onboarding_ramp`` scheduled
action; the scheduler runner delivers that day's segment and — only while more
remain — chains the next business-day occurrence. This is the one self-
terminating recurring kind in the system (every other recurring action chains
forever), so the chaining lives here next to the exhaustion check.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from openexecutive.staff_onboarding import store

logger = logging.getLogger(__name__)

# Hour-of-day (UTC) the daily drip is sent. Single-timezone for v1, matching the
# scheduler's principal-brief approach; revisit when company tz lands.
_RAMP_HOUR = 9


def next_business_day(after: datetime, *, hour: int = _RAMP_HOUR) -> datetime:
    """The next weekday (Mon-Fri) strictly after ``after``, at ``hour`` UTC.

    A naive ``after`` is treated as UTC so the returned ``run_at`` is always
    tz-aware (the scheduler compares due times against an aware ``now``)."""
    if after.tzinfo is None:
        after = after.replace(tzinfo=UTC)
    candidate = (after + timedelta(days=1)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )
    while candidate.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
        candidate += timedelta(days=1)
    return candidate


def enqueue_ramp(
    plan_id: int, *, after: datetime | None = None, db_path: Path | None = None
) -> int | None:
    """Enqueue the next ``onboarding_ramp`` action for a plan, or None when the
    plan can't drip (missing, no roster person, or segments exhausted)."""
    from openexecutive.memory.episodic import (
        insert_scheduled_action,
        list_scheduled_actions,
    )

    plan = store.get_plan(plan_id, db_path=db_path)
    if plan is None or plan.person_id is None:
        return None
    if plan.ramp_next_index >= len(plan.ramp_segments):
        return None  # nothing left to send — do not chain

    # Idempotency: never run two drip chains for one plan. A pending
    # onboarding_ramp row for this plan means a chain is already live, so a
    # repeat activate (double-click / retry / activate-while-mid-drip) is a
    # no-op. The chain itself is safe because each fire marks its row done
    # before enqueuing exactly one successor.
    pending = [
        a for a in list_scheduled_actions(status="pending", db_path=db_path)
        if a.kind == "onboarding_ramp" and a.channel_ref == str(plan_id)
    ]
    if pending:
        return None

    run_at = next_business_day(after or datetime.now(UTC))
    try:
        return insert_scheduled_action(
            run_at=run_at.isoformat(),
            channel="__internal__",
            channel_ref=str(plan_id),
            intent_text=f"Onboarding ramp drip for plan {plan_id}",
            kind="onboarding_ramp",
            assigned_to_person_id=plan.person_id,
            db_path=db_path,
        )
    except Exception:
        logger.exception("staff_onboarding: enqueue_ramp failed for plan %s", plan_id)
        return None


__all__ = ["enqueue_ramp", "next_business_day"]
