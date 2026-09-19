"""Pydantic models for the staff-onboarding framework.

This is the *staff* (employee) onboarding subsystem — onboarding a person into
the company — distinct from the *company-setup* wizard in
``openexecutive.onboarding`` and from the people roster in
``openexecutive.people``.

The three entities mirror the shape of ``openexecutive.talent.models`` (plain
Pydantic v2 models, optional ``id``, ISO-string ``created_at`` / ``updated_at``,
``archived`` soft-delete):

- ``OnboardingTemplate`` — a reusable, role/department-scoped blueprint: an
  ordered set of task specs (phase + owner-by-role + due offset), the specialist
  sections the welcome brief is built from, ramp length, and a check-in cadence.
- ``OnboardingPlan`` — one per hire, instantiated from a template and tailored
  from company context. Carries the generated welcome brief + reading list and
  rolls its tasks up into ``completion_pct``.
- ``OnboardingTask`` — one checklist item on a plan: phase, owner, due date,
  status.
"""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class OnboardingStatus(StrEnum):
    """Lifecycle of one hire's onboarding plan."""

    DRAFT = "draft"          # created, not yet activated (no orchestration fired)
    ACTIVE = "active"        # in progress
    COMPLETED = "completed"  # all phases done
    ARCHIVED = "archived"    # cancelled / no longer tracked


class OnboardingPhase(StrEnum):
    """Phases of a ramp, in forward order. ``due_offset_days`` on a task spec is
    relative to the hire's start date, so phases are a display grouping rather
    than a hard gate."""

    PRE_START = "pre_start"
    WEEK_1 = "week_1"
    DAY_30 = "day_30"
    DAY_60 = "day_60"
    DAY_90 = "day_90"


class TaskStatus(StrEnum):
    """Status of one checklist item."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    SKIPPED = "skipped"  # explicitly not applicable — excluded from completion %


# Owner roles a template task can target. Resolved to a concrete person_id at
# instantiation against the plan (hire / manager / buddy) or the roster
# (department head, IT, etc.). Kept as free-text-with-known-values rather than an
# enum so a template author can name a role the resolver falls back to "manager"
# on, without a schema change.
KNOWN_OWNER_ROLES = ("hire", "manager", "buddy", "department_head", "it", "hr")


class TaskSpec(BaseModel):
    """One task in a template — instantiated into an ``OnboardingTask``."""

    title: str
    category: str = "general"
    phase: OnboardingPhase = OnboardingPhase.WEEK_1
    owner_role: str = "manager"
    # Days after the hire's start date this task is due. May be negative for
    # pre-start tasks (e.g. -3 = three days before day one).
    due_offset_days: int = 0


class OnboardingTemplate(BaseModel):
    """A reusable onboarding blueprint.

    ``name`` is a unique snake_case key. ``department`` is a free-text grouping
    (also used as a hint when resolving the brief's lead specialist).
    ``brief_sections`` lists the section ids the ``role_onboarding`` workflow
    renders (e.g. ``company_landscape``, ``function_state``).
    """

    name: str
    title: str
    description: str = ""
    department: str = ""
    # Number of daily ramp-drip messages to send the hire (one per business day
    # from start). 0 = no drip. Capped to keep a drip from running for months.
    ramp_days: int = Field(default=0, ge=0, le=90)
    # Human cadence spec for milestone check-ins, e.g. "day_7,day_30,day_60,day_90".
    checkin_cadence: str = ""
    task_specs: list[TaskSpec] = Field(default_factory=list)
    brief_sections: list[str] = Field(default_factory=list)
    is_active: bool = True
    created_at: str = ""
    updated_at: str = ""


class OnboardingTask(BaseModel):
    """One checklist item on a plan."""

    id: int | None = None
    plan_id: int
    phase: OnboardingPhase = OnboardingPhase.WEEK_1
    title: str
    category: str = "general"
    owner_person_id: int | None = None
    due_date: str | None = None  # ISO date (YYYY-MM-DD)
    status: TaskStatus = TaskStatus.PENDING
    completed_at: str | None = None
    completed_by_person_id: int | None = None
    notes: str = ""
    sort_order: int = 0
    created_at: str = ""
    updated_at: str = ""


class OnboardingPlan(BaseModel):
    """One hire's onboarding plan.

    ``person_id`` links the hire to the roster once they exist as a ``Person`` —
    it is what unlocks delivery + the ramp drip + check-ins. ``engagement_id`` /
    ``candidate_id`` link back to the talent pipeline when the plan originated
    from a placed candidate. ``completion_pct`` is computed from the plan's tasks
    on read (never stored).
    """

    id: int | None = None
    full_name: str
    role: str = ""
    start_date: str  # ISO date (YYYY-MM-DD)
    person_id: int | None = None
    manager_person_id: int | None = None
    buddy_person_id: int | None = None
    template_name: str = ""
    status: OnboardingStatus = OnboardingStatus.DRAFT
    current_phase: OnboardingPhase = OnboardingPhase.PRE_START
    brief_artifact: str = ""
    reading_list: list[str] = Field(default_factory=list)
    # Pre-generated daily ramp-drip messages and the index of the next one to
    # send. The scheduler's bounded ``onboarding_ramp`` action walks these.
    ramp_segments: list[str] = Field(default_factory=list)
    ramp_next_index: int = 0
    engagement_id: int | None = None
    candidate_id: int | None = None
    completion_pct: int = 0
    archived: bool = False
    created_at: str = ""
    updated_at: str = ""
    # Populated only by ``get_plan`` (detail view); list endpoints leave it empty.
    tasks: list[OnboardingTask] = Field(default_factory=list)
