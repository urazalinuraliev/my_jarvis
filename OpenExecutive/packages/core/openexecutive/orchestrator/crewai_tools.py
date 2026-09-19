"""``run_crew``: the chat tool that starts one of the CrewAI marketing crews.

The Executive calls it when the principal asks for a multi-agent marketing
deliverable — a meeting briefing or an Instagram content strategy. A crew
takes minutes, longer than a chat turn may last (``CHAT_STREAM_TIMEOUT_S``),
so the tool only *starts* it: it records a ``crewai`` workflow run, launches
the crew as a background task and returns at once. The task completes or
fails the run when the crew ends, and the deliverable shows up on the
``/jobs`` page.

The tool is advertised only when the crews can run here
(``crew_integration_available``). Its handler stays registered either way and
then answers that the crews are not installed; the detailed reason names
server paths, so it is only logged.

JSON in, JSON out — like the other orchestrator tools.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from typing import Any

from openexecutive.audit import log_event as audit_log
from openexecutive.integrations import crewai_adapter
from openexecutive.integrations.adapters import AgentResult
from openexecutive.integrations.crewai_adapter import SUPPORTED_CREWS
from openexecutive.workflows.persistence import complete_run, create_run, fail_run

logger = logging.getLogger(__name__)

# The event loop keeps only weak references to tasks; these strong ones stop a
# running crew from being garbage-collected mid-run.
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

_STARTED_HINT = (
    "Tell the principal the crew is now running, that it takes a few minutes, "
    "and that its deliverable will be on the Jobs page (/jobs/runs/<run_id>) "
    "when it finishes. Do NOT wait for it, poll it, or call run_crew again for "
    "the same request."
)


@dataclass(frozen=True)
class _CrewRequest:
    crew: str
    task: str
    context: str

    @classmethod
    def from_tool_input(cls, tool_input: dict[str, Any]) -> _CrewRequest:
        return cls(
            crew=str(tool_input.get("crew", "instagram")).strip().lower(),
            task=str(tool_input.get("task", "")).strip(),
            context=str(tool_input.get("context", "")).strip(),
        )


async def handle_run_crew(tool_input: dict[str, Any]) -> str:
    request = _CrewRequest.from_tool_input(tool_input)
    problem = _request_problem(request)
    if problem is not None:
        return _err(problem)

    run_id = _open_run(request)
    background = asyncio.create_task(_run_crew_to_completion(run_id, request))
    _background_runs.add(background)
    background.add_done_callback(_background_runs.discard)
    _audit(
        True,
        f"run_crew ({request.crew}) started as run {run_id}",
        {"crew": request.crew, "run_id": run_id},
    )
    return json.dumps({
        "ok": True,
        "status": "started",
        "run_id": run_id,
        "crew": request.crew,
        "presentation_hint": _STARTED_HINT,
    })


def _request_problem(request: _CrewRequest) -> str | None:
    """Why *request* can't be started, or None."""
    if not request.task:
        return "run_crew: 'task' is required"
    if request.crew not in SUPPORTED_CREWS:
        return f"run_crew: unknown crew {request.crew!r}"
    unavailable = crewai_adapter.crew_unavailable_reason()
    if unavailable is not None:
        logger.warning("run_crew: crews unavailable: %s", unavailable)
        return "run_crew: the CrewAI crews are not installed on this server."
    return None


def _open_run(request: _CrewRequest) -> str:
    """Record a new ``crewai`` workflow run for *request*; return its id."""
    run_id = str(uuid.uuid4())
    try:
        create_run(
            run_id,
            "crewai",
            f"CrewAI {request.crew} crew (chat-tool fire)",
            {"crew": request.crew, "task": request.task, "context": request.context},
        )
    except Exception:
        logger.exception("run_crew: create_run failed")
    return run_id


async def _run_crew_to_completion(run_id: str, request: _CrewRequest) -> None:
    """Run the crew and record its outcome on workflow run *run_id*."""
    try:
        adapter = crewai_adapter.get_crewai_adapter(crew=request.crew)
        result = await adapter.run(task=request.task, context=request.context)
    except asyncio.CancelledError:
        # Server shutdown: don't leave the run "running" forever.
        with _suppress():
            fail_run(run_id, "cancelled (server shutting down)")
        raise
    except Exception as exc:
        # The exception text can carry server paths, so it goes to the log,
        # the run record and the audit row — never back into a chat.
        logger.exception("run_crew: crew %s failed (run %s)", request.crew, run_id)
        with _suppress():
            fail_run(run_id, str(exc)[:200])
        _audit(
            False,
            f"run_crew ({request.crew}) FAILED — {exc}",
            {"error": str(exc)[:300], "crew": request.crew},
        )
        return
    _record_success(run_id, request.crew, result)


def _record_success(run_id: str, crew: str, result: AgentResult) -> None:
    with _suppress():
        complete_run(run_id, result.text or "(no output)")
    _audit(
        True,
        (
            f"run_crew ({crew}): {len(result.files)} file(s), "
            f"consulted {result.consulted_specialists}"
        ),
        {
            "crew": crew,
            "run_id": run_id,
            "files": [file["name"] for file in result.files],
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
    """Best-effort bookkeeping: log a failure at debug level and carry on."""
    try:
        yield
    except Exception:
        logger.debug("suppressed exception in run_crew bookkeeping", exc_info=True)


# Advertised only when the crews can run; decided once at import so the cached
# tool block stays stable for the life of the process.
CREW_TOOLS: list[dict[str, Any]] = (
    [RUN_CREW_TOOL] if crewai_adapter.crew_integration_available() else []
)

CREW_TOOL_HANDLERS: dict[str, Callable[[dict[str, Any]], Awaitable[str]]] = {
    "run_crew": handle_run_crew,
}


__all__ = [
    "CREW_TOOLS",
    "CREW_TOOL_HANDLERS",
    "RUN_CREW_TOOL",
    "handle_run_crew",
]
