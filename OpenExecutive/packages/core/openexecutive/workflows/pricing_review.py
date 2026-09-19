"""Pricing & packaging review workflow — produces a structured analysis
of a proposed pricing / packaging change: customer willingness-to-pay,
tier design, P&L impact, migration plan for existing customers.

Uses the CMO, CFO, and CSO specialists. Output is a decision memo for
the founder + CFO + sales leader to align on before rolling out.
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

_PR_EXAMPLE_CHANGE = (
    "Introduce a new 'Team' tier at $40/seat between our current $20 Pro "
    "and $80 Enterprise tiers. The Team tier includes workspaces, SSO "
    "with Google/Okta only, and 10 saved views. Aim: capture the 5-50 "
    "seat sweet spot where Pro feels light but Enterprise is overkill."
)
_PR_EXAMPLE_CURRENT = (
    "Pro $20/seat — most accounts (~80%). Enterprise $80/seat — ~15% of "
    "accounts. The remaining ~5% are legacy custom contracts. Median "
    "Pro account is 8 seats; median Enterprise account is 95 seats."
)
_PR_EXAMPLE_MOTIVATION = (
    "Mid-market accounts (10-50 seats) churn 2x our average on Pro because "
    "they outgrow the seat model. Many ask us about Enterprise but only "
    "need ~3 of its 12 features. We're leaving $400K+/yr on the table."
)
_PR_EXAMPLE_DATA = (
    "Win-rate data: 14 of last 20 mid-market deals dropped at pricing "
    "(8 said 'too expensive at Enterprise tier', 6 said 'we'd pay more "
    "than Pro but not Enterprise'). Quarterly churn cohort 10-50 seats: "
    "3.1% vs. company average 1.5%."
)
_PR_EXAMPLE_CONSTRAINTS = (
    "Cannot raise prices on existing Pro customers within first 12 months. "
    "Need migration paths that don't force re-signing contracts."
)


class PricingReviewInput(BaseModel):
    """Inputs for the Pricing & Packaging Review workflow."""

    proposed_change: str = Field(
        ...,
        description=(
            "What change is being proposed? Be concrete — list new/changed "
            "tiers, prices, and what's included in each."
        ),
        min_length=30,
        examples=[_PR_EXAMPLE_CHANGE],
    )
    current_packaging: str = Field(
        ...,
        description=(
            "Describe the current packaging — tiers, prices, who's on each, "
            "and rough revenue mix."
        ),
        min_length=30,
        examples=[_PR_EXAMPLE_CURRENT],
    )
    motivation: str = Field(
        ...,
        description=(
            "Why now? What customer signal or business problem is this "
            "change solving? Be specific."
        ),
        min_length=20,
        examples=[_PR_EXAMPLE_MOTIVATION],
    )
    supporting_data: str = Field(
        default="",
        description=(
            "Optional. Win/loss data, churn cohorts, willingness-to-pay "
            "surveys, competitive prices. Anything that pressure-tests "
            "the new tier."
        ),
        examples=[_PR_EXAMPLE_DATA],
    )
    constraints: str = Field(
        default="",
        description=(
            "Optional. Things the proposal must respect — existing contracts, "
            "legal restrictions, channel relationships, board commitments."
        ),
        examples=[_PR_EXAMPLE_CONSTRAINTS],
    )


class PricingReviewWorkflow(Workflow):
    name = "pricing_review"
    title = "Pricing & Packaging Review"
    description = (
        "Drafts a decision memo for a proposed pricing or packaging change "
        "— rationale, tier design critique, P&L impact, migration plan, "
        "and risks. Uses the CMO, CFO, and CSO specialists."
    )
    section = WorkflowSection.GROWTH
    estimated_minutes = 4

    def input_model(self) -> type[BaseModel]:
        return PricingReviewInput

    def sample_inputs(self) -> dict[str, Any]:
        return {
            "proposed_change": _PR_EXAMPLE_CHANGE,
            "current_packaging": _PR_EXAMPLE_CURRENT,
            "motivation": _PR_EXAMPLE_MOTIVATION,
            "supporting_data": _PR_EXAMPLE_DATA,
            "constraints": _PR_EXAMPLE_CONSTRAINTS,
        }

    def steps(self) -> list[WorkflowStepDef]:
        return [
            WorkflowStepDef(
                id="context",
                title="Load context",
                description="Pull company profile and pricing-strategy RAG.",
            ),
            WorkflowStepDef(
                id="tier_critique",
                title="Critique the tier design",
                description="Where the proposed tier sits well, where it doesn't.",
            ),
            WorkflowStepDef(
                id="pl_impact",
                title="Model the P&L impact",
                description="Revenue, mix shift, ASP, and gross-margin implications.",
            ),
            WorkflowStepDef(
                id="migration_plan",
                title="Design the migration plan",
                description="How existing customers move (or don't) onto the new packaging.",
            ),
            WorkflowStepDef(
                id="risks",
                title="Risks & decision criteria",
                description="What could break, plus the metrics to watch post-launch.",
            ),
            WorkflowStepDef(
                id="assemble",
                title="Assemble decision memo",
                description="Combine sections into a single Markdown memo.",
            ),
        ]

    async def run(
        self,
        inputs: BaseModel,
        store: ChromaDBStore,
    ) -> AsyncIterator[WorkflowEvent]:
        assert isinstance(inputs, PricingReviewInput)
        ctx = _PricingCtx(inputs)

        yield WorkflowEvent(type="step_start", step_id="context", step_title="Load context")
        ctx.profile = load_or_create_profile()
        ctx.rag = retrieve(
            query="SaaS pricing packaging tier design willingness to pay",
            specialist_name="cmo",
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
            type="step_start", step_id="tier_critique", step_title="Critique the tier design"
        )
        ctx.tier_critique = await route_to_specialist(
            specialist_name="cmo",
            query=_build_tier_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=ctx.rag,
        )
        yield WorkflowEvent(
            type="step_done", step_id="tier_critique", summary=_first_line(ctx.tier_critique)
        )

        yield WorkflowEvent(
            type="step_start", step_id="pl_impact", step_title="Model the P&L impact"
        )
        ctx.pl_impact = await route_to_specialist(
            specialist_name="cfo",
            query=_build_pl_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=retrieve(
                query="SaaS pricing change revenue impact ASP mix shift",
                specialist_name="cfo",
                n_builtin=4,
                n_company=2,
                store=store,
            ),
        )
        yield WorkflowEvent(
            type="step_done", step_id="pl_impact", summary=_first_line(ctx.pl_impact)
        )

        yield WorkflowEvent(
            type="step_start", step_id="migration_plan", step_title="Design the migration plan"
        )
        ctx.migration_plan = await route_to_specialist(
            specialist_name="cmo",
            query=_build_migration_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=ctx.rag,
        )
        yield WorkflowEvent(
            type="step_done", step_id="migration_plan", summary=_first_line(ctx.migration_plan)
        )

        yield WorkflowEvent(
            type="step_start", step_id="risks", step_title="Risks & decision criteria"
        )
        ctx.risks = await route_to_specialist(
            specialist_name="cso",
            query=_build_risks_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=ctx.rag,
        )
        yield WorkflowEvent(type="step_done", step_id="risks", summary=_first_line(ctx.risks))

        yield WorkflowEvent(
            type="step_start", step_id="assemble", step_title="Assemble decision memo"
        )
        artifact = _assemble_memo(ctx)
        yield WorkflowEvent(
            type="step_done",
            step_id="assemble",
            summary=f"Assembled {len(artifact)} characters across 4 sections.",
        )
        yield WorkflowEvent(type="artifact", content=artifact)


class _PricingCtx:
    def __init__(self, inputs: PricingReviewInput) -> None:
        self.inputs = inputs
        self.profile: CompanyProfile | None = None
        self.rag: str = ""
        self.tier_critique: str = ""
        self.pl_impact: str = ""
        self.migration_plan: str = ""
        self.risks: str = ""


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


def _build_tier_prompt(ctx: _PricingCtx) -> str:
    data_block = (
        f"\n\nSupporting data:\n{ctx.inputs.supporting_data}"
        if ctx.inputs.supporting_data.strip()
        else ""
    )
    return (
        "Critique the **Tier Design** of the proposed pricing change. Where "
        "does the new packaging make sense, where does it conflict with how "
        "buyers actually buy, and what's missing?\n\n"
        f"Proposal:\n{ctx.inputs.proposed_change}\n\n"
        f"Current packaging:\n{ctx.inputs.current_packaging}\n\n"
        f"Motivation:\n{ctx.inputs.motivation}"
        f"{data_block}\n\n"
        "Output (Markdown):\n"
        "## Tier Design Critique\n\n"
        "### What's right\n"
        "1-2 paragraphs on what the proposal gets right — which buyer is "
        "well-served, what differentiation is sharpened.\n\n"
        "### What's missing\n"
        "1-2 paragraphs on gaps: features that should/shouldn't be in the "
        "new tier, edge cases the design doesn't address, price-anchor "
        "concerns. Be specific.\n\n"
        "### Alternative framings\n"
        "1-2 alternative tier designs we should at least consider before "
        "locking this in. For each, the trade-off in one sentence.\n\n"
        "Discipline: no buzzwords. If we genuinely don't know something "
        "(e.g., 'how many Pro accounts would move to Team?'), say 'we'd "
        "need to model this' rather than guess."
    )


def _build_pl_prompt(ctx: _PricingCtx) -> str:
    data_block = (
        f"\n\nSupporting data:\n{ctx.inputs.supporting_data}"
        if ctx.inputs.supporting_data.strip()
        else ""
    )
    return (
        "Model the **P&L Impact** of the proposed pricing change. Focus on "
        "the revenue, ASP, and mix-shift dynamics — not on tier design.\n\n"
        f"Proposal:\n{ctx.inputs.proposed_change}\n\n"
        f"Current packaging:\n{ctx.inputs.current_packaging}{data_block}\n\n"
        "Output (Markdown):\n"
        "## P&L Impact\n\n"
        "### Revenue scenarios\n"
        "Bullet list of 2-3 scenarios (pessimistic / base / optimistic), "
        "each with the rough quarter-over-quarter ARR delta and the "
        "assumption that drives it. Use placeholders for figures we "
        "haven't been given.\n\n"
        "### ASP & Mix\n"
        "1-2 paragraphs on how ASP changes if X% of Pro accounts move up "
        "and Y% of inbound mid-market lands on the new tier rather than "
        "Enterprise. Frame the cannibalization risk explicitly.\n\n"
        "### Gross margin & operating impact\n"
        "1 paragraph: implications for COGS, support load, sales ramp, "
        "and discounting practice.\n\n"
        "### Numbers we'd need to confirm\n"
        "Bullet list of the 3-5 questions the founder needs FP&A to answer "
        "before signing off (mix shift estimate, customer-success cost "
        "per seat at each tier, discount-pool budget, etc.).\n\n"
        "Do NOT invent specific dollar figures. Use placeholders."
    )


def _build_migration_prompt(ctx: _PricingCtx) -> str:
    constraints_block = (
        f"\n\nConstraints to respect:\n{ctx.inputs.constraints}"
        if ctx.inputs.constraints.strip()
        else ""
    )
    return (
        "Design the **Migration Plan** for existing customers. The plan "
        "must respect existing contracts and avoid creating churn from "
        "the price change itself.\n\n"
        f"Proposal:\n{ctx.inputs.proposed_change}\n\n"
        f"Current packaging:\n{ctx.inputs.current_packaging}"
        f"{constraints_block}\n\n"
        "Output (Markdown):\n"
        "## Migration Plan\n\n"
        "### Existing Pro customers\n"
        "What happens to today's Pro accounts — do they stay, or are they "
        "actively migrated? Specify the criteria and the comms plan.\n\n"
        "### Existing Enterprise customers\n"
        "Same treatment. Address the risk that Enterprise customers ask "
        "to downgrade to the new tier.\n\n"
        "### New customers\n"
        "How the new tier shows up in sales conversations and self-serve "
        "checkout. Sales-deck and pricing-page asks.\n\n"
        "### Comms timeline\n"
        "T-minus weeks: founder email / CS outreach / pricing-page update / "
        "sales-deck cutover. Owner placeholders.\n\n"
        "Discipline: assume customers will read the announcement adversarially. "
        "Pre-empt the 'this is a price increase in disguise' read."
    )


def _build_risks_prompt(ctx: _PricingCtx) -> str:
    return (
        "List the **Risks** of this pricing change and the **Decision "
        "Criteria** we'd use to evaluate it post-launch.\n\n"
        f"Proposal:\n{ctx.inputs.proposed_change}\n\n"
        f"Motivation:\n{ctx.inputs.motivation}\n\n"
        "Output (Markdown):\n"
        "## Risks & Decision Criteria\n\n"
        "### Risks\n"
        "3-5 specific risks, each as:\n"
        "- **[Short name]:** what could happen, how likely, how we'd notice "
        "it, what we'd do.\n\n"
        "Mix internal (sales motion confusion, support load) and external "
        "(competitor response, customer backlash) risks.\n\n"
        "### Decision criteria\n"
        "Bullet list of the 3-5 metrics we'd watch in the first 90 days to "
        "decide whether to keep, tweak, or roll back the change. For each: "
        "the metric, the threshold, and the response.\n\n"
        "Discipline: focus on falsifiable signals (e.g., 'new-tier "
        "attachment rate >25% within 60 days'), not vibes."
    )


def _assemble_memo(ctx: _PricingCtx) -> str:
    parts = [
        f"# Pricing & Packaging Review — {ctx.inputs.proposed_change.splitlines()[0][:80]}",
        "",
        "## Proposal Summary",
        "",
        ctx.inputs.proposed_change.strip(),
        "",
        "## Motivation",
        "",
        ctx.inputs.motivation.strip(),
        "",
        _ensure_heading(ctx.tier_critique, "## Tier Design Critique"),
        "",
        _ensure_heading(ctx.pl_impact, "## P&L Impact"),
        "",
        _ensure_heading(ctx.migration_plan, "## Migration Plan"),
        "",
        _ensure_heading(ctx.risks, "## Risks & Decision Criteria"),
        "",
        "---",
        "*Drafted by Open Executive. Review with the CFO, head of sales, "
        "and customer success before locking the launch date.*",
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
