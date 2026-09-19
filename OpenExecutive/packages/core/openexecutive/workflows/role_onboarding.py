"""Role onboarding workflow — generates a role-tailored welcome brief (and an
optional daily ramp drip) for a new hire, leaning on everything the system
already knows: company profile, departments, the people roster, and company-doc
RAG.

Mirrors the section-by-section shape of ``exec_search_brief`` but oriented to
ramp-up. Role context can come from an onboarding *plan* (the normal path —
``plan_id``), or from free-text inputs for an ad-hoc run. When a plan is given,
the generated brief, reading list, and ramp segments are written back onto it.
The lead specialist is resolved per role (department specialist_key → function
map → cso), so any role — exec or IC — gets a relevant lens.
"""
from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, Field

from openexecutive.knowledge.retriever import retrieve
from openexecutive.knowledge.store import ChromaDBStore
from openexecutive.memory.company_profile import CompanyProfile
from openexecutive.onboarding.profile_builder import load_or_create_profile
from openexecutive.orchestrator.router import route_to_specialist
from openexecutive.staff_onboarding import store as onboarding_store
from openexecutive.staff_onboarding.specialists import resolve_specialist
from openexecutive.workflows.base import (
    Workflow,
    WorkflowEvent,
    WorkflowSection,
    WorkflowStepDef,
)

logger = logging.getLogger(__name__)

_RAMP_MAX = 30  # safety cap on generated daily segments per run


class RoleOnboardingInput(BaseModel):
    """Inputs for the role-onboarding workflow.

    Supply ``plan_id`` to drive (and write back to) an existing onboarding plan;
    otherwise supply at least ``full_name`` + ``role`` for an ad-hoc brief.
    """

    plan_id: int | None = Field(
        default=None,
        description="Onboarding plan to generate for and write the brief back to.",
    )
    full_name: str = Field(
        default="", description="New hire's name (used when no plan_id).",
    )
    role: str = Field(default="", description="Role/title, e.g. 'Fractional CFO'.")
    function: str = Field(
        default="",
        description="Function the role sits in (engineering, sales, finance, …). "
        "Helps pick the lead specialist.",
    )
    focus: str = Field(default="", description="Optional one-line emphasis for the brief.")
    ramp_days: int | None = Field(
        default=None, ge=0, le=_RAMP_MAX,
        description="Number of daily ramp-drip messages to generate. None = use "
        "the plan template's value; 0 = force no drip; >0 = override the template.",
    )


class RoleOnboardingWorkflow(Workflow):
    name = "role_onboarding"
    title = "Role Onboarding"
    description = (
        "Generates a role-tailored onboarding brief for a new hire — company "
        "landscape, the state of their function, who's who, a 30/60/90 plan, "
        "and the questions to ask in week one — plus an optional daily ramp "
        "drip. Tailors via the role's domain specialist and writes the brief "
        "back onto the onboarding plan."
    )
    section = WorkflowSection.PEOPLE
    estimated_minutes = 4

    def input_model(self) -> type[BaseModel]:
        return RoleOnboardingInput

    def sample_inputs(self) -> dict[str, Any]:
        return {
            "full_name": "Priya Rao",
            "role": "Fractional CFO",
            "function": "finance",
            "focus": "Series B readiness",
            "ramp_days": 3,
        }

    def steps(self) -> list[WorkflowStepDef]:
        return [
            WorkflowStepDef(id="context", title="Load context",
                            description="Company profile, roster, role context, RAG."),
            WorkflowStepDef(id="company_landscape", title="Company landscape",
                            description="What the company is, market, priorities."),
            WorkflowStepDef(id="function_state", title="Function state",
                            description="Current state of the function this role owns."),
            WorkflowStepDef(id="people_map", title="People map",
                            description="Who's who and the key working relationships."),
            WorkflowStepDef(id="first_90", title="30/60/90 plan",
                            description="Prioritized first-90-days plan."),
            WorkflowStepDef(id="week_one", title="Week-one questions",
                            description="The sharp questions to ask in week one."),
            WorkflowStepDef(id="ramp", title="Ramp drip",
                            description="Optional per-day ramp messages."),
            WorkflowStepDef(id="assemble", title="Assemble brief",
                            description="Combine into one Markdown brief; save to plan."),
        ]

    async def run(
        self,
        inputs: BaseModel,
        store: ChromaDBStore,
    ) -> AsyncIterator[WorkflowEvent]:
        assert isinstance(inputs, RoleOnboardingInput)
        ctx = _Ctx(inputs)

        # ---- context -----------------------------------------------------
        yield WorkflowEvent(type="step_start", step_id="context", step_title="Load context")
        _load_context(ctx, store)
        if not ctx.full_name:
            yield WorkflowEvent(
                type="error",
                message="role_onboarding needs a plan_id or a full_name to run.",
            )
            return
        yield WorkflowEvent(
            type="step_done", step_id="context",
            summary=f"hire={ctx.full_name!r} role={ctx.role!r} specialist={ctx.specialist}",
        )

        company_ctx = _company_block(ctx.profile)

        # ---- company_landscape (cso) ------------------------------------
        yield WorkflowEvent(type="step_start", step_id="company_landscape",
                            step_title="Company landscape")
        ctx.company_landscape = await route_to_specialist(
            specialist_name="cso", query=_company_prompt(ctx),
            context=company_ctx, retrieved_knowledge=ctx.rag,
        )
        yield WorkflowEvent(type="step_done", step_id="company_landscape",
                            summary=_first_line(ctx.company_landscape))

        # ---- function_state (domain specialist) -------------------------
        yield WorkflowEvent(type="step_start", step_id="function_state",
                            step_title="Function state")
        ctx.function_state = await route_to_specialist(
            specialist_name=ctx.specialist, query=_function_prompt(ctx),
            context=company_ctx, retrieved_knowledge=ctx.rag,
        )
        yield WorkflowEvent(type="step_done", step_id="function_state",
                            summary=_first_line(ctx.function_state))

        # ---- people_map (chro) ------------------------------------------
        yield WorkflowEvent(type="step_start", step_id="people_map", step_title="People map")
        ctx.people_map = await route_to_specialist(
            specialist_name="chro", query=_people_prompt(ctx),
            context=company_ctx + "\n\n" + ctx.roster_block, retrieved_knowledge="",
        )
        yield WorkflowEvent(type="step_done", step_id="people_map",
                            summary=_first_line(ctx.people_map))

        # ---- first_90 (domain specialist) -------------------------------
        yield WorkflowEvent(type="step_start", step_id="first_90", step_title="30/60/90 plan")
        ctx.first_90 = await route_to_specialist(
            specialist_name=ctx.specialist, query=_first90_prompt(ctx),
            context=company_ctx, retrieved_knowledge=ctx.rag,
        )
        yield WorkflowEvent(type="step_done", step_id="first_90",
                            summary=_first_line(ctx.first_90))

        # ---- week_one (domain specialist) -------------------------------
        yield WorkflowEvent(type="step_start", step_id="week_one",
                            step_title="Week-one questions")
        ctx.week_one = await route_to_specialist(
            specialist_name=ctx.specialist, query=_weekone_prompt(ctx),
            context=company_ctx, retrieved_knowledge="",
        )
        yield WorkflowEvent(type="step_done", step_id="week_one",
                            summary=_first_line(ctx.week_one))

        # ---- ramp (optional) --------------------------------------------
        yield WorkflowEvent(type="step_start", step_id="ramp", step_title="Ramp drip")
        if ctx.ramp_days:
            raw = await route_to_specialist(
                specialist_name=ctx.specialist, query=_ramp_prompt(ctx),
                context=company_ctx, retrieved_knowledge="",
            )
            ctx.ramp_segments = _split_ramp(raw, ctx.ramp_days)
        yield WorkflowEvent(
            type="step_done", step_id="ramp",
            summary=f"{len(ctx.ramp_segments)} ramp segment(s)",
        )

        # ---- assemble ----------------------------------------------------
        yield WorkflowEvent(type="step_start", step_id="assemble", step_title="Assemble brief")
        artifact = _assemble(ctx)
        if ctx.plan_id is not None:
            # Only (re)write ramp fields when this run actually produced a drip,
            # so re-running just to refresh the brief can't wipe an in-progress
            # ramp's segments/index.
            ramp_kwargs: dict[str, Any] = {}
            if ctx.ramp_days and ctx.ramp_segments:
                ramp_kwargs = {"ramp_segments": ctx.ramp_segments, "ramp_next_index": 0}
            try:
                onboarding_store.update_plan(
                    ctx.plan_id,
                    brief_artifact=artifact,
                    reading_list=ctx.reading_list,
                    **ramp_kwargs,
                )
            except Exception:
                logger.exception("role_onboarding: failed to write brief to plan %s",
                                 ctx.plan_id)
        yield WorkflowEvent(type="step_done", step_id="assemble",
                            summary=f"{len(artifact)} chars; saved={ctx.plan_id is not None}")

        yield WorkflowEvent(
            type="result",
            data={
                "plan_id": ctx.plan_id,
                "specialist": ctx.specialist,
                "ramp_segments": ctx.ramp_segments,
                "reading_list": ctx.reading_list,
            },
        )
        yield WorkflowEvent(type="artifact", content=artifact)
        yield WorkflowEvent(type="done")


class _Ctx:
    def __init__(self, inputs: RoleOnboardingInput) -> None:
        self.inputs = inputs
        self.plan_id: int | None = inputs.plan_id
        self.full_name: str = inputs.full_name
        self.role: str = inputs.role
        self.function: str = inputs.function
        self.focus: str = inputs.focus
        # None until resolved in _load_context (caller value vs template vs 0).
        self.ramp_days: int | None = inputs.ramp_days
        self.department: str = ""
        self.start_date: str = ""
        self.profile: CompanyProfile | None = None
        self.specialist: str = "cso"
        self.rag: str = ""
        self.roster_block: str = ""
        self.reading_list: list[str] = []
        self.company_landscape: str = ""
        self.function_state: str = ""
        self.people_map: str = ""
        self.first_90: str = ""
        self.week_one: str = ""
        self.ramp_segments: list[str] = []


def _load_context(ctx: _Ctx, store: ChromaDBStore) -> None:
    """Resolve role context from the plan (if any) + company profile + roster."""
    if ctx.plan_id is not None:
        plan = onboarding_store.get_plan(ctx.plan_id)
        if plan is not None:
            ctx.full_name = plan.full_name or ctx.full_name
            ctx.role = plan.role or ctx.role
            ctx.start_date = plan.start_date
            if plan.template_name:
                tmpl = onboarding_store.get_template(plan.template_name)
                if tmpl is not None:
                    ctx.department = tmpl.department
                    # Caller value wins; fall back to the template's only when
                    # the caller didn't specify (None). An explicit 0 stays 0.
                    if ctx.ramp_days is None:
                        ctx.ramp_days = min(tmpl.ramp_days, _RAMP_MAX)

    # No value from caller or template → no drip.
    if ctx.ramp_days is None:
        ctx.ramp_days = 0

    try:
        ctx.profile = load_or_create_profile()
    except Exception:
        logger.exception("role_onboarding: load_or_create_profile failed")
        ctx.profile = None

    ctx.specialist = resolve_specialist(
        role=ctx.role, function=ctx.function, department=ctx.department,
    )

    try:
        ctx.rag = retrieve(
            query=f"onboarding ramp {ctx.role} {ctx.function} first 90 days",
            specialist_name=ctx.specialist, n_builtin=5, n_company=3, store=store,
        )
    except Exception:
        logger.exception("role_onboarding: retrieve failed")
        ctx.rag = ""

    ctx.roster_block = _roster_block()
    ctx.reading_list = _reading_list(ctx.specialist, store)


def _roster_block() -> str:
    try:
        from openexecutive.people.store import list_people

        people = list_people()
    except Exception:
        logger.exception("role_onboarding: list_people failed")
        return ""
    lines: list[str] = []
    for p in people[:50]:
        role = f" — {p.role}" if p.role else ""
        depts = f" [{', '.join(p.department_slugs)}]" if p.department_slugs else ""
        lines.append(f"- {p.full_name}{role}{depts}")
    if not lines:
        return ""
    return "CURRENT TEAM:\n" + "\n".join(lines)


def _reading_list(specialist: str, store: ChromaDBStore) -> list[str]:
    """Best-effort: distinct company-doc filenames relevant to this role."""
    try:
        results = store.query(
            query_text=f"onboarding {specialist} role overview",
            collection=ChromaDBStore.COMPANY_COLLECTION,
            n_results=8,
        )
    except Exception:
        logger.exception("role_onboarding: reading-list query failed")
        return []
    seen: list[str] = []
    for item in results or []:
        name = (item.get("metadata") or {}).get("filename")
        if name and name not in seen:
            seen.append(name)
    return seen[:5]


def _company_block(profile: CompanyProfile | None) -> str:
    if profile is None or profile.is_empty():
        return ""
    return profile.to_prompt_block()


def _focus_line(ctx: _Ctx) -> str:
    return f"\n\nEmphasis for this hire: {ctx.focus}" if ctx.focus else ""


def _company_prompt(ctx: _Ctx) -> str:
    return (
        f"A new hire — {ctx.full_name}, joining as {ctx.role or 'a new team member'} — "
        "needs to understand this company fast. Write the **Company Landscape** "
        "section of their onboarding brief.{focus}\n\n"
        "Output (Markdown):\n"
        "## Company Landscape\n"
        "### What we do & where we are\n2-4 sentences: the business, stage, model.\n"
        "### Market & competition\nThe competitive picture they should hold.\n"
        "### Strategic priorities\nThe few company priorities their work ladders up to.\n"
    ).replace("{focus}", _focus_line(ctx))


def _function_prompt(ctx: _Ctx) -> str:
    return (
        f"You are the functional leader closest to {ctx.full_name}'s role "
        f"({ctx.role or 'this role'}). Write the **State of the Function** they're "
        "inheriting — be concrete and honest.{focus}\n\n"
        "Output (Markdown):\n"
        "## State of Your Function\n"
        "### What's working\n2-4 bullets.\n"
        "### What's broken or unfinished\n2-4 bullets.\n"
        "### The metrics that matter\nThe few numbers they should track from day one.\n"
    ).replace("{focus}", _focus_line(ctx))


def _people_prompt(ctx: _Ctx) -> str:
    return (
        f"Using the team roster provided, write the **People Map** for "
        f"{ctx.full_name} ({ctx.role or 'new hire'}): who they'll work with most "
        "and why. If the roster is empty, give the archetypal stakeholders for "
        "this role instead.\n\n"
        "Output (Markdown):\n"
        "## People Map\n"
        "### Key relationships\n"
        "Bullet list: each person/role and what to align with them on.\n"
        "### First intro 1:1s to schedule\nWho to meet in week one, and why.\n"
    )


def _first90_prompt(ctx: _Ctx) -> str:
    return (
        f"Draft a prioritized **30/60/90-Day Plan** for {ctx.full_name} as "
        f"{ctx.role or 'the new hire'}, grounded in the company's strategic "
        "priorities and the state of their function.{focus}\n\n"
        "Output (Markdown):\n"
        "## 30 / 60 / 90 Day Plan\n"
        "### First 30 days — learn & stabilize\n3-5 bullets.\n"
        "### Days 31-60 — own & improve\n3-5 bullets.\n"
        "### Days 61-90 — deliver\n3-5 bullets, each with a visible outcome.\n"
    ).replace("{focus}", _focus_line(ctx))


def _weekone_prompt(ctx: _Ctx) -> str:
    return (
        f"List the sharp **Questions {ctx.full_name} Should Ask in Week One** — "
        "the ones that surface how things really work here, not generic ones.\n\n"
        "Output (Markdown):\n"
        "## Questions to Ask in Week One\n"
        "5-8 specific questions, each with one line on why it matters.\n"
    )


def _ramp_prompt(ctx: _Ctx) -> str:
    return (
        f"Write a {ctx.ramp_days}-day **ramp drip** for {ctx.full_name} "
        f"({ctx.role or 'new hire'}): one short, friendly daily message (2-4 "
        "sentences) they'll receive on each of their first business days. Each "
        "should give one concrete thing to do or learn that day, building on the "
        "prior days.\n\n"
        f"Output EXACTLY {ctx.ramp_days} messages, each on its own block, prefixed "
        "with 'DAY n:' (e.g. 'DAY 1:'). No other headers."
    )


_RAMP_RE = re.compile(r"^\s*DAY\s*\d+\s*:\s*", re.IGNORECASE | re.MULTILINE)


def _split_ramp(raw: str, expected: int) -> list[str]:
    """Split the model's ramp output into per-day segments.

    Primary parse splits on the ``DAY n:`` markers; if that yields nothing
    usable, fall back to splitting on blank lines. Either way the result is
    capped at ``expected`` so a chatty model can't over-produce.
    """
    if not raw or not raw.strip():
        return []
    # Use the DAY-marker split when the markers are actually present (so a valid
    # single-day drip isn't mistaken for a parse failure); otherwise fall back to
    # paragraph splitting.
    if _RAMP_RE.search(raw):
        parts = [p.strip() for p in _RAMP_RE.split(raw) if p.strip()]
    else:
        parts = [p.strip() for p in re.split(r"\n\s*\n", raw) if p.strip()]
    return parts[:expected]


def _first_line(text: str, max_len: int = 140) -> str:
    if not text:
        return "(empty)"
    line = text.strip().split("\n", 1)[0].lstrip("# ").strip()
    return line[: max_len - 1] + "…" if len(line) > max_len else line


def _ensure_heading(text: str, expected_heading: str) -> str:
    stripped = (text or "").strip()
    if not stripped:
        return f"{expected_heading}\n\n_(No content generated for this section.)_"
    first_line = stripped.split("\n", 1)[0]
    if first_line.startswith("##"):
        return stripped
    return f"{expected_heading}\n\n{stripped}"


def _assemble(ctx: _Ctx) -> str:
    title_role = f" — {ctx.role}" if ctx.role else ""
    parts = [
        f"# Onboarding Brief: {ctx.full_name}{title_role}",
        "",
        _ensure_heading(ctx.company_landscape, "## Company Landscape"),
        "",
        _ensure_heading(ctx.function_state, "## State of Your Function"),
        "",
        _ensure_heading(ctx.people_map, "## People Map"),
        "",
        _ensure_heading(ctx.first_90, "## 30 / 60 / 90 Day Plan"),
        "",
        _ensure_heading(ctx.week_one, "## Questions to Ask in Week One"),
    ]
    if ctx.reading_list:
        parts += ["", "## Suggested Reading", ""]
        parts += [f"- {name}" for name in ctx.reading_list]
    parts += [
        "",
        "---",
        "*Drafted by Open Executive from your company context. Review with the "
        "hiring manager before sharing.*",
    ]
    return "\n".join(parts).strip() + "\n"


__all__ = ["RoleOnboardingInput", "RoleOnboardingWorkflow"]
