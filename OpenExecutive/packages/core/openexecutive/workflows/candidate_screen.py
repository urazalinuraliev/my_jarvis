"""Candidate screen workflow — assesses one candidate against one search
engagement and produces a fit scorecard.

Reuses the existing workflow machinery (``Workflow`` ABC, ``WorkflowEvent``
stream, domain-filtered RAG via ``retrieve``, and the talent specialist via
``route_to_specialist``). The screen's numeric fit score and summary are
persisted back onto the candidate row through ``talent.store.record_screening``,
which also advances a raw ``lead`` to ``screened``.
"""
from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, Field

from openexecutive.knowledge.retriever import retrieve
from openexecutive.knowledge.store import ChromaDBStore
from openexecutive.orchestrator.router import route_to_specialist
from openexecutive.talent import graph as talent_graph
from openexecutive.talent import store as talent_store
from openexecutive.talent.models import Candidate, Engagement
from openexecutive.workflows.base import (
    Workflow,
    WorkflowEvent,
    WorkflowSection,
    WorkflowStepDef,
)

_SPECIALIST = "talent"


class CandidateScreenInput(BaseModel):
    """Inputs for the Candidate Screen workflow.

    Both ids must reference existing, non-archived rows. The candidate must
    belong to the engagement — screening a candidate against a different
    engagement than the one they're tracked under is a caller error, not a
    silent reassignment.
    """

    engagement_id: int = Field(..., description="The search engagement to screen against.")
    candidate_id: int = Field(..., description="The candidate to screen.")


class CandidateScreenWorkflow(Workflow):
    name = "candidate_screen"
    title = "Candidate Screen"
    description = (
        "Screens one candidate against one executive-search engagement: a "
        "fit score (0-100), evidence mapped to the must-haves, the biggest "
        "risk, and an advance/pass recommendation. Persists the score and "
        "summary onto the candidate and advances them to 'screened'."
    )
    section = WorkflowSection.PEOPLE
    estimated_minutes = 3

    def input_model(self) -> type[BaseModel]:
        return CandidateScreenInput

    def steps(self) -> list[WorkflowStepDef]:
        return [
            WorkflowStepDef(
                id="load",
                title="Load engagement & candidate",
                description="Fetch the search mandate and the candidate record.",
            ),
            WorkflowStepDef(
                id="assess",
                title="Screen candidate",
                description="The talent specialist scores fit against the must-haves.",
            ),
            WorkflowStepDef(
                id="persist",
                title="Record screening",
                description="Save the fit score & summary; advance the pipeline stage.",
            ),
        ]

    async def run(
        self,
        inputs: BaseModel,
        store: ChromaDBStore,
    ) -> AsyncIterator[WorkflowEvent]:
        assert isinstance(inputs, CandidateScreenInput)

        yield WorkflowEvent(
            type="step_start", step_id="load", step_title="Load engagement & candidate"
        )
        engagement = talent_store.get_engagement(inputs.engagement_id)
        candidate = talent_store.get_candidate(inputs.candidate_id)
        if engagement is None:
            yield WorkflowEvent(
                type="error", message=f"Engagement {inputs.engagement_id} not found."
            )
            return
        if candidate is None:
            yield WorkflowEvent(
                type="error", message=f"Candidate {inputs.candidate_id} not found."
            )
            return
        if candidate.engagement_id != engagement.id:
            yield WorkflowEvent(
                type="error",
                message=(
                    f"Candidate {candidate.id} belongs to engagement "
                    f"{candidate.engagement_id}, not {engagement.id}."
                ),
            )
            return
        from openexecutive.talent.reminders import company_name as _company_name

        company_name = _company_name()
        yield WorkflowEvent(
            type="step_done",
            step_id="load",
            summary=f"{candidate.full_name} vs. {engagement.role_title} for {company_name}.",
        )

        yield WorkflowEvent(
            type="step_start", step_id="assess", step_title="Screen candidate"
        )
        rag = retrieve(
            query=(
                f"executive screening interview scorecard {engagement.role_title} "
                f"{engagement.must_haves}"
            ),
            specialist_name=_SPECIALIST,
            n_builtin=4,
            n_company=2,
            store=store,
        )
        assessment = await route_to_specialist(
            specialist_name=_SPECIALIST,
            query=_build_screen_prompt(engagement, candidate),
            retrieved_knowledge=rag,
        )
        fit_score = _parse_fit_score(assessment)
        yield WorkflowEvent(
            type="step_done",
            step_id="assess",
            summary=(
                f"Fit score: {fit_score}/100." if fit_score is not None
                else "Assessment complete (no numeric score parsed)."
            ),
        )

        yield WorkflowEvent(
            type="step_start", step_id="persist", step_title="Record screening"
        )
        recorded = False
        if fit_score is not None and candidate.id is not None:
            recorded = talent_store.record_screening(
                candidate.id, fit_score=fit_score, summary=assessment
            )
            if recorded:
                # Re-index so the talent graph reflects the new screening
                # summary (the richest matching signal). Best-effort.
                refreshed = talent_store.get_candidate(candidate.id)
                if refreshed is not None:
                    talent_graph.index_candidate(refreshed, store)
        yield WorkflowEvent(
            type="step_done",
            step_id="persist",
            summary=(
                "Saved score and advanced pipeline stage." if recorded
                else "Skipped persistence — no defensible score to record."
            ),
        )

        # Structured payload first (for programmatic consumers), then the
        # human-facing Markdown artifact — same ordering the base ABC documents.
        yield WorkflowEvent(
            type="result",
            data={
                "candidate_id": candidate.id,
                "engagement_id": engagement.id,
                "fit_score": fit_score,
                "recorded": recorded,
            },
        )
        yield WorkflowEvent(
            type="artifact",
            content=_assemble_scorecard(
                engagement, candidate, company_name, fit_score, assessment
            ),
        )

    def sample_inputs(self) -> dict[str, Any]:
        return {"engagement_id": 1, "candidate_id": 1}


def _build_screen_prompt(engagement: Engagement, candidate: Candidate) -> str:
    must_haves = engagement.must_haves.strip() or "(none specified)"
    description = engagement.description.strip() or "(no additional context)"
    cand_lines = [
        f"- Name: {candidate.full_name}",
        f"- Current title: {candidate.current_title or '(unknown)'}",
        f"- Current company: {candidate.current_company or '(unknown)'}",
        f"- Location: {candidate.location or '(unknown)'}",
    ]
    if candidate.notes.strip():
        cand_lines.append(f"- Notes / background: {candidate.notes.strip()}")
    candidate_block = "\n".join(cand_lines)
    return (
        f"Screen this candidate for the **{engagement.role_title}** search "
        f"(comp band: {engagement.comp_band or 'unspecified'}; "
        f"location: {engagement.location or 'unspecified'}).\n\n"
        f"Must-haves / year-one outcomes:\n{must_haves}\n\n"
        f"Role context:\n{description}\n\n"
        f"Candidate:\n{candidate_block}\n\n"
        "Output (Markdown), in this order:\n"
        "1. **Fit score: N/100** — one line, where N is an integer 0-100, "
        "with a one-sentence justification tied to the must-haves.\n"
        "2. **Evidence for fit** — map what we know about the candidate to "
        "each must-have / outcome.\n"
        "3. **Gaps & biggest risk** — the single biggest risk and the "
        "reference/interview probe that would confirm or kill it.\n"
        "4. **Recommendation** — one of: advance / advance-with-reservations / pass.\n\n"
        "Discipline: score from evidence, not optimism. If a must-have is "
        "unmet, the score must reflect it. Begin your response with the "
        "literal text 'Fit score: ' so the number is unambiguous."
    )


def _parse_fit_score(text: str) -> int | None:
    """Extract a 0-100 integer fit score from the specialist's prose.

    Deliberately conservative: it matches ONLY the ``N/100`` form the prompt
    mandates ("**Fit score: N/100**"). Bare numbers are never parsed, because a
    score is indistinguishable from prose like "3/5 must-haves" or "5 criteria
    reviewed" — and recording a wrong score is worse than recording none. All
    ``N/100`` occurrences are scanned and the first in-range one wins, so a
    stray out-of-range "150/100" doesn't block a later valid "82/100". A miss
    returns None and the caller skips persistence (the safe failure mode).
    """
    if not text:
        return None
    for m in re.finditer(r"(\d{1,3})\s*/\s*100\b", text):
        value = int(m.group(1))
        if 0 <= value <= 100:
            return value
    return None


def _assemble_scorecard(
    engagement: Engagement,
    candidate: Candidate,
    company_name: str,
    fit_score: int | None,
    assessment: str,
) -> str:
    score_line = f"{fit_score}/100" if fit_score is not None else "not parsed"
    body = assessment.strip() or "_(No assessment generated.)_"
    parts = [
        f"# Candidate Screen — {candidate.full_name}",
        "",
        f"**Engagement:** {engagement.role_title} ({company_name})  ",
        f"**Fit score:** {score_line}  ",
        f"**Current:** {candidate.current_title or '—'} @ "
        f"{candidate.current_company or '—'}",
        "",
        "## Assessment",
        "",
        body,
        "",
        "---",
        "*Drafted by the Talent & Executive Search specialist. Review with the "
        "hiring committee before advancing the candidate.*",
    ]
    return "\n".join(parts).strip() + "\n"
