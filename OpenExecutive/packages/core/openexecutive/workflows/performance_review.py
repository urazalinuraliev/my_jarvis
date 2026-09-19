"""Performance review workflow — produces a calibration packet for a
manager: a clarified rubric, per-report structured writeups, team-level
patterns, and manager talking points for the review conversations.

Output is a draft. The manager owns final ratings, final language, and
final calibration decisions. This workflow accelerates preparation — it
does not replace the manager's judgment.
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

_DEFAULT_RUBRIC = (
    "Execution (delivers committed outcomes), Craft (technical or "
    "functional depth and quality), Leadership (raises the bar for others, "
    "owns scope), Collaboration (works effectively cross-functionally), "
    "Impact (measurable business outcomes)."
)

_PR_EXAMPLE_REPORTS = (
    "Alex Chen, Staff Backend Engineer, 3yr tenure: Owned the v2 reporting "
    "rebuild end-to-end; shipped on time, drove the architecture decisions, "
    "mentored two mids who got promoted this cycle. Strong cross-functional "
    "with Product. Concern: occasionally lets perfect block good — held up "
    "the migration two weeks debating an edge case worth ~3% of traffic.\n\n"
    "Priya Shah, Sr Backend Engineer, 1.5yr tenure: Carried the on-call rotation "
    "during the April outage; clean postmortem. Owned the Snowflake pipeline "
    "rewrite; cut costs 40%. Concern: writes great code but rarely reviews "
    "others'; team feedback is that her LGTMs lack depth.\n\n"
    "Jordan Park, Mid Frontend, 8mo tenure: Faster ramp than expected — "
    "shipped the dashboard refresh solo. Customer compliment from Acme on "
    "responsiveness. Concern: still light on testing discipline; flaky tests "
    "shipped to main twice."
)
_PR_EXAMPLE_TEAM_CONTEXT = (
    "We reorged in February — backend team grew from 4 to 7, and Alex took "
    "on a tech-lead role. Bar was raised on the hiring loop in Q1. "
    "Two open backfills slipped into next quarter."
)
_PR_EXAMPLE_PROMOTIONS = (
    "Priya Shah for Staff. We expect Staff promotions to demonstrate scope "
    "beyond their team and consistent technical leadership in design reviews."
)


class PerformanceReviewInput(BaseModel):
    """Inputs for the Performance Review prep workflow."""

    review_period: str = Field(
        ...,
        description="Review period (e.g., 'H1 2026' or 'Q2 2026')",
        examples=["H1 2026"],
    )
    manager_role: str = Field(
        ...,
        description="The manager's role, used to set the right scope and rubric (e.g., 'VP Engineering').",
        examples=["VP Engineering"],
    )
    direct_reports: str = Field(
        ...,
        description=(
            "One block of free text per direct report. Recommended format:\n"
            "Name, role, tenure: <summary of work this period including "
            "key outcomes, observations, strengths, concerns, customer or "
            "peer feedback>. One paragraph per person."
        ),
        min_length=40,
        examples=[_PR_EXAMPLE_REPORTS],
    )
    calibration_rubric: str = Field(
        default="",
        description=(
            "Optional. The dimensions you evaluate against. If blank, a "
            "default 5-dimension rubric will be used "
            "(Execution / Craft / Leadership / Collaboration / Impact)."
        ),
        examples=[_DEFAULT_RUBRIC],
    )
    team_context: str = Field(
        default="",
        description=(
            "Optional. Team-level context that affects calibration — recent "
            "reorgs, stretch projects, attrition, hiring bar shifts."
        ),
        examples=[_PR_EXAMPLE_TEAM_CONTEXT],
    )
    promotion_candidates: str = Field(
        default="",
        description=(
            "Optional. Any reports being considered for promotion this cycle. "
            "Promotion readiness gets an extra section in the writeup."
        ),
        examples=[_PR_EXAMPLE_PROMOTIONS],
    )


class PerformanceReviewWorkflow(Workflow):
    name = "performance_review"
    title = "Performance Review Prep"
    description = (
        "Drafts a calibration packet for a manager preparing performance "
        "reviews — clarified rubric, structured per-report writeups, "
        "team-level patterns, and talking points for each conversation. "
        "Uses the CHRO specialist."
    )
    section = WorkflowSection.PEOPLE
    estimated_minutes = 5

    def input_model(self) -> type[BaseModel]:
        return PerformanceReviewInput

    def sample_inputs(self) -> dict[str, Any]:
        return {
            "review_period": "H1 2026",
            "manager_role": "VP Engineering",
            "direct_reports": _PR_EXAMPLE_REPORTS,
            "calibration_rubric": _DEFAULT_RUBRIC,
            "team_context": _PR_EXAMPLE_TEAM_CONTEXT,
            "promotion_candidates": _PR_EXAMPLE_PROMOTIONS,
        }

    def steps(self) -> list[WorkflowStepDef]:
        return [
            WorkflowStepDef(
                id="context",
                title="Load context",
                description="Pull company profile, performance-management knowledge, and review-period framing.",
            ),
            WorkflowStepDef(
                id="rubric",
                title="Clarify the rubric",
                description="Refine the calibration dimensions and define what each level looks like.",
            ),
            WorkflowStepDef(
                id="per_report_writeups",
                title="Draft per-report writeups",
                description="Structured writeup per direct report: observations, strengths, growth areas, rating direction.",
            ),
            WorkflowStepDef(
                id="calibration_view",
                title="Draft team-level calibration view",
                description="Patterns across the team, distribution, promotion readiness, calibration risks.",
            ),
            WorkflowStepDef(
                id="talking_points",
                title="Draft manager talking points",
                description="Per-report talking points for the actual review conversation.",
            ),
            WorkflowStepDef(
                id="assemble",
                title="Assemble final packet",
                description="Combine all sections into a single Markdown packet.",
            ),
        ]

    async def run(
        self,
        inputs: BaseModel,
        store: ChromaDBStore,
    ) -> AsyncIterator[WorkflowEvent]:
        assert isinstance(inputs, PerformanceReviewInput)
        ctx = _PerformanceReviewContext(inputs)

        # --- Step 1: context ---
        yield WorkflowEvent(type="step_start", step_id="context", step_title="Load context")
        ctx.profile = load_or_create_profile()
        ctx.rag = retrieve(
            query="performance review calibration rubric ratings promotion",
            specialist_name="chro",
            n_builtin=5,
            n_company=3,
            store=store,
        )
        yield WorkflowEvent(
            type="step_done",
            step_id="context",
            summary=(
                f"Loaded profile and {_chunk_count(ctx.rag)} RAG chunks. "
                f"Using {'provided' if ctx.inputs.calibration_rubric.strip() else 'default'} rubric."
            ),
        )

        # --- Step 2: rubric ---
        yield WorkflowEvent(
            type="step_start", step_id="rubric", step_title="Clarify the rubric"
        )
        ctx.rubric_section = await route_to_specialist(
            specialist_name="chro",
            query=_build_rubric_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=ctx.rag,
        )
        yield WorkflowEvent(
            type="step_done", step_id="rubric", summary=_first_line(ctx.rubric_section)
        )

        # --- Step 3: per-report writeups ---
        yield WorkflowEvent(
            type="step_start",
            step_id="per_report_writeups",
            step_title="Draft per-report writeups",
        )
        ctx.per_report = await route_to_specialist(
            specialist_name="chro",
            query=_build_writeups_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=ctx.rag,
        )
        yield WorkflowEvent(
            type="step_done",
            step_id="per_report_writeups",
            summary=_first_line(ctx.per_report),
        )

        # --- Step 4: calibration view ---
        yield WorkflowEvent(
            type="step_start",
            step_id="calibration_view",
            step_title="Draft team-level calibration view",
        )
        ctx.calibration_view = await route_to_specialist(
            specialist_name="chro",
            query=_build_calibration_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=ctx.rag,
        )
        yield WorkflowEvent(
            type="step_done",
            step_id="calibration_view",
            summary=_first_line(ctx.calibration_view),
        )

        # --- Step 5: talking points ---
        yield WorkflowEvent(
            type="step_start",
            step_id="talking_points",
            step_title="Draft manager talking points",
        )
        ctx.talking_points = await route_to_specialist(
            specialist_name="chro",
            query=_build_talking_points_prompt(ctx),
            context=_company_context_block(ctx.profile),
            retrieved_knowledge=ctx.rag,
        )
        yield WorkflowEvent(
            type="step_done",
            step_id="talking_points",
            summary=_first_line(ctx.talking_points),
        )

        # --- Step 6: assemble ---
        yield WorkflowEvent(
            type="step_start", step_id="assemble", step_title="Assemble final packet"
        )
        artifact = _assemble_packet(ctx)
        yield WorkflowEvent(
            type="step_done",
            step_id="assemble",
            summary=f"Assembled {len(artifact)} characters across 4 sections.",
        )
        yield WorkflowEvent(type="artifact", content=artifact)


# -----------------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------------


class _PerformanceReviewContext:
    def __init__(self, inputs: PerformanceReviewInput) -> None:
        self.inputs = inputs
        self.profile: CompanyProfile | None = None
        self.rag: str = ""
        self.rubric_section: str = ""
        self.per_report: str = ""
        self.calibration_view: str = ""
        self.talking_points: str = ""

    @property
    def effective_rubric(self) -> str:
        return self.inputs.calibration_rubric.strip() or _DEFAULT_RUBRIC


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


def _build_rubric_prompt(ctx: _PerformanceReviewContext) -> str:
    return (
        f"For a {ctx.inputs.manager_role} preparing {ctx.inputs.review_period} "
        "performance reviews, refine the calibration rubric below into clear, "
        "evaluable dimensions.\n\n"
        f"Rubric dimensions to use:\n{ctx.effective_rubric}\n\n"
        "Output (Markdown):\n"
        "## Calibration Rubric\n\n"
        "For each rubric dimension:\n"
        "### [Dimension name]\n"
        "_What we're evaluating:_ 1-2 sentence definition specific to this "
        f"function ({ctx.inputs.manager_role}).\n\n"
        "**Levels:**\n"
        "- **Exceeds**: what this looks like at this level\n"
        "- **Meets**: what 'on track for level' looks like\n"
        "- **Below**: what's missing or concerning\n\n"
        "Discipline:\n"
        "- Concrete behaviors, not adjectives ('ships features on the date "
        "committed and proactively flags slippage' beats 'reliable').\n"
        "- Tailored to the function. An engineer's 'Craft' looks different "
        "from a designer's.\n"
        "- 'Meets' should describe a fully-performing person at the level — "
        "not a low bar."
    )


def _build_writeups_prompt(ctx: _PerformanceReviewContext) -> str:
    promotion_block = (
        f"\n\nPromotion candidates this cycle:\n{ctx.inputs.promotion_candidates}"
        if ctx.inputs.promotion_candidates.strip()
        else ""
    )
    team_block = (
        f"\n\nTeam context:\n{ctx.inputs.team_context}"
        if ctx.inputs.team_context.strip()
        else ""
    )
    return (
        f"For a {ctx.inputs.manager_role}, draft a structured performance "
        f"review writeup for each direct report covering {ctx.inputs.review_period}.\n\n"
        f"Rubric:\n{ctx.effective_rubric}\n\n"
        f"Direct reports and the manager's observations:\n"
        f"{ctx.inputs.direct_reports}"
        f"{promotion_block}"
        f"{team_block}\n\n"
        "Output (Markdown):\n"
        "## Per-Report Writeups\n\n"
        "For each named person in the inputs:\n"
        "### [Name] — [Role], [Tenure]\n\n"
        "**Period summary:** 1-2 sentence framing of the person's "
        "contribution this period, in the manager's voice.\n\n"
        "**Strengths (with evidence):**\n"
        "- 2-3 strengths, each with a specific example FROM THE PROVIDED INPUTS\n\n"
        "**Growth areas (with evidence):**\n"
        "- 2-3 growth areas, each with a specific example FROM THE PROVIDED INPUTS\n\n"
        "**Rating direction (by dimension):**\n"
        "- Execution: [Exceeds / Meets / Below], 1-sentence rationale\n"
        "- Craft: [Exceeds / Meets / Below], 1-sentence rationale\n"
        "- (continue for all rubric dimensions)\n\n"
        "**Overall rating direction:** [Exceeds / Meets / Below], with manager "
        "to confirm in calibration.\n\n"
        "**Promotion readiness:** "
        "(Include this section ONLY if the person was listed as a promotion "
        "candidate.) Make the case for or against promotion this cycle. "
        "Be specific about what would make them ready if not yet.\n\n"
        "Strict discipline:\n"
        "- Use ONLY the observations the manager provided. Do not invent "
        "achievements, projects, or feedback that weren't in the inputs.\n"
        "- If a rubric dimension wasn't covered in the input observations, "
        "say '[Not enough signal in provided observations — manager to add]' "
        "rather than guessing.\n"
        "- Concrete language. 'Closed 5 customer escalations in Q2' beats "
        "'handled customer issues well'.\n"
        "- Don't soften or hedge — this is the manager's preparation, not the "
        "delivered review."
    )


def _build_calibration_prompt(ctx: _PerformanceReviewContext) -> str:
    return (
        "Now zoom out and draft a team-level calibration view based on the "
        f"per-report writeups for {ctx.inputs.review_period}.\n\n"
        f"Direct reports:\n{ctx.inputs.direct_reports}\n\n"
        "Output (Markdown):\n"
        "## Team-Level Calibration View\n\n"
        "### Distribution\n"
        "How the team is distributed across rating directions. Use a simple "
        "table or bullet list. Note if the distribution looks healthy or "
        "skewed (e.g., everyone 'Exceeds' is a calibration smell).\n\n"
        "### Patterns\n"
        "2-4 patterns across the team — what's consistently strong, what's "
        "consistently weak, what's specific to the role mix.\n\n"
        "### Promotion Readiness\n"
        "Summarize who's ready, who's close, who's not yet — naming each "
        "candidate explicitly.\n\n"
        "### Calibration Risks\n"
        "1-3 specific risks before the manager goes into cross-team "
        "calibration. Examples: 'rating drift toward Exceeds across the "
        "team', 'unclear delta between Meets and Exceeds on Craft', "
        "'recent reorg may have created unfair comparison baseline'.\n\n"
        "Strict discipline:\n"
        "- Honest about the distribution. Don't flatten patterns to be polite.\n"
        "- Use ONLY information from the inputs. Don't speculate.\n"
        "- If the team is small (<4 reports), some sections may be 'N/A — "
        "team too small for distribution analysis' and that's correct."
    )


def _build_talking_points_prompt(ctx: _PerformanceReviewContext) -> str:
    return (
        "Draft per-report talking points for the actual review conversations. "
        "These are for the manager's reference DURING the 1:1 — concise, "
        "specific, conversational.\n\n"
        f"Direct reports:\n{ctx.inputs.direct_reports}\n\n"
        "Output (Markdown):\n"
        "## Manager Talking Points\n\n"
        "For each named person:\n"
        "### [Name]\n\n"
        "**Lead with:** 1 sentence. The single most important thing to say "
        "first — usually a specific reinforcing or recognition point.\n\n"
        "**Wins to recognize specifically:** 2-3 bullets — name the specific "
        "work and the impact.\n\n"
        "**Growth conversation:** the 1-2 things to address, framed as "
        "questions or observations (not pronouncements). Examples: 'I noticed "
        "you handled X by Y — what made you go that direction?'\n\n"
        "**Career growth question:** 1 question to surface where this person "
        "wants to grow next.\n\n"
        "**Anticipated reactions:** 1-2 likely reactions the manager should "
        "be prepared for (defensive, surprised, asking about promotion, etc.).\n\n"
        "Discipline:\n"
        "- Use the manager's voice — first person, conversational.\n"
        "- No corporate-speak. 'You really moved the needle' is fine; "
        "'You demonstrated significant value' is not.\n"
        "- These are talking points, not a script."
    )


def _assemble_packet(ctx: _PerformanceReviewContext) -> str:
    parts: list[str] = [
        f"# Performance Review Prep Packet — {ctx.inputs.review_period}",
        f"*Manager: {ctx.inputs.manager_role}*",
        "",
        _ensure_heading(ctx.rubric_section, "## Calibration Rubric"),
        "",
        _ensure_heading(ctx.per_report, "## Per-Report Writeups"),
        "",
        _ensure_heading(ctx.calibration_view, "## Team-Level Calibration View"),
        "",
        _ensure_heading(ctx.talking_points, "## Manager Talking Points"),
        "",
        "---",
        "**Important:** This packet is a draft to accelerate the manager's "
        "preparation. The manager owns final ratings, final language, and "
        "final calibration decisions. Use the writeups as a starting point "
        "to challenge, refine, and replace — not as the delivered review.",
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
