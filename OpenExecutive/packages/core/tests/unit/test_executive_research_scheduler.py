"""Tests for the periodic executive_research cron + skip-if-unchanged."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from openexecutive.alerts.store import initialize_db as initialize_alerts_db
from openexecutive.audit import AuditLogger, set_audit_logger
from openexecutive.memory.episodic import initialize_db as initialize_episodic_db
from openexecutive.monitoring import store as monitoring_store
from openexecutive.monitoring.research import scheduler as research_scheduler
from openexecutive.people.store import initialize_db as initialize_people_db


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "test_research_cron.db"
    monkeypatch.setattr("openexecutive.memory.episodic.DB_PATH", db_path)
    monkeypatch.setattr("openexecutive.alerts.store.DB_PATH", db_path)
    initialize_episodic_db(db_path)
    initialize_alerts_db(db_path)
    monitoring_store.initialize_db(db_path)
    monkeypatch.setattr("openexecutive.people.store.DB_PATH", db_path)
    initialize_people_db(db_path)
    audit_db = AuditLogger(db_path=db_path)
    audit_db.initialize_db()
    set_audit_logger(audit_db)
    return db_path


def test_state_hash_stable_across_calls(db: Path) -> None:
    h1 = research_scheduler.compute_research_state_hash(db_path=db)
    h2 = research_scheduler.compute_research_state_hash(db_path=db)
    assert h1 == h2
    assert isinstance(h1, str)
    assert len(h1) == 64


def test_state_hash_changes_when_watchlist_grows(db: Path) -> None:
    before = research_scheduler.compute_research_state_hash(db_path=db)
    monitoring_store.insert_watchlist_item(
        slug="stock-aapl", signal_type="stock", target="AAPL", db_path=db,
    )
    after = research_scheduler.compute_research_state_hash(db_path=db)
    assert before != after


def test_state_hash_changes_when_initiative_added(db: Path) -> None:
    from openexecutive.memory.episodic import store_initiative

    before = research_scheduler.compute_research_state_hash(db_path=db)
    store_initiative(
        title="Launch enterprise tier",
        status="active",
        summary="Drive ACV from $20k to $40k",
        db_path=db,
    )
    after = research_scheduler.compute_research_state_hash(db_path=db)
    assert before != after


def test_bootstrap_is_idempotent(db: Path) -> None:
    first = research_scheduler.bootstrap_watchlist_research_scan()
    second = research_scheduler.bootstrap_watchlist_research_scan()
    assert first is not None
    assert second is None


# --------------------------------------------------------------------- #
# Workflow stub helpers
# --------------------------------------------------------------------- #


class _MinimalInput:
    def __init__(self, note: str = "", **_: Any) -> None:
        self.note = note

    def model_dump(self) -> dict[str, Any]:
        return {"note": self.note}


def _make_workflow_stub(
    findings: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]] | None = None,
) -> MagicMock:
    """Workflow stub yielding result + artifact + done in the new shape."""
    tool_calls = tool_calls or []

    async def fake_run(*, inputs: Any, store: Any):
        from openexecutive.workflows.base import WorkflowEvent
        yield WorkflowEvent(
            type="result",
            data={
                "findings": findings,
                "tool_calls": tool_calls,
                "narrative": (
                    "Researched and routed." if findings else ""
                ),
            },
        )
        yield WorkflowEvent(
            type="artifact",
            content=(
                "# Executive research\n" if findings else "(quiet run)"
            ),
        )
        yield WorkflowEvent(type="done")

    workflow = MagicMock()
    workflow.run = fake_run
    workflow.input_model.return_value = _MinimalInput
    workflow.title = "Executive Research"
    return workflow


@pytest.mark.asyncio
async def test_scan_skips_when_state_unchanged(
    db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Second tick with unchanged state must NOT call the workflow."""
    workflow_calls = {"n": 0}

    async def counting_run(*, inputs, store):
        from openexecutive.workflows.base import WorkflowEvent
        workflow_calls["n"] += 1
        yield WorkflowEvent(
            type="result", data={"findings": [], "tool_calls": []},
        )
        yield WorkflowEvent(type="artifact", content="(empty)")
        yield WorkflowEvent(type="done")

    workflow = MagicMock()
    workflow.run = counting_run
    workflow.input_model.return_value = _MinimalInput
    workflow.title = "Executive Research"

    monkeypatch.setitem(
        __import__(
            "openexecutive.workflows", fromlist=["WORKFLOW_REGISTRY"]
        ).WORKFLOW_REGISTRY,
        "executive_research", workflow,
    )

    await research_scheduler.run_watchlist_research_scan(
        db_path=db, store=MagicMock(),
    )
    assert workflow_calls["n"] == 1

    await research_scheduler.run_watchlist_research_scan(
        db_path=db, store=MagicMock(),
    )
    assert workflow_calls["n"] == 1  # skipped


@pytest.mark.asyncio
async def test_scan_skips_after_run_that_mutates_watchlist(
    db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run that adds watchlist rows (as the real workflow does) must NOT
    re-trigger itself on the next tick.

    The real ``executive_research`` workflow's watchlist pass calls
    ``add_watchlist_entry`` — mutating the very watchlist the skip-if-unchanged
    fingerprint hashes. If the baseline stored were the *pre-run* hash, the next
    tick would read the now-larger watchlist, see a different hash, and run a
    full research pass again every interval. The baseline must be the *post-run*
    state so an otherwise-unchanged next tick skips. This stub reproduces the
    mutation that the production workflow performs.
    """
    workflow_calls = {"n": 0}

    async def mutating_run(*, inputs, store):
        from openexecutive.workflows.base import WorkflowEvent
        workflow_calls["n"] += 1
        # Mirror the real workflow's side effect: add a watchlist row.
        monitoring_store.insert_watchlist_item(
            slug=f"competitor-{workflow_calls['n']}",
            signal_type="news",
            target="Acme Corp",
            db_path=db,
        )
        yield WorkflowEvent(
            type="result",
            data={
                "findings": [{"title": "Acme moved", "summary": "s"}],
                "tool_calls": [{"tool": "add_watchlist_entry", "ok": True}],
            },
        )
        yield WorkflowEvent(type="artifact", content="# ran")
        yield WorkflowEvent(type="done")

    workflow = MagicMock()
    workflow.run = mutating_run
    workflow.input_model.return_value = _MinimalInput
    workflow.title = "Executive Research"
    monkeypatch.setitem(
        __import__(
            "openexecutive.workflows", fromlist=["WORKFLOW_REGISTRY"]
        ).WORKFLOW_REGISTRY,
        "executive_research", workflow,
    )

    # First tick: cold start runs, watchlist grows by one row.
    await research_scheduler.run_watchlist_research_scan(db_path=db, store=MagicMock())
    assert workflow_calls["n"] == 1

    # The stored baseline must equal the CURRENT (post-run) state hash — i.e.
    # it accounts for the row the run just added, not the empty pre-run state.
    from openexecutive.audit import get_audit_logger

    ran = get_audit_logger().query(event_type=research_scheduler.EVENT_RAN, limit=1)
    assert (ran[0].details or {}).get("state_hash") == (
        research_scheduler.compute_research_state_hash(db_path=db)
    )

    # Second tick, nothing else changed: must SKIP despite the run-added row.
    await research_scheduler.run_watchlist_research_scan(db_path=db, store=MagicMock())
    assert workflow_calls["n"] == 1  # skipped — no self-perpetuating loop


def _register_counting_workflow(
    monkeypatch: pytest.MonkeyPatch, counter: dict[str, int]
) -> None:
    async def counting_run(*, inputs, store):
        from openexecutive.workflows.base import WorkflowEvent
        counter["n"] += 1
        yield WorkflowEvent(type="result", data={"findings": [], "tool_calls": []})
        yield WorkflowEvent(type="artifact", content="(empty)")
        yield WorkflowEvent(type="done")

    workflow = MagicMock()
    workflow.run = counting_run
    workflow.input_model.return_value = _MinimalInput
    workflow.title = "Executive Research"
    monkeypatch.setitem(
        __import__(
            "openexecutive.workflows", fromlist=["WORKFLOW_REGISTRY"]
        ).WORKFLOW_REGISTRY,
        "executive_research", workflow,
    )


@pytest.mark.asyncio
async def test_scan_runs_when_stale_despite_unchanged_state(
    db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Staleness floor: an unchanged-state tick still runs once the floor elapses.

    The skip-if-unchanged fingerprint is blind to purely-external change, so
    the staleness floor must force a fresh run after enough time — otherwise a
    static profile would suppress the council indefinitely.
    """
    from datetime import UTC, datetime, timedelta

    calls = {"n": 0}
    _register_counting_workflow(monkeypatch, calls)

    # First tick records a successful periodic run "now".
    await research_scheduler.run_watchlist_research_scan(db_path=db, store=MagicMock())
    assert calls["n"] == 1

    # A tick just after still skips (well within the default 24h floor).
    await research_scheduler.run_watchlist_research_scan(db_path=db, store=MagicMock())
    assert calls["n"] == 1

    # A tick past the floor runs again, even though profile / initiatives /
    # watchlist are unchanged.
    future = datetime.now(UTC) + timedelta(hours=25)
    await research_scheduler.run_watchlist_research_scan(
        db_path=db, store=MagicMock(), now=future,
    )
    assert calls["n"] == 2

    # Lock the audit `trigger` values: first run is a cold start, the forced
    # run is attributed to the staleness floor.
    from openexecutive.audit import get_audit_logger

    ran = get_audit_logger().query(
        event_type=research_scheduler.EVENT_RAN, limit=5,
    )
    assert (ran[0].details or {}).get("trigger") == "staleness_floor"
    assert (ran[-1].details or {}).get("trigger") == "cold_start"


@pytest.mark.asyncio
async def test_staleness_floor_disabled_keeps_skipping(
    db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the floor disabled (<= 0), pure skip-if-unchanged still holds."""
    from datetime import UTC, datetime, timedelta

    class _Stub:
        watchlist_research_max_staleness_hours = 0

    monkeypatch.setattr("openexecutive.config.get_settings", lambda: _Stub())

    calls = {"n": 0}
    _register_counting_workflow(monkeypatch, calls)

    await research_scheduler.run_watchlist_research_scan(db_path=db, store=MagicMock())
    assert calls["n"] == 1

    # Far past any floor, but the floor is disabled → unchanged state skips.
    future = datetime.now(UTC) + timedelta(hours=100)
    await research_scheduler.run_watchlist_research_scan(
        db_path=db, store=MagicMock(), now=future,
    )
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_scan_does_not_write_alert_directly(
    db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cron must NOT insert its own Alert — the workflow's synthesis
    step fires create_alert / send_*_dm / etc. directly, so an extra
    Alert here would duplicate. The cron's only side-effect on success
    is the audit row + the workflow's own routing."""
    from openexecutive.alerts.store import list_alerts

    workflow = _make_workflow_stub(
        findings=[{
            "title": "Acme raised $50M", "summary": "s",
            "severity_hint": "high", "suggested_audience": "principal",
            "confidence": "high",
        }],
        tool_calls=[{
            "tool": "send_slack_dm", "input_preview": "principal",
            "result_preview": "{'status': 'sent'}", "ok": True,
        }],
    )

    monkeypatch.setitem(
        __import__(
            "openexecutive.workflows", fromlist=["WORKFLOW_REGISTRY"]
        ).WORKFLOW_REGISTRY,
        "executive_research", workflow,
    )

    surfaced = await research_scheduler.run_watchlist_research_scan(
        db_path=db, store=MagicMock(),
    )
    assert surfaced == 1
    assert list_alerts(limit=10) == []


@pytest.mark.asyncio
async def test_scan_audit_row_carries_expected_keys(
    db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lock the audit-row shape. The next tick's skip-if-unchanged check
    reads `state_hash` from this row; downstream cost dashboards expect
    `findings` / `tool_calls` / `ok_tool_calls`. A silent drop / rename
    on the producer side would break either consumer."""
    from openexecutive.audit import get_audit_logger

    workflow = _make_workflow_stub(
        findings=[{
            "title": "Acme raised $50M", "summary": "s",
            "severity_hint": "high", "suggested_audience": "principal",
            "confidence": "high",
        }],
        tool_calls=[
            {"tool": "send_slack_dm", "ok": True, "result_preview": "ok"},
            {"tool": "create_alert", "ok": False, "result_preview": "err"},
        ],
    )
    monkeypatch.setitem(
        __import__(
            "openexecutive.workflows", fromlist=["WORKFLOW_REGISTRY"]
        ).WORKFLOW_REGISTRY,
        "executive_research", workflow,
    )

    await research_scheduler.run_watchlist_research_scan(
        db_path=db, store=MagicMock(),
    )

    rows = get_audit_logger().query(event_type=research_scheduler.EVENT_RAN, limit=1)
    assert len(rows) == 1
    details = rows[0].details or {}
    # Skip-if-unchanged contract:
    assert "state_hash" in details
    assert isinstance(details["state_hash"], str)
    assert len(details["state_hash"]) == 64
    # Cost / routing dashboard contract:
    assert details.get("findings") == 1
    assert details.get("tool_calls") == 2
    assert details.get("ok_tool_calls") == 1
    assert "run_id" in details


# --------------------------------------------------------------------- #
# clear_research_run_history — the fixture-load skip-gate reset
# --------------------------------------------------------------------- #


def test_clear_research_run_history_only_touches_research_rows(
    db: Path,
) -> None:
    """Deletes the three research event types, preserves other audit rows."""
    from openexecutive.audit import log_event

    log_event(research_scheduler.EVENT_RAN, "ran", actor="scheduler",
              details={"state_hash": "h"})
    log_event(research_scheduler.EVENT_SKIPPED, "skipped", actor="scheduler")
    log_event(research_scheduler.EVENT_FAILED, "failed", actor="scheduler")
    log_event("peer_memory", "unrelated row", actor="someone")

    deleted = research_scheduler.clear_research_run_history(db_path=db)
    assert deleted == 3

    from openexecutive.audit import get_audit_logger

    assert get_audit_logger().query(
        event_type=research_scheduler.EVENT_RAN,
    ) == []
    survivors = get_audit_logger().query(event_type="peer_memory")
    assert len(survivors) == 1  # unrelated audit history is untouched


def test_clear_research_run_history_missing_db_is_zero(tmp_path: Path) -> None:
    # A fresh box (no DB yet) has nothing to clear — must not raise.
    assert research_scheduler.clear_research_run_history(
        db_path=tmp_path / "nope.db",
    ) == 0


@pytest.mark.asyncio
async def test_clearing_history_lets_an_unchanged_scan_run_again(
    db: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fixture-load fix end-to-end: a same-state scan that would skip runs
    again once the research run-history is cleared (what a fixture load does)."""
    calls = {"n": 0}
    _register_counting_workflow(monkeypatch, calls)

    await research_scheduler.run_watchlist_research_scan(db_path=db, store=MagicMock())
    assert calls["n"] == 1

    # Unchanged state within the staleness floor → would skip.
    await research_scheduler.run_watchlist_research_scan(db_path=db, store=MagicMock())
    assert calls["n"] == 1

    # Simulate a fixture load wiping the research run-history.
    research_scheduler.clear_research_run_history(db_path=db)

    # Same state, but the gate has no prior run to compare against → runs.
    await research_scheduler.run_watchlist_research_scan(db_path=db, store=MagicMock())
    assert calls["n"] == 2
