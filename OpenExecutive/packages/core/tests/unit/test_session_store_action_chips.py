"""Action-chip persistence on chat_messages (improvement-plan #5).

Covers the round-trip, the no-chips path, the additive-migration idempotency,
and migrating a legacy DB whose chat_messages predates the action_chips column.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from openexecutive.memory import episodic, session_store

_CHIPS = [
    {"type": "action_taken", "tool": "send_slack_dm", "summary": "DM'd Alex", "iteration": 1},
    {"type": "action_taken", "tool": "schedule_followup", "summary": "Follow-up Fri", "iteration": 1},
]


def _fresh_db(tmp_path: Path) -> Path:
    db = tmp_path / "chat.db"
    episodic.initialize_db(db)
    return db


def test_action_chips_round_trip(tmp_path: Path) -> None:
    db = _fresh_db(tmp_path)
    session_store.create_session("s1", "t", "2026-01-01T00:00:00Z", db_path=db)
    session_store.save_message("s1", "user", "hi", db_path=db)
    session_store.save_message(
        "s1", "assistant", "done", db_path=db, action_chips=json.dumps(_CHIPS)
    )
    msgs = session_store.load_messages("s1", db_path=db)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert "actions" not in msgs[0]            # user message carries no chips
    assert msgs[1]["actions"] == _CHIPS        # assistant chips restored verbatim


def test_message_without_chips_has_no_actions_key(tmp_path: Path) -> None:
    db = _fresh_db(tmp_path)
    session_store.create_session("s2", "t", "2026-01-01T00:00:00Z", db_path=db)
    session_store.save_message("s2", "assistant", "no actions", db_path=db)
    msgs = session_store.load_messages("s2", db_path=db)
    assert msgs[0]["content"] == "no actions"
    assert "actions" not in msgs[0]


def test_empty_chip_list_persists_no_actions_key(tmp_path: Path) -> None:
    # The route passes None (not "[]") for empty turns; assert an explicit
    # empty JSON list also round-trips to "no actions" rather than [].
    db = _fresh_db(tmp_path)
    session_store.create_session("s3", "t", "2026-01-01T00:00:00Z", db_path=db)
    session_store.save_message(
        "s3", "assistant", "x", db_path=db, action_chips=json.dumps([])
    )
    msgs = session_store.load_messages("s3", db_path=db)
    assert "actions" not in msgs[0]


def test_migration_is_idempotent_and_adds_column(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    episodic.initialize_db(db)
    episodic.initialize_db(db)  # second boot must not raise (PRAGMA-guarded ALTER)
    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(chat_messages)")}
    conn.close()
    assert "action_chips" in cols


def test_legacy_db_without_column_is_migrated(tmp_path: Path) -> None:
    # Simulate a pre-existing DB whose chat_messages lacks action_chips.
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE sessions (session_id TEXT PRIMARY KEY, title TEXT, "
        "created_at TEXT, updated_at TEXT, caller_person_id INTEGER)"
    )
    conn.execute(
        "CREATE TABLE chat_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "session_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, "
        "created_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO chat_messages (session_id, role, content, created_at) "
        "VALUES ('sL', 'assistant', 'legacy', '2026-01-01T00:00:00Z')"
    )
    conn.commit()
    conn.close()

    episodic.initialize_db(db)  # adds action_chips via the additive ALTER

    msgs = session_store.load_messages("sL", db_path=db)
    assert msgs[0]["content"] == "legacy"
    assert "actions" not in msgs[0]  # legacy row: NULL chips -> no actions
    # And new writes carry chips fine on the migrated DB.
    session_store.save_message(
        "sL", "assistant", "new", db_path=db, action_chips=json.dumps(_CHIPS)
    )
    assert session_store.load_messages("sL", db_path=db)[1]["actions"] == _CHIPS
