"""Chat tool that delegates a marketing workflow to the integrated CrewAI crew.

The Executive calls ``run_crew`` when the principal asks for a multi-agent
marketing deliverable — a meeting briefing, a competitive analysis, or an
Instagram content strategy. A crew pipeline takes minutes, longer than a chat
turn may last (``CHAT_STREAM_TIMEOUT_S``), so the tool only *starts* the crew:
it records a ``crewai`` workflow run, launches the crew as a background task
and returns at once. The run is completed or failed on the ``/jobs`` page
when the crew ends; the Executive tells the principal where to find it.

The tool is only advertised when the crew repo and the ``crewai`` package are
present (``crew_integration_available``); the handler stays registered either
way and answers that the crews are unavailable (the reason is only logged, as
it names server paths).

Mirrors the JSON-in / JSON-out pattern of the other orchestrator tools.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

from openexecutive.audit import log_event as audit_log
from openexecutive.integrations.crewai_adapter import (
    SUPPORTED_CREWS,
    crew_integration_available,
    crew_unavailable_reason,
)
from openexecutive.workflows.persistence import (
    complete_run,
    create_run,
    fail_run,
)

logger = logging.getLogger(__name__)

# Strong references to in-flight crew tasks: the event loop only keeps weak
# ones, so an unreferenced task could be garbage-collected mid-run.
_background_runs: set[asyncio.Task[None]] = set()


RUN_CREW_TOOL: dict[str, Any] = {
    "name": "run_crew",
    "description": (
        "Start a multi-agent marketing workflow on the integrated CrewAI "
        "crew. Two crews are available:\n"
        "- 'meeting_prep': research + industry analysis + strategy + briefing "
        "for an upcoming meeting. Use when the principal asks for a briefing, "
        "talking points, or competitive intel on meeting participants.\n"
        "- 'instagram': market research + content strategy + visual creation "
        "+ copywriting + final report for an Instagram content calendar. Use "
        "when the principal asks for a content plan, captions, or a social "
        "media strategy.\n"
        "A crew takes several minutes, so this starts it in the background "
        "and returns a run id at once; the deliverable appears on the Jobs "
        "page when the crew finishes."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "crew": {
                "type": "string",
                "enum": list(SUPPORTED_CREWS),
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
    if crew not in SUPPORTED_CREWS:
        return _err(f"run_crew: unknown crew {crew!r}")
    unavailable = crew_unavailable_reason()
    if unavailable is not None:
        # The reason names server paths: log it, keep it out of the chat.
        logger.warning("run_crew: crews unavailable: %s", unavailable)
        return _err("run_crew: the CrewAI crews are not installed on this server.")

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

    background = asyncio.create_task(
        _run_crew_to_completion(run_id=run_id, crew=crew, task=task, context=context)
    )
    _background_runs.add(background)
    background.add_done_callback(_background_runs.discard)
    _audit(True, f"run_crew ({crew}) started as run {run_id}", {"crew": crew, "run_id": run_id})

    return json.dumps({
        "ok": True,
        "status": "started",
        "run_id": run_id,
        "crew": crew,
        "presentation_hint": (
            "Tell the principal the crew is now running, that it takes a few "
            "minutes, and that its deliverable will be on the Jobs page "
            "(/jobs/runs/<run_id>) when it finishes. Do NOT wait for it, poll "
            "it, or call run_crew again for the same request."
        ),
    })


async def _run_crew_to_completion(*, run_id: str, crew: str, task: str, context: str) -> None:
    """Run the crew and record the outcome on its workflow run."""
    try:
        from openexecutive.integrations.crewai_adapter import get_crewai_adapter

        result = await get_crewai_adapter(crew=crew).run(task=task, context=context)
    except asyncio.CancelledError:
        # Server shutdown: don't leave the run "running" forever.
        with _suppress():
            fail_run(run_id, "cancelled (server shutting down)")
        raise
    except Exception as exc:
        # The exception text can carry server paths, so it goes to the log,
        # the run record and the audit row — never back into a chat.
        logger.exception("run_crew: crew %s failed (run %s)", crew, run_id)
        with _suppress():
            fail_run(run_id, str(exc)[:200])
        _audit(False, f"run_crew ({crew}) FAILED — {exc}", {"error": str(exc)[:300], "crew": crew})
        return

    with _suppress():
        complete_run(run_id, result.text or "(no output)")
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


# --------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------- #


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


@contextlib.contextmanager
def _suppress() -> Iterator[None]:
    try:
        yield
    except Exception:
        logger.debug("suppressed exception in run_crew cleanup", exc_info=True)


# Advertised only when the crews can actually run (evaluated once at import,
# so the cached tool block stays stable for the life of the process).
CREW_TOOLS: list[dict[str, Any]] = [RUN_CREW_TOOL] if crew_integration_available() else []

CREW_TOOL_HANDLERS: dict[str, Callable[[dict[str, Any]], Awaitable[str]]] = {
    "run_crew": handle_run_crew,
}


__all__ = [
    "CREW_TOOLS",
    "CREW_TOOL_HANDLERS",
    "RUN_CREW_TOOL",
    "handle_run_crew",
]
