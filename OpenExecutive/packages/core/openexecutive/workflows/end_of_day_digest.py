"""End-of-day digest workflow — a short proactive recap to the principal.

Renders a one-screen Markdown summary covering:
  • What OE did today on its own initiative
  • What's still pending / awaiting decisions
  • What's at risk for tomorrow
  • One thing the principal might sleep on before deciding

The scheduler fires a `principal_brief_eod` action once per day at the
configured time (default 18:00 UTC) which runs this workflow and DMs
the artifact to the principal via their preferred channel. Manual
invocation through the workflow API is also supported for testing.

Target audience is hardcoded to the principal — see the
`## Choosing Who to Tell` section in the persona for why EoD digests
are a personal-rhythm artifact rather than an org-coordination
broadcast.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from openexecutive.knowledge.store import ChromaDBStore
from openexecutive.workflows.base import (
    Workflow,
    WorkflowEvent,
    WorkflowSection,
    WorkflowStepDef,
)

logger = logging.getLogger(__name__)


class EndOfDayDigestInput(BaseModel):
    period_label: str = Field(
        default="",
        description="Human-readable period label (e.g. '2026-05-26'). Auto-filled when blank.",
    )


_EOD_DIGEST_SYSTEM = (
    "You are the user's Executive. You are writing the end-of-day "
    "digest — a short message the principal reads before logging off. "
    "Audience is the principal alone (DM only); peer-to-peer tone.\n\n"
    "Output ≤200 words of Markdown with these sections, in order, each "
    "only included when there is real content:\n"
    "  1. **What I did today** — actions you took without prompting "
    "(DMs sent, follow-ups scheduled, workflows queued, alerts "
    "flagged). One bullet per item, terse.\n"
    "  2. **Still pending** — proposals or workflows waiting on someone "
    "(name the person and what's blocking).\n"
    "  3. **At risk tomorrow** — what might trip if no action happens "
    "overnight or first-thing.\n"
    "  4. **Sleep on this** — at most ONE open question worth the "
    "principal mulling overnight. Skip if there isn't one.\n\n"
    "Skip headers for empty sections. If the day was genuinely quiet, "
    "output one line: 'Quiet day — nothing carrying forward.'"
)


def _render_eod_context(
    *,
    period_label: str,
    today_data: dict[str, Any],
    activity: list[dict[str, Any]],
) -> str:
    """Pack /today + activity into the user-turn block.

    Same structure as morning_brief's renderer but framed as end-of-day
    state. Activity items are explicitly labeled as "today's actions"
    since this is the recap, not the look-ahead.
    """
    parts: list[str] = [f"PERIOD: {period_label}\n"]

    if activity:
        parts.append("WHAT OE DID TODAY (most recent first):")
        for item in activity[:20]:
            parts.append(
                f"- [{item.get('at', '')[:10]}] {item.get('kind', 'action')}: "
                f"{item.get('summary', '')[:140]}"
            )
        parts.append("")

    proposals = today_data.get("proposals", [])
    if proposals:
        parts.append("STILL AWAITING DECISION:")
        for p in proposals[:10]:
            parts.append(f"- {p.get('headline', '')[:160]}")
        parts.append("")

    depts = today_data.get("departments", [])
    at_risk = [d for d in depts if d.get("at_risk_count", 0) or d.get("off_track_count", 0)]
    if at_risk:
        parts.append("DEPARTMENTS WITH RISK CARRIED FORWARD:")
        for d in at_risk:
            parts.append(
                f"- {d['title']}: at_risk={d.get('at_risk_count', 0)} "
                f"off_track={d.get('off_track_count', 0)}"
            )
        parts.append("")

    people = today_data.get("people", [])
    awaiting = [p for p in people if p.get("awaiting_count", 0)]
    if awaiting:
        parts.append("PEOPLE STILL WAITING ON YOU:")
        for p in awaiting:
            parts.append(
                f"- {p.get('full_name', '')}: "
                f"{p.get('awaiting_count', 0)} awaiting "
                f"(SLA {p.get('soonest_sla_at', 'unset')})"
            )

    if len(parts) == 1:
        parts.append("(No actions taken, no pending proposals, no at-risk goals today.)")

    return "\n".join(parts)


class EndOfDayDigestWorkflow(Workflow):
    name = "end_of_day_digest"
    title = "End-of-Day Digest"
    description = (
        "A short proactive recap for the principal: what OE did today, "
        "what's still pending, what's at risk for tomorrow. Fires "
        "automatically each evening via the scheduler; can also be "
        "invoked manually."
    )
    section = WorkflowSection.OPERATING
    estimated_minutes = 1

    def input_model(self) -> type[BaseModel]:
        return EndOfDayDigestInput

    def steps(self) -> list[WorkflowStepDef]:
        return [
            WorkflowStepDef(
                id="load_context",
                title="Gather today's actions and pending state",
                description="Pull today's OE activity, pending proposals, and at-risk goals.",
            ),
            WorkflowStepDef(
                id="synthesize",
                title="Synthesize the digest",
                description="Render a ≤200-word EoD digest in the Executive's voice.",
            ),
        ]

    async def run(
        self,
        inputs: BaseModel,
        store: ChromaDBStore,
    ) -> AsyncIterator[WorkflowEvent]:
        assert isinstance(inputs, EndOfDayDigestInput)
        period = inputs.period_label or datetime.now(UTC).strftime("%Y-%m-%d")

        yield WorkflowEvent(
            type="step_start",
            step_id="load_context",
            step_title="Gather today's actions and pending state",
        )

        from openexecutive.api.routes import today as today_route

        try:
            today_response = today_route._build_today()
            today_data = today_response.model_dump()
        except Exception:
            logger.exception("eod_digest: /today aggregation failed")
            today_data = {"departments": [], "people": [], "proposals": []}

        try:
            activity_response = today_route._build_activity(limit=30)
            activity = [item.model_dump() for item in activity_response.items]
        except Exception:
            logger.exception("eod_digest: /today/activity aggregation failed")
            activity = []

        yield WorkflowEvent(
            type="step_done",
            step_id="load_context",
            summary=(
                f"activity={len(activity)} "
                f"proposals={len(today_data['proposals'])} "
                f"depts={len(today_data['departments'])}"
            ),
        )

        yield WorkflowEvent(
            type="step_start",
            step_id="synthesize",
            step_title="Synthesize the digest",
        )

        from openexecutive.agents.utility_fast import get_fast_model
        from openexecutive.providers import get_provider

        user_content = _render_eod_context(
            period_label=period, today_data=today_data, activity=activity
        )

        try:
            model = get_fast_model()
            response = await get_provider(model).messages_create(
                model=model,
                max_tokens=600,
                system=_EOD_DIGEST_SYSTEM,
                messages=[{"role": "user", "content": user_content}],
            )
            text_blocks = [b for b in response.content if getattr(b, "type", "") == "text"]
            artifact_text = text_blocks[0].text.strip() if text_blocks else ""
        except Exception as exc:
            logger.exception("eod_digest: synthesis failed")
            yield WorkflowEvent(type="error", message=f"Synthesis failed: {exc}")
            return

        if not artifact_text:
            artifact_text = "Quiet day — nothing carrying forward."

        yield WorkflowEvent(
            type="step_done",
            step_id="synthesize",
            summary=artifact_text.split("\n", 1)[0][:160],
        )

        yield WorkflowEvent(type="artifact", content=artifact_text)
        yield WorkflowEvent(type="done")

    def sample_inputs(self) -> dict[str, Any] | None:
        return {"period_label": ""}


__all__ = ["EndOfDayDigestWorkflow", "EndOfDayDigestInput"]
