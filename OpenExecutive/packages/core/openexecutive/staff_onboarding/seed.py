"""Default onboarding templates seeded at startup.

Idempotent: a template is only inserted when its ``name`` isn't already present,
so an operator's edits to a seeded template are never clobbered on restart
(mirrors ``scheduler.seed_principal_briefs``).
"""
from __future__ import annotations

import logging
from pathlib import Path

from openexecutive.staff_onboarding import store
from openexecutive.staff_onboarding.models import (
    OnboardingPhase,
    OnboardingTemplate,
    TaskSpec,
)

logger = logging.getLogger(__name__)

# Tasks every hire shares, regardless of function. Owners are template roles
# resolved against the plan/roster at instantiation (hire/manager/it/hr/buddy).
_COMMON_TASKS: list[TaskSpec] = [
    TaskSpec(title="Send offer letter & confirm start date", category="hr",
             phase=OnboardingPhase.PRE_START, owner_role="hr", due_offset_days=-7),
    TaskSpec(title="Provision laptop, accounts & access", category="it",
             phase=OnboardingPhase.PRE_START, owner_role="it", due_offset_days=-2),
    TaskSpec(title="Welcome & intro 1:1 with manager", category="people",
             phase=OnboardingPhase.WEEK_1, owner_role="manager", due_offset_days=1),
    TaskSpec(title="Meet your onboarding buddy", category="people",
             phase=OnboardingPhase.WEEK_1, owner_role="buddy", due_offset_days=2),
    TaskSpec(title="Read the welcome brief & company handbook", category="ramp",
             phase=OnboardingPhase.WEEK_1, owner_role="hire", due_offset_days=3),
    TaskSpec(title="30-day check-in with manager", category="people",
             phase=OnboardingPhase.DAY_30, owner_role="manager", due_offset_days=30),
    TaskSpec(title="60-day check-in with manager", category="people",
             phase=OnboardingPhase.DAY_60, owner_role="manager", due_offset_days=60),
    TaskSpec(title="90-day review & ramp retrospective", category="people",
             phase=OnboardingPhase.DAY_90, owner_role="manager", due_offset_days=90),
]

_DEFAULT_TEMPLATES: list[OnboardingTemplate] = [
    OnboardingTemplate(
        name="generic",
        title="Generic Onboarding",
        description="Default cross-functional onboarding for any new hire.",
        ramp_days=5,
        checkin_cadence="day_7,day_30,day_60,day_90",
        task_specs=_COMMON_TASKS,
        brief_sections=["company_landscape", "function_state", "people_map",
                        "first_90", "week_one"],
    ),
    OnboardingTemplate(
        name="engineering",
        title="Engineering Onboarding",
        description="Onboarding for engineering / product hires.",
        department="product",
        ramp_days=7,
        checkin_cadence="day_7,day_30,day_60,day_90",
        task_specs=[
            *_COMMON_TASKS,
            TaskSpec(title="Set up dev environment & ship a starter PR",
                     category="engineering", phase=OnboardingPhase.WEEK_1,
                     owner_role="buddy", due_offset_days=4),
            TaskSpec(title="Walk the architecture & on-call runbook",
                     category="engineering", phase=OnboardingPhase.WEEK_1,
                     owner_role="manager", due_offset_days=5),
        ],
        brief_sections=["company_landscape", "function_state", "people_map",
                        "first_90", "week_one"],
    ),
    OnboardingTemplate(
        name="go_to_market",
        title="Go-to-Market Onboarding",
        description="Onboarding for sales / marketing / revenue hires.",
        department="marketing",
        ramp_days=7,
        checkin_cadence="day_7,day_30,day_60,day_90",
        task_specs=[
            *_COMMON_TASKS,
            TaskSpec(title="Learn the pitch, ICP & competitive positioning",
                     category="gtm", phase=OnboardingPhase.WEEK_1,
                     owner_role="manager", due_offset_days=4),
            TaskSpec(title="Shadow customer calls & review the funnel",
                     category="gtm", phase=OnboardingPhase.DAY_30,
                     owner_role="buddy", due_offset_days=14),
        ],
        brief_sections=["company_landscape", "function_state", "people_map",
                        "first_90", "week_one"],
    ),
    OnboardingTemplate(
        name="finance",
        title="Finance Onboarding",
        description="Onboarding for finance / accounting hires.",
        department="finance",
        ramp_days=5,
        checkin_cadence="day_7,day_30,day_60,day_90",
        task_specs=[
            *_COMMON_TASKS,
            TaskSpec(title="Review the model, board metrics & close process",
                     category="finance", phase=OnboardingPhase.WEEK_1,
                     owner_role="manager", due_offset_days=4),
        ],
        brief_sections=["company_landscape", "function_state", "people_map",
                        "first_90", "week_one"],
    ),
]


def seed_default_templates(db_path: Path | None = None) -> int:
    """Insert any missing default templates. Returns the number newly inserted."""
    inserted = 0
    for tmpl in _DEFAULT_TEMPLATES:
        try:
            if store.get_template(tmpl.name, db_path=db_path) is not None:
                continue
            store.upsert_template(tmpl, db_path=db_path)
            inserted += 1
        except Exception:
            logger.exception("staff_onboarding: failed to seed template %r", tmpl.name)
    if inserted:
        logger.info("staff_onboarding: seeded %d default template(s)", inserted)
    return inserted


__all__ = ["seed_default_templates"]
