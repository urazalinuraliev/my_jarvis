"""Org design review workflow — produces a structured analysis of a
proposed organizational change: rationale, structure delta, span-of-
control sanity check, transition plan, and comms strategy.

Uses the CHRO and CFO specialists.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, Field

from openexecutive.knowledge.retriever import retrieve
from openexecutive.knowledge.store import ChromaDBStore
from openexecutive.memory.company_profile import CompanyProfile
from openexecutive.onboarding.profile_builder import load_or_create_profile
from openexecutive.orchestrator.router import route_to_specialist
from openexecutive.workflows.base import (
    Workflow,
    WorkflowEvent,
    WorkflowSection,
    WorkflowStepDef,
)

_OD_EXAMPLE_CURRENT = (
    "Engineering: 12 ICs reporting to a single VP Engineering. Two team "
    "leads informally split backend (5 reports) and frontend (3 reports), "
    "with platform (4 reports) reporting directly to the VP. Product has "
    "3 PMs reporting to the CEO."
)
_OD_EXAMPLE_PROPOSED = (
    "Split engineering into three teams: Backend (with a Director hired "
    "externally), Frontend (current frontend lead promoted to manager), "
    "Platform (current platform lead promoted to manager). All three "
    "managers report to the VP. Product PMs move from CEO to a new Head "
    "of Product role (external hire)."
)
_OD_EXAMPLE_MOTIVATION = (
    "VP Engineering is at 12 directs, can't do real performance management. "
    "Three platform incidents in 90 days suggest the platform team needs "
    "dedicated leadership. CEO can't be PM-manager and CEO simultaneously "
    "now that we're 40 people."
)
_OD_EXAMPLE_CONSTRAINTS = (
    "Two new manager-level hires are in the comp band but the Director-"
    "level external hire is +$80K above current band. No additional budget "
    "for IC backfills caused by promotions."
)


class OrgDesignInput(BaseModel):
    """Inputs for the Org Design Review workflow."""

    current_structure: str = Field(
        ...,
        description=(
            "How the org is structured today — reporting lines, span of "
            "control, where the friction is."
        ),
        min_length=30,
        examples=[_OD_EXAMPLE_CURRENT],
    )
    proposed_structure: str = Field(
        ...,
        description=(
            "The proposed structure. Be concrete: new roles, who reports "
            "to whom, who's promoted, who's hired externally."
        ),
        min_length=30,
        examples=[_OD_EXAMPLE_PROPOSED],
    )
    motivation: str = Field(
        ...,
        description=(
            "Why now? What signal forced this — span-of-control breakdowns, "
            "execution failures, growth scale, performance issues."
        ),
        min_length=20,
        examples=[_OD_EXAMPLE_MOTIVATION],
    )
    constraints: str = Field(
        default="",
        description=(
            "Optional. Budget, comp band, headcount cap, timing constraints "
            "the change must respect."
        ),
        examples=[_OD_EXAMPLE_CONSTRAINTS],
    )


class OrgDesignWorkflow(Workflow):
    name = "org_design"
    title = "Org Design Review"
    description = (
        "Drafts a review of a proposed organizational change — rationale, "
        "structure delta, span-of-control check, headcount budget impact, "
        "transition plan, and comms. Uses the CHRO and CFO specialists."
    )
    section = WorkflowSection.PEOPLE
    estimated_minutes = 3

    def input_model(self) -> type[BaseModel]:
        return OrgDesignInput

    def sample_inputs(self) -> dict[str, Any]:
        return {
            "current_structure": _OD_EXAMPLE_CURRENT,
            "proposed_structure": _OD_EXAMPLE_PROPOSED,
            "motivation": _OD_EXAMPLE_MOTIVATION,
            "constraints": _OD_EXAMPLE_CONSTRAINTS,
        }

    def steps(self) -> list[WorkflowStepDef]:
        return [
            WorkflowStepDef(
                id="context",
                title="Load context",
                description="Pull company profile and people-ops RAG.",
            ),
            WorkflowStepDef(
                id="critique",
                title="Critique the proposal",
                description="Span of control, role clarity, reporting lines.",
            ),
            WorkflowStepDef(
                id="financial",
                title="Headcount & comp impact",
                description="Budget implications and band drift to watch.",
            ),
            WorkflowStepDef(
                id="transition",
                title="Transition plan",
                description="How we move from current to proposed without losing momentum.",
            ),
            WorkflowStepDef(
                id="comms",
                title="Comms plan",
                description="Internal announcement sequencing.",
            ),
            WorkflowStepDef(
                id="assemble",
                title="Assemble review",
                description="Combine into one Markdown review.",
            ),
        ]

    async def run(
        self,
        inputs: BaseModel,
        store: ChromaDBStore,
    ) -> AsyncIterator[WorkflowEvent]:
        assert isinstance(inputs, OrgDesignInput)
        ctx = _ODCtx(inputs)

        yield WorkflowEvent(type="step_start", step_id="context", step_title="Load context")
        ctx.profile = load_or_create_profile()
        ctx.rag = retrieve(
            query="org design span of control reporting structure management",
            specialist_name="chro",
            n_builtin=5,
            n_company=3,
            store=store,
        )
        yield WorkflowEvent(
            type="step_done",
            step_id="context",
            summary=(
                f"Loaded profile for {ctx.profile.name or 'company'} and "
                f"{_chunk_count(ctx.rag)} RAG chunks."
            ),
        )

        yield WorkflowEvent(
            type="step_start", step_id="critique", step_title="Critique the proposal"
        )
        ctx.critique = await route_to_specialist(
            specialist_name="chro",
            query=_build_critique_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=ctx.rag,
        )
        yield WorkflowEvent(
            type="step_done", step_id="critique", summary=_first_line(ctx.critique)
        )

        yield WorkflowEvent(
            type="step_start", step_id="financial", step_title="Headcount & comp impact"
        )
        ctx.financial = await route_to_specialist(
            specialist_name="cfo",
            query=_build_financial_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge="",
        )
        yield WorkflowEvent(
            type="step_done", step_id="financial", summary=_first_line(ctx.financial)
        )

        yield WorkflowEvent(
            type="step_start", step_id="transition", step_title="Transition plan"
        )
        ctx.transition = await route_to_specialist(
            specialist_name="chro",
            query=_build_transition_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=ctx.rag,
        )
        yield WorkflowEvent(
            type="step_done", step_id="transition", summary=_first_line(ctx.transition)
        )

        yield WorkflowEvent(
            type="step_start", step_id="comms", step_title="Comms plan"
        )
        ctx.comms = await route_to_specialist(
            specialist_name="chro",
            query=_build_comms_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge="",
        )
        yield WorkflowEvent(
            type="step_done", step_id="comms", summary=_first_line(ctx.comms)
        )

        yield WorkflowEvent(
            type="step_start", step_id="assemble", step_title="Assemble review"
        )
        artifact = _assemble_doc(ctx)
        yield WorkflowEvent(
            type="step_done",
            step_id="assemble",
            summary=f"Assembled {len(artifact)} characters across 4 sections.",
        )
        yield WorkflowEvent(type="artifact", content=artifact)


class _ODCtx:
    def __init__(self, inputs: OrgDesignInput) -> None:
        self.inputs = inputs
        self.profile: CompanyProfile | None = None
        self.rag: str = ""
        self.critique: str = ""
        self.financial: str = ""
        self.transition: str = ""
        self.comms: str = ""


def _company_context_block(profile: CompanyProfile | None) -> str:
    if profile is None or profile.is_empty():
        return ""
    return profile.to_prompt_block()


def _chunk_count(rag_string: str) -> int:
    return rag_string.count("\n[") if rag_string else 0


def _first_line(text: str, max_len: int = 140) -> str:
    if not text:
        return "(empty)"
    line = text.strip().split("\n", 1)[0].lstrip("# ").strip()
    return line[: max_len - 1] + "…" if len(line) > max_len else line


def _build_critique_prompt(ctx: _ODCtx) -> str:
    return (
        "Critique the proposed org design. Focus on span of control, role "
        "clarity, single points of failure, and decision-rights friction.\n\n"
        f"Current:\n{ctx.inputs.current_structure}\n\n"
        f"Proposed:\n{ctx.inputs.proposed_structure}\n\n"
        f"Motivation:\n{ctx.inputs.motivation}\n\n"
        "Output (Markdown):\n"
        "## Critique\n\n"
        "### What the proposal solves\n"
        "1-2 paragraphs. Specifically tie each problem named in the "
        "motivation to a structural change in the proposal.\n\n"
        "### What the proposal misses\n"
        "1-2 paragraphs. Span-of-control concerns (any manager over 7 "
        "directs?), role-clarity ambiguity (two leaders for the same "
        "outcome?), decision-rights friction.\n\n"
        "### Alternatives to consider\n"
        "1-2 alternative structures with the trade-off in one sentence. "
        "E.g., 'a single Eng Director with stronger team leads is faster "
        "to ship but caps the VP's leverage.'\n\n"
        "Discipline: name the actual people / role count concerns. "
        "'Could improve clarity' is not feedback."
    )


def _build_financial_prompt(ctx: _ODCtx) -> str:
    constraints_block = (
        f"\n\nConstraints:\n{ctx.inputs.constraints}"
        if ctx.inputs.constraints.strip()
        else ""
    )
    return (
        "Model the **Headcount & Compensation Impact** of the proposed "
        "change.\n\n"
        f"Proposed:\n{ctx.inputs.proposed_structure}{constraints_block}\n\n"
        "Output (Markdown):\n"
        "## Headcount & Comp Impact\n\n"
        "### Net headcount delta\n"
        "Bullet list: new roles (external hires), internal promotions, "
        "any role eliminations. Annualized comp cost delta with "
        "placeholders for figures we don't have.\n\n"
        "### Band drift\n"
        "1 paragraph: where the proposed comp lands vs. existing bands. "
        "Flag any 'band-bust' hires that would force band reviews for "
        "incumbents.\n\n"
        "### Backfill load\n"
        "1 paragraph: promotions create vacancies. Quantify backfills "
        "and signal whether that load is absorbable.\n\n"
        "Do NOT invent comp figures. Use '[band X, $Y midpoint — confirm]' "
        "placeholders for values not provided."
    )


def _build_transition_prompt(ctx: _ODCtx) -> str:
    return (
        "Design the **Transition Plan** from current to proposed structure. "
        "The goal is to avoid losing 90 days of momentum during the change.\n\n"
        f"Current:\n{ctx.inputs.current_structure}\n\n"
        f"Proposed:\n{ctx.inputs.proposed_structure}\n\n"
        "Output (Markdown):\n"
        "## Transition Plan\n\n"
        "### Sequencing\n"
        "Bullet list, in order: which moves happen first, which can wait, "
        "which dependencies gate which (e.g., 'cannot reorg backend until "
        "Director hire signs').\n\n"
        "### Risks during transition\n"
        "3-4 bullets: people who might leave, projects that might slip, "
        "external commitments at risk. Mitigation for each.\n\n"
        "### What we measure\n"
        "Bullet list of 3-5 measurable signals (eng cycle time, "
        "incident response, manager 1:1 cadence) we'd watch in the first "
        "60 days to know whether the new structure is taking hold.\n\n"
        "Discipline: name the actual blast radius. 'Some churn risk' is "
        "not transition planning."
    )


def _build_comms_prompt(ctx: _ODCtx) -> str:
    return (
        "Draft the **Internal Comms Plan** for announcing the change.\n\n"
        f"Proposed structure:\n{ctx.inputs.proposed_structure}\n\n"
        "Output (Markdown):\n"
        "## Comms Plan\n\n"
        "### Pre-announcement\n"
        "Bullet list of 1:1s that must happen BEFORE the all-hands "
        "announcement — anyone whose role changes, anyone passed over for "
        "promotion, key adjacent leaders.\n\n"
        "### Announcement\n"
        "1 paragraph framing for the all-hands or memo. Lead with the why "
        "(tied to motivation), not the org chart.\n\n"
        "### Anticipated questions\n"
        "5-7 questions the team will actually ask, each with a starter "
        "answer. Mix easy ones with hard ones ('does this mean layoffs?', "
        "'why an external hire over an internal promotion?').\n\n"
        "Discipline: comms before action — anyone learning about their "
        "role change at an all-hands is a process failure."
    )


def _assemble_doc(ctx: _ODCtx) -> str:
    parts = [
        "# Org Design Review",
        "",
        "## Motivation",
        "",
        ctx.inputs.motivation.strip(),
        "",
        "## Current vs. Proposed",
        "",
        "**Current:**",
        "",
        ctx.inputs.current_structure.strip(),
        "",
        "**Proposed:**",
        "",
        ctx.inputs.proposed_structure.strip(),
        "",
        _ensure_heading(ctx.critique, "## Critique"),
        "",
        _ensure_heading(ctx.financial, "## Headcount & Comp Impact"),
        "",
        _ensure_heading(ctx.transition, "## Transition Plan"),
        "",
        _ensure_heading(ctx.comms, "## Comms Plan"),
        "",
        "---",
        "*Drafted by Open Executive. Review with CHRO and the affected "
        "leaders 1:1 before any all-hands announcement.*",
    ]
    return "\n".join(parts).strip() + "\n"


def _ensure_heading(text: str, expected_heading: str) -> str:
    stripped = text.strip()
    if not stripped:
        return f"{expected_heading}\n\n_(No content generated for this section.)_"
    first_line = stripped.split("\n", 1)[0]
    if first_line.startswith("##"):
        return stripped
    return f"{expected_heading}\n\n{stripped}"
