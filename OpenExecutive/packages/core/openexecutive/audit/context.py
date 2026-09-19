"""Audit context — propagates session_id / turn_id to fire-and-forget emit sites.

A single Executive turn fans out across many helpers (retriever, specialist
routing, cache_manager probe, tool dispatch). Threading session_id + turn_id
through every signature would touch ~30 call sites and break unrelated
abstractions. ContextVars give us per-task propagation that's automatic
across `await` boundaries while staying scoped to the current asyncio task —
no global state, no cross-talk between concurrent chat turns.

Usage:

    from openexecutive.audit.context import set_turn, get_active_ids

    with set_turn(session_id="discord:dm:42", turn_id="t-abc"):
        await executive.stream_chat(...)   # retriever et al see the IDs

    sid, tid = get_active_ids()            # outside: both None

The context manager *resets* the vars on exit, so nested or stacked turns
restore prior values cleanly. This is the same pattern used by
`orchestrator.schedule_tools.current_session`.
"""
from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar

# Default to None so call sites that haven't been wrapped (CLI, ad-hoc tools,
# tests) just produce un-tagged events instead of crashing.
_audit_session_id: ContextVar[str | None] = ContextVar(
    "audit_session_id", default=None
)
_audit_turn_id: ContextVar[str | None] = ContextVar(
    "audit_turn_id", default=None
)


def get_active_ids() -> tuple[str | None, str | None]:
    """Return (session_id, turn_id) for the active turn, or (None, None)."""
    return _audit_session_id.get(), _audit_turn_id.get()


def get_active_session_id() -> str | None:
    return _audit_session_id.get()


def get_active_turn_id() -> str | None:
    return _audit_turn_id.get()


def bind_turn(*, session_id: str | None, turn_id: str | None) -> None:
    """Set both ContextVars without using a `with` block.

    For long-running async generators that yield repeatedly, a sync `with
    set_turn(...)` block over the whole body is the safe choice. Use this
    helper only when you also call `clear_turn()` at every exit path —
    otherwise a task that processes a second turn (rare: a workflow that
    piggy-backs on the same asyncio task) will inherit stale IDs and tag
    retrieval/audit rows incorrectly.

    Async generators that may be abandoned mid-stream (e.g., HTTP client
    drops the SSE connection) won't reach explicit `clear_turn()` calls;
    in those cases prefer `with set_turn(...)`.
    """
    _audit_session_id.set(session_id)
    _audit_turn_id.set(turn_id)


def clear_turn() -> None:
    """Reset both audit ContextVars to None. Pair with `bind_turn()`."""
    _audit_session_id.set(None)
    _audit_turn_id.set(None)


@contextlib.contextmanager
def set_turn(
    *, session_id: str | None = None, turn_id: str | None = None
) -> Iterator[None]:
    """Bind session_id + turn_id for the duration of the `with` block.

    Both kwargs are optional so callers can set just one if needed (e.g.
    a workflow that has a session but no logical turn). Reset on exit so
    nested calls restore prior values.

    Implementation note: we *save the prior value and restore it on exit*
    rather than using ``ContextVar.set()``/``reset(token)``. The Token
    variant raises ``ValueError: <Token …> was created in a different
    Context`` when ``__exit__`` runs in a Context that differs from the
    one ``__enter__`` ran in — which happens when this manager wraps an
    ``async for`` over an async generator whose iteration crosses task
    boundaries (FastAPI's SSE driver, httpx-backed streaming, anything
    that suspends/resumes the generator outside the original asyncio
    Task). The save/restore pattern is Context-independent and produces
    the same observable behavior.
    """
    prior_session = _audit_session_id.get()
    prior_turn = _audit_turn_id.get()
    _audit_session_id.set(session_id)
    _audit_turn_id.set(turn_id)
    try:
        yield
    finally:
        _audit_session_id.set(prior_session)
        _audit_turn_id.set(prior_turn)
