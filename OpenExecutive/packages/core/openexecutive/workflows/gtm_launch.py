"""GTM launch plan workflow — produces a complete go-to-market launch
plan as Markdown: positioning, messaging, channel plan, enablement,
timeline, and success metrics.

Uses the CMO, CPO, and COO specialists. Output is a draft for the
launch lead to review with the cross-functional team.
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

_GTM_EXAMPLE_LAUNCH = (
    "Workspaces — a new top-level container that lets teams group reports, "
    "share saved views, and manage access at the team level. Beta with "
    "30 accounts wrapping next month; GA target July 15."
)
_GTM_EXAMPLE_AUDIENCE = (
    "Primary: mid-market RevOps and Data leaders at 100-500 person SaaS "
    "companies who already use us individually but lack a clean way to "
    "share work. Secondary: existing admin buyers who want governance."
)
_GTM_EXAMPLE_VALUE_PROP = (
    "'Stop duplicating work — your team's analytics in one place, with the "
    "access controls IT will sign off on.' Replaces the spreadsheet-of-"
    "report-links pattern most teams use today."
)
_GTM_EXAMPLE_COMPETITION = (
    "Looker and Mode have workspace-like features but require central data "
    "team setup. Our angle: any user can create one in <60 seconds, no "
    "admin involvement. Hex announced something similar last month — "
    "expect them to claim parity in their press response."
)
_GTM_EXAMPLE_GOALS = (
    "- 40% of paid accounts create a workspace within 60 days of GA\n"
    "- $300K net new ARR attributable in first quarter post-launch\n"
    "- Lift mid-market trial-to-paid by 5pp\n"
    "- 3 customer case studies published within 90 days"
)
_GTM_EXAMPLE_CONSTRAINTS = (
    "Engineering can hold a 2-week post-GA hardening capacity but no more. "
    "Marketing budget for this launch capped at $40K. CS team is at "
    "capacity and can't run more than 2 high-touch onboardings/week."
)


class GTMLaunchInput(BaseModel):
    """Inputs for the GTM Launch Plan workflow."""

    launch_name: str = Field(
        ...,
        description="What is launching? Name + a 1-2 line description.",
        min_length=10,
        examples=[_GTM_EXAMPLE_LAUNCH],
    )
    target_audience: str = Field(
        ...,
        description=(
            "Who is this for? Be specific: persona, segment, the job they're "
            "trying to do. 'Everyone' is not an audience."
        ),
        min_length=20,
        examples=[_GTM_EXAMPLE_AUDIENCE],
    )
    value_proposition: str = Field(
        ...,
        description=(
            "The single line a customer would say to explain why they care, "
            "plus what behavior or workaround it replaces."
        ),
        min_length=15,
        examples=[_GTM_EXAMPLE_VALUE_PROP],
    )
    competitive_context: str = Field(
        default="",
        description=(
            "Optional. Who else solves this today, why we're different, and "
            "any imminent competitor moves."
        ),
        examples=[_GTM_EXAMPLE_COMPETITION],
    )
    success_metrics: str = Field(
        ...,
        description=(
            "The 3-5 measurable outcomes that define a successful launch. "
            "Include the time horizon. 'Drive awareness' is not a metric."
        ),
        min_length=20,
        examples=[_GTM_EXAMPLE_GOALS],
    )
    constraints: str = Field(
        default="",
        description=(
            "Optional. Capacity, budget, or dependency constraints the plan "
            "must respect."
        ),
        examples=[_GTM_EXAMPLE_CONSTRAINTS],
    )


class GTMLaunchWorkflow(Workflow):
    name = "gtm_launch"
    title = "GTM Launch Plan"
    description = (
        "Drafts a full go-to-market launch plan — positioning, messaging "
        "pillars, channel plan, internal enablement, timeline, and success "
        "metrics. Uses the CMO, CPO, and COO specialists."
    )
    section = WorkflowSection.GROWTH
    estimated_minutes = 4

    def input_model(self) -> type[BaseModel]:
        return GTMLaunchInput

    def sample_inputs(self) -> dict[str, Any]:
        return {
            "launch_name": _GTM_EXAMPLE_LAUNCH,
            "target_audience": _GTM_EXAMPLE_AUDIENCE,
            "value_proposition": _GTM_EXAMPLE_VALUE_PROP,
            "competitive_context": _GTM_EXAMPLE_COMPETITION,
            "success_metrics": _GTM_EXAMPLE_GOALS,
            "constraints": _GTM_EXAMPLE_CONSTRAINTS,
        }

    def steps(self) -> list[WorkflowStepDef]:
        return [
            WorkflowStepDef(
                id="context",
                title="Load context",
                description="Pull company profile and GTM/marketing RAG.",
            ),
            WorkflowStepDef(
                id="positioning",
                title="Sharpen positioning",
                description="Category frame, audience, and the 'replaces what' answer.",
            ),
            WorkflowStepDef(
                id="messaging",
                title="Draft messaging pillars",
                description="The 3 things every asset must say.",
            ),
            WorkflowStepDef(
                id="channels",
                title="Channel & launch-day plan",
                description="Where we show up, what we own, what we don't bother with.",
            ),
            WorkflowStepDef(
                id="enablement",
                title="Internal enablement",
                description="What sales, CS, and support need to be ready.",
            ),
            WorkflowStepDef(
                id="timeline",
                title="T-minus timeline & owners",
                description="Week-by-week from now to GA, with owners.",
            ),
            WorkflowStepDef(
                id="assemble",
                title="Assemble launch plan",
                description="Combine sections into a structured Markdown plan.",
            ),
        ]

    async def run(
        self,
        inputs: BaseModel,
        store: ChromaDBStore,
    ) -> AsyncIterator[WorkflowEvent]:
        assert isinstance(inputs, GTMLaunchInput)
        ctx = _GTMContext(inputs)

        yield WorkflowEvent(type="step_start", step_id="context", step_title="Load context")
        ctx.profile = load_or_create_profile()
        ctx.rag = retrieve(
            query=f"product launch go-to-market positioning {ctx.inputs.launch_name}",
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
            type="step_start", step_id="positioning", step_title="Sharpen positioning"
        )
        ctx.positioning = await route_to_specialist(
            specialist_name="cmo",
            query=_build_positioning_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=ctx.rag,
        )
        yield WorkflowEvent(
            type="step_done", step_id="positioning", summary=_first_line(ctx.positioning)
        )

        yield WorkflowEvent(
            type="step_start", step_id="messaging", step_title="Draft messaging pillars"
        )
        ctx.messaging = await route_to_specialist(
            specialist_name="cmo",
            query=_build_messaging_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=ctx.rag,
        )
        yield WorkflowEvent(
            type="step_done", step_id="messaging", summary=_first_line(ctx.messaging)
        )

        yield WorkflowEvent(
            type="step_start", step_id="channels", step_title="Channel & launch-day plan"
        )
        ctx.channels = await route_to_specialist(
            specialist_name="cmo",
            query=_build_channels_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=retrieve(
                query=f"launch channel strategy {ctx.inputs.target_audience}",
                specialist_name="cmo",
                n_builtin=4,
                n_company=3,
                store=store,
            ),
        )
        yield WorkflowEvent(
            type="step_done", step_id="channels", summary=_first_line(ctx.channels)
        )

        yield WorkflowEvent(
            type="step_start", step_id="enablement", step_title="Internal enablement"
        )
        ctx.enablement = await route_to_specialist(
            specialist_name="cpo",
            query=_build_enablement_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=retrieve(
                query=f"product launch enablement sales CS {ctx.inputs.launch_name}",
                specialist_name="cpo",
                n_builtin=4,
                n_company=2,
                store=store,
            ),
        )
        yield WorkflowEvent(
            type="step_done", step_id="enablement", summary=_first_line(ctx.enablement)
        )

        yield WorkflowEvent(
            type="step_start", step_id="timeline", step_title="T-minus timeline & owners"
        )
        ctx.timeline = await route_to_specialist(
            specialist_name="coo",
            query=_build_timeline_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge="",
        )
        yield WorkflowEvent(
            type="step_done", step_id="timeline", summary=_first_line(ctx.timeline)
        )

        yield WorkflowEvent(
            type="step_start", step_id="assemble", step_title="Assemble launch plan"
        )
        artifact = _assemble_plan(ctx)
        yield WorkflowEvent(
            type="step_done",
            step_id="assemble",
            summary=f"Assembled {len(artifact)} characters across 5 sections.",
        )
        yield WorkflowEvent(type="artifact", content=artifact)


# -----------------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------------


class _GTMContext:
    def __init__(self, inputs: GTMLaunchInput) -> None:
        self.inputs = inputs
        self.profile: CompanyProfile | None = None
        self.rag: str = ""
        self.positioning: str = ""
        self.messaging: str = ""
        self.channels: str = ""
        self.enablement: str = ""
        self.timeline: str = ""


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


def _build_positioning_prompt(ctx: _GTMContext) -> str:
    competition_block = (
        f"\n\nCompetitive context:\n{ctx.inputs.competitive_context}"
        if ctx.inputs.competitive_context.strip()
        else ""
    )
    return (
        f"Sharpen the **Positioning** for the launch of {ctx.inputs.launch_name}.\n\n"
        f"Audience:\n{ctx.inputs.target_audience}\n\n"
        f"Starting value prop:\n{ctx.inputs.value_proposition}"
        f"{competition_block}\n\n"
        "Output (Markdown):\n"
        "## Positioning\n\n"
        "### Category Frame\n"
        "1 paragraph: how we want buyers to mentally categorize this. "
        "Reference what we're 'a better X than' or 'the first Y to' — "
        "concrete category language.\n\n"
        "### Audience\n"
        "1 paragraph: the buyer in their own words. Use the job they're "
        "trying to do, not demographics.\n\n"
        "### Replaces / Displaces\n"
        "1 paragraph: the specific workaround or competing product this "
        "kills. Buyers don't add new tools; they swap.\n\n"
        "### The Sentence\n"
        "One sentence the buyer can repeat to their boss. Under 25 words. "
        "Avoid 'AI-powered', 'next-generation', or any other empty modifier."
    )


def _build_messaging_prompt(ctx: _GTMContext) -> str:
    return (
        "Draft **3 messaging pillars** for the launch. Every external asset "
        "(landing page, sales deck, email sequence, social, press) must "
        "reinforce these three. More than 3 = nothing sticks.\n\n"
        f"Audience: {ctx.inputs.target_audience}\n"
        f"Value prop: {ctx.inputs.value_proposition}\n"
        f"Success metrics: {ctx.inputs.success_metrics}\n\n"
        "Output (Markdown):\n"
        "## Messaging Pillars\n\n"
        "### Pillar 1: [Short name in customer language]\n"
        "**Claim:** 1 sentence the customer would believe.\n"
        "**Proof:** 1-2 concrete proof points we can stand behind (data, "
        "customer quote slot, capability demonstration).\n"
        "**Disqualifier:** what we explicitly do NOT claim.\n\n"
        "Repeat for Pillars 2 and 3. Pillars must be distinct from each "
        "other — if two of them are similar, you have only one.\n\n"
        "Discipline: no marketing buzzwords. The disqualifier line is "
        "non-negotiable; it keeps us honest and pre-empts pushback."
    )


def _build_channels_prompt(ctx: _GTMContext) -> str:
    constraints_block = (
        f"\n\nConstraints to respect:\n{ctx.inputs.constraints}"
        if ctx.inputs.constraints.strip()
        else ""
    )
    return (
        "Draft the **Channel & Launch-Day Plan**. The channels we activate, "
        "the assets each one needs, and what we explicitly skip.\n\n"
        f"Audience: {ctx.inputs.target_audience}\n"
        f"Goals: {ctx.inputs.success_metrics}{constraints_block}\n\n"
        "Output (Markdown):\n"
        "## Channels & Launch Day\n\n"
        "### Owned\n"
        "Bullet list: blog post / landing page / email to existing customers / "
        "in-product announcement / docs. For each: owner placeholder + "
        "one-line scope.\n\n"
        "### Earned\n"
        "Press, analyst briefings, podcast appearances. If we don't believe "
        "press will move the metrics, say so and skip.\n\n"
        "### Paid\n"
        "Paid social, paid search, sponsored newsletters. Only what we "
        "expect to pay back. Budget split with rough $ allocation.\n\n"
        "### Community / Partner\n"
        "Customer ambassadors, integration partners, communities to seed. "
        "Specific names, not 'engage the community'.\n\n"
        "### Explicit Skips\n"
        "What we are NOT doing for this launch, and why. (Cap-G or PR-stunt "
        "approaches that founders feel pressure to try.)\n\n"
        "Launch-day timeline: hour-by-hour of the day itself."
    )


def _build_enablement_prompt(ctx: _GTMContext) -> str:
    return (
        "Draft the **Internal Enablement** plan. What sales, CS, support, "
        "and the broader team need to be ready when launch hits.\n\n"
        f"Launch: {ctx.inputs.launch_name}\n"
        f"Audience: {ctx.inputs.target_audience}\n"
        f"Value prop: {ctx.inputs.value_proposition}\n\n"
        "Output (Markdown):\n"
        "## Internal Enablement\n\n"
        "### Sales\n"
        "Bullet list: training session (date+owner), updated deck slides, "
        "discovery questions, objection handling for top 3 objections, "
        "demo flow updates, CRM tagging changes.\n\n"
        "### Customer Success\n"
        "Outreach plan for existing customers, talking-points doc for QBRs, "
        "support article links to know, retention motion implications.\n\n"
        "### Support\n"
        "Top 5 questions support will get (with starter answers), "
        "escalation path for the first 2 weeks, known issues to watch.\n\n"
        "### Internal All-Hands Briefing\n"
        "1 paragraph framing the launch for the whole team — what changes, "
        "what we're betting, what we want everyone repeating externally."
    )


def _build_timeline_prompt(ctx: _GTMContext) -> str:
    return (
        "Draft the **Timeline & Owners** section. T-minus weeks from launch, "
        "with what must be done and who owns it.\n\n"
        f"Launch: {ctx.inputs.launch_name}\n"
        f"Constraints: {ctx.inputs.constraints or 'none specified'}\n\n"
        "Output (Markdown):\n"
        "## Timeline & Owners\n\n"
        "### T-4 weeks\n"
        "Bullet list: deliverable — [owner placeholder]\n\n"
        "### T-3 weeks\n... (same)\n\n"
        "### T-2 weeks\n... (same)\n\n"
        "### T-1 week\n... (same)\n\n"
        "### Launch day\n... (same)\n\n"
        "### T+2 weeks (review)\n"
        "What we measure and decide at the 2-week post-launch review.\n\n"
        "Be realistic about parallelism — sales training and content review "
        "compete for the same humans. Flag dependencies between rows. "
        "Where a date isn't provided in the inputs, use relative weeks."
    )


def _assemble_plan(ctx: _GTMContext) -> str:
    parts = [
        f"# GTM Launch Plan — {ctx.inputs.launch_name.splitlines()[0]}",
        "",
        "## Launch Goals",
        "",
        ctx.inputs.success_metrics.strip(),
        "",
        _ensure_heading(ctx.positioning, "## Positioning"),
        "",
        _ensure_heading(ctx.messaging, "## Messaging Pillars"),
        "",
        _ensure_heading(ctx.channels, "## Channels & Launch Day"),
        "",
        _ensure_heading(ctx.enablement, "## Internal Enablement"),
        "",
        _ensure_heading(ctx.timeline, "## Timeline & Owners"),
        "",
        "---",
        "*Drafted by Open Executive. Review with marketing, product, and "
        "the launch-day on-call before locking the schedule.*",
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
