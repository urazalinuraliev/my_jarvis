"""``_seed_episodic_memory`` must seed the ``scheduled_actions`` table from
fixture ``memory.json`` rows, resolve relative ``run_at`` sentinels like
``+30s`` against load time, and map ``assigned_to_person`` (a name string)
to a Person id via the cache ``_seed_people`` leaves on itself.

Without this, fixture-staged actions (used by the round_2 act/propose/escalate
demo) get deleted but never re-inserted, so loading the fixture leaves an
empty queue and the demo can't fire.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from openexecutive.cli import fixture_loader
from openexecutive.cli.fixture_loader import _resolve_run_at, _seed_episodic_memory


def test_resolve_run_at_relative_seconds() -> None:
    now = datetime(2026, 5, 28, 12, 0, 0, tzinfo=UTC)
    result = _resolve_run_at("+30s", now)
    assert result == (now + timedelta(seconds=30)).isoformat()


def test_resolve_run_at_relative_minutes_and_hours() -> None:
    now = datetime(2026, 5, 28, 12, 0, 0, tzinfo=UTC)
    assert _resolve_run_at("+5m", now) == (now + timedelta(minutes=5)).isoformat()
    assert _resolve_run_at("+2h", now) == (now + timedelta(hours=2)).isoformat()


def test_resolve_run_at_absolute_iso_passthrough() -> None:
    now = datetime(2026, 5, 28, 12, 0, 0, tzinfo=UTC)
    iso = "2026-06-01T00:00:00+00:00"
    assert _resolve_run_at(iso, now) == iso


def test_resolve_run_at_invalid_returns_none() -> None:
    now = datetime(2026, 5, 28, 12, 0, 0, tzinfo=UTC)
    assert _resolve_run_at("", now) is None
    assert _resolve_run_at("garbage", now) is None
    assert _resolve_run_at("+30", now) is None  # missing unit
    assert _resolve_run_at("+30x", now) is None  # invalid unit


@pytest.fixture(autouse=True)
def _isolate_episodic_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the episodic DB at tmp so the host DB stays clean.

    ``initialize_db``'s ``db_path`` default is bound at module-import time,
    so it does NOT pick up a monkeypatched ``DB_PATH``. Pass the path
    explicitly to guarantee the schema lands at the temp file the test
    then reads.
    """
    from openexecutive.memory import episodic

    db_path = tmp_path / "episodic.db"
    monkeypatch.setattr(episodic, "DB_PATH", db_path)
    episodic.initialize_db(db_path)
    return db_path


def test_seed_scheduled_actions_inserts_rows_and_resolves_relative_run_at(
    tmp_path: Path, _isolate_episodic_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A memory.json with scheduled_actions must yield real rows in the
    table; the relative ``+30s`` sentinel must resolve into the future
    against load time.
    """
    # Pre-populate the name→id cache the loader normally builds during
    # _seed_people; episodic seeding reads this attribute to resolve
    # `assigned_to_person`.
    monkeypatch.setattr(
        fixture_loader._seed_people,
        "_name_to_id",
        {"Jordan Avery": 42},
        raising=False,
    )

    memory_path = tmp_path / "memory.json"
    memory_path.write_text(
        json.dumps(
            {
                "decisions": [],
                "initiatives": [],
                "advice_given": [],
                "scheduled_actions": [
                    {
                        "run_at": "+30s",
                        "kind": "dept_cadence",
                        "department": "engineering",
                        "channel": "email",
                        "assigned_to_person": "Jordan Avery",
                        "intent_text": "Send the eng digest.",
                    }
                ],
            }
        )
    )

    settings = type("S", (), {"episodic_db_path": _isolate_episodic_db})()
    before = datetime.now(UTC)
    counts = _seed_episodic_memory(memory_path, settings)
    after = datetime.now(UTC)

    assert counts["scheduled_actions"] == 1

    conn = sqlite3.connect(str(_isolate_episodic_db))
    try:
        row = conn.execute(
            "SELECT run_at, channel, intent_text, department, kind, "
            "assigned_to_person_id, status, attempts FROM scheduled_actions"
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    run_at_str, channel, intent, dept, kind, assignee_id, status, attempts = row

    # Relative sentinel resolved against load time — must land in the
    # ~30-second window between `before` and `after + 30s`.
    run_at = datetime.fromisoformat(run_at_str)
    assert before + timedelta(seconds=29) <= run_at <= after + timedelta(seconds=31)

    assert channel == "email"
    assert intent == "Send the eng digest."
    assert dept == "engineering"
    assert kind == "dept_cadence"
    assert assignee_id == 42  # resolved from the cache
    assert status == "pending"
    assert attempts == 0


def test_seed_scheduled_actions_skips_unparseable_run_at(
    tmp_path: Path, _isolate_episodic_db: Path
) -> None:
    """Rows with garbage run_at must be skipped, not crash the load."""
    memory_path = tmp_path / "memory.json"
    memory_path.write_text(
        json.dumps(
            {
                "decisions": [],
                "initiatives": [],
                "advice_given": [],
                "scheduled_actions": [
                    {"run_at": "garbage", "intent_text": "bad row"},
                    {"run_at": "+5s", "intent_text": "good row"},
                ],
            }
        )
    )

    settings = type("S", (), {"episodic_db_path": _isolate_episodic_db})()
    counts = _seed_episodic_memory(memory_path, settings)

    assert counts["scheduled_actions"] == 1

    conn = sqlite3.connect(str(_isolate_episodic_db))
    try:
        intents = [
            r[0]
            for r in conn.execute("SELECT intent_text FROM scheduled_actions").fetchall()
        ]
    finally:
        conn.close()
    assert intents == ["good row"]


def test_seed_scheduled_actions_empty_list_is_noop(
    tmp_path: Path, _isolate_episodic_db: Path
) -> None:
    """Other fixtures all ship empty scheduled_actions arrays; they must
    continue to load cleanly with zero new rows.
    """
    memory_path = tmp_path / "memory.json"
    memory_path.write_text(
        json.dumps(
            {
                "decisions": [],
                "initiatives": [],
                "advice_given": [],
                "scheduled_actions": [],
            }
        )
    )

    settings = type("S", (), {"episodic_db_path": _isolate_episodic_db})()
    counts = _seed_episodic_memory(memory_path, settings)
    assert counts["scheduled_actions"] == 0


def test_seed_scheduled_actions_unknown_assignee_resolves_to_null(
    tmp_path: Path, _isolate_episodic_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If ``assigned_to_person`` names someone who isn't in the people-name
    cache (typo, person renamed, fixture mismatch), the row must still
    insert with ``assigned_to_person_id = NULL`` — silently skipping the
    row would hide demo bugs and break the act/propose/escalate flow.
    """
    monkeypatch.setattr(
        fixture_loader._seed_people,
        "_name_to_id",
        {"Someone Else": 99},
        raising=False,
    )

    memory_path = tmp_path / "memory.json"
    memory_path.write_text(
        json.dumps(
            {
                "decisions": [],
                "initiatives": [],
                "advice_given": [],
                "scheduled_actions": [
                    {
                        "run_at": "+5s",
                        "kind": "ad_hoc",
                        "department": "strategy",
                        "channel": "discord_dm",
                        "assigned_to_person": "Nobody Real",
                        "intent_text": "test row",
                    }
                ],
            }
        )
    )
    settings = type("S", (), {"episodic_db_path": _isolate_episodic_db})()
    counts = _seed_episodic_memory(memory_path, settings)

    assert counts["scheduled_actions"] == 1

    conn = sqlite3.connect(str(_isolate_episodic_db))
    try:
        assignee = conn.execute(
            "SELECT assigned_to_person_id FROM scheduled_actions"
        ).fetchone()[0]
    finally:
        conn.close()
    assert assignee is None


def test_seed_scheduled_actions_persists_required_scope(
    tmp_path: Path, _isolate_episodic_db: Path
) -> None:
    """A row carrying ``required_scope`` must round-trip into the table
    and back through ``list_scheduled_actions`` so the runner can read
    it at gate time and route the proposal to the matching approver.
    """
    from openexecutive.memory.episodic import list_scheduled_actions

    memory_path = tmp_path / "memory.json"
    memory_path.write_text(
        json.dumps(
            {
                "decisions": [],
                "initiatives": [],
                "advice_given": [],
                "scheduled_actions": [
                    {
                        "run_at": "+5s",
                        "kind": "ad_hoc",
                        "department": "finance",
                        "channel": "discord_dm",
                        "required_scope": "spend_lt_10k",
                        "intent_text": "approve this",
                    },
                    {
                        "run_at": "+5s",
                        "kind": "ad_hoc",
                        "department": "engineering",
                        "channel": "discord_dm",
                        "intent_text": "no scope here",
                    },
                ],
            }
        )
    )
    settings = type("S", (), {"episodic_db_path": _isolate_episodic_db})()
    counts = _seed_episodic_memory(memory_path, settings)
    assert counts["scheduled_actions"] == 2

    actions = sorted(
        list_scheduled_actions(db_path=_isolate_episodic_db),
        key=lambda a: a.department,
    )
    eng, fin = actions[0], actions[1]
    assert fin.department == "finance"
    assert fin.required_scope == "spend_lt_10k"
    assert eng.department == "engineering"
    assert eng.required_scope is None


def test_seed_scheduled_actions_clears_table_before_insert(
    tmp_path: Path, _isolate_episodic_db: Path
) -> None:
    """Running the seeder twice must NOT accumulate rows — fixture loading
    is destructive by design, and stale prior actions in the queue would
    fire alongside the new demo and confuse the narrative.
    """
    memory_path = tmp_path / "memory.json"
    memory_path.write_text(
        json.dumps(
            {
                "decisions": [],
                "initiatives": [],
                "advice_given": [],
                "scheduled_actions": [
                    {
                        "run_at": "+5s",
                        "kind": "ad_hoc",
                        "channel": "discord_dm",
                        "intent_text": "first load",
                    }
                ],
            }
        )
    )
    settings = type("S", (), {"episodic_db_path": _isolate_episodic_db})()

    _seed_episodic_memory(memory_path, settings)

    memory_path.write_text(
        json.dumps(
            {
                "decisions": [],
                "initiatives": [],
                "advice_given": [],
                "scheduled_actions": [
                    {
                        "run_at": "+5s",
                        "kind": "ad_hoc",
                        "channel": "discord_dm",
                        "intent_text": "second load",
                    }
                ],
            }
        )
    )
    counts = _seed_episodic_memory(memory_path, settings)

    assert counts["scheduled_actions"] == 1

    conn = sqlite3.connect(str(_isolate_episodic_db))
    try:
        intents = [
            r[0]
            for r in conn.execute(
                "SELECT intent_text FROM scheduled_actions"
            ).fetchall()
        ]
    finally:
        conn.close()
    # Only the second-load row remains — first-load row was wiped.
    assert intents == ["second load"]
