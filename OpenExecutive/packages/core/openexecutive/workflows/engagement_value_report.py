"""Engagement value report — the renewal artifact for fractional work.

A client-facing summary of what the executive actually did for one client
over a period: decisions supported, initiatives advanced, deliverables
produced, follow-through, monitoring. Unlike the form-driven workflows
(investor_update, mbr), the substance here is **read from the database**, not
typed by the user — the audit/memory/workflow trail IS the evidence, which is
exactly why no external tool can produce this report.

Multi-client aware: with no ``client_slug`` it reports on the live company
(the active client, or a plain single-company install). With a slug it reads
a parked slot's ``state.db`` read-only — no activation needed, same mechanism
as the practice cockpit. The single LLM step (board_comms) only narrates the
gathered facts; every list and count in the artifact is deterministic.

V1 trigger is deliberately human-initiated (cockpit/today renewal countdowns,
chat ``run_workflow``, /jobs): scheduled_actions swap with the client, so a
renewal-timed row for a parked client would never fire. Auto-generation
belongs to the overnight-rotation phase.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field

from openexecutive.clients.engagement_activity import (
    EngagementActivity,
    gather_engagement_activity,
)
from openexecutive.knowledge.store import ChromaDBStore
from openexecutive.orchestrator.router import route_to_specialist
from openexecutive.workflows.base import (
    Workflow,
    WorkflowEvent,
    WorkflowSection,
    WorkflowStepDef,
)

_DEFAULT_PERIOD_DAYS = 90


class EngagementValueReportInput(BaseModel):
    """Inputs for the Engagement Value Report workflow."""

    client_slug: str = Field(
        default="",
        description=(
            "Client slot to report on. Leave empty for the live company "
            "(the active client, or the only company on a single-company "
            "install). Parked clients are read from their slot without "
            "activating them."
        ),
        examples=["meridian_solar"],
    )
    period_start: str = Field(
        default="",
        description=(
            "ISO date the period starts. Empty = the engagement_start from "
            "the client's details, else 90 days back."
        ),
        examples=["2026-03-01"],
    )
    period_end: str = Field(
        default="",
        description="ISO date the period ends. Empty = today.",
        examples=["2026-06-01"],
    )
    audience_note: str = Field(
        default="",
        description=(
            "Optional steer for the narrative — who reads this and why "
            "(e.g. 'for the renewal call with Dana')."
        ),
    )


class EngagementValueReportWorkflow(Workflow):
    name = "engagement_value_report"
    title = "Engagement Value Report"
    description = (
        "Client-facing summary of what the executive did over a period — "
        "decisions supported, initiatives advanced, deliverables produced, "
        "follow-through, and monitoring — read from the engagement's own "
        "record, not typed in. Built for renewal conversations."
    )
    section = WorkflowSection.OPERATING
    estimated_minutes = 2

    def input_model(self) -> type[BaseModel]:
        return EngagementValueReportInput

    def sample_inputs(self) -> dict[str, Any]:
        return {
            "client_slug": "",
            "period_start": "",
            "period_end": "",
            "audience_note": "For the quarterly review call with the client CEO.",
        }

    def steps(self) -> list[WorkflowStepDef]:
        return [
            WorkflowStepDef(
                id="context",
                title="Resolve engagement",
                description="Client slot, engagement details, and reporting period.",
            ),
            WorkflowStepDef(
                id="gather",
                title="Gather the record",
                description=(
                    "Decisions, initiatives, deliverables, follow-through, and "
                    "monitoring from the engagement's own database."
                ),
            ),
            WorkflowStepDef(
                id="narrative",
                title="Write the summary",
                description="Board-comms voiced executive summary of the gathered facts.",
            ),
            WorkflowStepDef(
                id="assemble",
                title="Assemble the report",
                description="Deterministic sections + narrative into one Markdown artifact.",
            ),
        ]

    async def run(
        self,
        inputs: BaseModel,
        store: ChromaDBStore,
    ) -> AsyncIterator[WorkflowEvent]:
        assert isinstance(inputs, EngagementValueReportInput)

        # ── 1. context ───────────────────────────────────────────────────
        yield WorkflowEvent(
            type="step_start", step_id="context", step_title="Resolve engagement"
        )
        try:
            ctx = _resolve_context(inputs)
        except _ContextError as exc:
            yield WorkflowEvent(type="error", message=str(exc))
            return
        yield WorkflowEvent(
            type="step_done",
            step_id="context",
            summary=(
                f"{ctx['display_name']} — {ctx['period_start'][:10]} to "
                f"{ctx['period_end'][:10]}"
                + (" (parked slot, read-only)" if ctx["parked"] else "")
            ),
        )

        # ── 2. gather ────────────────────────────────────────────────────
        yield WorkflowEvent(
            type="step_start", step_id="gather", step_title="Gather the record"
        )
        activity = gather_engagement_activity(
            ctx["db_path"],
            ctx["period_start"],
            ctx["period_end"],
            read_only=ctx["parked"],
        )
        yield WorkflowEvent(
            type="step_done",
            step_id="gather",
            summary=(
                f"{len(activity.decisions)} decisions, "
                f"{len(activity.initiatives)} initiatives, "
                f"{len(activity.deliverables)} deliverables, "
                f"{activity.followups_completed} follow-ups completed."
            ),
        )

        # ── 3. narrative ─────────────────────────────────────────────────
        yield WorkflowEvent(
            type="step_start", step_id="narrative", step_title="Write the summary"
        )
        if activity.is_empty():
            narrative = (
                "No recorded activity in this period. This report reflects the "
                "engagement record as captured; if work happened outside the "
                "system, it is not shown here."
            )
        else:
            narrative = await route_to_specialist(
                specialist_name="board_comms",
                query=_build_narrative_prompt(ctx, activity),
                context=ctx["company_context"],
                retrieved_knowledge="",
            )
        yield WorkflowEvent(
            type="step_done", step_id="narrative", summary=_first_line(narrative)
        )

        # ── 4. assemble ──────────────────────────────────────────────────
        yield WorkflowEvent(
            type="step_start", step_id="assemble", step_title="Assemble the report"
        )
        artifact = _assemble(ctx, activity, narrative)
        yield WorkflowEvent(type="step_done", step_id="assemble", summary="Report assembled.")
        yield WorkflowEvent(type="artifact", content=artifact)


class _ContextError(ValueError):
    pass


def _resolve_context(inputs: EngagementValueReportInput) -> dict[str, Any]:
    """Resolve the target DB, profile, engagement meta, and period bounds."""
    from openexecutive.clients.slots import (
        ClientSlotError,
        _episodic_db_path,
        _read_meta,
        _require_slot,
        get_active_client,
    )
    from openexecutive.config import get_settings
    from openexecutive.memory.company_profile import CompanyProfile
    from openexecutive.onboarding.profile_builder import load_or_create_profile

    settings = get_settings()
    slug = (inputs.client_slug or "").strip()
    active = get_active_client(settings)

    meta: dict[str, Any] = {}
    if slug and slug != active:
        # Parked slot — read everything from the slot directory, in place.
        try:
            slot = _require_slot(settings, slug)
        except ClientSlotError as exc:
            raise _ContextError(str(exc)) from exc
        meta = _read_meta(slot)
        db_path = slot / "state.db"
        if not db_path.exists():
            raise _ContextError(
                f"Client {slug!r} has never been activated — there is no "
                "engagement record to report on yet."
            )
        profile_path = slot / "profile.yaml"
        profile = (
            CompanyProfile.load_from_yaml(profile_path)
            if profile_path.exists()
            else CompanyProfile()
        )
        display_name = meta.get("display_name") or profile.name or slug
        parked = True
    else:
        # Live company: the active client (with its meta) or a plain
        # single-company install (no meta — the header degrades gracefully).
        if active is not None:
            from openexecutive.clients.slots import _slot_dir

            meta = _read_meta(_slot_dir(settings, active))
        db_path = _episodic_db_path()
        profile = load_or_create_profile()
        display_name = meta.get("display_name") or profile.name or "the company"
        parked = False

    now = datetime.now(UTC)
    period_end = (inputs.period_end or "").strip() or now.date().isoformat()
    period_start = (inputs.period_start or "").strip()
    if not period_start:
        period_start = (meta.get("engagement_start") or "").strip()
    if not period_start:
        period_start = (now - timedelta(days=_DEFAULT_PERIOD_DAYS)).date().isoformat()
    # End bound is inclusive through the whole final day.
    period_end_bound = f"{period_end}T23:59:59" if len(period_end) == 10 else period_end

    profile_bits = [b for b in (profile.industry, profile.stage) if b]
    company_context = (
        f"Company: {display_name}"
        + (f" ({' · '.join(profile_bits)})" if profile_bits else "")
        + (f". Engagement role: {meta.get('role')}." if meta.get("role") else "")
    )

    return {
        "display_name": display_name,
        "db_path": db_path,
        "parked": parked,
        "meta": meta,
        "company_context": company_context,
        "period_start": period_start,
        "period_end": period_end_bound,
        "period_end_label": period_end,
        "audience_note": inputs.audience_note.strip(),
    }


def _build_narrative_prompt(ctx: dict[str, Any], activity: EngagementActivity) -> str:
    facts = activity.model_dump()
    return (
        "Write the executive summary for a client-facing engagement value "
        f"report covering {ctx['period_start'][:10]} to "
        f"{ctx['period_end_label']}. 2-3 short paragraphs, measured and "
        "confident — a senior advisor reporting to a client, not marketing "
        "copy.\n\n"
        "Use ONLY the facts below. Do not invent metrics, outcomes, or work "
        "that is not listed. If a category is empty, simply don't mention "
        "it.\n\n"
        + (f"Audience: {ctx['audience_note']}\n\n" if ctx["audience_note"] else "")
        + f"Recorded activity (JSON):\n{facts}"
    )


def _assemble(
    ctx: dict[str, Any], activity: EngagementActivity, narrative: str
) -> str:
    meta = ctx["meta"]
    lines: list[str] = []
    lines.append(f"# Engagement Value Report — {ctx['display_name']}")
    header_bits = []
    if meta.get("role"):
        header_bits.append(str(meta["role"]))
    header_bits.append(
        f"Period: {ctx['period_start'][:10]} – {ctx['period_end_label']}"
    )
    header_bits.append(
        f"Prepared: {datetime.now(UTC).date().isoformat()}"
    )
    lines.append("*" + " · ".join(header_bits) + "*")
    lines.append("")
    lines.append("## Executive summary")
    lines.append(narrative.strip())

    if activity.decisions:
        lines.append("")
        lines.append("## Decisions supported" + _of_total(activity.decisions, activity.decisions_total))
        for d in activity.decisions:
            suffix = f" — {d.outcome}" if d.outcome else ""
            domain = f" ({d.domain})" if d.domain else ""
            lines.append(f"- {d.timestamp[:10]}{domain}: {d.summary}{suffix}")

    if activity.initiatives:
        lines.append("")
        lines.append("## Initiatives advanced" + _of_total(activity.initiatives, activity.initiatives_total))
        for i in activity.initiatives:
            status = f" [{i.status}]" if i.status else ""
            summary = f" — {i.summary}" if i.summary else ""
            lines.append(f"- {i.title}{status}{summary}")

    if activity.deliverables:
        lines.append("")
        lines.append("## Deliverables produced" + _of_total(activity.deliverables, activity.deliverables_total))
        for w in activity.deliverables:
            lines.append(f"- {w.created_at[:10]}: {w.title}")

    follow_bits = []
    if activity.followups_completed:
        follow_bits.append(f"{activity.followups_completed} follow-ups completed")
    if activity.advice_count:
        domains = ", ".join(sorted(activity.advice_by_domain))
        follow_bits.append(
            f"{activity.advice_count} advisory consultations ({domains})"
        )
    if follow_bits:
        lines.append("")
        lines.append("## Follow-through")
        lines.extend(f"- {b}" for b in follow_bits)

    if activity.alerts_handled:
        lines.append("")
        lines.append("## Monitoring")
        lines.append(
            f"- {activity.alerts_handled} external signals and alerts triaged "
            "during the period"
        )

    lines.append("")
    lines.append("## Looking ahead")
    if activity.followups_pending:
        # Point-in-time, not period activity — that's why it lives here and
        # is excluded from is_empty(): "in flight now" is forward-looking.
        lines.append(
            f"- {activity.followups_pending} follow-ups currently in flight"
        )
    if meta.get("renewal_date"):
        lines.append(f"- Engagement renewal/review: {meta['renewal_date']}")
    lines.append(
        "- This report is generated from the engagement's own record "
        "(decisions, deliverables, and follow-through as captured in the "
        "system)."
    )
    return "\n".join(lines)


def _of_total(listed: list[Any], total: int) -> str:
    """' (showing N of M)' suffix when the listed items were capped."""
    if total > len(listed):
        return f" (showing {len(listed)} of {total})"
    return ""


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()[:160]
    return ""
