"""Interview coordination workflow — Phase 3 recruiting automation.

Drafts an interview loop (rounds, what each tests) plus a candidate-facing
availability-request message, then schedules a single reminder to the principal
to kick off scheduling. Draft-and-approve: OE never contacts the candidate
directly — the reminder hands the principal the ready-to-send availability
request and the loop plan.

Shares context/channel/scheduling machinery with the other talent workflows via
``openexecutive.talent.reminders``.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
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
_MAX_ROUNDS = 7


class InterviewCoordinationInput(BaseModel):
    """Inputs for the Interview Coordination workflow."""

    candidate_id: int = Field(..., description="Candidate to coordinate interviews for.")
    num_rounds: int = Field(
        default=4, ge=1, le=_MAX_ROUNDS,
        description="How many interview rounds to design (1-7).",
    )
    notes: str = Field(
        default="",
        description="Optional constraints (timeline, who must be on the panel, format).",
        max_length=2000,
    )


class InterviewCoordinationWorkflow(Workflow):
    name = "interview_coordination"
    title = "Interview Coordination"
    description = (
        "Designs the interview loop and drafts a candidate availability-request, "
        "then schedules a reminder to you to kick off scheduling. Never contacts "
        "the candidate directly."
    )
    section = WorkflowSection.PEOPLE
    estimated_minutes = 3

    def input_model(self) -> type[BaseModel]:
        return InterviewCoordinationInput

    def sample_inputs(self) -> dict[str, Any]:
        return {
            "candidate_id": 1,
            "num_rounds": 4,
            "notes": "Founder must take the final round; aim to close within two weeks.",
        }

    def steps(self) -> list[WorkflowStepDef]:
        return [
            WorkflowStepDef(
                id="load",
                title="Load candidate & recipient",
                description="Fetch the candidate, engagement, and the principal who'll coordinate.",
            ),
            WorkflowStepDef(
                id="design",
                title="Design loop & availability request",
                description="Interview rounds + a candidate-facing availability message.",
            ),
            WorkflowStepDef(
                id="schedule",
                title="Schedule reminder",
                description="Queue a reminder to you to kick off scheduling.",
            ),
        ]

    async def run(
        self,
        inputs: BaseModel,
        store: ChromaDBStore,
    ) -> AsyncIterator[WorkflowEvent]:
        assert isinstance(inputs, InterviewCoordinationInput)

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
                f"({ctx.company_name}); reminder → {ctx.principal.full_name}."
            ),
        )

        yield WorkflowEvent(
            type="step_start", step_id="design", step_title="Design loop & availability request"
        )
        rag = retrieve(
            query=f"executive interview loop plan {ctx.engagement.role_title} {ctx.engagement.must_haves}",
            specialist_name=_SPECIALIST,
            n_builtin=3,
            n_company=2,
            store=store,
        )
        loop = (
            await route_to_specialist(
                specialist_name=_SPECIALIST,
                query=_loop_prompt(ctx.engagement, ctx.candidate, inputs.num_rounds, inputs.notes),
                retrieved_knowledge=rag,
            )
        ).strip()
        availability = (
            await route_to_specialist(
                specialist_name=_SPECIALIST,
                query=_availability_prompt(ctx.engagement, ctx.candidate, ctx.company_name),
            )
        ).strip()
        yield WorkflowEvent(
            type="step_done", step_id="design", summary=f"Designed a {inputs.num_rounds}-round loop."
        )

        yield WorkflowEvent(
            type="step_start", step_id="schedule", step_title="Schedule reminder"
        )
        action_id = schedule_reminder(
            ctx=ctx,
            run_at=datetime.now(UTC),
            intent_text=_coord_reminder_text(ctx, loop, availability),
        )
        yield WorkflowEvent(
            type="step_done",
            step_id="schedule",
            summary=f"Scheduled a coordination reminder to {ctx.principal.full_name}.",
        )

        yield WorkflowEvent(
            type="result",
            data={
                "candidate_id": ctx.candidate.id,
                "engagement_id": ctx.engagement.id,
                "scheduled_count": 1,
                "action_ids": [action_id],
            },
        )
        yield WorkflowEvent(
            type="artifact",
            content=_assemble_artifact(ctx, loop, availability),
        )


def _coord_reminder_text(ctx: ReminderContext, loop: str, availability: str) -> str:
    return (
        f"Interview coordination for {ctx.candidate.full_name} on the "
        f"{ctx.engagement.role_title} search ({ctx.company_name}). Send the principal "
        "the proposed interview loop below and the ready-to-send availability request "
        "so they can line up the panel and send the request to the candidate. Do NOT "
        "contact the candidate directly.\n\n"
        f"--- INTERVIEW LOOP ---\n{loop}\n--- END LOOP ---\n\n"
        f"--- AVAILABILITY REQUEST (to send to candidate) ---\n{availability}\n"
        "--- END REQUEST ---"
    )


def _assemble_artifact(ctx: ReminderContext, loop: str, availability: str) -> str:
    lines = artifact_header(
        ctx,
        title="Interview Coordination",
        disclaimer=(
            "Drafts only — OE schedules a reminder to you to coordinate; you line up "
            "the panel and send the availability request. OE never contacts the "
            "candidate directly."
        ),
    )
    lines += [
        "## Proposed Interview Loop",
        "",
        loop or "_(none generated)_",
        "",
        "## Availability Request (to send to the candidate)",
        "",
        availability or "_(none generated)_",
    ]
    return "\n".join(lines).strip() + "\n"


def _loop_prompt(
    engagement: Engagement, candidate: Candidate, num_rounds: int, notes: str
) -> str:
    notes_block = f"\n\nConstraints from the principal: {notes.strip()}" if notes.strip() else ""
    return (
        f"Design a {num_rounds}-round interview loop for {candidate.full_name} for the "
        f"{engagement.role_title} role.\n\n"
        f"Role must-haves / context:\n{engagement.must_haves or '(not specified)'}\n"
        f"{engagement.description or ''}{notes_block}\n\n"
        f"Output (Markdown): a numbered list of exactly {num_rounds} rounds. For each: "
        "**Round name**, interviewer (role, e.g. founder / function head / peer), what "
        "it tests (tie to a must-have), and length in minutes. End with a one-line note "
        "on the working session or final-round focus. Be specific to THIS role — no "
        "generic 'culture fit' rounds without saying what that means here."
    )


def _availability_prompt(
    engagement: Engagement, candidate: Candidate, company_name: str
) -> str:
    return (
        f"Write a short, warm availability-request message to {candidate.full_name} to "
        f"schedule interviews for the {engagement.role_title} role at {company_name}.\n\n"
        "Output: the message body only (no subject, no commentary). Under 120 words. "
        "Explain the loop at a high level (how many conversations, roughly how long), "
        "ask for a few windows over the next 1-2 weeks, and keep it easy and respectful "
        "of their time. Sign off with a [Your name] placeholder."
    )
