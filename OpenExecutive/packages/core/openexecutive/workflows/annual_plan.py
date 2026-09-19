"""Annual operating plan workflow — produces a full-year operating plan:
strategic anchor + financial frame + per-function plan + risk register +
quarterly checkpoint cadence.

The yearly-horizon big sibling to `quarterly_plan`. Uses the CSO and CFO
specialists.
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

_AP_EXAMPLE_YEAR = "FY 2026"
_AP_EXAMPLE_PRIOR = (
    "FY 2025 closed at $4.1M ARR (+135% YoY, plan was $4.5M; slipped 9%). "
    "Mid-market motion launched in Q3; first 5 wins landed in Q4. "
    "Workspaces beta wrapped Q4 with NPS 62 from the 30-account cohort. "
    "Burn $640K/mo average; cash $9.2M, 14mo runway."
)
_AP_EXAMPLE_THESIS = (
    "The market is shifting from analytics-as-a-tool-for-analysts to "
    "analytics-as-the-operating-layer for go-to-market and ops teams. "
    "In FY 2026 we'll consolidate the mid-market segment and stand up a "
    "platform tier that lets enterprise IT trust the deployment. By "
    "year-end we want to be the default choice for any 50-500 person "
    "company adopting a new analytics layer."
)
_AP_EXAMPLE_REVENUE = (
    "Plan ARR end of year: $9-10M (~2.3x prior year). Net dollar "
    "retention target: 115%+. Hiring plan: 22 to 50 people, ~60% in "
    "engineering and product. Burn assumption: $850K/mo average ramping "
    "to $1.1M/mo by Q4. Series B raise targeted for Q3-Q4."
)
_AP_EXAMPLE_PRIORITIES = (
    "1. Workspaces GA + adoption — the linchpin of the mid-market motion.\n"
    "2. Platform tier launch with SSO/SAML, audit logs, customer-managed "
    "encryption — needed for enterprise IT trust.\n"
    "3. AI-assisted natural-language query — table stakes by year-end.\n"
    "4. Series B raised at fair valuation, with the right partner.\n"
    "5. Cut SMB churn from 1.8% to 1.0% by Q3.\n"
    "6. Hire VPE successor + Head of Product."
)


class AnnualPlanInput(BaseModel):
    """Inputs for the Annual Operating Plan workflow."""

    year_label: str = Field(
        ...,
        description="The year being planned (e.g., 'FY 2026', 'Calendar 2026').",
        min_length=3,
        examples=[_AP_EXAMPLE_YEAR],
    )
    prior_year_recap: str = Field(
        ...,
        description=(
            "What happened last year — wins, misses, key metrics actuals "
            "vs. plan. This grounds the new plan in observed reality."
        ),
        min_length=30,
        examples=[_AP_EXAMPLE_PRIOR],
    )
    strategic_thesis: str = Field(
        ...,
        description=(
            "The 2-3 paragraph thesis underpinning the year. What's "
            "changing in the market, where we want to be by year-end, "
            "and the position we're playing for."
        ),
        min_length=30,
        examples=[_AP_EXAMPLE_THESIS],
    )
    revenue_and_capital: str = Field(
        ...,
        description=(
            "Revenue target, hiring envelope, burn assumption, capital "
            "plan (raise vs. self-fund). The financial frame the rest "
            "of the plan lives inside."
        ),
        min_length=30,
        examples=[_AP_EXAMPLE_REVENUE],
    )
    top_priorities: str = Field(
        ...,
        description=(
            "The 5-7 things that must happen this year. Specific is "
            "better than abstract — 'launch platform tier with SAML by "
            "Q3' beats 'invest in enterprise readiness'."
        ),
        min_length=30,
        examples=[_AP_EXAMPLE_PRIORITIES],
    )


class AnnualPlanWorkflow(Workflow):
    name = "annual_plan"
    title = "Annual Operating Plan"
    description = (
        "Drafts a full-year operating plan — strategic anchor, financial "
        "frame, per-function plans, risk register, and the quarterly "
        "checkpoint cadence. The big sibling to quarterly_plan. Uses "
        "the CSO and CFO specialists."
    )
    section = WorkflowSection.OPERATING
    estimated_minutes = 5

    def input_model(self) -> type[BaseModel]:
        return AnnualPlanInput

    def sample_inputs(self) -> dict[str, Any]:
        return {
            "year_label": _AP_EXAMPLE_YEAR,
            "prior_year_recap": _AP_EXAMPLE_PRIOR,
            "strategic_thesis": _AP_EXAMPLE_THESIS,
            "revenue_and_capital": _AP_EXAMPLE_REVENUE,
            "top_priorities": _AP_EXAMPLE_PRIORITIES,
        }

    def steps(self) -> list[WorkflowStepDef]:
        return [
            WorkflowStepDef(
                id="context",
                title="Load context",
                description="Pull company profile and annual-planning RAG.",
            ),
            WorkflowStepDef(
                id="strategic_anchor",
                title="Strategic anchor",
                description="The thesis tightened, plus 'where we want to be by year-end'.",
            ),
            WorkflowStepDef(
                id="financial_frame",
                title="Financial frame",
                description="Revenue, hiring, burn, runway, raise plan.",
            ),
            WorkflowStepDef(
                id="function_plans",
                title="Per-function plans",
                description="What each function owns this year.",
            ),
            WorkflowStepDef(
                id="risks",
                title="Top risks",
                description="The 5 things most likely to break the plan.",
            ),
            WorkflowStepDef(
                id="cadence",
                title="Checkpoint cadence",
                description="How we review, adjust, and (if needed) replan.",
            ),
            WorkflowStepDef(
                id="assemble",
                title="Assemble plan",
                description="Combine into one Markdown plan.",
            ),
        ]

    async def run(
        self,
        inputs: BaseModel,
        store: ChromaDBStore,
    ) -> AsyncIterator[WorkflowEvent]:
        assert isinstance(inputs, AnnualPlanInput)
        ctx = _APCtx(inputs)

        yield WorkflowEvent(type="step_start", step_id="context", step_title="Load context")
        ctx.profile = load_or_create_profile()
        ctx.rag = retrieve(
            query=f"annual operating plan strategic priorities {ctx.inputs.year_label}",
            specialist_name="cso",
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
            type="step_start", step_id="strategic_anchor", step_title="Strategic anchor"
        )
        ctx.strategic_anchor = await route_to_specialist(
            specialist_name="cso",
            query=_build_anchor_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=ctx.rag,
        )
        yield WorkflowEvent(
            type="step_done",
            step_id="strategic_anchor",
            summary=_first_line(ctx.strategic_anchor),
        )

        yield WorkflowEvent(
            type="step_start", step_id="financial_frame", step_title="Financial frame"
        )
        ctx.financial_frame = await route_to_specialist(
            specialist_name="cfo",
            query=_build_financial_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=retrieve(
                query=f"annual financial plan forecast hiring burn runway {ctx.inputs.year_label}",
                specialist_name="cfo",
                n_builtin=4,
                n_company=2,
                store=store,
            ),
        )
        yield WorkflowEvent(
            type="step_done",
            step_id="financial_frame",
            summary=_first_line(ctx.financial_frame),
        )

        yield WorkflowEvent(
            type="step_start", step_id="function_plans", step_title="Per-function plans"
        )
        ctx.function_plans = await route_to_specialist(
            specialist_name="cso",
            query=_build_functions_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=ctx.rag,
        )
        yield WorkflowEvent(
            type="step_done",
            step_id="function_plans",
            summary=_first_line(ctx.function_plans),
        )

        yield WorkflowEvent(type="step_start", step_id="risks", step_title="Top risks")
        ctx.risks = await route_to_specialist(
            specialist_name="cso",
            query=_build_risks_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=ctx.rag,
        )
        yield WorkflowEvent(type="step_done", step_id="risks", summary=_first_line(ctx.risks))

        yield WorkflowEvent(
            type="step_start", step_id="cadence", step_title="Checkpoint cadence"
        )
        ctx.cadence = await route_to_specialist(
            specialist_name="cso",
            query=_build_cadence_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge="",
        )
        yield WorkflowEvent(
            type="step_done", step_id="cadence", summary=_first_line(ctx.cadence)
        )

        yield WorkflowEvent(
            type="step_start", step_id="assemble", step_title="Assemble plan"
        )
        artifact = _assemble_plan(ctx)
        yield WorkflowEvent(
            type="step_done",
            step_id="assemble",
            summary=f"Assembled {len(artifact)} characters across 5 sections.",
        )
        yield WorkflowEvent(type="artifact", content=artifact)


class _APCtx:
    def __init__(self, inputs: AnnualPlanInput) -> None:
        self.inputs = inputs
        self.profile: CompanyProfile | None = None
        self.rag: str = ""
        self.strategic_anchor: str = ""
        self.financial_frame: str = ""
        self.function_plans: str = ""
        self.risks: str = ""
        self.cadence: str = ""


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


def _build_anchor_prompt(ctx: _APCtx) -> str:
    return (
        f"Sharpen the **Strategic Anchor** for the {ctx.inputs.year_label} "
        "operating plan. This is the one section that, if read alone, "
        "should let a board observer guess the budget and roadmap "
        "within an order of magnitude.\n\n"
        f"Prior year recap:\n{ctx.inputs.prior_year_recap}\n\n"
        f"Founder's starting thesis:\n{ctx.inputs.strategic_thesis}\n\n"
        f"Top priorities:\n{ctx.inputs.top_priorities}\n\n"
        "Output (Markdown):\n"
        "## Strategic Anchor\n\n"
        "### Thesis\n"
        "2 paragraphs: the market shift we're betting on and the position "
        "we want to hold by year-end. Test: someone reading just this "
        "section should be able to predict which 3 things would make us "
        "happiest 12 months from now.\n\n"
        "### Year-end state\n"
        "Bullet list of 4-6 observable conditions that, if true at year-"
        "end, mean the plan worked. Each bullet must be concrete and "
        "measurable, or marked '[qualitative]'.\n\n"
        "### Where we don't compete\n"
        "1 paragraph: the segments / use cases / customer types we're "
        "explicitly NOT chasing this year. Naming what we're not doing "
        "is half the value of a strategic anchor.\n\n"
        "Discipline: no buzzwords. Anchor must be specific to this "
        "company, not a generic 'become the leader in X' frame."
    )


def _build_financial_prompt(ctx: _APCtx) -> str:
    return (
        "Frame the **Financial** picture for the year — revenue, hiring, "
        "burn, runway, capital plan.\n\n"
        f"Prior year recap:\n{ctx.inputs.prior_year_recap}\n\n"
        f"Founder's frame:\n{ctx.inputs.revenue_and_capital}\n\n"
        "Output (Markdown):\n"
        "## Financial Frame\n\n"
        "### Revenue plan\n"
        "1-2 paragraphs: end-of-year ARR target, growth rate, net dollar "
        "retention target. Quarterly shape (how much of the year's growth "
        "lands in Q1 vs. Q4).\n\n"
        "### Hiring plan\n"
        "Bullet list by function: target headcount end-of-year and the "
        "function-by-function ramp. Flag any hires gated on Series B.\n\n"
        "### Burn and runway\n"
        "1 paragraph: burn assumption month-by-month or quarterly, "
        "ending-cash-without-raise, runway-without-raise. Identify the "
        "month we're forced to either raise or cut.\n\n"
        "### Capital plan\n"
        "1 paragraph: whether and when we raise, target round size + "
        "valuation, lead profile we want, alternative if the raise "
        "slips a quarter or two.\n\n"
        "### Numbers to confirm with FP&A\n"
        "Bullet list of 4-6 figures FP&A must validate before this plan "
        "is final. Use placeholders for numbers not provided."
    )


def _build_functions_prompt(ctx: _APCtx) -> str:
    return (
        "Draft the **Per-Function Plan** for the year. Each function "
        "answers: 'what am I owning this year, and what am I explicitly "
        "not doing?'\n\n"
        f"Year-end state target:\n{ctx.inputs.strategic_thesis}\n\n"
        f"Top priorities:\n{ctx.inputs.top_priorities}\n\n"
        "Output (Markdown):\n"
        "## Per-Function Plan\n\n"
        "Cover the functions appropriate to this stage of the business — "
        "typically Engineering, Product, GTM (Sales + Marketing + CS), "
        "Operations, People, Finance. For each:\n\n"
        "### [Function]\n"
        "**Year-end outcomes:** 2-4 specific deliverables. Each tied "
        "to a top priority.\n"
        "**Explicit non-priorities:** 1-2 things this function is NOT "
        "doing this year (frees up capacity).\n"
        "**Top hires:** the 1-3 hires this function needs to make this "
        "year.\n"
        "**Biggest risk to the plan:** the one thing most likely to "
        "block the function from delivering.\n\n"
        "Discipline: deliverables must trace back to the strategic anchor. "
        "Outcomes are not 'execute well' — they're specific, observable, "
        "and tied to dates."
    )


def _build_risks_prompt(ctx: _APCtx) -> str:
    return (
        "Identify the **Top 5 Risks** to the annual plan. Each risk must "
        "be both material AND something we'd actually act on.\n\n"
        f"Prior year recap:\n{ctx.inputs.prior_year_recap}\n\n"
        f"Top priorities:\n{ctx.inputs.top_priorities}\n\n"
        f"Capital plan:\n{ctx.inputs.revenue_and_capital}\n\n"
        "Output (Markdown):\n"
        "## Top Risks\n\n"
        "5 risks, each:\n"
        "### Risk N: [Short name]\n"
        "**What could happen:** 1-2 sentences.\n"
        "**Likelihood × impact:** rough qualitative score.\n"
        "**Leading indicator:** the signal we'd watch.\n"
        "**Mitigation now:** what we're doing.\n"
        "**Mitigation if it materializes:** the playbook.\n"
        "**Owner:** [role placeholder].\n\n"
        "Discipline: include at least 1 internal (execution / hiring) risk "
        "AND at least 1 external (competitor / market / regulatory) risk. "
        "A risk register that's all internal or all external is "
        "intellectually incomplete."
    )


def _build_cadence_prompt(ctx: _APCtx) -> str:
    return (
        "Draft the **Checkpoint Cadence** for the year — how we review "
        "progress, adjust, and (if needed) replan.\n\n"
        f"Year-end target:\n{ctx.inputs.strategic_thesis}\n\n"
        "Output (Markdown):\n"
        "## Checkpoint Cadence\n\n"
        "### Quarterly review\n"
        "1 paragraph: when the quarterly review happens, what's measured "
        "(progress against year-end outcomes + against quarterly OKRs), "
        "and the decision frame ('confirm / adjust / replan').\n\n"
        "### Mid-year replan trigger\n"
        "1 paragraph: the conditions that would trigger a mid-year "
        "replan vs. an in-quarter adjustment. Examples: revenue >20% "
        "off-plan for 2 consecutive quarters, raise materially delayed, "
        "key-person departure.\n\n"
        "### Board updates\n"
        "1 paragraph: cadence and content of board updates throughout "
        "the year, tied to the four quarterly reviews.\n\n"
        "### What we do NOT change mid-year\n"
        "1 paragraph: the strategic anchor and year-end state should "
        "not move except under the replan trigger. Naming this prevents "
        "the team from drifting under quarterly pressure."
    )


def _assemble_plan(ctx: _APCtx) -> str:
    parts = [
        f"# Annual Operating Plan — {ctx.inputs.year_label}",
        "",
        "## Prior Year Recap",
        "",
        ctx.inputs.prior_year_recap.strip(),
        "",
        _ensure_heading(ctx.strategic_anchor, "## Strategic Anchor"),
        "",
        _ensure_heading(ctx.financial_frame, "## Financial Frame"),
        "",
        _ensure_heading(ctx.function_plans, "## Per-Function Plan"),
        "",
        _ensure_heading(ctx.risks, "## Top Risks"),
        "",
        _ensure_heading(ctx.cadence, "## Checkpoint Cadence"),
        "",
        "---",
        "*Drafted by Open Executive. Stress-test with the leadership team "
        "before locking. Every placeholder should be filled in with the "
        "function-head owner before the board sees it.*",
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
