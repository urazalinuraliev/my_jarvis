"""Product strategy memo workflow — produces the 'why this, why now,
what we're not doing' memo behind a product roadmap.

Output: a strategic memo (not a roadmap doc). It justifies the 3-5 bets
the product team is making and explicitly calls out what's being said
no to. Uses the CPO and CSO specialists.
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

_PS_EXAMPLE_HORIZON = "H2 2026 (next 6 months)"
_PS_EXAMPLE_JOBS = (
    "Jobs we serve today:\n"
    "1. RevOps and analytics leaders building org-wide self-serve "
    "reporting without IT.\n"
    "2. Customer-facing teams pulling ad-hoc data without disrupting the "
    "data engineering team.\n\n"
    "Jobs we want to serve more in this horizon:\n"
    "3. Cross-team collaboration on reports (shared workspaces, governance, "
    "approvals)."
)
_PS_EXAMPLE_BETS = (
    "1. Workspaces — team-level container for reports, access, governance. "
    "Beta now, GA July 15. Unlocks the cross-team job.\n"
    "2. Mobile-first 'dashboard view' — execs check KPIs on phones; we "
    "don't have a credible mobile story today.\n"
    "3. AI-assisted natural-language query — the table-stakes feature "
    "of the next 18 months."
)
_PS_EXAMPLE_CAPACITY = (
    "12 engineers, 4 designers, 3 PMs. Engineering capacity is the binding "
    "constraint. Hiring 2 more backend engineers is in the plan but no "
    "earlier than late Q3."
)
_PS_EXAMPLE_NOT_DOING = (
    "Native Salesforce write-back integration — high demand but cross-functional "
    "complexity is huge. Custom dashboard themes / white-labeling — distracting. "
    "An on-prem deployment option — we'd lose more in pace than we'd gain "
    "in TAM right now."
)


class ProductStrategyInput(BaseModel):
    """Inputs for the Product Strategy Memo workflow."""

    horizon: str = Field(
        ...,
        description="Time horizon this memo covers (e.g., 'H2 2026', 'Next 12 months').",
        min_length=3,
        examples=[_PS_EXAMPLE_HORIZON],
    )
    jobs_to_be_done: str = Field(
        ...,
        description=(
            "The buyer / user jobs we currently serve, and any new jobs "
            "we want to serve in this horizon. Specific is better than "
            "abstract."
        ),
        min_length=30,
        examples=[_PS_EXAMPLE_JOBS],
    )
    current_bets: str = Field(
        ...,
        description=(
            "The 3-5 specific bets the product team is making this horizon "
            "(features, capability areas, platform shifts). Be concrete."
        ),
        min_length=30,
        examples=[_PS_EXAMPLE_BETS],
    )
    capacity_and_constraints: str = Field(
        default="",
        description=(
            "Optional. Engineering / design / PM capacity and the binding "
            "constraint that shapes what's feasible."
        ),
        examples=[_PS_EXAMPLE_CAPACITY],
    )
    explicit_non_bets: str = Field(
        default="",
        description=(
            "Optional. Things we're explicitly NOT working on this horizon, "
            "even though they have a constituency. Naming them is half "
            "the value of this memo."
        ),
        examples=[_PS_EXAMPLE_NOT_DOING],
    )


class ProductStrategyWorkflow(Workflow):
    name = "product_strategy"
    title = "Product Strategy Memo"
    description = (
        "Drafts the 'why this, why now, what we're not doing' memo behind "
        "a product roadmap: thesis, jobs we serve, the bets we're making, "
        "and explicit non-bets. Uses the CPO and CSO specialists."
    )
    section = WorkflowSection.PRODUCT
    estimated_minutes = 3

    def input_model(self) -> type[BaseModel]:
        return ProductStrategyInput

    def sample_inputs(self) -> dict[str, Any]:
        return {
            "horizon": _PS_EXAMPLE_HORIZON,
            "jobs_to_be_done": _PS_EXAMPLE_JOBS,
            "current_bets": _PS_EXAMPLE_BETS,
            "capacity_and_constraints": _PS_EXAMPLE_CAPACITY,
            "explicit_non_bets": _PS_EXAMPLE_NOT_DOING,
        }

    def steps(self) -> list[WorkflowStepDef]:
        return [
            WorkflowStepDef(
                id="context",
                title="Load context",
                description="Pull company profile and product-strategy RAG.",
            ),
            WorkflowStepDef(
                id="thesis",
                title="Sharpen the product thesis",
                description="The one paragraph that justifies everything else.",
            ),
            WorkflowStepDef(
                id="bets",
                title="Frame the bets",
                description="Each bet justified against jobs-to-be-done and the thesis.",
            ),
            WorkflowStepDef(
                id="non_bets",
                title="The non-bets",
                description="What we're saying no to, and why now.",
            ),
            WorkflowStepDef(
                id="success",
                title="Success criteria",
                description="What 'this worked' looks like at the end of the horizon.",
            ),
            WorkflowStepDef(
                id="assemble",
                title="Assemble memo",
                description="Combine into one Markdown memo.",
            ),
        ]

    async def run(
        self,
        inputs: BaseModel,
        store: ChromaDBStore,
    ) -> AsyncIterator[WorkflowEvent]:
        assert isinstance(inputs, ProductStrategyInput)
        ctx = _PSCtx(inputs)

        yield WorkflowEvent(type="step_start", step_id="context", step_title="Load context")
        ctx.profile = load_or_create_profile()
        ctx.rag = retrieve(
            query=f"product strategy roadmap thesis jobs to be done {ctx.inputs.horizon}",
            specialist_name="cpo",
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
            type="step_start", step_id="thesis", step_title="Sharpen the product thesis"
        )
        ctx.thesis = await route_to_specialist(
            specialist_name="cso",
            query=_build_thesis_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=ctx.rag,
        )
        yield WorkflowEvent(type="step_done", step_id="thesis", summary=_first_line(ctx.thesis))

        yield WorkflowEvent(type="step_start", step_id="bets", step_title="Frame the bets")
        ctx.bets = await route_to_specialist(
            specialist_name="cpo",
            query=_build_bets_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=ctx.rag,
        )
        yield WorkflowEvent(type="step_done", step_id="bets", summary=_first_line(ctx.bets))

        yield WorkflowEvent(type="step_start", step_id="non_bets", step_title="The non-bets")
        ctx.non_bets = await route_to_specialist(
            specialist_name="cpo",
            query=_build_non_bets_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge="",
        )
        yield WorkflowEvent(type="step_done", step_id="non_bets", summary=_first_line(ctx.non_bets))

        yield WorkflowEvent(
            type="step_start", step_id="success", step_title="Success criteria"
        )
        ctx.success = await route_to_specialist(
            specialist_name="cpo",
            query=_build_success_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge="",
        )
        yield WorkflowEvent(type="step_done", step_id="success", summary=_first_line(ctx.success))

        yield WorkflowEvent(type="step_start", step_id="assemble", step_title="Assemble memo")
        artifact = _assemble_memo(ctx)
        yield WorkflowEvent(
            type="step_done",
            step_id="assemble",
            summary=f"Assembled {len(artifact)} characters across 4 sections.",
        )
        yield WorkflowEvent(type="artifact", content=artifact)


class _PSCtx:
    def __init__(self, inputs: ProductStrategyInput) -> None:
        self.inputs = inputs
        self.profile: CompanyProfile | None = None
        self.rag: str = ""
        self.thesis: str = ""
        self.bets: str = ""
        self.non_bets: str = ""
        self.success: str = ""


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


def _build_thesis_prompt(ctx: _PSCtx) -> str:
    return (
        f"Draft the **Product Thesis** for the {ctx.inputs.horizon} horizon. "
        "One paragraph (max 4-5 sentences) that, if true, makes every bet "
        "in this memo make sense. Test: someone reading just the thesis "
        "should be able to guess the bets within an order of magnitude.\n\n"
        f"Jobs we serve / want to serve:\n{ctx.inputs.jobs_to_be_done}\n\n"
        f"Current bets:\n{ctx.inputs.current_bets}\n\n"
        "Output (Markdown):\n"
        "## Product Thesis\n\n"
        "One paragraph, 4-5 sentences. Frame the change in the market or "
        "user behavior we believe is happening, and the position we want "
        "to hold by end of horizon. Avoid 'we want to be the leading X' "
        "framing — that's a goal, not a thesis.\n\n"
        "Discipline: no buzzwords. If you can't name the underlying "
        "shift in 1-2 sentences, the thesis isn't yet sharp enough."
    )


def _build_bets_prompt(ctx: _PSCtx) -> str:
    capacity_block = (
        f"\n\nCapacity and constraints:\n{ctx.inputs.capacity_and_constraints}"
        if ctx.inputs.capacity_and_constraints.strip()
        else ""
    )
    return (
        f"Frame the **Bets** for the {ctx.inputs.horizon} horizon. For each "
        "bet, justify it against the thesis and jobs-to-be-done, name what "
        "we'd ship, and call out the most important risk.\n\n"
        f"Jobs:\n{ctx.inputs.jobs_to_be_done}\n\n"
        f"Founder's starting list of bets:\n{ctx.inputs.current_bets}"
        f"{capacity_block}\n\n"
        "Output (Markdown):\n"
        "## Bets\n\n"
        "For each bet (3-5 total):\n"
        "### Bet N: [Short name]\n"
        "**Why it matters:** 1-2 sentences linking to thesis + the "
        "specific job this serves.\n"
        "**What we ship:** the concrete deliverable / capability by end of "
        "horizon. Specific is better than abstract.\n"
        "**Biggest risk:** the one thing most likely to kill the bet.\n"
        "**Owner:** [PM / function placeholder]\n\n"
        "Discipline: 3-5 bets max. If the founder gave you 7, force-rank "
        "and recommend cutting the bottom 2 to the non-bets section. "
        "Bets must be specific enough that we'd know if we shipped them."
    )


def _build_non_bets_prompt(ctx: _PSCtx) -> str:
    return (
        f"Draft the **Non-Bets** section. These are the asks we're saying "
        f"no to in the {ctx.inputs.horizon} horizon, with the reason. "
        "Naming non-bets is half the value of a strategy memo — it forces "
        "discipline and answers the 'why aren't we doing X?' question "
        "before it gets asked.\n\n"
        f"Founder's starting list (may be empty):\n{ctx.inputs.explicit_non_bets or 'None provided.'}\n\n"
        f"Jobs we serve:\n{ctx.inputs.jobs_to_be_done}\n\n"
        "Output (Markdown):\n"
        "## Non-Bets\n\n"
        "Bullet list of 3-6 explicit non-bets. For each:\n"
        "- **[Short name]:** what the ask is (in the requester's words), "
        "and the 1-line reason we're saying no THIS horizon (not 'forever'). "
        "Examples of valid reasons: 'wrong sequence — gates on workspaces "
        "shipping first', 'distracts from the thesis', 'capacity-bound', "
        "'we'd lose more in pace than gain in TAM'.\n\n"
        "Discipline: include at least 2 ideas with real internal advocacy. "
        "A non-bets list that only contains things nobody was asking for "
        "is intellectually dishonest. If the founder's input doesn't "
        "include any, infer the obvious 'this team always asks for X' "
        "candidates."
    )


def _build_success_prompt(ctx: _PSCtx) -> str:
    return (
        f"Draft the **Success Criteria** for the {ctx.inputs.horizon} "
        "horizon. What does 'this strategy worked' look like at the end?\n\n"
        f"Bets:\n{ctx.inputs.current_bets}\n\n"
        "Output (Markdown):\n"
        "## Success Criteria\n\n"
        "### End-of-horizon state\n"
        "3-5 bullets — observable outcomes (not internal milestones) that, "
        "if true, mean the strategy delivered. Each bullet should have an "
        "associated metric or measurable state, or be marked '[qualitative]'.\n\n"
        "### Failure modes\n"
        "2-3 bullets on what 'this strategy didn't work' looks like. "
        "Naming the failure mode in advance reduces post-hoc rationalization.\n\n"
        "### Checkpoint cadence\n"
        "1 paragraph: when and how we'd review progress against this memo "
        "(quarterly, mid-horizon, etc.)."
    )


def _assemble_memo(ctx: _PSCtx) -> str:
    parts = [
        f"# Product Strategy — {ctx.inputs.horizon}",
        "",
        _ensure_heading(ctx.thesis, "## Product Thesis"),
        "",
        "## Jobs To Be Done",
        "",
        ctx.inputs.jobs_to_be_done.strip(),
        "",
        _ensure_heading(ctx.bets, "## Bets"),
        "",
        _ensure_heading(ctx.non_bets, "## Non-Bets"),
        "",
        _ensure_heading(ctx.success, "## Success Criteria"),
        "",
        "---",
        "*Drafted by Open Executive. The product team should treat this as "
        "a starting point, debate the bets vs. non-bets explicitly, and "
        "publish the final version with founder + CPO sign-off.*",
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
