"""Morning brief workflow — a short proactive briefing to the principal.

Renders a one-screen Markdown summary covering:
  • At-risk department goals
  • Proposals awaiting the principal's decision
  • Anything OE acted on since the last brief
  • The top decision the principal needs to make today

The scheduler fires a `principal_brief_morning` action once per day at
the configured time (default 08:00 UTC) which runs this workflow and
DMs the artifact to the principal via their preferred channel. The
workflow can also be triggered manually through the workflow API for
testing or to re-send.

Target audience is hardcoded to the principal — this is a
personal-rhythm artifact, not org-coordination. See the
`## Choosing Who to Tell` section in the persona for the broader
audience-selection rules.
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


class MorningBriefInput(BaseModel):
    """Inputs for a morning brief run.

    Both fields are optional — the workflow defaults the period to
    today's date so the scheduler can fire it with no arguments.
    """

    period_label: str = Field(
        default="",
        description="Human-readable period label (e.g. '2026-05-26'). Auto-filled when blank.",
    )


# Narrative synthesis (system prompt + context render + LLM call) is shared
# with the on-page briefing header via openexecutive.briefing.narrative, so
# both surfaces tell the same story in the same voice.


class MorningBriefWorkflow(Workflow):
    name = "morning_brief"
    title = "Morning Brief"
    description = (
        "A short proactive briefing for the principal: what changed "
        "overnight, what needs them today, what's at risk, the top "
        "decision to make. Fires automatically each morning via the "
        "scheduler; can also be invoked manually."
    )
    section = WorkflowSection.OPERATING
    estimated_minutes = 1

    def input_model(self) -> type[BaseModel]:
        return MorningBriefInput

    def steps(self) -> list[WorkflowStepDef]:
        return [
            WorkflowStepDef(
                id="load_context",
                title="Gather today's state",
                description="Pull /today data, recent OE activity, and pending proposals.",
            ),
            WorkflowStepDef(
                id="synthesize",
                title="Synthesize the brief",
                description="Render a ≤200-word morning brief in the Executive's voice.",
            ),
        ]

    async def run(
        self,
        inputs: BaseModel,
        store: ChromaDBStore,
    ) -> AsyncIterator[WorkflowEvent]:
        assert isinstance(inputs, MorningBriefInput)
        period = inputs.period_label or datetime.now(UTC).strftime("%Y-%m-%d")

        # ------------------------------------------------------------------ #
        # Step 1: gather context
        # ------------------------------------------------------------------ #
        yield WorkflowEvent(
            type="step_start",
            step_id="load_context",
            step_title="Gather today's state",
        )

        from openexecutive.api.routes import today as today_route

        try:
            today_response = today_route._build_today()
            today_data = today_response.model_dump()
            # Focus the brief on action items — drop monitoring/watchlist noise
            # so it doesn't land in the DM's "Needs you" section (same exclusion
            # the /today narrative makes).
            today_data["proposals"] = [
                p for p in today_data["proposals"]
                if p.get("category", "action") == "action"
            ]
        except Exception:
            logger.exception("morning_brief: /today aggregation failed")
            today_data = {"departments": [], "people": [], "proposals": []}

        try:
            activity_response = today_route._build_activity(limit=20)
            activity = [item.model_dump() for item in activity_response.items]
        except Exception:
            logger.exception("morning_brief: /today/activity aggregation failed")
            activity = []

        yield WorkflowEvent(
            type="step_done",
            step_id="load_context",
            summary=(
                f"depts={len(today_data['departments'])} "
                f"proposals={len(today_data['proposals'])} "
                f"activity={len(activity)}"
            ),
        )

        # ------------------------------------------------------------------ #
        # Step 2: synthesize
        # ------------------------------------------------------------------ #
        yield WorkflowEvent(
            type="step_start",
            step_id="synthesize",
            step_title="Synthesize the brief",
        )

        from openexecutive.briefing.narrative import synthesize_briefing_narrative

        try:
            # standalone=True → the enumerated DM brief (no cards beside it),
            # not the /today header synthesis.
            artifact_text = await synthesize_briefing_narrative(
                today_data=today_data, activity=activity, period_label=period,
                standalone=True,
            )
        except Exception as exc:
            logger.exception("morning_brief: synthesis failed")
            yield WorkflowEvent(type="error", message=f"Synthesis failed: {exc}")
            return

        if not artifact_text:
            # Matches the shared synthesizer's quiet-day line so the empty
            # fallback reads identically to a model-produced quiet brief.
            artifact_text = "Quiet right now — nothing pressing."

        yield WorkflowEvent(
            type="step_done",
            step_id="synthesize",
            summary=artifact_text.split("\n", 1)[0][:160],
        )

        # ------------------------------------------------------------------ #
        # Artifact + done
        # ------------------------------------------------------------------ #
        yield WorkflowEvent(
            type="artifact",
            content=artifact_text,
        )
        yield WorkflowEvent(type="done")

    def sample_inputs(self) -> dict[str, Any] | None:
        return {"period_label": ""}


# Forward-compat: this workflow is used both manually (via the workflow API
# / form) and from the scheduler. The scheduler invocation path lives in
# `openexecutive.scheduler.runner._execute_action` (see the
# `principal_brief_morning` branch).
__all__ = ["MorningBriefWorkflow", "MorningBriefInput"]
