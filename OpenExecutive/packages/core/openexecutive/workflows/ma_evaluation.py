"""M&A target evaluation workflow — produces a structured evaluation of
a potential acquisition target: strategic rationale, valuation frame,
diligence checklist, integration risks, and recommendation.

Uses the CFO, CSO, and GC (General Counsel) specialists.
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

_MA_EXAMPLE_TARGET = (
    "Acme Analytics — 18-person Series-A SaaS company, ~$3.2M ARR, "
    "growing ~80% YoY. Their differentiated feature is a 'natural-"
    "language to SQL' engine, which we believe sits ahead of ours by "
    "~12 months. Founded 2022, raised $8M from a tier-2 fund. Based "
    "in NYC, fully remote engineering team in EU."
)
_MA_EXAMPLE_RATIONALE = (
    "Closes a ~12-month product gap on AI-assisted querying. Removes "
    "the most credible mid-market competitor we run into. The engineering "
    "team is unusually strong relative to their stage and would add 4-5 "
    "senior ICs we can't easily hire on the open market."
)
_MA_EXAMPLE_PRICE = (
    "Founder has signaled openness to acquisition in the $25-40M range "
    "(8-12x ARR). Likely structure: 60-70% stock, balance cash, with a "
    "12-18 month earn-out tied to retention of key employees."
)
_MA_EXAMPLE_KNOWN_RISKS = (
    "Their CTO is a co-founder and may not want to stay post-close — "
    "without him the engineering moat halves. They have a single $400K "
    "enterprise customer that's 12% of ARR. Their tech stack overlaps "
    "ours only ~40%; integration cost is real."
)


class MAEvaluationInput(BaseModel):
    """Inputs for the M&A Target Evaluation workflow."""

    target: str = Field(
        ...,
        description=(
            "The target company — name, size, stage, what they do, and "
            "anything else that frames the deal."
        ),
        min_length=30,
        examples=[_MA_EXAMPLE_TARGET],
    )
    strategic_rationale: str = Field(
        ...,
        description=(
            "Why this acquisition makes strategic sense. The 1-2 things "
            "you couldn't buy with cash on the open market."
        ),
        min_length=20,
        examples=[_MA_EXAMPLE_RATIONALE],
    )
    price_indication: str = Field(
        default="",
        description=(
            "Optional. The price range and likely deal structure (cash vs. "
            "stock vs. earn-out)."
        ),
        examples=[_MA_EXAMPLE_PRICE],
    )
    known_risks: str = Field(
        default="",
        description=(
            "Optional. Risks already apparent — customer concentration, "
            "key-person dependency, tech overlap, retention concerns."
        ),
        examples=[_MA_EXAMPLE_KNOWN_RISKS],
    )


class MAEvaluationWorkflow(Workflow):
    name = "ma_evaluation"
    title = "M&A Target Evaluation"
    description = (
        "Drafts a structured evaluation of a potential acquisition target "
        "— strategic rationale check, valuation frame, diligence "
        "checklist, integration risks, and a recommendation. Uses the "
        "CFO, CSO, and General Counsel specialists."
    )
    section = WorkflowSection.RISK
    estimated_minutes = 5

    def input_model(self) -> type[BaseModel]:
        return MAEvaluationInput

    def sample_inputs(self) -> dict[str, Any]:
        return {
            "target": _MA_EXAMPLE_TARGET,
            "strategic_rationale": _MA_EXAMPLE_RATIONALE,
            "price_indication": _MA_EXAMPLE_PRICE,
            "known_risks": _MA_EXAMPLE_KNOWN_RISKS,
        }

    def steps(self) -> list[WorkflowStepDef]:
        return [
            WorkflowStepDef(
                id="context",
                title="Load context",
                description="Pull company profile and M&A / strategy RAG.",
            ),
            WorkflowStepDef(
                id="strategic_check",
                title="Strategic rationale check",
                description="Pressure-test why this is worth doing.",
            ),
            WorkflowStepDef(
                id="valuation",
                title="Valuation frame",
                description="How to think about the price and the structure.",
            ),
            WorkflowStepDef(
                id="diligence",
                title="Diligence checklist",
                description="Commercial, financial, technical, legal, and people due diligence.",
            ),
            WorkflowStepDef(
                id="integration",
                title="Integration risk map",
                description="The post-close 12-month operational risks.",
            ),
            WorkflowStepDef(
                id="recommendation",
                title="Recommendation",
                description="The Yes / No / Conditional with the decision criteria.",
            ),
            WorkflowStepDef(
                id="assemble",
                title="Assemble evaluation",
                description="Combine into one Markdown evaluation.",
            ),
        ]

    async def run(
        self,
        inputs: BaseModel,
        store: ChromaDBStore,
    ) -> AsyncIterator[WorkflowEvent]:
        assert isinstance(inputs, MAEvaluationInput)
        ctx = _MACtx(inputs)

        yield WorkflowEvent(type="step_start", step_id="context", step_title="Load context")
        ctx.profile = load_or_create_profile()
        ctx.rag = retrieve(
            query="mergers acquisitions valuation diligence integration",
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
            type="step_start", step_id="strategic_check", step_title="Strategic rationale check"
        )
        ctx.strategic_check = await route_to_specialist(
            specialist_name="cso",
            query=_build_strategic_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=ctx.rag,
        )
        yield WorkflowEvent(
            type="step_done", step_id="strategic_check", summary=_first_line(ctx.strategic_check)
        )

        yield WorkflowEvent(
            type="step_start", step_id="valuation", step_title="Valuation frame"
        )
        ctx.valuation = await route_to_specialist(
            specialist_name="cfo",
            query=_build_valuation_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=retrieve(
                query="SaaS acquisition valuation multiples earnout deal structure",
                specialist_name="cfo",
                n_builtin=4,
                n_company=2,
                store=store,
            ),
        )
        yield WorkflowEvent(
            type="step_done", step_id="valuation", summary=_first_line(ctx.valuation)
        )

        yield WorkflowEvent(
            type="step_start", step_id="diligence", step_title="Diligence checklist"
        )
        ctx.diligence = await route_to_specialist(
            specialist_name="gc",
            query=_build_diligence_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=retrieve(
                query="due diligence checklist acquisition legal commercial",
                specialist_name="gc",
                n_builtin=4,
                n_company=2,
                store=store,
            ),
        )
        yield WorkflowEvent(
            type="step_done", step_id="diligence", summary=_first_line(ctx.diligence)
        )

        yield WorkflowEvent(
            type="step_start", step_id="integration", step_title="Integration risk map"
        )
        ctx.integration = await route_to_specialist(
            specialist_name="cso",
            query=_build_integration_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=ctx.rag,
        )
        yield WorkflowEvent(
            type="step_done", step_id="integration", summary=_first_line(ctx.integration)
        )

        yield WorkflowEvent(
            type="step_start", step_id="recommendation", step_title="Recommendation"
        )
        ctx.recommendation = await route_to_specialist(
            specialist_name="cso",
            query=_build_recommendation_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge="",
        )
        yield WorkflowEvent(
            type="step_done", step_id="recommendation", summary=_first_line(ctx.recommendation)
        )

        yield WorkflowEvent(
            type="step_start", step_id="assemble", step_title="Assemble evaluation"
        )
        artifact = _assemble_doc(ctx)
        yield WorkflowEvent(
            type="step_done",
            step_id="assemble",
            summary=f"Assembled {len(artifact)} characters across 5 sections.",
        )
        yield WorkflowEvent(type="artifact", content=artifact)


class _MACtx:
    def __init__(self, inputs: MAEvaluationInput) -> None:
        self.inputs = inputs
        self.profile: CompanyProfile | None = None
        self.rag: str = ""
        self.strategic_check: str = ""
        self.valuation: str = ""
        self.diligence: str = ""
        self.integration: str = ""
        self.recommendation: str = ""


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


def _build_strategic_prompt(ctx: _MACtx) -> str:
    risks_block = (
        f"\n\nKnown risks the founder named:\n{ctx.inputs.known_risks}"
        if ctx.inputs.known_risks.strip()
        else ""
    )
    return (
        "Pressure-test the **Strategic Rationale** for this acquisition. "
        "M&A is the most expensive way to acquire most things — make us "
        "earn the case.\n\n"
        f"Target:\n{ctx.inputs.target}\n\n"
        f"Founder's rationale:\n{ctx.inputs.strategic_rationale}{risks_block}\n\n"
        "Output (Markdown):\n"
        "## Strategic Rationale Check\n\n"
        "### Why M&A vs. alternatives\n"
        "1-2 paragraphs. For each named benefit (closes product gap, "
        "adds team, removes competitor), evaluate whether we could "
        "achieve it cheaper via build / hire / partner. Be honest.\n\n"
        "### What we're actually buying\n"
        "1 paragraph: rank-ordered list of what's worth paying for "
        "here (e.g., 'the engineering team', 'the customer base', 'the "
        "IP', 'removing a competitor'). The order matters — if the "
        "engineering team is #1 and we lose them post-close, the deal "
        "evaporates.\n\n"
        "### Counter-thesis\n"
        "1 paragraph: the strongest argument for NOT doing this deal "
        "even if we could. Force the reader to confront it.\n\n"
        "Discipline: do not assume the founder's rationale is correct. "
        "If 'removes a competitor' is the real driver, say so — that's "
        "a weaker reason than 'closes a product gap'."
    )


def _build_valuation_prompt(ctx: _MACtx) -> str:
    price_block = (
        f"\n\nPrice indication:\n{ctx.inputs.price_indication}"
        if ctx.inputs.price_indication.strip()
        else ""
    )
    return (
        "Frame the **Valuation** of this target.\n\n"
        f"Target:\n{ctx.inputs.target}{price_block}\n\n"
        f"Strategic rationale (for synergy adjustment):\n{ctx.inputs.strategic_rationale}\n\n"
        "Output (Markdown):\n"
        "## Valuation Frame\n\n"
        "### Standalone value\n"
        "1 paragraph: what the target is worth as a stand-alone business. "
        "Reference 2-3 comparable transactions or rev-multiple bands. "
        "Use placeholders if their financials aren't fully disclosed.\n\n"
        "### Synergy value to us\n"
        "1 paragraph: revenue + cost synergies we'd realistically capture, "
        "discounted heavily because most synergies are overestimated.\n\n"
        "### Walk-away price\n"
        "1 sentence: the price above which we no longer do this deal, "
        "even with strategic upside.\n\n"
        "### Structure recommendations\n"
        "Bullet list: cash / stock mix, escrow size, earn-out triggers "
        "(typically tied to retention + revenue), reps & warranties cap. "
        "For each, the rationale.\n\n"
        "Do NOT invent specific dollar figures. Use ranges and "
        "placeholders for inputs we don't have."
    )


def _build_diligence_prompt(ctx: _MACtx) -> str:
    return (
        "Draft the **Diligence Checklist** for this target. Stage-"
        "appropriate, organized so the deal team can divide ownership.\n\n"
        f"Target:\n{ctx.inputs.target}\n\n"
        "Output (Markdown):\n"
        "## Diligence Checklist\n\n"
        "### Commercial\n"
        "Bullet list: customer concentration, churn by cohort, "
        "renewal motion, pipeline quality, sales cycle, top-20 customer "
        "list, pricing exceptions.\n\n"
        "### Financial\n"
        "Bullet list: 3 years monthly P&L, ARR waterfall, deferred "
        "revenue, cap table (fully diluted), all material contracts, "
        "debt + warrant schedule.\n\n"
        "### Technical\n"
        "Bullet list: code-quality assessment, security audit, "
        "open-source license inventory, tech-debt list, vendor "
        "dependencies, customer-data segregation.\n\n"
        "### Legal\n"
        "Bullet list: corporate records, IP assignment for all current "
        "and former employees, litigation history, regulatory "
        "compliance (GDPR / SOC 2 / HIPAA where relevant), employment "
        "agreements, customer contracts with change-of-control clauses.\n\n"
        "### People\n"
        "Bullet list: key-person dependency map, retention concerns, "
        "comp / equity structure, performance history, anti-bullying / "
        "harassment complaints, equity-vesting schedules.\n\n"
        "Discipline: every item must be actionable — 'review HR records' "
        "is not a diligence task; 'request all employee NDAs, IP "
        "assignment agreements, and termination records for the last "
        "3 years' is."
    )


def _build_integration_prompt(ctx: _MACtx) -> str:
    return (
        "Map the **Integration Risks** for the first 12 months post-close.\n\n"
        f"Target:\n{ctx.inputs.target}\n\n"
        f"Strategic rationale:\n{ctx.inputs.strategic_rationale}\n\n"
        "Output (Markdown):\n"
        "## Integration Risk Map\n\n"
        "### People\n"
        "Bullet list of 3-5 specific people risks: key-person retention, "
        "culture clash, comp leveling, reporting-line disputes. For each, "
        "the trip-wire and mitigation.\n\n"
        "### Product & tech\n"
        "Bullet list of 3-5 product/tech risks: stack-merge complexity, "
        "shared customer migration, brand consolidation, support load. "
        "Trip-wire + mitigation each.\n\n"
        "### Commercial\n"
        "Bullet list: customer overlap, contract renegotiation triggers, "
        "channel conflicts. Trip-wire + mitigation each.\n\n"
        "### Most likely deal-killer\n"
        "1 paragraph: of all the risks listed, the one most likely to "
        "make this deal feel like a mistake 12 months out. Call it out "
        "explicitly so leadership can decide whether they accept it.\n\n"
        "Discipline: each risk must be specific to THIS target, not "
        "a generic M&A textbook list."
    )


def _build_recommendation_prompt(ctx: _MACtx) -> str:
    return (
        "Draft the **Recommendation**. The deal team needs a clear "
        "answer (with conditions), not a survey of the evidence.\n\n"
        f"Target:\n{ctx.inputs.target}\n\n"
        f"Strategic rationale:\n{ctx.inputs.strategic_rationale}\n\n"
        f"Known risks:\n{ctx.inputs.known_risks or '(none disclosed)'}\n\n"
        "Output (Markdown):\n"
        "## Recommendation\n\n"
        "### Verdict\n"
        "**Recommendation:** [Pursue / Pursue with conditions / Pass]\n\n"
        "1 paragraph justifying the call. Reference the strategic check, "
        "valuation, and integration sections.\n\n"
        "### Conditions to satisfy before LOI\n"
        "Bullet list: what diligence questions must come back favorably, "
        "what key-person commitments we need, what valuation range we "
        "lock in.\n\n"
        "### Walk-away triggers\n"
        "Bullet list: specific findings in diligence that would change "
        "the recommendation to a pass.\n\n"
        "Discipline: the verdict must be unambiguous. 'Lean yes' is "
        "not a recommendation."
    )


def _assemble_doc(ctx: _MACtx) -> str:
    parts = [
        "# M&A Target Evaluation",
        "",
        "## Target",
        "",
        ctx.inputs.target.strip(),
        "",
        "## Strategic Rationale (founder)",
        "",
        ctx.inputs.strategic_rationale.strip(),
        "",
        _ensure_heading(ctx.strategic_check, "## Strategic Rationale Check"),
        "",
        _ensure_heading(ctx.valuation, "## Valuation Frame"),
        "",
        _ensure_heading(ctx.diligence, "## Diligence Checklist"),
        "",
        _ensure_heading(ctx.integration, "## Integration Risk Map"),
        "",
        _ensure_heading(ctx.recommendation, "## Recommendation"),
        "",
        "---",
        "*Drafted by Open Executive. Engage outside M&A counsel and a "
        "deal advisor before issuing an LOI. Every diligence finding "
        "below must be confirmed against primary documents.*",
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
