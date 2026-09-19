"""Compensation refresh workflow — produces a comp / equity refresh
proposal: band review, refresh-grant logic, dilution model, and rollout
plan.

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

_CR_EXAMPLE_DRIVER = (
    "Two finalists declined the AE role over our base comp band ($110-130K). "
    "Recent hire on the data team reported their initial grant feels small "
    "now that we've doubled valuation. Eng band feels out of date — we've "
    "raised the bar but the bands haven't moved in 14 months."
)
_CR_EXAMPLE_CURRENT = (
    "Eng IC bands (base + target equity):\n"
    "- L3 IC: $130-150K + 0.05% / 4yr\n"
    "- L4 IC: $160-185K + 0.08%\n"
    "- L5 IC: $190-220K + 0.15%\n"
    "AE bands: Base $110-130K, OTE $200-240K, 0.05%.\n"
    "Last band review: 14 months ago. ARR has 2.5x'd since."
)
_CR_EXAMPLE_MARKET = (
    "Compa-ratio survey (recent): eng bands 87% of market median (was "
    "98% at last review). AE base 92% of market. Equity grants ~50% of "
    "median for Series-A funded, ~85% for our stage. Several recent "
    "competitor postings show $20-30K higher base for senior eng."
)
_CR_EXAMPLE_BUDGET = (
    "Cash budget: $200K incremental annualized for band raises. "
    "Equity refresh pool: 1.0% remaining in the option pool; another "
    "1.5% authorization at the next board meeting if needed."
)


class CompRefreshInput(BaseModel):
    """Inputs for the Compensation Refresh workflow."""

    driver: str = Field(
        ...,
        description=(
            "What's prompting this refresh? Specific incidents, churn, "
            "hiring losses, or 'periodic review'."
        ),
        min_length=20,
        examples=[_CR_EXAMPLE_DRIVER],
    )
    current_bands: str = Field(
        ...,
        description=(
            "Current comp bands — by role / level / function. Include "
            "base, equity, and OTE where applicable."
        ),
        min_length=30,
        examples=[_CR_EXAMPLE_CURRENT],
    )
    market_signal: str = Field(
        ...,
        description=(
            "What we know about the market: compa-ratio data, recent "
            "competitor postings, lost candidates' counter-offers, "
            "internal Glassdoor / equity-app comps."
        ),
        min_length=20,
        examples=[_CR_EXAMPLE_MARKET],
    )
    budget_envelope: str = Field(
        default="",
        description=(
            "Optional. Cash budget for raises and equity refresh pool. "
            "Without this, the proposal will use placeholders."
        ),
        examples=[_CR_EXAMPLE_BUDGET],
    )


class CompRefreshWorkflow(Workflow):
    name = "comp_refresh"
    title = "Compensation Refresh"
    description = (
        "Drafts a comp / equity refresh proposal — band review, raise "
        "logic, refresh-grant approach, dilution model, and rollout. "
        "Uses the CHRO and CFO specialists."
    )
    section = WorkflowSection.PEOPLE
    estimated_minutes = 3

    def input_model(self) -> type[BaseModel]:
        return CompRefreshInput

    def sample_inputs(self) -> dict[str, Any]:
        return {
            "driver": _CR_EXAMPLE_DRIVER,
            "current_bands": _CR_EXAMPLE_CURRENT,
            "market_signal": _CR_EXAMPLE_MARKET,
            "budget_envelope": _CR_EXAMPLE_BUDGET,
        }

    def steps(self) -> list[WorkflowStepDef]:
        return [
            WorkflowStepDef(
                id="context",
                title="Load context",
                description="Pull company profile and comp / equity RAG.",
            ),
            WorkflowStepDef(
                id="band_review",
                title="Band review",
                description="Which bands move, by how much, and why.",
            ),
            WorkflowStepDef(
                id="refresh_grants",
                title="Refresh-grant logic",
                description="Who gets a refresh, the formula, the equity impact.",
            ),
            WorkflowStepDef(
                id="dilution",
                title="Dilution & budget model",
                description="What this costs in cash and equity, with the math.",
            ),
            WorkflowStepDef(
                id="rollout",
                title="Rollout plan",
                description="Sequencing, manager comms, employee comms.",
            ),
            WorkflowStepDef(
                id="assemble",
                title="Assemble proposal",
                description="Combine into one Markdown proposal.",
            ),
        ]

    async def run(
        self,
        inputs: BaseModel,
        store: ChromaDBStore,
    ) -> AsyncIterator[WorkflowEvent]:
        assert isinstance(inputs, CompRefreshInput)
        ctx = _CompCtx(inputs)

        yield WorkflowEvent(type="step_start", step_id="context", step_title="Load context")
        ctx.profile = load_or_create_profile()
        ctx.rag = retrieve(
            query="compensation bands equity refresh employee retention",
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
            type="step_start", step_id="band_review", step_title="Band review"
        )
        ctx.band_review = await route_to_specialist(
            specialist_name="chro",
            query=_build_band_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=ctx.rag,
        )
        yield WorkflowEvent(
            type="step_done", step_id="band_review", summary=_first_line(ctx.band_review)
        )

        yield WorkflowEvent(
            type="step_start", step_id="refresh_grants", step_title="Refresh-grant logic"
        )
        ctx.refresh_grants = await route_to_specialist(
            specialist_name="chro",
            query=_build_refresh_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=ctx.rag,
        )
        yield WorkflowEvent(
            type="step_done", step_id="refresh_grants", summary=_first_line(ctx.refresh_grants)
        )

        yield WorkflowEvent(
            type="step_start", step_id="dilution", step_title="Dilution & budget model"
        )
        ctx.dilution = await route_to_specialist(
            specialist_name="cfo",
            query=_build_dilution_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=retrieve(
                query="employee equity pool dilution refresh grants",
                specialist_name="cfo",
                n_builtin=4,
                n_company=2,
                store=store,
            ),
        )
        yield WorkflowEvent(
            type="step_done", step_id="dilution", summary=_first_line(ctx.dilution)
        )

        yield WorkflowEvent(
            type="step_start", step_id="rollout", step_title="Rollout plan"
        )
        ctx.rollout = await route_to_specialist(
            specialist_name="chro",
            query=_build_rollout_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge="",
        )
        yield WorkflowEvent(
            type="step_done", step_id="rollout", summary=_first_line(ctx.rollout)
        )

        yield WorkflowEvent(
            type="step_start", step_id="assemble", step_title="Assemble proposal"
        )
        artifact = _assemble_proposal(ctx)
        yield WorkflowEvent(
            type="step_done",
            step_id="assemble",
            summary=f"Assembled {len(artifact)} characters across 4 sections.",
        )
        yield WorkflowEvent(type="artifact", content=artifact)


class _CompCtx:
    def __init__(self, inputs: CompRefreshInput) -> None:
        self.inputs = inputs
        self.profile: CompanyProfile | None = None
        self.rag: str = ""
        self.band_review: str = ""
        self.refresh_grants: str = ""
        self.dilution: str = ""
        self.rollout: str = ""


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


def _build_band_prompt(ctx: _CompCtx) -> str:
    return (
        "Draft the **Band Review** section. Which bands move, by how much, "
        "and the principle behind each move.\n\n"
        f"Driver:\n{ctx.inputs.driver}\n\n"
        f"Current bands:\n{ctx.inputs.current_bands}\n\n"
        f"Market signal:\n{ctx.inputs.market_signal}\n\n"
        "Output (Markdown):\n"
        "## Band Review\n\n"
        "### Bands that move\n"
        "Bullet list. For each:\n"
        "- **[Role / level]:** old → new (cash + equity), and the "
        "1-sentence rationale tied to market signal or driver.\n\n"
        "### Bands that hold\n"
        "Bullet list (with 1-sentence reason each). Saying 'this is "
        "still right' is part of the proposal.\n\n"
        "### Internal-equity check\n"
        "1 paragraph: when we move a band, who in the existing population "
        "gets bumped to fit, and how we avoid creating new compression.\n\n"
        "Discipline: every band change must have either market evidence "
        "or a specific business case attached. 'Feels low' is not a reason."
    )


def _build_refresh_prompt(ctx: _CompCtx) -> str:
    return (
        "Draft the **Refresh-Grant Logic**. Who gets a refresh, how the "
        "grant is sized, when it happens.\n\n"
        f"Driver:\n{ctx.inputs.driver}\n\n"
        f"Current bands:\n{ctx.inputs.current_bands}\n\n"
        "Output (Markdown):\n"
        "## Refresh-Grant Logic\n\n"
        "### Eligibility\n"
        "1 paragraph: who's eligible this cycle. Typically a tenure + "
        "performance gate (e.g., '2+ years tenure or hired before the "
        "last valuation step, plus meets-or-exceeds rating').\n\n"
        "### Sizing formula\n"
        "1 paragraph: the formula in plain English. Something like "
        "'top up to 50% of original new-hire grant for the relevant band'. "
        "Be concrete; vague refresh policies create resentment.\n\n"
        "### Vesting\n"
        "1 paragraph: vesting shape (typically a fresh 4-year clock vs. "
        "extending the original cliff). Reasoning.\n\n"
        "### Edge cases\n"
        "Bullet list of 3-5 hard edge cases (newish hires, recent "
        "promotions, departing-soon flagged employees, those on PIPs). "
        "How each is handled.\n\n"
        "Discipline: write the policy precisely enough that two HRBPs "
        "would apply it the same way to the same employee."
    )


def _build_dilution_prompt(ctx: _CompCtx) -> str:
    budget_block = (
        f"\n\nBudget envelope:\n{ctx.inputs.budget_envelope}"
        if ctx.inputs.budget_envelope.strip()
        else ""
    )
    return (
        "Model the **Dilution & Budget Impact** of the proposed refresh "
        "and band moves.\n\n"
        f"Driver:\n{ctx.inputs.driver}\n\n"
        f"Current bands:\n{ctx.inputs.current_bands}{budget_block}\n\n"
        "Output (Markdown):\n"
        "## Dilution & Budget Model\n\n"
        "### Cash impact\n"
        "1 paragraph: annualized incremental cash from band raises. "
        "Show the math by function (eng + GTM + ops). Placeholders for "
        "headcount-by-band figures we don't have.\n\n"
        "### Equity impact\n"
        "1 paragraph: total option-pool consumption from refresh grants, "
        "as % of fully diluted. Compare to remaining pool and the next "
        "expected option-pool authorization.\n\n"
        "### Scenarios\n"
        "Bullet list of 2-3 scenarios (conservative / target / aggressive) "
        "with the cash + equity totals for each.\n\n"
        "### Numbers we need to confirm\n"
        "Bullet list: headcount per band, performance distribution, "
        "current pool size, % allocated vs. unallocated. The CFO and "
        "head of people-ops jointly own these.\n\n"
        "Do NOT invent specific dollar or percentage figures. Show the "
        "math with explicit placeholders where inputs are missing."
    )


def _build_rollout_prompt(ctx: _CompCtx) -> str:
    return (
        "Draft the **Rollout Plan** for the refresh.\n\n"
        "Output (Markdown):\n"
        "## Rollout Plan\n\n"
        "### Sequencing\n"
        "Bullet list of weeks T-minus, who does what when. Approvals "
        "(legal, board if material), manager calibration sessions, "
        "manager-employee conversations, written letters.\n\n"
        "### Manager talking points\n"
        "5-7 bullets covering what every manager must say, and what they "
        "must NOT say. Common pitfalls: comparing one report's number to "
        "another's, promising future refreshes, blaming budget.\n\n"
        "### Anticipated employee questions\n"
        "5-7 questions employees will ask, each with a starter answer.\n\n"
        "### Things that go wrong\n"
        "3-4 likely failure modes (leak, manager mis-delivery, finance "
        "math error caught after letters go out) and the mitigation.\n\n"
        "Discipline: any employee who gets a refresh should hear it from "
        "their manager, not via the letter alone."
    )


def _assemble_proposal(ctx: _CompCtx) -> str:
    parts = [
        "# Compensation Refresh Proposal",
        "",
        "## Driver",
        "",
        ctx.inputs.driver.strip(),
        "",
        "## Market Signal",
        "",
        ctx.inputs.market_signal.strip(),
        "",
        _ensure_heading(ctx.band_review, "## Band Review"),
        "",
        _ensure_heading(ctx.refresh_grants, "## Refresh-Grant Logic"),
        "",
        _ensure_heading(ctx.dilution, "## Dilution & Budget Model"),
        "",
        _ensure_heading(ctx.rollout, "## Rollout Plan"),
        "",
        "---",
        "*Drafted by Open Executive. Validate every band figure against "
        "the current market survey and the cap table before approving.*",
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
