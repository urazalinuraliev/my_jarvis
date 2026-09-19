"""``log_event`` should inherit session_id/turn_id from the active ContextVars.

Without this fallback, headless emitters that don't thread the ids
themselves — notably the Honcho wrapper's ``_emit_peer_memory`` —
produce audit rows with ``session_id=NULL``, which are invisible in
the session-grouped /audit view and the per-turn flow chart.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from openexecutive.audit import set_turn
from openexecutive.audit.logger import AuditLogger, log_event, set_audit_logger


@pytest.fixture()
def audit_db(tmp_path: Path):
    instance = AuditLogger(tmp_path / "audit.db")
    set_audit_logger(instance)
    yield instance
    set_audit_logger(None)


def test_log_event_inherits_active_contextvars(audit_db: AuditLogger) -> None:
    """A bare log_event call inside set_turn picks up session/turn from the ContextVars."""
    with set_turn(session_id="sess-abc", turn_id="t-123"):
        log_event("peer_memory", "honcho.prefetch: ok", actor="honcho")

    rows = audit_db.query(event_type="peer_memory")
    assert len(rows) == 1
    assert rows[0].session_id == "sess-abc"
    assert rows[0].turn_id == "t-123"


def test_log_event_explicit_session_id_overrides_contextvar(audit_db: AuditLogger) -> None:
    """If the caller passes session_id, the kwarg wins over the ContextVar."""
    with set_turn(session_id="sess-ctx", turn_id="t-ctx"):
        log_event(
            "peer_memory",
            "honcho.sync_turn: ok",
            actor="honcho",
            session_id="sess-explicit",
        )

    rows = audit_db.query(event_type="peer_memory")
    assert len(rows) == 1
    assert rows[0].session_id == "sess-explicit"
    # turn_id NOT passed → still inherited from ContextVar.
    assert rows[0].turn_id == "t-ctx"


def test_log_event_without_contextvar_writes_null(audit_db: AuditLogger) -> None:
    """No active ContextVars + no kwargs → session/turn remain NULL.

    Confirms the fix is additive: the fallback only fires when the
    ContextVars are populated. Un-scoped emitters (e.g. startup logs,
    background tasks before any turn is bound) keep their prior NULL
    behavior rather than picking up a stale value from some unrelated
    upstream context.
    """
    log_event("peer_memory", "honcho.prefetch: disabled", actor="honcho")
    rows = audit_db.query(event_type="peer_memory")
    assert len(rows) == 1
    assert rows[0].session_id is None
    assert rows[0].turn_id is None
