"""Reference check workflow — Phase 3 recruiting automation.

Drafts a reference-check rubric (questions + what a concerning answer looks like)
plus a reference-facing outreach message, then schedules a single reminder to the
principal to conduct the checks. Draft-and-approve: OE never contacts references
directly — the reminder hands the principal the rubric and the ready-to-send
outreach.

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
_MAX_REFERENCES = 5


class ReferenceCheckInput(BaseModel):
    """Inputs for the Reference Check workflow."""

    candidate_id: int = Field(..., description="Candidate to run reference checks for.")
    reference_count: int = Field(
        default=2, ge=1, le=_MAX_REFERENCES,
        description="How many references to plan for (1-5).",
    )
    reference_notes: str = Field(
        default="",
        description="Optional known references or focus areas (names, relationships, concerns to probe).",
        max_length=2000,
    )


class ReferenceCheckWorkflow(Workflow):
    name = "reference_check"
    title = "Reference Check"
    description = (
        "Drafts a reference-check rubric and a reference-outreach message, then "
        "schedules a reminder to you to conduct the checks. Never contacts "
        "references directly."
    )
    section = WorkflowSection.PEOPLE
    estimated_minutes = 3

    def input_model(self) -> type[BaseModel]:
        return ReferenceCheckInput

    def sample_inputs(self) -> dict[str, Any]:
        return {
            "candidate_id": 1,
            "reference_count": 2,
            "reference_notes": "One former manager, one former direct report. Probe the 2020 downturn.",
        }

    def steps(self) -> list[WorkflowStepDef]:
        return [
            WorkflowStepDef(
                id="load",
                title="Load candidate & recipient",
                description="Fetch the candidate, engagement, and the principal who'll conduct.",
            ),
            WorkflowStepDef(
                id="draft",
                title="Draft rubric & outreach",
                description="Reference questions + a reference-facing outreach message.",
            ),
            WorkflowStepDef(
                id="schedule",
                title="Schedule reminder",
                description="Queue a reminder to you to conduct the checks.",
            ),
        ]

    async def run(
        self,
        inputs: BaseModel,
        store: ChromaDBStore,
    ) -> AsyncIterator[WorkflowEvent]:
        assert isinstance(inputs, ReferenceCheckInput)

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
            type="step_start", step_id="draft", step_title="Draft rubric & outreach"
        )
        rag = retrieve(
            query=f"executive reference check questions {ctx.engagement.role_title}",
            specialist_name=_SPECIALIST,
            n_builtin=3,
            n_company=2,
            store=store,
        )
        rubric = (
            await route_to_specialist(
                specialist_name=_SPECIALIST,
                query=_rubric_prompt(ctx.engagement, ctx.candidate, inputs.reference_notes),
                retrieved_knowledge=rag,
            )
        ).strip()
        outreach = (
            await route_to_specialist(
                specialist_name=_SPECIALIST,
                query=_outreach_prompt(ctx.engagement, ctx.candidate, ctx.company_name),
            )
        ).strip()
        yield WorkflowEvent(
            type="step_done",
            step_id="draft",
            summary=f"Drafted a rubric and outreach for {inputs.reference_count} reference(s).",
        )

        yield WorkflowEvent(
            type="step_start", step_id="schedule", step_title="Schedule reminder"
        )
        action_id = schedule_reminder(
            ctx=ctx,
            run_at=datetime.now(UTC),
            intent_text=_ref_reminder_text(ctx, inputs.reference_count, rubric, outreach),
        )
        yield WorkflowEvent(
            type="step_done",
            step_id="schedule",
            summary=f"Scheduled a reference-check reminder to {ctx.principal.full_name}.",
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
            content=_assemble_artifact(ctx, inputs.reference_count, rubric, outreach),
        )


def _ref_reminder_text(
    ctx: ReminderContext, reference_count: int, rubric: str, outreach: str
) -> str:
    return (
        f"Reference checks ({reference_count}) for {ctx.candidate.full_name} on the "
        f"{ctx.engagement.role_title} search ({ctx.company_name}). Send the principal the "
        "rubric below and the ready-to-send reference-outreach so they can line up and "
        "run the references themselves. Do NOT contact the references directly.\n\n"
        f"--- REFERENCE RUBRIC ---\n{rubric}\n--- END RUBRIC ---\n\n"
        f"--- REFERENCE OUTREACH (to send to references) ---\n{outreach}\n"
        "--- END OUTREACH ---"
    )


def _assemble_artifact(
    ctx: ReminderContext, reference_count: int, rubric: str, outreach: str
) -> str:
    lines = artifact_header(
        ctx,
        title="Reference Check",
        disclaimer=(
            "Drafts only — OE schedules a reminder to you to run the references; you "
            "contact them yourself. OE never contacts references directly."
        ),
        meta_lines=[f"**References planned:** {reference_count}  "],
    )
    lines += [
        "## Reference Rubric",
        "",
        rubric or "_(none generated)_",
        "",
        "## Reference Outreach (to send to references)",
        "",
        outreach or "_(none generated)_",
    ]
    return "\n".join(lines).strip() + "\n"


def _rubric_prompt(engagement: Engagement, candidate: Candidate, notes: str) -> str:
    notes_block = f"\n\nKnown references / focus from the principal: {notes.strip()}" if notes.strip() else ""
    return (
        f"Write a reference-check rubric for {candidate.full_name}, a candidate for the "
        f"{engagement.role_title} role.\n\n"
        f"Role must-haves / context:\n{engagement.must_haves or '(not specified)'}\n"
        f"{engagement.description or ''}{notes_block}\n\n"
        "Output (Markdown): 6-8 specific questions to ask every reference, each with a "
        "one-line note on what answer would CONCERN us (the signal we're listening for). "
        "Tie the questions to this role's must-haves and risks — not a generic 'would you "
        "rehire them' list. Add a final question that invites the reference to flag "
        "anything we didn't ask about."
    )


def _outreach_prompt(
    engagement: Engagement, candidate: Candidate, company_name: str
) -> str:
    return (
        f"Write a short, professional message to a REFERENCE (not the candidate) to set "
        f"up a reference conversation about {candidate.full_name}, who we're considering "
        f"for the {engagement.role_title} role at {company_name}.\n\n"
        "Output: the message body only (no subject, no commentary). Under 120 words. "
        "Briefly say why we're reaching out, that the candidate gave their name, ask for "
        "20-30 minutes, and offer a few windows. Warm and respectful of their time. Sign "
        "off with a [Your name] placeholder."
    )
