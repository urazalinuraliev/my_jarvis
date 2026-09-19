"""Chat tool that delegates a marketing workflow to the integrated CrewAI crew.

The Executive calls ``run_crew`` when the principal asks for a multi-agent
marketing deliverable — a meeting briefing, a competitive analysis, or an
Instagram content strategy. The tool fans out to the CrewAI adapter, which
runs the underlying crew (meeting_prep or instagram) and returns a
structured summary. The Executive then describes the deliverable to the
principal in chat.

Mirrors the JSON-in / JSON-out pattern of the other orchestrator tools.
"""
from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from openexecutive.audit import log_event as audit_log
from openexecutive.integrations.adapters import AgentResult
from openexecutive.workflows.persistence import (
    complete_run,
    create_run,
    fail_run,
)

logger = logging.getLogger(__name__)


RUN_CREW_TOOL: dict[str, Any] = {
    "name": "run_crew",
    "description": (
        "Delegate a multi-agent marketing workflow to the integrated CrewAI "
        "crew. Two crews are available:\n"
        "- 'meeting_prep': research + industry analysis + strategy + briefing "
        "for an upcoming meeting. Use when the principal asks for a briefing, "
        "talking points, or competitive intel on meeting participants.\n"
        "- 'instagram': market research + content strategy + visual creation "
        "+ copywriting + final report for an Instagram content calendar. Use "
        "when the principal asks for a content plan, captions, or a social "
        "media strategy.\n"
        "The crew runs its full agent pipeline and returns a summary of the "
        "deliverable plus any artifacts it produced."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "crew": {
                "type": "string",
                "enum": ["meeting_prep", "instagram"],
                "description": "Which CrewAI crew to run.",
            },
            "task": {
                "type": "string",
                "description": (
                    "The task for the crew. For meeting_prep this is the "
                    "meeting topic/participants; for instagram this is the "
                    "content topic or theme."
                ),
            },
            "context": {
                "type": "string",
                "description": (
                    "Optional conversation/company context the crew should "
                    "consider (e.g. brand voice, recent campaigns, audience)."
                ),
            },
        },
        "required": ["crew", "task"],
    },
}


async def handle_run_crew(tool_input: dict[str, Any]) -> str:
    crew = str(tool_input.get("crew", "instagram")).strip().lower()
    task = str(tool_input.get("task", "")).strip()
    context = str(tool_input.get("context", "")).strip()

    if not task:
        return _err("run_crew: 'task' is required")
    if crew not in ("meeting_prep", "instagram"):
        return _err(f"run_crew: unknown crew {crew!r}")

    run_id = str(uuid.uuid4())
    try:
        create_run(
            run_id,
            "crewai",
            f"CrewAI {crew} crew (chat-tool fire)",
            {"crew": crew, "task": task, "context": context},
        )
    except Exception:
        logger.exception("run_crew: create_run failed")

    try:
        from openexecutive.integrations.crewai_adapter import get_crewai_adapter

        adapter = get_crewai_adapter(crew=crew)
        result: AgentResult = await adapter.run(task=task, context=context)
    except Exception as exc:
        logger.exception("run_crew: adapter.run crashed")
        with _suppress():
            fail_run(run_id, str(exc)[:200])
        _audit(
            False,
            f"run_crew ({crew}) FAILED — {exc}",
            {"error": str(exc)[:300], "crew": crew},
        )
        return _err(f"crew error: {exc}")

    artifact = result.text or "(no output)"
    with _suppress():
        complete_run(run_id, artifact)

    _audit(
        True,
        (
            f"run_crew ({crew}): {len(result.artifacts)} artifact(s), "
            f"consulted {result.consulted_specialists}"
        ),
        {
            "crew": crew,
            "run_id": run_id,
            "artifacts": [a.get("name") for a in result.artifacts],
            "consulted_specialists": result.consulted_specialists,
        },
    )

    return json.dumps({
        "ok": True,
        "run_id": run_id,
        "crew": crew,
        "text": result.text,
        "artifacts": result.artifacts,
        "consulted_specialists": result.consulted_specialists,
        "presentation_hint": (
            "Tell the principal what the crew produced. Lead with the "
            "deliverable summary, then mention any artifacts it wrote "
            "(e.g. final-content-strategy.md). Do NOT re-run the crew or "
            "re-enumerate its internal agent steps."
        ),
    })


# --------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------- #
import contextlib as _contextlib


def _err(msg: str) -> str:
    _audit(False, f"run_crew: {msg}", {"error": msg[:300]})
    return json.dumps({"error": msg})


def _audit(ok: bool, summary: str, details: dict[str, Any]) -> None:
    audit_log(
        "tool_invocation",
        summary,
        actor="executive",
        details={"tool": "run_crew", "ok": ok, **details},
    )


@_contextlib.contextmanager
def _suppress():
    try:
        yield
    except Exception:
        logger.debug("suppressed exception in run_crew cleanup", exc_info=True)


CREW_TOOLS: list[dict[str, Any]] = [RUN_CREW_TOOL]

CREW_TOOL_HANDLERS: dict[str, Callable[[dict[str, Any]], Awaitable[str]]] = {
    "run_crew": handle_run_crew,
}


__all__ = [
    "CREW_TOOLS",
    "CREW_TOOL_HANDLERS",
    "RUN_CREW_TOOL",
    "handle_run_crew",
]