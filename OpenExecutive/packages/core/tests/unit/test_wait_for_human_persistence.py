"""Tests for Phase 6 WaitForHuman persistence helpers."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from openexecutive.workflows import persistence as wf_persistence


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated workflow_runs DB."""
    path = tmp_path / "wf.db"
    # persistence.py imports DB_PATH from episodic at module level;
    # monkeypatch it so initialize_runs_db uses the temp file.
    monkeypatch.setattr(wf_persistence, "DB_PATH", path)
    import openexecutive.memory.episodic as ep
    monkeypatch.setattr(ep, "DB_PATH", path)
    ep.initialize_db(path)
    wf_persistence.initialize_runs_db(path)
    return path


def _seed_run(db: Path, run_id: str = "run-001") -> None:
    wf_persistence.create_run(
        run_id,
        "department_check_in",
        "Test run",
        {"department_slug": "finance"},
        db_path=db,
    )


# ---------------------------------------------------------------------------
# initialize_runs_db — new columns present
# ---------------------------------------------------------------------------

def test_initialize_runs_db_creates_phase6_columns(db: Path) -> None:
    import sqlite3
    conn = sqlite3.connect(str(db))
    cols = {row[1] for row in conn.execute("PRAGMA table_info(workflow_runs)")}
    conn.close()
    assert "state_json" in cols
    assert "awaiting_person_id" in cols
    assert "awaiting_until" in cols
    assert "resolution_json" in cols


def test_initialize_runs_db_idempotent(db: Path) -> None:
    wf_persistence.initialize_runs_db(db)
    wf_persistence.initialize_runs_db(db)  # second call must not raise


def test_list_runs_status_filter_done_not_starved(db: Path) -> None:
    """The `status` filter is applied in SQL, so a `status='done'` caller is
    never starved by more-recent running rows that fill a small `limit`."""
    # Three running runs touched most recently, one older done run.
    for i in range(3):
        wf_persistence.create_run(f"run-r{i}", "research", f"Running {i}", {}, db_path=db)
    wf_persistence.create_run("run-done", "morning_brief", "Done one", {}, db_path=db)
    wf_persistence.complete_run("run-done", artifact="body", db_path=db)

    # Unfiltered, limit=2 returns the two most-recently-updated (the done run
    # was completed last, so it leads; the running ones follow).
    unfiltered = wf_persistence.list_runs(limit=2, db_path=db)
    assert len(unfiltered) == 2

    # status='done' returns only the done run regardless of the running backlog.
    done = wf_persistence.list_runs(status="done", limit=2, db_path=db)
    assert [r["run_id"] for r in done] == ["run-done"]
    assert all(r["status"] == "done" for r in done)


# ---------------------------------------------------------------------------
# save_checkpoint / load_checkpoint
# ---------------------------------------------------------------------------

def test_save_load_checkpoint_round_trip(db: Path) -> None:
    _seed_run(db)
    state = '{"on_timeout": "escalate", "channel": "slack", "question": "Approve?"}'
    until = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)

    wf_persistence.save_checkpoint("run-001", state, person_id := 42, until, db_path=db)

    result = wf_persistence.load_checkpoint("run-001", db_path=db)
    assert result is not None
    loaded_state, loaded_person, loaded_until = result
    assert loaded_state == state
    assert loaded_person == person_id
    assert loaded_until is not None
    assert loaded_until.replace(tzinfo=UTC) == until


def test_checkpoint_sets_awaiting_human_status(db: Path) -> None:
    _seed_run(db)
    wf_persistence.save_checkpoint("run-001", "{}", None, None, db_path=db)
    run = wf_persistence.get_run("run-001", db_path=db)
    assert run is not None
    assert run["status"] == "awaiting_human"


def test_checkpoint_awaiting_fields_stored(db: Path) -> None:
    _seed_run(db)
    until = datetime.now(UTC) + timedelta(hours=24)
    wf_persistence.save_checkpoint("run-001", '{"q": "ok?"}', 7, until, db_path=db)

    result = wf_persistence.load_checkpoint("run-001", db_path=db)
    assert result is not None
    _, pid, ts = result
    assert pid == 7
    assert ts is not None
    assert abs((ts - until).total_seconds()) < 2


def test_load_nonexistent_checkpoint_returns_none(db: Path) -> None:
    assert wf_persistence.load_checkpoint("nonexistent", db_path=db) is None


def test_load_checkpoint_null_state_json_returns_none(db: Path) -> None:
    _seed_run(db)
    # Never saved a checkpoint — state_json is NULL.
    assert wf_persistence.load_checkpoint("run-001", db_path=db) is None


# ---------------------------------------------------------------------------
# store_resolution / mark_timed_out
# ---------------------------------------------------------------------------

def test_store_resolution_marks_resolved(db: Path) -> None:
    _seed_run(db)
    wf_persistence.save_checkpoint("run-001", "{}", None, None, db_path=db)

    ok = wf_persistence.store_resolution("run-001", '{"decision":"approve"}', db_path=db)
    assert ok is True

    run = wf_persistence.get_run("run-001", db_path=db)
    assert run is not None
    assert run["status"] == "resolved"


def test_store_resolution_idempotent(db: Path) -> None:
    _seed_run(db)
    wf_persistence.save_checkpoint("run-001", "{}", None, None, db_path=db)
    wf_persistence.store_resolution("run-001", '{"decision":"approve"}', db_path=db)
    # Second call on already-resolved run returns False (not awaiting_human).
    ok2 = wf_persistence.store_resolution("run-001", '{"decision":"approve"}', db_path=db)
    assert ok2 is False


def test_mark_timed_out_transitions_status(db: Path) -> None:
    _seed_run(db)
    wf_persistence.save_checkpoint("run-001", "{}", None, None, db_path=db)
    ok = wf_persistence.mark_timed_out("run-001", db_path=db)
    assert ok is True
    run = wf_persistence.get_run("run-001", db_path=db)
    assert run is not None
    assert run["status"] == "timed_out"


def test_mark_timed_out_only_from_awaiting_human(db: Path) -> None:
    _seed_run(db)
    # run is in 'running' status — should not be timed out.
    ok = wf_persistence.mark_timed_out("run-001", db_path=db)
    assert ok is False


# ---------------------------------------------------------------------------
# list_awaiting_runs
# ---------------------------------------------------------------------------

def test_list_awaiting_runs_filters_correctly(db: Path) -> None:
    wf_persistence.create_run("r1", "wf", "T1", {}, db_path=db)
    wf_persistence.create_run("r2", "wf", "T2", {}, db_path=db)
    wf_persistence.save_checkpoint("r1", "{}", 1, None, db_path=db)
    # r2 stays in running

    awaiting = wf_persistence.list_awaiting_runs(db_path=db)
    run_ids = [r["run_id"] for r in awaiting]
    assert "r1" in run_ids
    assert "r2" not in run_ids
