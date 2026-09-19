"""Monthly investor update workflow — produces a short investor email
covering highlights, lowlights, metrics, asks, and outlook as Markdown.

Lighter-weight than board_prep / fundraising_prep — meant for routine
monthly investor / angel updates. Uses the CFO and Board Comms specialists.
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

_IU_EXAMPLE_HIGHLIGHTS = (
    "- Closed our largest deal to date ($240K ACV, mid-market)\n"
    "- Workspaces beta launched to 30 accounts; NPS 62 from the cohort\n"
    "- Hired Priya as VP Engineering (starts next month)\n"
    "- SOC 2 Type II audit cleared; unblocking 3 enterprise deals"
)
_IU_EXAMPLE_LOWLIGHTS = (
    "- Pipeline coverage for next month soft at 2.1x vs 3x target\n"
    "- SMB churn ticked up to 1.8% (was 1.2%) — concentrated <50-seat accounts\n"
    "- 90 min platform incident on the 18th; full RCA done, mitigations shipping"
)
_IU_EXAMPLE_METRICS = (
    "- MRR $342K (+6% MoM)\n"
    "- New ARR $180K (plan $220K)\n"
    "- Burn $610K (plan $680K — favorable, hire slipped)\n"
    "- Cash $9.2M, ~15mo runway\n"
    "- Headcount 38"
)
_IU_EXAMPLE_ASKS = (
    "- Warm intros to the head of data at any 200-500 person SaaS company\n"
    "- Candidate intros for our AE backfill (mid-market, base $130K)"
)
_IU_EXAMPLE_OUTLOOK = (
    "Targeting $1.5M revenue next month and the workspaces GA on July 15. "
    "Watching pipeline coverage and SMB churn closely."
)


class InvestorUpdateInput(BaseModel):
    """Inputs for the Monthly Investor Update workflow."""

    month_label: str = Field(
        ...,
        description="Month being reported (e.g., 'May 2026').",
        min_length=3,
        examples=["May 2026"],
    )
    highlights: str = Field(
        ...,
        description=(
            "The 3-5 best things this month — customers, milestones, hires, "
            "wins. Bullets are fine."
        ),
        min_length=20,
        examples=[_IU_EXAMPLE_HIGHLIGHTS],
    )
    lowlights: str = Field(
        ...,
        description=(
            "The 2-3 things that didn't go well or are at risk. Investors "
            "respect a CEO who names them — don't sugarcoat."
        ),
        min_length=15,
        examples=[_IU_EXAMPLE_LOWLIGHTS],
    )
    metrics: str = Field(
        ...,
        description=(
            "Key numbers: revenue / MRR / ARR, growth rate, burn, cash, "
            "runway, headcount. Bullets are fine. Don't invent numbers."
        ),
        min_length=20,
        examples=[_IU_EXAMPLE_METRICS],
    )
    asks: str = Field(
        default="",
        description=(
            "Optional. Specific asks of the investor list — intros, hiring "
            "leads, feedback. Investors love a clear ask."
        ),
        examples=[_IU_EXAMPLE_ASKS],
    )
    outlook: str = Field(
        default="",
        description=(
            "Optional. 1-2 sentences on what's most on your mind looking "
            "forward — the bet, the risk, the thing you're watching."
        ),
        examples=[_IU_EXAMPLE_OUTLOOK],
    )


class InvestorUpdateWorkflow(Workflow):
    name = "investor_update"
    title = "Monthly Investor Update"
    description = (
        "Drafts a short monthly investor email — highlights, lowlights, "
        "metrics, asks, and outlook. Uses the CFO and Board Comms "
        "specialists. Output is Markdown ready to paste into an email client."
    )
    section = WorkflowSection.CAPITAL
    estimated_minutes = 2

    def input_model(self) -> type[BaseModel]:
        return InvestorUpdateInput

    def sample_inputs(self) -> dict[str, Any]:
        return {
            "month_label": "May 2026",
            "highlights": _IU_EXAMPLE_HIGHLIGHTS,
            "lowlights": _IU_EXAMPLE_LOWLIGHTS,
            "metrics": _IU_EXAMPLE_METRICS,
            "asks": _IU_EXAMPLE_ASKS,
            "outlook": _IU_EXAMPLE_OUTLOOK,
        }

    def steps(self) -> list[WorkflowStepDef]:
        return [
            WorkflowStepDef(
                id="context",
                title="Load context",
                description="Pull company profile and investor-update RAG.",
            ),
            WorkflowStepDef(
                id="metrics_block",
                title="Frame the metrics",
                description="CFO-voiced framing of the numbers: what's moving and why.",
            ),
            WorkflowStepDef(
                id="narrative",
                title="Draft the narrative",
                description="The opening + closing prose — CEO voice.",
            ),
            WorkflowStepDef(
                id="assemble",
                title="Assemble the email",
                description="Combine sections into one Markdown email.",
            ),
        ]

    async def run(
        self,
        inputs: BaseModel,
        store: ChromaDBStore,
    ) -> AsyncIterator[WorkflowEvent]:
        assert isinstance(inputs, InvestorUpdateInput)
        ctx = _IUContext(inputs)

        yield WorkflowEvent(type="step_start", step_id="context", step_title="Load context")
        ctx.profile = load_or_create_profile()
        ctx.rag = retrieve(
            query=f"monthly investor update communications {ctx.inputs.month_label}",
            specialist_name="board_comms",
            n_builtin=4,
            n_company=2,
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
            type="step_start", step_id="metrics_block", step_title="Frame the metrics"
        )
        ctx.metrics_block = await route_to_specialist(
            specialist_name="cfo",
            query=_build_metrics_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge="",
        )
        yield WorkflowEvent(
            type="step_done", step_id="metrics_block", summary=_first_line(ctx.metrics_block)
        )

        yield WorkflowEvent(
            type="step_start", step_id="narrative", step_title="Draft the narrative"
        )
        ctx.narrative = await route_to_specialist(
            specialist_name="board_comms",
            query=_build_narrative_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=ctx.rag,
        )
        yield WorkflowEvent(
            type="step_done", step_id="narrative", summary=_first_line(ctx.narrative)
        )

        yield WorkflowEvent(
            type="step_start", step_id="assemble", step_title="Assemble the email"
        )
        artifact = _assemble_email(ctx)
        yield WorkflowEvent(
            type="step_done",
            step_id="assemble",
            summary=f"Assembled {len(artifact)} characters.",
        )
        yield WorkflowEvent(type="artifact", content=artifact)


class _IUContext:
    def __init__(self, inputs: InvestorUpdateInput) -> None:
        self.inputs = inputs
        self.profile: CompanyProfile | None = None
        self.rag: str = ""
        self.metrics_block: str = ""
        self.narrative: str = ""


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


def _build_metrics_prompt(ctx: _IUContext) -> str:
    return (
        f"Draft the **Metrics** section of the {ctx.inputs.month_label} "
        "investor update. Short, scannable, with one-line interpretation "
        "of any variance vs. plan.\n\n"
        f"Numbers from the founder:\n{ctx.inputs.metrics}\n\n"
        "Output (Markdown):\n"
        "## Metrics\n\n"
        "Bullet list, each item formatted as:\n"
        "- **[Metric name]:** [value] ([trend, e.g., +6% MoM]) — [one-line "
        "interpretation if it's noteworthy].\n\n"
        "Discipline: do not invent numbers. Use placeholders like "
        "'[CAC payback — need from finance]' where a figure is implied "
        "but not provided. Keep it under 8 bullets."
    )


def _build_narrative_prompt(ctx: _IUContext) -> str:
    asks_block = (
        f"\n\nAsks:\n{ctx.inputs.asks}" if ctx.inputs.asks.strip() else ""
    )
    outlook_block = (
        f"\n\nOutlook:\n{ctx.inputs.outlook}"
        if ctx.inputs.outlook.strip()
        else ""
    )
    return (
        f"Draft the **narrative** of the {ctx.inputs.month_label} investor "
        "update — the parts of the email that aren't the metrics table. "
        "Write in the CEO's voice: direct, specific, no buzzwords.\n\n"
        f"Highlights:\n{ctx.inputs.highlights}\n\n"
        f"Lowlights:\n{ctx.inputs.lowlights}"
        f"{asks_block}{outlook_block}\n\n"
        "Output (Markdown), exactly this structure:\n"
        "## Highlights\n"
        "Bullet list. Tight. Each bullet 1-2 lines, leading with the "
        "concrete thing that happened.\n\n"
        "## Lowlights\n"
        "Bullet list. Name the actual concern. 'We're working on it' is "
        "not a lowlight; 'churn jumped to 1.8% in SMB and we don't yet "
        "know why' is.\n\n"
        + (
            "## Asks\n"
            "Bullet list of the specific intros / hiring leads / feedback "
            "we want from the investor reader.\n\n"
            if ctx.inputs.asks.strip()
            else ""
        )
        + (
            "## Outlook\n"
            "1-2 short paragraphs. What's most on the CEO's mind looking "
            "forward — the bet, the risk, the thing being watched.\n\n"
            if ctx.inputs.outlook.strip()
            else ""
        )
        + "Discipline: no fabricated customer names, no fabricated metrics. "
        "If a number is implied but not provided, use '[X to confirm]'."
    )


def _assemble_email(ctx: _IUContext) -> str:
    parts = [
        f"# Investor Update — {ctx.inputs.month_label}",
        "",
        "Hi all,",
        "",
        ctx.narrative.strip(),
        "",
        _ensure_heading(ctx.metrics_block, "## Metrics"),
        "",
        "Thanks as always for the support.",
        "",
        "---",
        "*Drafted by Open Executive. Review every number against the source "
        "of truth before sending.*",
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
