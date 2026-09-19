"""Annual risk register workflow — produces an enterprise-level risk
register: identified risks across categories, ranked by impact and
likelihood, with leading indicators and accountable owners.

Uses the GC (General Counsel), CFO, and COO specialists.
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

_RR_EXAMPLE_PERIOD = "FY 2026"
_RR_EXAMPLE_BUSINESS = (
    "Series-A funded ($14M raised), 40 people, $4M ARR growing 80% YoY. "
    "Plan to raise Series B in Q3-Q4. Going-concern dependent on raising "
    "or hitting profitability within 18 months. SOC 2 Type II in place; "
    "no HIPAA / FedRAMP. ~50% of revenue from top 20 customers."
)
_RR_EXAMPLE_KNOWN = (
    "Strategic: a Series-C-funded competitor announced a similar product "
    "direction. Operational: single platform engineer can't take vacation; "
    "no DR runbook. Financial: top customer is 12% of ARR and renewal is "
    "in 6 months. Legal: pending GDPR processor-agreement renegotiation "
    "with 3 large customers. People: VP Engineering transition risk."
)
_RR_EXAMPLE_PRIOR = (
    "Last year's register flagged 'data center single-region dependency' "
    "(addressed via multi-region rollout) and 'inadequate IDR coverage' "
    "(partially addressed — IDR now exists but is single-shift)."
)


class RiskRegisterInput(BaseModel):
    """Inputs for the Annual Risk Register workflow."""

    review_period: str = Field(
        ...,
        description="Period the register covers (e.g., 'FY 2026', 'H2 2026').",
        min_length=3,
        examples=[_RR_EXAMPLE_PERIOD],
    )
    business_context: str = Field(
        ...,
        description=(
            "Where the business is — stage, funding, customer mix, "
            "regulatory posture. Shapes which risks are material."
        ),
        min_length=30,
        examples=[_RR_EXAMPLE_BUSINESS],
    )
    known_concerns: str = Field(
        ...,
        description=(
            "The risks leadership is already worried about, by category "
            "if possible (strategic / operational / financial / legal / "
            "people). Don't sanitize — adversarial honesty here saves "
            "later surprise."
        ),
        min_length=30,
        examples=[_RR_EXAMPLE_KNOWN],
    )
    prior_register_status: str = Field(
        default="",
        description=(
            "Optional. What was on last cycle's register and whether it "
            "was addressed. Helps avoid re-reporting closed items."
        ),
        examples=[_RR_EXAMPLE_PRIOR],
    )


class RiskRegisterWorkflow(Workflow):
    name = "risk_register"
    title = "Annual Risk Register"
    description = (
        "Drafts an enterprise risk register — risks across strategic, "
        "operational, financial, legal, and people categories, ranked "
        "and owned. Uses the General Counsel, CFO, and COO specialists."
    )
    section = WorkflowSection.RISK
    estimated_minutes = 4

    def input_model(self) -> type[BaseModel]:
        return RiskRegisterInput

    def sample_inputs(self) -> dict[str, Any]:
        return {
            "review_period": _RR_EXAMPLE_PERIOD,
            "business_context": _RR_EXAMPLE_BUSINESS,
            "known_concerns": _RR_EXAMPLE_KNOWN,
            "prior_register_status": _RR_EXAMPLE_PRIOR,
        }

    def steps(self) -> list[WorkflowStepDef]:
        return [
            WorkflowStepDef(
                id="context",
                title="Load context",
                description="Pull company profile and risk / ops RAG.",
            ),
            WorkflowStepDef(
                id="strategic",
                title="Strategic risks",
                description="Market, competitive, capital-structure risks.",
            ),
            WorkflowStepDef(
                id="operational",
                title="Operational risks",
                description="Infra, vendor, key-person, process risks.",
            ),
            WorkflowStepDef(
                id="financial",
                title="Financial risks",
                description="Cash, customer concentration, currency, fraud.",
            ),
            WorkflowStepDef(
                id="legal_reg",
                title="Legal & regulatory risks",
                description="Contracts, compliance, IP, litigation, jurisdiction.",
            ),
            WorkflowStepDef(
                id="ranking",
                title="Ranking & owners",
                description="The risk matrix and accountable owner per risk.",
            ),
            WorkflowStepDef(
                id="assemble",
                title="Assemble register",
                description="Combine into one Markdown register.",
            ),
        ]

    async def run(
        self,
        inputs: BaseModel,
        store: ChromaDBStore,
    ) -> AsyncIterator[WorkflowEvent]:
        assert isinstance(inputs, RiskRegisterInput)
        ctx = _RRCtx(inputs)

        yield WorkflowEvent(type="step_start", step_id="context", step_title="Load context")
        ctx.profile = load_or_create_profile()
        ctx.rag = retrieve(
            query="enterprise risk register operational financial legal strategic",
            specialist_name="coo",
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
            type="step_start", step_id="strategic", step_title="Strategic risks"
        )
        ctx.strategic = await route_to_specialist(
            specialist_name="coo",
            query=_build_category_prompt(ctx, "Strategic", _strategic_guidance()),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=ctx.rag,
        )
        yield WorkflowEvent(
            type="step_done", step_id="strategic", summary=_first_line(ctx.strategic)
        )

        yield WorkflowEvent(
            type="step_start", step_id="operational", step_title="Operational risks"
        )
        ctx.operational = await route_to_specialist(
            specialist_name="coo",
            query=_build_category_prompt(ctx, "Operational", _operational_guidance()),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=ctx.rag,
        )
        yield WorkflowEvent(
            type="step_done", step_id="operational", summary=_first_line(ctx.operational)
        )

        yield WorkflowEvent(
            type="step_start", step_id="financial", step_title="Financial risks"
        )
        ctx.financial = await route_to_specialist(
            specialist_name="cfo",
            query=_build_category_prompt(ctx, "Financial", _financial_guidance()),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=retrieve(
                query="financial risk cash concentration customer fraud",
                specialist_name="cfo",
                n_builtin=4,
                n_company=2,
                store=store,
            ),
        )
        yield WorkflowEvent(
            type="step_done", step_id="financial", summary=_first_line(ctx.financial)
        )

        yield WorkflowEvent(
            type="step_start", step_id="legal_reg", step_title="Legal & regulatory risks"
        )
        ctx.legal_reg = await route_to_specialist(
            specialist_name="gc",
            query=_build_category_prompt(ctx, "Legal & regulatory", _legal_guidance()),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=retrieve(
                query="legal regulatory contract compliance IP litigation risk",
                specialist_name="gc",
                n_builtin=4,
                n_company=2,
                store=store,
            ),
        )
        yield WorkflowEvent(
            type="step_done", step_id="legal_reg", summary=_first_line(ctx.legal_reg)
        )

        yield WorkflowEvent(
            type="step_start", step_id="ranking", step_title="Ranking & owners"
        )
        ctx.ranking = await route_to_specialist(
            specialist_name="coo",
            query=_build_ranking_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge="",
        )
        yield WorkflowEvent(
            type="step_done", step_id="ranking", summary=_first_line(ctx.ranking)
        )

        yield WorkflowEvent(
            type="step_start", step_id="assemble", step_title="Assemble register"
        )
        artifact = _assemble_doc(ctx)
        yield WorkflowEvent(
            type="step_done",
            step_id="assemble",
            summary=f"Assembled {len(artifact)} characters across 5 sections.",
        )
        yield WorkflowEvent(type="artifact", content=artifact)


class _RRCtx:
    def __init__(self, inputs: RiskRegisterInput) -> None:
        self.inputs = inputs
        self.profile: CompanyProfile | None = None
        self.rag: str = ""
        self.strategic: str = ""
        self.operational: str = ""
        self.financial: str = ""
        self.legal_reg: str = ""
        self.ranking: str = ""


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


def _strategic_guidance() -> str:
    return (
        "Strategic risks: things that could change the company's "
        "trajectory or viability. Examples: a well-funded competitor "
        "out-shipping, a category shift (platform consolidation), an "
        "inability to raise the next round, a key partner relationship "
        "souring."
    )


def _operational_guidance() -> str:
    return (
        "Operational risks: things that disrupt the company's ability to "
        "deliver. Examples: single-vendor dependency, key-person "
        "concentration, infra single points of failure, security gaps, "
        "vendor outages."
    )


def _financial_guidance() -> str:
    return (
        "Financial risks: cash, revenue, FX, fraud, and reporting risks. "
        "Examples: customer concentration above 10%, cash runway "
        "miscalculation, churn pockets misrepresented in metrics, "
        "currency mismatch in international deals, payroll-tax mistakes."
    )


def _legal_guidance() -> str:
    return (
        "Legal and regulatory risks: contract, compliance, IP, employment, "
        "and litigation risks. Examples: GDPR exposure, AI-content liability "
        "if applicable, IP-assignment gaps for ex-employees, customer "
        "contracts with hidden indemnity exposure, jurisdiction-specific "
        "employment risks for remote teams."
    )


def _build_category_prompt(ctx: _RRCtx, label: str, guidance: str) -> str:
    prior_block = (
        f"\n\nPrior register status:\n{ctx.inputs.prior_register_status}"
        if ctx.inputs.prior_register_status.strip()
        else ""
    )
    return (
        f"List the **{label} Risks** for {ctx.inputs.review_period}. {guidance}\n\n"
        f"Business context:\n{ctx.inputs.business_context}\n\n"
        f"Known concerns leadership flagged:\n{ctx.inputs.known_concerns}"
        f"{prior_block}\n\n"
        "Output (Markdown):\n"
        f"## {label} Risks\n\n"
        "For each risk (3-6 risks per category):\n"
        "### Risk: [Short name]\n"
        "**What could happen:** 1-2 sentences.\n"
        "**Likelihood:** High / Medium / Low — 1-sentence reason.\n"
        "**Impact:** High / Medium / Low — 1-sentence reason.\n"
        "**Leading indicator:** the observable signal that this risk is "
        "becoming real (something the team would actually monitor).\n"
        "**Current mitigation:** what we already do, if anything.\n"
        "**Gap:** what's missing in our current mitigation.\n\n"
        "Discipline: do NOT pad. If only 3 material risks exist in this "
        "category, list 3. The register's value depends on signal-to-"
        "noise, not item count. Tie risks back to specific business "
        "context where possible."
    )


def _build_ranking_prompt(ctx: _RRCtx) -> str:
    return (
        "Synthesize the **Ranking & Ownership** view across all risks "
        "identified. The reader should be able to see the top-10 risks "
        "and who owns each.\n\n"
        f"Business context:\n{ctx.inputs.business_context}\n\n"
        "Output (Markdown):\n"
        "## Ranking & Ownership\n\n"
        "### Top 10 risks\n"
        "Numbered list of the 10 risks (drawing from all 4 categories) "
        "with the highest likelihood × impact score. For each:\n"
        "- **[Short name]** (category) — Likelihood: H/M/L, Impact: H/M/L. "
        "Owner: [role placeholder].\n\n"
        "### Risks recommended for active mitigation this period\n"
        "Bullet list of 4-6 risks where leadership should fund / staff "
        "explicit mitigation in this review period. For each: the "
        "recommended action and rough effort.\n\n"
        "### Risks we accept\n"
        "Bullet list of risks we identified but are explicitly choosing "
        "not to invest in mitigating this period — typically because the "
        "cost exceeds the expected loss. Naming them prevents post-hoc "
        "surprise.\n\n"
        "Discipline: the top-10 ranking must include risks the team "
        "doesn't want to talk about. A register that's all green for "
        "the most-visible problems is performative, not useful."
    )


def _assemble_doc(ctx: _RRCtx) -> str:
    parts = [
        f"# Risk Register — {ctx.inputs.review_period}",
        "",
        "## Business Context",
        "",
        ctx.inputs.business_context.strip(),
        "",
        _ensure_heading(ctx.strategic, "## Strategic Risks"),
        "",
        _ensure_heading(ctx.operational, "## Operational Risks"),
        "",
        _ensure_heading(ctx.financial, "## Financial Risks"),
        "",
        _ensure_heading(ctx.legal_reg, "## Legal & Regulatory Risks"),
        "",
        _ensure_heading(ctx.ranking, "## Ranking & Ownership"),
        "",
        "---",
        "*Drafted by Open Executive. Review with leadership, sharpen, "
        "and confirm owners. Revisit quarterly; the register loses "
        "value the moment it's filed and forgotten.*",
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
