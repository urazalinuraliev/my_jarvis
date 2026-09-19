"""Tests for workflows/resumer.py."""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from openexecutive.alerts import store as alert_store
from openexecutive.departments import store as dept_store
from openexecutive.memory import episodic
from openexecutive.people import store as people_store
from openexecutive.workflows import persistence as wf_persistence
from openexecutive.workflows.resumer import _handle_timeout, _tick, apply_resolution
from openexecutive.workflows.wait_for_human import WaitForHumanResolution


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "test.db"
    monkeypatch.setattr(episodic, "DB_PATH", db)
    monkeypatch.setattr(wf_persistence, "DB_PATH", db)
    monkeypatch.setattr(alert_store, "DB_PATH", db)
    monkeypatch.setattr(dept_store, "DB_PATH", db)
    monkeypatch.setattr(people_store, "DB_PATH", db)

    episodic.initialize_db(db)
    wf_persistence.initialize_runs_db(db)
    alert_store.initialize_db(db)
    dept_store.initialize_db(db)
    people_store.initialize_db(db)
    yield


def _seed_awaiting(
    run_id: str,
    person_id: int,
    on_timeout: str = "escalate",
    awaiting_until: datetime | None = None,
    *,
    department: str = "",
) -> None:
    wf_persistence.create_run(run_id, "test_wf", "Test run", {})
    state = json.dumps({
        "on_timeout": on_timeout,
        "channel": "slack",
        "channel_ref": "U123",
        "expected_reply_shape": "approve_reject",
        "question": "Please approve.",
        "department": department,
    })
    until = awaiting_until or datetime.now(UTC) - timedelta(minutes=1)  # already expired
    wf_persistence.save_checkpoint(run_id, state, person_id, until)


# ---------------------------------------------------------------------------
# apply_resolution
# ---------------------------------------------------------------------------

def test_apply_resolution_marks_resolved() -> None:
    _seed_awaiting("run-1", person_id=5)
    resolution = WaitForHumanResolution(
        run_id="run-1",
        reply_text="approved",
        source_channel="slack",
        source_message_id="msg-1",
        parsed_decision={"decision": "approve", "note": ""},
        person_id=5,
    )
    result = asyncio.run(apply_resolution("run-1", resolution))
    assert result is True

    run = wf_persistence.get_run("run-1")
    assert run is not None
    assert run["status"] == "resolved"
    loaded_res = json.loads(run["resolution_json"])
    assert loaded_res["parsed_decision"]["decision"] == "approve"


def test_apply_resolution_is_idempotent() -> None:
    _seed_awaiting("run-2", person_id=3)
    resolution = WaitForHumanResolution(
        run_id="run-2",
        reply_text="ok",
        source_channel="telegram",
        parsed_decision={"decision": "approve", "note": ""},
        person_id=3,
    )
    first = asyncio.run(apply_resolution("run-2", resolution))
    second = asyncio.run(apply_resolution("run-2", resolution))
    assert first is True
    assert second is False  # run is no longer awaiting_human


def test_apply_resolution_writes_audit_log() -> None:
    from openexecutive.audit.logger import AuditLogger, set_audit_logger
    db = episodic.DB_PATH  # already monkeypatched to tmp_path in autouse fixture
    audit_logger = AuditLogger(db)
    set_audit_logger(audit_logger)

    _seed_awaiting("run-3", person_id=7)
    resolution = WaitForHumanResolution(
        run_id="run-3",
        reply_text="yes",
        source_channel="slack",
        parsed_decision={"decision": "approve", "note": ""},
        person_id=7,
    )
    asyncio.run(apply_resolution("run-3", resolution))

    events = audit_logger.query(event_type="human_resolution", limit=5)
    assert any("run-3" in str(e.summary) for e in events)


# ---------------------------------------------------------------------------
# Timeout handling
# ---------------------------------------------------------------------------

def test_timeout_escalate_creates_alert() -> None:
    dept_store.seed_default_departments()
    principal_id = people_store.upsert_person(full_name="Founder", is_principal=True)
    from openexecutive.people.models import AuthorityScope
    people_store.set_authority_scope(principal_id, [AuthorityScope.WILDCARD])

    _seed_awaiting("run-esc", person_id=principal_id, on_timeout="escalate", department="finance")
    run = wf_persistence.list_awaiting_runs()[0]
    asyncio.run(_handle_timeout(run, datetime.now(UTC)))

    run_after = wf_persistence.get_run("run-esc")
    assert run_after is not None
    assert run_after["status"] == "timed_out"


def test_timeout_fail_sets_error_status() -> None:
    _seed_awaiting("run-fail", person_id=1, on_timeout="fail")
    run = wf_persistence.list_awaiting_runs()[0]
    asyncio.run(_handle_timeout(run, datetime.now(UTC)))

    run_after = wf_persistence.get_run("run-fail")
    assert run_after is not None
    assert run_after["status"] == "error"


def test_timeout_auto_proceed_marks_resolved() -> None:
    _seed_awaiting("run-auto", person_id=2, on_timeout="auto_proceed")
    run = wf_persistence.list_awaiting_runs()[0]
    asyncio.run(_handle_timeout(run, datetime.now(UTC)))

    run_after = wf_persistence.get_run("run-auto")
    assert run_after is not None
    assert run_after["status"] == "resolved"
    loaded_res = json.loads(run_after["resolution_json"])
    assert loaded_res["parsed_decision"]["decision"] == "auto_proceed"


# ---------------------------------------------------------------------------
# _tick — poll cycle
# ---------------------------------------------------------------------------

def test_tick_processes_expired_runs() -> None:
    past = datetime.now(UTC) - timedelta(hours=1)
    future = datetime.now(UTC) + timedelta(hours=24)

    _seed_awaiting("expired", person_id=1, on_timeout="fail", awaiting_until=past)
    _seed_awaiting("not-yet", person_id=1, on_timeout="fail", awaiting_until=future)

    asyncio.run(_tick(datetime.now(UTC)))

    assert wf_persistence.get_run("expired")["status"] == "error"
    assert wf_persistence.get_run("not-yet")["status"] == "awaiting_human"


def test_tick_no_runs_is_no_op() -> None:
    # No awaiting runs — must not raise.
    asyncio.run(_tick(datetime.now(UTC)))
