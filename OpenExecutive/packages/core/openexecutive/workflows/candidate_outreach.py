"""Candidate outreach sequence workflow — Phase 3 recruiting automation.

Drafts a personalized first-touch plus N scheduled follow-ups for a candidate on
an engagement (via the talent specialist) and schedules each touch as a
*reminder to the principal* — never a direct message to the candidate.

Posture: draft-and-approve. OE never emails candidates. Each scheduled reminder
is the human checkpoint: when it fires, the Executive DMs the principal the
ready-to-send draft for review and manual sending. This sidesteps the roster-
gated outbound model (candidates are not `Person` records) and the deferred
generator-resume limitation (a `wait_for_human` gate would pause and never
schedule), while keeping a human in the loop on every touch.

Context resolution, principal-channel routing, and reminder scheduling are
shared with the other talent workflows via ``openexecutive.talent.reminders``.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field

from openexecutive.knowledge.retriever import retrieve
from openexecutive.knowledge.store import ChromaDBStore
from openexecutive.orchestrator.router import route_to_specialist
from openexecutive.talent.models import Candidate, Engagement
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

_SPECIALIST = "talent"
_MAX_FOLLOW_UPS = 5


class CandidateOutreachInput(BaseModel):
    """Inputs for the Candidate Outreach Sequence workflow."""

    candidate_id: int = Field(..., description="Candidate to build the outreach sequence for.")
    follow_up_count: int = Field(
        default=2, ge=0, le=_MAX_FOLLOW_UPS,
        description="Number of follow-up touches after the first (0-5).",
    )
    follow_up_interval_days: int = Field(
        default=3, ge=1, le=30,
        description="Days between touches.",
    )
    angle: str = Field(
        default="",
        description="Optional emphasis for the outreach (e.g. 'lead with the platform rebuild').",
        max_length=2000,
    )


class CandidateOutreachWorkflow(Workflow):
    name = "candidate_outreach"
    title = "Candidate Outreach Sequence"
    description = (
        "Drafts a personalized first-touch plus scheduled follow-ups for a "
        "candidate and schedules each as a reminder to you (the principal) to "
        "review and send. Never contacts the candidate directly."
    )
    section = WorkflowSection.PEOPLE
    estimated_minutes = 3

    def input_model(self) -> type[BaseModel]:
        return CandidateOutreachInput

    def sample_inputs(self) -> dict[str, Any]:
        return {
            "candidate_id": 1,
            "follow_up_count": 2,
            "follow_up_interval_days": 3,
            "angle": "lead with the year-one mandate and the scope of the role",
        }

    def steps(self) -> list[WorkflowStepDef]:
        return [
            WorkflowStepDef(
                id="load",
                title="Load candidate & recipient",
                description="Fetch the candidate, engagement, and the principal who'll send.",
            ),
            WorkflowStepDef(
                id="draft",
                title="Draft the sequence",
                description="First-touch + follow-ups, personalized to the role.",
            ),
            WorkflowStepDef(
                id="schedule",
                title="Schedule reminders",
                description="Queue a review-and-send reminder to you for each touch.",
            ),
        ]

    async def run(
        self,
        inputs: BaseModel,
        store: ChromaDBStore,
    ) -> AsyncIterator[WorkflowEvent]:
        assert isinstance(inputs, CandidateOutreachInput)

        yield WorkflowEvent(
            type="step_start", step_id="load", step_title="Load candidate & recipient"
        )
        ctx = resolve_reminder_context(inputs.candidate_id)
        if isinstance(ctx, str):
            yield WorkflowEvent(type="error", message=ctx)
            return
        yield WorkflowEvent(
            type="step_done",
            step_id="load",
            summary=(
                f"{ctx.candidate.full_name} for {ctx.engagement.role_title} "
                f"({ctx.company_name}); reminders → {ctx.principal.full_name} via {ctx.channel}."
            ),
        )

        yield WorkflowEvent(
            type="step_start", step_id="draft", step_title="Draft the sequence"
        )
        rag = retrieve(
            query=f"executive outreach message {ctx.engagement.role_title} {ctx.engagement.must_haves}",
            specialist_name=_SPECIALIST,
            n_builtin=3,
            n_company=2,
            store=store,
        )
        touches: list[tuple[str, str]] = []
        first = await route_to_specialist(
            specialist_name=_SPECIALIST,
            query=_first_touch_prompt(ctx.engagement, ctx.candidate, ctx.company_name, inputs.angle),
            retrieved_knowledge=rag,
        )
        touches.append(("First touch", first.strip()))
        for k in range(1, inputs.follow_up_count + 1):
            body = await route_to_specialist(
                specialist_name=_SPECIALIST,
                query=_follow_up_prompt(
                    ctx.engagement, ctx.candidate, ctx.company_name, k, inputs.follow_up_count
                ),
            )
            touches.append((f"Follow-up {k}", body.strip()))
        yield WorkflowEvent(
            type="step_done", step_id="draft", summary=f"Drafted {len(touches)} touches."
        )

        yield WorkflowEvent(
            type="step_start", step_id="schedule", step_title="Schedule reminders"
        )
        # Compute each touch's send time ONCE (touch i at now + i*interval) so the
        # scheduled reminders and the artifact can't drift apart.
        now = datetime.now(UTC)
        schedule = [
            (label, body, now + timedelta(days=i * inputs.follow_up_interval_days))
            for i, (label, body) in enumerate(touches)
        ]
        total = len(schedule)
        action_ids = [
            schedule_reminder(
                ctx=ctx,
                run_at=run_at_dt,
                intent_text=_reminder_text(
                    label, i + 1, total, ctx.candidate, ctx.engagement, ctx.company_name, body
                ),
            )
            for i, (label, body, run_at_dt) in enumerate(schedule)
        ]
        yield WorkflowEvent(
            type="step_done",
            step_id="schedule",
            summary=f"Scheduled {len(action_ids)} reminders to {ctx.principal.full_name}.",
        )

        yield WorkflowEvent(
            type="result",
            data={
                "candidate_id": ctx.candidate.id,
                "engagement_id": ctx.engagement.id,
                "scheduled_count": len(action_ids),
                "action_ids": action_ids,
            },
        )
        yield WorkflowEvent(
            type="artifact",
            content=_assemble_artifact(
                ctx, schedule, inputs.follow_up_interval_days
            ),
        )


def _reminder_text(
    label: str,
    n: int,
    total: int,
    candidate: Candidate,
    engagement: Engagement,
    company_name: str,
    body: str,
) -> str:
    """Instruction delivered to the Executive at fire time — DM the principal the
    draft for review. Explicitly forbids contacting the candidate directly."""
    who = candidate.full_name
    if candidate.current_title:
        who += f" ({candidate.current_title}"
        who += f" at {candidate.current_company})" if candidate.current_company else ")"
    return (
        f"Outreach reminder {n}/{total} ({label}) for the {engagement.role_title} "
        f"search ({company_name}). Send the principal this ready-to-send draft for "
        f"{who} so they can review and send it themselves. Do NOT contact the "
        f"candidate directly.\n\n"
        f"--- DRAFT ({label}) ---\n{body}\n--- END DRAFT ---"
    )


def _assemble_artifact(
    ctx: ReminderContext,
    schedule: list[tuple[str, str, datetime]],
    interval_days: int,
) -> str:
    lines = artifact_header(
        ctx,
        title="Outreach Sequence",
        disclaimer=(
            "Drafts only — OE schedules a reminder to you for each touch; you "
            "review and send to the candidate. OE never contacts candidates directly."
        ),
        meta_lines=[f"**Cadence:** first touch now, then every {interval_days} day(s)  "],
    )
    for label, body, run_at_dt in schedule:
        send_on = run_at_dt.date().isoformat()
        lines += [f"## {label} — send ~{send_on}", "", body.strip(), ""]
    return "\n".join(lines).strip() + "\n"


def _first_touch_prompt(
    engagement: Engagement, candidate: Candidate, company_name: str, angle: str
) -> str:
    angle_block = f"\n\nEmphasis the principal asked for: {angle.strip()}" if angle.strip() else ""
    return (
        f"Write a personalized FIRST-TOUCH outreach message to {candidate.full_name} "
        f"({candidate.current_title or 'an executive'}"
        f"{f' at {candidate.current_company}' if candidate.current_company else ''}) "
        f"about the {engagement.role_title} search for {company_name}.\n\n"
        f"Role must-haves / context:\n{engagement.must_haves or '(not specified)'}\n"
        f"{engagement.description or ''}{angle_block}\n\n"
        "Output: the message body only (no subject line, no preamble, no commentary). "
        "Keep it under 150 words, specific to this person's background, and lead with "
        "why THEM for THIS role — not a generic recruiter blast. Sign off as the "
        "principal (use a [Your name] placeholder)."
    )


def _follow_up_prompt(
    engagement: Engagement, candidate: Candidate, company_name: str, k: int, total: int
) -> str:
    return (
        f"Write follow-up #{k} of {total} to {candidate.full_name} for the "
        f"{engagement.role_title} search ({company_name}). They have not replied to "
        "the previous message(s).\n\n"
        "Output: the message body only (no subject, no commentary). Under 100 words, "
        "add a NEW angle or piece of value each time (don't just 'bump' the thread), "
        "stay warm and low-pressure, and make it easy to decline. Sign off with a "
        "[Your name] placeholder."
    )
