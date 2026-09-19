"""Offer package & approval workflow — closing the hire loop.

Drafts a complete offer package for a candidate (terms via the CHRO
specialist anchored on the engagement's comp band, closing plan via the
talent specialist), persists it as an :class:`~openexecutive.talent.models.Offer`,
DMs the HIRING_SIGNOFF approver a summary, and pauses on a
``WaitForHumanEvent`` gate so the approval is recorded against the run.

This is the first *built-in* workflow to yield the gate (previously only
user-created dynamic workflows did). Paused runs never auto-resume
(generator resume is deferred upstream), so the gate's job here is to
*record* the sign-off — the ``pending_approval → extended`` transition is an
explicit follow-up action (the ``extend_offer`` tool / ``POST
/offers/{id}/extend``) that consults the recorded resolution via
``openexecutive.talent.offers``. The ``result`` and ``artifact`` events are
yielded *before* the gate, and the package Markdown is persisted onto the
Offer row, so nothing is lost when the run pauses.

Posture: OE never sends the offer to the candidate. The approver gets the
sign-off request; the principal extends the offer themselves after sign-off.
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, Field

from openexecutive.knowledge.retriever import retrieve
from openexecutive.knowledge.store import ChromaDBStore
from openexecutive.orchestrator.router import route_to_specialist
from openexecutive.talent import store as talent_store
from openexecutive.talent.models import (
    Candidate,
    CandidateStage,
    Engagement,
    Offer,
    OfferStatus,
)
from openexecutive.talent.offers import gate_context_summary
from openexecutive.talent.reminders import (
    ReminderContext,
    artifact_header,
    person_channel_raw,
    resolve_reminder_context,
)
from openexecutive.workflows.base import (
    Workflow,
    WorkflowEvent,
    WorkflowSection,
    WorkflowStepDef,
)
from openexecutive.workflows.wait_for_human import WaitForHumanEvent

logger = logging.getLogger(__name__)

_TERMS_SPECIALIST = "chro"
_CLOSE_SPECIALIST = "talent"

# Candidates must have at least been interviewed before an offer is drafted.
_OFFERABLE_STAGES = (CandidateStage.INTERVIEWED, CandidateStage.OFFER)

_SIGNOFF_TIMEOUT_HOURS = 72


class OfferApprovalInput(BaseModel):
    """Inputs for the Offer Package & Approval workflow."""

    candidate_id: int = Field(..., description="Candidate to draft the offer for.")
    comp_notes: str = Field(
        default="",
        description=(
            "Optional terms the principal already has in mind (base, equity, "
            "sign-on, start date…). The drafted terms anchor on these plus the "
            "engagement's comp band."
        ),
        max_length=2000,
    )
    angle: str = Field(
        default="",
        description="Optional emphasis for the close (e.g. 'they have a competing offer').",
        max_length=2000,
    )


class OfferApprovalWorkflow(Workflow):
    name = "offer_approval"
    title = "Offer Package & Approval"
    description = (
        "Drafts a complete offer package (terms anchored on the engagement's "
        "comp band, plus a closing plan), sends the hiring sign-off request to "
        "the HIRING_SIGNOFF approver, and pauses until they reply. After "
        "approval, mark the offer extended (extend_offer) when you send it — "
        "OE never sends the offer to the candidate."
    )
    section = WorkflowSection.PEOPLE
    estimated_minutes = 4

    def input_model(self) -> type[BaseModel]:
        return OfferApprovalInput

    def sample_inputs(self) -> dict[str, Any]:
        return {
            "candidate_id": 1,
            "comp_notes": "base around the top of band, 0.5% equity, modest sign-on",
            "angle": "they are also in late stages with a competitor",
        }

    def steps(self) -> list[WorkflowStepDef]:
        return [
            WorkflowStepDef(
                id="load",
                title="Load candidate & approver",
                description="Fetch the candidate, engagement, and the hiring sign-off approver.",
            ),
            WorkflowStepDef(
                id="draft_terms",
                title="Draft offer terms",
                description="Comp package anchored on the engagement's comp band.",
            ),
            WorkflowStepDef(
                id="close_plan",
                title="Closing plan",
                description="Closing risks, competing-offer posture, recommended expiry window.",
            ),
            WorkflowStepDef(
                id="persist",
                title="Persist the offer",
                description="Save the offer package and move the candidate to the offer stage.",
            ),
            WorkflowStepDef(
                id="request_signoff",
                title="Request sign-off",
                description="DM the approver and pause until they approve or reject.",
            ),
        ]

    async def run(
        self,
        inputs: BaseModel,
        store: ChromaDBStore,
    ) -> AsyncIterator[WorkflowEvent]:
        assert isinstance(inputs, OfferApprovalInput)

        yield WorkflowEvent(
            type="step_start", step_id="load", step_title="Load candidate & approver"
        )
        ctx = resolve_reminder_context(inputs.candidate_id)
        if isinstance(ctx, str):
            yield WorkflowEvent(type="error", message=ctx)
            return
        if ctx.candidate.stage not in _OFFERABLE_STAGES:
            yield WorkflowEvent(
                type="error",
                message=(
                    f"{ctx.candidate.full_name} is at stage "
                    f"'{ctx.candidate.stage.value}' — screen and interview them "
                    "before drafting an offer."
                ),
            )
            return
        if talent_store.get_open_offer_for_candidate(inputs.candidate_id) is not None:
            yield WorkflowEvent(
                type="error",
                message=(
                    f"{ctx.candidate.full_name} already has an open offer — record "
                    "a decision on it (or rescind it) before drafting another."
                ),
            )
            return
        approver = _resolve_approver(ctx)
        yield WorkflowEvent(
            type="step_done",
            step_id="load",
            summary=(
                f"{ctx.candidate.full_name} for {ctx.engagement.role_title} "
                f"({ctx.company_name}); sign-off → {approver.full_name}."
            ),
        )

        yield WorkflowEvent(
            type="step_start", step_id="draft_terms", step_title="Draft offer terms"
        )
        rag = retrieve(
            query=(
                f"compensation offer design {ctx.engagement.role_title} "
                f"{ctx.engagement.comp_band}"
            ),
            specialist_name=_TERMS_SPECIALIST,
            n_builtin=3,
            n_company=2,
            store=store,
        )
        terms = (
            await route_to_specialist(
                specialist_name=_TERMS_SPECIALIST,
                query=_terms_prompt(ctx.engagement, ctx.candidate, ctx.company_name, inputs.comp_notes),
                retrieved_knowledge=rag,
            )
        ).strip()
        yield WorkflowEvent(
            type="step_done", step_id="draft_terms", summary=f"Drafted terms ({len(terms)} chars)."
        )

        yield WorkflowEvent(
            type="step_start", step_id="close_plan", step_title="Closing plan"
        )
        close_plan = (
            await route_to_specialist(
                specialist_name=_CLOSE_SPECIALIST,
                query=_close_prompt(ctx.engagement, ctx.candidate, ctx.company_name, inputs.angle),
            )
        ).strip()
        yield WorkflowEvent(
            type="step_done", step_id="close_plan", summary="Closing plan ready."
        )

        yield WorkflowEvent(
            type="step_start", step_id="persist", step_title="Persist the offer"
        )
        comp_summary = inputs.comp_notes.strip() or ctx.engagement.comp_band or "see package"
        try:
            offer_id = talent_store.create_offer(
                candidate_id=inputs.candidate_id,
                engagement_id=ctx.candidate.engagement_id,
                comp_summary=comp_summary,
            )
        except ValueError as exc:
            # Raced another create between the load guard and here.
            yield WorkflowEvent(type="error", message=str(exc))
            return
        offer = talent_store.get_offer(offer_id)
        assert offer is not None
        artifact_md = _assemble_artifact(ctx, offer, terms, close_plan, approver.full_name)
        talent_store.update_offer_terms(offer_id, package_md=artifact_md)
        talent_store.set_offer_status(offer_id, OfferStatus.PENDING_APPROVAL)
        if ctx.candidate.stage is CandidateStage.INTERVIEWED:
            # Mirrors record_screening advancing lead → screened: drafting an
            # offer is what moves a candidate into the offer stage.
            talent_store.set_candidate_stage(inputs.candidate_id, CandidateStage.OFFER)
        yield WorkflowEvent(
            type="step_done",
            step_id="persist",
            summary=f"Offer {offer_id} saved (pending approval).",
        )

        yield WorkflowEvent(
            type="step_start", step_id="request_signoff", step_title="Request sign-off"
        )
        question = (
            f"Approve the offer to {ctx.candidate.full_name} for the "
            f"{ctx.engagement.role_title} role? (offer_id={offer_id}) "
            f"Terms: {comp_summary}"
        )
        outbound_message_id = await _dm_approver(approver.id or 0, question, offer_id, ctx)
        channel, channel_ref = person_channel_raw(approver) or ("", "")
        yield WorkflowEvent(
            type="step_done",
            step_id="request_signoff",
            summary=f"Sign-off requested from {approver.full_name}; run pauses until they reply.",
        )

        # result + artifact BEFORE the gate: the HTTP runner stops at the gate
        # without completing the run, so anything after it would be lost.
        yield WorkflowEvent(
            type="result",
            data={
                "offer_id": offer_id,
                "candidate_id": ctx.candidate.id,
                "engagement_id": ctx.engagement.id,
                "approver_person_id": approver.id,
            },
        )
        yield WorkflowEvent(type="artifact", content=artifact_md)

        gate = WaitForHumanEvent(
            person_id=approver.id or 0,
            question=question,
            timeout_hours=_SIGNOFF_TIMEOUT_HOURS,
            on_timeout="escalate",
            context_summary=gate_context_summary(
                offer, ctx.candidate.full_name, ctx.engagement.role_title
            ),
            expected_reply_shape="approve_reject",
            department=_department_slug(ctx.engagement),
            outbound_message_id=outbound_message_id,
            channel=channel,
            channel_ref=channel_ref,
        )
        # WaitForHumanEvent is a sentinel the runner isinstance-checks; it
        # isn't a WorkflowEvent, hence the typed-yield ignore (same as
        # workflows/dynamic.py).
        yield gate  # type: ignore[misc]
        return


def _resolve_approver(ctx: ReminderContext) -> Any:
    """The HIRING_SIGNOFF approver, falling back to the principal.

    ``find_approvers`` prefers delegated humans over the principal and
    includes WILDCARD holders; an empty result (no scope rows configured at
    all) falls back to the principal, who is the operator of record.
    """
    from openexecutive.people.models import AuthorityScope
    from openexecutive.people.store import find_approvers

    approvers = find_approvers(AuthorityScope.HIRING_SIGNOFF)
    return approvers[0] if approvers else ctx.principal


def _department_slug(engagement: Engagement) -> str:
    """Resolve the engagement's free-text department to a real slug, or ''.

    The gate's ``department`` drives timeout escalation routing — only pass
    it when it resolves to an actual department.
    """
    from openexecutive.departments.registry import get_state

    label = engagement.department.strip()
    if not label:
        return ""
    for candidate_slug in (label, label.lower(), label.lower().replace(" ", "_")):
        if get_state(candidate_slug) is not None:
            return candidate_slug
    return ""


async def _dm_approver(
    approver_person_id: int, question: str, offer_id: int, ctx: ReminderContext
) -> str:
    """Best-effort DM of the sign-off request to the approver.

    Delegates to ``handle_message_person`` (same path the scheduler uses for
    dynamic-workflow artifact delivery) — it resolves the channel server-side
    and falls back to a briefing alert when no DM channel is deliverable, so
    the request always lands somewhere visible. Returns the outbound message
    id when the channel reports one, else "".
    """
    from openexecutive.orchestrator.schedule_tools import handle_message_person

    text = (
        f"Hiring sign-off needed: {question}\n\n"
        f"Full package: /talent/candidates/{ctx.candidate.id}\n"
        "Reply approve / reject / defer."
    )
    try:
        raw = await handle_message_person(
            {"person_id": approver_person_id, "text": text}
        )
    except Exception:  # noqa: BLE001 — an undeliverable DM must not kill the gate
        logger.warning(
            "offer_approval: sign-off DM failed (offer %s)", offer_id, exc_info=True
        )
        return ""
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return ""
    return str(parsed.get("message_id") or parsed.get("ts") or "")


def _assemble_artifact(
    ctx: ReminderContext,
    offer: Offer,
    terms: str,
    close_plan: str,
    approver_name: str,
) -> str:
    lines = artifact_header(
        ctx,
        title="Offer Package",
        disclaimer=(
            "Draft for sign-off — OE never sends the offer to the candidate. "
            f"After {approver_name} approves, you extend the offer yourself and "
            "mark it extended so expiry reminders start."
        ),
        meta_lines=[
            f"**Comp band:** {ctx.engagement.comp_band or '(not set — confirm comp before extending)'}  ",
            f"**Sign-off:** {approver_name}  ",
            f"**Offer id:** {offer.id}  ",
        ],
    )
    lines += [
        "## Proposed terms",
        "",
        terms,
        "",
        "## Closing plan",
        "",
        close_plan,
        "",
        "## Next steps",
        "",
        f"1. {approver_name} approves or rejects the sign-off request.",
        "2. On approval, you send the offer to the candidate yourself.",
        "3. Mark it extended (extend_offer) — expiry reminders are scheduled then.",
        "4. Record the outcome (accepted / declined / expired) when you hear back.",
    ]
    return "\n".join(lines).strip() + "\n"


def _terms_prompt(
    engagement: Engagement, candidate: Candidate, company_name: str, comp_notes: str
) -> str:
    band = engagement.comp_band.strip() or (
        "(none set — flag clearly that the principal must confirm comp before extending)"
    )
    notes_block = (
        f"\n\nTerms the principal has in mind:\n{comp_notes.strip()}" if comp_notes.strip() else ""
    )
    return (
        f"Draft the offer TERMS for {candidate.full_name} "
        f"({candidate.current_title or 'an executive'}"
        f"{f' at {candidate.current_company}' if candidate.current_company else ''}) "
        f"for the {engagement.role_title} role at {company_name}.\n\n"
        f"Comp band for this role: {band}\n"
        f"Role must-haves / context:\n{engagement.must_haves or '(not specified)'}\n"
        f"{engagement.description or ''}{notes_block}\n\n"
        "Output: a concise terms section in Markdown — base salary (anchored to "
        "the band), equity, sign-on/relocation if warranted, start date posture, "
        "and any contingencies (references, background check). State the "
        "reasoning for each number in one line. No preamble, no commentary."
    )


def _close_prompt(
    engagement: Engagement, candidate: Candidate, company_name: str, angle: str
) -> str:
    angle_block = f"\n\nContext from the principal: {angle.strip()}" if angle.strip() else ""
    return (
        f"We are about to extend an offer to {candidate.full_name} for the "
        f"{engagement.role_title} role at {company_name}.{angle_block}\n\n"
        "Output, in Markdown: (1) the top closing risks for this specific "
        "candidate and how to pre-empt each, (2) competing-offer posture — what "
        "to do if they shop it, (3) a recommended expiry window for the offer "
        "with one line of reasoning. Keep it tight; no preamble."
    )
