"""New-hire onboarding workflow — the placed → Person handoff.

When an offer is accepted (candidate ``placed``), the talent module and the
people module need to connect: the candidate becomes a real
:class:`~openexecutive.people.models.Person` the Executive can address, and
their first 90 days get a plan plus milestone check-ins.

This workflow is the *explicit* trigger for that handoff — Person creation
is never a hidden side effect of a stage change. It is idempotent: re-running
matches the existing Person (by email, else exact name) and updates their
role instead of duplicating them.

Posture: milestone reminders go to the *principal* (never the new hire) —
each fires as a prompt to run the check-in themselves.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from pydantic import BaseModel, Field

from openexecutive.knowledge.retriever import retrieve
from openexecutive.knowledge.store import ChromaDBStore
from openexecutive.orchestrator.router import route_to_specialist
from openexecutive.talent import store as talent_store
from openexecutive.talent.models import CandidateStage, Engagement, OfferStatus
from openexecutive.talent.reminders import (
    ReminderContext,
    artifact_header,
    resolve_reminder_context,
    schedule_reminder,
)
from openexecutive.workflows.base import (
    Workflow,
    WorkflowEvent,
    WorkflowSection,
    WorkflowStepDef,
)

logger = logging.getLogger(__name__)

_SPECIALIST = "chro"

# Day offsets for the milestone check-in reminders. Day 7 catches early
# drift; 30/60/90 mirror the plan the chro drafts.
_CHECKIN_DAYS = (7, 30, 60, 90)


class NewHireOnboardingInput(BaseModel):
    """Inputs for the New-Hire Onboarding workflow."""

    candidate_id: int = Field(..., description="The placed candidate to onboard.")
    start_date: str = Field(
        default="",
        description="The hire's start date (ISO date, e.g. 2026-07-01). Defaults to today.",
    )
    focus_notes: str = Field(
        default="",
        description=(
            "Optional emphasis for the 30/60/90 plan (e.g. 'first priority is "
            "stabilizing the field ops team')."
        ),
        max_length=2000,
    )


class NewHireOnboardingWorkflow(Workflow):
    name = "new_hire_onboarding"
    title = "New-Hire Onboarding (30/60/90)"
    description = (
        "Turns a placed candidate into a Person on the roster, drafts a "
        "role-specific 30/60/90 onboarding plan, and schedules milestone "
        "check-in reminders to you (the principal). Never contacts the new "
        "hire directly. Run it after recording an accepted offer."
    )
    section = WorkflowSection.PEOPLE
    estimated_minutes = 3

    def input_model(self) -> type[BaseModel]:
        return NewHireOnboardingInput

    def sample_inputs(self) -> dict[str, Any]:
        return {
            "candidate_id": 1,
            "start_date": "",
            "focus_notes": "first priority is stabilizing the field ops team",
        }

    def steps(self) -> list[WorkflowStepDef]:
        return [
            WorkflowStepDef(
                id="load",
                title="Load the placed candidate",
                description="Verify the hire is placed (or their offer accepted).",
            ),
            WorkflowStepDef(
                id="create_person",
                title="Add to the roster",
                description="Create (or update) the Person record for the new hire.",
            ),
            WorkflowStepDef(
                id="design_plan",
                title="Draft the 30/60/90 plan",
                description="Role-specific onboarding plan via the people specialist.",
            ),
            WorkflowStepDef(
                id="schedule_checkins",
                title="Schedule check-ins",
                description="Queue day-7/30/60/90 check-in reminders to you.",
            ),
        ]

    async def run(
        self,
        inputs: BaseModel,
        store: ChromaDBStore,
    ) -> AsyncIterator[WorkflowEvent]:
        assert isinstance(inputs, NewHireOnboardingInput)

        yield WorkflowEvent(
            type="step_start", step_id="load", step_title="Load the placed candidate"
        )
        ctx = resolve_reminder_context(inputs.candidate_id)
        if isinstance(ctx, str):
            yield WorkflowEvent(type="error", message=ctx)
            return
        accepted = talent_store.list_offers(
            candidate_id=inputs.candidate_id, status=OfferStatus.ACCEPTED
        )
        if ctx.candidate.stage is not CandidateStage.PLACED and not accepted:
            yield WorkflowEvent(
                type="error",
                message=(
                    f"{ctx.candidate.full_name} is not placed and has no accepted "
                    "offer — record the offer acceptance first "
                    "(record_offer_decision)."
                ),
            )
            return
        try:
            start = (
                date.fromisoformat(inputs.start_date)
                if inputs.start_date.strip()
                else datetime.now(UTC).date()
            )
        except ValueError:
            yield WorkflowEvent(
                type="error",
                message=f"start_date is not an ISO date: {inputs.start_date!r}",
            )
            return
        yield WorkflowEvent(
            type="step_done",
            step_id="load",
            summary=(
                f"{ctx.candidate.full_name} → {ctx.engagement.role_title} "
                f"({ctx.company_name}), starting {start.isoformat()}."
            ),
        )

        yield WorkflowEvent(
            type="step_start", step_id="create_person", step_title="Add to the roster"
        )
        person_id, created = _upsert_hire_person(ctx)
        yield WorkflowEvent(
            type="step_done",
            step_id="create_person",
            summary=(
                f"{'Added' if created else 'Updated'} {ctx.candidate.full_name} "
                f"on the roster (person {person_id})."
            ),
        )

        yield WorkflowEvent(
            type="step_start", step_id="design_plan", step_title="Draft the 30/60/90 plan"
        )
        rag = retrieve(
            query=f"executive onboarding 30 60 90 plan {ctx.engagement.role_title}",
            specialist_name=_SPECIALIST,
            n_builtin=3,
            n_company=2,
            store=store,
        )
        plan = (
            await route_to_specialist(
                specialist_name=_SPECIALIST,
                query=_plan_prompt(ctx.engagement, ctx.candidate.full_name, ctx.company_name,
                                   start, inputs.focus_notes),
                retrieved_knowledge=rag,
            )
        ).strip()
        yield WorkflowEvent(
            type="step_done", step_id="design_plan", summary="30/60/90 plan drafted."
        )

        yield WorkflowEvent(
            type="step_start", step_id="schedule_checkins", step_title="Schedule check-ins"
        )
        now = datetime.now(UTC)
        action_ids: list[int] = []
        scheduled_days: list[int] = []
        for day in _CHECKIN_DAYS:
            run_at = datetime.combine(start + timedelta(days=day), time(9, 0), tzinfo=UTC)
            if run_at <= now:
                continue  # don't fire check-ins for milestones already past
            action_ids.append(
                schedule_reminder(
                    ctx=ctx,
                    run_at=run_at,
                    intent_text=_checkin_text(day, ctx),
                )
            )
            scheduled_days.append(day)
        yield WorkflowEvent(
            type="step_done",
            step_id="schedule_checkins",
            summary=(
                f"Scheduled {len(action_ids)} check-in reminders "
                f"(days {', '.join(str(d) for d in scheduled_days) or '—'}) "
                f"to {ctx.principal.full_name}."
            ),
        )

        yield WorkflowEvent(
            type="result",
            data={
                "person_id": person_id,
                "person_created": created,
                "candidate_id": ctx.candidate.id,
                "engagement_id": ctx.engagement.id,
                "scheduled_count": len(action_ids),
                "action_ids": action_ids,
            },
        )
        yield WorkflowEvent(
            type="artifact",
            content=_assemble_artifact(ctx, plan, start, scheduled_days),
        )


def _upsert_hire_person(ctx: ReminderContext) -> tuple[int, bool]:
    """Create or update the Person record for the hire. Returns (id, created).

    Idempotent: matches an existing non-archived Person by case-insensitive
    email (when the candidate has one), else by exact full name, and updates
    their role rather than duplicating. New hires get no authority scopes —
    those are granted deliberately, not by onboarding.
    """
    from openexecutive.people.store import (
        find_person_by_email,
        list_people,
        upsert_person,
    )

    candidate = ctx.candidate
    existing = None
    if candidate.email:
        existing = find_person_by_email(candidate.email)
    if existing is None:
        existing = next(
            (p for p in list_people() if p.full_name == candidate.full_name), None
        )

    dept_slugs = _resolvable_department_slugs(ctx.engagement)
    if existing is not None and existing.id is not None:
        upsert_person(
            full_name=existing.full_name,
            role=ctx.engagement.role_title,
            is_principal=existing.is_principal,
            # The engagement is the source of truth for the NEW role (role is
            # overwritten above for the same reason) — a re-hire moving
            # departments must not keep the stale slugs. Existing slugs only
            # survive when the engagement's department doesn't resolve.
            department_slugs=dept_slugs or existing.department_slugs,
            email=existing.email or candidate.email,
            slack_user_id=existing.slack_user_id,
            telegram_chat_id=existing.telegram_chat_id,
            discord_user_id=existing.discord_user_id,
            preferred_channel=existing.preferred_channel,
            response_sla_hours=existing.response_sla_hours,
            on_leave_until=existing.on_leave_until,
            reports_to_person_id=existing.reports_to_person_id,
            person_id=existing.id,
        )
        return existing.id, False
    person_id = upsert_person(
        full_name=candidate.full_name,
        role=ctx.engagement.role_title,
        email=candidate.email,
        department_slugs=dept_slugs,
    )
    return person_id, True


def _resolvable_department_slugs(engagement: Engagement) -> list[str]:
    """Map the engagement's free-text department to a real slug, if it is one.

    ``Engagement.department`` is a plain label, not a FK — only pass it onto
    the Person when it resolves in the department registry.
    """
    from openexecutive.departments.registry import get_state

    label = engagement.department.strip()
    if not label:
        return []
    for candidate_slug in (label, label.lower(), label.lower().replace(" ", "_")):
        if get_state(candidate_slug) is not None:
            return [candidate_slug]
    return []


def _checkin_text(day: int, ctx: ReminderContext) -> str:
    return (
        f"Onboarding check-in (day {day}) for {ctx.candidate.full_name}, "
        f"{ctx.engagement.role_title} at {ctx.company_name}. DM the principal "
        f"the day-{day} milestone questions from the onboarding plan so they "
        "can run the check-in themselves. Do NOT contact the new hire "
        "directly — this is a reminder for the principal."
    )


def _assemble_artifact(
    ctx: ReminderContext, plan: str, start: date, scheduled_days: list[int]
) -> str:
    lines = artifact_header(
        ctx,
        title="Onboarding Plan",
        disclaimer=(
            "Check-in reminders go to you — OE never contacts the new hire "
            "directly. You run each milestone conversation yourself."
        ),
        meta_lines=[
            f"**Start date:** {start.isoformat()}  ",
            f"**Check-ins:** day {', '.join(str(d) for d in scheduled_days) or '(none scheduled)'}  ",
        ],
    )
    lines += ["## 30/60/90 plan", "", plan]
    return "\n".join(lines).strip() + "\n"


def _plan_prompt(
    engagement: Engagement,
    hire_name: str,
    company_name: str,
    start: date,
    focus_notes: str,
) -> str:
    focus_block = (
        f"\n\nEmphasis from the principal: {focus_notes.strip()}" if focus_notes.strip() else ""
    )
    return (
        f"Draft a 30/60/90-day onboarding plan for {hire_name}, our new "
        f"{engagement.role_title} at {company_name}, starting {start.isoformat()}.\n\n"
        f"Role must-haves / mandate:\n{engagement.must_haves or '(not specified)'}\n"
        f"{engagement.description or ''}{focus_block}\n\n"
        "Output, in Markdown: a section each for days 1-30 (learn), 31-60 "
        "(own), 61-90 (deliver), each with 3-5 concrete outcomes tied to this "
        "role's mandate, plus a final section of milestone check-in questions "
        "for day 7, 30, 60, and 90. No preamble."
    )
