"""Customer churn deep-dive workflow — produces a structured churn
analysis: cohort patterns, root-cause hypotheses, retention interventions
ranked by leverage, and financial impact.

Uses the CPO, CMO, and CFO specialists.
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

_CH_EXAMPLE_OVERVIEW = (
    "Quarterly churn (logo) climbed from 1.2% to 1.8% over the last 3 "
    "quarters. Net dollar retention is still 112% so revenue churn looks "
    "fine — but the customer base is leaking. Concentrated in <50-seat "
    "accounts; mid-market and enterprise are stable."
)
_CH_EXAMPLE_COHORTS = (
    "- <50 seats: 3.1% quarterly logo churn (was 1.5%)\n"
    "- 50-200 seats: 1.4% (flat)\n"
    "- >200 seats: 0.6% (improved)\n"
    "- By age: 0-6mo cohort churning at 5.2% — the bulk of the problem.\n"
    "- By acquisition channel: paid-search-acquired accounts churning 2x organic."
)
_CH_EXAMPLE_QUALITATIVE = (
    "Exit-survey themes from the last quarter:\n"
    "1. 'Too expensive for the value' (43% of small-account exits)\n"
    "2. 'Couldn't get our team to adopt' (28%)\n"
    "3. 'Found a simpler tool' (19%)\n"
    "Onboarding: time-to-first-report on the SMB plan is 11 days median "
    "(vs. 3 days on mid-market where CS owns it)."
)
_CH_EXAMPLE_INTERVENTIONS = (
    "Already running: weekly 'activation report' email for new accounts. "
    "Considering: a high-touch CS motion for the top decile by usage in "
    "the first 30 days, a simplified onboarding for solo / small teams, "
    "and a paid-search audience refinement to drop low-intent traffic."
)


class ChurnDeepDiveInput(BaseModel):
    """Inputs for the Customer Churn Deep-Dive workflow."""

    overview: str = Field(
        ...,
        description=(
            "What's the churn picture — magnitude, direction, and where "
            "it's concentrated? Be specific about the segment(s) affected."
        ),
        min_length=30,
        examples=[_CH_EXAMPLE_OVERVIEW],
    )
    cohort_data: str = Field(
        ...,
        description=(
            "Cohort breakdown — by segment, age, channel, plan tier, or "
            "however we slice it. Numbers expected, not narratives."
        ),
        min_length=20,
        examples=[_CH_EXAMPLE_COHORTS],
    )
    qualitative_signal: str = Field(
        default="",
        description=(
            "Optional. Exit-survey themes, CS-team observations, support "
            "ticket patterns. What customers actually say or do before leaving."
        ),
        examples=[_CH_EXAMPLE_QUALITATIVE],
    )
    interventions_already_tried: str = Field(
        default="",
        description=(
            "Optional. What we've already shipped or are considering, so "
            "the memo doesn't recommend things we're already doing."
        ),
        examples=[_CH_EXAMPLE_INTERVENTIONS],
    )


class ChurnDeepDiveWorkflow(Workflow):
    name = "churn_deep_dive"
    title = "Customer Churn Deep-Dive"
    description = (
        "Drafts a structured churn analysis — cohort read, root-cause "
        "hypotheses, retention interventions ranked by leverage, and "
        "financial impact. Uses the CPO, CMO, and CFO specialists."
    )
    section = WorkflowSection.PRODUCT
    estimated_minutes = 4

    def input_model(self) -> type[BaseModel]:
        return ChurnDeepDiveInput

    def sample_inputs(self) -> dict[str, Any]:
        return {
            "overview": _CH_EXAMPLE_OVERVIEW,
            "cohort_data": _CH_EXAMPLE_COHORTS,
            "qualitative_signal": _CH_EXAMPLE_QUALITATIVE,
            "interventions_already_tried": _CH_EXAMPLE_INTERVENTIONS,
        }

    def steps(self) -> list[WorkflowStepDef]:
        return [
            WorkflowStepDef(
                id="context",
                title="Load context",
                description="Pull company profile and retention/product RAG.",
            ),
            WorkflowStepDef(
                id="diagnosis",
                title="Diagnose root causes",
                description="2-3 root-cause hypotheses ranked by evidence weight.",
            ),
            WorkflowStepDef(
                id="interventions",
                title="Rank interventions",
                description="Possible retention plays scored by leverage and feasibility.",
            ),
            WorkflowStepDef(
                id="financial",
                title="Model financial impact",
                description="What 50bps of churn improvement is worth.",
            ),
            WorkflowStepDef(
                id="program",
                title="Propose a 90-day program",
                description="Sequenced action plan with owners and checkpoints.",
            ),
            WorkflowStepDef(
                id="assemble",
                title="Assemble report",
                description="Combine sections into one Markdown report.",
            ),
        ]

    async def run(
        self,
        inputs: BaseModel,
        store: ChromaDBStore,
    ) -> AsyncIterator[WorkflowEvent]:
        assert isinstance(inputs, ChurnDeepDiveInput)
        ctx = _ChurnCtx(inputs)

        yield WorkflowEvent(type="step_start", step_id="context", step_title="Load context")
        ctx.profile = load_or_create_profile()
        ctx.rag = retrieve(
            query="SaaS customer churn retention cohort analysis interventions",
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
            type="step_start", step_id="diagnosis", step_title="Diagnose root causes"
        )
        ctx.diagnosis = await route_to_specialist(
            specialist_name="cpo",
            query=_build_diagnosis_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=ctx.rag,
        )
        yield WorkflowEvent(
            type="step_done", step_id="diagnosis", summary=_first_line(ctx.diagnosis)
        )

        yield WorkflowEvent(
            type="step_start", step_id="interventions", step_title="Rank interventions"
        )
        ctx.interventions = await route_to_specialist(
            specialist_name="cmo",
            query=_build_interventions_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=retrieve(
                query="customer success retention lifecycle interventions onboarding",
                specialist_name="cmo",
                n_builtin=4,
                n_company=3,
                store=store,
            ),
        )
        yield WorkflowEvent(
            type="step_done", step_id="interventions", summary=_first_line(ctx.interventions)
        )

        yield WorkflowEvent(
            type="step_start", step_id="financial", step_title="Model financial impact"
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
            type="step_start", step_id="program", step_title="Propose a 90-day program"
        )
        ctx.program = await route_to_specialist(
            specialist_name="cpo",
            query=_build_program_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=ctx.rag,
        )
        yield WorkflowEvent(
            type="step_done", step_id="program", summary=_first_line(ctx.program)
        )

        yield WorkflowEvent(
            type="step_start", step_id="assemble", step_title="Assemble report"
        )
        artifact = _assemble_report(ctx)
        yield WorkflowEvent(
            type="step_done",
            step_id="assemble",
            summary=f"Assembled {len(artifact)} characters across 4 sections.",
        )
        yield WorkflowEvent(type="artifact", content=artifact)


class _ChurnCtx:
    def __init__(self, inputs: ChurnDeepDiveInput) -> None:
        self.inputs = inputs
        self.profile: CompanyProfile | None = None
        self.rag: str = ""
        self.diagnosis: str = ""
        self.interventions: str = ""
        self.financial: str = ""
        self.program: str = ""


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


def _build_diagnosis_prompt(ctx: _ChurnCtx) -> str:
    qual_block = (
        f"\n\nQualitative signal:\n{ctx.inputs.qualitative_signal}"
        if ctx.inputs.qualitative_signal.strip()
        else ""
    )
    return (
        "Diagnose the **Root Causes** of the churn pattern. We're looking "
        "for 2-3 hypotheses, ranked by evidence weight — not a laundry "
        "list. Each hypothesis must be testable.\n\n"
        f"Overview:\n{ctx.inputs.overview}\n\n"
        f"Cohort breakdown:\n{ctx.inputs.cohort_data}"
        f"{qual_block}\n\n"
        "Output (Markdown):\n"
        "## Root-Cause Hypotheses\n\n"
        "For each hypothesis (2-3 total, ranked):\n"
        "### Hypothesis N: [Short name]\n"
        "**Claim:** 1 sentence stating the proposed cause.\n"
        "**Supporting evidence:** 2-3 specific data points from the inputs.\n"
        "**Disconfirming evidence we'd accept:** what would have to be "
        "true for us to abandon this hypothesis. Forces the diagnosis to "
        "be falsifiable.\n"
        "**Confidence:** High / Medium / Low — with 1-sentence reason.\n\n"
        "Discipline: do not propose 'product is too expensive' or 'product "
        "is too complex' without naming the specific feature, segment, or "
        "moment in the customer journey involved. Vague diagnoses produce "
        "vague interventions."
    )


def _build_interventions_prompt(ctx: _ChurnCtx) -> str:
    already_block = (
        f"\n\nAlready tried / under consideration:\n{ctx.inputs.interventions_already_tried}"
        if ctx.inputs.interventions_already_tried.strip()
        else ""
    )
    return (
        "Propose **Retention Interventions** addressing the diagnosed "
        "causes. Rank by (leverage × feasibility). Avoid recommending "
        "things already being tried.\n\n"
        f"Overview:\n{ctx.inputs.overview}{already_block}\n\n"
        "Output (Markdown):\n"
        "## Interventions\n\n"
        "For each intervention (4-7 total, ranked):\n"
        "### Intervention N: [Short name]\n"
        "**What:** 1-2 sentences. What we'd actually do.\n"
        "**Addresses hypothesis:** reference 1-3 of the root-cause hypotheses.\n"
        "**Effort:** Low / Medium / High — engineering + GTM weeks.\n"
        "**Expected impact:** the cohort-level metric movement we'd "
        "expect, with a rough timeframe. Use ranges, not point estimates.\n"
        "**Risk:** what could backfire (e.g., 'might increase support load').\n\n"
        "Discipline: rank by leverage. The first 1-2 interventions should "
        "be the ones we'd run even if we had to drop the rest. Mark any "
        "that overlap with the 'already tried' list as such."
    )


def _build_financial_prompt(ctx: _ChurnCtx) -> str:
    return (
        "Model the **Financial Impact** of reducing churn. We need to put "
        "a rough dollar value on the problem to size the investment.\n\n"
        f"Overview:\n{ctx.inputs.overview}\n\n"
        f"Cohort breakdown:\n{ctx.inputs.cohort_data}\n\n"
        "Output (Markdown):\n"
        "## Financial Impact\n\n"
        "### Current cost\n"
        "1 paragraph: rough annualized cost of the current churn rate. "
        "Use placeholders for figures we don't have (ARR, ASP per segment).\n\n"
        "### If we cut churn in half\n"
        "1 paragraph: what the ARR and revenue trajectory look like 12mo "
        "out if we hit the target reduction (typically 25-50% improvement "
        "is feasible). Frame as a range.\n\n"
        "### Numbers we'd need to confirm\n"
        "Bullet list of figures to pull from FP&A / data team: ASP per "
        "segment, gross margin on at-risk segment, payback period on "
        "the proposed intervention budgets.\n\n"
        "Do NOT invent specific dollar figures. Show the math but use "
        "placeholders for the inputs we don't have."
    )


def _build_program_prompt(ctx: _ChurnCtx) -> str:
    return (
        "Propose a **90-Day Retention Program** sequencing the highest-"
        "leverage interventions into something the team can actually run.\n\n"
        "Output (Markdown):\n"
        "## 90-Day Retention Program\n\n"
        "### Days 0-30\n"
        "Bullet list: discovery + first-30-day interventions. Owner "
        "placeholders.\n\n"
        "### Days 31-60\n"
        "Bullet list: shipping interventions, learning loop.\n\n"
        "### Days 61-90\n"
        "Bullet list: full-cohort measurement, decisions about what to "
        "scale or kill.\n\n"
        "### Weekly metrics review\n"
        "Bullet list of the 4-6 metrics the team reviews weekly during "
        "the program. For each, the threshold that triggers an escalation.\n\n"
        "Discipline: the program must respect realistic eng / CS / marketing "
        "capacity. If everything looks like it needs to ship at once, "
        "sequence ruthlessly and call out the explicit deferrals."
    )


def _assemble_report(ctx: _ChurnCtx) -> str:
    parts = [
        "# Customer Churn Deep-Dive",
        "",
        "## Overview",
        "",
        ctx.inputs.overview.strip(),
        "",
        _ensure_heading(ctx.diagnosis, "## Root-Cause Hypotheses"),
        "",
        _ensure_heading(ctx.interventions, "## Interventions"),
        "",
        _ensure_heading(ctx.financial, "## Financial Impact"),
        "",
        _ensure_heading(ctx.program, "## 90-Day Retention Program"),
        "",
        "---",
        "*Drafted by Open Executive. Validate every percentage in the cohort "
        "section against the source data before circulating.*",
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
